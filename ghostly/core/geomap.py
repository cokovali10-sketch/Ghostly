from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from .database import Database
# --- константы вынесены FORGE refactor ---
CONST_14_235 = 14.235
CONST_20_5937 = 20.5937
CONST_30 = 30
CONST_50 = 50
CONST_51_9253 = 51.9253
CONST_78_9629 = 78.9629


logger = logging.getLogger("ghostly.geomap")

# Country name mapping for common ISO codes
COUNTRY_NAMES: dict[str, str] = {
    "US": "United States", "GB": "United Kingdom", "DE": "Germany", "FR": "France",
    "JP": "Japan", "CN": "China", "BR": "Brazil", "IN": "India", "CA": "Canada",
    "AU": "Australia", "RU": "Russia", "KR": "South Korea", "ES": "Spain",
    "IT": "Italy", "NL": "Netherlands", "SE": "Sweden", "ZA": "South Africa",
    "MX": "Mexico", "PL": "Poland", "TR": "Turkey", "ID": "Indonesia",
    "TH": "Thailand", "VN": "Vietnam", "PH": "Philippines", "MY": "Malaysia",
    "SG": "Singapore", "HK": "Hong Kong", "TW": "Taiwan", "NZ": "New Zealand",
    "NO": "Norway", "FI": "Finland", "DK": "Denmark", "CH": "Switzerland",
    "AT": "Austria", "BE": "Belgium", "IE": "Ireland", "PT": "Portugal",
    "GR": "Greece", "CZ": "Czech Republic", "RO": "Romania", "HU": "Hungary",
    "UA": "Ukraine", "IL": "Israel", "AE": "UAE", "SA": "Saudi Arabia",
    "EG": "Egypt", "NG": "Nigeria", "KE": "Kenya", "AR": "Argentina",
    "CO": "Colombia", "CL": "Chile", "PE": "Peru", "Unknown": "Unknown",
}

# Approximate country centroids for map rendering
COUNTRY_CENTROIDS: dict[str, tuple[float, float]] = {
    "US": (39.8283, -98.5795), "GB": (55.3781, -3.4360), "DE": (51.1657, 10.4515),
    "FR": (46.2276, 2.2137), "JP": (36.2048, 138.2529), "CN": (35.8617, 104.1954),
    "BR": (-CONST_14_235, -CONST_51_9253), "IN": (CONST_20_5937, CONST_78_9629), "CA": (56.1304, -106.3468),
    "AU": (-25.2744, 133.7751), "RU": (61.5240, 105.3188), "KR": (35.9078, 127.7669),
    "ES": (40.4637, -3.7492), "IT": (41.8719, 12.5674), "NL": (52.1326, 5.2913),
    "SE": (60.1282, 18.6435), "BR": (-CONST_14_235, -CONST_51_9253), "IN": (CONST_20_5937, CONST_78_9629),
    "MX": (23.6345, -102.5528), "PL": (51.9194, 19.1451), "TR": (38.9637, 35.2433),
    "ID": (-0.7893, 113.9213), "TH": (15.8700, 100.9925), "VN": (14.0583, 108.2772),
    "PH": (12.8797, 121.7740), "MY": (4.2105, 101.9758), "SG": (1.3521, 103.8198),
    "HK": (22.3193, 114.1694), "TW": (23.6978, 120.9605), "NZ": (-40.9006, 174.8860),
    "NO": (60.4720, 8.4689), "FI": (61.9241, 25.7482), "DK": (56.2639, 9.5018),
    "CH": (46.8182, 8.2275), "AT": (47.5162, 14.5501), "BE": (50.8503, 4.3517),
    "IE": (53.1424, -7.6921), "PT": (39.3999, -8.2245), "GR": (39.0742, 21.8243),
    "CZ": (49.8175, 15.4730), "RO": (45.9432, 24.9668), "HU": (47.1625, 19.5033),
    "ZA": (-30.5595, 22.9375), "NG": (9.0820, 8.6753), "KE": (-0.0236, 37.9062),
    "AR": (-38.4161, -63.6166), "CO": (4.5709, -74.2973), "CL": (-35.6751, -71.5430),
    "PE": (-9.1900, -75.0152), "EG": (26.8206, 30.8025), "SA": (23.8859, 45.0792),
    "AE": (23.4241, 53.8478), "IL": (31.0461, 34.8516),
}


