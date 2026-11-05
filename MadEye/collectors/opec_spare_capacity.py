"""
MadEye OPEC Spare Production Capacity Collector
Tracks spare capacity estimates from news.
Low spare (<2M bbl/d) = any disruption can't be offset = bullish premium.
High spare (>4M bbl/d) = buffer exists = bearish premium.
Current estimate: ~3.5M bbl/d (mostly Saudi + UAE).
"""

import logging
import re
from typing import Dict, List

from .base import BaseCollector

logger = logging.getLogger("madeye")

NEWSAPI_URL = "https://newsapi.org/v2/everything"
NEWSAPI_KEY = "9a1a0c6118414732871c9f72618818d9"

# Hardcoded baseline as of late 2026
BASELINE_SPARE = 3.5  # million bbl/d
BASELINE_NOTE = "Baseline: ~3.5M bbl/d (mostly Saudi Arabia + UAE)"


class OPECSpareCapacityCollector(BaseCollector):
    name = "opec_spare_capacity"
    category = "supply"
    cache_ttl = 7200  # 2 hours

    async def _fetch_spare_capacity_news(self) -> List[Dict]:
        """Fetch OPEC spare capacity news."""
        params = {
            "q": '"OPEC spare capacity" OR "Saudi spare capacity" OR "OPEC+ production capacity" OR "OPEC production ceiling"',
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": 15,
            "apiKey": NEWSAPI_KEY,
        }
        data = await self.fetch_json(NEWSAPI_URL, params=params,
                                     cache_key="opec_spare_news")
        if not data or data.get("status") != "ok":
            return []
        return data.get("articles", [])

    def _analyze_spare_capacity_news(self, articles: List[Dict]) -> Dict:
        """Analyze news for spare capacity estimates and signals."""
        capacity_estimates = []
        tightening_count = 0
        loosening_count = 0
        cut_mentions = 0
        increase_mentions = 0

        for article in articles:
            text = f"{article.get('title', '')} {article.get('description', '')}".lower()

            # Extract capacity numbers
            matches = re.findall(r'(\d+(?:\.\d+)?)\s*(?:million)?\s*(?:barrels?\s*per\s*day|bpd|mb/d|mbpd)\s*(?:of)?\s*spare', text)
            for m in matches:
                val = float(m)
                if 0.5 < val < 10:  # Sanity check
                    capacity_estimates.append(val)

            # Also try reverse pattern
            matches2 = re.findall(r'spare\s*(?:production\s*)?capacity\s*(?:of|at|around|~)?\s*(\d+(?:\.\d+)?)\s*(?:million)?\s*(?:bpd|mb/d|barrels)', text)
            for m in matches2:
                val = float(m)
                if 0.5 < val < 10:
                    capacity_estimates.append(val)

            # Tightening signals (less spare = bullish)
            if any(w in text for w in ["spare capacity shrink", "capacity dwindl",
                                       "little spare", "thin cushion",
                                       "capacity concerns", "no room",
                                       "fully utilized", "production limit"]):
                tightening_count += 1

            # Loosening signals (more spare = bearish)
            if any(w in text for w in ["ample spare", "plenty of capacity",
                                       "spare capacity increase", "buffer grows",
                                       "unused capacity", "room to increase"]):
                loosening_count += 1

            # Production cut/increase mentions
            if any(w in text for w in ["production cut", "output cut", "curb production"]):
                cut_mentions += 1
            if any(w in text for w in ["production increase", "output increase",
                                       "boost production", "unwind cuts"]):
                increase_mentions += 1

        return {
            "capacity_estimates": capacity_estimates,
            "tightening": tightening_count,
            "loosening": loosening_count,
            "cut_mentions": cut_mentions,
            "increase_mentions": increase_mentions,
            "articles": len(articles),
        }

    async def collect(self) -> Dict:
        signals = []
        score = 5.0
        confidence = 0.3

        articles = await self._fetch_spare_capacity_news()
        analysis = self._analyze_spare_capacity_news(articles)
        details = analysis

        # Use news-derived estimate or fall back to baseline
        if analysis["capacity_estimates"]:
            spare = sum(analysis["capacity_estimates"]) / len(analysis["capacity_estimates"])
            signals.append(f"OPEC spare capacity (news estimate): ~{spare:.1f}M bbl/d")
            confidence = 0.6
        else:
            spare = BASELINE_SPARE
            signals.append(f"OPEC spare capacity (baseline estimate): ~{spare:.1f}M bbl/d")
            signals.append(BASELINE_NOTE)
            confidence = 0.4

        details["estimated_spare_mbpd"] = round(spare, 2)

        # Score based on spare capacity level
        if spare < 1.5:
            score = 9.5
            signals.append("Spare capacity critically low (<1.5M) -- any disruption = price spike, very bullish")
        elif spare < 2.0:
            score = 8.0
            signals.append("Spare capacity low (<2M) -- thin buffer, bullish risk premium")
        elif spare < 3.0:
            score = 6.5
            signals.append("Spare capacity below average -- limited buffer, mildly bullish")
        elif spare < 4.0:
            score = 5.0
            signals.append("Spare capacity adequate (3-4M) -- reasonable buffer, neutral")
        elif spare < 5.0:
            score = 3.5
            signals.append("Spare capacity comfortable (4-5M) -- large buffer, bearish")
        else:
            score = 2.0
            signals.append("Spare capacity very high (>5M) -- excess buffer, bearish")

        # Adjust for trend signals from news
        if articles:
            signals.append(f"OPEC spare capacity news: {analysis['articles']} articles")

            net_tight = analysis["tightening"] - analysis["loosening"]
            if net_tight >= 2:
                score = min(10, score + 1.0)
                signals.append("News signals: spare capacity tightening")
            elif net_tight <= -2:
                score = max(0, score - 1.0)
                signals.append("News signals: spare capacity loosening")

            # Cut vs increase
            if analysis["cut_mentions"] > analysis["increase_mentions"]:
                signals.append(f"Production cuts mentioned more than increases ({analysis['cut_mentions']} vs {analysis['increase_mentions']})")
            elif analysis["increase_mentions"] > analysis["cut_mentions"]:
                signals.append(f"Production increases mentioned more ({analysis['increase_mentions']} vs {analysis['cut_mentions']})")

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
