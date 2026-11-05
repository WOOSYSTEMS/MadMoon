"""
MadEye Gold -- Geopolitical/Safe Haven Collector
Gold is the ultimate safe haven. War, crisis, sanctions = bullish gold.
VIX spike = fear = bullish gold.
Weight: 10% of total signal.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Tuple

from .base import BaseCollector

logger = logging.getLogger("madeye.gold")

# Geopolitical keywords that drive safe-haven gold demand
CRISIS_KEYWORDS_HIGH = [
    "nuclear", "world war", "invasion", "missile strike", "military attack",
    "declaration of war", "martial law", "coup", "regime collapse",
]
CRISIS_KEYWORDS_MEDIUM = [
    "sanctions", "trade war", "tariffs", "conflict escalation", "military buildup",
    "diplomatic crisis", "embargo", "blockade", "cyber attack",
    "debt ceiling", "default risk", "bank failure", "financial crisis",
]
CRISIS_KEYWORDS_LOW = [
    "geopolitical tension", "political uncertainty", "election crisis",
    "protest", "civil unrest", "border dispute", "diplomatic row",
]


class GeopoliticalGoldCollector(BaseCollector):
    name = "geopolitical_gold"
    category = "geopolitical"
    cache_ttl = 900  # 15 minutes

    def __init__(self, newsapi_key: str = None):
        super().__init__()
        self.newsapi_key = newsapi_key

    async def collect(self) -> Dict:
        signals = []
        subscores = []

        # --- 1. VIX (Fear Index) ---
        vix_score, vix_signals, vix_details = await self._analyze_vix()
        subscores.append(("vix", vix_score, 0.35))
        signals.extend(vix_signals)

        # --- 2. Crisis News Headlines ---
        news_score, news_signals = await self._analyze_crisis_news()
        subscores.append(("crisis_news", news_score, 0.35))
        signals.extend(news_signals)

        # --- 3. GDELT geopolitical tone ---
        gdelt_score, gdelt_signals = await self._analyze_gdelt_tone()
        subscores.append(("gdelt", gdelt_score, 0.30))
        signals.extend(gdelt_signals)

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
                "vix_score": round(vix_score, 2),
                "crisis_news_score": round(news_score, 2),
                "gdelt_score": round(gdelt_score, 2),
                **vix_details,
            },
            confidence=confidence,
        )

    async def _analyze_vix(self) -> Tuple[float, List[str], Dict]:
        """Fetch VIX from Yahoo Finance ^VIX."""
        signals = []
        details = {}
        score = 5.0

        try:
            import yfinance as yf
            ticker = yf.Ticker("^VIX")
            hist = ticker.history(period="1mo")

            if hist.empty:
                return 5.0, ["VIX: No data"], {}

            prices = hist["Close"].dropna().tolist()
            current = prices[-1]
            details["vix_current"] = round(current, 2)
            signals.append(f"VIX: {current:.2f}")

            # VIX level scoring
            if current > 40:
                score = 9.5
                signals.append("VIX extreme fear (>40) -- panic buying gold as safe haven")
            elif current > 30:
                score = 8.5
                signals.append("VIX high fear (>30) -- strong safe haven demand for gold")
            elif current > 25:
                score = 7.5
                signals.append("VIX elevated (>25) -- increased gold demand")
            elif current > 20:
                score = 6.0
                signals.append("VIX moderate (>20) -- mild safe haven bid")
            elif current > 15:
                score = 4.5
                signals.append("VIX low (<20) -- complacency, less gold demand")
            elif current > 12:
                score = 3.5
                signals.append("VIX very low -- extreme complacency, bearish for gold demand")
            else:
                score = 2.5
                signals.append("VIX historically low -- no fear, no safe haven bid")

            # VIX rate of change (spike detection)
            if len(prices) >= 2:
                vix_change = current - prices[-2]
                vix_pct_change = vix_change / prices[-2] * 100

                details["vix_daily_change"] = round(vix_change, 2)

                if vix_pct_change > 20:
                    score = min(10, score + 1.5)
                    signals.append(f"VIX SPIKE +{vix_pct_change:.1f}% -- panic mode, gold surge likely")
                elif vix_pct_change > 10:
                    score = min(10, score + 1.0)
                    signals.append(f"VIX surge +{vix_pct_change:.1f}% -- fear rising fast")
                elif vix_pct_change < -15:
                    score = max(0, score - 1.0)
                    signals.append(f"VIX plunge {vix_pct_change:.1f}% -- fear unwinding, gold pressure")

            # VIX trend (5-day)
            if len(prices) >= 6:
                vix_5d_change = (current - prices[-6]) / prices[-6] * 100
                if vix_5d_change > 30:
                    score = min(10, score + 0.5)
                    signals.append(f"VIX 5d trend: +{vix_5d_change:.1f}% -- sustained fear")

        except Exception as e:
            logger.warning(f"VIX error: {e}")
            signals.append("VIX data unavailable")

        return score, signals, details

    async def _analyze_crisis_news(self) -> Tuple[float, List[str]]:
        """Scan news for geopolitical crisis headlines."""
        signals = []
        score = 5.0

        if not self.newsapi_key:
            return 5.0, ["Crisis news: No API key"]

        try:
            url = "https://newsapi.org/v2/everything"
            params = {
                "q": "war OR conflict OR nuclear OR sanctions OR crisis OR military",
                "apiKey": self.newsapi_key,
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": 30,
            }
            data = await self.fetch_json(url, params=params, cache_key="crisis_news")

            if data and "articles" in data:
                articles = data["articles"]
                high_severity = 0
                medium_severity = 0
                low_severity = 0

                for article in articles:
                    title = (article.get("title") or "").lower()
                    desc = (article.get("description") or "").lower()
                    text = title + " " + desc

                    for kw in CRISIS_KEYWORDS_HIGH:
                        if kw in text:
                            high_severity += 1
                            break
                    for kw in CRISIS_KEYWORDS_MEDIUM:
                        if kw in text:
                            medium_severity += 1
                            break
                    for kw in CRISIS_KEYWORDS_LOW:
                        if kw in text:
                            low_severity += 1
                            break

                signals.append(
                    f"Crisis news: {high_severity} critical, {medium_severity} elevated, {low_severity} low"
                )

                # Score based on severity
                crisis_intensity = high_severity * 3 + medium_severity * 1.5 + low_severity * 0.5

                if crisis_intensity > 20:
                    score = 9.5
                    signals.append("EXTREME geopolitical crisis -- gold safe haven in full effect")
                elif crisis_intensity > 12:
                    score = 8.0
                    signals.append("High geopolitical tension -- strong safe haven gold demand")
                elif crisis_intensity > 6:
                    score = 7.0
                    signals.append("Elevated geopolitical risk -- gold demand supported")
                elif crisis_intensity > 3:
                    score = 6.0
                    signals.append("Moderate geopolitical noise")
                else:
                    score = 4.5
                    signals.append("Low geopolitical risk -- less safe haven demand")

        except Exception as e:
            logger.warning(f"Crisis news error: {e}")
            signals.append("Crisis news fetch failed")

        return score, signals

    async def _analyze_gdelt_tone(self) -> Tuple[float, List[str]]:
        """Analyze GDELT tone for geopolitical events."""
        signals = []
        score = 5.0

        try:
            # GDELT DOC 2.0 API for gold-related geopolitical tone
            url = "https://api.gdeltproject.org/api/v2/doc/doc"
            params = {
                "query": "gold safe haven OR gold crisis OR gold war",
                "mode": "tonechart",
                "format": "json",
                "timespan": "24h",
            }
            data = await self.fetch_json(url, params=params, cache_key="gdelt_gold_tone")

            if data and isinstance(data, dict):
                # GDELT returns tone data
                tone_data = data.get("tonechart", [])
                if tone_data:
                    # Average tone: negative = more negative sentiment = more crisis = bullish gold
                    avg_tone = sum(t.get("tone", 0) for t in tone_data) / len(tone_data) if tone_data else 0
                    signals.append(f"GDELT gold/crisis tone: {avg_tone:.2f}")

                    if avg_tone < -5:
                        score = 9.0
                        signals.append("GDELT: Very negative global tone -- strong safe haven bid")
                    elif avg_tone < -2:
                        score = 7.5
                        signals.append("GDELT: Negative global tone -- safe haven supported")
                    elif avg_tone < 0:
                        score = 6.0
                        signals.append("GDELT: Mildly negative tone")
                    elif avg_tone > 3:
                        score = 3.0
                        signals.append("GDELT: Positive global tone -- risk-on, less gold demand")
                    else:
                        score = 5.0

            elif data and isinstance(data, list):
                # Sometimes GDELT returns array directly
                if len(data) > 0:
                    avg_tone = sum(item.get("tone", 0) for item in data if isinstance(item, dict)) / max(1, len(data))
                    if avg_tone < -3:
                        score = 7.5
                    elif avg_tone > 2:
                        score = 3.5

        except Exception as e:
            logger.warning(f"GDELT error: {e}")
            signals.append("GDELT tone unavailable")

        return score, signals
