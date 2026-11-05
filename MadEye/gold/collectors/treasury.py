"""
MadEye Gold -- Treasury/Nominal Yields Collector
Nominal yields + yield curve shape.
Yields dropping = bullish gold. Curve inverting = recession fear = bullish medium-term.
Weight: 10% of total signal.
"""

import logging
from typing import Dict, List, Tuple

from .base import BaseCollector

logger = logging.getLogger("madeye.gold")


class TreasuryCollector(BaseCollector):
    name = "treasury"
    category = "treasury"
    cache_ttl = 900  # 15 minutes

    def __init__(self, fred_key: str = None):
        super().__init__()
        self.fred_key = fred_key or "DEMO_KEY"

    async def collect(self) -> Dict:
        signals = []
        subscores = []

        # --- 1. 10Y Yield from Yahoo ^TNX for intraday ---
        tnx_score, tnx_signals, tnx_details = await self._analyze_10y_yahoo()
        subscores.append(("tnx", tnx_score, 0.35))
        signals.extend(tnx_signals)

        # --- 2. FRED Nominal Yields (DGS10, DGS2, DGS30) ---
        fred_score, fred_signals = await self._analyze_fred_yields()
        subscores.append(("fred_yields", fred_score, 0.30))
        signals.extend(fred_signals)

        # --- 3. Yield Curve (T10Y2Y) ---
        curve_score, curve_signals = await self._analyze_yield_curve()
        subscores.append(("yield_curve", curve_score, 0.35))
        signals.extend(curve_signals)

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
                "tnx_score": round(tnx_score, 2),
                "fred_yields_score": round(fred_score, 2),
                "yield_curve_score": round(curve_score, 2),
                **tnx_details,
            },
            confidence=confidence,
        )

    async def _analyze_10y_yahoo(self) -> Tuple[float, List[str], Dict]:
        """Fetch 10Y Treasury yield from Yahoo Finance ^TNX."""
        signals = []
        details = {}
        score = 5.0

        try:
            import yfinance as yf
            ticker = yf.Ticker("^TNX")
            hist = ticker.history(period="1mo", interval="1h")

            if hist.empty:
                hist = ticker.history(period="3mo")

            if hist.empty:
                return 5.0, ["10Y Yield: No Yahoo data"], {}

            prices = hist["Close"].dropna().tolist()
            current = prices[-1]
            details["yield_10y"] = round(current, 3)
            signals.append(f"10Y Yield: {current:.3f}%")

            # Rate of change
            if len(prices) >= 6:
                roc = current - prices[-6]
                details["yield_10y_roc_5bar"] = round(roc, 4)

                if roc < -0.10:
                    score = 8.5
                    signals.append(f"10Y yield falling sharply ({roc:+.3f}pp) -- bullish gold")
                elif roc < -0.03:
                    score = 7.0
                    signals.append(f"10Y yield declining ({roc:+.3f}pp) -- bullish gold")
                elif roc > 0.10:
                    score = 2.0
                    signals.append(f"10Y yield surging ({roc:+.3f}pp) -- bearish gold")
                elif roc > 0.03:
                    score = 3.5
                    signals.append(f"10Y yield rising ({roc:+.3f}pp) -- bearish gold")
                else:
                    score = 5.0
                    signals.append(f"10Y yield stable ({roc:+.3f}pp)")

            # Absolute level context
            if current > 5.0:
                score = max(0, score - 0.5)
                signals.append("10Y yield very high -- strong alternative to gold")
            elif current < 3.5:
                score = min(10, score + 0.5)
                signals.append("10Y yield low -- gold more attractive")

        except Exception as e:
            logger.warning(f"Yahoo ^TNX error: {e}")
            signals.append("10Y Yahoo yield unavailable")

        return score, signals, details

    async def _analyze_fred_yields(self) -> Tuple[float, List[str]]:
        """Fetch DGS10, DGS2, DGS30 from FRED."""
        signals = []
        score = 5.0

        yields = {}
        for series_id, label in [("DGS10", "10Y"), ("DGS2", "2Y"), ("DGS30", "30Y")]:
            try:
                url = "https://api.stlouisfed.org/fred/series/observations"
                params = {
                    "series_id": series_id,
                    "api_key": self.fred_key,
                    "file_type": "json",
                    "sort_order": "desc",
                    "limit": 10,
                }
                data = await self.fetch_json(url, params=params, cache_key=f"fred_{series_id}")
                if data and "observations" in data:
                    obs = [o for o in data["observations"] if o["value"] != "."]
                    if len(obs) >= 2:
                        latest = float(obs[0]["value"])
                        prev = float(obs[1]["value"])
                        yields[label] = latest
                        change = latest - prev
                        if abs(change) > 0.03:
                            signals.append(f"FRED {label}: {latest:.2f}% ({change:+.3f}pp)")
            except Exception as e:
                logger.warning(f"FRED {series_id} error: {e}")

        # Score based on yield direction
        if "10Y" in yields and "2Y" in yields:
            # If yields broadly falling
            total_change = 0
            for label in yields:
                # We use latest vs previous already fetched
                pass

        # If we got 10Y data
        if "10Y" in yields:
            y10 = yields["10Y"]
            if y10 < 3.5:
                score = 7.0
                signals.append("Low nominal yields -- gold competitive")
            elif y10 > 5.0:
                score = 3.0
                signals.append("High nominal yields -- bonds compete with gold")

        return score, signals

    async def _analyze_yield_curve(self) -> Tuple[float, List[str]]:
        """Fetch T10Y2Y (10Y-2Y spread) from FRED."""
        signals = []
        score = 5.0

        try:
            url = "https://api.stlouisfed.org/fred/series/observations"
            params = {
                "series_id": "T10Y2Y",
                "api_key": self.fred_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 30,
            }
            data = await self.fetch_json(url, params=params, cache_key="fred_T10Y2Y")

            if data and "observations" in data:
                obs = [o for o in data["observations"] if o["value"] != "."]
                if obs:
                    spread = float(obs[0]["value"])
                    signals.append(f"Yield Curve (10Y-2Y): {spread:+.2f}%")

                    if spread < -0.5:
                        score = 8.0
                        signals.append("Yield curve deeply inverted -- recession risk HIGH -- bullish gold")
                    elif spread < 0:
                        score = 7.0
                        signals.append("Yield curve inverted -- recession signal -- bullish gold")
                    elif spread < 0.3:
                        score = 6.0
                        signals.append("Yield curve flat -- uncertainty -- mildly bullish gold")
                    elif spread < 1.0:
                        score = 5.0
                        signals.append("Yield curve normal")
                    else:
                        score = 4.0
                        signals.append("Yield curve steep -- healthy economy -- less gold demand")

                    # Trend: curve flattening = moving toward inversion = bullish gold
                    if len(obs) >= 10:
                        prev_spread = float(obs[9]["value"])
                        trend = spread - prev_spread
                        if trend < -0.1:
                            score = min(10, score + 1.0)
                            signals.append(f"Curve flattening ({trend:+.2f}pp) -- recession fear growing")
                        elif trend > 0.1:
                            score = max(0, score - 0.5)
                            signals.append(f"Curve steepening ({trend:+.2f}pp) -- optimism")

        except Exception as e:
            logger.warning(f"FRED T10Y2Y error: {e}")
            signals.append("Yield curve data unavailable")

        return score, signals
