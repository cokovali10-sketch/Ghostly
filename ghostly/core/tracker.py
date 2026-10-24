from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from .database import Database

# ── user-agent patterns ──────────────────────────────────────────────────

_BROWSER_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Edge", re.compile(r"Edg(?:e|A|iOS)?/(\d+)")),
    ("Chrome", re.compile(r"(?:Chrome|CriOS)/(\d+)")),
    ("Firefox", re.compile(r"(?:Firefox|FxiOS)/(\d+)")),
    ("Safari", re.compile(r"Version/(\d+).+Safari")),
    ("Opera", re.compile(r"(?:OPR|Opera)/(\d+)")),
    ("Samsung", re.compile(r"SamsungBrowser/(\d+)")),
    ("UC Browser", re.compile(r"UCBrowser/(\d+)")),
    ("IE", re.compile(r"MSIE (\d+)|Trident/.*rv:(\d+)")),
]

_OS_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Windows", re.compile(r"Windows NT 10\.0|Windows 10")),
    ("macOS", re.compile(r"Mac OS X (\d+[._]\d+)")),
    ("iOS", re.compile(r"iPhone OS (\d+[._]\d+)|iPad.*OS (\d+[._]\d+)")),
    ("Android", re.compile(r"Android (\d+[\.\d]*)")),
    ("Linux", re.compile(r"Linux(?!.*Android)")),
    ("ChromeOS", re.compile(r"CrOS")),
]

_DEVICE_KEYWORDS: dict[str, list[str]] = {
    "mobile": ["Mobile", "Android", "iPhone", "Windows Phone", "BlackBerry", "Opera Mini"],
    "tablet": ["iPad", "Tablet", "Kindle", "Silk"],
    "tv": ["SmartTV", "TV", "AppleTV", "Roku", "Chromecast"],
    "console": ["PlayStation", "Xbox", "Nintendo"],
}

