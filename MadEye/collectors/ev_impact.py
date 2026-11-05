"""
MadEye Electric Vehicle Adoption Impact on Oil Demand Collector
Tracks EV sales trends and their impact on oil demand.
Rising EV share = long-term bearish oil.
Short-term impact minimal (<2% of total oil demand displaced).
Score mostly neutral 4-5 unless major news.
"""

import logging
import re
from typing import Dict, List

from .base import BaseCollector

logger = logging.getLogger("madeye")

NEWSAPI_URL = "https://newsapi.org/v2/everything"
NEWSAPI_KEY = "9a1a0c6118414732871c9f72618818d9"


class EVImpactCollector(BaseCollector):
    name = "ev_impact"
    category = "demand"
    cache_ttl = 7200  # 2 hours (slow-moving signal)

    async def _fetch_ev_news(self) -> List[Dict]:
        """Fetch EV adoption and oil demand displacement news."""
        params = {
            "q": '"EV sales" OR "electric vehicle adoption" OR "Tesla deliveries" OR "EV market share" OR "oil demand EV" OR "electric car sales"',
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": 15,
            "apiKey": NEWSAPI_KEY,
        }
        data = await self.fetch_json(NEWSAPI_URL, params=params,
                                     cache_key="ev_news")
        if not data or data.get("status") != "ok":
            return []
        return data.get("articles", [])

    def _analyze_ev_news(self, articles: List[Dict]) -> Dict:
        """Analyze EV news for oil demand impact."""
        acceleration_count = 0   # EV adoption speeding up = more bearish for oil
        slowdown_count = 0       # EV adoption slowing = less impact on oil
        china_ev_count = 0       # China = biggest EV market
        displacement_mentions = []

        for article in articles:
            text = f"{article.get('title', '')} {article.get('description', '')}".lower()

            # EV acceleration (long-term bearish oil)
            if any(w in text for w in ["record ev sales", "ev sales surge",
                                       "ev market share grows", "million ev",
                                       "ev adoption accelerat", "peak oil demand",
                                       "ev tipping point", "all-electric",
                                       "combustion engine ban", "ev mandate"]):
                acceleration_count += 1

            # EV slowdown (less impact on oil)
            if any(w in text for w in ["ev sales slow", "ev demand falls",
                                       "ev bubble", "charging infrastructure",
                                       "range anxiety", "ev price too high",
                                       "hybrid comeback", "ev inventory pile",
                                       "ev subsidy cut", "ev cancell"]):
                slowdown_count += 1

            # China EV specifics
            if ("china" in text or "chinese" in text) and "ev" in text:
                china_ev_count += 1

            # Oil displacement numbers
            matches = re.findall(r'(\d+(?:\.\d+)?)\s*(?:million)?\s*(?:barrels?\s*per\s*day|bpd|mb/d)', text)
            for m in matches:
                displacement_mentions.append(float(m))

        return {
            "acceleration": acceleration_count,
            "slowdown": slowdown_count,
            "china_ev": china_ev_count,
            "displacement_bpd": displacement_mentions,
            "articles": len(articles),
        }

    async def collect(self) -> Dict:
        signals = []
        score = 5.0  # Default neutral -- EV impact is gradual
        confidence = 0.3

        articles = await self._fetch_ev_news()

        if not articles:
            signals.append("No EV adoption news available")
            signals.append("EV impact on oil: assumed minimal near-term (<2% of ~100mb/d demand)")
            return self.make_result(
                score=5.0, direction="NEUTRAL",
                signals=signals, confidence=0.2,
            )

        analysis = self._analyze_ev_news(articles)
        details = analysis

        signals.append(f"EV news: {analysis['articles']} articles")
        signals.append(f"EV acceleration signals: {analysis['acceleration']}")
        signals.append(f"EV slowdown signals: {analysis['slowdown']}")

        if analysis["china_ev"] > 0:
            signals.append(f"China EV mentions: {analysis['china_ev']} (China = ~60% of global EV sales)")

        if analysis["displacement_bpd"]:
            avg_disp = sum(analysis["displacement_bpd"]) / len(analysis["displacement_bpd"])
            signals.append(f"Estimated oil displacement: ~{avg_disp:.1f} mb/d")
            details["estimated_displacement_mbpd"] = round(avg_disp, 2)

        # Scoring: mostly stay 4-5 range unless strong signals
        accel = analysis["acceleration"]
        slow = analysis["slowdown"]
        net = accel - slow

        if net >= 4:
            score = 3.0
            signals.append("Strong EV acceleration -- meaningful long-term bearish for oil demand")
        elif net >= 2:
            score = 4.0
            signals.append("EV adoption growing -- gradual bearish pressure on oil")
        elif net >= 0:
            score = 4.5
            signals.append("EV adoption steady -- minimal near-term oil impact")
        elif net >= -2:
            score = 5.0
            signals.append("EV adoption slowing -- less threat to oil demand")
        else:
            score = 5.5
            signals.append("EV adoption stalling -- oil demand resilience")

        # Context: current EV impact is small
        signals.append("Context: EVs currently displace ~1.5-2 mb/d of ~100 mb/d global oil demand (<2%)")
        signals.append("Near-term oil price impact: minimal. Long-term: structural bearish force")

        confidence = min(0.5, 0.2 + analysis["articles"] * 0.02)

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
