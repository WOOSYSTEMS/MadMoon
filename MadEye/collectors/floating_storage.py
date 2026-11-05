"""
MadEye Floating Storage Collector
Uses NewsAPI to monitor floating storage / tanker storage mentions.
Rising floating storage = bearish (oversupply).
Falling floating storage = bullish (demand absorbing supply).
"""

import logging
from typing import Dict

from .base import BaseCollector

logger = logging.getLogger("madeye")

NEWSAPI_BASE = "https://newsapi.org/v2/everything"


def _load_newsapi_key():
    """Load NewsAPI key from data file or environment."""
    import os
    key_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "newsapi_key.txt")
    if os.path.exists(key_path):
        with open(key_path) as f:
            return f.read().strip()
    return os.environ.get("NEWSAPI_KEY", "")


class FloatingStorageCollector(BaseCollector):
    name = "floating_storage"
    category = "floating_storage"
    cache_ttl = 3600  # 1 hour

    def __init__(self, newsapi_key: str = None):
        super().__init__()
        self.newsapi_key = newsapi_key or _load_newsapi_key()

    async def collect(self) -> Dict:
        signals = []
        score = 5.0
        confidence = 0.3

        # --- 1. NewsAPI floating storage search ---
        storage_score, storage_signals = await self._check_floating_storage_news()
        signals.extend(storage_signals)

        # --- 2. GDELT backup for broader coverage ---
        gdelt_score, gdelt_signals = await self._check_gdelt_storage()
        signals.extend(gdelt_signals)

        # Combine: NewsAPI 60%, GDELT 40%
        if storage_score != 5.0 or gdelt_score != 5.0:
            score = storage_score * 0.6 + gdelt_score * 0.4
            confidence = 0.6
        else:
            score = 5.0
            confidence = 0.2

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
            details={
                "newsapi_score": round(storage_score, 2),
                "gdelt_score": round(gdelt_score, 2),
            },
            confidence=confidence,
        )

    async def _check_floating_storage_news(self) -> tuple:
        """Search NewsAPI for floating storage mentions."""
        signals = []
        score = 5.0

        if not self.newsapi_key:
            signals.append("Floating storage: NewsAPI key not configured")
            return score, signals

        params = {
            "q": '"floating storage" OR "tanker storage" OR "oil storage tanker"',
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": "30",
            "apiKey": self.newsapi_key,
        }

        data = await self.fetch_json(
            NEWSAPI_BASE, params=params, cache_key="newsapi_floating_storage"
        )

        if not data or data.get("status") != "ok":
            signals.append("Floating storage NewsAPI: unavailable")
            return score, signals

        articles = data.get("articles", [])
        total = len(articles)
        signals.append(f"Floating storage articles: {total}")

        if total == 0:
            signals.append("No floating storage news -- likely normal conditions")
            return 5.5, signals  # Slightly bullish -- no storage buildup news

        # Analyze sentiment
        rising_count = 0
        falling_count = 0
        for art in articles:
            title = (art.get("title", "") or "").lower()
            desc = (art.get("description", "") or "").lower()
            text = title + " " + desc

            for kw in ["increase", "rise", "build", "surge", "record", "high",
                        "growing", "overflow", "full", "glut"]:
                if kw in text:
                    rising_count += 1
                    break
            for kw in ["decline", "fall", "drop", "draw", "empty", "decrease",
                        "shrink", "lowest", "reduce"]:
                if kw in text:
                    falling_count += 1
                    break

        signals.append(f"Storage rising mentions: {rising_count} | Falling mentions: {falling_count}")

        # Rising floating storage = bearish for oil (oversupply)
        # Falling floating storage = bullish (demand absorbing)
        if rising_count > falling_count + 3:
            score = 2.5
            signals.append("Floating storage RISING strongly -- oversupply, bearish")
        elif rising_count > falling_count:
            score = 3.5
            signals.append("Floating storage increasing -- mild bearish")
        elif falling_count > rising_count + 3:
            score = 8.0
            signals.append("Floating storage FALLING sharply -- demand absorbing supply, bullish")
        elif falling_count > rising_count:
            score = 6.5
            signals.append("Floating storage decreasing -- mildly bullish")
        else:
            score = 5.0
            signals.append("Floating storage: mixed signals")

        # High article count itself = something notable happening
        if total > 15:
            signals.append("High floating storage coverage -- market watching closely")

        return score, signals

    async def _check_gdelt_storage(self) -> tuple:
        """Check GDELT for oil storage news."""
        signals = []
        score = 5.0

        url = "https://api.gdeltproject.org/api/v2/doc/doc"
        params = {
            "query": "floating+storage+oil+OR+tanker+storage+crude+OR+oil+surplus+storage",
            "mode": "artlist",
            "maxrecords": "30",
            "format": "json",
            "timespan": "7d",
        }

        data = await self.fetch_json(url, params=params, cache_key="gdelt_floating_storage")
        if not data:
            signals.append("GDELT floating storage: unavailable")
            return score, signals

        articles = data.get("articles", [])
        count = len(articles)
        signals.append(f"GDELT storage articles (7d): {count}")

        if count == 0:
            return 5.5, signals  # No news = no buildup = slightly bullish

        # Analyze for buildup vs drawdown
        buildup = 0
        drawdown = 0
        for art in articles:
            title = (art.get("title", "") or "").lower()
            for kw in ["build", "increase", "surplus", "glut", "overflow", "full"]:
                if kw in title:
                    buildup += 1
                    break
            for kw in ["draw", "decrease", "empty", "shrink", "reduce", "clear"]:
                if kw in title:
                    drawdown += 1
                    break

        if buildup > drawdown + 2:
            score = 3.0
            signals.append("GDELT: storage buildup trend (bearish)")
        elif drawdown > buildup + 2:
            score = 7.0
            signals.append("GDELT: storage drawdown trend (bullish)")
        elif buildup > drawdown:
            score = 4.0
        elif drawdown > buildup:
            score = 6.0
        else:
            score = 5.0

        return score, signals
