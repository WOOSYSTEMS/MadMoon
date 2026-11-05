"""
MadEye Regional Refinery Utilization Collector
Fetches PADD district refinery utilization from EIA API.
Gulf Coast (PADD 3) = ~50% of US refining capacity.
Low utilization = maintenance/hurricane = bullish oil (less product supply).
"""

import logging
from typing import Dict, List, Optional, Tuple

from .base import BaseCollector

logger = logging.getLogger("madeye")

EIA_API_URL = "https://api.eia.gov/v2/petroleum/pnp/wiup/data/"
EIA_API_KEY = "hFz7MGqCdj6hbhRTNpLRgGNK7pGbqbkC87JjWgtP"

# PADD district series IDs for refinery utilization (percent)
# EIA v2 API uses different query structure
PADD_DISTRICTS = {
    "PADD 1 (East Coast)": {"weight": 0.10, "duoarea": "R10"},
    "PADD 2 (Midwest)": {"weight": 0.20, "duoarea": "R20"},
    "PADD 3 (Gulf Coast)": {"weight": 0.50, "duoarea": "R30"},
    "PADD 4 (Rocky Mountain)": {"weight": 0.05, "duoarea": "R40"},
    "PADD 5 (West Coast)": {"weight": 0.15, "duoarea": "R50"},
}


class RefineryRegionalCollector(BaseCollector):
    name = "refinery_regional"
    category = "supply"
    cache_ttl = 7200  # 2 hours (EIA data updates weekly)

    async def _fetch_utilization(self) -> Optional[List[Dict]]:
        """Fetch refinery utilization data from EIA v2 API."""
        params = {
            "api_key": EIA_API_KEY,
            "frequency": "weekly",
            "data[0]": "value",
            "facets[process][]": "YOP",  # Operable utilization
            "sort[0][column]": "period",
            "sort[0][direction]": "desc",
            "offset": 0,
            "length": 50,
        }
        data = await self.fetch_json(EIA_API_URL, params=params,
                                     cache_key="eia_refinery_util")
        if not data:
            return None
        try:
            return data.get("response", {}).get("data", [])
        except (KeyError, AttributeError):
            return None

    def _process_utilization(self, records: List[Dict]) -> Dict:
        """Process EIA records into PADD utilization data."""
        padd_data = {}

        for record in records:
            area = record.get("duoarea", "")
            value = record.get("value")
            period = record.get("period", "")

            if value is None:
                continue

            for name, info in PADD_DISTRICTS.items():
                if info["duoarea"] == area:
                    if name not in padd_data:
                        padd_data[name] = {
                            "current": float(value),
                            "period": period,
                            "history": [],
                        }
                    padd_data[name]["history"].append(float(value))

        return padd_data

    def _score_utilization(self, util_pct: float) -> Tuple[float, str]:
        """Score refinery utilization.
        High utilization (>93%) = refiners running hard, buying crude = bullish
        Low utilization (<85%) = maintenance/demand destruction
        - Short term: bullish (less product supply)
        - Medium term: bearish (less crude demand)
        """
        if util_pct > 95:
            return 8.5, "very high utilization -- refiners maxed out, bullish crude demand"
        elif util_pct > 93:
            return 7.5, "high utilization -- strong crude demand"
        elif util_pct > 90:
            return 6.0, "above-average utilization"
        elif util_pct > 87:
            return 5.0, "normal utilization"
        elif util_pct > 83:
            return 6.5, "below-average utilization -- less product supply, near-term bullish"
        elif util_pct > 78:
            return 7.0, "low utilization -- likely maintenance/weather, supply squeeze possible"
        else:
            return 7.5, "very low utilization -- major disruption, product supply crunch"

    async def collect(self) -> Dict:
        signals = []
        confidence = 0.3

        records = await self._fetch_utilization()

        if not records:
            # Fallback: try simple series approach
            signals.append("EIA refinery utilization data unavailable")
            return self.make_result(
                score=5.0, direction="NEUTRAL",
                signals=signals, confidence=0.0,
            )

        padd_data = self._process_utilization(records)

        if not padd_data:
            signals.append("No PADD utilization data parsed from EIA")
            return self.make_result(
                score=5.0, direction="NEUTRAL",
                signals=signals, confidence=0.1,
            )

        weighted_score = 0.0
        total_weight = 0.0
        details = {}

        for name, info in PADD_DISTRICTS.items():
            if name in padd_data:
                util = padd_data[name]["current"]
                period = padd_data[name]["period"]
                weight = info["weight"]

                s, desc = self._score_utilization(util)
                weighted_score += s * weight
                total_weight += weight

                signals.append(f"{name}: {util:.1f}% (week {period}) -- {desc}")
                details[name] = {
                    "utilization": util,
                    "period": period,
                    "score": round(s, 2),
                }

                # Trend from history
                hist = padd_data[name]["history"]
                if len(hist) >= 4:
                    recent = sum(hist[:2]) / 2
                    older = sum(hist[2:4]) / 2
                    trend = recent - older
                    if abs(trend) > 2:
                        signals.append(f"  {name} trend: {trend:+.1f}pp over 2 weeks")

        composite = weighted_score / total_weight if total_weight > 0 else 5.0
        confidence = 0.7 if total_weight > 0.5 else 0.4

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
