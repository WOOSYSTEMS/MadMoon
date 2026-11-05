"""
MadEye Silver -- COMEX Silver Inventory Proxy (Weight: 8%)
COMEX silver inventory tracking via news and SLV holdings as proxy.
Falling inventory = bullish (physical tightness).
"""

import logging
from typing import Dict, Tuple

from .base import BaseCollector

logger = logging.getLogger("madeye.silver")

NEWSAPI_BASE = "https://newsapi.org/v2/everything"


class COMEXSilverCollector(BaseCollector):
    name = "comex_silver"
    category = "supply"
    cache_ttl = 3600  # 1 hour

    def __init__(self, newsapi_key: str = ""):
        super().__init__()
        self.newsapi_key = newsapi_key

    async def collect(self) -> Dict:
        signals = []
        subscores = []

        # --- 1. COMEX Inventory News ---
        comex_score, comex_signals = await self._check_comex_news()
        subscores.append(comex_score)
        signals.extend(comex_signals)

        # --- 2. SLV Holdings as Physical Demand Proxy ---
        slv_score, slv_signals = await self._check_slv_holdings()
        subscores.append(slv_score)
        signals.extend(slv_signals)

        # --- 3. Silver Delivery News ---
        delivery_score, delivery_signals = await self._check_delivery_news()
        subscores.append(delivery_score)
        signals.extend(delivery_signals)

        # Weighted: COMEX news 40%, SLV proxy 35%, Delivery 25%
        weights = [0.40, 0.35, 0.25]
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
                "comex_score": round(comex_score, 2),
                "slv_score": round(slv_score, 2),
                "delivery_score": round(delivery_score, 2),
            },
            confidence=confidence,
        )

    async def _check_comex_news(self) -> Tuple[float, list]:
        """Check COMEX silver inventory news."""
        signals = []
        score = 5.0

        if not self.newsapi_key:
            return 5.0, ["COMEX inventory: no NewsAPI key"]

        data = await self.fetch_json(
            NEWSAPI_BASE,
            params={
                "q": '"COMEX silver inventory" OR "COMEX silver stocks" OR "silver warehouse"',
                "apiKey": self.newsapi_key,
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": "15",
            },
            cache_key="comex_news",
        )

        if not data or "articles" not in data:
            return 5.0, ["COMEX inventory news: unavailable"]

        articles = data.get("articles", [])
        total = data.get("totalResults", 0)
        signals.append(f"COMEX inventory news: {total} articles")

        if total == 0:
            return 5.0, signals

        bullish_kw = ["drawdown", "decline", "drop", "falling", "low", "tight",
                      "shortage", "depleted", "withdrew", "squeeze"]
        bearish_kw = ["increase", "rise", "build", "inflow", "surplus", "ample"]

        bullish_count = 0
        bearish_count = 0
        for article in articles[:10]:
            title = (article.get("title", "") or "").lower()
            desc = (article.get("description", "") or "").lower()
            text = title + " " + desc
            for kw in bullish_kw:
                if kw in text:
                    bullish_count += 1
            for kw in bearish_kw:
                if kw in text:
                    bearish_count += 1

        net = bullish_count - bearish_count
        signals.append(f"COMEX sentiment: {bullish_count} tight, {bearish_count} ample mentions")

        if net >= 4:
            score = 8.5
            signals.append("COMEX inventory dropping fast -- physical tightness, bullish")
        elif net >= 2:
            score = 7.0
            signals.append("COMEX inventory declining -- bullish supply signal")
        elif net <= -3:
            score = 2.5
            signals.append("COMEX inventory building -- ample supply, bearish")
        elif net <= -1:
            score = 4.0
            signals.append("COMEX inventory stable/rising -- mildly bearish")
        else:
            score = 5.0

        return score, signals

    async def _check_slv_holdings(self) -> Tuple[float, list]:
        """Use SLV ETF as proxy for physical silver demand."""
        signals = []
        score = 5.0

        try:
            import yfinance as yf
            slv = yf.Ticker("SLV")
            hist = slv.history(period="3mo")

            if hist.empty:
                return 5.0, ["SLV holdings proxy: no data"]

            prices = hist["Close"].dropna().tolist()
            volumes = hist["Volume"].dropna().tolist()

            if len(prices) < 20:
                return 5.0, ["SLV: insufficient data"]

            # SLV share price tracks silver with ETF creation/redemption
            # Persistent high volume = physical silver being absorbed
            avg_vol_recent = sum(volumes[-5:]) / 5 if len(volumes) >= 5 else 0
            avg_vol_older = sum(volumes[-20:-5]) / 15 if len(volumes) >= 20 else avg_vol_recent

            if avg_vol_older == 0:
                return 5.0, ["SLV volume: zero"]

            vol_trend = ((avg_vol_recent - avg_vol_older) / avg_vol_older) * 100
            price_trend = ((prices[-1] - prices[-20]) / prices[-20]) * 100

            signals.append(f"SLV volume trend: {vol_trend:+.1f}% (5d vs 20d), Price: {price_trend:+.1f}%")

            if vol_trend > 50 and price_trend > 0:
                score = 8.0
                signals.append("SLV volume surging + rising -- physical demand strong")
            elif vol_trend > 20 and price_trend > 0:
                score = 6.5
                signals.append("SLV volume up with positive price -- healthy demand")
            elif vol_trend > 50 and price_trend < 0:
                score = 3.5
                signals.append("SLV heavy volume on decline -- liquidation")
            elif vol_trend < -30:
                score = 4.5
                signals.append("SLV volume declining -- waning interest")
            else:
                score = 5.0

        except Exception as e:
            logger.warning(f"SLV holdings proxy error: {e}")
            signals.append(f"SLV: error ({str(e)[:50]})")

        return score, signals

    async def _check_delivery_news(self) -> Tuple[float, list]:
        """Check silver delivery/shortage news."""
        signals = []
        score = 5.0

        if not self.newsapi_key:
            return 5.0, ["Delivery news: no NewsAPI key"]

        data = await self.fetch_json(
            NEWSAPI_BASE,
            params={
                "q": '"silver delivery" OR "silver shortage" OR "physical silver demand"',
                "apiKey": self.newsapi_key,
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": "10",
            },
            cache_key="delivery_news",
        )

        if not data or "articles" not in data:
            return 5.0, ["Delivery news: unavailable"]

        total = data.get("totalResults", 0)
        articles = data.get("articles", [])

        if total > 10:
            score = 7.0
            signals.append(f"Silver delivery/shortage news elevated ({total} articles) -- potential tightness")
        elif total > 3:
            score = 6.0
            signals.append(f"Some silver delivery news ({total} articles)")
        else:
            score = 5.0
            signals.append(f"Silver delivery news: quiet ({total} articles)")

        return score, signals
