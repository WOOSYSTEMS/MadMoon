"""
MadEye Silver -- DXY Dollar Index Impact (Weight: 12%)
Dollar index impact on silver. Correlation -0.40 to -0.70 (weaker than gold's -0.85).
DXY UP = Silver DOWN, DXY DOWN = Silver UP.
"""

import logging
from typing import Dict, Tuple

from .base import BaseCollector

logger = logging.getLogger("madeye.silver")

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"


class DXYSilverCollector(BaseCollector):
    name = "dxy_silver"
    category = "macro"
    cache_ttl = 1800  # 30 minutes

    def __init__(self, fred_key: str = ""):
        super().__init__()
        self.fred_key = fred_key or "DEMO_KEY"

    async def collect(self) -> Dict:
        signals = []
        subscores = []

        # --- 1. DXY Level and Trend ---
        dxy_score, dxy_signals = await self._check_dxy()
        subscores.append(dxy_score)
        signals.extend(dxy_signals)

        # --- 2. DXY vs Silver Divergence ---
        div_score, div_signals = await self._check_divergence()
        subscores.append(div_score)
        signals.extend(div_signals)

        # Weighted: DXY level/trend 60%, Divergence 40%
        weights = [0.60, 0.40]
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
                "dxy_score": round(dxy_score, 2),
                "divergence_score": round(div_score, 2),
            },
            confidence=confidence,
        )

    async def _check_dxy(self) -> Tuple[float, list]:
        """Check US Dollar Index via Yahoo Finance."""
        signals = []
        score = 5.0
        values = []

        try:
            import yfinance as yf
            dxy = yf.Ticker("DX-Y.NYB")
            hist = dxy.history(period="3mo")
            if not hist.empty:
                values = hist["Close"].dropna().tolist()
        except Exception as e:
            logger.warning(f"Yahoo DXY error: {e}")

        # FRED fallback
        if not values:
            obs = await self._fetch_fred("DTWEXBGS", limit=60)
            if obs:
                for o in obs:
                    v = o.get("value", ".")
                    if v != ".":
                        values.append(float(v))
                    if len(values) >= 40:
                        break
                values = list(reversed(values))

        if len(values) < 5:
            return 5.0, ["DXY: insufficient data"]

        current = values[-1]
        prev_week = values[max(0, len(values) - 6)]
        prev_month = values[max(0, len(values) - 22)]

        wow = ((current - prev_week) / prev_week) * 100
        mom = ((current - prev_month) / prev_month) * 100

        signals.append(f"DXY: {current:.2f} (WoW: {wow:+.2f}%, MoM: {mom:+.2f}%)")

        # DXY rising = bearish silver, but weaker correlation than gold
        # Silver correlation is -0.40 to -0.70 vs gold's -0.85
        if mom > 4:
            score = 1.5
            signals.append("DXY surging -- strong bearish for silver")
        elif mom > 2:
            score = 3.0
            signals.append("DXY rising -- bearish for silver")
        elif wow > 1.5:
            score = 3.5
            signals.append("DXY short-term strength -- mildly bearish silver")
        elif mom < -4:
            score = 8.5
            signals.append("DXY falling sharply -- strong bullish for silver")
        elif mom < -2:
            score = 7.0
            signals.append("DXY weakening -- bullish for silver")
        elif wow < -1.5:
            score = 6.5
            signals.append("DXY short-term weakness -- mildly bullish silver")
        else:
            score = 5.0

        # Absolute level matters too
        if current > 108:
            score = max(1.0, score - 1.0)
            signals.append(f"DXY above 108 -- strong dollar headwind")
        elif current < 97:
            score = min(10.0, score + 1.0)
            signals.append(f"DXY below 97 -- weak dollar tailwind")

        return score, signals

    async def _check_divergence(self) -> Tuple[float, list]:
        """Check if DXY and silver are diverging (both rising = unusual)."""
        signals = []
        score = 5.0

        try:
            import yfinance as yf

            dxy_ticker = yf.Ticker("DX-Y.NYB")
            silver_ticker = yf.Ticker("SI=F")

            dxy_hist = dxy_ticker.history(period="1mo")
            silver_hist = silver_ticker.history(period="1mo")

            if dxy_hist.empty or silver_hist.empty:
                return 5.0, ["DXY/Silver divergence: no data"]

            dxy_prices = dxy_hist["Close"].dropna().tolist()
            silver_prices = silver_hist["Close"].dropna().tolist()

            if len(dxy_prices) < 5 or len(silver_prices) < 5:
                return 5.0, ["Divergence: insufficient data"]

            dxy_change = ((dxy_prices[-1] - dxy_prices[-6]) / dxy_prices[-6]) * 100
            silver_change = ((silver_prices[-1] - silver_prices[-6]) / silver_prices[-6]) * 100

            signals.append(f"5d: DXY {dxy_change:+.1f}%, Silver {silver_change:+.1f}%")

            # Normal: DXY up, silver down (or vice versa)
            # Unusual: both up or both down
            if dxy_change > 1 and silver_change > 1:
                score = 7.0
                signals.append("Silver rising despite strong dollar -- very bullish (demand-driven)")
            elif dxy_change < -1 and silver_change < -1:
                score = 3.0
                signals.append("Silver falling despite weak dollar -- very bearish (demand collapse)")
            elif dxy_change > 1 and silver_change < -2:
                score = 3.5
                signals.append("Strong dollar dragging silver down -- normal correlation")
            elif dxy_change < -1 and silver_change > 2:
                score = 6.5
                signals.append("Weak dollar lifting silver -- normal correlation")
            else:
                score = 5.0

        except Exception as e:
            logger.warning(f"Divergence check error: {e}")
            signals.append(f"Divergence: error ({str(e)[:50]})")

        return score, signals

    async def _fetch_fred(self, series_id: str, limit: int = 30):
        """Fetch FRED series data."""
        params = {
            "series_id": series_id,
            "api_key": self.fred_key,
            "file_type": "json",
            "sort_order": "desc",
            "limit": str(limit),
        }
        data = await self.fetch_json(
            FRED_BASE, params=params, cache_key=f"fred_{series_id}"
        )
        if data and "observations" in data:
            return data["observations"]
        return None
