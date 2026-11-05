"""
MadEye Gold Unified Scoring Engine
Collects all 10 gold factor scores, applies weights, produces trading signal.
Includes day/hour time filter optimized for gold trading sessions.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from collectors.dxy import DXYCollector
from collectors.real_rates import RealRatesCollector
from collectors.treasury import TreasuryCollector
from collectors.central_banks import CentralBanksCollector
from collectors.etf_flows_gold import ETFFlowsGoldCollector
from collectors.geopolitical_gold import GeopoliticalGoldCollector
from collectors.inflation import InflationCollector
from collectors.technical_gold import TechnicalGoldCollector
from collectors.currency_gold import CurrencyGoldCollector
from collectors.seasonal_gold import SeasonalGoldCollector

logger = logging.getLogger("madeye.gold")

DATA_DIR = Path(__file__).parent / "data"

# Gold factor weights (must sum to 100% conceptually)
TIER_WEIGHTS = {
    # Tier 1: Dominant price drivers (35%) -- every 5 min
    "dxy": 5.0,              # 25% -- THE #1 predictor
    "technical_gold": 2.0,    # 10% -- price action confirmation
    # Tier 2: Fundamental macro (40%) -- every 15 min
    "real_rates": 4.0,        # 20% -- real yield competition
    "treasury": 2.0,          # 10% -- nominal yields + curve
    "geopolitical_gold": 2.0, # 10% -- safe haven demand
    # Tier 3: Structural/slower factors (25%) -- every 30 min
    "central_banks": 2.0,     # 10% -- CB buying trend
    "etf_flows_gold": 1.6,    # 8% -- institutional flows
    "inflation": 1.4,         # 7% -- inflation hedge
    "currency_gold": 1.0,     # 5% -- FX correlations
    "seasonal_gold": 1.0,     # 5% -- seasonal patterns
}

# Signal thresholds (gold-specific, calibrated tighter)
SIGNAL_THRESHOLDS = {
    "STRONG_BUY": 12,
    "BUY": 5,
    "WEAK_BUY": 3,
    "HOLD_UPPER": 3,
    "HOLD_LOWER": -3,
    "WEAK_SELL": -3,
    "SELL": -5,
    "STRONG_SELL": -12,
}


class GoldScorer:
    """Unified scoring engine for gold signals."""

    def __init__(self, fred_key: str = None, newsapi_key: str = None,
                 alphavantage_key: str = None):
        self.collectors = {
            "dxy": DXYCollector(fred_key=fred_key),
            "real_rates": RealRatesCollector(fred_key=fred_key),
            "treasury": TreasuryCollector(fred_key=fred_key),
            "central_banks": CentralBanksCollector(newsapi_key=newsapi_key),
            "etf_flows_gold": ETFFlowsGoldCollector(),
            "geopolitical_gold": GeopoliticalGoldCollector(newsapi_key=newsapi_key),
            "inflation": InflationCollector(fred_key=fred_key),
            "technical_gold": TechnicalGoldCollector(),
            "currency_gold": CurrencyGoldCollector(),
            "seasonal_gold": SeasonalGoldCollector(),
        }
        self._last_signal: Optional[Dict] = None
        self._signal_history: List[Dict] = []
        self._load_history()

    def _load_history(self):
        path = DATA_DIR / "signal_history.json"
        if path.exists():
            try:
                with open(path) as f:
                    self._signal_history = json.load(f)
            except Exception:
                self._signal_history = []

    def _save_history(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        path = DATA_DIR / "signal_history.json"
        try:
            history = self._signal_history[-1000:]
            with open(path, "w") as f:
                json.dump(history, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save signal history: {e}")

    async def run_all(self) -> Dict:
        """Run all collectors and produce unified signal."""
        import asyncio

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
            1: ["dxy", "technical_gold"],
            2: ["real_rates", "treasury", "geopolitical_gold"],
            3: ["central_banks", "etf_flows_gold", "inflation", "currency_gold", "seasonal_gold"],
        }

        collector_names = tier_map.get(tier, [])
        tasks = {}
        for name in collector_names:
            if name in self.collectors:
                tasks[name] = asyncio.create_task(self.collectors[name].safe_collect())

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

            # Apply confidence as modifier
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

        net_score = total_weighted_score

        # Apply time filter for gold trading sessions
        time_adj, time_signals = self._compute_time_filter()
        net_score += time_adj
        all_signals.extend(time_signals)

        # Determine action
        if net_score > SIGNAL_THRESHOLDS["STRONG_BUY"]:
            action = "STRONG_BUY"
            action_text = "Strong BUY -- multiple gold factors aligned bullish"
        elif net_score > SIGNAL_THRESHOLDS["BUY"]:
            action = "BUY"
            action_text = "BUY -- net bullish gold signal"
        elif net_score > SIGNAL_THRESHOLDS["WEAK_BUY"]:
            action = "WEAK_BUY"
            action_text = "WEAK BUY -- slight bullish lean"
        elif net_score < SIGNAL_THRESHOLDS["STRONG_SELL"]:
            action = "STRONG_SELL"
            action_text = "Strong SELL -- multiple gold factors aligned bearish"
        elif net_score < SIGNAL_THRESHOLDS["SELL"]:
            action = "SELL"
            action_text = "SELL -- net bearish gold signal"
        elif net_score < SIGNAL_THRESHOLDS["WEAK_SELL"]:
            action = "WEAK_SELL"
            action_text = "WEAK SELL -- slight bearish lean"
        else:
            action = "HOLD"
            action_text = "HOLD -- no clear gold directional signal"

        # Overall confidence
        if total_weight > 0:
            avg_confidence = sum(
                results[n].get("confidence", 0.5) * TIER_WEIGHTS.get(n, 1.0)
                for n in results
            ) / total_weight
        else:
            avg_confidence = 0.0

        # Reasoning
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
        """Compute time-based score adjustment for gold trading.
        Best hours for gold:
        - London session: 3-8 AM ET (08:00-13:00 UTC)
        - NY session: 8:30-11 AM ET (13:30-16:00 UTC)
        - London/NY overlap: 8-11 AM ET (13:00-16:00 UTC) -- BEST
        Avoid:
        - Friday after 2PM ET (19:00 UTC)
        - Weekends
        - Asian lunch (off-hours for major gold moves)
        """
        now = datetime.now(timezone.utc)
        utc_hour = now.hour
        utc_minute = now.minute
        weekday = now.weekday()

        adjustment = 0.0
        signals = []

        # --- Friday after 2PM ET (19:00 UTC) ---
        if weekday == 4 and utc_hour >= 19:
            adjustment = -3.0
            signals.append("TIME: Friday after 2PM ET -- avoid opening gold positions (score -3)")
            return adjustment, signals

        # --- Weekend ---
        if weekday >= 5:
            adjustment = -3.0
            signals.append("TIME: Weekend -- gold markets effectively closed (score -3)")
            return adjustment, signals

        # --- London/NY Overlap (BEST): 13:00-16:00 UTC ---
        if weekday <= 3 and 13 <= utc_hour <= 15:
            adjustment = 1.5
            signals.append(f"TIME: London/NY overlap (UTC {utc_hour}:00) -- PEAK gold liquidity (score +1.5)")
        # --- London Session: 08:00-13:00 UTC ---
        elif weekday <= 4 and 8 <= utc_hour <= 12:
            adjustment = 1.0
            signals.append(f"TIME: London session (UTC {utc_hour}:00) -- high gold liquidity (score +1)")
        # --- NY Morning: 13:00-17:00 UTC ---
        elif weekday <= 4 and 13 <= utc_hour <= 17:
            adjustment = 0.5
            signals.append(f"TIME: NY session (UTC {utc_hour}:00) -- good gold liquidity (score +0.5)")
        # --- Asian session: 00:00-07:00 UTC ---
        elif 0 <= utc_hour <= 7:
            adjustment = -0.5
            signals.append(f"TIME: Asian session (UTC {utc_hour}:00) -- lower gold liquidity (score -0.5)")
        # --- Late US / pre-Asia: 22:00-00:00 UTC ---
        elif utc_hour >= 22:
            adjustment = -1.0
            signals.append(f"TIME: Late session (UTC {utc_hour}:00) -- thin gold market (score -1)")
        else:
            adjustment = 0.0
            signals.append(f"TIME: Normal hours (UTC {utc_hour}:00)")

        return adjustment, signals

    def _save_signal(self, signal: Dict):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        path = DATA_DIR / "current_signal.json"
        try:
            with open(path, "w") as f:
                json.dump(signal, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save signal: {e}")

    def get_current_signal(self) -> Optional[Dict]:
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
        return self._signal_history[-limit:]

    async def close(self):
        for collector in self.collectors.values():
            await collector.close()