# ── country detection (common CIDR → country) ───────────────────────────
# Lightweight mapping for the most common public ranges.
# For full accuracy, ship a MaxMind GeoLite2-Country mmdb.
_COUNTRY_BLOCKS: list[tuple[str, str]] = [
    ("2.", "US"), ("3.", "US"), ("4.", "US"), ("5.", "US"), ("6.", "US"),
    ("7.", "US"), ("8.", "US"), ("9.", "US"), ("11.", "US"), ("12.", "US"),
    ("13.", "US"), ("14.", "US"), ("15.", "US"), ("16.", "US"), ("17.", "US"),
    ("18.", "US"), ("19.", "US"), ("20.", "US"), ("21.", "US"), ("22.", "US"),
    ("23.", "US"), ("24.", "US"), ("25.", "US"), ("26.", "US"), ("27.", "US"),
    ("28.", "US"), ("29.", "US"), ("30.", "US"), ("31.", "US"), ("32.", "US"),
    ("33.", "FR"), ("34.", "US"), ("35.", "US"), ("36.", "AU"), ("37.", "FR"),
    ("38.", "US"), ("39.", "US"), ("40.", "US"), ("41.", "ZA"), ("42.", "US"),
    ("43.", "JP"), ("44.", "GB"), ("45.", "US"), ("46.", "RU"), ("47.", "US"),
    ("48.", "US"), ("49.", "DE"), ("50.", "US"), ("51.", "US"), ("52.", "US"),
    ("53.", "DE"), ("54.", "US"), ("55.", "US"), ("56.", "US"), ("57.", "US"),
    ("58.", "CN"), ("59.", "CN"), ("60.", "CN"), ("61.", "AU"), ("62.", "DE"),
    ("63.", "US"), ("64.", "US"), ("65.", "US"), ("66.", "US"), ("67.", "US"),
    ("68.", "US"), ("69.", "US"), ("70.", "US"), ("71.", "US"), ("72.", "US"),
    ("73.", "US"), ("74.", "US"), ("75.", "US"), ("76.", "US"), ("77.", "US"),
    ("78.", "NL"), ("79.", "DE"), ("80.", "GB"), ("81.", "JP"), ("82.", "DE"),
    ("83.", "FR"), ("84.", "DE"), ("85.", "US"), ("86.", "CN"), ("87.", "NL"),
    ("88.", "DE"), ("89.", "DE"), ("90.", "DE"), ("91.", "RU"), ("92.", "RU"),
    ("93.", "RU"), ("94.", "RU"), ("95.", "RU"), ("96.", "SE"), ("97.", "US"),
    ("98.", "US"), ("99.", "US"), ("100.", "US"), ("101.", "US"), ("102.", "US"),
    ("103.", "US"), ("104.", "US"), ("105.", "US"), ("106.", "CN"), ("107.", "US"),
    ("108.", "BR"), ("109.", "US"), ("110.", "US"), ("111.", "US"), ("112.", "US"),
    ("113.", "AU"), ("114.", "AU"), ("115.", "AU"), ("116.", "AU"), ("117.", "US"),
    ("118.", "US"), ("119.", "US"), ("120.", "US"), ("121.", "US"), ("122.", "US"),
    ("123.", "US"), ("124.", "US"), ("125.", "US"), ("126.", "JP"), ("127.", "US"),
    ("128.", "US"), ("129.", "US"), ("130.", "US"), ("131.", "US"), ("132.", "US"),
    ("133.", "JP"), ("134.", "US"), ("135.", "US"), ("136.", "US"), ("137.", "US"),
    ("138.", "US"), ("139.", "US"), ("140.", "JP"), ("141.", "US"), ("142.", "US"),
    ("143.", "US"), ("144.", "US"), ("145.", "US"), ("146.", "US"), ("147.", "US"),
    ("148.", "US"), ("149.", "US"), ("150.", "US"), ("151.", "US"), ("152.", "US"),
    ("153.", "US"), ("154.", "US"), ("155.", "US"), ("156.", "US"), ("157.", "US"),
    ("158.", "US"), ("159.", "US"), ("160.", "US"), ("161.", "US"), ("162.", "US"),
    ("163.", "AU"), ("164.", "US"), ("165.", "US"), ("166.", "US"), ("167.", "US"),
    ("168.", "US"), ("169.", "US"), ("170.", "US"), ("171.", "US"), ("172.", "US"),
    ("173.", "US"), ("174.", "US"), ("175.", "US"), ("176.", "DE"), ("177.", "US"),
    ("178.", "RU"), ("179.", "BR"), ("180.", "US"), ("181.", "US"), ("182.", "US"),
    ("183.", "CN"), ("184.", "US"), ("185.", "US"), ("186.", "US"), ("187.", "US"),
    ("188.", "US"), ("189.", "BR"), ("190.", "US"), ("191.", "US"), ("192.", "US"),
    ("193.", "US"), ("194.", "US"), ("195.", "US"), ("196.", "US"), ("197.", "US"),
    ("198.", "US"), ("199.", "US"), ("200.", "BR"), ("201.", "BR"), ("202.", "AU"),
    ("203.", "AU"), ("204.", "US"), ("205.", "US"), ("206.", "US"), ("207.", "US"),
    ("208.", "US"), ("209.", "US"), ("210.", "JP"), ("211.", "JP"), ("212.", "DE"),
    ("213.", "ES"), ("214.", "US"), ("215.", "US"), ("216.", "US"), ("217.", "US"),
    ("218.", "CN"), ("219.", "JP"), ("220.", "JP"), ("221.", "KR"), ("222.", "KR"),
    ("223.", "CN"), ("224.", "US"), ("225.", "US"), ("226.", "US"), ("227.", "US"),
    ("228.", "US"), ("229.", "US"), ("230.", "US"), ("231.", "US"), ("232.", "US"),
    ("233.", "US"), ("234.", "US"), ("235.", "US"), ("236.", "CA"), ("237.", "CA"),
    ("238.", "CA"), ("239.", "CA"), ("240.", "CA"), ("241.", "CA"), ("242.", "CA"),
    ("243.", "CA"), ("244.", "CA"), ("245.", "CA"), ("246.", "CA"), ("247.", "CA"),
    ("248.", "CA"), ("249.", "CA"), ("250.", "CA"), ("251.", "CA"), ("252.", "CA"),
    ("253.", "CA"), ("254.", "CA"), ("255.", "CA"),
]


