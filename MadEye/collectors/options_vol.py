"""
MadEye Options Volatility Surface Collector
Tracks GVZ (gold vol), OVX (oil vol), and put/call ratio signals.
High vol + declining = bullish (fear subsiding).
Put/call ratio > 1 = bearish sentiment = contrarian bullish.
"""

import logging
from typing import Dict, List, Optional, Tuple

from .base import BaseCollector

logger = logging.getLogger("madeye")

YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=30d"
YAHOO_HEADERS = {"User-Agent": "Mozilla/5.0"}
NEWSAPI_URL = "https://newsapi.org/v2/everything"
NEWSAPI_KEY = "9a1a0c6118414732871c9f72618818d9"


class OptionsVolCollector(BaseCollector):
    name = "options_vol"
    category = "sentiment"
    cache_ttl = 1800  # 30 minutes

    async def _get_vol_index(self, ticker: str) -> Optional[Dict]:
        """Fetch volatility index data from Yahoo Finance."""
        url = YAHOO_CHART.format(ticker=ticker)
        data = await self.fetch_json(url, cache_key=f"vol_{ticker.replace('^', '')}")
        if not data:
            return None
        try:
            result = data["chart"]["result"][0]
            closes = result["indicators"]["quote"][0]["close"]
            # Filter None values
            valid_closes = [c for c in closes if c is not None]
            if not valid_closes:
                return None
            return {
                "current": valid_closes[-1],
                "prev": valid_closes[-2] if len(valid_closes) >= 2 else valid_closes[-1],
                "avg_30d": sum(valid_closes) / len(valid_closes),
                "high_30d": max(valid_closes),
                "low_30d": min(valid_closes),
                "series": valid_closes,
            }
        except (KeyError, IndexError, TypeError):
            return None

    async def _get_put_call_from_news(self) -> Dict:
        """Estimate put/call ratio from CME news via NewsAPI."""
        params = {
            "q": '"put call ratio" AND (oil OR gold OR silver OR crude)',
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": 10,
            "apiKey": NEWSAPI_KEY,
        }
        data = await self.fetch_json(NEWSAPI_URL, params=params, cache_key="put_call_news")
        if not data or data.get("status") != "ok":
            return {"available": False}

        articles = data.get("articles", [])
        import re
        ratios = []
        for article in articles:
            text = f"{article.get('title', '')} {article.get('description', '')}".lower()
            matches = re.findall(r'put[/-]call\s*(?:ratio)?\s*(?:of|at|:)?\s*(\d+\.?\d*)', text)
            for m in matches:
                val = float(m)
                if 0.1 < val < 5.0:  # Sanity check
                    ratios.append(val)

        if ratios:
            return {"available": True, "avg_ratio": sum(ratios) / len(ratios), "count": len(ratios)}
        return {"available": False}

    def _score_vol_index(self, name: str, data: Dict) -> Tuple[float, List[str]]:
        """Score a volatility index."""
        signals = []
        score = 5.0

        current = data["current"]
        prev = data["prev"]
        avg = data["avg_30d"]

        signals.append(f"{name}: {current:.2f} (30d avg: {avg:.2f})")

        # Relative to 30-day average
        ratio_to_avg = current / avg if avg > 0 else 1.0
        change = ((current - prev) / prev * 100) if prev > 0 else 0

        signals.append(f"{name} change: {change:+.1f}% vs yesterday")

        # Trend analysis: is vol declining from elevated levels?
        series = data["series"]
        if len(series) >= 5:
            recent_5 = series[-5:]
            older_5 = series[-10:-5] if len(series) >= 10 else series[:5]
            recent_avg = sum(recent_5) / len(recent_5)
            older_avg = sum(older_5) / len(older_5)
            vol_trend = "declining" if recent_avg < older_avg else "rising"
        else:
            vol_trend = "flat"

        # High vol + declining = bullish (fear subsiding)
        # Low vol + rising = potential volatility event incoming
        if ratio_to_avg > 1.3 and vol_trend == "declining":
            score = 7.5
            signals.append(f"{name} elevated but declining -- fear subsiding, bullish")
        elif ratio_to_avg > 1.3 and vol_trend == "rising":
            score = 3.0
            signals.append(f"{name} high and rising -- growing fear, bearish near-term")
        elif ratio_to_avg > 1.1:
            score = 4.5
            signals.append(f"{name} above average -- elevated uncertainty")
        elif ratio_to_avg < 0.8:
            score = 5.5
            signals.append(f"{name} low -- complacency, watch for volatility spike")
        else:
            score = 5.0
            signals.append(f"{name} in normal range")

        return score, signals

    async def collect(self) -> Dict:
        signals = []
        subscores = []
        confidence = 0.3

        # --- GVZ (Gold Volatility) ---
        gvz_data = await self._get_vol_index("%5EGVZ")
        if gvz_data:
            gvz_score, gvz_signals = self._score_vol_index("GVZ (Gold Vol)", gvz_data)
            subscores.append(("gold", gvz_score))
            signals.extend(gvz_signals)
            confidence = max(confidence, 0.6)
        else:
            signals.append("GVZ data unavailable")

        # --- OVX (Oil Volatility) ---
        ovx_data = await self._get_vol_index("%5EOVX")
        if ovx_data:
            ovx_score, ovx_signals = self._score_vol_index("OVX (Oil Vol)", ovx_data)
            subscores.append(("oil", ovx_score))
            signals.extend(ovx_signals)
            confidence = max(confidence, 0.6)
        else:
            signals.append("OVX data unavailable")

        # --- Put/Call Ratio ---
        pc_data = await self._get_put_call_from_news()
        if pc_data.get("available"):
            ratio = pc_data["avg_ratio"]
            signals.append(f"Put/call ratio (news-derived): {ratio:.2f}")

            if ratio > 1.5:
                pc_score = 7.5  # Extreme bearish sentiment = contrarian bullish
                signals.append("Put/call ratio very high (>1.5) -- extreme bearish sentiment, contrarian bullish")
            elif ratio > 1.0:
                pc_score = 6.5
                signals.append("Put/call ratio elevated (>1.0) -- bearish sentiment, contrarian bullish")
            elif ratio > 0.7:
                pc_score = 5.0
                signals.append("Put/call ratio normal range")
            else:
                pc_score = 3.5
                signals.append("Put/call ratio low (<0.7) -- excessive bullishness, contrarian bearish")

            subscores.append(("sentiment", pc_score))
            confidence = min(1.0, confidence + 0.1)
        else:
            signals.append("Put/call ratio data unavailable from news")

        # Composite
        if subscores:
            weights = {"gold": 0.35, "oil": 0.35, "sentiment": 0.30}
            total_weight = sum(weights.get(name, 0.33) for name, _ in subscores)
            composite = sum(weights.get(name, 0.33) * s for name, s in subscores) / total_weight
        else:
            composite = 5.0

        details = {
            "gvz": {"current": gvz_data["current"], "avg_30d": round(gvz_data["avg_30d"], 2)} if gvz_data else None,
            "ovx": {"current": ovx_data["current"], "avg_30d": round(ovx_data["avg_30d"], 2)} if ovx_data else None,
            "put_call": pc_data if pc_data.get("available") else None,
            "subscores": {name: round(s, 2) for name, s in subscores},
        }

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
