"""
MadEye Technical Collector
Computes RSI, MACD, Bollinger Bands, moving averages, support/resistance from Yahoo Finance.
Scores technical signal 0-10.
"""

import logging
import numpy as np
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from .base import BaseCollector

logger = logging.getLogger("madeye")


def compute_rsi(prices: list, period: int = 14) -> Optional[float]:
    """Compute RSI from price series."""
    if len(prices) < period + 1:
        return None
    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def compute_macd(prices: list, fast: int = 12, slow: int = 26, signal: int = 9) -> Optional[Dict]:
    """Compute MACD, signal line, histogram."""
    if len(prices) < slow + signal:
        return None

    def ema(data, period):
        k = 2.0 / (period + 1)
        result = [data[0]]
        for i in range(1, len(data)):
            result.append(data[i] * k + result[-1] * (1 - k))
        return result

    ema_fast = ema(prices, fast)
    ema_slow = ema(prices, slow)
    macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]
    signal_line = ema(macd_line[slow - 1:], signal)
    histogram = [m - s for m, s in zip(macd_line[slow - 1 + signal - 1:], signal_line)]

    return {
        "macd": macd_line[-1],
        "signal": signal_line[-1],
        "histogram": histogram[-1] if histogram else 0,
        "histogram_prev": histogram[-2] if len(histogram) >= 2 else 0,
    }


def compute_bollinger(prices: list, period: int = 20, std_dev: float = 2.0) -> Optional[Dict]:
    """Compute Bollinger Bands."""
    if len(prices) < period:
        return None
    window = prices[-period:]
    sma = sum(window) / period
    std = (sum((p - sma) ** 2 for p in window) / period) ** 0.5
    return {
        "upper": sma + std_dev * std,
        "middle": sma,
        "lower": sma - std_dev * std,
        "bandwidth": (2 * std_dev * std) / sma * 100 if sma else 0,
        "pct_b": (prices[-1] - (sma - std_dev * std)) / (2 * std_dev * std) if std else 0.5,
    }


def compute_sma(prices: list, period: int) -> Optional[float]:
    if len(prices) < period:
        return None
    return sum(prices[-period:]) / period