class Tracker:
    """Privacy-first analytics tracker."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self._session_cache: dict[str, datetime] = {}
        self._SESSION_TIMEOUT = timedelta(minutes=30)

    # ── hashing ──────────────────────────────────────────────────────────

    @staticmethod
    def _hash_ip_user_agent(ip: str, user_agent: str) -> str:
        salt = "ghostly-salt-v1"
        raw = f"{salt}:{ip}:{user_agent}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    # ── user-agent parsing ───────────────────────────────────────────────

    @staticmethod
    def parse_user_agent(user_agent: str) -> dict[str, str]:
        browser = "Other"
        for name, pattern in _BROWSER_PATTERNS:
            if pattern.search(user_agent):
                browser = name
                break

        os_name = "Other"
        for name, pattern in _OS_PATTERNS:
            if pattern.search(user_agent):
                os_name = name
                break

        device_type = "desktop"
        ua_lower = user_agent.lower()
        for dtype, keywords in _DEVICE_KEYWORDS.items():
            if any(kw.lower() in ua_lower for kw in keywords):
                device_type = dtype
                break

        return {"browser": browser, "os": os_name, "device_type": device_type}

    # ── country detection ────────────────────────────────────────────────

    @staticmethod
    def detect_country(ip: str) -> str:
        for prefix, country in _COUNTRY_BLOCKS:
            if ip.startswith(prefix):
                return country
        if ip.startswith("::ffff:"):
            ip = ip[7:]
        for prefix, country in _COUNTRY_BLOCKS:
            if ip.startswith(prefix):
                return country
        return "Unknown"

    # ── session management ───────────────────────────────────────────────

    def _get_or_create_session(
        self,
        visitor_id: str,
        ip: str,
        user_agent: str,
        referrer: str,
        country: str,
        *,
        now: datetime | None = None,
    ) -> str:
        now = now or datetime.now(timezone.utc)
        cached = self._session_cache.get(visitor_id)
        if cached and (now - cached) < self._SESSION_TIMEOUT:
            return visitor_id + "-" + cached.strftime("%Y%m%d%H%M")
        self._session_cache[visitor_id] = now
        return visitor_id + "-" + now.strftime("%Y%m%d%H%M")

    # ── public API ───────────────────────────────────────────────────────

    def get_visitor_id(self, ip: str, user_agent: str) -> str:
        return self._hash_ip_user_agent(ip, user_agent)

    async def track_pageview(
        self,
        *,
        site_id: int,
        url: str,
        path: str = "/",
        title: str = "",
        referrer: str = "",
        language: str = "",
        screen_size: str = "",
        ip_address: str = "0.0.0.0",
        user_agent: str = "",
    ) -> dict[str, Any]:
        parsed = self.parse_user_agent(user_agent)
        country = self.detect_country(ip_address)
        visitor_id = self.get_visitor_id(ip_address, user_agent)
        session_id = self._get_or_create_session(
            visitor_id, ip_address, user_agent, referrer, country,
        )

        # persist visitor
        await self.db.db.execute(
            """INSERT INTO visitors (id, site_id, ip_address, user_agent, country, last_seen)
               VALUES (?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(id) DO UPDATE SET last_seen=datetime('now'), visits=visits+1""",
            (visitor_id, site_id, ip_address, user_agent, country),
        )

        # persist session
        await self.db.db.execute(
            """INSERT INTO sessions (id, site_id, visitor_id, referrer, browser, os, device_type, country)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET page_count=page_count+1, ended_at=datetime('now')""",
            (session_id, site_id, visitor_id, referrer,
             parsed["browser"], parsed["os"], parsed["device_type"], country),
        )

        # persist referrer
        if referrer:
            parsed_ref = urlparse(referrer)
            ref_domain = parsed_ref.netloc or referrer
            await self.db.db.execute(
                """INSERT INTO referrers (site_id, url, domain, visits, last_seen)
                   VALUES (?, ?, ?, 1, datetime('now'))
                   ON CONFLICT(site_id, url) DO UPDATE SET visits=visits+1, last_seen=datetime('now')""",
                (site_id, referrer, ref_domain),
            )

        # persist device / browser / country aggregates
        for table, col, val in [
            ("devices", "device_type", parsed["device_type"]),
            ("browsers", "browser", parsed["browser"]),
            ("countries", "country", country),
        ]:
            await self.db.db.execute(
                f"""INSERT INTO {table} (site_id, {col}, visits, last_seen)
                    VALUES (?, ?, 1, datetime('now'))
                    ON CONFLICT(site_id, {col}) DO UPDATE SET visits=visits+1, last_seen=datetime('now')""",
                (site_id, val),
            )

        # persist pageview
        pageview_id = await self.db.insert_pageview(
            site_id=site_id,
            visitor_id=visitor_id,
            session_id=session_id,
            url=url,
            path=path,
            title=title,
            referrer=referrer,
            language=language,
            screen_size=screen_size,
            ip_address=ip_address,
            country=country,
            browser=parsed["browser"],
            os=parsed["os"],
            device_type=parsed["device_type"],
        )

        await self.db.db.commit()

        return {
            "pageview_id": pageview_id,
            "visitor_id": visitor_id,
            "session_id": session_id,
            "country": country,
            **parsed,
        }

    async def track_event(
        self,
        *,
        site_id: int,
        visitor_id: str,
        session_id: str,
        name: str,
        url: str = "",
        meta: dict[str, Any] | None = None,
    ) -> int:
        event_id = await self.db.insert_event(
            site_id=site_id,
            visitor_id=visitor_id,
            session_id=session_id,
            name=name,
            url=url,
            meta=meta,
        )
        await self.db.db.commit()
        return event_id
