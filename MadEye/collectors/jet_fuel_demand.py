"""
MadEye Jet Fuel Demand Proxy Collector
Uses airline ETF (JETS) as proxy for aviation fuel demand.
Rising airline traffic = rising jet fuel demand = bullish oil.
Also monitors airline demand news.
"""

import logging
from typing import Dict, List, Optional

from .base import BaseCollector

logger = logging.getLogger("madeye")

YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=30d"
NEWSAPI_URL = "https://newsapi.org/v2/everything"
NEWSAPI_KEY = "9a1a0c6118414732871c9f72618818d9"


class JetFuelDemandCollector(BaseCollector):
    name = "jet_fuel_demand"
    category = "demand"
    cache_ttl = 1800  # 30 minutes

    async def _get_etf_data(self, ticker: str) -> Optional[Dict]:
        """Fetch ETF price/volume series from Yahoo Finance."""
        url = YAHOO_CHART.format(ticker=ticker)
        data = await self.fetch_json(url, cache_key=f"jet_{ticker}")
        if not data:
            return None
        try:
            result = data["chart"]["result"][0]
            closes = result["indicators"]["quote"][0]["close"]
            volumes = result["indicators"]["quote"][0]["volume"]

            valid_closes = [c for c in closes if c is not None]
            valid_volumes = [v for v in volumes if v is not None]

            if not valid_closes:
                return None

            return {
                "current": valid_closes[-1],
                "prev": valid_closes[-2] if len(valid_closes) >= 2 else valid_closes[-1],
                "avg_30d": sum(valid_closes) / len(valid_closes),
                "series": valid_closes,
                "volume_current": valid_volumes[-1] if valid_volumes else 0,
                "volume_avg": sum(valid_volumes) / len(valid_volumes) if valid_volumes else 0,
            }
        except (KeyError, IndexError, TypeError):
            return None

    async def _get_aviation_news(self) -> List[Dict]:
        """Fetch airline/jet fuel demand news."""
        params = {
            "q": '"airline demand" OR "jet fuel" OR "air travel recovery" OR "passenger traffic" OR "airline capacity"',
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": 10,
            "apiKey": NEWSAPI_KEY,
        }
        data = await self.fetch_json(NEWSAPI_URL, params=params,
                                     cache_key="aviation_news")
        if not data or data.get("status") != "ok":
            return []
        return data.get("articles", [])

    def _analyze_aviation_news(self, articles: List[Dict]) -> Dict:
        """Analyze aviation news for demand signals."""
        bullish = 0
        bearish = 0

        for article in articles:
            text = f"{article.get('title', '')} {article.get('description', '')}".lower()

            if any(w in text for w in ["record passengers", "travel recovery",
                                       "strong demand", "capacity increase",
                                       "bookings surge", "summer travel",
                                       "above 2019", "pre-pandemic levels",
                                       "fuel demand rise", "new routes"]):
                bullish += 1

            if any(w in text for w in ["demand slump", "travel decline",
                                       "capacity cut", "airline bankruptcy",
                                       "grounded", "passenger drop",
                                       "covid variant", "travel restrictions",
                                       "recession", "fuel hedging cut"]):
                bearish += 1

        return {
            "bullish": bullish,
            "bearish": bearish,
            "articles": len(articles),
        }

    async def collect(self) -> Dict:
        signals = []
        subscores = []
        confidence = 0.3
        details = {}

        # --- 1. JETS ETF ---
        jets_data = await self._get_etf_data("JETS")

        if jets_data:
            current = jets_data["current"]
            avg = jets_data["avg_30d"]
            series = jets_data["series"]

            signals.append(f"JETS ETF: ${current:.2f} (30d avg: ${avg:.2f})")
            details["jets_price"] = round(current, 2)
            details["jets_avg_30d"] = round(avg, 2)

            # Price relative to 30d average
            ratio = current / avg if avg > 0 else 1.0

            # 5-day momentum
            if len(series) >= 5:
                week_change = ((current - series[-5]) / series[-5] * 100) if series[-5] > 0 else 0
                signals.append(f"JETS 5-day change: {week_change:+.1f}%")
                details["jets_5d_change"] = round(week_change, 2)
            else:
                week_change = 0

            # 30-day momentum
            if len(series) >= 20:
                month_change = ((current - series[0]) / series[0] * 100) if series[0] > 0 else 0
                signals.append(f"JETS 30-day change: {month_change:+.1f}%")
                details["jets_30d_change"] = round(month_change, 2)
            else:
                month_change = 0

            # Score JETS
            if week_change > 5 and month_change > 10:
                jets_score = 8.5
                signals.append("JETS surging -- strong airline recovery, bullish jet fuel demand")
            elif week_change > 3 or month_change > 5:
                jets_score = 7.0
                signals.append("JETS rising -- improving air travel, bullish oil")
            elif week_change > 0 and ratio > 1.0:
                jets_score = 6.0
                signals.append("JETS above average -- steady aviation demand")
            elif week_change > -3:
                jets_score = 5.0
                signals.append("JETS stable -- normal aviation demand")
            elif week_change > -5:
                jets_score = 4.0
                signals.append("JETS declining -- weakening air travel demand")
            else:
                jets_score = 2.5
                signals.append("JETS selling off -- aviation demand collapsing, bearish oil")

            # Volume confirmation
            vol_ratio = jets_data["volume_current"] / jets_data["volume_avg"] if jets_data["volume_avg"] > 0 else 1.0
            if vol_ratio > 2.0:
                signals.append(f"JETS volume spike ({vol_ratio:.1f}x avg) -- strong institutional interest")

            subscores.append(("jets", jets_score))
            confidence = 0.6
        else:
            signals.append("JETS ETF data unavailable")

        # --- 2. Aviation news ---
        articles = await self._get_aviation_news()
        if articles:
            analysis = self._analyze_aviation_news(articles)
            signals.append(f"Aviation news: {analysis['articles']} articles ({analysis['bullish']} bullish, {analysis['bearish']} bearish)")
            details["news"] = analysis

            b = analysis["bullish"]
            br = analysis["bearish"]

            if b > br and b >= 2:
                news_score = 7.5
                signals.append("Aviation news sentiment: strong demand recovery")
            elif b > br:
                news_score = 6.0
            elif br > b and br >= 2:
                news_score = 3.0
                signals.append("Aviation news sentiment: demand weakness")
            elif br > b:
                news_score = 4.5
            else:
                news_score = 5.0

            subscores.append(("news", news_score))
        else:
            signals.append("No aviation demand news available")

        # Composite
        if subscores:
            weights = {"jets": 0.55, "news": 0.45}
            total_weight = sum(weights.get(n, 0.5) for n, _ in subscores)
            composite = sum(weights.get(n, 0.5) * s for n, s in subscores) / total_weight
        else:
            composite = 5.0

        details["subscores"] = {n: round(s, 2) for n, s in subscores}

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
