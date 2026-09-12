from __future__ import annotations

import asyncio
import gzip
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .database import Database

logger = logging.getLogger("ghostly.backup")

BACKUP_DIR = Path(__file__).parent.parent.parent / "backups"


class BackupManager:
    """Backs up and restores the SQLite database with optional gzip compression."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self._backup_dir = BACKUP_DIR
        self._backup_dir.mkdir(parents=True, exist_ok=True)

    @property
    def backup_dir(self) -> Path:
        return self._backup_dir

    async def create_backup(
        self,
        *,
        name: str | None = None,
        compress: bool = True,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        if name is None:
            name = now.strftime("ghostly_%Y%m%d_%H%M%S")

        db_path = self.db.db_path
        if not db_path.exists():
            raise FileNotFoundError(f"Database file not found: {db_path}")

        if compress:
            dest = self._backup_dir / f"{name}.db.gz"
            with open(db_path, "rb") as f_in:
                with gzip.open(dest, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
        else:
            dest = self._backup_dir / f"{name}.db"
            shutil.copy2(str(db_path), str(dest))

        size = dest.stat().st_size
        logger.info("Backup created: %s (%d bytes)", dest.name, size)

        await self.db.db.execute(
            """INSERT INTO backups (filename, original_size, compressed_size, compress, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (dest.name, db_path.stat().st_size, size, compress, now.isoformat()),
        )
        await self.db.db.commit()

        return {
            "filename": dest.name,
            "path": str(dest),
            "original_size": db_path.stat().st_size,
            "compressed_size": size,
            "compressed": compress,
            "created_at": now.isoformat(),
        }

    async def restore_backup(self, filename: str) -> dict[str, Any]:
        backup_path = self._backup_dir / filename
        if not backup_path.exists():
            raise FileNotFoundError(f"Backup not found: {backup_path}")

        db_path = self.db.db_path
        temp_path = db_path.with_suffix(".db.restoring")

        try:
            if filename.endswith(".gz"):
                with gzip.open(backup_path, "rb") as f_in:
                    with open(temp_path, "wb") as f_out:
                        shutil.copyfileobj(f_in, f_out)
            else:
                shutil.copy2(str(backup_path), str(temp_path))

            await self.db.close()

            shutil.move(str(temp_path), str(db_path))

            await self.db.connect()
            await self.db.init_db()

            logger.info("Restored database from %s", filename)
            return {
                "ok": True,
                "filename": filename,
                "restored_at": datetime.now(timezone.utc).isoformat(),
            }

        except Exception as exc:
            logger.error("Restore failed: %s", exc)
            if temp_path.exists():
                temp_path.unlink()
            try:
                await self.db.connect()
            except Exception:
                pass
            raise

    async def list_backups(self) -> list[dict[str, Any]]:
        rows = await self.db._fetch_all(
            "SELECT id, filename, original_size, compressed_size, compress, created_at FROM backups ORDER BY created_at DESC"
        )
        for row in rows:
            path = self._backup_dir / row["filename"]
            row["exists"] = path.exists()
            row["path"] = str(path)
        return rows

    async def delete_backup(self, filename: str) -> bool:
        backup_path = self._backup_dir / filename
        deleted_file = False
        if backup_path.exists():
            backup_path.unlink()
            deleted_file = True

        result = await self.db.db.execute("DELETE FROM backups WHERE filename=?", (filename,))
        await self.db.db.commit()
        return deleted_file or result.rowcount > 0

    async def prune_old_backups(self, keep_count: int = 10) -> int:
        rows = await self.db._fetch_all(
            "SELECT id, filename FROM backups ORDER BY created_at DESC"
        )

        if len(rows) <= keep_count:
            return 0

        to_delete = rows[keep_count:]
        deleted = 0

        for row in to_delete:
            backup_path = self._backup_dir / row["filename"]
            if backup_path.exists():
                backup_path.unlink()
            await self.db.db.execute("DELETE FROM backups WHERE id=?", (row["id"],))
            deleted += 1

        await self.db.db.commit()
        logger.info("Pruned %d old backups", deleted)
        return deleted

    async def get_backup_info(self, filename: str) -> dict[str, Any] | None:
        row = await self.db._fetch_one(
            "SELECT id, filename, original_size, compressed_size, compress, created_at FROM backups WHERE filename=?",
            (filename,),
        )
        if not row:
            return None
        path = self._backup_dir / filename
        row["exists"] = path.exists()
        row["path"] = str(path)
        return row
