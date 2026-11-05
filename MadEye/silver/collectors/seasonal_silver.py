"""
MadEye Silver -- Seasonal Patterns Collector (Weight: 5%)
Monthly patterns + India festival demand + Chinese New Year.
Jan = best month (Chinese New Year), Jun = worst, Jul = 2nd best.
Indian Diwali demand (Oct-Nov).
"""

import logging
from datetime import datetime, timezone
from typing import Dict

from .base import BaseCollector

logger = logging.getLogger("madeye.silver")

# 55-year average monthly returns (1971-2026)
MONTHLY_RETURNS = {
    1: {"avg_return": 3.95, "win_rate": 67, "signal": "STRONGEST month -- Chinese New Year"},
    2: {"avg_return": 2.0, "win_rate": 50, "signal": "Mildly bullish"},
    3: {"avg_return": 0.5, "win_rate": 50, "signal": "Neutral"},
    4: {"avg_return": 1.5, "win_rate": 55, "signal": "Mildly bullish"},
    5: {"avg_return": 0.5, "win_rate": 48, "signal": "Neutral"},
    6: {"avg_return": -2.7, "win_rate": 37, "signal": "WEAKEST month -- avoid"},
    7: {"avg_return": 2.8, "win_rate": 67, "signal": "Second strongest month"},
    8: {"avg_return": 2.0, "win_rate": 50, "signal": "Mildly bullish"},
    9: {"avg_return": 1.0, "win_rate": 52, "signal": "Slightly bullish"},
    10: {"avg_return": 0.5, "win_rate": 50, "signal": "Neutral, Diwali demand starting"},
    11: {"avg_return": 1.0, "win_rate": 52, "signal": "Slightly bullish, Indian festival buying"},
    12: {"avg_return": 0.5, "win_rate": 48, "signal": "Neutral, pre-January positioning"},
}


class SeasonalSilverCollector(BaseCollector):
    name = "seasonal_silver"
    category = "seasonal"
    cache_ttl = 86400  # 24 hours (seasonal data doesn't change)

    async def collect(self) -> Dict:
        signals = []
        subscores = []

        now = datetime.now(timezone.utc)
        month = now.month
        day = now.day

        # --- 1. Monthly Seasonal Pattern ---
        monthly_score, monthly_signals = self._check_monthly(month, day)
        subscores.append(monthly_score)
        signals.extend(monthly_signals)

        # --- 2. Indian Festival Demand ---
        india_score, india_signals = self._check_india_demand(month, day)
        subscores.append(india_score)
        signals.extend(india_signals)

        # --- 3. Q1 Industrial Restocking ---
        restock_score, restock_signals = self._check_restocking(month)
        subscores.append(restock_score)
        signals.extend(restock_signals)

        # Weighted: Monthly 50%, India 25%, Restocking 25%
        weights = [0.50, 0.25, 0.25]
        composite = sum(s * w for s, w in zip(subscores, weights)) / sum(weights)

        if composite >= 6.5:
            direction = "BULLISH"
        elif composite <= 3.5:
            direction = "BEARISH"
        else:
            direction = "NEUTRAL"

        confidence = 0.4  # Seasonal is background signal, never high confidence

        return self.make_result(
            score=composite,
            direction=direction,
            signals=signals,
            details={
                "month": month,
                "monthly_data": MONTHLY_RETURNS.get(month, {}),
                "monthly_score": round(monthly_score, 2),
                "india_score": round(india_score, 2),
                "restocking_score": round(restock_score, 2),
            },
            confidence=confidence,
        )

    def _check_monthly(self, month: int, day: int) -> tuple:
        """Check monthly seasonal pattern."""
        signals = []
        data = MONTHLY_RETURNS.get(month, {})
        avg_ret = data.get("avg_return", 0)
        win_rate = data.get("win_rate", 50)
        note = data.get("signal", "")

        signals.append(f"Month {month}: avg return {avg_ret:+.1f}%, win rate {win_rate}% -- {note}")

        # Map to score
        if avg_ret > 3:
            score = 8.0
            signals.append("Strong seasonal tailwind for silver")
        elif avg_ret > 1.5:
            score = 6.5
            signals.append("Positive seasonal pattern")
        elif avg_ret > 0:
            score = 5.5
        elif avg_ret > -1:
            score = 4.5
        elif avg_ret > -2:
            score = 3.5
            signals.append("Negative seasonal pattern")
        else:
            score = 2.0
            signals.append("Strong seasonal headwind -- worst month for silver")

        # Late-month positioning for next month
        if day >= 25:
            next_month = (month % 12) + 1
            next_data = MONTHLY_RETURNS.get(next_month, {})
            next_ret = next_data.get("avg_return", 0)
            if next_ret > 2:
                score = min(10, score + 1.0)
                signals.append(f"Approaching strong month ({next_month}) -- pre-position bullish")
            elif next_ret < -1:
                score = max(0, score - 0.5)
                signals.append(f"Approaching weak month ({next_month}) -- caution")

        return score, signals

    def _check_india_demand(self, month: int, day: int) -> tuple:
        """Check Indian festival season demand."""
        signals = []
        score = 5.0

        # Diwali silver buying: Oct-Nov (Diwali moves within Oct 15 - Nov 15)
        # Dhanteras (day before Diwali) is THE biggest silver buying day in India
        if month == 10 and day >= 10:
            score = 6.5
            signals.append("Indian Diwali season approaching -- physical silver demand from India")
        elif month == 11 and day <= 20:
            score = 6.5
            signals.append("Indian Diwali/festival season -- silver coin/bar buying active")
        elif month == 1:
            score = 5.5
            signals.append("Makar Sankranti / Pongal -- mild Indian silver buying")
        elif month == 3 or month == 4:
            score = 5.5
            signals.append("Indian wedding season -- some silver jewelry demand")
        else:
            score = 5.0
            signals.append("No major Indian silver buying season")

        return score, signals

    def _check_restocking(self, month: int) -> tuple:
        """Check Q1 industrial restocking cycle."""
        signals = []
        score = 5.0

        if month == 1:
            score = 6.5
            signals.append("Q1 industrial restocking underway -- positive for silver demand")
        elif month == 2:
            score = 6.0
            signals.append("Q1 restocking continuing")
        elif month == 3:
            score = 5.5
            signals.append("End of Q1 restocking period")
        elif month in (6, 7, 8):
            score = 5.5
            signals.append("Peak northern hemisphere industrial activity")
        elif month == 12:
            score = 4.5
            signals.append("Year-end industrial slowdown")
        else:
            score = 5.0
            signals.append("Normal industrial cycle")

        return score, signals
