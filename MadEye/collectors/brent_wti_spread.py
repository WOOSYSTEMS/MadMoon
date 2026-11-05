"""
MadEye Brent-WTI Spread Collector (Enhanced)
Tracks Brent-WTI spread level, trend, and rate of change.
Normal: $2-5. Wide >$8 = European tightness. Narrow <$1 = US export uncompetitive.
Also estimates WTI Midland spread from news.
"""

import logging
import re
from typing import Dict, List, Optional

from .base import BaseCollector

logger = logging.getLogger("madeye")

YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=30d"
NEWSAPI_URL = "https://newsapi.org/v2/everything"
NEWSAPI_KEY = "9a1a0c6118414732871c9f72618818d9"


class BrentWTISpreadCollector(BaseCollector):
    name = "brent_wti_spread"
    category = "spreads"
    cache_ttl = 1800  # 30 minutes

    async def _get_price_series(self, ticker: str) -> Optional[List[float]]:
        """Fetch price series from Yahoo Finance."""
        url = YAHOO_CHART.format(ticker=ticker)
        data = await self.fetch_json(url, cache_key=f"bws_{ticker.replace('=', '_')}")
        if not data:
            return None
        try:
            result = data["chart"]["result"][0]
            closes = result["indicators"]["quote"][0]["close"]
            return [c for c in closes if c is not None]
        except (KeyError, IndexError, TypeError):
            return None

    async def _get_midland_news(self) -> Dict:
        """Fetch WTI Midland spread signals from news."""
        params = {
            "q": '"WTI Midland" OR "Midland crude" OR "Permian crude premium"',
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": 5,
            "apiKey": NEWSAPI_KEY,
        }
        data = await self.fetch_json(NEWSAPI_URL, params=params,
                                     cache_key="midland_news")
        if not data or data.get("status") != "ok":
            return {"available": False}

        articles = data.get("articles", [])
        if not articles:
            return {"available": False}

        premium_mentions = []
        for article in articles:
            text = f"{article.get('title', '')} {article.get('description', '')}".lower()
            matches = re.findall(r'midland.*?\$(\d+\.?\d*)', text)
            for m in matches:
                val = float(m)
                if 0 < val < 20:
                    premium_mentions.append(val)

        return {
            "available": len(articles) > 0,
            "articles": len(articles),
            "premium_mentions": premium_mentions,
        }

    async def collect(self) -> Dict:
        signals = []
        score = 5.0
        confidence = 0.3

        brent_series = await self._get_price_series("BZ=F")
        wti_series = await self._get_price_series("CL=F")

        details = {}

        if not brent_series or not wti_series:
            signals.append("Brent or WTI price data unavailable")
            return self.make_result(
                score=5.0, direction="NEUTRAL",
                signals=signals, confidence=0.0,
            )

        # Align series length
        min_len = min(len(brent_series), len(wti_series))
        brent_series = brent_series[-min_len:]
        wti_series = wti_series[-min_len:]

        # Calculate spread series
        spreads = [b - w for b, w in zip(brent_series, wti_series)]

        current_spread = spreads[-1]
        current_brent = brent_series[-1]
        current_wti = wti_series[-1]

        signals.append(f"Brent (BZ=F): ${current_brent:.2f}")
        signals.append(f"WTI (CL=F): ${current_wti:.2f}")
        signals.append(f"Brent-WTI spread: ${current_spread:.2f}")

        details["brent"] = round(current_brent, 2)
        details["wti"] = round(current_wti, 2)
        details["spread"] = round(current_spread, 2)

        # 30-day spread statistics
        avg_spread = sum(spreads) / len(spreads)
        max_spread = max(spreads)
        min_spread = min(spreads)
        details["avg_30d_spread"] = round(avg_spread, 2)

        signals.append(f"30d spread range: ${min_spread:.2f} to ${max_spread:.2f} (avg ${avg_spread:.2f})")

        # Rate of change (5-day vs current)
        if len(spreads) >= 5:
            spread_5d_ago = spreads[-5]
            roc = current_spread - spread_5d_ago
            signals.append(f"Spread 5-day change: {roc:+.2f}")
            details["spread_roc_5d"] = round(roc, 2)

            # 10-day trend
            if len(spreads) >= 10:
                spread_10d_ago = spreads[-10]
                roc_10d = current_spread - spread_10d_ago
                details["spread_roc_10d"] = round(roc_10d, 2)

        # Scoring based on spread level
        if current_spread > 10:
            score = 8.5
            signals.append("Spread very wide (>$10) -- extreme European/Atlantic tightness, bullish Brent")
        elif current_spread > 8:
            score = 7.5
            signals.append("Spread wide (>$8) -- European tightness, Brent premium elevated")
        elif current_spread > 5:
            score = 6.5
            signals.append("Spread above normal (>$5) -- Atlantic basin tighter than US")
        elif current_spread > 2:
            score = 5.0
            signals.append("Spread in normal range ($2-5) -- balanced market")
        elif current_spread > 1:
            score = 4.0
            signals.append("Spread narrow ($1-2) -- US export economics weakening")
        elif current_spread > 0:
            score = 3.0
            signals.append("Spread very narrow (<$1) -- US exports uncompetitive, bearish")
        else:
            score = 2.0
            signals.append("Negative spread (WTI > Brent) -- very unusual, US oversupply")

        # Trend adjustment
        if len(spreads) >= 5:
            recent_avg = sum(spreads[-5:]) / 5
            older_avg = sum(spreads[:5]) / 5 if len(spreads) >= 10 else avg_spread

            if recent_avg > older_avg + 1.0:
                score = min(10, score + 0.5)
                signals.append("Spread widening trend -- Atlantic basin tightening")
            elif recent_avg < older_avg - 1.0:
                score = max(0, score - 0.5)
                signals.append("Spread narrowing trend -- convergence")

        confidence = 0.8

        # WTI Midland spread (from news)
        midland = await self._get_midland_news()
        if midland.get("available"):
            signals.append(f"WTI Midland news: {midland['articles']} articles")
            if midland.get("premium_mentions"):
                avg_mid = sum(midland["premium_mentions"]) / len(midland["premium_mentions"])
                signals.append(f"WTI Midland premium estimate: ${avg_mid:.2f}")
                details["midland_premium"] = round(avg_mid, 2)

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
