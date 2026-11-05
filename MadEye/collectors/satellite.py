"""
MadEye Satellite Collector
NASA FIRMS thermal anomalies in Middle East oil infrastructure.
Scores satellite signal 0-10.
"""

import logging
import csv
import io
from datetime import datetime, timezone, timedelta
from typing import Dict, List

from .base import BaseCollector

logger = logging.getLogger("madeye")

NASA_FIRMS_KEY = "cf56ebe9e0641c7716f98d13e0f44778"
FIRMS_BASE = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"

# Key oil infrastructure monitoring regions (lat/lon bounding boxes)
MONITOR_REGIONS = {
    "persian_gulf": {
        "name": "Persian Gulf (Iran/Iraq/Kuwait/Saudi)",
        "bbox": "46,24,56,32",  # Wider area covering Iran, Iraq, Kuwait, Saudi
        "baseline_hotspots": 50,
    },
    "yemen": {
        "name": "Yemen (Houthi)",
        "bbox": "42,13,46,17",
        "baseline_hotspots": 10,
    },
    "hormuz_strait": {
        "name": "Strait of Hormuz",
        "bbox": "54,25,58,28",
        "baseline_hotspots": 8,
    },
    "gulf_of_mexico": {
        "name": "Gulf of Mexico Platforms",
        "bbox": "-98,25,-85,31",
        "baseline_hotspots": 30,
    },
    "libya": {
        "name": "Libya Oil Terminals",
        "bbox": "10,28,25,34",
        "baseline_hotspots": 15,
    },
    "nigeria_delta": {
        "name": "Niger Delta",
        "bbox": "3,4,9,7",
        "baseline_hotspots": 40,
    },
    "russia_urals": {
        "name": "Russian Urals Pipeline",
        "bbox": "50,52,70,62",
        "baseline_hotspots": 25,
    },
}


class SatelliteCollector(BaseCollector):
    name = "satellite"
    category = "satellite"
    cache_ttl = 7200  # 2 hours (FIRMS data has ~3hr lag)

    async def collect(self) -> Dict:
        signals = []
        subscores = []

        for region_id, region in MONITOR_REGIONS.items():
            region_score, region_signals = await self._check_region(region_id, region)
            subscores.append(region_score)
            signals.extend(region_signals)

        if not subscores:
            return self.make_result(
                score=5.0,
                direction="NEUTRAL",
                signals=["Satellite data: all regions unavailable"],
                confidence=0.0,
            )

        # Weight Persian Gulf, Hormuz, and GoM more heavily
        weights = {
            "persian_gulf": 0.25,
            "yemen": 0.10,
            "hormuz_strait": 0.15,
            "gulf_of_mexico": 0.20,
            "libya": 0.10,
            "nigeria_delta": 0.10,
            "russia_urals": 0.10,
        }
        region_ids = list(MONITOR_REGIONS.keys())
        weighted_scores = []
        total_weight = 0
        for i, rid in enumerate(region_ids):
            if i < len(subscores):
                w = weights.get(rid, 0.1)
                weighted_scores.append(subscores[i] * w)
                total_weight += w

        composite = sum(weighted_scores) / total_weight if total_weight > 0 else 5.0

        if composite >= 6.5:
            direction = "BULLISH"
        elif composite <= 3.5:
            direction = "BEARISH"
        else:
            direction = "NEUTRAL"

        confidence = min(1.0, len([s for s in subscores if s != 5.0]) / max(1, len(subscores)))

        return self.make_result(
            score=composite,
            direction=direction,
            signals=signals,
            details={
                rid: round(subscores[i], 2) if i < len(subscores) else 5.0
                for i, rid in enumerate(region_ids)
            },
            confidence=confidence,
        )

    async def _check_region(self, region_id: str, region: Dict) -> tuple:
        """Check NASA FIRMS thermal anomalies for a specific region."""
        signals = []
        score = 5.0

        bbox = region["bbox"]
        baseline = region["baseline_hotspots"]
        name = region["name"]

        # FIRMS API: get last 24h of VIIRS data for bounding box
        url = f"{FIRMS_BASE}/{NASA_FIRMS_KEY}/VIIRS_SNPP_NRT/{bbox}/1"

        csv_text = await self.fetch_text(url, cache_key=f"firms_{region_id}")
        if not csv_text:
            signals.append(f"{name}: FIRMS data unavailable")
            return score, signals

        try:
            reader = csv.DictReader(io.StringIO(csv_text))
            hotspots = list(reader)
            count = len(hotspots)

            # Filter for high-confidence detections
            high_conf = [h for h in hotspots if h.get("confidence", "n") in ("high", "h", "nominal", "n")]
            high_conf_count = len(high_conf)

            # Count high FRP (Fire Radiative Power) events
            high_frp = [h for h in hotspots if float(h.get("frp", 0)) > 100]
            high_frp_count = len(high_frp)

            ratio = count / baseline if baseline > 0 else 1.0

            if count == 0:
                # No hotspots could mean cloud cover or genuinely quiet
                signals.append(f"{name}: 0 thermal anomalies (possible cloud cover)")
                score = 5.0
            elif ratio > 3.0:
                score = 8.5
                signals.append(f"{name}: {count} hotspots ({ratio:.1f}x baseline!) -- possible infrastructure fire")
            elif ratio > 2.0:
                score = 7.0
                signals.append(f"{name}: {count} hotspots ({ratio:.1f}x baseline) -- elevated activity")
            elif ratio > 1.3:
                score = 6.0
                signals.append(f"{name}: {count} hotspots (above baseline)")
            elif ratio < 0.5:
                # Significantly fewer hotspots = reduced flaring = possible production cut
                score = 6.5
                signals.append(f"{name}: {count} hotspots ({ratio:.1f}x baseline) -- reduced flaring?")
            else:
                score = 5.0
                signals.append(f"{name}: {count} hotspots (normal range)")

            # Very high FRP events = infrastructure fires
            if high_frp_count >= 5:
                score = min(10, score + 2.0)
                signals.append(f"  {high_frp_count} high-intensity fire events detected!")
            elif high_frp_count >= 2:
                score = min(10, score + 1.0)
                signals.append(f"  {high_frp_count} high-intensity events")

        except Exception as e:
            logger.warning(f"FIRMS parse error for {region_id}: {e}")
            signals.append(f"{name}: FIRMS parse error")

        return score, signals
