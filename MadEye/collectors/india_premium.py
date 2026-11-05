"""
MadEye India Physical Gold/Silver Premium Collector
Tracks Indian physical gold and silver premiums via news.
Premium = bullish (strong physical demand), discount = bearish.
Seasonal factors: Diwali (Oct-Nov), wedding season, import duty changes.
"""

import logging
import re
from datetime import datetime, timezone
from typing import Dict

from .base import BaseCollector

logger = logging.getLogger("madeye")

NEWSAPI_URL = "https://newsapi.org/v2/everything"
NEWSAPI_KEY = "9a1a0c6118414732871c9f72618818d9"


class IndiaPremiumCollector(BaseCollector):
    name = "india_premium"
    category = "physical_demand"
    cache_ttl = 3600  # 1 hour

    async def _fetch_india_news(self) -> Dict:
        """Fetch India gold/silver premium news from NewsAPI."""
        params = {
            "q": '"India gold premium" OR "India silver premium" OR "India gold demand" OR "India gold discount" OR "India gold import"',
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": 15,
            "apiKey": NEWSAPI_KEY,
        }
        data = await self.fetch_json(NEWSAPI_URL, params=params, cache_key="india_premium_news")
        if not data or data.get("status") != "ok":
            return {"articles": [], "total": 0}
        return {"articles": data.get("articles", []), "total": data.get("totalResults", 0)}

    def _analyze_articles(self, articles: list) -> Dict:
        """Analyze article content for premium/discount signals."""
        premium_values = []
        discount_values = []
        bullish_count = 0
        bearish_count = 0
        duty_change = False
        festival_mention = False

        for article in articles:
            text = f"{article.get('title', '')} {article.get('description', '')}".lower()

            # Extract premium amounts
            prem_matches = re.findall(r'premium\s+(?:of\s+)?\$?(\d+(?:\.\d+)?)', text)
            for m in prem_matches:
                premium_values.append(float(m))

            disc_matches = re.findall(r'discount\s+(?:of\s+)?\$?(\d+(?:\.\d+)?)', text)
            for m in disc_matches:
                discount_values.append(float(m))

            # Sentiment keywords
            if any(w in text for w in ["strong demand", "premium rises", "buying spree",
                                       "import surge", "record imports", "festival demand",
                                       "wedding season", "diwali demand", "jewel"]):
                bullish_count += 1
            if any(w in text for w in ["discount", "weak demand", "import falls",
                                       "slowdown", "price resistance", "consumers shun"]):
                bearish_count += 1

            # Special events
            if any(w in text for w in ["import duty", "duty cut", "duty hike", "tariff"]):
                duty_change = True
            if any(w in text for w in ["diwali", "dhanteras", "akshaya tritiya", "wedding"]):
                festival_mention = True

        return {
            "premium_values": premium_values,
            "discount_values": discount_values,
            "bullish_count": bullish_count,
            "bearish_count": bearish_count,
            "duty_change": duty_change,
            "festival_mention": festival_mention,
        }

    def _seasonal_factor(self) -> tuple:
        """Check if we're in a high-demand season for Indian gold."""
        now = datetime.now(timezone.utc)
        month = now.month
        signals = []
        bonus = 0.0

        # Diwali/Dhanteras season (October-November)
        if month in (10, 11):
            signals.append("Indian festive season (Diwali/Dhanteras) -- historically peak gold demand")
            bonus = 0.5
        # Wedding season (November-February)
        elif month in (11, 12, 1, 2):
            signals.append("Indian wedding season -- elevated gold demand")
            bonus = 0.3
        # Akshaya Tritiya (April-May)
        elif month in (4, 5):
            signals.append("Akshaya Tritiya period -- auspicious gold buying")
            bonus = 0.3
        # Low season
        elif month in (6, 7, 8):
            signals.append("Indian monsoon season -- traditionally lower gold demand")
            bonus = -0.3

        return bonus, signals

    async def collect(self) -> Dict:
        signals = []
        score = 5.0
        confidence = 0.3

        # Fetch news
        news = await self._fetch_india_news()
        articles = news["articles"]

        if articles:
            analysis = self._analyze_articles(articles)
            details = {
                "article_count": len(articles),
                "analysis": {k: v for k, v in analysis.items()
                             if k not in ("premium_values", "discount_values")},
            }

            signals.append(f"India gold/silver news: {len(articles)} recent articles")

            # Premium/discount scoring
            if analysis["premium_values"]:
                avg_prem = sum(analysis["premium_values"]) / len(analysis["premium_values"])
                signals.append(f"Average India premium: ${avg_prem:.1f}/oz")
                if avg_prem > 5:
                    score = 8.0
                elif avg_prem > 2:
                    score = 7.0
                else:
                    score = 6.0
                confidence = 0.7
            elif analysis["discount_values"]:
                avg_disc = sum(analysis["discount_values"]) / len(analysis["discount_values"])
                signals.append(f"Average India discount: ${avg_disc:.1f}/oz")
                if avg_disc > 10:
                    score = 2.0
                elif avg_disc > 5:
                    score = 3.0
                else:
                    score = 4.0
                confidence = 0.7
            else:
                # Use sentiment
                b = analysis["bullish_count"]
                br = analysis["bearish_count"]
                if b > br and b >= 2:
                    score = 7.0
                    signals.append(f"India demand sentiment: bullish ({b} vs {br} mentions)")
                elif br > b and br >= 2:
                    score = 3.0
                    signals.append(f"India demand sentiment: bearish ({br} vs {b} mentions)")
                else:
                    score = 5.0
                    signals.append("India demand sentiment: mixed/neutral")
                confidence = 0.4

            # Duty change flag
            if analysis["duty_change"]:
                signals.append("Import duty change detected -- major demand driver")
                confidence = min(1.0, confidence + 0.1)

            # Festival mention
            if analysis["festival_mention"]:
                signals.append("Festival/wedding season mentioned in news")
        else:
            signals.append("No recent India premium news available")
            details = {"article_count": 0}

        # Seasonal adjustment
        seasonal_bonus, seasonal_signals = self._seasonal_factor()
        score += seasonal_bonus
        signals.extend(seasonal_signals)

        score = max(0.0, min(10.0, score))

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