class GeoMapCollector:
    """Collects and aggregates geographic visitor data for map visualization."""

    def __init__(self, db: Database) -> None:
        self.db = db

    async def record_visitor_location(
        self,
        site_id: int,
        visitor_id: str,
        country: str = "",
        city: str = "",
        latitude: float | None = None,
        longitude: float | None = None,
        ip_address: str = "",
    ) -> int:
        cursor = await self.db.db.execute(
            """INSERT INTO visitor_locations
               (site_id, visitor_id, country, city, latitude, longitude, ip_address)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (site_id, visitor_id, country, city, latitude, longitude, ip_address),
        )
        await self.db.db.commit()
        return cursor.lastrowid or 0

    async def get_country_stats(
        self, site_id: int, days: int = CONST_30, limit: int = CONST_50
    ) -> list[dict[str, Any]]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        rows = await self.db._fetch_all(
            """SELECT country, COUNT(DISTINCT visitor_id) AS unique_visitors, COUNT(*) AS visits
               FROM visitor_locations
               WHERE site_id=? AND created_at>=? AND country != ''
               GROUP BY country ORDER BY visits DESC LIMIT ?""",
            (site_id, since, limit),
        )
        for row in rows:
            code = row["country"]
            row["country_name"] = COUNTRY_NAMES.get(code, code)
            centroid = COUNTRY_CENTROIDS.get(code)
            row["latitude"] = centroid[0] if centroid else None
            row["longitude"] = centroid[1] if centroid else None
        return rows

    async def get_city_stats(
        self, site_id: int, days: int = CONST_30, limit: int = 100
    ) -> list[dict[str, Any]]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        return await self.db._fetch_all(
            """SELECT city, country, latitude, longitude,
                      COUNT(DISTINCT visitor_id) AS unique_visitors, COUNT(*) AS visits
               FROM visitor_locations
               WHERE site_id=? AND created_at>=? AND city != ''
               GROUP BY city, country ORDER BY visits DESC LIMIT ?""",
            (site_id, since, limit),
        )

    async def get_top_countries(
        self, site_id: int, days: int = CONST_30, limit: int = 10
    ) -> list[dict[str, Any]]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        rows = await self.db._fetch_all(
            """SELECT country, COUNT(DISTINCT visitor_id) AS unique_visitors, COUNT(*) AS visits
               FROM visitor_locations
               WHERE site_id=? AND created_at>=? AND country != ''
               GROUP BY country ORDER BY visits DESC LIMIT ?""",
            (site_id, since, limit),
        )
        for row in rows:
            code = row["country"]
            row["country_name"] = COUNTRY_NAMES.get(code, code)
        return rows

    async def get_top_cities(
        self, site_id: int, days: int = CONST_30, limit: int = 20
    ) -> list[dict[str, Any]]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        return await self.db._fetch_all(
            """SELECT city, country, COUNT(DISTINCT visitor_id) AS unique_visitors, COUNT(*) AS visits
               FROM visitor_locations
               WHERE site_id=? AND created_at>=? AND city != ''
               GROUP BY city, country ORDER BY visits DESC LIMIT ?""",
            (site_id, since, limit),
        )

    async def generate_geojson(
        self, site_id: int, days: int = CONST_30, limit: int = 200
    ) -> dict[str, Any]:
        cities = await self.get_city_stats(site_id, days=days, limit=limit)
        features = []
        for city in cities:
            if city.get("latitude") is None or city.get("longitude") is None:
                centroid = COUNTRY_CENTROIDS.get(city.get("country", ""))
                if centroid:
                    city["latitude"] = centroid[0]
                    city["longitude"] = centroid[1]
            if city.get("latitude") is not None and city.get("longitude") is not None:
                features.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [city["longitude"], city["latitude"]],
                    },
                    "properties": {
                        "city": city["city"],
                        "country": city["country"],
                        "country_name": COUNTRY_NAMES.get(city["country"], city["country"]),
                        "unique_visitors": city["unique_visitors"],
                        "visits": city["visits"],
                    },
                })

        return {
            "type": "FeatureCollection",
            "features": features,
            "metadata": {
                "site_id": site_id,
                "period_days": days,
                "total_features": len(features),
            },
        }

    async def generate_country_geojson(
        self, site_id: int, days: int = CONST_30
    ) -> dict[str, Any]:
        countries = await self.get_country_stats(site_id, days=days)
        features = []
        for country in countries:
            centroid = COUNTRY_CENTROIDS.get(country["country"])
            if centroid:
                features.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [centroid[1], centroid[0]],
                    },
                    "properties": {
                        "country": country["country"],
                        "country_name": country["country_name"],
                        "unique_visitors": country["unique_visitors"],
                        "visits": country["visits"],
                    },
                })

        return {
            "type": "FeatureCollection",
            "features": features,
            "metadata": {
                "site_id": site_id,
                "period_days": days,
                "total_features": len(features),
            },
        }

    async def get_visitor_country_distribution(
        self, site_id: int, days: int = CONST_30
    ) -> dict[str, Any]:
        countries = await self.get_country_stats(site_id, days=days, limit=CONST_50)
        total_visitors = sum(c["unique_visitors"] for c in countries)
        distribution = []
        for c in countries:
            pct = round(c["unique_visitors"] / total_visitors * 100, 2) if total_visitors else 0
            distribution.append({
                "country": c["country"],
                "country_name": c["country_name"],
                "unique_visitors": c["unique_visitors"],
                "percentage": pct,
            })
        return {
            "total_visitors": total_visitors,
            "countries": distribution,
        }

    async def get_geo_summary(self, site_id: int, days: int = CONST_30) -> dict[str, Any]:
        countries = await self.get_country_stats(site_id, days=days, limit=CONST_50)
        cities = await self.get_top_cities(site_id, days=days, limit=10)
        total_countries = len(countries)
        total_cities_result = await self.db._fetch_one(
            """SELECT COUNT(DISTINCT city) AS total_cities
               FROM visitor_locations
               WHERE site_id=? AND created_at>=? AND city != ''""",
            (site_id, (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()),
        )
        total_cities = total_cities_result["total_cities"] if total_cities_result else 0

        return {
            "total_countries": total_countries,
            "total_cities": total_cities,
            "top_countries": countries[:10],
            "top_cities": cities,
        }