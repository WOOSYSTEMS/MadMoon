"""
MadEye Silver Scoring Engine
10 factors, weighted. Gold/silver ratio is the unique edge.
When ratio > 85 AND gold is bullish AND DXY falling = STRONG BUY silver.
Day/hour filter for optimal trade timing.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from collectors.gold_silver_ratio import GoldSilverRatioCollector
from collectors.industrial_demand import IndustrialDemandCollector
from collectors.dxy_silver import DXYSilverCollector
from collectors.real_rates_silver import RealRatesSilverCollector
from collectors.etf_flows_silver import ETFFlowsSilverCollector
from collectors.comex_silver import COMEXSilverCollector
from collectors.geopolitical_silver import GeopoliticalSilverCollector
from collectors.technical_silver import TechnicalSilverCollector
from collectors.copper_correlation import CopperCorrelationCollector
from collectors.seasonal_silver import SeasonalSilverCollector

logger = logging.getLogger("madeye.silver")

DATA_DIR = Path(__file__).parent / "data"

# Factor weights -- must sum to ~100% conceptually
# Gold/Silver Ratio is THE unique edge (20%)
FACTOR_WEIGHTS = {
    "gold_silver_ratio":    3.0,   # 20% -- THE key signal
    "industrial_demand":    2.25,  # 15%
    "dxy_silver":          1.8,   # 12%
    "real_rates_silver":   1.5,   # 10%
    "etf_flows_silver":    1.5,   # 10%
    "technical_silver":    1.5,   # 10%
    "comex_silver":        1.2,   # 8%
    "geopolitical_silver": 1.2,   # 8%
    "copper_correlation":  1.05,  # 7%
    "seasonal_silver":     0.75,  # 5% (background, timing)
}

# Signal thresholds
SIGNAL_THRESHOLDS = {
    "STRONG_BUY": 12,
    "BUY": 8,
    "HOLD_UPPER": 7,
    "HOLD_LOWER": -5,
    "SELL": -5,
    "STRONG_SELL": -12,
}


class SilverScorer:
    """Unified silver scoring engine: 10 collectors, weighted composite signal."""

    def __init__(self, newsapi_key: str = "", fred_key: str = "",
                 alphavantage_key: str = ""):
        self.collectors = {
            "gold_silver_ratio": GoldSilverRatioCollector(),
            "industrial_demand": IndustrialDemandCollector(
                newsapi_key=newsapi_key, fred_key=fred_key
            ),
            "dxy_silver": DXYSilverCollector(fred_key=fred_key),
            "real_rates_silver": RealRatesSilverCollector(fred_key=fred_key),
            "etf_flows_silver": ETFFlowsSilverCollector(newsapi_key=newsapi_key),
            "comex_silver": COMEXSilverCollector(newsapi_key=newsapi_key),
            "geopolitical_silver": GeopoliticalSilverCollector(newsapi_key=newsapi_key),
            "technical_silver": TechnicalSilverCollector(),
            "copper_correlation": CopperCorrelationCollector(),
            "seasonal_silver": SeasonalSilverCollector(),
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
        """Run all 10 collectors and produce unified signal."""
        import asyncio

        tasks = {}
        for name, collector in self.collectors.items():
            tasks[name] = asyncio.create_task(collector.safe_collect())

        results = {}
        for name, task in tasks.items():
            results[name] = await task

        return self._compute_signal(results)

    async def run_tier(self, tier: int) -> Dict:
        """Run collectors for a specific tier."""
        import asyncio

        tier_map = {
            1: ["gold_silver_ratio", "dxy_silver", "real_rates_silver"],
            2: ["industrial_demand", "copper_correlation", "technical_silver"],
            3: ["etf_flows_silver", "comex_silver", "geopolitical_silver", "seasonal_silver"],
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
                    "collector": name, "category": name,
                    "score": 5.0, "direction": "NEUTRAL",
                    "confidence": 0.0, "signals": ["No data yet"],
                    "details": {}, "stale": True,
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
            weight = FACTOR_WEIGHTS.get(name, 1.0)

            centered_score = raw_score - 5.0
            adjusted_score = centered_score * max(0.2, confidence)
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

        # --- COMBO BONUS: GSR > 85 AND gold bullish AND DXY falling ---
        gsr_details = results.get("gold_silver_ratio", {}).get("details", {})
        dxy_dir = results.get("dxy_silver", {}).get("direction", "NEUTRAL")
        gsr_ratio = gsr_details.get("current_ratio", 70)

        if gsr_ratio > 85 and dxy_dir == "BULLISH":
            combo_bonus = 3.0
            net_score += combo_bonus
            all_signals.append(f"COMBO BONUS +{combo_bonus}: GSR > 85 ({gsr_ratio:.1f}) AND DXY falling -- STRONG BUY silver")

        if gsr_ratio > 90 and dxy_dir == "BULLISH":
            # Extra bonus for extreme ratio with DXY falling
            extra_bonus = 2.0
            net_score += extra_bonus
            all_signals.append(f"EXTREME COMBO +{extra_bonus}: GSR > 90 with weak dollar -- historically massive silver rallies")

        # Apply time filter
        time_adj, time_signals = self._compute_time_filter()
        net_score += time_adj
        all_signals.extend(time_signals)

        # Determine action
        if net_score > SIGNAL_THRESHOLDS["STRONG_BUY"]:
            action = "STRONG_BUY"
            action_text = "Strong BUY SILVER -- multiple factors aligned bullish"
        elif net_score > SIGNAL_THRESHOLDS["BUY"]:
            action = "BUY"
            action_text = "BUY SILVER -- net bullish signal"
        elif net_score < SIGNAL_THRESHOLDS["STRONG_SELL"]:
            action = "STRONG_SELL"
            action_text = "Strong SELL SILVER -- multiple factors aligned bearish"
        elif net_score < SIGNAL_THRESHOLDS["SELL"]:
            action = "SELL"
            action_text = "SELL SILVER -- net bearish signal"
        else:
            action = "HOLD"
            action_text = "HOLD -- no clear directional signal"

        # Confidence
        if total_weight > 0:
            avg_confidence = sum(
                results[n].get("confidence", 0.5) * FACTOR_WEIGHTS.get(n, 1.0)
                for n in results
            ) / total_weight
        else:
            avg_confidence = 0.0

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
            "gsr_ratio": round(gsr_ratio, 2),
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
            "gsr_ratio": round(gsr_ratio, 2),
            "bullish_count": len(bullish_factors),
            "bearish_count": len(bearish_factors),
        })
        self._save_signal(signal)
        self._save_history()

        return signal

    def _compute_time_filter(self) -> tuple:
        """Same time filter as oil -- best Mon-Thu 5AM-11AM PT."""
        now = datetime.now(timezone.utc)
        utc_hour = now.hour
        utc_minute = now.minute
        weekday = now.weekday()

        adjustment = 0.0
        signals = []
        pt_hour = (utc_hour - 7) % 24

        if weekday == 4 and utc_hour >= 19:
            return -3.0, ["TIME FILTER: Friday after 12PM PT -- AVOID (score -3)"]
        if weekday >= 5:
            return -3.0, ["TIME FILTER: Weekend -- markets closed (score -3)"]
        if utc_hour == 7:
            return -3.0, ["TIME FILTER: Midnight PT hour -- worst hour (score -3)"]

        if weekday <= 3 and 12 <= utc_hour <= 17:
            adjustment = 1.0
            signals.append(f"TIME FILTER: Optimal trading hours (Mon-Thu, UTC {utc_hour}:00) (+1)")
        elif utc_hour < 8 or utc_hour > 22:
            adjustment = -1.0
            signals.append(f"TIME FILTER: Off-hours (UTC {utc_hour}:00) -- reduced liquidity (-1)")
        else:
            signals.append(f"TIME FILTER: Normal hours (UTC {utc_hour}:00)")

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