class TechnicalCollector(BaseCollector):
    name = "technical"
    category = "technical"
    cache_ttl = 600  # 10 minutes

    async def collect(self) -> Dict:
        signals = []
        subscores = []

        # Fetch price data
        prices, volumes = await self._get_price_data()
        if not prices or len(prices) < 50:
            return self.make_result(
                score=5.0,
                direction="NEUTRAL",
                signals=["Insufficient price data for technical analysis"],
                confidence=0.0,
            )

        current_price = prices[-1]
        signals.append(f"Brent current: ${current_price:.2f}")

        # --- 1. Moving Averages ---
        ma_score, ma_signals = self._analyze_moving_averages(prices)
        subscores.append(ma_score)
        signals.extend(ma_signals)

        # --- 2. RSI ---
        rsi_score, rsi_signals = self._analyze_rsi(prices)
        subscores.append(rsi_score)
        signals.extend(rsi_signals)

        # --- 3. MACD ---
        macd_score, macd_signals = self._analyze_macd(prices)
        subscores.append(macd_score)
        signals.extend(macd_signals)

        # --- 4. Bollinger Bands ---
        bb_score, bb_signals = self._analyze_bollinger(prices)
        subscores.append(bb_score)
        signals.extend(bb_signals)

        # --- 5. Volume Analysis ---
        vol_score, vol_signals = self._analyze_volume(prices, volumes)
        subscores.append(vol_score)
        signals.extend(vol_signals)

        # Weighted: MA 30%, RSI 20%, MACD 20%, BB 15%, Volume 15%
        weights = [0.30, 0.20, 0.20, 0.15, 0.15]
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
                "current_price": current_price,
                "ma_score": round(ma_score, 2),
                "rsi_score": round(rsi_score, 2),
                "macd_score": round(macd_score, 2),
                "bb_score": round(bb_score, 2),
                "volume_score": round(vol_score, 2),
            },
            confidence=confidence,
        )

    async def _get_price_data(self) -> Tuple[List[float], List[float]]:
        """Get Brent crude price history from Yahoo Finance."""
        try:
            import yfinance as yf
            ticker = yf.Ticker("BZ=F")
            hist = ticker.history(period="1y")
            if hist.empty:
                # Fallback to WTI
                ticker = yf.Ticker("CL=F")
                hist = ticker.history(period="1y")

            if not hist.empty:
                prices = hist["Close"].dropna().tolist()
                volumes = hist["Volume"].dropna().tolist()
                # Cache the data
                self._set_cache("prices", {
                    "prices": prices[-250:],
                    "volumes": volumes[-250:],
                })
                return prices, volumes
        except Exception as e:
            logger.warning(f"Yahoo Finance error: {e}")

        # Try cache
        cached = self._get_cache("prices", ignore_ttl=True)
        if cached:
            return cached.get("prices", []), cached.get("volumes", [])

        return [], []

    def _analyze_moving_averages(self, prices: list) -> tuple:
        signals = []
        score = 5.0

        current = prices[-1]
        ma50 = compute_sma(prices, 50)
        ma100 = compute_sma(prices, 100)
        ma200 = compute_sma(prices, 200)

        above_count = 0
        below_count = 0

        if ma50:
            if current > ma50:
                above_count += 1
                signals.append(f"Price above 50MA (${ma50:.2f})")
            else:
                below_count += 1
                signals.append(f"Price below 50MA (${ma50:.2f})")

        if ma100:
            if current > ma100:
                above_count += 1
            else:
                below_count += 1

        if ma200:
            if current > ma200:
                above_count += 1
                signals.append(f"Price above 200MA (${ma200:.2f}) -- long-term uptrend")
            else:
                below_count += 1
                signals.append(f"Price below 200MA (${ma200:.2f}) -- long-term downtrend")

        # Golden/Death cross check
        if ma50 and ma200:
            if ma50 > ma200:
                # Check if recent cross
                ma50_prev = compute_sma(prices[:-5], 50) if len(prices) > 55 else None
                ma200_prev = compute_sma(prices[:-5], 200) if len(prices) > 205 else None
                if ma50_prev and ma200_prev and ma50_prev < ma200_prev:
                    signals.append("GOLDEN CROSS detected -- strong bullish")
                    above_count += 2
            elif ma50 < ma200:
                ma50_prev = compute_sma(prices[:-5], 50) if len(prices) > 55 else None
                ma200_prev = compute_sma(prices[:-5], 200) if len(prices) > 205 else None
                if ma50_prev and ma200_prev and ma50_prev > ma200_prev:
                    signals.append("DEATH CROSS detected -- strong bearish")
                    below_count += 2

        total = above_count + below_count
        if total > 0:
            score = 2.0 + (above_count / total) * 6.0  # range 2-8

        # MA slope (50-day) for momentum
        if ma50 and len(prices) > 55:
            ma50_5d_ago = compute_sma(prices[:-5], 50)
            if ma50_5d_ago:
                slope = (ma50 - ma50_5d_ago) / ma50_5d_ago * 100
                if slope > 1:
                    score = min(10, score + 1.0)
                    signals.append(f"50MA rising sharply ({slope:.1f}%)")
                elif slope < -1:
                    score = max(0, score - 1.0)
                    signals.append(f"50MA falling sharply ({slope:.1f}%)")

        return score, signals

    def _analyze_rsi(self, prices: list) -> tuple:
        signals = []
        score = 5.0

        rsi = compute_rsi(prices, 14)
        if rsi is None:
            return 5.0, ["RSI: insufficient data"]

        signals.append(f"RSI(14): {rsi:.1f}")

        if rsi > 80:
            score = 2.0
            signals.append("RSI extremely overbought -- reversal likely")
        elif rsi > 70:
            score = 3.0
            signals.append("RSI overbought territory")
        elif rsi > 60:
            score = 6.0
            signals.append("RSI showing bullish momentum")
        elif rsi > 40:
            score = 5.0
        elif rsi > 30:
            score = 7.0
            signals.append("RSI approaching oversold")
        elif rsi > 20:
            score = 8.0
            signals.append("RSI oversold -- bounce likely")
        else:
            score = 9.0
            signals.append("RSI extremely oversold -- strong bounce signal")

        return score, signals

    def _analyze_macd(self, prices: list) -> tuple:
        signals = []
        score = 5.0

        macd_data = compute_macd(prices)
        if not macd_data:
            return 5.0, ["MACD: insufficient data"]

        macd_val = macd_data["macd"]
        signal_val = macd_data["signal"]
        hist = macd_data["histogram"]
        hist_prev = macd_data["histogram_prev"]

        signals.append(f"MACD: {macd_val:.3f}, Signal: {signal_val:.3f}")

        # MACD above signal = bullish
        if macd_val > signal_val:
            score = 6.5
            if hist > hist_prev:
                score = 7.5
                signals.append("MACD bullish + strengthening histogram")
            else:
                signals.append("MACD bullish but histogram weakening")
        else:
            score = 3.5
            if hist < hist_prev:
                score = 2.5
                signals.append("MACD bearish + strengthening bearish histogram")
            else:
                signals.append("MACD bearish but histogram improving")

        # Cross detection
        if hist > 0 and hist_prev <= 0:
            score = 8.0
            signals.append("MACD bullish crossover!")
        elif hist < 0 and hist_prev >= 0:
            score = 2.0
            signals.append("MACD bearish crossover!")

        return score, signals

    def _analyze_bollinger(self, prices: list) -> tuple:
        signals = []
        score = 5.0

        bb = compute_bollinger(prices)
        if not bb:
            return 5.0, ["Bollinger Bands: insufficient data"]

        current = prices[-1]
        pct_b = bb["pct_b"]
        bandwidth = bb["bandwidth"]

        signals.append(f"BB: upper=${bb['upper']:.2f} mid=${bb['middle']:.2f} lower=${bb['lower']:.2f}")

        # %B interpretation (0 = at lower band, 1 = at upper band)
        if pct_b > 1.0:
            score = 3.0
            signals.append("Price above upper BB -- overbought")
        elif pct_b > 0.8:
            score = 4.0
            signals.append("Price near upper BB")
        elif pct_b < 0.0:
            score = 8.0
            signals.append("Price below lower BB -- oversold, bounce likely")
        elif pct_b < 0.2:
            score = 7.0
            signals.append("Price near lower BB")
        elif 0.4 < pct_b < 0.6:
            score = 5.0

        # Bandwidth squeeze = upcoming volatility
        if bandwidth < 5:
            signals.append("BB SQUEEZE -- low volatility, big move incoming")

        return score, signals

    def _analyze_volume(self, prices: list, volumes: list) -> tuple:
        signals = []
        score = 5.0

        if not volumes or len(volumes) < 20:
            return 5.0, ["Volume: insufficient data"]

        avg_vol_20 = sum(volumes[-20:]) / 20
        recent_vol = volumes[-1] if volumes else 0
        price_change = prices[-1] - prices[-2] if len(prices) >= 2 else 0

        if avg_vol_20 == 0:
            return 5.0, ["Volume: no valid data"]

        vol_ratio = recent_vol / avg_vol_20

        if price_change > 0 and vol_ratio > 1.5:
            score = 7.5
            signals.append(f"Rising price on high volume ({vol_ratio:.1f}x avg) -- confirmed bullish")
        elif price_change > 0 and vol_ratio < 0.7:
            score = 4.0
            signals.append("Rising price on low volume -- weak rally")
        elif price_change < 0 and vol_ratio > 1.5:
            score = 2.5
            signals.append(f"Falling price on high volume ({vol_ratio:.1f}x avg) -- confirmed bearish")
        elif price_change < 0 and vol_ratio < 0.7:
            score = 5.5
            signals.append("Falling price on low volume -- selling exhaustion")
        else:
            score = 5.0

        return score, signals
