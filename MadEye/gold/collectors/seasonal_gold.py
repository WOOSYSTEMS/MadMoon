"""
MadEye Gold -- Seasonal & Cultural Demand Collector
Monthly gold price patterns + Indian/Chinese demand calendar.
Jan +1.8%, Aug +1.5%, Sep +1.2% historically best months.
Indian wedding season (Oct-Dec, Apr-May) = structural demand.
Weight: 5% of total signal.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Tuple

from .base import BaseCollector

logger = logging.getLogger("madeye.gold")

# Historical monthly gold returns (average %, based on 50-year data)
MONTHLY_SEASONALITY = {
    1: {"avg_return": 1.8, "name": "January", "note": "Post-holiday buying, portfolio rebalancing"},
    2: {"avg_return": -0.2, "name": "February", "note": "Quiet month, post-CNY lull"},
    3: {"avg_return": -0.1, "name": "March", "note": "Quarter-end rebalancing"},
    4: {"avg_return": 0.7, "name": "April", "note": "Indian Akshaya Tritiya month"},
    5: {"avg_return": 0.3, "name": "May", "note": "Indian wedding season tail"},
    6: {"avg_return": -0.3, "name": "June", "note": "Summer doldrums begin"},
    7: {"avg_return": 0.5, "name": "July", "note": "Mid-year positioning"},
    8: {"avg_return": 1.5, "name": "August", "note": "Pre-India season buying + summer rally"},
    9: {"avg_return": 1.2, "name": "September", "note": "India festival season begins"},
    10: {"avg_return": 0.3, "name": "October", "note": "Diwali demand peak"},
    11: {"avg_return": 0.6, "name": "November", "note": "Indian wedding season + year-end"},
    12: {"avg_return": 0.8, "name": "December", "note": "Chinese pre-CNY buying begins"},
}

# Key cultural demand events (approximate dates, varies by year)
# 2026 dates
CULTURAL_EVENTS_2026 = [
    {"name": "Chinese New Year", "month": 2, "day_range": (10, 20), "impact": "bullish", "weight": 1.5,
     "note": "Heavy gold gifting tradition, buying peaks 2 weeks before"},
    {"name": "Akshaya Tritiya", "month": 4, "day_range": (20, 30), "impact": "bullish", "weight": 1.5,
     "note": "Most auspicious day to buy gold in India"},
    {"name": "Indian Wedding Season Start", "month": 10, "day_range": (1, 15), "impact": "bullish", "weight": 1.0,
     "note": "Oct-Dec wedding season drives physical demand"},
    {"name": "Diwali/Dhanteras", "month": 10, "day_range": (18, 25), "impact": "bullish", "weight": 2.0,
     "note": "Dhanteras: biggest single gold-buying day globally"},
    {"name": "Thanksgiving/Black Friday", "month": 11, "day_range": (25, 30), "impact": "neutral", "weight": 0.5,
     "note": "US gold coin/jewelry sales"},
    {"name": "Chinese Pre-CNY", "month": 12, "day_range": (15, 31), "impact": "bullish", "weight": 1.0,
     "note": "Gold buying ramps up before Lunar New Year"},
]


class SeasonalGoldCollector(BaseCollector):
    name = "seasonal_gold"
    category = "seasonal"
    cache_ttl = 3600  # 1 hour (changes slowly)

    async def collect(self) -> Dict:
        signals = []
        subscores = []

        now = datetime.now(timezone.utc)

        # --- 1. Monthly seasonality ---
        monthly_score, monthly_signals = self._analyze_monthly_pattern(now)
        subscores.append(("monthly", monthly_score, 0.40))
        signals.extend(monthly_signals)

        # --- 2. Cultural demand events ---
        cultural_score, cultural_signals = self._analyze_cultural_events(now)
        subscores.append(("cultural", cultural_score, 0.35))
        signals.extend(cultural_signals)

        # --- 3. Day of week pattern ---
        dow_score, dow_signals = self._analyze_day_of_week(now)
        subscores.append(("day_of_week", dow_score, 0.15))
        signals.extend(dow_signals)

        # --- 4. Quarter-end effects ---
        qtr_score, qtr_signals = self._analyze_quarter_effects(now)
        subscores.append(("quarter", qtr_score, 0.10))
        signals.extend(qtr_signals)

        total_weight = sum(w for _, _, w in subscores)
        composite = sum(s * w for _, s, w in subscores) / total_weight if total_weight > 0 else 5.0

        if composite >= 6.5:
            direction = "BULLISH"
        elif composite <= 3.5:
            direction = "BEARISH"
        else:
            direction = "NEUTRAL"

        confidence = 0.6  # Seasonal is statistical, moderate confidence

        return self.make_result(
            score=composite,
            direction=direction,
            signals=signals,
            details={
                "monthly_score": round(monthly_score, 2),
                "cultural_score": round(cultural_score, 2),
                "dow_score": round(dow_score, 2),
                "quarter_score": round(qtr_score, 2),
                "month": now.month,
                "day": now.day,
                "weekday": now.strftime("%A"),
            },
            confidence=confidence,
        )

    def _analyze_monthly_pattern(self, now: datetime) -> Tuple[float, List[str]]:
        """Score based on historical monthly gold performance."""
        signals = []
        month = now.month
        data = MONTHLY_SEASONALITY.get(month, {})

        avg_return = data.get("avg_return", 0)
        name = data.get("name", "")
        note = data.get("note", "")

        signals.append(f"{name} avg gold return: {avg_return:+.1f}%")
        if note:
            signals.append(f"Seasonal note: {note}")

        # Convert return to score (0-10 scale)
        # +1.8% best -> 8.5, -0.3% worst -> 3.5
        score = 5.0 + (avg_return / 1.8) * 3.5
        score = max(2.0, min(9.0, score))

        return score, signals

    def _analyze_cultural_events(self, now: datetime) -> Tuple[float, List[str]]:
        """Check proximity to major gold demand events."""
        signals = []
        score = 5.0
        month = now.month
        day = now.day

        active_events = []
        upcoming_events = []

        for event in CULTURAL_EVENTS_2026:
            e_month = event["month"]
            day_start, day_end = event["day_range"]

            if e_month == month and day_start <= day <= day_end:
                active_events.append(event)
            elif (e_month == month and day < day_start and day_start - day <= 14) or \
                 (e_month == month + 1 and day > 15):
                upcoming_events.append(event)

        if active_events:
            best = max(active_events, key=lambda e: e["weight"])
            score = 5.0 + best["weight"] * 2.0
            score = min(9.5, score)
            for event in active_events:
                signals.append(f"ACTIVE: {event['name']} -- {event['note']}")
        elif upcoming_events:
            score = 6.0
            for event in upcoming_events:
                signals.append(f"UPCOMING: {event['name']} -- pre-event buying expected")
        else:
            # Check if in a strong demand quarter
            if month in [10, 11, 12]:
                score = 6.5
                signals.append("Q4: Indian wedding + festival season -- structural demand")
            elif month in [1, 2]:
                score = 6.0
                signals.append("Q1 start: CNY season + new year flows")
            elif month in [4, 5]:
                score = 6.0
                signals.append("Akshaya Tritiya / wedding season window")
            else:
                score = 4.5
                signals.append("No major cultural demand event nearby")

        return score, signals

    def _analyze_day_of_week(self, now: datetime) -> Tuple[float, List[str]]:
        """Gold tends to have specific day-of-week patterns."""
        signals = []
        weekday = now.weekday()

        # Historical pattern: Monday often weak (profit-taking), Friday often weak (risk reduction)
        # Tuesday-Thursday tend to be stronger
        day_scores = {
            0: (4.5, "Monday: historically weaker gold day (profit-taking)"),
            1: (5.5, "Tuesday: normal trading day"),
            2: (5.5, "Wednesday: normal trading day"),
            3: (5.5, "Thursday: normal trading day"),
            4: (4.0, "Friday: position reduction before weekend"),
            5: (5.0, "Saturday: markets closed"),
            6: (5.0, "Sunday: markets closed"),
        }

        score, note = day_scores.get(weekday, (5.0, ""))
        if note:
            signals.append(note)

        return score, signals

    def _analyze_quarter_effects(self, now: datetime) -> Tuple[float, List[str]]:
        """Quarter-end rebalancing and options expiry effects."""
        signals = []
        score = 5.0
        month = now.month
        day = now.day

        # Last 5 trading days of quarter tend to see rebalancing
        if month in [3, 6, 9, 12] and day >= 25:
            score = 4.0
            signals.append("Quarter-end rebalancing -- potential gold selling by funds")
        elif month in [1, 4, 7, 10] and day <= 5:
            score = 6.0
            signals.append("New quarter inflows -- fresh allocation to gold")

        # Options expiry (3rd Friday of each month, especially quarterly)
        if 15 <= day <= 21 and now.weekday() == 4:
            score = max(3.5, score - 0.5)
            signals.append("Options expiry week -- increased volatility, potential pin risk")

        return score, signals
