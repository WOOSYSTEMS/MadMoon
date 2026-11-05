"""
MadEye Natural Gas Substitution Signal Collector
Tracks gas-to-oil switching threshold for power generation.
When gas > $7/MMBtu, power plants switch to oil = bullish oil demand.
When gas < $3, no substitution pressure = neutral.
Also tracks European gas (TTF) via news.
"""

import logging
import re
from typing import Dict, List, Optional

from .base import BaseCollector

logger = logging.getLogger("madeye")

YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=30d"
NEWSAPI_URL = "https://newsapi.org/v2/everything"
NEWSAPI_KEY = "9a1a0c6118414732871c9f72618818d9"


class NaturalGasSubCollector(BaseCollector):
    name = "natural_gas_sub"
    category = "demand"
    cache_ttl = 1800  # 30 minutes

    async def _get_price_series(self, ticker: str) -> Optional[Dict]:
        """Fetch price series from Yahoo Finance."""
        url = YAHOO_CHART.format(ticker=ticker)
        data = await self.fetch_json(url, cache_key=f"ngsub_{ticker.replace('=', '_')}")
        if not data:
            return None
        try:
            result = data["chart"]["result"][0]
            closes = result["indicators"]["quote"][0]["close"]
            valid = [c for c in closes if c is not None]
            if not valid:
                return None
            return {
                "current": valid[-1],
                "prev": valid[-2] if len(valid) >= 2 else valid[-1],
                "avg_30d": sum(valid) / len(valid),
                "high_30d": max(valid),
                "low_30d": min(valid),
                "series": valid,
            }
        except (KeyError, IndexError, TypeError):
            return None

    async def _get_european_gas_news(self) -> Dict:
        """Fetch European gas / TTF / LNG news."""
        params = {
            "q": '"TTF gas" OR "European gas" OR "LNG price" OR "natural gas Europe" OR "gas-to-oil switching"',
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": 10,
            "apiKey": NEWSAPI_KEY,
        }
        data = await self.fetch_json(NEWSAPI_URL, params=params,
                                     cache_key="euro_gas_news")
        if not data or data.get("status") != "ok":
            return {"articles": []}
        return {"articles": data.get("articles", [])}

    def _analyze_euro_gas_news(self, articles: List[Dict]) -> Dict:
        """Analyze European gas news for price/switching signals."""
        bullish_oil = 0  # High gas = oil substitution = bullish oil
        bearish_oil = 0  # Low gas = no switching = neutral/bearish oil
        ttf_prices = []

        for article in articles:
            text = f"{article.get('title', '')} {article.get('description', '')}".lower()

            # TTF price extraction (EUR/MWh)
            matches = re.findall(r'(?:ttf|dutch\s+gas).*?(?:\u20ac|eur)?\s*(\d+(?:\.\d+)?)\s*/?\s*mwh', text)
            for m in matches:
                val = float(m)
                if 5 < val < 200:  # Sanity check
                    ttf_prices.append(val)

            if any(w in text for w in ["gas price surge", "gas crisis", "gas shortage",
                                       "switch to oil", "gas-to-oil", "oil substitution",
                                       "record gas", "gas spike"]):
                bullish_oil += 1

            if any(w in text for w in ["gas price fall", "gas glut", "mild winter",
                                       "storage full", "gas surplus", "cheap gas"]):
                bearish_oil += 1

        return {
            "bullish_oil": bullish_oil,
            "bearish_oil": bearish_oil,
            "ttf_prices": ttf_prices,
            "articles": len(articles),
        }

    async def collect(self) -> Dict:
        signals = []
        subscores = []
        confidence = 0.3
        details = {}

        # --- 1. Henry Hub Natural Gas (NG=F) ---
        ng_data = await self._get_price_series("NG=F")

        if ng_data:
            ng_price = ng_data["current"]
            ng_avg = ng_data["avg_30d"]
            signals.append(f"Henry Hub gas (NG=F): ${ng_price:.3f}/MMBtu (30d avg: ${ng_avg:.3f})")
            details["henry_hub"] = round(ng_price, 3)

            # Gas-to-oil switching thresholds
            # > $9: heavy switching to oil in power gen = very bullish oil
            # $7-9: switching begins = bullish oil
            # $3-7: normal range, some switching at margins
            # < $3: very cheap gas, no switching = neutral for oil

            if ng_price > 9:
                ng_score = 9.0
                signals.append("Gas price >$9/MMBtu -- heavy gas-to-oil switching, very bullish oil demand")
            elif ng_price > 7:
                ng_score = 7.5
                signals.append("Gas price $7-9 -- switching threshold reached, bullish oil demand")
            elif ng_price > 5:
                ng_score = 6.0
                signals.append("Gas price $5-7 -- marginal switching possible")
            elif ng_price > 3:
                ng_score = 5.0
                signals.append("Gas price $3-5 -- normal range, minimal oil substitution")
            elif ng_price > 2:
                ng_score = 4.5
                signals.append("Gas price $2-3 -- cheap gas, no switching to oil")
            else:
                ng_score = 4.0
                signals.append("Gas price <$2 -- very cheap gas, gas preferred over oil everywhere")

            # Gas price trend
            if len(ng_data["series"]) >= 5:
                recent = sum(ng_data["series"][-5:]) / 5
                older = sum(ng_data["series"][:5]) / 5
                trend_pct = ((recent - older) / older * 100) if older > 0 else 0

                if trend_pct > 20:
                    ng_score = min(10, ng_score + 1.0)
                    signals.append(f"Gas price surging ({trend_pct:+.0f}%) -- switching momentum building")
                elif trend_pct < -20:
                    ng_score = max(0, ng_score - 0.5)
                    signals.append(f"Gas price falling ({trend_pct:+.0f}%) -- less switching pressure")

            subscores.append(("henry_hub", ng_score))
            confidence = 0.7
        else:
            signals.append("Henry Hub gas price unavailable")

        # --- 2. European Gas (TTF) via news ---
        euro_news = await self._get_european_gas_news()
        euro_analysis = self._analyze_euro_gas_news(euro_news.get("articles", []))

        if euro_analysis["articles"] > 0:
            signals.append(f"European gas news: {euro_analysis['articles']} articles")

            if euro_analysis["ttf_prices"]:
                avg_ttf = sum(euro_analysis["ttf_prices"]) / len(euro_analysis["ttf_prices"])
                signals.append(f"TTF estimate: ~EUR{avg_ttf:.1f}/MWh")
                details["ttf_estimate"] = round(avg_ttf, 1)

                # Convert TTF to $/MMBtu equivalent (rough: 1 EUR/MWh ~ $0.35/MMBtu)
                ttf_mmbtu = avg_ttf * 0.35
                details["ttf_mmbtu_equiv"] = round(ttf_mmbtu, 2)

            b = euro_analysis["bullish_oil"]
            br = euro_analysis["bearish_oil"]

            if b > br:
                euro_score = 7.0
                signals.append(f"European gas signals: bullish for oil ({b} vs {br})")
            elif br > b:
                euro_score = 4.0
                signals.append(f"European gas signals: bearish for oil ({br} vs {b})")
            else:
                euro_score = 5.0
                signals.append("European gas: mixed signals")

            subscores.append(("european_gas", euro_score))
            details["euro_gas"] = euro_analysis
        else:
            signals.append("No European gas news available")

        # Composite
        if subscores:
            weights = {"henry_hub": 0.60, "european_gas": 0.40}
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
