"""
MadEye Advanced Demand Collector
US gasoline demand (EIA), refinery utilization, OPEC spare capacity, EV adoption impact.
"""

import logging
from typing import Dict, List, Optional

from .base import BaseCollector

logger = logging.getLogger("madeye")

EIA_BASE = "https://api.eia.gov/v2/petroleum/sum/sndw/data/"


def _load_eia_key():
    """Load EIA API key from data file or environment."""
    import os
    key_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "eia_api_key.txt")
    if os.path.exists(key_path):
        with open(key_path) as f:
            return f.read().strip()
    return os.environ.get("EIA_API_KEY", "DEMO_KEY")


class DemandAdvancedCollector(BaseCollector):
    name = "demand_advanced"
    category = "demand_advanced"
    cache_ttl = 3600  # 1 hour

    def __init__(self, eia_key: str = None):
        super().__init__()
        self.eia_key = eia_key or _load_eia_key()

    async def collect(self) -> Dict:
        signals = []
        subscores = []

        # --- 1. US Gasoline Demand ---
        gas_score, gas_signals = await self._check_gasoline_demand()
        subscores.append(gas_score)
        signals.extend(gas_signals)

        # --- 2. Refinery Utilization (EIA) ---
        ref_score, ref_signals = await self._check_refinery_utilization()
        subscores.append(ref_score)
        signals.extend(ref_signals)

        # --- 3. OPEC Spare Capacity ---
        opec_score, opec_signals = self._check_opec_spare_capacity()
        subscores.append(opec_score)
        signals.extend(opec_signals)

        # --- 4. EV Adoption Impact ---
        ev_score, ev_signals = self._check_ev_impact()
        subscores.append(ev_score)
        signals.extend(ev_signals)

        # Weighted: Gasoline demand 35%, Refinery 25%, OPEC spare 25%, EV 15%
        weights = [0.35, 0.25, 0.25, 0.15]
        composite = sum(s * w for s, w in zip(subscores, weights)) / sum(weights)

        if composite >= 6.5:
            direction = "BULLISH"
        elif composite <= 3.5:
            direction = "BEARISH"
        else:
            direction = "NEUTRAL"

        confidence = min(1.0, len([s for s in subscores if s != 5.0]) / max(len(subscores), 1))

        return self.make_result(
            score=composite,
            direction=direction,
            signals=signals,
            details={
                "gasoline_demand_score": round(gas_score, 2),
                "refinery_util_score": round(ref_score, 2),
                "opec_spare_score": round(opec_score, 2),
                "ev_impact_score": round(ev_score, 2),
            },
            confidence=confidence,
        )

    async def _fetch_eia_series(self, series_id: str, length: int = 10) -> Optional[List]:
        """Fetch EIA data series."""
        params = {
            "api_key": self.eia_key,
            "frequency": "weekly",
            "data[0]": "value",
            "facets[series][]": series_id,
            "sort[0][column]": "period",
            "sort[0][direction]": "desc",
            "length": str(length),
        }
        data = await self.fetch_json(
            EIA_BASE, params=params, cache_key=f"eia_demand_{series_id}"
        )
        if data and "response" in data:
            return data["response"].get("data", [])
        return None

    async def _check_gasoline_demand(self) -> tuple:
        """Check US gasoline demand (product supplied) from EIA."""
        signals = []
        score = 5.0

        # WGFUPUS2 = US Finished Motor Gasoline Product Supplied
        records = await self._fetch_eia_series("WGFUPUS2", length=10)
        if not records or len(records) < 2:
            signals.append("Gasoline demand (EIA): data unavailable")
            return score, signals

        try:
            latest = float(records[0].get("value", 0))
            previous = float(records[1].get("value", 0))
            change = latest - previous  # thousands bbl/d

            signals.append(f"US gasoline demand: {latest:.0f}K bbl/d (change: {change:+.0f}K)")

            # Strong demand = bullish
            if latest > 9500:
                score = 8.0
                signals.append("Gasoline demand very strong (>9.5M bbl/d) -- summer peak levels, bullish")
            elif latest > 9000:
                score = 7.0
                signals.append("Gasoline demand above average -- healthy driving season")
            elif latest > 8500:
                score = 5.5
                signals.append("Gasoline demand normal range")
            elif latest > 8000:
                score = 4.0
                signals.append("Gasoline demand below average -- demand concern")
            else:
                score = 2.5
                signals.append("Gasoline demand very weak (<8M bbl/d) -- recession/destruction signal")

            # Week-over-week trend
            if change > 200:
                score = min(10, score + 1.0)
                signals.append(f"Gasoline demand surging (+{change:.0f}K)")
            elif change > 100:
                score = min(10, score + 0.5)
                signals.append("Gasoline demand rising")
            elif change < -200:
                score = max(0, score - 1.0)
                signals.append(f"Gasoline demand dropping ({change:+.0f}K)")
            elif change < -100:
                score = max(0, score - 0.5)

            # 4-week trend
            if len(records) >= 4:
                vals = [float(r.get("value", 0)) for r in records[:4]]
                trend = vals[0] - vals[3]  # latest - 4 weeks ago
                if trend > 500:
                    score = min(10, score + 0.5)
                    signals.append(f"4-week demand trend rising (+{trend:.0f}K)")
                elif trend < -500:
                    score = max(0, score - 0.5)
                    signals.append(f"4-week demand trend falling ({trend:+.0f}K)")

        except (ValueError, TypeError) as e:
            signals.append(f"Gasoline demand parse error: {str(e)[:50]}")

        return score, signals

    async def _check_refinery_utilization(self) -> tuple:
        """Check refinery utilization rate from EIA."""
        signals = []
        score = 5.0

        records = await self._fetch_eia_series("WPULEUS3", length=5)
        if not records or len(records) < 1:
            signals.append("Refinery utilization (adv): unavailable")
            return score, signals

        try:
            latest = float(records[0].get("value", 0))
            signals.append(f"Refinery utilization: {latest:.1f}%")

            # High utilization = strong demand pulling crude = bullish
            if latest > 95:
                score = 8.5
                signals.append("Refineries maxed out (>95%) -- very tight, bullish")
            elif latest > 93:
                score = 7.0
                signals.append("High utilization -- strong crude demand from refiners")
            elif latest > 90:
                score = 6.0
                signals.append("Above-average utilization")
            elif latest > 87:
                score = 4.5
                signals.append("Below-average utilization -- seasonal or demand issue")
            elif latest > 82:
                score = 3.0
                signals.append("Low utilization -- turnaround season or weak demand")
            else:
                score = 2.0
                signals.append("Very low utilization (<82%) -- severe demand destruction")

            # Week-over-week change
            if len(records) >= 2:
                prev = float(records[1].get("value", 0))
                change = latest - prev
                if change > 2:
                    score = min(10, score + 0.5)
                    signals.append(f"Utilization jumping ({change:+.1f}pp)")
                elif change < -2:
                    score = max(0, score - 0.5)
                    signals.append(f"Utilization dropping ({change:+.1f}pp)")

        except (ValueError, TypeError) as e:
            signals.append(f"Refinery utilization parse error: {str(e)[:50]}")

        return score, signals

    def _check_opec_spare_capacity(self) -> tuple:
        """Estimate OPEC spare capacity impact.
        Hardcoded baseline ~3-4M bbl/d as of late 2026.
        Low spare capacity = higher risk premium = bullish.
        """
        signals = []

        # Current estimate: ~3.5M bbl/d spare capacity (Saudi ~2M, UAE ~0.5M, others ~1M)
        # This should be updated periodically from OPEC reports
        spare_capacity_mbd = 3.5

        signals.append(f"OPEC spare capacity estimate: ~{spare_capacity_mbd:.1f}M bbl/d")

        if spare_capacity_mbd < 1.5:
            score = 9.0
            signals.append("OPEC spare capacity critically low (<1.5M) -- extreme risk premium, very bullish")
        elif spare_capacity_mbd < 2.5:
            score = 7.5
            signals.append("OPEC spare capacity tight (<2.5M) -- elevated risk premium")
        elif spare_capacity_mbd < 4.0:
            score = 6.0
            signals.append("OPEC spare capacity moderate -- manageable buffer")
        elif spare_capacity_mbd < 5.5:
            score = 4.5
            signals.append("OPEC spare capacity comfortable -- bearish for risk premium")
        else:
            score = 3.0
            signals.append("OPEC spare capacity very high (>5.5M) -- abundant supply buffer, bearish")

        return score, signals

    def _check_ev_impact(self) -> tuple:
        """EV adoption long-term oil demand impact.
        Currently minor but growing. Score based on trend.
        """
        signals = []

        # EV share of global vehicle sales as of 2026: ~25%
        # Annual oil demand displacement estimate: ~2.5M bbl/d (out of ~100M total)
        # Long-term bearish but short-term negligible
        ev_share = 25  # percent of new vehicle sales
        displacement_mbd = 2.5

        signals.append(f"EV share of new vehicle sales: ~{ev_share}%")
        signals.append(f"Estimated oil demand displacement: ~{displacement_mbd:.1f}M bbl/d")

        # EV is a long-term structural bearish signal
        # But in the short/medium term, ICE fleet still dominates
        if ev_share > 40:
            score = 3.0
            signals.append("EV adoption accelerating past tipping point -- structural bearish")
        elif ev_share > 30:
            score = 3.5
            signals.append("EV share significant -- growing demand headwind")
        elif ev_share > 20:
            score = 4.0
            signals.append("EV share moderate -- mild long-term bearish")
        elif ev_share > 10:
            score = 4.5
            signals.append("EV share small -- minimal near-term impact")
        else:
            score = 5.0
            signals.append("EV share negligible")

        return score, signals
