"""
MadEye Gold -- Real Interest Rates Collector
10Y TIPS yield and breakeven inflation.
Negative real rates = bullish gold (gold has zero yield, competes with bonds).
Rising real rates = bearish gold.
Weight: 20% of total signal.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from .base import BaseCollector

logger = logging.getLogger("madeye.gold")


class RealRatesCollector(BaseCollector):
    name = "real_rates"
    category = "real_rates"
    cache_ttl = 900  # 15 minutes

    def __init__(self, fred_key: str = None):
        super().__init__()
        self.fred_key = fred_key or "DEMO_KEY"

    async def collect(self) -> Dict:
        signals = []
        subscores = []

        # --- 1. 10Y TIPS Yield (Real Rate) ---
        tips10_score, tips10_signals, tips10_details = await self._fetch_tips_yield("DFII10", "10Y")
        subscores.append(("tips10", tips10_score, 0.40))
        signals.extend(tips10_signals)

        # --- 2. 5Y TIPS Yield ---
        tips5_score, tips5_signals, _ = await self._fetch_tips_yield("DFII5", "5Y")
        subscores.append(("tips5", tips5_score, 0.20))
        signals.extend(tips5_signals)

        # --- 3. Breakeven Inflation (5Y and 10Y) ---
        bei_score, bei_signals = await self._fetch_breakeven_inflation()
        subscores.append(("breakeven", bei_score, 0.25))
        signals.extend(bei_signals)

        # --- 4. Rate of change in real rates ---
        roc_score, roc_signals = await self._analyze_real_rate_trend()
        subscores.append(("roc", roc_score, 0.15))
        signals.extend(roc_signals)

        # Weighted composite
        total_weight = sum(w for _, _, w in subscores)
        composite = sum(s * w for _, s, w in subscores) / total_weight if total_weight > 0 else 5.0

        if composite >= 6.5:
            direction = "BULLISH"
        elif composite <= 3.5:
            direction = "BEARISH"
        else:
            direction = "NEUTRAL"

        confidence = min(1.0, len([s for _, s, _ in subscores if s != 5.0]) / max(1, len(subscores)))

        return self.make_result(
            score=composite,
            direction=direction,
            signals=signals,
            details={
                "tips10_score": round(tips10_score, 2),
                "tips5_score": round(tips5_score, 2),
                "breakeven_score": round(bei_score, 2),
                "roc_score": round(roc_score, 2),
                **tips10_details,
            },
            confidence=confidence,
        )

    async def _fetch_tips_yield(self, series_id: str, label: str) -> Tuple[float, List[str], Dict]:
        """Fetch TIPS yield from FRED."""
        signals = []
        details = {}
        score = 5.0

        try:
            url = "https://api.stlouisfed.org/fred/series/observations"
            params = {
                "series_id": series_id,
                "api_key": self.fred_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 60,
            }
            data = await self.fetch_json(url, params=params, cache_key=f"fred_{series_id}")

            if data and "observations" in data:
                obs = [o for o in data["observations"] if o["value"] != "."]
                if obs:
                    latest = float(obs[0]["value"])
                    details[f"real_rate_{label}"] = round(latest, 3)

                    # Cache for trend analysis
                    values = [float(o["value"]) for o in obs if o["value"] != "."]
                    self._set_cache(f"{series_id}_history", values[:60])

                    signals.append(f"{label} Real Rate: {latest:.3f}%")

                    # Scoring: Negative real rates are bullish for gold
                    if latest < -1.0:
                        score = 9.5
                        signals.append(f"{label} real rate deeply negative -- extremely bullish gold")
                    elif latest < -0.5:
                        score = 8.5
                        signals.append(f"{label} real rate negative -- very bullish gold")
                    elif latest < 0:
                        score = 7.5
                        signals.append(f"{label} real rate negative -- bullish gold")
                    elif latest < 0.5:
                        score = 5.5
                        signals.append(f"{label} real rate low positive -- mildly bullish gold")
                    elif latest < 1.0:
                        score = 4.0
                        signals.append(f"{label} real rate moderate -- neutral to bearish gold")
                    elif latest < 1.5:
                        score = 3.0
                        signals.append(f"{label} real rate elevated -- bearish gold")
                    elif latest < 2.0:
                        score = 2.0
                        signals.append(f"{label} real rate high -- very bearish gold")
                    else:
                        score = 1.0
                        signals.append(f"{label} real rate very high -- extremely bearish gold")

                    # Rate of change
                    if len(obs) >= 6:
                        prev = float(obs[5]["value"])
                        change = latest - prev
                        if change < -0.1:
                            score = min(10, score + 1.0)
                            signals.append(f"{label} real rate falling ({change:+.3f}pp) -- gold tailwind")
                        elif change > 0.1:
                            score = max(0, score - 1.0)
                            signals.append(f"{label} real rate rising ({change:+.3f}pp) -- gold headwind")

        except Exception as e:
            logger.warning(f"FRED {series_id} error: {e}")
            signals.append(f"{label} TIPS yield unavailable")

        return score, signals, details

    async def _fetch_breakeven_inflation(self) -> Tuple[float, List[str]]:
        """Fetch breakeven inflation expectations from FRED."""
        signals = []
        score = 5.0

        try:
            # 5Y Breakeven
            url = "https://api.stlouisfed.org/fred/series/observations"
            params_5y = {
                "series_id": "T5YIE",
                "api_key": self.fred_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 30,
            }
            params_10y = {
                "series_id": "T10YIE",
                "api_key": self.fred_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 30,
            }

            data_5y = await self.fetch_json(url, params=params_5y, cache_key="fred_T5YIE")
            data_10y = await self.fetch_json(url, params=params_10y, cache_key="fred_T10YIE")

            bei_5y = None
            bei_10y = None

            if data_5y and "observations" in data_5y:
                obs = [o for o in data_5y["observations"] if o["value"] != "."]
                if obs:
                    bei_5y = float(obs[0]["value"])
                    signals.append(f"5Y Breakeven Inflation: {bei_5y:.2f}%")

            if data_10y and "observations" in data_10y:
                obs = [o for o in data_10y["observations"] if o["value"] != "."]
                if obs:
                    bei_10y = float(obs[0]["value"])
                    signals.append(f"10Y Breakeven Inflation: {bei_10y:.2f}%")

            # Higher inflation expectations = bullish gold (inflation hedge)
            bei = bei_5y or bei_10y
            if bei is not None:
                if bei > 3.0:
                    score = 9.0
                    signals.append("Inflation expectations elevated -- strong gold demand as hedge")
                elif bei > 2.5:
                    score = 7.5
                    signals.append("Inflation expectations above target -- bullish gold")
                elif bei > 2.0:
                    score = 6.0
                    signals.append("Inflation expectations near target -- mildly bullish gold")
                elif bei > 1.5:
                    score = 4.5
                    signals.append("Inflation expectations moderate")
                else:
                    score = 3.0
                    signals.append("Inflation expectations low -- less gold demand as hedge")

                # Rising breakevens = more bullish
                if data_5y and "observations" in data_5y:
                    obs = [o for o in data_5y["observations"] if o["value"] != "."]
                    if len(obs) >= 10:
                        older = float(obs[9]["value"])
                        trend = bei_5y - older if bei_5y else 0
                        if trend > 0.1:
                            score = min(10, score + 0.5)
                            signals.append(f"5Y breakeven rising ({trend:+.2f}pp) -- inflation fears growing")
                        elif trend < -0.1:
                            score = max(0, score - 0.5)
                            signals.append(f"5Y breakeven falling ({trend:+.2f}pp) -- inflation fears easing")

        except Exception as e:
            logger.warning(f"Breakeven inflation error: {e}")
            signals.append("Breakeven inflation data unavailable")

        return score, signals

    async def _analyze_real_rate_trend(self) -> Tuple[float, List[str]]:
        """Analyze the trend direction and velocity of real rates."""
        signals = []
        score = 5.0

        cached = self._get_cache("DFII10_history", ignore_ttl=True)
        if not cached or len(cached) < 10:
            return 5.0, ["Real rate trend: insufficient data"]

        rates = cached  # Most recent first from FRED
        latest = rates[0]
        week_ago = rates[min(5, len(rates) - 1)]
        month_ago = rates[min(20, len(rates) - 1)]

        # Weekly change
        weekly_change = latest - week_ago
        # Monthly change
        monthly_change = latest - month_ago

        if weekly_change < -0.1 and monthly_change < -0.2:
            score = 9.0
            signals.append("Real rates falling on both weekly and monthly -- strong gold tailwind")
        elif weekly_change < -0.05:
            score = 7.0
            signals.append(f"Real rates falling weekly ({weekly_change:+.3f}pp)")
        elif weekly_change > 0.1 and monthly_change > 0.2:
            score = 1.5
            signals.append("Real rates rising on both weekly and monthly -- strong gold headwind")
        elif weekly_change > 0.05:
            score = 3.0
            signals.append(f"Real rates rising weekly ({weekly_change:+.3f}pp)")
        else:
            score = 5.0
            signals.append("Real rates stable")

        return score, signals
