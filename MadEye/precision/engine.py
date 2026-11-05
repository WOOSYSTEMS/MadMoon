"""
MadEye Precision Mode Engine
Takes ALL collector scores from oil (14), gold (10), silver (10) = 34 total.
Counts how many score 7+ (bullish) or 3- (bearish).
If 5+ agree AND all confirmations pass -> signal.
"""

import json
import logging
import asyncio
import sys
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Add parent directories to path so we can import from oil/gold/silver scorers
MADEYE_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(MADEYE_ROOT))

logger = logging.getLogger("madeye.precision")

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Minimum collectors that must agree on direction
MIN_AGREEMENT = 5

# Score thresholds for individual collectors (0-10 scale)
BULLISH_THRESHOLD = 7.0   # Score >= 7 = bullish vote
BEARISH_THRESHOLD = 3.0   # Score <= 3 = bearish vote

# Commodity configs
COMMODITIES = {
    "oil": {
        "instrument": "BCO_USD",
        "name": "Brent Crude Oil",
        "yahoo_symbol": "BZ=F",
        "collector_source": "oil",
    },
    "gold": {
        "instrument": "XAU_USD",
        "name": "Gold",
        "yahoo_symbol": "GC=F",
        "collector_source": "gold",
    },
    "silver": {
        "instrument": "XAG_USD",
        "name": "Silver",
        "yahoo_symbol": "SI=F",
        "collector_source": "silver",
    },
}


