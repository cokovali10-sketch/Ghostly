from __future__ import annotations

import hashlib
import logging
import math
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from .database import Database

logger = logging.getLogger("ghostly.ab_test")


class ABTestManager:
    """Manages A/B testing experiments, variant assignment, and statistical analysis."""

    def __init__(self, db: Database) -> None:
        self.db = db

    async def create_experiment(
        self,
        site_id: int,
        name: str,
        variants: list[dict[str, Any]],
        description: str = "",
        traffic_pct: float = 100.0,
    ) -> dict[str, Any]:
        if not variants or len(variants) < 2:
            raise ValueError("At least 2 variants are required")

        cursor = await self.db.db.execute(
            """INSERT INTO ab_experiments (site_id, name, description, traffic_pct)
               VALUES (?, ?, ?, ?)""",
            (site_id, name, description, traffic_pct),
        )
        await self.db.db.commit()
        experiment_id = cursor.lastrowid or 0

        total_weight = sum(v.get("weight", 1.0) for v in variants)
        if total_weight <= 0:
            total_weight = len(variants)

        variant_ids = []
        for idx, variant in enumerate(variants):
            weight = variant.get("weight", 1.0)
            is_control = 1 if idx == 0 else 0
            v_cursor = await self.db.db.execute(
                """INSERT INTO ab_variants (experiment_id, name, weight, is_control)
                   VALUES (?, ?, ?, ?)""",
                (experiment_id, variant.get("name", f"Variant {idx + 1}"), weight, is_control),
            )
            await self.db.db.commit()
            variant_ids.append(v_cursor.lastrowid or 0)

        logger.info("Created experiment %d for site %d: %s", experiment_id, site_id, name)

        return {
            "id": experiment_id,
            "site_id": site_id,
            "name": name,
            "description": description,
            "status": "draft",
            "traffic_pct": traffic_pct,
            "variants": [
                {
                    "id": vid,
                    "name": variants[i].get("name", f"Variant {i + 1}"),
                    "weight": variants[i].get("weight", 1.0),
                    "is_control": i == 0,
                }
                for i, vid in enumerate(variant_ids)
            ],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    async def get_experiments(self, site_id: int) -> list[dict[str, Any]]:
        experiments = await self.db._fetch_all(
            """SELECT id, site_id, name, description, status, traffic_pct, created_at, ended_at
               FROM ab_experiments WHERE site_id=? ORDER BY created_at DESC""",
            (site_id,),
        )
        for exp in experiments:
            exp["variants"] = await self._get_variants(exp["id"])
        return experiments

    async def get_experiment(self, experiment_id: int) -> dict[str, Any] | None:
        exp = await self.db._fetch_one(
            """SELECT id, site_id, name, description, status, traffic_pct, created_at, ended_at
               FROM ab_experiments WHERE id=?""",
            (experiment_id,),
        )
        if exp:
            exp["variants"] = await self._get_variants(experiment_id)
        return exp

    async def _get_variants(self, experiment_id: int) -> list[dict[str, Any]]:
        return await self.db._fetch_all(
            """SELECT id, experiment_id, name, weight, is_control, created_at
               FROM ab_variants WHERE experiment_id=? ORDER BY id""",
            (experiment_id,),
        )

    async def start_experiment(self, experiment_id: int) -> bool:
        result = await self.db.db.execute(
            "UPDATE ab_experiments SET status='running' WHERE id=? AND status='draft'",
            (experiment_id,),
        )
        await self.db.db.commit()
        return result.rowcount > 0

    async def stop_experiment(self, experiment_id: int) -> bool:
        result = await self.db.db.execute(
            """UPDATE ab_experiments SET status='completed', ended_at=datetime('now')
               WHERE id=? AND status='running'""",
            (experiment_id,),
        )
        await self.db.db.commit()
        return result.rowcount > 0

    async def delete_experiment(self, experiment_id: int) -> bool:
        await self.db.db.execute("DELETE FROM ab_conversions WHERE experiment_id=?", (experiment_id,))
        await self.db.db.execute("DELETE FROM ab_assignments WHERE experiment_id=?", (experiment_id,))
        await self.db.db.execute("DELETE FROM ab_variants WHERE experiment_id=?", (experiment_id,))
        result = await self.db.db.execute("DELETE FROM ab_experiments WHERE id=?", (experiment_id,))
        await self.db.db.commit()
        return result.rowcount > 0

    def _get_visitor_variant_hash(self, experiment_id: int, visitor_id: str) -> int:
        raw = f"ghostly-ab-{experiment_id}-{visitor_id}"
        hash_val = int(hashlib.sha256(raw.encode()).hexdigest(), 16)
        return hash_val % 10000

    async def assign_visitor(
        self, experiment_id: int, visitor_id: str
    ) -> dict[str, Any] | None:
        existing = await self.db._fetch_one(
            """SELECT a.variant_id, v.name AS variant_name, v.is_control
               FROM ab_assignments a
               JOIN ab_variants v ON a.variant_id = v.id
               WHERE a.experiment_id=? AND a.visitor_id=?""",
            (experiment_id, visitor_id),
        )
        if existing:
            return {
                "variant_id": existing["variant_id"],
                "variant_name": existing["variant_name"],
                "is_control": bool(existing["is_control"]),
                "is_new_assignment": False,
            }

        experiment = await self.get_experiment(experiment_id)
        if not experiment or experiment["status"] != "running":
            return None

        variants = experiment["variants"]
        if not variants:
            return None

        total_weight = sum(v["weight"] for v in variants)
        if total_weight <= 0:
            return None

        hash_val = self._get_visitor_variant_hash(experiment_id, visitor_id)
        normalized = (hash_val / 10000) * total_weight

        cumulative = 0.0
        selected_variant = variants[0]
        for variant in variants:
            cumulative += variant["weight"]
            if normalized < cumulative:
                selected_variant = variant
                break

        await self.db.db.execute(
            """INSERT OR IGNORE INTO ab_assignments (experiment_id, variant_id, visitor_id)
               VALUES (?, ?, ?)""",
            (experiment_id, selected_variant["id"], visitor_id),
        )
        await self.db.db.commit()

        return {
            "variant_id": selected_variant["id"],
            "variant_name": selected_variant["name"],
            "is_control": bool(selected_variant["is_control"]),
            "is_new_assignment": True,
        }

    async def track_conversion(
        self,
        experiment_id: int,
        visitor_id: str,
        event_name: str = "conversion",
        value: float = 0.0,
    ) -> dict[str, Any] | None:
        assignment = await self.db._fetch_one(
            "SELECT variant_id FROM ab_assignments WHERE experiment_id=? AND visitor_id=?",
            (experiment_id, visitor_id),
        )
        if not assignment:
            return None

        cursor = await self.db.db.execute(
            """INSERT INTO ab_conversions (experiment_id, variant_id, visitor_id, event_name, value)
               VALUES (?, ?, ?, ?, ?)""",
            (experiment_id, assignment["variant_id"], visitor_id, event_name, value),
        )
        await self.db.db.commit()

        return {
            "conversion_id": cursor.lastrowid or 0,
            "experiment_id": experiment_id,
            "variant_id": assignment["variant_id"],
            "event_name": event_name,
            "value": value,
        }

    async def get_experiment_stats(
        self, experiment_id: int, days: int = 30
    ) -> dict[str, Any]:
        experiment = await self.get_experiment(experiment_id)
        if not experiment:
            return {}

        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        variants = experiment["variants"]

        variant_stats = []
        for variant in variants:
            assignments = await self.db._fetch_one(
                """SELECT COUNT(*) AS count FROM ab_assignments
                   WHERE experiment_id=? AND variant_id=? AND assigned_at>=?""",
                (experiment_id, variant["id"], since),
            )
            visitors = assignments["count"] if assignments else 0

            conversions = await self.db._fetch_one(
                """SELECT COUNT(*) AS count, COALESCE(SUM(value), 0) AS total_value
                   FROM ab_conversions
                   WHERE experiment_id=? AND variant_id=? AND created_at>=?""",
                (experiment_id, variant["id"], since),
            )
            conv_count = conversions["count"] if conversions else 0
            total_value = conversions["total_value"] if conversions else 0
            conversion_rate = round(conv_count / visitors * 100, 2) if visitors else 0
            avg_value = round(total_value / conv_count, 2) if conv_count else 0

            unique_converters = await self.db._fetch_one(
                """SELECT COUNT(DISTINCT visitor_id) AS count
                   FROM ab_conversions
                   WHERE experiment_id=? AND variant_id=? AND created_at>=?""",
                (experiment_id, variant["id"], since),
            )
            unique_conv = unique_converters["count"] if unique_converters else 0

            variant_stats.append({
                "variant_id": variant["id"],
                "variant_name": variant["name"],
                "is_control": bool(variant["is_control"]),
                "visitors": visitors,
                "conversions": conv_count,
                "unique_converters": unique_conv,
                "conversion_rate": conversion_rate,
                "total_value": total_value,
                "avg_value_per_conversion": avg_value,
            })

        control = next((v for v in variant_stats if v["is_control"]), None)
        for vs in variant_stats:
            if control and not vs["is_control"]:
                if control["conversion_rate"] > 0:
                    lift = round(
                        (vs["conversion_rate"] - control["conversion_rate"])
                        / control["conversion_rate"] * 100,
                        2,
                    )
                else:
                    lift = 0.0
                vs["lift_vs_control_pct"] = lift
            else:
                vs["lift_vs_control_pct"] = 0.0

        return {
            "experiment": experiment,
            "period_days": days,
            "variants": variant_stats,
        }

    def _calculate_z_score(
        self, conversions_a: int, visitors_a: int, conversions_b: int, visitors_b: int
    ) -> float:
        if visitors_a == 0 or visitors_b == 0:
            return 0.0
        p_a = conversions_a / visitors_a
        p_b = conversions_b / visitors_b
        p_pool = (conversions_a + conversions_b) / (visitors_a + visitors_b)
        if p_pool == 0 or p_pool == 1:
            return 0.0
        se = math.sqrt(
            p_pool * (1 - p_pool) * (1 / visitors_a + 1 / visitors_b)
        )
        if se == 0:
            return 0.0
        return (p_b - p_a) / se

    def _z_score_to_p_value(self, z_score: float) -> float:
        abs_z = abs(z_score)
        if abs_z > 8:
            return 0.0
        t = 1.0 / (1.0 + 0.2316419 * abs_z)
        d = 0.3989422804014327 * math.exp(-abs_z * abs_z / 2.0)
        p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274))))
        return 2.0 * p

    async def get_statistical_significance(
        self, experiment_id: int, days: int = 30
    ) -> dict[str, Any]:
        stats = await self.get_experiment_stats(experiment_id, days)
        if not stats or not stats.get("variants"):
            return {"is_significant": False, "confidence": 0, "variants": []}

        control = next((v for v in stats["variants"] if v["is_control"]), None)
        if not control:
            return {"is_significant": False, "confidence": 0, "variants": []}

        results = []
        any_significant = False

        for variant in stats["variants"]:
            if variant["is_control"]:
                results.append({
                    "variant_name": variant["variant_name"],
                    "z_score": 0.0,
                    "p_value": 1.0,
                    "is_significant": False,
                    "confidence": 0,
                })
                continue

            z_score = self._calculate_z_score(
                control["conversions"], control["visitors"],
                variant["conversions"], variant["visitors"],
            )
            p_value = self._z_score_to_p_value(z_score)
            confidence = round((1 - p_value) * 100, 2)
            is_significant = p_value < 0.05

            if is_significant:
                any_significant = True

            results.append({
                "variant_name": variant["variant_name"],
                "z_score": round(z_score, 4),
                "p_value": round(p_value, 6),
                "is_significant": is_significant,
                "confidence": confidence,
            })

        return {
            "experiment_id": experiment_id,
            "period_days": days,
            "is_significant": any_significant,
            "significance_level": 0.05,
            "variants": results,
        }

    async def get_experiment_summary(self, site_id: int, days: int = 30) -> dict[str, Any]:
        experiments = await self.get_experiments(site_id)
        active = [e for e in experiments if e["status"] == "running"]
        completed = [e for e in experiments if e["status"] == "completed"]
        draft = [e for e in experiments if e["status"] == "draft"]

        return {
            "total_experiments": len(experiments),
            "active": len(active),
            "completed": len(completed),
            "draft": len(draft),
            "experiments": [
                {
                    "id": e["id"],
                    "name": e["name"],
                    "status": e["status"],
                    "variant_count": len(e.get("variants", [])),
                    "created_at": e["created_at"],
                }
                for e in experiments
            ],
        }