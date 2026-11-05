"""
MadEye Silver -- Industrial Demand Collector (Weight: 15%)
Silver's industrial half: solar, semiconductor, EV, manufacturing PMI.
51% of silver demand is industrial -- this is what makes silver different from gold.
"""

import logging
from typing import Dict, Tuple

from .base import BaseCollector

logger = logging.getLogger("madeye.silver")

NEWSAPI_BASE = "https://newsapi.org/v2/everything"
FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"


class IndustrialDemandCollector(BaseCollector):
    name = "industrial_demand"
    category = "industrial"
    cache_ttl = 1800  # 30 minutes

    def __init__(self, newsapi_key: str = "", fred_key: str = ""):
        super().__init__()
        self.newsapi_key = newsapi_key
        self.fred_key = fred_key or "DEMO_KEY"

    async def collect(self) -> Dict:
        signals = []
        subscores = []

        # --- 1. Solar Panel Demand (news sentiment) ---
        solar_score, solar_signals = await self._check_solar()
        subscores.append(solar_score)
        signals.extend(solar_signals)

        # --- 2. Semiconductor Demand ---
        semi_score, semi_signals = await self._check_semiconductors()
        subscores.append(semi_score)
        signals.extend(semi_signals)

        # --- 3. EV Demand Proxy (Tesla + Copper) ---
        ev_score, ev_signals = await self._check_ev_proxy()
        subscores.append(ev_score)
        signals.extend(ev_signals)

        # --- 4. US Manufacturing PMI proxy ---
        pmi_score, pmi_signals = await self._check_pmi()
        subscores.append(pmi_score)
        signals.extend(pmi_signals)

        # Weighted: Solar 30%, Semi 25%, EV 20%, PMI 25%
        weights = [0.30, 0.25, 0.20, 0.25]
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
                "solar_score": round(solar_score, 2),
                "semi_score": round(semi_score, 2),
                "ev_score": round(ev_score, 2),
                "pmi_score": round(pmi_score, 2),
            },
            confidence=confidence,
        )

    async def _check_solar(self) -> Tuple[float, list]:
        """Check solar panel silver demand via NewsAPI."""
        signals = []
        score = 5.0

        if not self.newsapi_key:
            return 5.0, ["Solar demand: no NewsAPI key"]

        data = await self.fetch_json(
            NEWSAPI_BASE,
            params={
                "q": '"solar panel silver" OR "photovoltaic silver" OR "silver paste solar"',
                "apiKey": self.newsapi_key,
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": "20",
            },
            cache_key="solar_news",
        )

        if not data or "articles" not in data:
            return 5.0, ["Solar demand news: unavailable"]

        articles = data.get("articles", [])
        total = data.get("totalResults", 0)
        signals.append(f"Solar silver news: {total} articles found")

        if total == 0:
            return 5.0, signals

        # Sentiment analysis from titles
        bullish_keywords = ["growth", "surge", "demand", "record", "expansion", "boom",
                           "install", "mandate", "subsidy", "increase"]
        bearish_keywords = ["substitute", "copper replace", "thrift", "decline", "reduce",
                           "cut", "slowdown", "tariff"]

        bullish_count = 0
        bearish_count = 0
        for article in articles[:15]:
            title = (article.get("title", "") or "").lower()
            desc = (article.get("description", "") or "").lower()
            text = title + " " + desc
            for kw in bullish_keywords:
                if kw in text:
                    bullish_count += 1
            for kw in bearish_keywords:
                if kw in text:
                    bearish_count += 1

        net = bullish_count - bearish_count
        signals.append(f"Solar sentiment: {bullish_count} bullish, {bearish_count} bearish mentions")

        if net >= 5:
            score = 8.0
            signals.append("Strong solar demand growth narrative -- bullish silver")
        elif net >= 2:
            score = 6.5
            signals.append("Positive solar demand -- mildly bullish silver")
        elif net <= -3:
            score = 2.5
            signals.append("Solar substitution/decline narrative -- bearish silver")
        elif net <= -1:
            score = 4.0
            signals.append("Negative solar sentiment -- mildly bearish")
        else:
            score = 5.0

        return score, signals

    async def _check_semiconductors(self) -> Tuple[float, list]:
        """Check semiconductor demand via SOX index from Yahoo Finance."""
        signals = []
        score = 5.0

        try:
            import yfinance as yf
            sox = yf.Ticker("^SOX")
            hist = sox.history(period="3mo")
            if hist.empty:
                return 5.0, ["SOX index: no data"]

            prices = hist["Close"].dropna().tolist()
            if len(prices) < 20:
                return 5.0, ["SOX index: insufficient data"]

            current = prices[-1]
            ma20 = sum(prices[-20:]) / 20
            ma50 = sum(prices[-50:]) / 50 if len(prices) >= 50 else ma20

            pct_vs_ma20 = ((current - ma20) / ma20) * 100
            pct_vs_ma50 = ((current - ma50) / ma50) * 100

            signals.append(f"SOX Index: {current:.0f} (vs 20MA: {pct_vs_ma20:+.1f}%, vs 50MA: {pct_vs_ma50:+.1f}%)")

            if pct_vs_ma20 > 5:
                score = 7.5
                signals.append("Semiconductor sector strong -- bullish industrial silver demand")
            elif pct_vs_ma20 > 2:
                score = 6.5
                signals.append("Semiconductor sector positive")
            elif pct_vs_ma20 < -5:
                score = 2.5
                signals.append("Semiconductor sector weak -- bearish industrial silver demand")
            elif pct_vs_ma20 < -2:
                score = 3.5
                signals.append("Semiconductor sector softening")
            else:
                score = 5.0

        except Exception as e:
            logger.warning(f"SOX fetch error: {e}")
            signals.append(f"SOX index: error ({str(e)[:50]})")

        return score, signals

    async def _check_ev_proxy(self) -> Tuple[float, list]:
        """Check EV demand via Tesla stock and copper futures."""
        signals = []
        score = 5.0

        try:
            import yfinance as yf

            # Tesla as EV demand proxy
            tsla = yf.Ticker("TSLA")
            tsla_hist = tsla.history(period="1mo")

            # Copper as industrial demand proxy
            copper = yf.Ticker("HG=F")
            copper_hist = copper.history(period="1mo")

            tsla_score = 5.0
            copper_score = 5.0

            if not tsla_hist.empty:
                tsla_prices = tsla_hist["Close"].dropna().tolist()
                if len(tsla_prices) >= 5:
                    tsla_change = ((tsla_prices[-1] - tsla_prices[-6]) / tsla_prices[-6]) * 100
                    signals.append(f"Tesla 5d change: {tsla_change:+.1f}%")
                    if tsla_change > 10:
                        tsla_score = 7.5
                    elif tsla_change > 3:
                        tsla_score = 6.5
                    elif tsla_change < -10:
                        tsla_score = 3.0
                    elif tsla_change < -3:
                        tsla_score = 4.0

            if not copper_hist.empty:
                copper_prices = copper_hist["Close"].dropna().tolist()
                if len(copper_prices) >= 5:
                    copper_change = ((copper_prices[-1] - copper_prices[-6]) / copper_prices[-6]) * 100
                    signals.append(f"Copper 5d change: {copper_change:+.1f}%")
                    if copper_change > 5:
                        copper_score = 7.5
                    elif copper_change > 2:
                        copper_score = 6.5
                    elif copper_change < -5:
                        copper_score = 3.0
                    elif copper_change < -2:
                        copper_score = 4.0

            # Average of Tesla and copper signals
            score = (tsla_score * 0.4 + copper_score * 0.6)

        except Exception as e:
            logger.warning(f"EV proxy error: {e}")
            signals.append(f"EV proxy: error ({str(e)[:50]})")

        return score, signals

    async def _check_pmi(self) -> Tuple[float, list]:
        """Check US Manufacturing PMI via FRED MANEMP proxy."""
        signals = []
        score = 5.0

        obs = await self._fetch_fred("MANEMP", limit=6)
        if not obs:
            # Fallback: try industrial production
            obs = await self._fetch_fred("INDPRO", limit=6)

        if not obs:
            return 5.0, ["PMI proxy: unavailable"]

        try:
            values = []
            for o in obs:
                v = o.get("value", ".")
                if v != ".":
                    values.append(float(v))
                if len(values) >= 3:
                    break

            if len(values) < 2:
                return 5.0, ["PMI proxy: insufficient data"]

            current = values[0]
            prev = values[1]
            change_pct = ((current - prev) / prev) * 100

            signals.append(f"Manufacturing employment: {current:.0f}K (MoM: {change_pct:+.2f}%)")

            if change_pct > 1.0:
                score = 8.0
                signals.append("Manufacturing expanding strongly -- bullish industrial silver")
            elif change_pct > 0.3:
                score = 6.5
                signals.append("Manufacturing growing -- positive for silver demand")
            elif change_pct < -1.0:
                score = 2.5
                signals.append("Manufacturing contracting -- bearish industrial silver")
            elif change_pct < -0.3:
                score = 3.5
                signals.append("Manufacturing softening")
            else:
                score = 5.0

        except (ValueError, TypeError) as e:
            signals.append(f"PMI proxy error: {str(e)[:50]}")

        return score, signals

    async def _fetch_fred(self, series_id: str, limit: int = 10):
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
