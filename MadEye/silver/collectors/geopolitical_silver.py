"""
MadEye Silver -- Geopolitical Collector (Weight: 8%)
Safe haven + supply disruption from top producers.
Mexico mining (top producer), Peru political instability, China export controls, VIX.
"""

import logging
from typing import Dict, Tuple

from .base import BaseCollector

logger = logging.getLogger("madeye.silver")

NEWSAPI_BASE = "https://newsapi.org/v2/everything"


class GeopoliticalSilverCollector(BaseCollector):
    name = "geopolitical_silver"
    category = "geopolitical"
    cache_ttl = 1800  # 30 minutes

    def __init__(self, newsapi_key: str = ""):
        super().__init__()
        self.newsapi_key = newsapi_key

    async def collect(self) -> Dict:
        signals = []
        subscores = []

        # --- 1. Mexico Mining Disruption ---
        mexico_score, mexico_signals = await self._check_mexico()
        subscores.append(mexico_score)
        signals.extend(mexico_signals)

        # --- 2. Peru Political Risk ---
        peru_score, peru_signals = await self._check_peru()
        subscores.append(peru_score)
        signals.extend(peru_signals)

        # --- 3. China Silver Export Controls ---
        china_score, china_signals = await self._check_china()
        subscores.append(china_score)
        signals.extend(china_signals)

        # --- 4. VIX Risk Sentiment ---
        vix_score, vix_signals = await self._check_vix()
        subscores.append(vix_score)
        signals.extend(vix_signals)

        # Weighted: Mexico 30%, Peru 20%, China 25%, VIX 25%
        weights = [0.30, 0.20, 0.25, 0.25]
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
                "mexico_score": round(mexico_score, 2),
                "peru_score": round(peru_score, 2),
                "china_score": round(china_score, 2),
                "vix_score": round(vix_score, 2),
            },
            confidence=confidence,
        )

    async def _check_mexico(self) -> Tuple[float, list]:
        """Check Mexico mining security / disruption news."""
        signals = []
        score = 5.0

        if not self.newsapi_key:
            return 5.0, ["Mexico mining: no NewsAPI key"]

        data = await self.fetch_json(
            NEWSAPI_BASE,
            params={
                "q": '"Mexico mining" OR "Mexico silver mine" OR "cartel mining" OR "Zacatecas mine" OR "Durango mine"',
                "apiKey": self.newsapi_key,
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": "15",
            },
            cache_key="mexico_mining",
        )

        if not data or "articles" not in data:
            return 5.0, ["Mexico mining news: unavailable"]

        total = data.get("totalResults", 0)
        articles = data.get("articles", [])
        signals.append(f"Mexico mining news: {total} articles")

        disruption_kw = ["shutdown", "suspend", "attack", "cartel", "violence",
                        "blockade", "protest", "halt", "evacuate", "closed"]
        disruption_count = 0
        for article in articles[:10]:
            title = (article.get("title", "") or "").lower()
            desc = (article.get("description", "") or "").lower()
            text = title + " " + desc
            for kw in disruption_kw:
                if kw in text:
                    disruption_count += 1
                    break

        if disruption_count >= 4:
            score = 8.5
            signals.append("Multiple Mexico mine disruptions -- major supply risk, bullish silver")
        elif disruption_count >= 2:
            score = 7.0
            signals.append("Mexico mining disruptions reported -- supply risk")
        elif disruption_count >= 1:
            score = 6.0
            signals.append("Some Mexico mining disruption")
        else:
            score = 5.0

        return score, signals

    async def _check_peru(self) -> Tuple[float, list]:
        """Check Peru political / mining disruption."""
        signals = []
        score = 5.0

        if not self.newsapi_key:
            return 5.0, ["Peru risk: no NewsAPI key"]

        data = await self.fetch_json(
            NEWSAPI_BASE,
            params={
                "q": '"Peru mining" OR "Peru protest mine" OR "Peru blockade" OR "Petroperu"',
                "apiKey": self.newsapi_key,
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": "10",
            },
            cache_key="peru_mining",
        )

        if not data or "articles" not in data:
            return 5.0, ["Peru mining news: unavailable"]

        total = data.get("totalResults", 0)
        articles = data.get("articles", [])

        disruption_kw = ["blockade", "protest", "shutdown", "crisis", "suspend", "halt"]
        disruption_count = 0
        for article in articles[:8]:
            title = (article.get("title", "") or "").lower()
            desc = (article.get("description", "") or "").lower()
            text = title + " " + desc
            for kw in disruption_kw:
                if kw in text:
                    disruption_count += 1
                    break

        signals.append(f"Peru mining news: {total} articles, {disruption_count} disruptions")

        if disruption_count >= 3:
            score = 8.0
            signals.append("Peru major disruptions -- silver supply risk, bullish")
        elif disruption_count >= 1:
            score = 6.5
            signals.append("Peru disruption signals -- watching")
        else:
            score = 5.0

        return score, signals

    async def _check_china(self) -> Tuple[float, list]:
        """Check China silver export control news."""
        signals = []
        score = 5.0

        if not self.newsapi_key:
            return 5.0, ["China silver: no NewsAPI key"]

        data = await self.fetch_json(
            NEWSAPI_BASE,
            params={
                "q": '"China silver export" OR "China silver restrict" OR "China silver stockpile"',
                "apiKey": self.newsapi_key,
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": "10",
            },
            cache_key="china_silver",
        )

        if not data or "articles" not in data:
            return 5.0, ["China silver news: unavailable"]

        total = data.get("totalResults", 0)
        articles = data.get("articles", [])

        restrict_kw = ["restrict", "ban", "control", "limit", "stockpile", "hoard"]
        restrict_count = 0
        for article in articles[:8]:
            title = (article.get("title", "") or "").lower()
            desc = (article.get("description", "") or "").lower()
            text = title + " " + desc
            for kw in restrict_kw:
                if kw in text:
                    restrict_count += 1
                    break

        signals.append(f"China silver export news: {total} articles, {restrict_count} restriction mentions")

        if restrict_count >= 3:
            score = 8.5
            signals.append("China restricting silver exports -- global supply tightens, very bullish")
        elif restrict_count >= 1:
            score = 6.5
            signals.append("Some China silver restriction signals")
        else:
            score = 5.0

        return score, signals

    async def _check_vix(self) -> Tuple[float, list]:
        """Check VIX for risk sentiment. Silver is a weaker safe haven than gold."""
        signals = []
        score = 5.0

        try:
            import yfinance as yf
            vix = yf.Ticker("^VIX")
            hist = vix.history(period="1mo")

            if hist.empty:
                return 5.0, ["VIX: no data"]

            vix_values = hist["Close"].dropna().tolist()
            if not vix_values:
                return 5.0, ["VIX: empty data"]

            current_vix = vix_values[-1]
            avg_vix = sum(vix_values) / len(vix_values)

            signals.append(f"VIX: {current_vix:.1f} (month avg: {avg_vix:.1f})")

            # Silver behavior with VIX:
            # Moderate VIX rise (20-30) = safe haven bid, mildly bullish
            # Extreme VIX (>35) = PANIC = silver drops initially (industrial fear) then recovers
            # Low VIX (<15) = complacency, neutral
            if current_vix > 40:
                score = 3.5
                signals.append("VIX extreme -- panic mode, silver drops initially before recovery")
            elif current_vix > 30:
                score = 4.5
                signals.append("VIX elevated -- risk-off, mixed for silver (safe haven vs industrial)")
            elif current_vix > 20:
                score = 6.0
                signals.append("VIX moderate -- some safe haven bid for silver")
            elif current_vix < 13:
                score = 5.0
                signals.append("VIX very low -- complacency, no safe haven bid")
            else:
                score = 5.0

        except Exception as e:
            logger.warning(f"VIX error: {e}")
            signals.append(f"VIX: error ({str(e)[:50]})")

        return score, signals
