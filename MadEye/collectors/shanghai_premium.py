"""
MadEye Shanghai Gold Premium Collector
Tracks premium of Shanghai Gold Exchange (SGE) over London/COMEX fix.
Premium > $20/oz = strong Chinese demand = bullish gold.
Premium negative = weak Chinese demand = bearish gold.
"""

import logging
from typing import Dict

from .base import BaseCollector

logger = logging.getLogger("madeye")

YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=5d"
YAHOO_HEADERS = {"User-Agent": "Mozilla/5.0"}
NEWSAPI_URL = "https://newsapi.org/v2/everything"
NEWSAPI_KEY = "9a1a0c6118414732871c9f72618818d9"


class ShanghaiPremiumCollector(BaseCollector):
    name = "shanghai_premium"
    category = "physical_demand"
    cache_ttl = 3600  # 1 hour

    async def _get_gold_price(self) -> float:
        """Fetch COMEX gold price from Yahoo Finance."""
        url = YAHOO_CHART.format(ticker="GC=F")
        data = await self.fetch_json(url, cache_key="gold_comex")
        if not data:
            return 0.0
        try:
            result = data["chart"]["result"][0]
            closes = result["indicators"]["quote"][0]["close"]
            # Get last non-None close
            for c in reversed(closes):
                if c is not None:
                    return float(c)
        except (KeyError, IndexError, TypeError):
            pass
        return 0.0

    async def _get_shanghai_premium_from_news(self) -> Dict:
        """Estimate Shanghai premium from news articles."""
        params = {
            "q": '"Shanghai gold premium" OR "SGE premium" OR "Shanghai premium gold"',
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": 10,
            "apiKey": NEWSAPI_KEY,
        }
        data = await self.fetch_json(NEWSAPI_URL, params=params, cache_key="shanghai_news")
        if not data or data.get("status") != "ok":
            return {"premium": None, "articles": 0, "sentiment": "unknown"}

        articles = data.get("articles", [])
        if not articles:
            return {"premium": None, "articles": 0, "sentiment": "unknown"}

        # Parse premium mentions from article titles/descriptions
        premium_mentions = []
        bullish_count = 0
        bearish_count = 0

        for article in articles:
            text = f"{article.get('title', '')} {article.get('description', '')}".lower()

            # Look for dollar premium numbers
            import re
            matches = re.findall(r'\$(\d+(?:\.\d+)?)\s*(?:per\s*ounce|/oz|premium)', text)
            for m in matches:
                premium_mentions.append(float(m))

            # Sentiment keywords
            if any(w in text for w in ["strong demand", "premium widens", "premium rises",
                                       "buying surge", "record premium", "high premium"]):
                bullish_count += 1
            if any(w in text for w in ["discount", "premium narrows", "premium falls",
                                       "weak demand", "selling", "negative premium"]):
                bearish_count += 1

        avg_premium = sum(premium_mentions) / len(premium_mentions) if premium_mentions else None

        if bullish_count > bearish_count:
            sentiment = "bullish"
        elif bearish_count > bullish_count:
            sentiment = "bearish"
        else:
            sentiment = "neutral"

        return {
            "premium": avg_premium,
            "articles": len(articles),
            "sentiment": sentiment,
            "bullish_mentions": bullish_count,
            "bearish_mentions": bearish_count,
        }

    async def collect(self) -> Dict:
        signals = []
        score = 5.0
        confidence = 0.3

        gold_price = await self._get_gold_price()
        if gold_price > 0:
            signals.append(f"COMEX gold (GC=F): ${gold_price:.2f}/oz")
        else:
            signals.append("COMEX gold price unavailable")

        news_data = await self._get_shanghai_premium_from_news()
        details = {"gold_price": gold_price, "news_data": news_data}

        if news_data["premium"] is not None:
            premium = news_data["premium"]
            signals.append(f"SGE premium estimate: ${premium:.2f}/oz")
            confidence = 0.7

            if premium > 40:
                score = 9.5
                signals.append("Extreme Shanghai premium (>$40) -- massive Chinese buying, very bullish gold")
            elif premium > 20:
                score = 8.0
                signals.append("High Shanghai premium (>$20) -- strong Chinese demand, bullish gold")
            elif premium > 10:
                score = 7.0
                signals.append("Moderate Shanghai premium -- healthy Chinese demand")
            elif premium > 0:
                score = 5.5
                signals.append("Small Shanghai premium -- normal demand")
            elif premium > -10:
                score = 4.0
                signals.append("Shanghai discount -- weak Chinese demand, mildly bearish")
            else:
                score = 2.0
                signals.append("Large Shanghai discount -- very weak Chinese demand, bearish gold")
        elif news_data["articles"] > 0:
            # Use sentiment as fallback
            sentiment = news_data["sentiment"]
            confidence = 0.4

            if sentiment == "bullish":
                score = 7.0
                signals.append(f"Shanghai premium news sentiment: bullish ({news_data['bullish_mentions']} mentions)")
            elif sentiment == "bearish":
                score = 3.0
                signals.append(f"Shanghai premium news sentiment: bearish ({news_data['bearish_mentions']} mentions)")
            else:
                score = 5.0
                signals.append("Shanghai premium news: mixed/neutral sentiment")
        else:
            signals.append("No Shanghai premium data available")
            confidence = 0.1

        if score >= 6.5:
            direction = "BULLISH"
        elif score <= 3.5:
            direction = "BEARISH"
        else:
            direction = "NEUTRAL"

        return self.make_result(
            score=score,
            direction=direction,
            signals=signals,
            details=details,
            confidence=confidence,
        )
