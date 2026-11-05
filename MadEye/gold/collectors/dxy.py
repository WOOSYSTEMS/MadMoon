"""
MadEye Gold -- DXY (Dollar Index) Collector
THE #1 gold predictor. -0.85 correlation with XAU/USD.
DXY falling = bullish gold. DXY rising = bearish gold.
Weight: 25% of total signal.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from .base import BaseCollector

logger = logging.getLogger("madeye.gold")


class DXYCollector(BaseCollector):
    name = "dxy"
    category = "dollar_index"
    cache_ttl = 300  # 5 minutes

    def __init__(self, fred_key: str = None):
        super().__init__()
        self.fred_key = fred_key or "DEMO_KEY"

    async def collect(self) -> Dict:
        signals = []
        subscores = []

        # --- 1. Live DXY from Yahoo Finance ---
        dxy_score, dxy_signals, dxy_details = await self._analyze_dxy_yahoo()
        subscores.append(("dxy_live", dxy_score, 0.50))
        signals.extend(dxy_signals)

        # --- 2. FRED DTWEXBGS (Broad Dollar Index) as fallback/confirmation ---
        fred_score, fred_signals = await self._analyze_fred_dollar()
        subscores.append(("fred_dollar", fred_score, 0.25))
        signals.extend(fred_signals)

        # --- 3. Rate of change analysis ---
        roc_score, roc_signals = await self._analyze_roc()
        subscores.append(("roc", roc_score, 0.25))
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
                "dxy_live_score": round(dxy_score, 2),
                "fred_dollar_score": round(fred_score, 2),
                "roc_score": round(roc_score, 2),
                **dxy_details,
            },
            confidence=confidence,
        )

    async def _analyze_dxy_yahoo(self) -> Tuple[float, List[str], Dict]:
        """Fetch DXY from Yahoo Finance DX-Y.NYB."""
        signals = []
        details = {}
        score = 5.0

        try:
            import yfinance as yf
            ticker = yf.Ticker("DX-Y.NYB")
            hist = ticker.history(period="1mo", interval="1h")

            if hist.empty:
                # Fallback to daily
                hist = ticker.history(period="3mo")

            if hist.empty:
                return 5.0, ["DXY: No data from Yahoo"], {}

            prices = hist["Close"].dropna().tolist()
            current = prices[-1]
            details["dxy_current"] = round(current, 3)

            self._set_cache("dxy_prices", prices[-500:])

            signals.append(f"DXY: {current:.3f}")

            # 5-bar rate of change (approx 5 hours or 5 days)
            if len(prices) >= 6:
                roc_5 = (current - prices[-6]) / prices[-6] * 100
                details["dxy_roc_5bar"] = round(roc_5, 4)

                if roc_5 < -0.5:
                    score = 9.0
                    signals.append(f"DXY falling sharply ({roc_5:+.3f}%) -- STRONG bullish gold")
                elif roc_5 < -0.2:
                    score = 7.5
                    signals.append(f"DXY declining ({roc_5:+.3f}%) -- bullish gold")
                elif roc_5 < -0.05:
                    score = 6.5
                    signals.append(f"DXY drifting lower ({roc_5:+.3f}%) -- mildly bullish gold")
                elif roc_5 > 0.5:
                    score = 1.0
                    signals.append(f"DXY surging ({roc_5:+.3f}%) -- STRONG bearish gold")
                elif roc_5 > 0.2:
                    score = 2.5
                    signals.append(f"DXY rising ({roc_5:+.3f}%) -- bearish gold")
                elif roc_5 > 0.05:
                    score = 3.5
                    signals.append(f"DXY drifting higher ({roc_5:+.3f}%) -- mildly bearish gold")
                else:
                    score = 5.0
                    signals.append(f"DXY flat ({roc_5:+.3f}%) -- neutral")

            # 24-bar rate of change (approx 1 day or 1 month)
            if len(prices) >= 25:
                roc_24 = (current - prices[-25]) / prices[-25] * 100
                details["dxy_roc_24bar"] = round(roc_24, 4)

                if roc_24 < -1.0:
                    score = min(10, score + 1.0)
                    signals.append(f"DXY 24-bar trend strongly down ({roc_24:+.3f}%)")
                elif roc_24 > 1.0:
                    score = max(0, score - 1.0)
                    signals.append(f"DXY 24-bar trend strongly up ({roc_24:+.3f}%)")

            # DXY level thresholds
            if current < 100:
                score = min(10, score + 0.5)
                signals.append("DXY below 100 -- weak dollar regime, structurally bullish gold")
            elif current > 107:
                score = max(0, score - 0.5)
                signals.append("DXY above 107 -- strong dollar, headwind for gold")

        except Exception as e:
            logger.warning(f"DXY Yahoo error: {e}")
            signals.append(f"DXY Yahoo fetch failed: {str(e)[:60]}")

        return score, signals, details

    async def _analyze_fred_dollar(self) -> Tuple[float, List[str]]:
        """Fetch FRED DTWEXBGS (Trade Weighted Broad Dollar Index)."""
        signals = []
        score = 5.0

        try:
            url = "https://api.stlouisfed.org/fred/series/observations"
            params = {
                "series_id": "DTWEXBGS",
                "api_key": self.fred_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 30,
            }
            data = await self.fetch_json(url, params=params, cache_key="fred_dtwexbgs")
            if data and "observations" in data:
                obs = [o for o in data["observations"] if o["value"] != "."]
                if len(obs) >= 2:
                    latest = float(obs[0]["value"])
                    prev = float(obs[1]["value"])
                    change = (latest - prev) / prev * 100

                    if change < -0.3:
                        score = 8.0
                        signals.append(f"FRED Broad Dollar falling ({change:+.2f}%) -- bullish gold")
                    elif change < 0:
                        score = 6.5
                        signals.append(f"FRED Broad Dollar dipping ({change:+.2f}%)")
                    elif change > 0.3:
                        score = 2.0
                        signals.append(f"FRED Broad Dollar rising ({change:+.2f}%) -- bearish gold")
                    elif change > 0:
                        score = 3.5
                        signals.append(f"FRED Broad Dollar edging up ({change:+.2f}%)")

                    # Trend over 10 observations
                    if len(obs) >= 10:
                        oldest = float(obs[9]["value"])
                        trend = (latest - oldest) / oldest * 100
                        if trend < -1.0:
                            score = min(10, score + 1.0)
                            signals.append(f"FRED Dollar 10-day trend down ({trend:+.2f}%)")
                        elif trend > 1.0:
                            score = max(0, score - 1.0)
                            signals.append(f"FRED Dollar 10-day trend up ({trend:+.2f}%)")

        except Exception as e:
            logger.warning(f"FRED Dollar error: {e}")
            signals.append(f"FRED Dollar unavailable")

        return score, signals

    async def _analyze_roc(self) -> Tuple[float, List[str]]:
        """Compute multi-timeframe rate of change from cached DXY data."""
        signals = []
        score = 5.0

        cached = self._get_cache("dxy_prices", ignore_ttl=True)
        if not cached or len(cached) < 50:
            return 5.0, ["DXY ROC: insufficient cached data"]

        prices = cached
        current = prices[-1]

        # 5-period momentum
        if len(prices) >= 6:
            mom_5 = current - prices[-6]
            # 20-period momentum
            mom_20 = current - prices[-21] if len(prices) >= 21 else 0

            # Both declining = strong gold signal
            if mom_5 < 0 and mom_20 < 0:
                score = 8.5
                signals.append("DXY momentum: both short and medium-term declining -- bullish gold")
            elif mom_5 < 0 and mom_20 > 0:
                score = 6.5
                signals.append("DXY momentum: short-term down, medium-term up -- reversal forming")
            elif mom_5 > 0 and mom_20 < 0:
                score = 4.0
                signals.append("DXY momentum: short-term up, medium-term down -- bounce in downtrend")
            elif mom_5 > 0 and mom_20 > 0:
                score = 1.5
                signals.append("DXY momentum: both timeframes rising -- bearish gold")
            else:
                score = 5.0
                signals.append("DXY momentum: flat")

            # Acceleration
            if len(prices) >= 12:
                mom_5_prev = prices[-6] - prices[-12]
                acceleration = mom_5 - mom_5_prev
                if acceleration < -0.3:
                    score = min(10, score + 1.0)
                    signals.append("DXY accelerating downward -- gold breakout potential")
                elif acceleration > 0.3:
                    score = max(0, score - 1.0)
                    signals.append("DXY accelerating upward -- gold pressure increasing")

        return score, signals
