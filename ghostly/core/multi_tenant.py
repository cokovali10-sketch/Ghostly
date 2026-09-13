from __future__ import annotations

import hashlib
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from ghostly.core.database import Database

logger = logging.getLogger("ghostly.multi_tenant")

PLAN_LIMITS = {
    "free": {
        "max_sites": 3,
        "max_pageviews_monthly": 100_000,
        "max_team_members": 2,
        "max_api_keys": 5,
        "retention_days": 30,
        "realtime_enabled": False,
        "heatmaps_enabled": False,
        "ab_testing_enabled": False,
        "exports_enabled": False,
        "email_reports_enabled": False,
        "webhooks_enabled": False,
        "custom_themes": False,
        "priority_support": False,
    },
    "pro": {
        "max_sites": 25,
        "max_pageviews_monthly": 5_000_000,
        "max_team_members": 15,
        "max_api_keys": 50,
        "retention_days": 365,
        "realtime_enabled": True,
        "heatmaps_enabled": True,
        "ab_testing_enabled": True,
        "exports_enabled": True,
        "email_reports_enabled": True,
        "webhooks_enabled": True,
        "custom_themes": True,
        "priority_support": False,
    },
    "enterprise": {
        "max_sites": 999,
        "max_pageviews_monthly": 999_999_999,
        "max_team_members": 999,
        "max_api_keys": 999,
        "retention_days": 999,
        "realtime_enabled": True,
        "heatmaps_enabled": True,
        "ab_testing_enabled": True,
        "exports_enabled": True,
        "email_reports_enabled": True,
        "webhooks_enabled": True,
        "custom_themes": True,
        "priority_support": True,
    },
}

PLAN_PRICING = {
    "free": {"monthly": 0, "yearly": 0},
    "pro": {"monthly": 29, "yearly": 290},
    "enterprise": {"monthly": 199, "yearly": 1990},
}


class TenantError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        self.message = message
        self.status = status
        super().__init__(message)


