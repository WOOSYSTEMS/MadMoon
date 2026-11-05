"""
MadEye Dark Fleet / Shadow Fleet Tracker
Monitors sanctioned tanker activity via news signals.
Rising dark fleet = sanctions leaking = bearish (more supply reaching market).
Dark fleet seizures/crackdowns = tighter enforcement = bullish.
"""

import logging
import re
from typing import Dict, List

from .base import BaseCollector

logger = logging.getLogger("madeye")

NEWSAPI_URL = "https://newsapi.org/v2/everything"
NEWSAPI_KEY = "9a1a0c6118414732871c9f72618818d9"


class DarkFleetCollector(BaseCollector):
    name = "dark_fleet"
    category = "supply"
    cache_ttl = 3600  # 1 hour

    async def _fetch_dark_fleet_news(self) -> List[Dict]:
        """Fetch dark fleet / shadow fleet news."""
        params = {
            "q": '"dark fleet" OR "shadow fleet" OR "AIS off tanker" OR "sanctions tanker" OR "illicit oil shipment" OR "sanctions evasion oil"',
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": 20,
            "apiKey": NEWSAPI_KEY,
        }
        data = await self.fetch_json(NEWSAPI_URL, params=params,
                                     cache_key="dark_fleet_news")
        if not data or data.get("status") != "ok":
            return []
        return data.get("articles", [])

    def _analyze_articles(self, articles: List[Dict]) -> Dict:
        """Analyze dark fleet articles for supply/enforcement signals."""
        leaking_count = 0       # Sanctions leaking = bearish (more supply)
        enforcement_count = 0   # Enforcement tightening = bullish (less supply)
        volume_mentions = []
        countries = {"russia": 0, "iran": 0, "venezuela": 0, "north_korea": 0}

        for article in articles:
            text = f"{article.get('title', '')} {article.get('description', '')}".lower()

            # Sanctions leaking signals (more oil getting through = bearish)
            if any(w in text for w in ["growing fleet", "fleet expands", "more tankers",
                                       "record shipments", "sanctions evasion",
                                       "bypass sanctions", "ship-to-ship transfer",
                                       "ais dark", "ais off", "ghost tanker",
                                       "sanctions workaround", "illicit oil"]):
                leaking_count += 1

            # Enforcement signals (less oil getting through = bullish)
            if any(w in text for w in ["seizure", "seized", "detained", "impounded",
                                       "sanctions enforcement", "crackdown", "blacklist",
                                       "insurance withdrawn", "port ban", "arrested",
                                       "tighter sanctions", "new sanctions"]):
                enforcement_count += 1

            # Country tracking
            if "russia" in text or "russian" in text:
                countries["russia"] += 1
            if "iran" in text or "iranian" in text:
                countries["iran"] += 1
            if "venezuela" in text or "venezuelan" in text:
                countries["venezuela"] += 1

            # Volume mentions
            bpd_matches = re.findall(r'(\d+(?:\.\d+)?)\s*(?:million)?\s*(?:barrels?\s*per\s*day|bpd|b/d|mb/d)', text)
            for m in bpd_matches:
                volume_mentions.append(float(m))

        return {
            "leaking_count": leaking_count,
            "enforcement_count": enforcement_count,
            "countries": countries,
            "volume_mentions": volume_mentions,
            "total_articles": len(articles),
        }

    async def collect(self) -> Dict:
        signals = []
        score = 5.0
        confidence = 0.3

        articles = await self._fetch_dark_fleet_news()

        if not articles:
            signals.append("No dark fleet news available")
            return self.make_result(
                score=5.0, direction="NEUTRAL",
                signals=signals, confidence=0.1,
            )

        analysis = self._analyze_articles(articles)
        details = analysis

        signals.append(f"Dark fleet news: {analysis['total_articles']} articles")
        signals.append(f"Sanctions leaking signals: {analysis['leaking_count']}")
        signals.append(f"Enforcement signals: {analysis['enforcement_count']}")

        # Country breakdown
        active_countries = {k: v for k, v in analysis["countries"].items() if v > 0}
        if active_countries:
            country_str = ", ".join(f"{k}: {v}" for k, v in active_countries.items())
            signals.append(f"Countries mentioned: {country_str}")

        # Volume intelligence
        if analysis["volume_mentions"]:
            avg_vol = sum(analysis["volume_mentions"]) / len(analysis["volume_mentions"])
            signals.append(f"Estimated dark fleet volume: ~{avg_vol:.1f} mb/d")

        # Scoring logic:
        # Net enforcement > leaking = supply getting tighter = bullish
        # Net leaking > enforcement = supply getting through = bearish
        leak = analysis["leaking_count"]
        enforce = analysis["enforcement_count"]

        if enforce > leak and enforce >= 3:
            score = 8.0
            signals.append("Strong enforcement signals -- sanctions working, bullish oil")
        elif enforce > leak and enforce >= 1:
            score = 7.0
            signals.append("Enforcement outpacing leaks -- mildly bullish")
        elif leak > enforce and leak >= 3:
            score = 2.5
            signals.append("Significant sanctions evasion -- extra supply bearish for oil")
        elif leak > enforce and leak >= 1:
            score = 3.5
            signals.append("Some sanctions leakage -- mildly bearish")
        elif leak == 0 and enforce == 0:
            # Activity level matters too
            if analysis["total_articles"] > 5:
                score = 5.5
                signals.append("High dark fleet media attention -- market watching sanctions closely")
            else:
                score = 5.0
                signals.append("Dark fleet: quiet period, neutral")
        else:
            score = 5.0
            signals.append("Dark fleet: mixed signals")

        confidence = min(0.7, 0.3 + analysis["total_articles"] * 0.03)

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
