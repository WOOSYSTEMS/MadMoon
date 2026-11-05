"""
MadEye US Crude Oil Exports Collector
Fetches US crude exports from EIA API.
Rising US exports = strong international demand = bullish overall.
Also affects Brent-WTI spread (more exports = narrows spread).
"""

import logging
from typing import Dict, List, Optional

from .base import BaseCollector

logger = logging.getLogger("madeye")

EIA_API_KEY = "hFz7MGqCdj6hbhRTNpLRgGNK7pGbqbkC87JjWgtP"
EIA_EXPORTS_URL = "https://api.eia.gov/v2/petroleum/move/wkly/data/"


class USCrudeExportsCollector(BaseCollector):
    name = "us_crude_exports"
    category = "supply"
    cache_ttl = 7200  # 2 hours (weekly data)

    async def _fetch_exports(self) -> Optional[List[Dict]]:
        """Fetch US crude oil exports from EIA v2 API."""
        params = {
            "api_key": EIA_API_KEY,
            "frequency": "weekly",
            "data[0]": "value",
            "facets[product][]": "EPC0",  # Crude oil exports
            "facets[duoarea][]": "NUS",   # National US
            "sort[0][column]": "period",
            "sort[0][direction]": "desc",
            "offset": 0,
            "length": 52,  # 1 year of weekly data
        }
        data = await self.fetch_json(EIA_EXPORTS_URL, params=params,
                                     cache_key="eia_crude_exports")
        if not data:
            return None
        try:
            return data.get("response", {}).get("data", [])
        except (KeyError, AttributeError):
            return None

    def _analyze_exports(self, records: List[Dict]) -> Dict:
        """Analyze export data for trends and levels."""
        values = []
        for r in records:
            val = r.get("value")
            period = r.get("period", "")
            if val is not None:
                values.append({"value": float(val), "period": period})

        if not values:
            return {"available": False}

        current = values[0]["value"]
        current_period = values[0]["period"]

        # 4-week average
        recent_4 = [v["value"] for v in values[:4]]
        avg_4w = sum(recent_4) / len(recent_4) if recent_4 else current

        # 13-week (quarterly) average
        recent_13 = [v["value"] for v in values[:13]]
        avg_13w = sum(recent_13) / len(recent_13) if recent_13 else current

        # 52-week (annual) average
        all_vals = [v["value"] for v in values]
        avg_52w = sum(all_vals) / len(all_vals) if all_vals else current

        # YoY comparison (roughly 52 weeks ago)
        yoy_val = values[-1]["value"] if len(values) >= 50 else None

        # Trend: are exports rising or falling?
        if len(values) >= 8:
            recent_4w_avg = sum(v["value"] for v in values[:4]) / 4
            prior_4w_avg = sum(v["value"] for v in values[4:8]) / 4
            trend_pct = ((recent_4w_avg - prior_4w_avg) / prior_4w_avg * 100) if prior_4w_avg > 0 else 0
        else:
            trend_pct = 0

        return {
            "available": True,
            "current": current,
            "current_period": current_period,
            "avg_4w": avg_4w,
            "avg_13w": avg_13w,
            "avg_52w": avg_52w,
            "yoy_value": yoy_val,
            "trend_pct": trend_pct,
        }

    async def collect(self) -> Dict:
        signals = []
        score = 5.0
        confidence = 0.3
        details = {}

        records = await self._fetch_exports()
        if not records:
            signals.append("EIA crude exports data unavailable")
            return self.make_result(
                score=5.0, direction="NEUTRAL",
                signals=signals, confidence=0.0,
            )

        analysis = self._analyze_exports(records)

        if not analysis.get("available"):
            signals.append("No usable export data from EIA")
            return self.make_result(
                score=5.0, direction="NEUTRAL",
                signals=signals, confidence=0.1,
            )

        current = analysis["current"]
        avg_4w = analysis["avg_4w"]
        avg_52w = analysis["avg_52w"]

        # EIA exports are in thousand barrels per day (kb/d)
        signals.append(f"US crude exports: {current:.0f} kb/d (week of {analysis['current_period']})")
        signals.append(f"4-week average: {avg_4w:.0f} kb/d")
        signals.append(f"52-week average: {avg_52w:.0f} kb/d")

        details["current_kbpd"] = round(current, 0)
        details["avg_4w_kbpd"] = round(avg_4w, 0)
        details["avg_52w_kbpd"] = round(avg_52w, 0)

        # Relative to annual average
        ratio_to_avg = current / avg_52w if avg_52w > 0 else 1.0

        # Score based on export levels and trends
        # High exports = strong international demand = bullish
        # Record exports = very strong pull from global markets
        if ratio_to_avg > 1.15:
            score = 8.0
            signals.append("Exports well above annual average (>15%) -- strong international demand, bullish")
        elif ratio_to_avg > 1.05:
            score = 7.0
            signals.append("Exports above annual average -- healthy international demand")
        elif ratio_to_avg > 0.95:
            score = 5.0
            signals.append("Exports near annual average -- normal demand")
        elif ratio_to_avg > 0.85:
            score = 3.5
            signals.append("Exports below annual average -- weak international demand")
        else:
            score = 2.5
            signals.append("Exports significantly below average -- very weak international demand, bearish")

        # Trend adjustment
        trend = analysis["trend_pct"]
        details["trend_4w_pct"] = round(trend, 2)
        signals.append(f"4-week trend: {trend:+.1f}%")

        if trend > 10:
            score = min(10, score + 1.0)
            signals.append("Exports surging -- strong bullish signal")
        elif trend > 5:
            score = min(10, score + 0.5)
            signals.append("Exports rising -- mildly bullish")
        elif trend < -10:
            score = max(0, score - 1.0)
            signals.append("Exports dropping sharply -- demand weakening")
        elif trend < -5:
            score = max(0, score - 0.5)
            signals.append("Exports declining -- mildly bearish")

        # YoY comparison
        if analysis["yoy_value"]:
            yoy_change = ((current - analysis["yoy_value"]) / analysis["yoy_value"] * 100)
            signals.append(f"Year-over-year change: {yoy_change:+.1f}%")
            details["yoy_change_pct"] = round(yoy_change, 2)

        confidence = 0.7

        if score >= 6.5:
            direction = "BULLISH"
        elif score <= 3.5:
            direction = "BEARISH"
        else:
            direction = "NEUTRAL"

        return self.make_result(
            score=score,
            direction=direction,
            signals=signals,
            details=details,
            confidence=confidence,
        )
