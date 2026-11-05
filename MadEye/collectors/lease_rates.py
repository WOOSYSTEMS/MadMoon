"""
MadEye Gold and Silver Lease/Forward Rates Collector
Calculates implied lease rates from futures curve.
Gold lease rate = SOFR - gold forward rate (GOFO).
Rising lease rates = physical tightness = bullish.
"""

import logging
from typing import Dict, Optional, Tuple

from .base import BaseCollector

logger = logging.getLogger("madeye")

YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=5d"
YAHOO_HEADERS = {"User-Agent": "Mozilla/5.0"}

# SOFR proxy: use 3-month T-bill or hardcode current Fed rate region
# As of late 2026, use Alpha Vantage for fed funds rate
ALPHA_VANTAGE_KEY = "8S7DUSYD93O29PK9"
FRED_SOFR_URL = "https://www.alphavantage.co/query"


class LeaseRatesCollector(BaseCollector):
    name = "lease_rates"
    category = "physical_demand"
    cache_ttl = 3600  # 1 hour

    async def _get_yahoo_price(self, ticker: str) -> Optional[float]:
        """Fetch latest close price from Yahoo Finance."""
        url = YAHOO_CHART.format(ticker=ticker)
        data = await self.fetch_json(url, cache_key=f"price_{ticker.replace('=', '_')}")
        if not data:
            return None
        try:
            result = data["chart"]["result"][0]
            closes = result["indicators"]["quote"][0]["close"]
            for c in reversed(closes):
                if c is not None:
                    return float(c)
        except (KeyError, IndexError, TypeError):
            pass
        return None

    async def _get_sofr_rate(self) -> float:
        """Fetch SOFR or Fed Funds rate. Falls back to hardcoded estimate."""
        # Try Alpha Vantage federal funds rate
        params = {
            "function": "FEDERAL_FUNDS_RATE",
            "interval": "daily",
            "apikey": ALPHA_VANTAGE_KEY,
        }
        data = await self.fetch_json(FRED_SOFR_URL, params=params, cache_key="sofr_rate")
        if data and "data" in data:
            try:
                for entry in data["data"][:5]:
                    val = entry.get("value")
                    if val and val != ".":
                        return float(val) / 100.0  # Convert percentage to decimal
            except (ValueError, KeyError):
                pass

        # Fallback: approximate SOFR from current Fed policy
        return 0.045  # ~4.5% as of late 2026 estimate

    def _calculate_forward_rate(self, spot: float, futures: float,
                                days_to_expiry: int) -> float:
        """Calculate annualized forward rate from spot/futures."""
        if spot <= 0 or days_to_expiry <= 0:
            return 0.0
        return ((futures - spot) / spot) * (360.0 / days_to_expiry)

    def _calculate_lease_rate(self, sofr: float, forward_rate: float) -> float:
        """Lease rate = SOFR - forward rate (GOFO)."""
        return sofr - forward_rate

    async def collect(self) -> Dict:
        signals = []
        subscores = []
        confidence = 0.3

        sofr = await self._get_sofr_rate()
        signals.append(f"SOFR/Fed Funds rate: {sofr*100:.2f}%")

        # --- Gold lease rate ---
        gold_score, gold_signals, gold_details = await self._calc_metal_lease(
            metal="Gold",
            spot_ticker="GC=F",
            # Back month futures - approximate days to expiry
            futures_tickers=[("GCZ26.CMX", 60), ("GCG27.CMX", 150)],
            sofr=sofr,
        )
        subscores.append(gold_score)
        signals.extend(gold_signals)

        # --- Silver lease rate ---
        silver_score, silver_signals, silver_details = await self._calc_metal_lease(
            metal="Silver",
            spot_ticker="SI=F",
            futures_tickers=[("SIZ26.CMX", 60), ("SIH27.CMX", 150)],
            sofr=sofr,
        )
        subscores.append(silver_score)
        signals.extend(silver_signals)

        # Composite: gold 60%, silver 40%
        if subscores:
            weights = [0.6, 0.4][:len(subscores)]
            composite = sum(s * w for s, w in zip(subscores, weights)) / sum(weights)
        else:
            composite = 5.0

        details = {
            "sofr": round(sofr, 4),
            "gold": gold_details,
            "silver": silver_details,
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

    async def _calc_metal_lease(self, metal: str, spot_ticker: str,
                                futures_tickers: list,
                                sofr: float) -> Tuple[float, list, Dict]:
        """Calculate lease rate for a specific metal."""
        signals = []
        score = 5.0
        details = {}

        spot = await self._get_yahoo_price(spot_ticker)
        if spot is None:
            signals.append(f"{metal} spot price unavailable")
            return 5.0, signals, details

        signals.append(f"{metal} spot ({spot_ticker}): ${spot:.2f}")
        details["spot"] = spot

        lease_rates = []
        for fut_ticker, days in futures_tickers:
            fut_price = await self._get_yahoo_price(fut_ticker)
            if fut_price is None:
                # Try alternate ticker format
                alt_ticker = fut_ticker.replace(".CMX", ".CME")
                fut_price = await self._get_yahoo_price(alt_ticker)

            if fut_price is not None and fut_price > 0:
                fwd_rate = self._calculate_forward_rate(spot, fut_price, days)
                lease = self._calculate_lease_rate(sofr, fwd_rate)
                lease_rates.append(lease)
                signals.append(f"{metal} {fut_ticker}: ${fut_price:.2f} | fwd rate: {fwd_rate*100:.2f}% | lease: {lease*100:.2f}%")
                details[fut_ticker] = {
                    "price": fut_price,
                    "forward_rate": round(fwd_rate, 4),
                    "lease_rate": round(lease, 4),
                    "days": days,
                }

        if not lease_rates:
            # Fallback: use spot vs front month futures
            front = await self._get_yahoo_price(spot_ticker)
            signals.append(f"{metal}: no back-month futures data, using spot only")
            return 5.0, signals, details

        avg_lease = sum(lease_rates) / len(lease_rates)
        details["avg_lease_rate"] = round(avg_lease, 4)

        # Score lease rate
        # High lease rate = physical tightness = bullish
        # Normal gold lease rate is 0-2%, silver 0-3%
        if metal == "Gold":
            if avg_lease > 0.03:
                score = 9.0
                signals.append(f"{metal} lease rate very high ({avg_lease*100:.2f}%) -- extreme physical tightness, very bullish")
            elif avg_lease > 0.02:
                score = 8.0
                signals.append(f"{metal} lease rate elevated -- physical tightness, bullish")
            elif avg_lease > 0.01:
                score = 6.5
                signals.append(f"{metal} lease rate above normal -- mild tightness")
            elif avg_lease > 0:
                score = 5.0
                signals.append(f"{metal} lease rate normal range")
            elif avg_lease > -0.01:
                score = 4.0
                signals.append(f"{metal} lease rate slightly negative -- ample supply")
            else:
                score = 3.0
                signals.append(f"{metal} lease rate negative -- excess supply, bearish")
        else:  # Silver
            if avg_lease > 0.04:
                score = 9.0
                signals.append(f"{metal} lease rate very high ({avg_lease*100:.2f}%) -- extreme tightness")
            elif avg_lease > 0.02:
                score = 7.5
                signals.append(f"{metal} lease rate elevated -- tightness, bullish")
            elif avg_lease > 0.005:
                score = 5.5
                signals.append(f"{metal} lease rate normal")
            elif avg_lease > -0.01:
                score = 4.0
                signals.append(f"{metal} lease rate low -- ample supply")
            else:
                score = 2.5
                signals.append(f"{metal} lease rate deeply negative -- bearish")

        return score, signals, details
