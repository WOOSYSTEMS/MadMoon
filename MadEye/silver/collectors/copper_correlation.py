"""
MadEye Silver -- Copper Correlation Collector (Weight: 7%)
Copper as leading indicator for silver. Correlation: +0.72 to +0.90.
Copper rising while silver flat = silver about to catch up (bullish).
Copper falling = industrial demand weak = bearish silver.
"""

import logging
from typing import Dict, List, Tuple

from .base import BaseCollector

logger = logging.getLogger("madeye.silver")


class CopperCorrelationCollector(BaseCollector):
    name = "copper_correlation"
    category = "industrial"
    cache_ttl = 900  # 15 minutes

    async def collect(self) -> Dict:
        signals = []
        subscores = []

        copper_prices, silver_prices = await self._get_prices()

        if not copper_prices or not silver_prices or len(copper_prices) < 20:
            return self.make_result(
                score=5.0, direction="NEUTRAL",
                signals=["Insufficient copper/silver data"],
                confidence=0.0,
            )

        # --- 1. Copper Trend ---
        copper_score, copper_signals = self._analyze_copper_trend(copper_prices)
        subscores.append(copper_score)
        signals.extend(copper_signals)

        # --- 2. Copper/Silver Divergence ---
        div_score, div_signals = self._analyze_divergence(copper_prices, silver_prices)
        subscores.append(div_score)
        signals.extend(div_signals)

        # --- 3. Copper Momentum ---
        mom_score, mom_signals = self._analyze_copper_momentum(copper_prices)
        subscores.append(mom_score)
        signals.extend(mom_signals)

        # Weighted: Copper trend 35%, Divergence 40%, Momentum 25%
        weights = [0.35, 0.40, 0.25]
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
                "copper_price": round(copper_prices[-1], 4),
                "silver_price": round(silver_prices[-1], 2),
                "copper_trend_score": round(copper_score, 2),
                "divergence_score": round(div_score, 2),
                "momentum_score": round(mom_score, 2),
            },
            confidence=confidence,
        )

    async def _get_prices(self) -> Tuple[List[float], List[float]]:
        try:
            import yfinance as yf
            copper = yf.Ticker("HG=F")
            silver = yf.Ticker("SI=F")

            copper_hist = copper.history(period="3mo")
            silver_hist = silver.history(period="3mo")

            if copper_hist.empty or silver_hist.empty:
                raise ValueError("Empty price data")

            copper_prices = copper_hist["Close"].dropna().tolist()
            silver_prices = silver_hist["Close"].dropna().tolist()

            min_len = min(len(copper_prices), len(silver_prices))
            copper_prices = copper_prices[-min_len:]
            silver_prices = silver_prices[-min_len:]

            self._set_cache("cu_ag_prices", {
                "copper": copper_prices,
                "silver": silver_prices,
            })
            return copper_prices, silver_prices
        except Exception as e:
            logger.warning(f"Copper/Silver price error: {e}")

        cached = self._get_cache("cu_ag_prices", ignore_ttl=True)
        if cached:
            return cached.get("copper", []), cached.get("silver", [])
        return [], []

    def _analyze_copper_trend(self, copper_prices: list) -> Tuple[float, list]:
        signals = []
        score = 5.0

        if len(copper_prices) < 22:
            return 5.0, ["Copper trend: insufficient data"]

        current = copper_prices[-1]
        ma20 = sum(copper_prices[-20:]) / 20

        pct_vs_ma = ((current - ma20) / ma20) * 100
        week_change = ((current - copper_prices[-6]) / copper_prices[-6]) * 100

        signals.append(f"Copper (HG=F): ${current:.4f} (vs 20MA: {pct_vs_ma:+.1f}%, 5d: {week_change:+.1f}%)")

        if pct_vs_ma > 5 and week_change > 3:
            score = 8.0
            signals.append("Copper surging -- industrial demand strong, bullish silver")
        elif pct_vs_ma > 2:
            score = 6.5
            signals.append("Copper above 20MA -- positive industrial signal")
        elif pct_vs_ma < -5 and week_change < -3:
            score = 2.0
            signals.append("Copper plunging -- industrial demand collapsing, bearish silver")
        elif pct_vs_ma < -2:
            score = 3.5
            signals.append("Copper below 20MA -- weak industrial demand")
        else:
            score = 5.0

        return score, signals

    def _analyze_divergence(self, copper_prices: list, silver_prices: list) -> Tuple[float, list]:
        """KEY SIGNAL: Copper rising while silver flat = silver catch-up trade."""
        signals = []
        score = 5.0

        if len(copper_prices) < 10 or len(silver_prices) < 10:
            return 5.0, ["Copper/Silver divergence: insufficient data"]

        copper_5d = ((copper_prices[-1] - copper_prices[-6]) / copper_prices[-6]) * 100
        silver_5d = ((silver_prices[-1] - silver_prices[-6]) / silver_prices[-6]) * 100
        divergence = copper_5d - silver_5d

        signals.append(f"5d: Copper {copper_5d:+.1f}%, Silver {silver_5d:+.1f}%, Divergence: {divergence:+.1f}%")

        # The key trade: copper rising while silver lags
        if copper_5d > 2 and silver_5d < 1 and divergence > 2:
            score = 8.5
            signals.append("Copper outpacing silver -- silver catch-up trade imminent, STRONG BUY")
        elif copper_5d > 1 and divergence > 1.5:
            score = 7.0
            signals.append("Copper leading silver -- catch-up potential")
        elif copper_5d < -2 and silver_5d > -1:
            score = 3.0
            signals.append("Copper falling while silver holds -- silver may follow down")
        elif copper_5d < -1 and silver_5d < -1:
            score = 3.5
            signals.append("Both falling -- industrial weakness confirmed")
        elif copper_5d > 1 and silver_5d > 1:
            score = 6.5
            signals.append("Both rising -- industrial demand strong, bullish")
        else:
            score = 5.0

        return score, signals

    def _analyze_copper_momentum(self, copper_prices: list) -> Tuple[float, list]:
        signals = []
        score = 5.0

        if len(copper_prices) < 30:
            return 5.0, ["Copper momentum: insufficient data"]

        # 20-day momentum
        momentum = ((copper_prices[-1] - copper_prices[-21]) / copper_prices[-21]) * 100
        # 5-day acceleration
        mom_recent = ((copper_prices[-1] - copper_prices[-6]) / copper_prices[-6]) * 100
        mom_prior = ((copper_prices[-6] - copper_prices[-11]) / copper_prices[-11]) * 100
        acceleration = mom_recent - mom_prior

        signals.append(f"Copper 20d momentum: {momentum:+.1f}%, acceleration: {acceleration:+.1f}%")

        if momentum > 5 and acceleration > 0:
            score = 8.0
            signals.append("Copper strong + accelerating -- bullish silver")
        elif momentum > 3:
            score = 6.5
        elif momentum < -5 and acceleration < 0:
            score = 2.0
            signals.append("Copper weak + decelerating -- bearish silver")
        elif momentum < -3:
            score = 3.5
        else:
            score = 5.0

        return score, signals
