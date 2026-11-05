"""
MadEye Shipping Collector
Tanker rates, Hormuz/Suez traffic monitoring.
Scores shipping signal 0-10.
"""

import logging
from datetime import datetime, timezone
from typing import Dict

from .base import BaseCollector

logger = logging.getLogger("madeye")

HORMUZ_API = "https://hormuz.data-tracking.net/api/crossings"
STRAIT_WATCH = "https://jasperbernaers.com/strait-watch/api/data"
NEWSAPI_BASE = "https://newsapi.org/v2/everything"

def _load_newsapi_key():
    """Load NewsAPI key from data file or environment."""
    import os
    key_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "newsapi_key.txt")
    if os.path.exists(key_path):
        with open(key_path) as f:
            return f.read().strip()
    return os.environ.get("NEWSAPI_KEY", "")


class ShippingCollector(BaseCollector):
    name = "shipping"
    category = "shipping"
    cache_ttl = 1800  # 30 minutes

    def __init__(self, newsapi_key: str = None):
        super().__init__()
        self.newsapi_key = newsapi_key or _load_newsapi_key()

    async def collect(self) -> Dict:
        signals = []
        subscores = []

        # --- 1. Hormuz Traffic ---
        hormuz_score, hormuz_signals = await self._check_hormuz_detailed()
        subscores.append(hormuz_score)
        signals.extend(hormuz_signals)

        # --- 2. Suez / Red Sea ---
        suez_score, suez_signals = await self._check_suez()
        subscores.append(suez_score)
        signals.extend(suez_signals)

        # --- 3. Tanker Rates ---
        tanker_score, tanker_signals = await self._check_tanker_rates()
        subscores.append(tanker_score)
        signals.extend(tanker_signals)

        # --- 4. Floating Storage Mentions (NewsAPI) ---
        fs_score, fs_signals = await self._check_floating_storage_mentions()
        subscores.append(fs_score)
        signals.extend(fs_signals)

        # --- 5. Suez Canal Disruption (NewsAPI) ---
        suez_news_score, suez_news_signals = await self._check_suez_disruption_newsapi()
        subscores.append(suez_news_score)
        signals.extend(suez_news_signals)

        # Weighted: Hormuz 30%, Suez 20%, Tanker rates 25%, Floating storage 10%, Suez NewsAPI 15%
        weights = [0.30, 0.20, 0.25, 0.10, 0.15]
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
                "hormuz_score": round(hormuz_score, 2),
                "suez_score": round(suez_score, 2),
                "tanker_score": round(tanker_score, 2),
                "floating_storage_mentions_score": round(fs_score, 2),
                "suez_newsapi_score": round(suez_news_score, 2),
            },
            confidence=confidence,
        )

    async def _check_hormuz_detailed(self) -> tuple:
        """Detailed Strait of Hormuz monitoring."""
        signals = []
        score = 5.0

        # 24-hour and 7-day data
        data_24h = await self.fetch_json(
            HORMUZ_API, params={"period": "24h"}, cache_key="hormuz_24h"
        )
        data_7d = await self.fetch_json(
            HORMUZ_API, params={"period": "7d"}, cache_key="hormuz_7d"
        )

        if data_24h:
            crossings = data_24h if isinstance(data_24h, list) else data_24h.get("crossings", data_24h.get("data", []))
            count_24h = len(crossings) if isinstance(crossings, list) else 0

            if count_24h > 0:
                signals.append(f"Hormuz 24h crossings: {count_24h}")

                # Tanker type breakdown
                tanker_count = 0
                for c in crossings if isinstance(crossings, list) else []:
                    ship_type = str(c.get("type", c.get("ship_type", ""))).lower()
                    if "tanker" in ship_type or "crude" in ship_type:
                        tanker_count += 1

                if tanker_count > 0:
                    signals.append(f"  Oil tankers: {tanker_count}")

                # Normal ~40-60/day total, ~15-25 tankers
                if count_24h < 20:
                    score = 9.0
                    signals.append("Hormuz CRITICAL disruption")
                elif count_24h < 30:
                    score = 7.5
                    signals.append("Hormuz traffic significantly below normal")
                elif count_24h < 40:
                    score = 6.0
                    signals.append("Hormuz traffic below normal")
                elif count_24h > 60:
                    score = 3.5
                    signals.append("Hormuz traffic above normal")
                else:
                    score = 5.0
                    signals.append("Hormuz traffic normal range")
            else:
                signals.append("Hormuz 24h: no crossings data in response")
        else:
            signals.append("Hormuz API: unavailable")

        # Compare 7d trend
        if data_7d:
            crossings_7d = data_7d if isinstance(data_7d, list) else data_7d.get("crossings", data_7d.get("data", []))
            if isinstance(crossings_7d, list) and len(crossings_7d) > 0:
                # Group by day
                daily = {}
                for c in crossings_7d:
                    d = str(c.get("date", c.get("timestamp", "")))[:10]
                    if d:
                        daily[d] = daily.get(d, 0) + 1

                if len(daily) >= 2:
                    sorted_days = sorted(daily.keys())
                    first_half = [daily[d] for d in sorted_days[:len(sorted_days)//2]]
                    second_half = [daily[d] for d in sorted_days[len(sorted_days)//2:]]
                    if first_half and second_half:
                        avg_first = sum(first_half) / len(first_half)
                        avg_second = sum(second_half) / len(second_half)
                        if avg_first > 0:
                            trend = (avg_second - avg_first) / avg_first * 100
                            if trend < -20:
                                score = min(10, score + 1.5)
                                signals.append(f"Hormuz 7d DECLINING trend ({trend:.0f}%)")
                            elif trend > 20:
                                score = max(0, score - 1.0)
                                signals.append(f"Hormuz 7d improving trend ({trend:+.0f}%)")

        return score, signals

    async def _check_suez(self) -> tuple:
        """Check Suez Canal / Red Sea traffic."""
        signals = []
        score = 5.0

        # Check GDELT for Suez/Red Sea/Houthi disruption news
        url = "https://api.gdeltproject.org/api/v2/doc/doc"
        params = {
            "query": "Suez+canal+OR+Red+Sea+OR+Houthi+ship+OR+Bab+el-Mandeb+tanker",
            "mode": "artlist",
            "maxrecords": "30",
            "format": "json",
            "timespan": "48h",
        }

        data = await self.fetch_json(url, params=params, cache_key="gdelt_suez")
        if not data:
            signals.append("Suez/Red Sea monitoring: GDELT unavailable")
            return score, signals

        articles = data.get("articles", [])
        count = len(articles)

        # Check for disruption keywords
        disruption_count = 0
        for art in articles:
            title = (art.get("title", "") or "").lower()
            for kw in ["attack", "missile", "divert", "reroute", "shutdown",
                        "blockade", "disruption", "halt", "suspend"]:
                if kw in title:
                    disruption_count += 1
                    break

        if disruption_count >= 10:
            score = 8.5
            signals.append(f"Major Suez/Red Sea disruption coverage: {disruption_count} articles")
        elif disruption_count >= 5:
            score = 7.0
            signals.append(f"Suez/Red Sea disruption reports: {disruption_count} articles")
        elif disruption_count >= 2:
            score = 6.0
            signals.append(f"Minor Suez/Red Sea disruption reports: {disruption_count}")
        elif count > 0:
            score = 5.0
            signals.append(f"Suez/Red Sea: {count} articles, {disruption_count} disruptions")
        else:
            score = 4.0
            signals.append("Suez/Red Sea: calm, no disruption news")

        return score, signals

    async def _check_tanker_rates(self) -> tuple:
        """Check tanker/shipping headlines via NewsAPI and GDELT."""
        signals = []
        score = 5.0
        all_articles = []

        # Primary: NewsAPI for tanker/shipping/suez/hormuz headlines
        if self.newsapi_key:
            params = {
                "q": "tanker OR shipping OR suez OR hormuz",
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": "20",
                "apiKey": self.newsapi_key,
            }
            data = await self.fetch_json(
                NEWSAPI_BASE, params=params, cache_key="newsapi_shipping"
            )
            if data and data.get("status") == "ok":
                all_articles.extend(data.get("articles", []))
                signals.append(f"NewsAPI shipping: {len(data.get('articles', []))} articles")

        # Fallback/Supplement: GDELT
        url = "https://api.gdeltproject.org/api/v2/doc/doc"
        gdelt_params = {
            "query": "tanker+rate+OR+VLCC+rate+OR+freight+rate+crude+oil",
            "mode": "artlist",
            "maxrecords": "20",
            "format": "json",
            "timespan": "7d",
        }
        gdelt_data = await self.fetch_json(url, params=gdelt_params, cache_key="gdelt_tanker_rates")
        if gdelt_data:
            all_articles.extend(gdelt_data.get("articles", []))

        if not all_articles:
            signals.append("Tanker/shipping: no data available")
            return score, signals

        spike_keywords = 0
        drop_keywords = 0
        disruption_keywords = 0
        for art in all_articles:
            title = (art.get("title", "") or "").lower()
            desc = (art.get("description", "") or "").lower()
            text = title + " " + desc

            for kw in ["surge", "spike", "record", "soar", "highest", "jump"]:
                if kw in text:
                    spike_keywords += 1
                    break
            for kw in ["drop", "fall", "decline", "plunge", "low"]:
                if kw in text:
                    drop_keywords += 1
                    break
            for kw in ["attack", "missile", "divert", "reroute", "blockade", "halt", "seized"]:
                if kw in text:
                    disruption_keywords += 1
                    break

        # Disruptions are strongly bullish for oil
        if disruption_keywords >= 5:
            score = 8.5
            signals.append(f"Major shipping disruption coverage ({disruption_keywords} articles)")
        elif disruption_keywords >= 2:
            score = 7.0
            signals.append(f"Shipping disruption reports ({disruption_keywords})")
        elif spike_keywords > drop_keywords + 3:
            score = 8.0
            signals.append(f"Tanker rates surging ({spike_keywords} spike articles)")
        elif spike_keywords > drop_keywords:
            score = 6.5
            signals.append("Tanker rates rising trend")
        elif drop_keywords > spike_keywords + 3:
            score = 2.5
            signals.append(f"Tanker rates declining ({drop_keywords} drop articles)")
        elif drop_keywords > spike_keywords:
            score = 3.5
            signals.append("Tanker rates falling trend")
        else:
            score = 5.0
            signals.append("Tanker/shipping: stable/mixed signals")

        return score, signals

    async def _check_floating_storage_mentions(self) -> tuple:
        """Check NewsAPI for floating storage / tanker storage mentions."""
        signals = []
        score = 5.0

        if not self.newsapi_key:
            signals.append("Floating storage mentions: NewsAPI key not configured")
            return score, signals

        params = {
            "q": '"floating storage" OR "tanker storage" OR "oil storage tanker"',
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": "20",
            "apiKey": self.newsapi_key,
        }

        data = await self.fetch_json(
            NEWSAPI_BASE, params=params, cache_key="newsapi_floating_storage_shipping"
        )

        if not data or data.get("status") != "ok":
            signals.append("Floating storage mentions: NewsAPI unavailable")
            return score, signals

        articles = data.get("articles", [])
        count = len(articles)
        signals.append(f"Floating storage news mentions: {count}")

        if count == 0:
            score = 5.5  # No news = no storage buildup = slightly bullish
            signals.append("No floating storage news -- normal conditions")
        elif count > 10:
            # Lots of mentions = significant storage activity
            rising = sum(1 for a in articles if any(
                kw in (a.get("title", "") or "").lower()
                for kw in ["increase", "build", "surge", "record", "growing"]
            ))
            if rising > count // 2:
                score = 3.0
                signals.append(f"Rising floating storage coverage ({rising}/{count} bearish)")
            else:
                score = 6.5
                signals.append("Floating storage news active but mixed")
        elif count > 3:
            score = 4.5
            signals.append("Some floating storage mentions -- monitor")
        else:
            score = 5.0

        return score, signals

    async def _check_suez_disruption_newsapi(self) -> tuple:
        """Check NewsAPI specifically for Suez Canal disruptions."""
        signals = []
        score = 5.0

        if not self.newsapi_key:
            signals.append("Suez disruption (NewsAPI): key not configured")
            return score, signals

        params = {
            "q": '"Suez Canal" AND (disruption OR blockage OR attack OR closure OR reroute)',
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": "20",
            "apiKey": self.newsapi_key,
        }

        data = await self.fetch_json(
            NEWSAPI_BASE, params=params, cache_key="newsapi_suez_disruption"
        )

        if not data or data.get("status") != "ok":
            signals.append("Suez disruption NewsAPI: unavailable")
            return score, signals

        articles = data.get("articles", [])
        count = len(articles)

        if count == 0:
            score = 4.5  # No disruption news = slightly bearish (smooth flows)
            signals.append("No Suez Canal disruption news -- smooth transit")
        elif count >= 10:
            score = 8.5
            signals.append(f"MAJOR Suez Canal disruption coverage ({count} articles) -- very bullish oil")
        elif count >= 5:
            score = 7.0
            signals.append(f"Suez Canal disruption reports ({count} articles) -- bullish supply concern")
        elif count >= 2:
            score = 6.0
            signals.append(f"Minor Suez disruption mentions ({count})")
        else:
            score = 5.5
            signals.append(f"Isolated Suez disruption mention")

        return score, signals
