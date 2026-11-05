"""
MadEye Silver -- ETF Flows (SLV, PSLV) Collector (Weight: 10%)
SLV and PSLV price/volume as proxy for ETF flows.
Volume spikes = institutional/retail interest.
Reddit squeeze risk monitoring via NewsAPI.
"""

import logging
from typing import Dict, Tuple

from .base import BaseCollector

logger = logging.getLogger("madeye.silver")

NEWSAPI_BASE = "https://newsapi.org/v2/everything"


class ETFFlowsSilverCollector(BaseCollector):
    name = "etf_flows_silver"
    category = "investment"
    cache_ttl = 1800  # 30 minutes

    def __init__(self, newsapi_key: str = ""):
        super().__init__()
        self.newsapi_key = newsapi_key

    async def collect(self) -> Dict:
        signals = []
        subscores = []

        # --- 1. SLV Volume and Price ---
        slv_score, slv_signals = await self._check_etf("SLV", "iShares Silver Trust")
        subscores.append(slv_score)
        signals.extend(slv_signals)

        # --- 2. PSLV Volume and Price ---
        pslv_score, pslv_signals = await self._check_etf("PSLV", "Sprott Physical Silver")
        subscores.append(pslv_score)
        signals.extend(pslv_signals)

        # --- 3. Reddit Squeeze Risk ---
        squeeze_score, squeeze_signals = await self._check_squeeze_risk()
        subscores.append(squeeze_score)
        signals.extend(squeeze_signals)

        # Weighted: SLV 40%, PSLV 35%, Squeeze 25%
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
                "slv_score": round(slv_score, 2),
                "pslv_score": round(pslv_score, 2),
                "squeeze_score": round(squeeze_score, 2),
            },
            confidence=confidence,
        )

    async def _check_etf(self, ticker: str, name: str) -> Tuple[float, list]:
        """Check ETF volume and price trend."""
        signals = []
        score = 5.0

        try:
            import yfinance as yf
            etf = yf.Ticker(ticker)
            hist = etf.history(period="3mo")

            if hist.empty:
                return 5.0, [f"{ticker}: no data"]

            prices = hist["Close"].dropna().tolist()
            volumes = hist["Volume"].dropna().tolist()

            if len(prices) < 20 or len(volumes) < 20:
                return 5.0, [f"{ticker}: insufficient data"]

            current_price = prices[-1]
            current_vol = volumes[-1]
            avg_vol_20 = sum(volumes[-20:]) / 20
            ma20 = sum(prices[-20:]) / 20

            vol_ratio = current_vol / avg_vol_20 if avg_vol_20 > 0 else 1.0
            price_vs_ma = ((current_price - ma20) / ma20) * 100

            signals.append(f"{ticker}: ${current_price:.2f} (vs 20MA: {price_vs_ma:+.1f}%), Vol: {vol_ratio:.1f}x avg")

            # High volume + rising price = strong inflows = bullish
            if vol_ratio > 2.0 and price_vs_ma > 0:
                score = 8.5
                signals.append(f"{name}: massive volume spike with rising price -- strong inflows")
            elif vol_ratio > 1.5 and price_vs_ma > 0:
                score = 7.0
                signals.append(f"{name}: elevated volume, positive price -- institutional buying")
            elif vol_ratio > 2.0 and price_vs_ma < 0:
                score = 3.0
                signals.append(f"{name}: massive volume spike with falling price -- heavy outflows")
            elif vol_ratio > 1.5 and price_vs_ma < 0:
                score = 3.5
                signals.append(f"{name}: elevated volume, negative price -- selling pressure")
            elif price_vs_ma > 3:
                score = 6.5
                signals.append(f"{name}: above 20MA -- positive trend")
            elif price_vs_ma < -3:
                score = 3.5
                signals.append(f"{name}: below 20MA -- negative trend")
            else:
                score = 5.0

        except Exception as e:
            logger.warning(f"{ticker} fetch error: {e}")
            signals.append(f"{ticker}: error ({str(e)[:50]})")

        return score, signals

    async def _check_squeeze_risk(self) -> Tuple[float, list]:
        """Check for silver squeeze / WSB silver activity via NewsAPI."""
        signals = []
        score = 5.0

        if not self.newsapi_key:
            return 5.0, ["Squeeze risk: no NewsAPI key"]

        data = await self.fetch_json(
            NEWSAPI_BASE,
            params={
                "q": '"silver squeeze" OR "wallstreetbets silver" OR "reddit silver" OR "#SilverSqueeze"',
                "apiKey": self.newsapi_key,
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": "10",
            },
            cache_key="squeeze_news",
        )

        if not data or "articles" not in data:
            return 5.0, ["Squeeze risk: no data"]

        total = data.get("totalResults", 0)
        signals.append(f"Silver squeeze mentions: {total} articles")

        if total > 20:
            score = 7.5
            signals.append("HIGH squeeze activity -- expect short-term spike then reversal")
        elif total > 10:
            score = 6.5
            signals.append("Moderate squeeze chatter -- watch for volatility")
        elif total > 3:
            score = 5.5
            signals.append("Some squeeze mentions -- awareness level")
        else:
            score = 5.0
            signals.append("No squeeze activity -- normal conditions")

        return score, signals
