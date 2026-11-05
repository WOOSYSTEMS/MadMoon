"""
MadEye Weather Collector
NOAA hurricane data for Gulf of Mexico, seasonal patterns.
Scores weather signal 0-10.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List

from .base import BaseCollector

logger = logging.getLogger("madeye")

NHC_ACTIVE = "https://www.nhc.noaa.gov/CurrentSummary.json"
NHC_OUTLOOK = "https://www.nhc.noaa.gov/gtwo_atl_7d_info.json"
NOAA_WEATHER = "https://api.weather.gov"
BSEE_SHUTINS = "https://www.bsee.gov/hurricane-information"

# GoM production zone approximate bounds
GOM_BOUNDS = {"lat_min": 24, "lat_max": 31, "lon_min": -98, "lon_max": -82}


class WeatherCollector(BaseCollector):
    name = "weather"
    category = "weather"
    cache_ttl = 3600  # 1 hour

    async def collect(self) -> Dict:
        signals = []
        subscores = []

        # --- 1. Active Hurricanes / Tropical Systems ---
        hurricane_score, hurricane_signals = await self._check_hurricanes()
        subscores.append(hurricane_score)
        signals.extend(hurricane_signals)

        # --- 2. Seasonal Pattern ---
        seasonal_score, seasonal_signals = self._check_seasonal()
        subscores.append(seasonal_score)
        signals.extend(seasonal_signals)

        # --- 3. Extreme Weather Events ---
        extreme_score, extreme_signals = await self._check_extreme_weather()
        subscores.append(extreme_score)
        signals.extend(extreme_signals)

        # Weighted: Hurricanes 50%, Seasonal 25%, Extreme weather 25%
        weights = [0.50, 0.25, 0.25]
        composite = sum(s * w for s, w in zip(subscores, weights)) / sum(weights)

        if composite >= 6.5:
            direction = "BULLISH"
        elif composite <= 3.5:
            direction = "BEARISH"
        else:
            direction = "NEUTRAL"

        confidence = min(1.0, len([s for s in subscores if s != 5.0]) / len(subscores))

        return self.make_result(
            score=composite,
            direction=direction,
            signals=signals,
            details={
                "hurricane_score": round(hurricane_score, 2),
                "seasonal_score": round(seasonal_score, 2),
                "extreme_weather_score": round(extreme_score, 2),
            },
            confidence=confidence,
        )

    async def _check_hurricanes(self) -> tuple:
        """Check for active tropical systems threatening Gulf of Mexico."""
        signals = []
        score = 5.0

        # Check NHC active systems
        data = await self.fetch_json(NHC_ACTIVE, cache_key="nhc_active")

        # Also check via GDELT for hurricane/storm news
        gdelt_url = "https://api.gdeltproject.org/api/v2/doc/doc"
        gdelt_params = {
            "query": "hurricane+OR+tropical+storm+Gulf+Mexico+OR+oil+production+shutdown",
            "mode": "artlist",
            "maxrecords": "30",
            "format": "json",
            "timespan": "72h",
        }
        gdelt_data = await self.fetch_json(gdelt_url, params=gdelt_params, cache_key="gdelt_hurricane")

        # Check if we're in hurricane season
        now = datetime.now(timezone.utc)
        in_hurricane_season = 6 <= now.month <= 11

        if not in_hurricane_season:
            signals.append("Outside hurricane season (Jun-Nov)")
            score = 4.5  # Slight bearish as no hurricane premium needed
            return score, signals

        signals.append("Hurricane season active (Jun-Nov)")

        # Parse NHC data
        active_systems = 0
        gom_threats = 0

        if data:
            try:
                # NHC format varies; try common structures
                systems = data.get("activeStorms", data.get("storms", []))
                if isinstance(systems, list):
                    active_systems = len(systems)
                    for storm in systems:
                        lat = float(storm.get("lat", storm.get("latitude", 0)))
                        lon = float(storm.get("lon", storm.get("longitude", 0)))
                        category = storm.get("category", storm.get("classification", ""))

                        # Check if storm is in/near GoM
                        if (GOM_BOUNDS["lat_min"] <= lat <= GOM_BOUNDS["lat_max"] + 5 and
                                GOM_BOUNDS["lon_min"] - 5 <= lon <= GOM_BOUNDS["lon_max"]):
                            gom_threats += 1
                            cat_str = str(category)
                            signals.append(f"GoM THREAT: {storm.get('name', 'Unknown')} Cat {cat_str}")
                elif isinstance(data, dict) and "CurrentStorms" in data:
                    storms = data["CurrentStorms"].get("Storm", [])
                    if isinstance(storms, dict):
                        storms = [storms]
                    active_systems = len(storms)
            except Exception as e:
                logger.warning(f"NHC parse error: {e}")

        # GDELT-based hurricane assessment
        if gdelt_data:
            articles = gdelt_data.get("articles", [])
            shutdown_articles = 0
            for art in articles:
                title = (art.get("title", "") or "").lower()
                if any(kw in title for kw in ["shutdown", "evacuate", "halt production", "shut in"]):
                    shutdown_articles += 1

            if shutdown_articles >= 5:
                score = 9.0
                signals.append(f"Multiple production shutdown reports ({shutdown_articles})")
            elif shutdown_articles >= 2:
                score = 7.5
                signals.append(f"Production shutdown reports detected ({shutdown_articles})")
            elif len(articles) > 15:
                score = 6.5
                signals.append(f"Heavy hurricane/storm coverage ({len(articles)} articles)")
            elif len(articles) > 5:
                score = 6.0
                signals.append(f"Active storm coverage ({len(articles)} articles)")
            else:
                signals.append(f"Minimal storm coverage ({len(articles)} articles)")

        if gom_threats > 0:
            score = max(score, 8.0)
            signals.append(f"{gom_threats} active GoM threat(s)")
        elif active_systems > 0:
            score = max(score, 6.0)
            signals.append(f"{active_systems} active Atlantic system(s), not GoM-threatening")

        return score, signals

    def _check_seasonal(self) -> tuple:
        """Apply seasonal oil price patterns."""
        signals = []
        now = datetime.now(timezone.utc)
        month = now.month

        # Historical seasonal patterns from research doc
        seasonal_map = {
            1: (3.5, "January: post-holiday demand lull"),
            2: (3.5, "February: refinery maintenance season"),
            3: (6.5, "March: rally begins, refinery restarts"),
            4: (7.0, "April: summer blend production ramp"),
            5: (7.5, "May: peak driving season preparation"),
            6: (7.5, "June: summer driving season peak demand"),
            7: (7.0, "July: summer plateau"),
            8: (6.5, "August: late summer, demand starts fading"),
            9: (4.0, "September: fall turnaround season begins"),
            10: (4.5, "October: turnaround season, hurricane wildcards"),
            11: (5.5, "November: winter heating demand building"),
            12: (5.0, "December: mixed holiday/heating dynamics"),
        }

        score, note = seasonal_map.get(month, (5.0, "Unknown seasonal pattern"))
        signals.append(f"Seasonal: {note}")

        return score, signals

    async def _check_extreme_weather(self) -> tuple:
        """Check for extreme weather affecting oil infrastructure."""
        signals = []
        score = 5.0

        # Use GDELT to check for extreme weather + oil
        url = "https://api.gdeltproject.org/api/v2/doc/doc"
        params = {
            "query": "extreme+weather+OR+winter+storm+OR+freeze+OR+flood+oil+refinery+OR+pipeline",
            "mode": "artlist",
            "maxrecords": "20",
            "format": "json",
            "timespan": "7d",
        }

        data = await self.fetch_json(url, params=params, cache_key="gdelt_extreme_weather")
        if not data:
            signals.append("Extreme weather monitoring: unavailable")
            return score, signals

        articles = data.get("articles", [])
        disruption_count = 0

        for art in articles:
            title = (art.get("title", "") or "").lower()
            if any(kw in title for kw in ["shutdown", "outage", "disruption", "damage",
                                            "evacuate", "freeze", "flood"]):
                disruption_count += 1

        if disruption_count >= 5:
            score = 7.5
            signals.append(f"Weather-related oil disruptions: {disruption_count} reports")
        elif disruption_count >= 2:
            score = 6.0
            signals.append(f"Some weather disruption reports: {disruption_count}")
        else:
            score = 5.0
            signals.append("No significant weather disruptions reported")

        return score, signals
