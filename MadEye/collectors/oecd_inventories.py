"""
MadEye OECD Commercial Oil Inventories Collector
Tracks OECD commercial petroleum inventories via EIA data.
Below 5-year average = bullish, above = bearish.
Days of forward demand cover is the key metric.
"""

import logging
from typing import Dict, List, Optional

from .base import BaseCollector

logger = logging.getLogger("madeye")

EIA_API_KEY = "hFz7MGqCdj6hbhRTNpLRgGNK7pGbqbkC87JjWgtP"
NEWSAPI_URL = "https://newsapi.org/v2/everything"
NEWSAPI_KEY = "9a1a0c6118414732871c9f72618818d9"

# EIA STEO (Short-Term Energy Outlook) has OECD inventory data
EIA_STEO_URL = "https://api.eia.gov/v2/steo/data/"


class OECDInventoriesCollector(BaseCollector):
    name = "oecd_inventories"
    category = "supply"
    cache_ttl = 14400  # 4 hours (monthly data)

    async def _fetch_eia_oecd(self) -> Optional[List[Dict]]:
        """Fetch OECD commercial inventory data from EIA STEO."""
        params = {
            "api_key": EIA_API_KEY,
            "frequency": "monthly",
            "data[0]": "value",
            "facets[seriesId][]": "PAPR_OECD",  # OECD commercial petroleum stocks
            "sort[0][column]": "period",
            "sort[0][direction]": "desc",
            "offset": 0,
            "length": 72,  # 6 years for 5-year average comparison
        }
        data = await self.fetch_json(EIA_STEO_URL, params=params,
                                     cache_key="eia_oecd_inventory")
        if not data:
            return None
        try:
            return data.get("response", {}).get("data", [])
        except (KeyError, AttributeError):
            return None

    async def _fetch_oecd_news(self) -> Dict:
        """Fallback: get OECD inventory signals from news."""
        params = {
            "q": '"OECD oil inventories" OR "OECD petroleum stocks" OR "commercial oil inventories" OR "days of forward cover"',
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": 10,
            "apiKey": NEWSAPI_KEY,
        }
        data = await self.fetch_json(NEWSAPI_URL, params=params,
                                     cache_key="oecd_inv_news")
        if not data or data.get("status") != "ok":
            return {"articles": []}
        return {"articles": data.get("articles", [])}

    def _analyze_inventory_data(self, records: List[Dict]) -> Dict:
        """Analyze OECD inventory data against 5-year average."""
        if not records:
            return {"available": False}

        values = []
        for r in records:
            val = r.get("value")
            period = r.get("period", "")
            if val is not None:
                values.append({"value": float(val), "period": period})

        if len(values) < 13:
            return {"available": False}

        current = values[0]["value"]
        current_period = values[0]["period"]

        # 5-year average for same month
        current_month = current_period[-2:] if len(current_period) >= 7 else None
        five_year_vals = []
        if current_month:
            for v in values[12:]:  # Skip first year
                if v["period"].endswith(current_month):
                    five_year_vals.append(v["value"])
                    if len(five_year_vals) >= 5:
                        break

        five_year_avg = sum(five_year_vals) / len(five_year_vals) if five_year_vals else None

        # Year-over-year
        yoy_val = None
        for v in values[11:14]:
            yoy_val = v["value"]
            break

        # Recent trend (3 months)
        recent_3 = [v["value"] for v in values[:3]] if len(values) >= 3 else []

        return {
            "available": True,
            "current": current,
            "current_period": current_period,
            "five_year_avg": five_year_avg,
            "yoy_value": yoy_val,
            "recent_trend": recent_3,
        }

    def _analyze_news_fallback(self, articles: List[Dict]) -> tuple:
        """Analyze news for OECD inventory signals."""
        bullish = 0
        bearish = 0
        import re

        for article in articles:
            text = f"{article.get('title', '')} {article.get('description', '')}".lower()

            if any(w in text for w in ["below average", "below 5-year", "draw", "decline",
                                       "tighter", "deficit", "depleted", "falling stocks"]):
                bullish += 1
            if any(w in text for w in ["above average", "above 5-year", "build", "surplus",
                                       "glut", "overhang", "rising stocks", "excess"]):
                bearish += 1

            # Days of cover
            cover_matches = re.findall(r'(\d+(?:\.\d+)?)\s*days?\s*(?:of)?\s*(?:forward)?\s*(?:cover|supply)', text)
            for m in cover_matches:
                days = float(m)
                if days < 55:
                    bullish += 1
                elif days > 65:
                    bearish += 1

        return bullish, bearish

    async def collect(self) -> Dict:
        signals = []
        score = 5.0
        confidence = 0.3

        # Try EIA STEO data first
        records = await self._fetch_eia_oecd()
        inv_data = self._analyze_inventory_data(records or [])

        details = {}

        if inv_data.get("available"):
            current = inv_data["current"]
            five_yr = inv_data["five_year_avg"]

            signals.append(f"OECD commercial stocks: {current:.0f} million barrels ({inv_data['current_period']})")

            if five_yr:
                diff = current - five_yr
                diff_pct = (diff / five_yr) * 100

                signals.append(f"5-year average: {five_yr:.0f} million barrels")
                signals.append(f"Deviation: {diff:+.0f} mmbbl ({diff_pct:+.1f}%)")

                details["current_mmbbl"] = round(current, 1)
                details["five_year_avg"] = round(five_yr, 1)
                details["deviation_mmbbl"] = round(diff, 1)
                details["deviation_pct"] = round(diff_pct, 1)

                if diff_pct < -5:
                    score = 9.0
                    signals.append("OECD stocks well below 5-year average -- very bullish")
                elif diff_pct < -2:
                    score = 7.5
                    signals.append("OECD stocks below 5-year average -- bullish")
                elif diff_pct < 0:
                    score = 6.0
                    signals.append("OECD stocks slightly below average -- mildly bullish")
                elif diff_pct < 2:
                    score = 5.0
                    signals.append("OECD stocks near 5-year average -- neutral")
                elif diff_pct < 5:
                    score = 3.5
                    signals.append("OECD stocks above 5-year average -- bearish")
                else:
                    score = 2.0
                    signals.append("OECD stocks well above 5-year average -- very bearish")

                confidence = 0.8
            else:
                signals.append("5-year average not calculable from available data")

            # Trend
            trend = inv_data.get("recent_trend", [])
            if len(trend) >= 3:
                if trend[0] < trend[1] < trend[2]:
                    signals.append("OECD stocks trending down -- drawing, bullish")
                    score = min(10, score + 0.5)
                elif trend[0] > trend[1] > trend[2]:
                    signals.append("OECD stocks trending up -- building, bearish")
                    score = max(0, score - 0.5)

            # YoY comparison
            yoy = inv_data.get("yoy_value")
            if yoy:
                yoy_diff = current - yoy
                signals.append(f"Year-over-year change: {yoy_diff:+.0f} mmbbl")

        else:
            # Fallback to news
            signals.append("EIA OECD data unavailable, using news fallback")
            news = await self._fetch_oecd_news()
            articles = news.get("articles", [])

            if articles:
                bullish, bearish = self._analyze_news_fallback(articles)
                signals.append(f"OECD inventory news: {bullish} bullish vs {bearish} bearish signals")

                net = bullish - bearish
                if net >= 2:
                    score = 7.5
                elif net >= 1:
                    score = 6.0
                elif net <= -2:
                    score = 3.0
                elif net <= -1:
                    score = 4.0
                else:
                    score = 5.0

                confidence = 0.4
                details["news_bullish"] = bullish
                details["news_bearish"] = bearish
            else:
                signals.append("No OECD inventory data or news available")

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