class PrecisionEngine:
    """Core precision engine that aggregates all collectors across 3 commodities."""

    def __init__(self):
        self._oil_scorer = None
        self._gold_scorer = None
        self._silver_scorer = None
        self._signals: Dict[str, Dict] = {}
        self._signal_history: List[Dict] = []
        self._load_history()

    def _load_history(self):
        path = DATA_DIR / "precision_history.json"
        if path.exists():
            try:
                with open(path) as f:
                    self._signal_history = json.load(f)
            except Exception:
                self._signal_history = []

    def _save_history(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        path = DATA_DIR / "precision_history.json"
        try:
            with open(path, "w") as f:
                json.dump(self._signal_history[-2000:], f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save precision history: {e}")

    async def _get_oil_scores(self) -> Dict[str, Dict]:
        """Get all 14 oil collector scores."""
        if self._oil_scorer is None:
            try:
                oil_path = MADEYE_ROOT
                sys.path.insert(0, str(oil_path))
                # Import oil collectors directly
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

                self._oil_scorer = {
                    "oil_geopolitical": GeopoliticalCollector(),
                    "oil_supply": SupplyCollector(),
                    "oil_financial": FinancialCollector(),
                    "oil_technical": TechnicalCollector(),
                    "oil_sentiment": SentimentCollector(),
                    "oil_shipping": ShippingCollector(),
                    "oil_satellite": SatelliteCollector(),
                    "oil_weather": WeatherCollector(),
                    "oil_crack_spread": CrackSpreadCollector(),
                    "oil_cross_commodity": CrossCommodityCollector(),
                    "oil_spreads": SpreadsCollector(),
                    "oil_floating_storage": FloatingStorageCollector(),
                    "oil_demand_advanced": DemandAdvancedCollector(),
                    "oil_etf_flows": ETFFlowsCollector(),
                }
            except Exception as e:
                logger.error(f"Failed to init oil collectors: {e}")
                return {}

        results = {}
        tasks = {}
        for name, collector in self._oil_scorer.items():
            tasks[name] = asyncio.create_task(collector.safe_collect())
        for name, task in tasks.items():
            try:
                results[name] = await task
            except Exception as e:
                logger.warning(f"Oil collector {name} failed: {e}")
        return results

    async def _get_gold_scores(self) -> Dict[str, Dict]:
        """Get all 10 gold collector scores."""
        if self._gold_scorer is None:
            try:
                gold_path = MADEYE_ROOT / "gold"
                sys.path.insert(0, str(gold_path))
                from gold.collectors.dxy import DXYCollector
                from gold.collectors.real_rates import RealRatesCollector
                from gold.collectors.treasury import TreasuryCollector
                from gold.collectors.central_banks import CentralBanksCollector
                from gold.collectors.etf_flows_gold import ETFFlowsGoldCollector
                from gold.collectors.geopolitical_gold import GeopoliticalGoldCollector
                from gold.collectors.inflation import InflationCollector
                from gold.collectors.technical_gold import TechnicalGoldCollector
                from gold.collectors.currency_gold import CurrencyGoldCollector
                from gold.collectors.seasonal_gold import SeasonalGoldCollector

                self._gold_scorer = {
                    "gold_dxy": DXYCollector(),
                    "gold_real_rates": RealRatesCollector(),
                    "gold_treasury": TreasuryCollector(),
                    "gold_central_banks": CentralBanksCollector(),
                    "gold_etf_flows": ETFFlowsGoldCollector(),
                    "gold_geopolitical": GeopoliticalGoldCollector(),
                    "gold_inflation": InflationCollector(),
                    "gold_technical": TechnicalGoldCollector(),
                    "gold_currency": CurrencyGoldCollector(),
                    "gold_seasonal": SeasonalGoldCollector(),
                }
            except Exception as e:
                logger.error(f"Failed to init gold collectors: {e}")
                return {}

        results = {}
        tasks = {}
        for name, collector in self._gold_scorer.items():
            tasks[name] = asyncio.create_task(collector.safe_collect())
        for name, task in tasks.items():
            try:
                results[name] = await task
            except Exception as e:
                logger.warning(f"Gold collector {name} failed: {e}")
        return results

    async def _get_silver_scores(self) -> Dict[str, Dict]:
        """Get all 10 silver collector scores."""
        if self._silver_scorer is None:
            try:
                silver_path = MADEYE_ROOT / "silver"
                sys.path.insert(0, str(silver_path))
                from silver.collectors.gold_silver_ratio import GoldSilverRatioCollector
                from silver.collectors.industrial_demand import IndustrialDemandCollector
                from silver.collectors.dxy_silver import DXYSilverCollector
                from silver.collectors.real_rates_silver import RealRatesSilverCollector
                from silver.collectors.etf_flows_silver import ETFFlowsSilverCollector
                from silver.collectors.comex_silver import COMEXSilverCollector
                from silver.collectors.geopolitical_silver import GeopoliticalSilverCollector
                from silver.collectors.technical_silver import TechnicalSilverCollector
                from silver.collectors.copper_correlation import CopperCorrelationCollector
                from silver.collectors.seasonal_silver import SeasonalSilverCollector

                self._silver_scorer = {
                    "silver_gold_ratio": GoldSilverRatioCollector(),
                    "silver_industrial": IndustrialDemandCollector(),
                    "silver_dxy": DXYSilverCollector(),
                    "silver_real_rates": RealRatesSilverCollector(),
                    "silver_etf_flows": ETFFlowsSilverCollector(),
                    "silver_comex": COMEXSilverCollector(),
                    "silver_geopolitical": GeopoliticalSilverCollector(),
                    "silver_technical": TechnicalSilverCollector(),
                    "silver_copper": CopperCorrelationCollector(),
                    "silver_seasonal": SeasonalSilverCollector(),
                }
            except Exception as e:
                logger.error(f"Failed to init silver collectors: {e}")
                return {}

        results = {}
        tasks = {}
        for name, collector in self._silver_scorer.items():
            tasks[name] = asyncio.create_task(collector.safe_collect())
        for name, task in tasks.items():
            try:
                results[name] = await task
            except Exception as e:
                logger.warning(f"Silver collector {name} failed: {e}")
        return results

    def _count_votes(self, scores: Dict[str, Dict]) -> Tuple[int, int, List[str], List[str]]:
        """Count bullish and bearish votes from collector scores.
        Returns (bullish_count, bearish_count, bullish_names, bearish_names)"""
        bullish_count = 0
        bearish_count = 0
        bullish_names = []
        bearish_names = []

        for name, result in scores.items():
            score = result.get("score", 5.0)
            if score >= BULLISH_THRESHOLD:
                bullish_count += 1
                bullish_names.append(f"{name}({score:.1f})")
            elif score <= BEARISH_THRESHOLD:
                bearish_count += 1
                bearish_names.append(f"{name}({score:.1f})")

        return bullish_count, bearish_count, bullish_names, bearish_names

    async def evaluate_commodity(self, commodity: str, confirmations_checker=None) -> Dict:
        """Evaluate precision signal for a single commodity.

        Args:
            commodity: 'oil', 'gold', or 'silver'
            confirmations_checker: Optional confirmations module with check functions
        """
        config = COMMODITIES.get(commodity)
        if not config:
            return {"commodity": commodity, "signal": "NONE", "error": "Unknown commodity"}

        # Gather all collector scores for this commodity
        if commodity == "oil":
            scores = await self._get_oil_scores()
        elif commodity == "gold":
            scores = await self._get_gold_scores()
        elif commodity == "silver":
            scores = await self._get_silver_scores()
        else:
            scores = {}

        total_collectors = len(scores)
        if total_collectors == 0:
            return {
                "commodity": commodity,
                "instrument": config["instrument"],
                "signal": "NONE",
                "reason": "No collector data available",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        # Count votes
        bullish_count, bearish_count, bullish_names, bearish_names = self._count_votes(scores)

        # Determine direction
        direction = None
        n_agreeing = 0
        voters = []

        if bullish_count >= MIN_AGREEMENT:
            direction = "BUY"
            n_agreeing = bullish_count
            voters = bullish_names
        elif bearish_count >= MIN_AGREEMENT:
            direction = "SELL"
            n_agreeing = bearish_count
            voters = bearish_names

        # Run confirmations if we have a direction candidate
        confirmations_passed = True
        confirmation_details = {}

        if direction and confirmations_checker:
            try:
                yahoo_symbol = config["yahoo_symbol"]

                # 1. DXY confirmation
                dxy_ok = await confirmations_checker.check_dxy(direction, commodity)
                confirmation_details["dxy"] = dxy_ok
                if not dxy_ok:
                    confirmations_passed = False

                # 2. Technical (price vs 4h MA)
                tech_ok = await confirmations_checker.check_technical(direction, yahoo_symbol)
                confirmation_details["technical"] = tech_ok
                if not tech_ok:
                    confirmations_passed = False

                # 3. Momentum (4h ROC)
                mom_ok = await confirmations_checker.check_momentum(direction, yahoo_symbol)
                confirmation_details["momentum"] = mom_ok
                if not mom_ok:
                    confirmations_passed = False

                # 4. Volatility (ATR > 0.3%)
                vol_ok = await confirmations_checker.check_volatility(yahoo_symbol)
                confirmation_details["volatility"] = vol_ok
                if not vol_ok:
                    confirmations_passed = False

                # 5. RSI (not extreme)
                rsi_ok = await confirmations_checker.check_rsi(direction, yahoo_symbol)
                confirmation_details["rsi"] = rsi_ok
                if not rsi_ok:
                    confirmations_passed = False

                # 6. Time filter
                time_ok = confirmations_checker.check_time(commodity)
                confirmation_details["time"] = time_ok
                if not time_ok:
                    confirmations_passed = False

            except Exception as e:
                logger.error(f"Confirmation check error for {commodity}: {e}")
                confirmations_passed = False
                confirmation_details["error"] = str(e)

        # Build final signal
        confidence = n_agreeing / max(1, total_collectors)

        if direction and confirmations_passed and n_agreeing >= MIN_AGREEMENT:
            signal = direction
            reason = (
                f"{n_agreeing}/{total_collectors} collectors agree {direction} | "
                f"All {len(confirmation_details)} confirmations passed"
            )
        elif direction and not confirmations_passed:
            signal = "HOLD"
            failed = [k for k, v in confirmation_details.items() if not v]
            reason = (
                f"{n_agreeing}/{total_collectors} agree {direction} but "
                f"confirmations failed: {', '.join(failed)}"
            )
        else:
            signal = "HOLD"
            reason = (
                f"No consensus: {bullish_count} bullish, {bearish_count} bearish "
                f"(need {MIN_AGREEMENT}+ to agree)"
            )

        result = {
            "commodity": commodity,
            "instrument": config["instrument"],
            "name": config["name"],
            "signal": signal,
            "direction": direction or "NONE",
            "confidence": round(confidence, 3),
            "n_agreeing": n_agreeing,
            "total_collectors": total_collectors,
            "bullish_count": bullish_count,
            "bearish_count": bearish_count,
            "bullish_voters": bullish_names,
            "bearish_voters": bearish_names,
            "confirmations": confirmation_details,
            "confirmations_passed": confirmations_passed,
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "collector_scores": {
                name: {
                    "score": r.get("score", 5.0),
                    "direction": r.get("direction", "NEUTRAL"),
                    "confidence": r.get("confidence", 0.0),
                }
                for name, r in scores.items()
            },
        }

        return result

    async def evaluate_all(self, confirmations_checker=None) -> Dict[str, Dict]:
        """Evaluate precision signals for all 3 commodities."""
        results = {}
        for commodity in COMMODITIES:
            try:
                result = await self.evaluate_commodity(commodity, confirmations_checker)
                results[commodity] = result
                self._signals[commodity] = result

                # Log
                sig = result["signal"]
                n = result["n_agreeing"]
                total = result["total_collectors"]
                logger.info(
                    f"PRECISION [{commodity.upper()}]: {sig} "
                    f"({n}/{total} agree, conf={result['confidence']:.2f})"
                )

            except Exception as e:
                logger.error(f"Precision evaluation failed for {commodity}: {e}")
                results[commodity] = {
                    "commodity": commodity,
                    "signal": "ERROR",
                    "error": str(e),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }

        # Save to history
        history_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "signals": {
                k: {
                    "signal": v.get("signal"),
                    "n_agreeing": v.get("n_agreeing", 0),
                    "confidence": v.get("confidence", 0),
                    "bullish": v.get("bullish_count", 0),
                    "bearish": v.get("bearish_count", 0),
                }
                for k, v in results.items()
            },
        }
        self._signal_history.append(history_entry)
        self._save_history()

        # Save current signals to disk
        self._save_signals(results)

        return results

    def _save_signals(self, signals: Dict):
        path = DATA_DIR / "precision_signals.json"
        try:
            with open(path, "w") as f:
                json.dump(signals, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save precision signals: {e}")

    def get_current_signals(self) -> Dict[str, Dict]:
        if self._signals:
            return self._signals
        path = DATA_DIR / "precision_signals.json"
        if path.exists():
            try:
                with open(path) as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def get_history(self, limit: int = 200) -> List[Dict]:
        return self._signal_history[-limit:]

    async def close(self):
        """Close all collector HTTP clients."""
        for scorer_dict in [self._oil_scorer, self._gold_scorer, self._silver_scorer]:
            if scorer_dict:
                for collector in scorer_dict.values():
                    try:
                        await collector.close()
                    except Exception:
                        pass
