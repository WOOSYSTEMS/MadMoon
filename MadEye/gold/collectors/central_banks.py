"""
MadEye Gold -- Central Bank Gold Purchases Collector
Tracks central bank buying/selling of gold reserves.
Net buying = structural bullish. Pause/selling = short-term bearish.
Weight: 10% of total signal.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Tuple

from .base import BaseCollector

logger = logging.getLogger("madeye.gold")

# Hardcoded known 2026 central bank buying trends
# Source: World Gold Council, public reporting
CB_BUYING_2026 = {
    "trend": "record_buying",
    "description": "Central banks on track for 4th consecutive year of 1000+ tonnes net purchases",
    "top_buyers": {
        "PBOC": {"tonnes_ytd": 180, "trend": "accelerating", "note": "De-dollarization strategy"},
        "RBI": {"tonnes_ytd": 85, "trend": "steady", "note": "India reserves diversification"},
        "NBP": {"tonnes_ytd": 50, "trend": "steady", "note": "Poland NATO hedge"},
        "MAS": {"tonnes_ytd": 30, "trend": "new_buyer", "note": "Singapore diversifying"},
        "TCMB": {"tonnes_ytd": 65, "trend": "steady", "note": "Turkey rebuilding reserves"},
        "CBR": {"tonnes_ytd": 40, "trend": "reduced", "note": "Russia sanctions, domestic buying"},
    },
    "net_annual_estimate_tonnes": 1100,
    "structural_score": 8.0,  # Strong structural bullish
}

# Major central bank events that move gold
CB_EVENTS_KEYWORDS = [
    "central bank gold",
    "PBOC gold",
    "gold reserves",
    "central bank buying gold",
    "gold reserve increase",
    "de-dollarization",
    "reserve diversification",
    "gold repatriation",
    "BIS gold",
    "IMF gold sales",
]


class CentralBanksCollector(BaseCollector):
    name = "central_banks"
    category = "central_banks"
    cache_ttl = 1800  # 30 minutes

    def __init__(self, newsapi_key: str = None):
        super().__init__()
        self.newsapi_key = newsapi_key

    async def collect(self) -> Dict:
        signals = []
        subscores = []

        # --- 1. Structural CB buying trend (hardcoded 2026 data) ---
        struct_score, struct_signals = self._analyze_structural_trend()
        subscores.append(("structural", struct_score, 0.40))
        signals.extend(struct_signals)

        # --- 2. News sentiment on CB gold buying ---
        news_score, news_signals = await self._analyze_cb_news()
        subscores.append(("news", news_score, 0.35))
        signals.extend(news_signals)

        # --- 3. Monthly reporting cycle awareness ---
        cycle_score, cycle_signals = self._analyze_reporting_cycle()
        subscores.append(("cycle", cycle_score, 0.25))
        signals.extend(cycle_signals)

        total_weight = sum(w for _, _, w in subscores)
        composite = sum(s * w for _, s, w in subscores) / total_weight if total_weight > 0 else 5.0

        if composite >= 6.5:
            direction = "BULLISH"
        elif composite <= 3.5:
            direction = "BEARISH"
        else:
            direction = "NEUTRAL"

        confidence = min(1.0, len([s for _, s, _ in subscores if s != 5.0]) / max(1, len(subscores)))

        return self.make_result(
            score=composite,
            direction=direction,
            signals=signals,
            details={
                "structural_score": round(struct_score, 2),
                "news_score": round(news_score, 2),
                "cycle_score": round(cycle_score, 2),
                "net_annual_estimate_tonnes": CB_BUYING_2026["net_annual_estimate_tonnes"],
            },
            confidence=confidence,
        )

    def _analyze_structural_trend(self) -> Tuple[float, List[str]]:
        """Score based on hardcoded 2026 CB buying data."""
        signals = []
        score = CB_BUYING_2026["structural_score"]

        total_ytd = sum(b["tonnes_ytd"] for b in CB_BUYING_2026["top_buyers"].values())
        signals.append(f"CB net buying 2026: ~{CB_BUYING_2026['net_annual_estimate_tonnes']}t estimate")
        signals.append(f"Top buyers YTD: ~{total_ytd}t (PBOC, RBI, Poland, Turkey leading)")
        signals.append(CB_BUYING_2026["description"])

        # Accelerating buyers add bullish pressure
        accelerating = [k for k, v in CB_BUYING_2026["top_buyers"].items() if v["trend"] == "accelerating"]
        if accelerating:
            score = min(10, score + 0.5)
            signals.append(f"Accelerating buyers: {', '.join(accelerating)}")

        return score, signals

    async def _analyze_cb_news(self) -> Tuple[float, List[str]]:
        """Fetch recent central bank gold news from NewsAPI."""
        signals = []
        score = 5.0

        if not self.newsapi_key:
            return 5.0, ["CB news: No API key"]

        try:
            url = "https://newsapi.org/v2/everything"
            params = {
                "q": '"central bank" AND "gold" AND ("buying" OR "reserves" OR "purchases")',
                "apiKey": self.newsapi_key,
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": 20,
            }
            data = await self.fetch_json(url, params=params, cache_key="cb_gold_news")

            if data and "articles" in data:
                articles = data["articles"]
                total = len(articles)
                signals.append(f"CB gold news articles (recent): {total}")

                if total == 0:
                    return 5.0, signals

                # Sentiment analysis on headlines
                bullish_keywords = [
                    "buying", "purchases", "increase", "record", "added",
                    "accumulating", "reserves rise", "de-dollarization", "diversify"
                ]
                bearish_keywords = [
                    "selling", "sold", "decrease", "reduce", "liquidate",
                    "pause", "halt", "stopped buying"
                ]

                bullish_count = 0
                bearish_count = 0

                for article in articles:
                    title = (article.get("title") or "").lower()
                    desc = (article.get("description") or "").lower()
                    text = title + " " + desc

                    for kw in bullish_keywords:
                        if kw in text:
                            bullish_count += 1
                            break
                    for kw in bearish_keywords:
                        if kw in text:
                            bearish_count += 1
                            break

                signals.append(f"CB news sentiment: {bullish_count} bullish, {bearish_count} bearish")

                if bullish_count > bearish_count * 2:
                    score = 8.5
                    signals.append("Strong CB buying narrative in news -- bullish gold")
                elif bullish_count > bearish_count:
                    score = 7.0
                    signals.append("Net bullish CB narrative")
                elif bearish_count > bullish_count * 2:
                    score = 2.0
                    signals.append("CB selling/pausing narrative dominant -- bearish gold")
                elif bearish_count > bullish_count:
                    score = 3.5
                    signals.append("Net bearish CB narrative")
                else:
                    score = 5.0

                # Check for high-impact headlines
                for article in articles[:5]:
                    title = (article.get("title") or "").lower()
                    if "pboc" in title and "gold" in title:
                        if any(kw in title for kw in ["increase", "buy", "add", "record"]):
                            score = min(10, score + 1.0)
                            signals.append("PBOC gold buying headline -- major bullish signal")
                            break

        except Exception as e:
            logger.warning(f"CB news error: {e}")
            signals.append("CB news fetch failed")

        return score, signals

    def _analyze_reporting_cycle(self) -> Tuple[float, List[str]]:
        """Check where we are in the monthly CB reporting cycle."""
        signals = []
        score = 5.0
        now = datetime.now(timezone.utc)

        # PBOC reports around 7th of each month
        # WGC quarterly reports
        day = now.day
        month = now.month

        if 5 <= day <= 10:
            signals.append("PBOC monthly reserves report window -- watch for gold data")
            score = 6.0  # Slight bullish bias given 2026 trend

        # WGC quarterly reports (Jan, Apr, Jul, Oct)
        if month in [1, 4, 7, 10] and day <= 15:
            signals.append("World Gold Council quarterly report window")
            score = 6.0

        # Q4 traditionally strong CB buying (year-end positioning)
        if month in [10, 11, 12]:
            score = min(10, score + 0.5)
            signals.append("Q4 historically strong for CB gold purchases")

        return score, signals
