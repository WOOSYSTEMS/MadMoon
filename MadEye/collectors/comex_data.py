"""
MadEye COMEX Warehouse Stocks and Delivery Data Collector
Tracks COMEX gold/silver registered vs eligible inventory.
Falling registered = delivery squeeze potential = bullish.
"""

import logging
import re
from typing import Dict, List, Tuple

from .base import BaseCollector

logger = logging.getLogger("madeye")

NEWSAPI_URL = "https://newsapi.org/v2/everything"
NEWSAPI_KEY = "9a1a0c6118414732871c9f72618818d9"


class ComexDataCollector(BaseCollector):
    name = "comex_data"
    category = "physical_demand"
    cache_ttl = 3600  # 1 hour

    async def _fetch_comex_news(self, metal: str) -> List[Dict]:
        """Fetch COMEX inventory news for a specific metal."""
        params = {
            "q": f'"COMEX {metal} inventory" OR "COMEX {metal} stocks" OR "COMEX {metal} delivery" OR "COMEX {metal} warehouse" OR "COMEX {metal} registered"',
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": 10,
            "apiKey": NEWSAPI_KEY,
        }
        data = await self.fetch_json(NEWSAPI_URL, params=params,
                                     cache_key=f"comex_{metal.lower()}_news")
        if not data or data.get("status") != "ok":
            return []
        return data.get("articles", [])

    def _analyze_metal_news(self, articles: List[Dict], metal: str) -> Tuple[float, List[str], Dict]:
        """Analyze COMEX news for a specific metal."""
        signals = []
        score = 5.0
        details = {}

        if not articles:
            signals.append(f"COMEX {metal}: no recent news")
            return 5.0, signals, details

        bullish_count = 0
        bearish_count = 0
        inventory_mentions = []

        for article in articles:
            text = f"{article.get('title', '')} {article.get('description', '')}".lower()

            # Look for inventory numbers (millions of ounces or tonnes)
            oz_matches = re.findall(r'(\d+(?:\.\d+)?)\s*(?:million|mln|m)\s*(?:ounces|oz|troy)', text)
            for m in oz_matches:
                inventory_mentions.append(float(m))

            tonne_matches = re.findall(r'(\d+(?:\.\d+)?)\s*(?:tonnes?|tons?)', text)
            for m in tonne_matches:
                inventory_mentions.append(float(m))

            # Bullish signals (falling inventories)
            if any(w in text for w in ["inventory fall", "stocks decline", "registered drop",
                                       "outflow", "delivery surge", "warehouse drain",
                                       "lowest since", "record low", "squeeze",
                                       "registered to eligible", "depleted"]):
                bullish_count += 1

            # Bearish signals (rising inventories)
            if any(w in text for w in ["inventory rise", "stocks increase", "inflow",
                                       "rebuild", "highest since", "record high",
                                       "eligible to registered", "surplus"]):
                bearish_count += 1

        details = {
            "articles": len(articles),
            "bullish_signals": bullish_count,
            "bearish_signals": bearish_count,
            "inventory_mentions": inventory_mentions[:5],
        }

        signals.append(f"COMEX {metal}: {len(articles)} news articles")
        signals.append(f"COMEX {metal}: {bullish_count} bullish vs {bearish_count} bearish inventory signals")

        # Score based on signal balance
        net = bullish_count - bearish_count

        if net >= 3:
            score = 9.0
            signals.append(f"COMEX {metal}: strong inventory depletion signals -- very bullish")
        elif net >= 2:
            score = 7.5
            signals.append(f"COMEX {metal}: falling inventories -- bullish")
        elif net >= 1:
            score = 6.5
            signals.append(f"COMEX {metal}: mildly declining inventories")
        elif net == 0:
            score = 5.0
            signals.append(f"COMEX {metal}: mixed inventory signals")
        elif net >= -1:
            score = 4.0
            signals.append(f"COMEX {metal}: mildly rising inventories")
        elif net >= -2:
            score = 3.0
            signals.append(f"COMEX {metal}: rebuilding inventories -- bearish")
        else:
            score = 2.0
            signals.append(f"COMEX {metal}: strong inventory rebuild -- very bearish")

        return score, signals, details

    async def collect(self) -> Dict:
        signals = []
        confidence = 0.3

        # Gold
        gold_articles = await self._fetch_comex_news("gold")
        gold_score, gold_signals, gold_details = self._analyze_metal_news(gold_articles, "Gold")
        signals.extend(gold_signals)

        # Silver
        silver_articles = await self._fetch_comex_news("silver")
        silver_score, silver_signals, silver_details = self._analyze_metal_news(silver_articles, "Silver")
        signals.extend(silver_signals)

        # Composite: gold 55%, silver 45%
        composite = gold_score * 0.55 + silver_score * 0.45

        if gold_articles or silver_articles:
            confidence = 0.5
            if len(gold_articles) >= 3 or len(silver_articles) >= 3:
                confidence = 0.6

        details = {
            "gold_score": round(gold_score, 2),
            "silver_score": round(silver_score, 2),
            "gold": gold_details,
            "silver": silver_details,
        }

        if composite >= 6.5:
            direction = "BULLISH"
        elif composite <= 3.5:
            direction = "BEARISH"
        else:
            direction = "NEUTRAL"

        return self.make_result(
            score=composite,
            direction=direction,
            signals=signals,
            details=details,
            confidence=confidence,
        )
