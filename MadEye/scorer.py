"""
MadEye Unified Scoring Engine
Collects all 14 category scores, applies tier-based weighting, produces trading signal.
Includes day/hour time filter for optimal trade timing.
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from collectors.geopolitical import GeopoliticalCollector
from collectors.supply import SupplyCollector
from collectors.financial import FinancialCollector
from collectors.technical import TechnicalCollector
from collectors.sentiment import SentimentCollector
from collectors.shipping import ShippingCollector
from collectors.satellite import SatelliteCollector
from collectors.weather import WeatherCollector
from collectors.crack_spread import CrackSpreadCollector
from collectors.cross_commodity import CrossCommodityCollector
from collectors.spreads import SpreadsCollector
from collectors.floating_storage import FloatingStorageCollector
from collectors.demand_advanced import DemandAdvancedCollector
from collectors.etf_flows import ETFFlowsCollector

logger = logging.getLogger("madeye")

DATA_DIR = Path(__file__).parent / "data"

# Tier weights from backtest optimization
# Dropped Baker Hughes rigs (near-zero predictive power)
# Boosted: sanctions, Libya/Nigeria disruptions, futures curve, OVX (most predictive)
TIER_WEIGHTS = {
    # Tier 1: Immediate price movers - weight 3x
    "geopolitical": 3.0,
    "supply": 3.0,
    # Tier 2: Daily/Weekly signals - weight 2-2.5x
    "financial": 2.5,
    "shipping": 2.0,
    "crack_spread": 2.0,       # Directly determines refiner crude demand
    "spreads": 2.0,            # Market structure (contango/backwardation)
    "demand_advanced": 2.0,    # Gasoline demand, refinery util, OPEC spare
    # Tier 3: Sentiment + Technical + Confirmation - weight 1.5-2x
    "sentiment": 2.0,
    "technical": 1.5,
    "cross_commodity": 1.5,    # Confirmation signals (copper, gold, natgas, BDI)
    # Tier 4: Background/structural - weight 0.5-1.5x
    "satellite": 1.5,
    "floating_storage": 1.0,   # Background storage signal
    "etf_flows": 1.0,          # Institutional flow tracking
    "weather": 0.5,
}

# Signal thresholds
SIGNAL_THRESHOLDS = {
    "STRONG_BUY": 15,
    "BUY": 8,
    "HOLD_UPPER": 7,
    "HOLD_LOWER": -5,
    "SELL": -5,
    "STRONG_SELL": -15,
}


class MadEyeScorer:
    """Unified scoring engine that runs all 14 collectors and produces a trading signal."""

    def __init__(self, eia_key: str = None, fred_key: str = None,
                 newsapi_key: str = None, alphavantage_key: str = None):
        self.collectors = {
            # Original 8
            "geopolitical": GeopoliticalCollector(newsapi_key=newsapi_key),
            "supply": SupplyCollector(eia_key=eia_key),
            "financial": FinancialCollector(fred_key=fred_key, alphavantage_key=alphavantage_key),
            "technical": TechnicalCollector(),
            "sentiment": SentimentCollector(fred_key=fred_key, newsapi_key=newsapi_key),
            "shipping": ShippingCollector(newsapi_key=newsapi_key),
            "satellite": SatelliteCollector(),
            "weather": WeatherCollector(),
            # New 6 from counter-check
            "crack_spread": CrackSpreadCollector(),
            "cross_commodity": CrossCommodityCollector(fred_key=fred_key),
            "spreads": SpreadsCollector(),
            "floating_storage": FloatingStorageCollector(newsapi_key=newsapi_key),
            "demand_advanced": DemandAdvancedCollector(eia_key=eia_key),
            "etf_flows": ETFFlowsCollector(),
        }
        self._last_signal: Optional[Dict] = None
        self._signal_history: List[Dict] = []
        self._load_history()

    def _load_history(self):
        """Load signal history from disk."""
        path = DATA_DIR / "signal_history.json"
        if path.exists():
            try:
                with open(path) as f:
                    self._signal_history = json.load(f)
            except Exception:
                self._signal_history = []

    def _save_history(self):
        """Save signal history to disk."""
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        path = DATA_DIR / "signal_history.json"
        try:
            # Keep last 1000 signals
            history = self._signal_history[-1000:]
            with open(path, "w") as f:
                json.dump(history, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save signal history: {e}")

    async def run_all(self) -> Dict:
        """Run all collectors and produce unified signal."""
        import asyncio

        # Run all collectors concurrently
        tasks = {}
        for name, collector in self.collectors.items():
            tasks[name] = asyncio.create_task(collector.safe_collect())

        results = {}
        for name, task in tasks.items():
            results[name] = await task

        return self._compute_signal(results)

    async def run_tier(self, tier: int) -> Dict:
        """Run collectors for a specific tier only."""
        import asyncio

        tier_map = {
            1: ["geopolitical", "supply"],
            2: ["financial", "shipping", "crack_spread", "spreads", "demand_advanced"],
            3: ["technical", "sentiment", "cross_commodity"],
            4: ["weather", "satellite", "floating_storage", "etf_flows"],
        }

        collector_names = tier_map.get(tier, [])
        tasks = {}
        for name in collector_names:
            if name in self.collectors:
                tasks[name] = asyncio.create_task(self.collectors[name].safe_collect())

        # Merge with last known results for other tiers
        results = {}
        for name, collector in self.collectors.items():
            if name in tasks:
                results[name] = await tasks[name]
            elif collector._last_score:
                results[name] = collector._last_score
            else:
                results[name] = {
                    "collector": name,
                    "category": name,
                    "score": 5.0,
                    "direction": "NEUTRAL",
                    "confidence": 0.0,
                    "signals": ["No data yet"],
                    "details": {},
                    "stale": True,
                }

        return self._compute_signal(results)

    def _compute_signal(self, results: Dict) -> Dict:
        """Compute unified signal from all collector results."""
        # Calculate weighted net score
        # Each collector score is 0-10 where 5 = neutral
        # Convert to -5 to +5 range, then apply tier weights

        factor_scores = {}
        total_weighted_score = 0.0
        total_weight = 0.0
        all_signals = []
        bullish_factors = []
        bearish_factors = []

        for name, result in results.items():
            raw_score = result.get("score", 5.0)
            direction = result.get("direction", "NEUTRAL")
            confidence = result.get("confidence", 0.5)
            weight = TIER_WEIGHTS.get(name, 1.0)

            # Convert 0-10 to -5 to +5
            centered_score = raw_score - 5.0

            # Apply confidence as a modifier (low confidence = closer to neutral)
            adjusted_score = centered_score * max(0.2, confidence)

            # Apply tier weight
            weighted_score = adjusted_score * weight

            total_weighted_score += weighted_score
            total_weight += weight

            factor_scores[name] = {
                "raw_score": round(raw_score, 2),
                "centered_score": round(centered_score, 2),
                "weighted_score": round(weighted_score, 2),
                "direction": direction,
                "confidence": round(confidence, 2),
                "tier_weight": weight,
                "signals": result.get("signals", []),
                "details": result.get("details", {}),
                "stale": result.get("stale", False),
                "timestamp": result.get("timestamp", ""),
            }

            all_signals.extend(result.get("signals", []))

            if direction == "BULLISH":
                bullish_factors.append(name)
            elif direction == "BEARISH":
                bearish_factors.append(name)

        # Net score: sum of all weighted scores
        net_score = total_weighted_score

        # Apply time filter
        time_adj, time_signals = self._compute_time_filter()
        net_score += time_adj
        all_signals.extend(time_signals)

        # Determine action
        if net_score > SIGNAL_THRESHOLDS["STRONG_BUY"]:
            action = "STRONG_BUY"
            action_text = "Strong BUY -- multiple factors aligned bullish"
        elif net_score > SIGNAL_THRESHOLDS["BUY"]:
            action = "BUY"
            action_text = "BUY -- net bullish signal"
        elif net_score < SIGNAL_THRESHOLDS["STRONG_SELL"]:
            action = "STRONG_SELL"
            action_text = "Strong SELL -- multiple factors aligned bearish"
        elif net_score < SIGNAL_THRESHOLDS["SELL"]:
            action = "SELL"
            action_text = "SELL -- net bearish signal"
        else:
            action = "HOLD"
            action_text = "HOLD -- no clear directional signal"

        # Overall confidence: weighted average of all collector confidences
        if total_weight > 0:
            avg_confidence = sum(
                results[n].get("confidence", 0.5) * TIER_WEIGHTS.get(n, 1.0)
                for n in results
            ) / total_weight
        else:
            avg_confidence = 0.0

        # Build reasoning
        reasoning_parts = []
        if bullish_factors:
            reasoning_parts.append(f"Bullish: {', '.join(bullish_factors)}")
        if bearish_factors:
            reasoning_parts.append(f"Bearish: {', '.join(bearish_factors)}")
        neutral = [n for n in results if results[n].get("direction") == "NEUTRAL"]
        if neutral:
            reasoning_parts.append(f"Neutral: {', '.join(neutral)}")

        signal = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "action_text": action_text,
            "net_score": round(net_score, 2),
            "confidence": round(avg_confidence, 2),
            "reasoning": " | ".join(reasoning_parts),
            "bullish_factors": bullish_factors,
            "bearish_factors": bearish_factors,
            "factor_scores": factor_scores,
            "thresholds": SIGNAL_THRESHOLDS,
            "time_filter": {
                "adjustment": time_adj,
                "signals": time_signals,
            },
        }

        # Save to disk
        self._last_signal = signal
        self._signal_history.append({
            "timestamp": signal["timestamp"],
            "action": action,
            "net_score": signal["net_score"],
            "confidence": signal["confidence"],
            "bullish_count": len(bullish_factors),
            "bearish_count": len(bearish_factors),
        })
        self._save_signal(signal)
        self._save_history()

        return signal

    def _compute_time_filter(self) -> tuple:
        """Compute time-based score adjustment for trade timing.
        Best hours to open: Mon-Thu 5AM-11AM PT (12:00-18:00 UTC)
        Never open Friday after 12PM PT (19:00 UTC)
        Never open during midnight PT hour (07:00 UTC)
        EIA release: Wed 10:30 AM ET (14:30 UTC) -- wait 15 min after
        Returns (adjustment, signals_list).
        """
        now = datetime.now(timezone.utc)
        utc_hour = now.hour
        utc_minute = now.minute
        weekday = now.weekday()  # 0=Monday ... 6=Sunday

        adjustment = 0.0
        signals = []

        # Convert to PT (UTC-8, ignoring DST for simplicity; UTC-7 during DST)
        # Using UTC-7 for Pacific Daylight Time (most of trading year)
        pt_hour = (utc_hour - 7) % 24

        # --- NEVER OPEN: Friday after 12PM PT (19:00 UTC) ---
        if weekday == 4 and utc_hour >= 19:
            adjustment = -3.0
            signals.append("TIME FILTER: Friday after 12PM PT -- AVOID opening (score -3)")
            return adjustment, signals

        # --- NEVER OPEN: Saturday/Sunday ---
        if weekday >= 5:
            adjustment = -3.0
            signals.append("TIME FILTER: Weekend -- markets closed (score -3)")
            return adjustment, signals

        # --- NEVER OPEN: Midnight PT hour (07:00 UTC) ---
        if utc_hour == 7:
            adjustment = -3.0
            signals.append("TIME FILTER: Midnight PT hour (07:00 UTC) -- worst hour (score -3)")
            return adjustment, signals

        # --- EIA Release Window: Wed 14:30-14:45 UTC (10:30-10:45 AM ET) ---
        if weekday == 2 and utc_hour == 14 and 30 <= utc_minute <= 45:
            adjustment = -2.0
            signals.append("TIME FILTER: EIA release window (Wed 10:30 AM ET) -- wait 15 min (score -2)")
            return adjustment, signals

        # --- BEST HOURS: Mon-Thu 5AM-11AM PT (12:00-18:00 UTC) ---
        if weekday <= 3 and 12 <= utc_hour <= 17:
            adjustment = 1.0
            signals.append(f"TIME FILTER: Optimal trading hours (Mon-Thu 5-11AM PT, UTC {utc_hour}:00) (score +1)")
        # --- POST-EIA: Wed after 14:45 UTC (great volatility) ---
        elif weekday == 2 and utc_hour == 14 and utc_minute > 45:
            adjustment = 1.0
            signals.append("TIME FILTER: Post-EIA release window -- high signal quality (score +1)")
        elif weekday == 2 and utc_hour == 15:
            adjustment = 1.0
            signals.append("TIME FILTER: Post-EIA first hour -- strong signal (score +1)")
        # --- LATE FRIDAY: 12PM PT is cutoff but before that is ok ---
        elif weekday == 4 and utc_hour < 19:
            adjustment = 0.0
            signals.append("TIME FILTER: Friday before cutoff -- normal")
        # --- OVERNIGHT / OFF-HOURS ---
        elif utc_hour < 8 or utc_hour > 22:
            adjustment = -1.0
            signals.append(f"TIME FILTER: Off-hours (UTC {utc_hour}:00) -- reduced liquidity (score -1)")
        else:
            adjustment = 0.0
            signals.append(f"TIME FILTER: Normal hours (UTC {utc_hour}:00)")

        return adjustment, signals

    def _save_signal(self, signal: Dict):
        """Save current signal to disk."""
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        path = DATA_DIR / "current_signal.json"
        try:
            with open(path, "w") as f:
                json.dump(signal, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save signal: {e}")

    def get_current_signal(self) -> Optional[Dict]:
        """Get the last computed signal."""
        if self._last_signal:
            return self._last_signal
        path = DATA_DIR / "current_signal.json"
        if path.exists():
            try:
                with open(path) as f:
                    return json.load(f)
            except Exception:
                return None
        return None

    def get_history(self, limit: int = 100) -> List[Dict]:
        """Get signal history."""
        return self._signal_history[-limit:]

    async def close(self):
        """Close all collector HTTP clients."""
        for collector in self.collectors.values():
            await collector.close()
