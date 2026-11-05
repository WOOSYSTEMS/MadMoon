"""
MadEye Silver -- Real Interest Rates (Weight: 10%)
FRED DFII10 (10Y TIPS yield) and T10YIE (breakeven inflation).
Silver more sensitive to rate expectations in both directions.
Real rates rising = BEARISH, falling/negative = BULLISH.
"""

import logging
from typing import Dict, Tuple

from .base import BaseCollector

logger = logging.getLogger("madeye.silver")

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"


class RealRatesSilverCollector(BaseCollector):
    name = "real_rates_silver"
    category = "macro"
    cache_ttl = 3600  # 1 hour

    def __init__(self, fred_key: str = ""):
        super().__init__()
        self.fred_key = fred_key or "DEMO_KEY"

    async def collect(self) -> Dict:
        signals = []
        subscores = []

        # --- 1. Real Yield Level (DFII10) ---
        real_score, real_signals = await self._check_real_yield()
        subscores.append(real_score)
        signals.extend(real_signals)

        # --- 2. Breakeven Inflation (T10YIE) ---
        bei_score, bei_signals = await self._check_breakeven()
        subscores.append(bei_score)
        signals.extend(bei_signals)

        # --- 3. Rate of Change in Real Yields ---
        roc_score, roc_signals = await self._check_real_yield_roc()
        subscores.append(roc_score)
        signals.extend(roc_signals)

        # Weighted: Real yield level 40%, Breakeven 25%, ROC 35%
        weights = [0.40, 0.25, 0.35]
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
                "real_yield_score": round(real_score, 2),
                "breakeven_score": round(bei_score, 2),
                "roc_score": round(roc_score, 2),
            },
            confidence=confidence,
        )

    async def _fetch_fred(self, series_id: str, limit: int = 30):
        params = {
            "series_id": series_id,
            "api_key": self.fred_key,
            "file_type": "json",
            "sort_order": "desc",
            "limit": str(limit),
        }
        data = await self.fetch_json(
            FRED_BASE, params=params, cache_key=f"fred_{series_id}"
        )
        if data and "observations" in data:
            return data["observations"]
        return None

    def _extract_values(self, obs, max_count=20):
        values = []
        if not obs:
            return values
        for o in obs:
            v = o.get("value", ".")
            if v != ".":
                values.append(float(v))
            if len(values) >= max_count:
                break
        return values

    async def _check_real_yield(self) -> Tuple[float, list]:
        """Check 10Y TIPS real yield level."""
        signals = []
        score = 5.0

        obs = await self._fetch_fred("DFII10", limit=10)
        values = self._extract_values(obs, 5)

        if not values:
            return 5.0, ["Real yield (DFII10): unavailable"]

        current = values[0]
        signals.append(f"10Y Real Yield (TIPS): {current:.2f}%")

        # Silver has INVERSE correlation -0.50 to -0.80
        # Silver more sensitive than gold in both directions
        if current > 2.5:
            score = 1.0
            signals.append("Real yield > 2.5% -- extremely bearish for silver")
        elif current > 2.0:
            score = 2.0
            signals.append("Real yield > 2.0% -- strong bearish headwind")
        elif current > 1.5:
            score = 3.0
            signals.append("Real yield 1.5-2.0% -- moderate bearish")
        elif current > 0.5:
            score = 4.0
            signals.append("Real yield 0.5-1.5% -- mild bearish")
        elif current > 0:
            score = 5.5
            signals.append("Real yield near zero -- neutral to mildly bullish")
        elif current > -0.5:
            score = 7.0
            signals.append("Negative real yield -- bullish for silver")
        else:
            score = 9.0
            signals.append("Deeply negative real yield -- STRONG BULLISH for silver")

        return score, signals

    async def _check_breakeven(self) -> Tuple[float, list]:
        """Check 10Y breakeven inflation rate."""
        signals = []
        score = 5.0

        obs = await self._fetch_fred("T10YIE", limit=10)
        values = self._extract_values(obs, 5)

        if not values:
            return 5.0, ["Breakeven inflation (T10YIE): unavailable"]

        current = values[0]
        signals.append(f"10Y Breakeven Inflation: {current:.2f}%")

        # Rising inflation expectations = bullish for silver (inflation hedge + industrial)
        if current > 3.0:
            score = 8.0
            signals.append("High inflation expectations -- strong bullish silver (inflation hedge)")
        elif current > 2.5:
            score = 6.5
            signals.append("Elevated inflation expectations -- mildly bullish")
        elif current > 2.0:
            score = 5.5
            signals.append("Normal inflation expectations")
        elif current > 1.5:
            score = 4.0
            signals.append("Low inflation expectations -- deflation concern")
        else:
            score = 2.5
            signals.append("Very low inflation expectations -- bearish silver")

        return score, signals

    async def _check_real_yield_roc(self) -> Tuple[float, list]:
        """Check rate of change in real yields -- rapid decline = strongest signal."""
        signals = []
        score = 5.0

        obs = await self._fetch_fred("DFII10", limit=30)
        values = self._extract_values(obs, 20)

        if len(values) < 5:
            return 5.0, ["Real yield ROC: insufficient data"]

        current = values[0]
        week_ago = values[min(4, len(values) - 1)]
        month_ago = values[min(19, len(values) - 1)]

        wow_change = current - week_ago
        mom_change = current - month_ago

        signals.append(f"Real yield change: WoW {wow_change:+.2f}%, MoM {mom_change:+.2f}%")

        # Falling real yields = BULLISH silver
        if mom_change < -0.5:
            score = 9.0
            signals.append("Real yields falling fast -- STRONG BUY signal for silver")
        elif mom_change < -0.25:
            score = 7.5
            signals.append("Real yields declining -- bullish silver")
        elif wow_change < -0.15:
            score = 7.0
            signals.append("Real yields dropping this week -- short-term bullish")
        elif mom_change > 0.5:
            score = 1.5
            signals.append("Real yields surging -- STRONG SELL signal for silver")
        elif mom_change > 0.25:
            score = 3.0
            signals.append("Real yields rising -- bearish silver")
        elif wow_change > 0.15:
            score = 3.5
            signals.append("Real yields up this week -- short-term bearish")
        else:
            score = 5.0

        return score, signals
