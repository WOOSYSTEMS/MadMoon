"""
MadEye Crack Spread Variants Collector
Calculates additional crack spreads: 5:3:2, jet fuel, diesel, gasoline.
High cracks = refiners buying crude aggressively = bullish oil.
All prices from Yahoo Finance raw API.
"""

import logging
from typing import Dict, Optional, Tuple, List

from .base import BaseCollector

logger = logging.getLogger("madeye")

YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=10d"


class CrackVariantsCollector(BaseCollector):
    name = "crack_variants"
    category = "crack_spread"
    cache_ttl = 1800  # 30 minutes

    async def _get_price(self, ticker: str) -> Optional[float]:
        """Fetch latest close from Yahoo Finance."""
        url = YAHOO_CHART.format(ticker=ticker)
        data = await self.fetch_json(url, cache_key=f"crack_px_{ticker.replace('=', '_')}")
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

    async def _get_prev_price(self, ticker: str) -> Optional[float]:
        """Fetch previous day close for trend."""
        url = YAHOO_CHART.format(ticker=ticker)
        data = await self.fetch_json(url, cache_key=f"crack_px_{ticker.replace('=', '_')}")
        if not data:
            return None
        try:
            result = data["chart"]["result"][0]
            closes = result["indicators"]["quote"][0]["close"]
            valid = [c for c in closes if c is not None]
            if len(valid) >= 2:
                return float(valid[-2])
        except (KeyError, IndexError, TypeError):
            pass
        return None

    def _score_crack(self, name: str, crack: float, prev_crack: Optional[float],
                     thresholds: Dict) -> Tuple[float, List[str]]:
        """Score a crack spread with configurable thresholds."""
        signals = []
        score = 5.0

        signals.append(f"{name}: ${crack:.2f}/bbl")

        if crack > thresholds.get("very_high", 35):
            score = 9.0
            signals.append(f"{name} very high -- refiners desperate for crude, very bullish")
        elif crack > thresholds.get("high", 25):
            score = 7.5
            signals.append(f"{name} high -- strong refining margins, bullish")
        elif crack > thresholds.get("above_avg", 18):
            score = 6.5
            signals.append(f"{name} above average -- healthy refining demand")
        elif crack > thresholds.get("normal", 12):
            score = 5.0
            signals.append(f"{name} normal range")
        elif crack > thresholds.get("low", 5):
            score = 3.5
            signals.append(f"{name} low -- weak refining margins, bearish")
        else:
            score = 2.0
            signals.append(f"{name} collapsed -- refiners cutting runs")

        # Trend
        if prev_crack is not None and prev_crack != 0:
            change_pct = (crack - prev_crack) / abs(prev_crack) * 100
            signals.append(f"{name} trend: {change_pct:+.1f}% vs prior day")
            if change_pct > 10:
                score = min(10, score + 0.5)
            elif change_pct < -10:
                score = max(0, score - 0.5)

        return score, signals

    async def collect(self) -> Dict:
        signals = []
        subscores = []
        confidence = 0.3

        # Fetch all prices
        # Gasoline (RBOB) in $/gallon, Heating oil in $/gallon, Crude in $/barrel
        rb = await self._get_price("RB=F")   # RBOB gasoline
        ho = await self._get_price("HO=F")   # Heating oil (diesel/jet proxy)
        bz = await self._get_price("BZ=F")   # Brent crude
        cl = await self._get_price("CL=F")   # WTI crude

        # Previous day prices for trend
        rb_prev = await self._get_prev_price("RB=F")
        ho_prev = await self._get_prev_price("HO=F")
        bz_prev = await self._get_prev_price("BZ=F")
        cl_prev = await self._get_prev_price("CL=F")

        details = {}

        if rb is None or ho is None:
            signals.append("Product prices unavailable (RB=F or HO=F)")
            return self.make_result(score=5.0, direction="NEUTRAL",
                                    signals=signals, confidence=0.0)

        # Convert $/gallon to $/barrel (42 gal/bbl)
        gas_bbl = rb * 42
        ho_bbl = ho * 42

        signals.append(f"Gasoline (RB=F): ${rb:.4f}/gal = ${gas_bbl:.2f}/bbl")
        signals.append(f"Heating oil (HO=F): ${ho:.4f}/gal = ${ho_bbl:.2f}/bbl")
        if bz:
            signals.append(f"Brent (BZ=F): ${bz:.2f}/bbl")
        if cl:
            signals.append(f"WTI (CL=F): ${cl:.2f}/bbl")

        crude = bz or cl  # Prefer Brent
        crude_prev = bz_prev or cl_prev
        if crude is None:
            signals.append("Crude price unavailable")
            return self.make_result(score=5.0, direction="NEUTRAL",
                                    signals=signals, confidence=0.0)

        # Previous barrel equivalents
        gas_bbl_prev = rb_prev * 42 if rb_prev else None
        ho_bbl_prev = ho_prev * 42 if ho_prev else None

        # --- 1. 5:3:2 crack spread ---
        # (3*gasoline + 2*heating_oil - 5*crude) / 5
        crack_532 = (3 * gas_bbl + 2 * ho_bbl - 5 * crude) / 5
        prev_532 = None
        if gas_bbl_prev and ho_bbl_prev and crude_prev:
            prev_532 = (3 * gas_bbl_prev + 2 * ho_bbl_prev - 5 * crude_prev) / 5

        s532, sig532 = self._score_crack("5:3:2 crack", crack_532, prev_532,
                                          {"very_high": 30, "high": 22, "above_avg": 15,
                                           "normal": 10, "low": 5})
        subscores.append(s532)
        signals.extend(sig532)
        details["crack_532"] = round(crack_532, 2)

        # --- 2. Jet fuel crack (HO=F as proxy) ---
        jet_crack = ho_bbl - crude
        prev_jet = (ho_bbl_prev - crude_prev) if (ho_bbl_prev and crude_prev) else None

        sjet, sigjet = self._score_crack("Jet fuel crack", jet_crack, prev_jet,
                                          {"very_high": 40, "high": 30, "above_avg": 22,
                                           "normal": 15, "low": 8})
        subscores.append(sjet)
        signals.extend(sigjet)
        details["jet_crack"] = round(jet_crack, 2)

        # --- 3. Diesel crack (HO=F - BZ=F) ---
        diesel_crack = ho_bbl - crude
        # Same as jet (HO is best proxy for both diesel and jet)
        details["diesel_crack"] = round(diesel_crack, 2)
        signals.append(f"Diesel crack (HO-Brent): ${diesel_crack:.2f}/bbl (same as jet proxy)")

        # --- 4. Gasoline crack (RB=F - BZ=F) ---
        gas_crack = gas_bbl - crude
        prev_gas_crack = (gas_bbl_prev - crude_prev) if (gas_bbl_prev and crude_prev) else None

        sgas, siggas = self._score_crack("Gasoline crack", gas_crack, prev_gas_crack,
                                          {"very_high": 35, "high": 25, "above_avg": 18,
                                           "normal": 12, "low": 5})
        subscores.append(sgas)
        signals.extend(siggas)
        details["gasoline_crack"] = round(gas_crack, 2)

        confidence = 0.8

        # Composite: equal weight across 3 unique cracks (532, jet, gasoline)
        composite = sum(subscores) / len(subscores) if subscores else 5.0

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
