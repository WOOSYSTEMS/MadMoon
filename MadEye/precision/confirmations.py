"""
MadEye Precision Mode -- Confirmation Checks
All must pass before a precision signal becomes actionable.

1. DXY direction (falling for gold/oil buy, rising for sell)
2. Technical (price vs 4h MA)
3. Momentum (4h rate of change > +/-0.2%)
4. Volatility (ATR > 0.3%)
5. RSI not extreme (not >80 for buy, not <20 for sell)
6. Time filter (day/hour rules per commodity)
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx
import numpy as np

logger = logging.getLogger("madeye.precision")

# Yahoo Finance base URL
YF_BASE = "https://query1.finance.yahoo.com/v8/finance/chart"
YF_HEADERS = {"User-Agent": "Mozilla/5.0 MadEye/2.0"}

# DXY symbol on Yahoo
DXY_SYMBOL = "DX-Y.NYB"


class ConfirmationChecker:
    """Runs all 6 confirmation checks for precision mode."""

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None
        self._price_cache = {}  # symbol -> (timestamp, data)
        self._cache_ttl = 120   # 2 minutes

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=15.0,
                headers=YF_HEADERS,
                follow_redirects=True,
            )
        return self._client

    async def _fetch_prices(self, symbol: str, interval: str = "1h",
                            range_str: str = "5d") -> Optional[dict]:
        """Fetch price data from Yahoo Finance with caching."""
        cache_key = f"{symbol}_{interval}_{range_str}"
        now = datetime.now(timezone.utc).timestamp()

        if cache_key in self._price_cache:
            cached_ts, cached_data = self._price_cache[cache_key]
            if now - cached_ts < self._cache_ttl:
                return cached_data

        try:
            client = await self._get_client()
            url = f"{YF_BASE}/{symbol}"
            params = {"interval": interval, "range": range_str}
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

            result = data.get("chart", {}).get("result", [])
            if not result:
                return None

            chart = result[0]
            timestamps = chart.get("timestamp", [])
            quotes = chart.get("indicators", {}).get("quote", [{}])[0]

            closes = quotes.get("close", [])
            highs = quotes.get("high", [])
            lows = quotes.get("low", [])

            # Filter out None values
            price_data = {
                "timestamps": timestamps,
                "closes": [c if c is not None else 0 for c in closes],
                "highs": [h if h is not None else 0 for h in highs],
                "lows": [l if l is not None else 0 for l in lows],
            }

            self._price_cache[cache_key] = (now, price_data)
            return price_data

        except Exception as e:
            logger.warning(f"Yahoo fetch failed for {symbol}: {e}")
            # Return stale cache if available
            if cache_key in self._price_cache:
                return self._price_cache[cache_key][1]
            return None

    # ---- CONFIRMATION 1: DXY Direction ----

    async def check_dxy(self, direction: str, commodity: str) -> bool:
        """DXY must be moving in the expected direction.
        For gold/silver/oil BUY: DXY should be falling (negative 1h ROC)
        For gold/silver/oil SELL: DXY should be rising (positive 1h ROC)
        """
        data = await self._fetch_prices(DXY_SYMBOL, interval="1h", range_str="2d")
        if not data or len(data["closes"]) < 4:
            logger.warning("DXY data insufficient -- skipping check (pass)")
            return True  # Fail-open if no data

        closes = [c for c in data["closes"] if c > 0]
        if len(closes) < 4:
            return True

        # 1-hour rate of change (last vs 1 hour ago)
        current = closes[-1]
        prev = closes[-2]
        roc = (current - prev) / prev * 100

        if direction == "BUY":
            # DXY should be falling for commodity buys
            ok = roc < 0.05  # Allow tiny positive (noise)
            logger.debug(f"DXY check BUY: ROC={roc:.3f}%, pass={ok}")
            return ok
        elif direction == "SELL":
            # DXY should be rising for commodity sells
            ok = roc > -0.05
            logger.debug(f"DXY check SELL: ROC={roc:.3f}%, pass={ok}")
            return ok

        return True

    # ---- CONFIRMATION 2: Technical (Price vs 4h MA) ----

    async def check_technical(self, direction: str, symbol: str) -> bool:
        """Price must be above 4-hour MA for BUY, below for SELL.
        We use a 20-period MA on 1h data (approximates 4h MA with smoothing).
        """
        data = await self._fetch_prices(symbol, interval="1h", range_str="5d")
        if not data or len(data["closes"]) < 20:
            return True  # Fail-open

        closes = [c for c in data["closes"] if c > 0]
        if len(closes) < 20:
            return True

        # 20-period MA on hourly = approximately 4-hour smoothed MA
        ma_20 = np.mean(closes[-20:])
        current = closes[-1]

        if direction == "BUY":
            ok = current > ma_20
            logger.debug(f"Tech check {symbol} BUY: price={current:.2f} MA20={ma_20:.2f} pass={ok}")
            return ok
        elif direction == "SELL":
            ok = current < ma_20
            logger.debug(f"Tech check {symbol} SELL: price={current:.2f} MA20={ma_20:.2f} pass={ok}")
            return ok

        return True

    # ---- CONFIRMATION 3: Momentum (4h ROC > +/-0.2%) ----

    async def check_momentum(self, direction: str, symbol: str) -> bool:
        """4-hour rate of change must be > +0.2% for BUY, < -0.2% for SELL."""
        data = await self._fetch_prices(symbol, interval="1h", range_str="2d")
        if not data or len(data["closes"]) < 5:
            return True

        closes = [c for c in data["closes"] if c > 0]
        if len(closes) < 5:
            return True

        # 4-hour ROC: current vs 4 hours ago
        current = closes[-1]
        four_h_ago = closes[-5] if len(closes) >= 5 else closes[0]
        roc = (current - four_h_ago) / four_h_ago * 100

        if direction == "BUY":
            ok = roc > 0.2
            logger.debug(f"Momentum {symbol} BUY: 4h ROC={roc:.3f}% pass={ok}")
            return ok
        elif direction == "SELL":
            ok = roc < -0.2
            logger.debug(f"Momentum {symbol} SELL: 4h ROC={roc:.3f}% pass={ok}")
            return ok

        return True

    # ---- CONFIRMATION 4: Volatility (ATR > 0.3%) ----

    async def check_volatility(self, symbol: str) -> bool:
        """ATR must be > 0.3% of price (market active enough to move)."""
        data = await self._fetch_prices(symbol, interval="1h", range_str="3d")
        if not data or len(data["closes"]) < 14:
            return True

        closes = data["closes"]
        highs = data["highs"]
        lows = data["lows"]

        # Calculate 14-period ATR on hourly
        true_ranges = []
        for i in range(1, min(15, len(closes))):
            if closes[i] > 0 and closes[i-1] > 0 and highs[i] > 0 and lows[i] > 0:
                tr = max(
                    highs[i] - lows[i],
                    abs(highs[i] - closes[i-1]),
                    abs(lows[i] - closes[i-1]),
                )
                true_ranges.append(tr)

        if not true_ranges:
            return True

        atr = np.mean(true_ranges)
        current_price = closes[-1] if closes[-1] > 0 else 1
        atr_pct = (atr / current_price) * 100

        ok = atr_pct > 0.3
        logger.debug(f"Volatility {symbol}: ATR={atr:.4f} ({atr_pct:.3f}%) pass={ok}")
        return ok

    # ---- CONFIRMATION 5: RSI Not Extreme ----

    async def check_rsi(self, direction: str, symbol: str) -> bool:
        """RSI must not be overbought (>80) for buys or oversold (<20) for sells."""
        data = await self._fetch_prices(symbol, interval="1h", range_str="5d")
        if not data or len(data["closes"]) < 15:
            return True

        closes = [c for c in data["closes"] if c > 0]
        if len(closes) < 15:
            return True

        # Calculate RSI(14) on hourly
        deltas = np.diff(closes[-15:])
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)

        avg_gain = np.mean(gains)
        avg_loss = np.mean(losses)

        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))

        if direction == "BUY":
            ok = rsi < 80
            logger.debug(f"RSI {symbol} BUY: RSI={rsi:.1f} pass={ok}")
            return ok
        elif direction == "SELL":
            ok = rsi > 20
            logger.debug(f"RSI {symbol} SELL: RSI={rsi:.1f} pass={ok}")
            return ok

        return True

    # ---- CONFIRMATION 6: Time Filter ----

    def check_time(self, commodity: str) -> bool:
        """Check if current time is within allowed trading hours.

        Oil: Mon-Thu 5AM-11AM PT (12:00-18:00 UTC)
        Gold/Silver: London/NY overlap 3AM-8AM ET (08:00-13:00 UTC)
        NEVER: Friday after 12PM PT (19:00 UTC)
        NEVER: Midnight PT hour (07:00 UTC)
        NEVER: Weekends
        """
        now = datetime.now(timezone.utc)
        utc_hour = now.hour
        weekday = now.weekday()  # 0=Mon, 6=Sun

        # Universal blocks
        if weekday >= 5:
            logger.debug("Time check: Weekend -- BLOCKED")
            return False

        if weekday == 4 and utc_hour >= 19:
            logger.debug("Time check: Friday after 12PM PT -- BLOCKED")
            return False

        if utc_hour == 7:
            logger.debug("Time check: Midnight PT hour -- BLOCKED")
            return False

        if commodity == "oil":
            # Mon-Thu 5AM-11AM PT = 12:00-18:00 UTC
            ok = weekday <= 3 and 12 <= utc_hour <= 17
            logger.debug(f"Time check oil: UTC {utc_hour}, weekday={weekday}, pass={ok}")
            return ok

        elif commodity in ("gold", "silver"):
            # London/NY overlap: 3AM-8AM ET = 08:00-13:00 UTC
            ok = weekday <= 4 and 8 <= utc_hour <= 12
            logger.debug(f"Time check {commodity}: UTC {utc_hour}, weekday={weekday}, pass={ok}")
            return ok

        return False

    async def run_all_checks(self, direction: str, commodity: str,
                              yahoo_symbol: str) -> dict:
        """Run all 6 confirmations and return results dict."""
        results = {}

        results["dxy"] = await self.check_dxy(direction, commodity)
        results["technical"] = await self.check_technical(direction, yahoo_symbol)
        results["momentum"] = await self.check_momentum(direction, yahoo_symbol)
        results["volatility"] = await self.check_volatility(yahoo_symbol)
        results["rsi"] = await self.check_rsi(direction, yahoo_symbol)
        results["time"] = self.check_time(commodity)

        results["all_passed"] = all(results.values())
        return results

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
