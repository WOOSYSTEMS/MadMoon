"""
MadEye Geopolitical Collector
Monitors GDELT for Middle East/oil events, Hormuz ship traffic, conflict escalation.
Scores geopolitical risk 0-10.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List

from .base import BaseCollector

logger = logging.getLogger("madeye")

# GDELT query keywords for oil geopolitics
GDELT_QUERIES = [
    "oil+crude+Iran+OR+Hormuz+OR+OPEC+OR+sanctions",
    "oil+attack+OR+strike+OR+missile+OR+drone+Middle+East",
    "Strait+Hormuz+OR+Houthi+OR+Red+Sea+tanker",
    "OPEC+production+cut+OR+increase+OR+quota",
    "Libya+oil+OR+Nigeria+oil+OR+Iraq+oil+disruption",
]

# Key oil-producing regions to monitor
CONFLICT_REGIONS = [
    "Iran", "Iraq", "Saudi Arabia", "Yemen", "Libya",
    "Nigeria", "Venezuela", "Russia", "Ukraine", "Syria",
]

HORMUZ_API = "https://hormuz.data-tracking.net/api/crossings"

# NewsAPI configuration
NEWSAPI_BASE = "https://newsapi.org/v2/everything"

# Supply disruption keywords for bullish scoring
SUPPLY_DISRUPTION_KEYWORDS = [
    "sanctions", "embargo", "blockade", "shutdown", "attack", "missile",
    "strike", "explosion", "pipeline", "refinery fire", "outage", "disruption",
    "houthi", "iran", "hormuz", "escalation", "war", "conflict", "halt",
    "opec cut", "production cut", "libya shutdown", "nigeria", "force majeure",
]

def _load_newsapi_key():
    """Load NewsAPI key from data file or environment."""
    import os
    key_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "newsapi_key.txt")
    if os.path.exists(key_path):
        with open(key_path) as f:
            return f.read().strip()
    return os.environ.get("NEWSAPI_KEY", "")


class GeopoliticalCollector(BaseCollector):
    name = "geopolitical"
    category = "geopolitical"
    cache_ttl = 600  # 10 minutes

    def __init__(self, newsapi_key: str = None):
        super().__init__()
        self.newsapi_key = newsapi_key or _load_newsapi_key()

    async def collect(self) -> Dict:
        signals = []
        subscores = []

        # --- 1. NewsAPI Real-Time Headlines ---
        news_score, news_signals = await self._check_newsapi_headlines()
        subscores.append(news_score)
        signals.extend(news_signals)

        # --- 2. GDELT News Tone & Volume ---
        gdelt_score, gdelt_signals = await self._check_gdelt()
        subscores.append(gdelt_score)
        signals.extend(gdelt_signals)

        # --- 3. Hormuz Ship Traffic ---
        hormuz_score, hormuz_signals = await self._check_hormuz()
        subscores.append(hormuz_score)
        signals.extend(hormuz_signals)

        # --- 4. GDELT Conflict Events ---
        conflict_score, conflict_signals = await self._check_conflict_events()
        subscores.append(conflict_score)
        signals.extend(conflict_signals)

        # Weighted composite: NewsAPI 35%, GDELT tone 20%, Hormuz 25%, conflict 20%
        weights = [0.35, 0.20, 0.25, 0.20]
        composite = sum(s * w for s, w in zip(subscores, weights)) / sum(weights)

        # Determine direction
        if composite >= 6.5:
            direction = "BULLISH"
        elif composite <= 3.5:
            direction = "BEARISH"
        else:
            direction = "NEUTRAL"

        confidence = min(1.0, len([s for s in signals if s]) / 3.0)

        return self.make_result(
            score=composite,
            direction=direction,
            signals=signals,
            details={
                "gdelt_score": round(gdelt_score, 2),
                "hormuz_score": round(hormuz_score, 2),
                "conflict_score": round(conflict_score, 2),
                "subscores": [round(s, 2) for s in subscores],
            },
            confidence=confidence,
        )

    async def _check_newsapi_headlines(self) -> tuple:
        """Check NewsAPI for real-time oil/Middle East headlines."""
        signals = []
        score = 5.0

        if not self.newsapi_key:
            signals.append("NewsAPI: no API key configured")
            return score, signals

        params = {
            "q": "oil OR brent OR houthi OR iran OR hormuz",
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": "20",
            "apiKey": self.newsapi_key,
        }

        data = await self.fetch_json(
            NEWSAPI_BASE, params=params, cache_key="newsapi_geo_headlines"
        )

        if not data or data.get("status") != "ok":
            signals.append("NewsAPI: unavailable or error")
            return score, signals

        articles = data.get("articles", [])
        if not articles:
            signals.append("NewsAPI: no recent oil/geopolitical headlines")
            return 4.0, signals

        # Score based on headline sentiment -- negative supply disruption = bullish oil
        disruption_count = 0
        bearish_supply_count = 0
        for art in articles:
            title = (art.get("title", "") or "").lower()
            desc = (art.get("description", "") or "").lower()
            text = title + " " + desc

            # Check for supply disruption (bullish oil)
            for kw in SUPPLY_DISRUPTION_KEYWORDS:
                if kw in text:
                    disruption_count += 1
                    break

            # Check for bearish supply signals
            for kw in ["oversupply", "glut", "demand weak", "recession", "surplus",
                        "opec increase", "production increase", "demand destruction"]:
                if kw in text:
                    bearish_supply_count += 1
                    break

        total = len(articles)
        disruption_pct = disruption_count / total if total > 0 else 0
        bearish_pct = bearish_supply_count / total if total > 0 else 0

        signals.append(f"NewsAPI: {total} headlines, {disruption_count} disruption, {bearish_supply_count} bearish")

        if disruption_pct > 0.6:
            score = 9.0
            signals.append("HEAVY supply disruption coverage in headlines")
        elif disruption_pct > 0.4:
            score = 7.5
            signals.append("Significant supply disruption headlines")
        elif disruption_pct > 0.2:
            score = 6.5
            signals.append("Some supply disruption headlines")
        elif bearish_pct > 0.4:
            score = 2.5
            signals.append("Headlines dominated by oversupply/demand weakness")
        elif bearish_pct > 0.2:
            score = 3.5
            signals.append("Bearish supply sentiment in headlines")
        else:
            score = 5.0
            signals.append("Headlines neutral/mixed")

        return score, signals

    async def _check_gdelt(self) -> tuple:
        """Query GDELT for oil-related news tone."""
        signals = []
        score = 5.0  # neutral default

        query = GDELT_QUERIES[0]
        url = "https://api.gdeltproject.org/api/v2/doc/doc"
        params = {
            "query": query,
            "mode": "artlist",
            "maxrecords": "75",
            "format": "json",
            "sort": "DateDesc",
        }

        data = await self.fetch_json(url, params=params, cache_key="gdelt_artlist")
        if not data:
            signals.append("GDELT: API unavailable, using neutral")
            return score, signals

        articles = data.get("articles", [])
        if not articles:
            signals.append("GDELT: No recent oil-geopolitical articles")
            return 4.0, signals

        # Analyze tone: negative tone = geopolitical risk = bullish oil
        tones = []
        conflict_keywords = 0
        for art in articles:
            tone = art.get("tone", 0)
            if isinstance(tone, (int, float)):
                tones.append(tone)
            title = (art.get("title", "") or "").lower()
            for kw in ["attack", "strike", "missile", "war", "conflict", "bomb",
                        "sanctions", "escalation", "threat", "blockade", "shutdown"]:
                if kw in title:
                    conflict_keywords += 1
                    break

        if tones:
            avg_tone = sum(tones) / len(tones)
            # GDELT tone: negative = conflict/risk, positive = cooperation
            # Map: very negative (-10) = score 10, neutral (0) = score 5, positive (+5) = score 2
            score = max(0, min(10, 5.0 - avg_tone * 0.5))
            signals.append(f"GDELT avg tone: {avg_tone:.1f} ({len(articles)} articles)")
        else:
            signals.append("GDELT: No tone data in articles")

        # Boost score based on conflict keyword density
        if articles:
            conflict_pct = conflict_keywords / len(articles)
            if conflict_pct > 0.5:
                score = min(10, score + 2.0)
                signals.append(f"High conflict keyword density: {conflict_pct:.0%}")
            elif conflict_pct > 0.25:
                score = min(10, score + 1.0)
                signals.append(f"Moderate conflict keyword density: {conflict_pct:.0%}")

        return score, signals

    async def _check_hormuz(self) -> tuple:
        """Check Strait of Hormuz tanker traffic."""
        signals = []
        score = 5.0

        data = await self.fetch_json(
            HORMUZ_API,
            params={"period": "7d"},
            cache_key="hormuz_7d",
        )

        if not data:
            signals.append("Hormuz API: unavailable, using neutral")
            return score, signals

        # Parse crossing data
        crossings = data if isinstance(data, list) else data.get("crossings", data.get("data", []))
        if not crossings:
            signals.append("Hormuz: No crossing data available")
            return score, signals

        try:
            # Count daily crossings
            daily_counts = {}
            for c in crossings:
                date_str = str(c.get("date", c.get("timestamp", "")))[:10]
                if date_str:
                    daily_counts[date_str] = daily_counts.get(date_str, 0) + 1

            if daily_counts:
                avg_daily = sum(daily_counts.values()) / len(daily_counts)
                # Normal: ~40-60 tanker crossings/day
                # Disrupted: <30 = significant, <20 = critical
                if avg_daily < 20:
                    score = 9.5
                    signals.append(f"Hormuz CRITICAL: only {avg_daily:.0f} crossings/day")
                elif avg_daily < 30:
                    score = 8.0
                    signals.append(f"Hormuz DISRUPTED: {avg_daily:.0f} crossings/day (normal ~50)")
                elif avg_daily < 40:
                    score = 6.5
                    signals.append(f"Hormuz below normal: {avg_daily:.0f} crossings/day")
                elif avg_daily > 55:
                    score = 3.0
                    signals.append(f"Hormuz traffic healthy: {avg_daily:.0f} crossings/day")
                else:
                    score = 5.0
                    signals.append(f"Hormuz traffic normal: {avg_daily:.0f} crossings/day")

                # Check trend: declining = bearish for shipping = bullish for oil
                dates_sorted = sorted(daily_counts.keys())
                if len(dates_sorted) >= 3:
                    recent = sum(daily_counts[d] for d in dates_sorted[-2:]) / 2
                    earlier = sum(daily_counts[d] for d in dates_sorted[:2]) / 2
                    if earlier > 0:
                        change_pct = (recent - earlier) / earlier * 100
                        if change_pct < -15:
                            score = min(10, score + 1.5)
                            signals.append(f"Hormuz traffic declining {change_pct:.0f}%")
                        elif change_pct > 15:
                            score = max(0, score - 1.0)
                            signals.append(f"Hormuz traffic increasing {change_pct:.0f}%")
            else:
                signals.append("Hormuz: Could not parse daily counts")
        except Exception as e:
            logger.warning(f"Hormuz parse error: {e}")
            signals.append(f"Hormuz: Parse error ({str(e)[:50]})")

        return score, signals

    async def _check_conflict_events(self) -> tuple:
        """Check GDELT for conflict events in oil regions."""
        signals = []
        score = 5.0

        url = "https://api.gdeltproject.org/api/v2/doc/doc"
        params = {
            "query": "oil+attack+OR+strike+OR+missile+OR+war+Iran+OR+Iraq+OR+Saudi+OR+Yemen+OR+Libya",
            "mode": "artlist",
            "maxrecords": "50",
            "format": "json",
            "sort": "DateDesc",
            "timespan": "24h",
        }

        data = await self.fetch_json(url, params=params, cache_key="gdelt_conflict_24h")
        if not data:
            signals.append("GDELT conflict check: unavailable")
            return score, signals

        articles = data.get("articles", [])
        count = len(articles)

        # Score based on volume of conflict articles in 24h
        if count >= 40:
            score = 9.0
            signals.append(f"HIGH conflict volume: {count} articles in 24h")
        elif count >= 25:
            score = 7.5
            signals.append(f"Elevated conflict volume: {count} articles in 24h")
        elif count >= 15:
            score = 6.0
            signals.append(f"Moderate conflict volume: {count} articles in 24h")
        elif count >= 5:
            score = 5.0
            signals.append(f"Normal conflict volume: {count} articles in 24h")
        else:
            score = 3.0
            signals.append(f"Low conflict volume: {count} articles in 24h")

        # Check for critical escalation keywords
        critical_count = 0
        for art in articles:
            title = (art.get("title", "") or "").lower()
            for kw in ["nuclear", "invasion", "blockade", "hormuz closed",
                        "oil embargo", "war declared", "total shutdown"]:
                if kw in title:
                    critical_count += 1
                    break

        if critical_count >= 3:
            score = min(10, score + 2.0)
            signals.append(f"CRITICAL escalation keywords found: {critical_count}")
        elif critical_count >= 1:
            score = min(10, score + 1.0)
            signals.append(f"Escalation keywords found: {critical_count}")

        return score, signals
