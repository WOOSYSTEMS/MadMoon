"""
MadEye Financial/Macro Collector
Tracks DXY, Fed decisions, treasury yields via FRED, futures curve contango/backwardation.
Scores financial signal 0-10.
"""

import logging
import csv
import io
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

from .base import BaseCollector

logger = logging.getLogger("madeye")

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
FRED_API_KEY = "DEMO_KEY"  # FRED allows limited access without key
ALPHA_VANTAGE_BASE = "https://www.alphavantage.co/query"

def _load_alphavantage_key():
    """Load Alpha Vantage API key from data file or environment."""
    import os
    key_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "alphavantage_key.txt")
    if os.path.exists(key_path):
        with open(key_path) as f:
            return f.read().strip()
    return os.environ.get("ALPHAVANTAGE_KEY", "")


class FinancialCollector(BaseCollector):
    name = "financial"
    category = "financial"
    cache_ttl = 1800  # 30 minutes

    def __init__(self, fred_key: str = None, alphavantage_key: str = None):
        super().__init__()
        self.fred_key = fred_key or FRED_API_KEY
        self.av_key = alphavantage_key or _load_alphavantage_key()

    async def collect(self) -> Dict:
        signals = []
        subscores = []

        # --- 1. DXY Dollar Index ---
        dxy_score, dxy_signals = await self._check_dxy()
        subscores.append(dxy_score)
        signals.extend(dxy_signals)

        # --- 2. Treasury Yields & Yield Curve ---
        yield_score, yield_signals = await self._check_yields()
        subscores.append(yield_score)
        signals.extend(yield_signals)

        # --- 3. Fed Funds Rate ---
        fed_score, fed_signals = await self._check_fed_rate()
        subscores.append(fed_score)
        signals.extend(fed_signals)

        # --- 4. Futures Curve Structure ---
        curve_score, curve_signals = await self._check_futures_curve()
        subscores.append(curve_score)
        signals.extend(curve_signals)

        # --- 5. CPI / Inflation ---
        cpi_score, cpi_signals = await self._check_cpi()
        subscores.append(cpi_score)
        signals.extend(cpi_signals)

        # --- 6. 10Y-2Y Yield Curve Spread (recession indicator) ---
        spread_score, spread_signals = await self._check_yield_curve_spread()
        subscores.append(spread_score)
        signals.extend(spread_signals)

        # Weighted: DXY 28%, Yields 15%, Fed 12%, Curve 25%, CPI 10%, Yield spread 10%
        weights = [0.28, 0.15, 0.12, 0.25, 0.10, 0.10]
        composite = sum(s * w for s, w in zip(subscores, weights)) / sum(weights)

        if composite >= 6.5:
            direction = "BULLISH"
        elif composite <= 3.5:
            direction = "BEARISH"
        else:
            direction = "NEUTRAL"

        confidence = min(1.0, len([s for s in subscores if s != 5.0]) / len(subscores))

        return self.make_result(
            score=composite,
            direction=direction,
            signals=signals,
            details={
                "dxy_score": round(dxy_score, 2),
                "yield_score": round(yield_score, 2),
                "fed_score": round(fed_score, 2),
                "curve_score": round(curve_score, 2),
                "cpi_score": round(cpi_score, 2),
                "yield_curve_spread_score": round(spread_score, 2),
            },
            confidence=confidence,
        )

    async def _fetch_fred(self, series_id: str, limit: int = 30) -> Optional[List]:
        """Fetch FRED series data."""
        params = {
            "series_id": series_id,
            "api_key": self.fred_key,
            "file_type": "json",
            "sort_order": "desc",
            "limit": str(limit),
        }
        data = await self.fetch_json(
            FRED_BASE, params=params, cache_key=f"fred_{series_id}"
        )
        if data and "observations" in data:
            return data["observations"]
        return None

    async def _check_dxy(self) -> tuple:
        """Check US Dollar Index via Yahoo Finance (DX-Y.NYB), Alpha Vantage, and FRED fallback."""
        signals = []
        score = 5.0

        # Primary: Yahoo Finance DXY
        values = []
        try:
            import yfinance as yf
            dxy = yf.Ticker("DX-Y.NYB")
            hist = dxy.history(period="1mo")
            if not hist.empty:
                closes = hist["Close"].dropna().tolist()
                if closes:
                    values = closes
        except Exception as e:
            logger.warning(f"Yahoo DXY fetch error: {e}")

        # Fallback: Alpha Vantage forex
        if not values and self.av_key:
            av_data = await self.fetch_json(
                ALPHA_VANTAGE_BASE,
                params={
                    "function": "REAL_GDP",
                    "interval": "quarterly",
                    "apikey": self.av_key,
                },
                cache_key="av_gdp",
            )
            if av_data and "data" in av_data:
                signals.append(f"Alpha Vantage GDP data available ({len(av_data['data'])} entries)")

        # Fallback: FRED trade-weighted dollar
        if not values:
            obs = await self._fetch_fred("DTWEXBGS", limit=30)
            if obs:
                for o in obs:
                    v = o.get("value", ".")
                    if v != ".":
                        values.append(float(v))
                    if len(values) >= 20:
                        break
                # FRED is in reverse chronological order
                values = list(reversed(values))

        if len(values) < 2:
            signals.append("DXY: insufficient data from all sources")
            return score, signals

        try:
            current = values[-1]
            prev_week = values[max(0, len(values) - 6)]
            prev_month = values[0]

            # Week-over-week change
            wow_change = ((current - prev_week) / prev_week) * 100
            # Month change
            mom_change = ((current - prev_month) / prev_month) * 100

            signals.append(f"DXY index: {current:.2f} (WoW: {wow_change:+.2f}%, MoM: {mom_change:+.2f}%)")

            # DXY rising = bearish for oil (inverse correlation)
            if mom_change > 3:
                score = 1.5
                signals.append("DXY surging -- strong bearish for oil")
            elif mom_change > 1.5:
                score = 3.0
                signals.append("DXY rising -- bearish for oil")
            elif wow_change > 1:
                score = 3.5
                signals.append("DXY short-term strength")
            elif mom_change < -3:
                score = 8.5
                signals.append("DXY falling sharply -- bullish for oil")
            elif mom_change < -1.5:
                score = 7.0
                signals.append("DXY weakening -- bullish for oil")
            elif wow_change < -1:
                score = 6.5
                signals.append("DXY short-term weakness")
            else:
                score = 5.0

        except (ValueError, TypeError, IndexError) as e:
            signals.append(f"DXY parse error: {str(e)[:50]}")

        return score, signals

    async def _check_yields(self) -> tuple:
        """Check Treasury yields and yield curve shape."""
        signals = []
        score = 5.0

        # 10Y yield
        obs_10y = await self._fetch_fred("DGS10", limit=10)
        obs_2y = await self._fetch_fred("DGS2", limit=10)
        # 10Y-2Y spread
        obs_spread = await self._fetch_fred("T10Y2Y", limit=10)

        latest_10y = None
        latest_2y = None
        latest_spread = None

        if obs_10y:
            for o in obs_10y:
                v = o.get("value", ".")
                if v != ".":
                    latest_10y = float(v)
                    break

        if obs_2y:
            for o in obs_2y:
                v = o.get("value", ".")
                if v != ".":
                    latest_2y = float(v)
                    break

        if obs_spread:
            for o in obs_spread:
                v = o.get("value", ".")
                if v != ".":
                    latest_spread = float(v)
                    break

        if latest_10y:
            signals.append(f"10Y yield: {latest_10y:.2f}%")
        if latest_2y:
            signals.append(f"2Y yield: {latest_2y:.2f}%")

        if latest_spread is not None:
            signals.append(f"10Y-2Y spread: {latest_spread:.2f}%")

            # Inverted yield curve = recession signal = bearish for oil
            if latest_spread < -0.5:
                score = 2.0
                signals.append("Deeply inverted yield curve -- recession risk (bearish oil)")
            elif latest_spread < 0:
                score = 3.5
                signals.append("Yield curve inverted -- caution")
            elif latest_spread > 1.5:
                score = 7.0
                signals.append("Steep yield curve -- growth signal (bullish oil)")
            elif latest_spread > 0.5:
                score = 6.0
                signals.append("Normal yield curve")
            else:
                score = 4.5
                signals.append("Flat yield curve")
        else:
            signals.append("Yield curve data: unavailable")

        # High yields generally tighten conditions = bearish
        if latest_10y and latest_10y > 5.0:
            score = max(0, score - 1.0)
            signals.append(f"10Y above 5% -- tight conditions")
        elif latest_10y and latest_10y < 3.0:
            score = min(10, score + 0.5)
            signals.append(f"10Y below 3% -- accommodative")

        return score, signals

    async def _check_fed_rate(self) -> tuple:
        """Check Fed Funds rate and trend."""
        signals = []
        score = 5.0

        obs = await self._fetch_fred("DFF", limit=30)
        if not obs:
            signals.append("Fed funds rate: unavailable")
            return score, signals

        try:
            values = []
            for o in obs:
                v = o.get("value", ".")
                if v != ".":
                    values.append(float(v))
                if len(values) >= 20:
                    break

            if not values:
                return score, ["Fed funds: no valid data"]

            current_rate = values[0]
            signals.append(f"Fed funds rate: {current_rate:.2f}%")

            # Check for recent changes
            if len(values) >= 5:
                prev = values[4]
                change = current_rate - prev
                if change < -0.25:
                    score = 7.5
                    signals.append(f"Rate cut detected ({change:+.2f}%) -- bullish oil")
                elif change > 0.25:
                    score = 3.0
                    signals.append(f"Rate hike detected ({change:+.2f}%) -- bearish oil")
                else:
                    # Stable rates -- level matters
                    if current_rate > 5.5:
                        score = 3.5
                        signals.append("Restrictive rate level")
                    elif current_rate < 3.0:
                        score = 6.5
                        signals.append("Accommodative rate level")
                    else:
                        score = 5.0

        except (ValueError, TypeError) as e:
            signals.append(f"Fed rate parse error: {str(e)[:50]}")

        return score, signals

    async def _check_futures_curve(self) -> tuple:
        """Check oil futures curve structure (contango vs backwardation)."""
        signals = []
        score = 5.0

        # Try Yahoo Finance for front-month vs deferred Brent
        # BZ=F (Brent front month) vs BZ=F deferred - we compare via price history
        try:
            import yfinance as yf
            brent = yf.Ticker("BZ=F")
            hist = brent.history(period="5d")
            if not hist.empty:
                latest_price = float(hist["Close"].iloc[-1])
                signals.append(f"Brent front month: ${latest_price:.2f}")

                # Check if we can get deferred month
                # Try CL (WTI) calendar spread as proxy
                wti = yf.Ticker("CL=F")
                wti_hist = wti.history(period="5d")
                if not wti_hist.empty:
                    wti_price = float(wti_hist["Close"].iloc[-1])
                    spread = latest_price - wti_price
                    signals.append(f"Brent-WTI spread: ${spread:.2f}")

                    # Wide Brent premium = tight Atlantic basin = bullish
                    if spread > 8:
                        score = 7.5
                        signals.append("Wide Brent premium -- tight supply")
                    elif spread > 4:
                        score = 6.0
                    elif spread < 0:
                        score = 3.5
                        signals.append("WTI premium over Brent -- unusual")
                    else:
                        score = 5.0
            else:
                signals.append("Futures curve: no price data")
        except Exception as e:
            logger.warning(f"Futures curve check error: {e}")
            signals.append("Futures curve: data unavailable")

            # Fallback: try API Ninjas
            try:
                data = await self.fetch_json(
                    "https://api.api-ninjas.com/v1/commodityforwardcurve",
                    cache_key="futures_curve",
                )
                if data:
                    structure = data.get("structure", "unknown")
                    if structure == "backwardation":
                        score = 7.0
                        signals.append("Futures in backwardation (bullish)")
                    elif structure == "contango":
                        score = 3.0
                        signals.append("Futures in contango (bearish)")
                    else:
                        score = 5.0
                        signals.append(f"Futures structure: {structure}")
            except Exception:
                pass

        return score, signals

    async def _check_cpi(self) -> tuple:
        """Check CPI data from FRED (CPIAUCSL) for inflation trend."""
        signals = []
        score = 5.0

        obs = await self._fetch_fred("CPIAUCSL", limit=15)
        if not obs:
            signals.append("CPI (FRED): unavailable")
            return score, signals

        try:
            values = []
            for o in obs:
                v = o.get("value", ".")
                if v != ".":
                    values.append(float(v))
                if len(values) >= 13:
                    break

            if len(values) < 2:
                signals.append("CPI: insufficient data")
                return score, signals

            current_cpi = values[0]
            prev_cpi = values[1]

            # Month-over-month change
            mom_change = ((current_cpi - prev_cpi) / prev_cpi) * 100

            # Year-over-year if enough data
            yoy_change = None
            if len(values) >= 13:
                year_ago_cpi = values[12]
                yoy_change = ((current_cpi - year_ago_cpi) / year_ago_cpi) * 100
                signals.append(f"CPI YoY: {yoy_change:.1f}% | MoM: {mom_change:.2f}%")
            else:
                signals.append(f"CPI MoM: {mom_change:.2f}%")

            # High inflation = tightening = bearish for oil demand
            # Moderate inflation = commodity support = bullish
            if yoy_change is not None:
                if yoy_change > 5:
                    score = 3.5
                    signals.append("CPI very high (>5%) -- aggressive tightening expected, bearish oil")
                elif yoy_change > 3.5:
                    score = 4.5
                    signals.append("CPI elevated -- inflation supports commodities but risks tightening")
                elif yoy_change > 2:
                    score = 6.0
                    signals.append("CPI moderate (2-3.5%) -- healthy inflation, bullish for commodities")
                elif yoy_change > 1:
                    score = 5.0
                    signals.append("CPI low (1-2%) -- disinflation, neutral")
                else:
                    score = 3.5
                    signals.append("CPI very low (<1%) -- deflation risk, bearish for oil")
            else:
                if mom_change > 0.5:
                    score = 4.0
                    signals.append("Hot CPI print -- tightening expectations")
                elif mom_change < -0.1:
                    score = 4.0
                    signals.append("CPI declining -- deflation pressure")
                else:
                    score = 5.0

        except (ValueError, TypeError) as e:
            signals.append(f"CPI parse error: {str(e)[:50]}")

        return score, signals

    async def _check_yield_curve_spread(self) -> tuple:
        """Check 10Y-2Y yield curve spread as recession indicator.
        Inverted curve = recession signal = bearish for oil demand.
        """
        signals = []
        score = 5.0

        obs = await self._fetch_fred("T10Y2Y", limit=30)
        if not obs:
            signals.append("Yield curve spread (T10Y2Y): unavailable")
            return score, signals

        try:
            values = []
            for o in obs:
                v = o.get("value", ".")
                if v != ".":
                    values.append(float(v))
                if len(values) >= 20:
                    break

            if not values:
                signals.append("Yield curve spread: no valid data")
                return score, signals

            current_spread = values[0]
            signals.append(f"10Y-2Y spread (T10Y2Y): {current_spread:.2f}%")

            if current_spread < -1.0:
                score = 1.5
                signals.append("Yield curve deeply inverted (<-1%) -- severe recession risk, very bearish oil")
            elif current_spread < -0.5:
                score = 2.5
                signals.append("Yield curve inverted -- recession risk elevated, bearish oil demand")
            elif current_spread < 0:
                score = 3.5
                signals.append("Yield curve slightly inverted -- caution on demand outlook")
            elif current_spread < 0.5:
                score = 4.5
                signals.append("Yield curve flat -- growth uncertainty")
            elif current_spread < 1.5:
                score = 6.0
                signals.append("Yield curve normal -- healthy growth signal, bullish oil demand")
            elif current_spread < 2.5:
                score = 7.0
                signals.append("Yield curve steep -- strong growth expectations, bullish")
            else:
                score = 7.5
                signals.append("Yield curve very steep -- boom expectations")

            # Trend
            if len(values) >= 5:
                prev_spread = values[4]
                change = current_spread - prev_spread
                if change > 0.3:
                    score = min(10, score + 1.0)
                    signals.append(f"Yield curve steepening ({change:+.2f}%) -- improving growth outlook")
                elif change < -0.3:
                    score = max(0, score - 1.0)
                    signals.append(f"Yield curve flattening ({change:+.2f}%) -- deteriorating outlook")

        except (ValueError, TypeError) as e:
            signals.append(f"Yield curve spread parse error: {str(e)[:50]}")

        return score, signals
