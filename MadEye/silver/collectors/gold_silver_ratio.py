"""
MadEye Silver -- Gold/Silver Ratio Collector (Weight: 20%)
THE most important silver-specific signal.
Ratio > 85 = buy silver (historically reverts to mean ~65)
Ratio < 60 = sell silver
Rate of change matters: ratio falling fast = silver outperforming
"""

import logging
from typing import Dict, List, Optional, Tuple

from .base import BaseCollector

logger = logging.getLogger("madeye.silver")


class GoldSilverRatioCollector(BaseCollector):
    name = "gold_silver_ratio"
    category = "ratio"
    cache_ttl = 600  # 10 minutes

    async def collect(self) -> Dict:
        signals = []
        subscores = []

        # Fetch gold and silver prices from Yahoo Finance
        gold_prices, silver_prices = await self._get_prices()

        if not gold_prices or not silver_prices or len(gold_prices) < 20:
            return self.make_result(
                score=5.0,
                direction="NEUTRAL",
                signals=["Insufficient gold/silver price data for ratio analysis"],
                confidence=0.0,
            )

        # Calculate current ratio
        current_gold = gold_prices[-1]
        current_silver = silver_prices[-1]

        if current_silver <= 0:
            return self.make_result(
                score=5.0, direction="NEUTRAL",
                signals=["Silver price is zero/negative"], confidence=0.0,
            )

        current_ratio = current_gold / current_silver
        signals.append(f"Gold/Silver Ratio: {current_ratio:.1f} (Gold ${current_gold:.2f} / Silver ${current_silver:.2f})")

        # --- 1. Absolute Level Analysis ---
        level_score, level_signals = self._analyze_level(current_ratio)
        subscores.append(level_score)
        signals.extend(level_signals)

        # --- 2. Rate of Change ---
        roc_score, roc_signals = self._analyze_rate_of_change(gold_prices, silver_prices)
        subscores.append(roc_score)
        signals.extend(roc_signals)

        # --- 3. Mean Reversion Signal ---
        mr_score, mr_signals = self._analyze_mean_reversion(gold_prices, silver_prices)
        subscores.append(mr_score)
        signals.extend(mr_signals)

        # --- 4. Ratio Trend (20-day direction) ---
        trend_score, trend_signals = self._analyze_trend(gold_prices, silver_prices)
        subscores.append(trend_score)
        signals.extend(trend_signals)

        # Weighted: Level 40%, Rate of Change 25%, Mean Reversion 20%, Trend 15%
        weights = [0.40, 0.25, 0.20, 0.15]
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
                "current_ratio": round(current_ratio, 2),
                "gold_price": round(current_gold, 2),
                "silver_price": round(current_silver, 2),
                "level_score": round(level_score, 2),
                "roc_score": round(roc_score, 2),
                "mean_reversion_score": round(mr_score, 2),
                "trend_score": round(trend_score, 2),
            },
            confidence=confidence,
        )

    async def _get_prices(self) -> Tuple[List[float], List[float]]:
        """Get gold and silver price history from Yahoo Finance."""
        try:
            import yfinance as yf
            gold_ticker = yf.Ticker("GC=F")
            silver_ticker = yf.Ticker("SI=F")

            gold_hist = gold_ticker.history(period="6mo")
            silver_hist = silver_ticker.history(period="6mo")

            if gold_hist.empty or silver_hist.empty:
                raise ValueError("Empty price history")

            gold_prices = gold_hist["Close"].dropna().tolist()
            silver_prices = silver_hist["Close"].dropna().tolist()

            # Align lengths
            min_len = min(len(gold_prices), len(silver_prices))
            gold_prices = gold_prices[-min_len:]
            silver_prices = silver_prices[-min_len:]

            self._set_cache("gsr_prices", {
                "gold": gold_prices[-200:],
                "silver": silver_prices[-200:],
            })
            return gold_prices, silver_prices
        except Exception as e:
            logger.warning(f"Yahoo Finance GSR error: {e}")

        cached = self._get_cache("gsr_prices", ignore_ttl=True)
        if cached:
            return cached.get("gold", []), cached.get("silver", [])
        return [], []

    def _analyze_level(self, ratio: float) -> Tuple[float, list]:
        """Analyze the absolute ratio level."""
        signals = []
        score = 5.0

        if ratio > 100:
            score = 9.5
            signals.append(f"GSR > 100 ({ratio:.1f}) -- EXTREME: Silver historically cheap, preceded 400%+ rallies")
        elif ratio > 90:
            score = 8.5
            signals.append(f"GSR > 90 ({ratio:.1f}) -- Silver very cheap vs gold, strong buy signal")
        elif ratio > 85:
            score = 7.5
            signals.append(f"GSR > 85 ({ratio:.1f}) -- Silver cheap vs gold, buy signal")
        elif ratio > 80:
            score = 6.5
            signals.append(f"GSR 80-85 ({ratio:.1f}) -- Silver moderately cheap")
        elif ratio > 70:
            score = 5.0
            signals.append(f"GSR 70-80 ({ratio:.1f}) -- Neutral zone")
        elif ratio > 65:
            score = 4.0
            signals.append(f"GSR 65-70 ({ratio:.1f}) -- Silver approaching fair value")
        elif ratio > 60:
            score = 3.0
            signals.append(f"GSR 60-65 ({ratio:.1f}) -- Silver at historical mean, consider reducing")
        else:
            score = 1.5
            signals.append(f"GSR < 60 ({ratio:.1f}) -- Silver expensive vs gold, SELL signal")

        return score, signals

    def _analyze_rate_of_change(self, gold_prices: list, silver_prices: list) -> Tuple[float, list]:
        """Analyze how fast the ratio is changing."""
        signals = []
        score = 5.0

        if len(gold_prices) < 10 or len(silver_prices) < 10:
            return 5.0, ["GSR ROC: insufficient data"]

        # Current and 5-day ago ratios
        current_ratio = gold_prices[-1] / silver_prices[-1] if silver_prices[-1] > 0 else 0
        ratio_5d = gold_prices[-6] / silver_prices[-6] if silver_prices[-6] > 0 else 0
        ratio_20d = gold_prices[-min(21, len(gold_prices))] / silver_prices[-min(21, len(silver_prices))] if silver_prices[-min(21, len(silver_prices))] > 0 else 0

        if current_ratio == 0 or ratio_5d == 0:
            return 5.0, ["GSR ROC: zero ratio"]

        roc_5d = ((current_ratio - ratio_5d) / ratio_5d) * 100
        roc_20d = ((current_ratio - ratio_20d) / ratio_20d) * 100 if ratio_20d > 0 else 0

        signals.append(f"GSR change: 5d {roc_5d:+.1f}%, 20d {roc_20d:+.1f}%")

        # Ratio FALLING = silver outperforming gold = BULLISH for silver
        if roc_5d < -3:
            score = 8.5
            signals.append("GSR falling fast -- silver massively outperforming gold")
        elif roc_5d < -1.5:
            score = 7.5
            signals.append("GSR falling -- silver outperforming gold")
        elif roc_5d < -0.5:
            score = 6.5
            signals.append("GSR declining -- silver gaining vs gold")
        elif roc_5d > 3:
            score = 2.0
            signals.append("GSR rising fast -- silver underperforming badly")
        elif roc_5d > 1.5:
            score = 3.0
            signals.append("GSR rising -- silver lagging gold")
        elif roc_5d > 0.5:
            score = 4.0
            signals.append("GSR edging up -- gold outperforming")
        else:
            score = 5.0

        return score, signals

    def _analyze_mean_reversion(self, gold_prices: list, silver_prices: list) -> Tuple[float, list]:
        """Analyze distance from historical mean for mean reversion signal."""
        signals = []
        score = 5.0

        if len(gold_prices) < 50:
            return 5.0, ["GSR mean reversion: insufficient data"]

        # Calculate rolling 50-day average ratio
        ratios = []
        for g, s in zip(gold_prices, silver_prices):
            if s > 0:
                ratios.append(g / s)

        if len(ratios) < 50:
            return 5.0, ["GSR mean reversion: insufficient ratio data"]

        mean_ratio = sum(ratios[-50:]) / 50
        current_ratio = ratios[-1]
        deviation = current_ratio - mean_ratio
        pct_deviation = (deviation / mean_ratio) * 100

        signals.append(f"GSR vs 50d mean: {current_ratio:.1f} vs {mean_ratio:.1f} ({pct_deviation:+.1f}%)")

        # Historical mean is ~65-75. Distance from 70 is the key signal.
        long_term_mean = 70.0
        distance_from_mean = current_ratio - long_term_mean
        pct_from_mean = (distance_from_mean / long_term_mean) * 100

        if pct_from_mean > 30:
            score = 9.0
            signals.append(f"GSR {pct_from_mean:.0f}% above long-term mean (70) -- extreme buy")
        elif pct_from_mean > 20:
            score = 8.0
            signals.append(f"GSR {pct_from_mean:.0f}% above mean -- strong buy")
        elif pct_from_mean > 10:
            score = 7.0
            signals.append(f"GSR {pct_from_mean:.0f}% above mean -- buy signal")
        elif pct_from_mean > 0:
            score = 5.5
            signals.append(f"GSR slightly above mean")
        elif pct_from_mean > -10:
            score = 4.5
            signals.append(f"GSR near/below mean")
        elif pct_from_mean > -15:
            score = 3.0
            signals.append(f"GSR {abs(pct_from_mean):.0f}% below mean -- silver expensive")
        else:
            score = 1.5
            signals.append(f"GSR {abs(pct_from_mean):.0f}% below mean -- extreme sell")

        return score, signals

    def _analyze_trend(self, gold_prices: list, silver_prices: list) -> Tuple[float, list]:
        """Analyze 20-day trend direction of the ratio."""
        signals = []
        score = 5.0

        if len(gold_prices) < 25:
            return 5.0, ["GSR trend: insufficient data"]

        ratios = []
        for g, s in zip(gold_prices[-25:], silver_prices[-25:]):
            if s > 0:
                ratios.append(g / s)

        if len(ratios) < 20:
            return 5.0, ["GSR trend: insufficient data"]

        # Simple linear regression slope
        n = len(ratios)
        x_mean = (n - 1) / 2
        y_mean = sum(ratios) / n
        numerator = sum((i - x_mean) * (y - y_mean) for i, y in enumerate(ratios))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        slope = numerator / denominator if denominator != 0 else 0

        # Normalize slope relative to current ratio level
        normalized_slope = (slope / ratios[-1]) * 100 if ratios[-1] > 0 else 0

        if normalized_slope < -0.3:
            score = 7.5
            signals.append(f"GSR trend: falling (slope {normalized_slope:.2f}%/day) -- bullish silver")
        elif normalized_slope < -0.1:
            score = 6.5
            signals.append(f"GSR trend: drifting lower -- mildly bullish silver")
        elif normalized_slope > 0.3:
            score = 3.0
            signals.append(f"GSR trend: rising (slope {normalized_slope:.2f}%/day) -- bearish silver")
        elif normalized_slope > 0.1:
            score = 4.0
            signals.append(f"GSR trend: drifting higher -- mildly bearish silver")
        else:
            score = 5.0
            signals.append(f"GSR trend: flat")

        return score, signals
