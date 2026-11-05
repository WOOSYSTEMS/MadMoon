"""
MadEye Tank Satellite Fill Level Collector
Uses NASA FIRMS thermal signatures to monitor oil storage activity.
Cushing OK (35.9N, -96.0W) and ARA (51.9N, 4.5E) are key storage hubs.
More thermal activity at storage = more throughput = signal of activity level.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

from .base import BaseCollector

logger = logging.getLogger("madeye")

NASA_FIRMS_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
NASA_FIRMS_KEY = "cf56ebe9e0641c7716f98d13e0f44778"

# Key storage locations
LOCATIONS = {
    "cushing_ok": {
        "name": "Cushing, Oklahoma (WTI Hub)",
        "lat": 35.9,
        "lon": -96.0,
        "radius_km": 15,  # Cushing tank farms spread ~10km
        "weight": 0.60,
    },
    "ara": {
        "name": "ARA (Amsterdam-Rotterdam-Antwerp)",
        "lat": 51.9,
        "lon": 4.5,
        "radius_km": 30,  # Large industrial area
        "weight": 0.40,
    },
}


class TankSatelliteCollector(BaseCollector):
    name = "tank_satellite"
    category = "supply"
    cache_ttl = 21600  # 6 hours (satellite data updates periodically)

    async def _fetch_firms_data(self, lat: float, lon: float, radius_km: float,
                                location_key: str) -> Optional[List[Dict]]:
        """Fetch NASA FIRMS thermal anomaly data for a region."""
        # FIRMS API: area query around lat/lon
        # Using VIIRS data source for better resolution
        today = datetime.now(timezone.utc)
        end_date = today.strftime("%Y-%m-%d")
        start_date = (today - timedelta(days=10)).strftime("%Y-%m-%d")

        # FIRMS area CSV endpoint
        # Format: /api/area/csv/{key}/{source}/{area}/{days}
        # Area format: lat,lon,radius_in_degrees
        radius_deg = radius_km / 111.0  # Rough km to degrees

        # Try VIIRS SNPP
        url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{NASA_FIRMS_KEY}/VIIRS_SNPP_NRT/{lon - radius_deg},{lat - radius_deg},{lon + radius_deg},{lat + radius_deg}/10"

        text = await self.fetch_text(url, cache_key=f"firms_{location_key}")
        if not text:
            # Fallback: try MODIS
            url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{NASA_FIRMS_KEY}/MODIS_NRT/{lon - radius_deg},{lat - radius_deg},{lon + radius_deg},{lat + radius_deg}/10"
            text = await self.fetch_text(url, cache_key=f"firms_modis_{location_key}")

        if not text:
            return None

        # Parse CSV
        records = []
        lines = text.strip().split("\n")
        if len(lines) < 2:
            return records

        headers = lines[0].split(",")
        for line in lines[1:]:
            fields = line.split(",")
            if len(fields) >= len(headers):
                record = dict(zip(headers, fields))
                records.append(record)

        return records

    def _analyze_thermal_data(self, records: List[Dict], location: Dict) -> Dict:
        """Analyze thermal anomaly data for storage activity."""
        if not records:
            return {
                "detections": 0,
                "avg_frp": 0,
                "score": 5.0,
                "signal": "No thermal data available",
            }

        # Count detections and average fire radiative power (FRP)
        frp_values = []
        brightness_values = []
        daily_counts = {}

        for record in records:
            try:
                frp = float(record.get("frp", 0))
                if frp > 0:
                    frp_values.append(frp)
            except (ValueError, TypeError):
                pass

            try:
                bright = float(record.get("bright_ti4", 0) or record.get("brightness", 0))
                if bright > 0:
                    brightness_values.append(bright)
            except (ValueError, TypeError):
                pass

            date = record.get("acq_date", "unknown")
            daily_counts[date] = daily_counts.get(date, 0) + 1

        total_detections = len(records)
        avg_frp = sum(frp_values) / len(frp_values) if frp_values else 0
        avg_daily = total_detections / max(len(daily_counts), 1)

        # Scoring: More thermal activity at storage = more throughput
        # For oil storage areas, thermal activity comes from:
        # - Refinery/processing operations
        # - Tank heating (for heavy crude)
        # - Flaring during transfers
        # More activity = more oil movement = useful activity signal

        if total_detections > 50:
            score = 7.0
            signal = f"High thermal activity ({total_detections} detections) -- heavy throughput"
        elif total_detections > 20:
            score = 6.0
            signal = f"Moderate thermal activity ({total_detections} detections) -- normal operations"
        elif total_detections > 5:
            score = 5.0
            signal = f"Low thermal activity ({total_detections} detections) -- quiet period"
        elif total_detections > 0:
            score = 4.0
            signal = f"Minimal thermal activity ({total_detections} detections) -- very quiet"
        else:
            score = 5.0
            signal = "No thermal detections -- could be cloud cover or quiet operations"

        return {
            "detections": total_detections,
            "avg_frp": round(avg_frp, 2),
            "avg_daily_detections": round(avg_daily, 1),
            "days_with_data": len(daily_counts),
            "score": score,
            "signal": signal,
        }

    async def collect(self) -> Dict:
        signals = []
        weighted_score = 0.0
        total_weight = 0.0
        confidence = 0.2
        details = {}

        for key, loc in LOCATIONS.items():
            records = await self._fetch_firms_data(
                lat=loc["lat"],
                lon=loc["lon"],
                radius_km=loc["radius_km"],
                location_key=key,
            )

            analysis = self._analyze_thermal_data(records or [], loc)

            signals.append(f"{loc['name']}: {analysis['signal']}")
            if analysis["detections"] > 0:
                signals.append(f"  Avg FRP: {analysis['avg_frp']:.1f} MW, {analysis['avg_daily_detections']:.1f} detections/day over {analysis['days_with_data']} days")
                confidence = max(confidence, 0.4)

            weighted_score += analysis["score"] * loc["weight"]
            total_weight += loc["weight"]
            details[key] = analysis

        composite = weighted_score / total_weight if total_weight > 0 else 5.0

        # If both locations show high activity, that's notable
        cushing = details.get("cushing_ok", {})
        ara = details.get("ara", {})
        if cushing.get("detections", 0) > 20 and ara.get("detections", 0) > 20:
            signals.append("Both Cushing and ARA showing high activity -- active global oil logistics")
            confidence = min(1.0, confidence + 0.1)

        if composite >= 6.5:
            direction = "BULLISH"
        elif composite <= 3.5:
            direction = "BEARISH"
        else:
            direction = "NEUTRAL"

        return self.make_result(
            score=composite,
            direction=direction,
            signals=signals,
            details=details,
            confidence=confidence,
        )