class TenantManager:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def create_organization(
        self,
        name: str,
        owner_user_id: int,
        plan: str = "free",
        subdomain: str | None = None,
    ) -> dict[str, Any]:
        if plan not in PLAN_LIMITS:
            raise TenantError(f"Invalid plan: {plan}")

        if not subdomain:
            subdomain = self._generate_subdomain(name)
        else:
            subdomain = subdomain.lower().strip()
            if not subdomain.isalnum() and not all(c.isalnum() or c == "-" for c in subdomain):
                raise TenantError("Subdomain must contain only alphanumeric characters and hyphens")

        existing = await self.db._fetch_one(
            "SELECT id FROM organizations WHERE subdomain=?", (subdomain,)
        )
        if existing:
            raise TenantError("Subdomain already taken", 409)

        plan_config = PLAN_LIMITS[plan]
        cursor = await self.db.db.execute(
            """INSERT INTO organizations (name, plan, subdomain, owner_user_id,
               max_sites, max_pageviews_monthly, max_team_members, max_api_keys,
               retention_days, settings)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                name,
                plan,
                subdomain,
                owner_user_id,
                plan_config["max_sites"],
                plan_config["max_pageviews_monthly"],
                plan_config["max_team_members"],
                plan_config["max_api_keys"],
                plan_config["retention_days"],
                json.dumps({"features": plan_config}),
            ),
        )
        await self.db.db.commit()
        org_id = cursor.lastrowid or 0

        await self.db.db.execute(
            """INSERT INTO org_members (org_id, user_id, role, invited_by)
               VALUES (?, ?, 'owner', ?)""",
            (org_id, owner_user_id, owner_user_id),
        )
        await self.db.db.commit()

        await self.db.log_audit(
            owner_user_id, "org_create", "organization",
            {"org_id": org_id, "name": name, "plan": plan},
        )

        return await self.get_organization(org_id)

    async def get_organization(self, org_id: int) -> dict[str, Any] | None:
        org = await self.db._fetch_one(
            "SELECT * FROM organizations WHERE id=?", (org_id,)
        )
        if org:
            org["settings"] = json.loads(org.get("settings") or "{}")
        return org

    async def get_organization_by_subdomain(self, subdomain: str) -> dict[str, Any] | None:
        org = await self.db._fetch_one(
            "SELECT * FROM organizations WHERE subdomain=? AND is_active=1",
            (subdomain,),
        )
        if org:
            org["settings"] = json.loads(org.get("settings") or "{}")
        return org

    async def update_organization(self, org_id: int, **kwargs: Any) -> bool:
        allowed = {"name", "plan", "subdomain", "is_active", "settings", "billing_email",
                    "max_sites", "max_pageviews_monthly", "max_team_members", "max_api_keys",
                    "retention_days"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return False
        if "settings" in updates and isinstance(updates["settings"], dict):
            updates["settings"] = json.dumps(updates["settings"])
        set_clause = ", ".join(f"{k}=?" for k in updates)
        values = list(updates.values()) + [org_id]
        await self.db.db.execute(f"UPDATE organizations SET {set_clause} WHERE id=?", values)
        await self.db.db.commit()
        return True

    async def delete_organization(self, org_id: int) -> bool:
        result = await self.db.db.execute("UPDATE organizations SET is_active=0 WHERE id=?", (org_id,))
        await self.db.db.commit()
        return result.rowcount > 0

    async def list_organizations(self, limit: int = 100) -> list[dict[str, Any]]:
        orgs = await self.db._fetch_all(
            "SELECT * FROM organizations WHERE is_active=1 ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        for org in orgs:
            org["settings"] = json.loads(org.get("settings") or "{}")
        return orgs

    # ── Team Members ─────────────────────────────────────────────────────

    async def add_member(
        self,
        org_id: int,
        user_id: int,
        role: str = "viewer",
        invited_by: int | None = None,
    ) -> dict[str, Any]:
        if role not in ("owner", "admin", "editor", "viewer"):
            raise TenantError("Invalid role")

        org = await self.get_organization(org_id)
        if not org:
            raise TenantError("Organization not found", 404)

        member_count = await self.db._fetch_one(
            "SELECT COUNT(*) as total FROM org_members WHERE org_id=?", (org_id,)
        )
        count = member_count["total"] if member_count else 0
        if count >= org.get("max_team_members", 2):
            raise TenantError("Team member limit reached for your plan", 403)

        existing = await self.db._fetch_one(
            "SELECT id FROM org_members WHERE org_id=? AND user_id=?", (org_id, user_id)
        )
        if existing:
            raise TenantError("User is already a member", 409)

        cursor = await self.db.db.execute(
            """INSERT INTO org_members (org_id, user_id, role, invited_by)
               VALUES (?, ?, ?, ?)""",
            (org_id, user_id, role, invited_by),
        )
        await self.db.db.commit()

        await self.db.log_audit(
            invited_by, "member_add", "organization",
            {"org_id": org_id, "user_id": user_id, "role": role},
        )

        return await self.get_member(org_id, user_id)

    async def get_member(self, org_id: int, user_id: int) -> dict[str, Any] | None:
        return await self.db._fetch_one(
            """SELECT m.id, m.org_id, m.user_id, m.role, m.joined_at, m.invited_by,
                      u.email as user_email
               FROM org_members m
               LEFT JOIN users u ON m.user_id = u.id
               WHERE m.org_id=? AND m.user_id=?""",
            (org_id, user_id),
        )

    async def get_members(self, org_id: int) -> list[dict[str, Any]]:
        return await self.db._fetch_all(
            """SELECT m.id, m.org_id, m.user_id, m.role, m.joined_at, m.invited_by,
                      u.email as user_email
               FROM org_members m
               LEFT JOIN users u ON m.user_id = u.id
               WHERE m.org_id=?
               ORDER BY m.joined_at""",
            (org_id,),
        )

    async def update_member_role(self, org_id: int, user_id: int, role: str) -> bool:
        if role not in ("admin", "editor", "viewer"):
            raise TenantError("Invalid role")
        result = await self.db.db.execute(
            "UPDATE org_members SET role=? WHERE org_id=? AND user_id=?",
            (role, org_id, user_id),
        )
        await self.db.db.commit()
        return result.rowcount > 0

    async def remove_member(self, org_id: int, user_id: int) -> bool:
        member = await self.get_member(org_id, user_id)
        if member and member["role"] == "owner":
            raise TenantError("Cannot remove the organization owner")
        result = await self.db.db.execute(
            "DELETE FROM org_members WHERE org_id=? AND user_id=?",
            (org_id, user_id),
        )
        await self.db.db.commit()
        return result.rowcount > 0

    async def get_user_organizations(self, user_id: int) -> list[dict[str, Any]]:
        return await self.db._fetch_all(
            """SELECT o.*, m.role as member_role
               FROM organizations o
               INNER JOIN org_members m ON o.id = m.org_id
               WHERE m.user_id=? AND o.is_active=1
               ORDER BY o.created_at DESC""",
            (user_id,),
        )

    async def check_user_role(self, org_id: int, user_id: int, required_roles: list[str] | None = None) -> str | None:
        if required_roles is None:
            required_roles = ["owner", "admin", "editor", "viewer"]
        member = await self.get_member(org_id, user_id)
        if not member:
            return None
        if member["role"] in required_roles:
            return member["role"]
        return None

    # ── Sites under org ──────────────────────────────────────────────────

    async def get_org_sites(self, org_id: int) -> list[dict[str, Any]]:
        return await self.db._fetch_all(
            """SELECT s.id, s.domain, s.name, s.created_at, s.is_active
               FROM sites s
               INNER JOIN org_sites os ON s.id = os.site_id
               WHERE os.org_id=? AND s.is_active=1
               ORDER BY s.created_at DESC""",
            (org_id,),
        )

    async def add_site_to_org(self, org_id: int, site_id: int) -> bool:
        org = await self.get_organization(org_id)
        if not org:
            raise TenantError("Organization not found", 404)

        site_count = await self.db._fetch_one(
            "SELECT COUNT(*) as total FROM org_sites WHERE org_id=?", (org_id,)
        )
        count = site_count["total"] if site_count else 0
        if count >= org.get("max_sites", 3):
            raise TenantError("Site limit reached for your plan", 403)

        existing = await self.db._fetch_one(
            "SELECT id FROM org_sites WHERE org_id=? AND site_id=?", (org_id, site_id)
        )
        if existing:
            return True

        await self.db.db.execute(
            "INSERT INTO org_sites (org_id, site_id) VALUES (?, ?)",
            (org_id, site_id),
        )
        await self.db.db.commit()
        return True

    async def remove_site_from_org(self, org_id: int, site_id: int) -> bool:
        result = await self.db.db.execute(
            "DELETE FROM org_sites WHERE org_id=? AND site_id=?",
            (org_id, site_id),
        )
        await self.db.db.commit()
        return result.rowcount > 0

    # ── Usage & Quotas ───────────────────────────────────────────────────

    async def get_org_usage(self, org_id: int) -> dict[str, Any]:
        org = await self.get_organization(org_id)
        if not org:
            return {}

        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()

        site_ids_rows = await self.db._fetch_all(
            "SELECT site_id FROM org_sites WHERE org_id=?", (org_id,)
        )
        site_ids = [r["site_id"] for r in site_ids_rows]

        pageviews_this_month = 0
        if site_ids:
            placeholders = ",".join("?" * len(site_ids))
            pv = await self.db._fetch_one(
                f"SELECT COUNT(*) as total FROM pageviews WHERE site_id IN ({placeholders}) AND created_at>=?",
                (*site_ids, month_start),
            )
            pageviews_this_month = pv["total"] if pv else 0

        site_count = len(site_ids)
        member_count_row = await self.db._fetch_one(
            "SELECT COUNT(*) as total FROM org_members WHERE org_id=?", (org_id,)
        )
        member_count = member_count_row["total"] if member_count_row else 0

        api_keys_row = await self.db._fetch_one(
            "SELECT COUNT(*) as total FROM user_api_keys WHERE user_id IN (SELECT user_id FROM org_members WHERE org_id=?)",
            (org_id,),
        )
        api_key_count = api_keys_row["total"] if api_keys_row else 0

        return {
            "plan": org.get("plan", "free"),
            "sites_used": site_count,
            "max_sites": org.get("max_sites", 3),
            "team_members_used": member_count,
            "max_team_members": org.get("max_team_members", 2),
            "pageviews_this_month": pageviews_this_month,
            "max_pageviews_monthly": org.get("max_pageviews_monthly", 100_000),
            "api_keys_used": api_key_count,
            "max_api_keys": org.get("max_api_keys", 5),
            "pageview_usage_pct": round(
                pageviews_this_month / max(org.get("max_pageviews_monthly", 1), 1) * 100, 1
            ),
        }

    async def check_quota(self, org_id: int, quota_type: str, amount: int = 1) -> bool:
        usage = await self.get_org_usage(org_id)
        if not usage:
            return False

        checks = {
            "site": ("sites_used", "max_sites"),
            "pageview": ("pageviews_this_month", "max_pageviews_monthly"),
            "team_member": ("team_members_used", "max_team_members"),
            "api_key": ("api_keys_used", "max_api_keys"),
        }

        if quota_type not in checks:
            return True

        used_key, max_key = checks[quota_type]
        used = usage.get(used_key, 0)
        limit = usage.get(max_key, 0)
        return (used + amount) <= limit

    async def record_usage(self, org_id: int, usage_type: str, amount: int = 1) -> None:
        await self.db.db.execute(
            """INSERT INTO usage_records (org_id, usage_type, amount, recorded_at)
               VALUES (?, ?, ?, datetime('now'))""",
            (org_id, usage_type, amount),
        )
        await self.db.db.commit()

    async def get_usage_records(
        self, org_id: int, usage_type: str | None = None, days: int = 30
    ) -> list[dict[str, Any]]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        if usage_type:
            return await self.db._fetch_all(
                """SELECT id, org_id, usage_type, amount, recorded_at
                   FROM usage_records WHERE org_id=? AND usage_type=? AND recorded_at>=?
                   ORDER BY recorded_at DESC""",
                (org_id, usage_type, since),
            )
        return await self.db._fetch_all(
            """SELECT id, org_id, usage_type, amount, recorded_at
               FROM usage_records WHERE org_id=? AND recorded_at>=?
               ORDER BY recorded_at DESC""",
            (org_id, since),
        )

    # ── Billing ──────────────────────────────────────────────────────────

    async def create_invoice(
        self,
        org_id: int,
        amount: float,
        description: str,
        billing_period: str = "monthly",
    ) -> dict[str, Any]:
        org = await self.get_organization(org_id)
        if not org:
            raise TenantError("Organization not found", 404)

        invoice_id = secrets.token_hex(8)
        cursor = await self.db.db.execute(
            """INSERT INTO invoices (org_id, invoice_id, amount, currency, description,
               billing_period, status, created_at)
               VALUES (?, ?, ?, 'USD', ?, ?, 'pending', datetime('now'))""",
            (org_id, invoice_id, amount, description, billing_period),
        )
        await self.db.db.commit()

        return await self.db._fetch_one(
            "SELECT * FROM invoices WHERE id=?", (cursor.lastrowid,)
        )

    async def get_invoices(self, org_id: int, limit: int = 50) -> list[dict[str, Any]]:
        return await self.db._fetch_all(
            """SELECT * FROM invoices WHERE org_id=? ORDER BY created_at DESC LIMIT ?""",
            (org_id, limit),
        )

    async def update_invoice_status(self, invoice_id: int, status: str) -> bool:
        if status not in ("pending", "paid", "failed", "refunded", "cancelled"):
            raise TenantError("Invalid invoice status")
        result = await self.db.db.execute(
            "UPDATE invoices SET status=?, updated_at=datetime('now') WHERE id=?",
            (status, invoice_id),
        )
        await self.db.db.commit()
        return result.rowcount > 0

    # ── Subdomain Routing ────────────────────────────────────────────────

    async def resolve_subdomain(self, hostname: str) -> dict[str, Any] | None:
        parts = hostname.split(".")
        if len(parts) < 3:
            return None
        subdomain = parts[0]
        return await self.get_organization_by_subdomain(subdomain)

    async def validate_subdomain(self, subdomain: str) -> dict[str, Any]:
        subdomain = subdomain.lower().strip()
        if len(subdomain) < 3:
            return {"valid": False, "error": "Subdomain must be at least 3 characters"}
        if len(subdomain) > 63:
            return {"valid": False, "error": "Subdomain must be at most 63 characters"}
        if not subdomain[0].isalpha():
            return {"valid": False, "error": "Subdomain must start with a letter"}
        if not all(c.isalnum() or c == "-" for c in subdomain):
            return {"valid": False, "error": "Only alphanumeric characters and hyphens allowed"}
        if "--" in subdomain:
            return {"valid": False, "error": "Cannot contain consecutive hyphens"}

        reserved = {"www", "api", "admin", "mail", "ftp", "ns1", "ns2", "smtp", "pop",
                     "imap", "ghostly", "app", "dashboard", "status", "docs", "support"}
        if subdomain in reserved:
            return {"valid": False, "error": "This subdomain is reserved"}

        existing = await self.get_organization_by_subdomain(subdomain)
        if existing:
            return {"valid": False, "error": "Subdomain already taken"}

        return {"valid": True, "subdomain": subdomain}

    # ── Plan Management ──────────────────────────────────────────────────

    async def upgrade_plan(self, org_id: int, new_plan: str) -> dict[str, Any]:
        if new_plan not in PLAN_LIMITS:
            raise TenantError("Invalid plan")

        org = await self.get_organization(org_id)
        if not org:
            raise TenantError("Organization not found", 404)

        new_config = PLAN_LIMITS[new_plan]
        await self.update_organization(
            org_id,
            plan=new_plan,
            max_sites=new_config["max_sites"],
            max_pageviews_monthly=new_config["max_pageviews_monthly"],
            max_team_members=new_config["max_team_members"],
            max_api_keys=new_config["max_api_keys"],
            retention_days=new_config["retention_days"],
            settings={"features": new_config},
        )

        await self.db.log_audit(
            org.get("owner_user_id"), "plan_upgrade", "organization",
            {"org_id": org_id, "old_plan": org.get("plan"), "new_plan": new_plan},
        )

        return await self.get_organization(org_id)

    async def get_plan_features(self, plan: str) -> dict[str, Any]:
        if plan not in PLAN_LIMITS:
            raise TenantError("Invalid plan")
        return {
            "plan": plan,
            "limits": PLAN_LIMITS[plan],
            "pricing": PLAN_PRICING[plan],
        }

    def get_plan_limits(self, plan: str) -> dict[str, Any]:
        return PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])

    def _generate_subdomain(self, name: str) -> str:
        import re
        sub = re.sub(r"[^a-z0-9]", "", name.lower().replace(" ", ""))
        if not sub or not sub[0].isalpha():
            sub = "org" + sub
        return sub[:63]
