"""
MadEye Supply Collector
Pulls EIA weekly inventory data, OPEC production, Baker Hughes rig count, SPR levels.
Scores supply signal 0-10.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .base import BaseCollector

logger = logging.getLogger("madeye")

# EIA API configuration
EIA_BASE = "https://api.eia.gov/v2/petroleum/sum/sndw/data/"

# Key EIA series IDs
EIA_SERIES = {
    "crude_stocks": "WCESTUS1",       # US Commercial Crude Oil Stocks
    "gasoline_stocks": "WGTSTUS1",    # US Total Gasoline Stocks
    "distillate_stocks": "WDISTUS1",  # US Distillate Fuel Oil Stocks
    "production": "WCRFPUS2",         # US Field Production
    "imports": "WCRIMUS2",            # US Crude Oil Imports
    "exports": "WCREXUS2",            # US Crude Oil Exports
    "refinery_util": "WPULEUS3",      # Refinery Utilization Rate
    "spr": "WCSSTUS1",               # Strategic Petroleum Reserve
}

def _load_eia_key():
    """Load EIA API key from data file or environment."""
    import os
    key_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "eia_api_key.txt")
    if os.path.exists(key_path):
        with open(key_path) as f:
            return f.read().strip()
    return os.environ.get("EIA_API_KEY", "DEMO_KEY")


class SupplyCollector(BaseCollector):
    name = "supply"
    category = "supply"
    cache_ttl = 1800  # 30 minutes

    def __init__(self, eia_key: str = None):
        super().__init__()
        self.eia_key = eia_key or _load_eia_key()

    async def collect(self) -> Dict:
        signals = []
        subscores = []

        # --- 1. EIA Crude Inventory ---
        inv_score, inv_signals = await self._check_eia_inventory()
        subscores.append(inv_score)
        signals.extend(inv_signals)

        # --- 2. SPR Levels ---
        spr_score, spr_signals = await self._check_spr()
        subscores.append(spr_score)
        signals.extend(spr_signals)

        # --- 3. US Production ---
        prod_score, prod_signals = await self._check_production()
        subscores.append(prod_score)
        signals.extend(prod_signals)

        # --- 4. Refinery Utilization ---
        ref_score, ref_signals = await self._check_refinery()
        subscores.append(ref_score)
        signals.extend(ref_signals)

        # --- 5. Import/Export Balance ---
        ie_score, ie_signals = await self._check_imports_exports()
        subscores.append(ie_score)
        signals.extend(ie_signals)

        # --- 6. US Crude Exports (standalone) ---
        exp_score, exp_signals = await self._check_exports()
        subscores.append(exp_score)
        signals.extend(exp_signals)

        # --- 7. OPEC Spare Capacity Signal ---
        opec_score, opec_signals = self._check_opec_spare()
        subscores.append(opec_score)
        signals.extend(opec_signals)

        # Weighted: Inventory 30%, SPR 8%, Production 22%, Refinery 12%, Imports/Exports 12%, Exports 8%, OPEC 8%
        weights = [0.30, 0.08, 0.22, 0.12, 0.12, 0.08, 0.08]
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
                "inventory_score": round(inv_score, 2),
                "spr_score": round(spr_score, 2),
                "production_score": round(prod_score, 2),
                "refinery_score": round(ref_score, 2),
                "exports_score": round(exp_score, 2),
                "opec_spare_score": round(opec_score, 2),
            },
            confidence=confidence,
        )

    async def _fetch_eia_series(self, series_id: str, length: int = 10) -> Optional[List]:
        """Fetch EIA data series."""
        params = {
            "api_key": self.eia_key,
            "frequency": "weekly",
            "data[0]": "value",
            "facets[series][]": series_id,
            "sort[0][column]": "period",
            "sort[0][direction]": "desc",
            "length": str(length),
        }
        data = await self.fetch_json(
            EIA_BASE, params=params, cache_key=f"eia_{series_id}"
        )
        if data and "response" in data:
            return data["response"].get("data", [])
        return None

    async def _check_eia_inventory(self) -> tuple:
        """Check US crude oil inventory changes."""
        signals = []
        score = 5.0

        records = await self._fetch_eia_series("WCESTUS1", length=5)
        if not records or len(records) < 2:
            signals.append("EIA inventory: data unavailable")
            return score, signals

        try:
            latest = float(records[0].get("value", 0))
            previous = float(records[1].get("value", 0))
            change = latest - previous  # in thousands of barrels

            # Change in millions of barrels
            change_mb = change / 1000.0

            signals.append(f"EIA crude stocks: {latest/1000:.1f}M bbl (change: {change_mb:+.1f}M)")

            # Score: draw = bullish (higher score), build = bearish (lower score)
            if change_mb < -5:
                score = 9.0
                signals.append(f"Large inventory draw: {change_mb:+.1f}M bbl")
            elif change_mb < -3:
                score = 7.5
                signals.append(f"Significant draw: {change_mb:+.1f}M bbl")
            elif change_mb < -1:
                score = 6.5
                signals.append(f"Moderate draw: {change_mb:+.1f}M bbl")
            elif change_mb < 1:
                score = 5.0
                signals.append(f"Flat inventory: {change_mb:+.1f}M bbl")
            elif change_mb < 3:
                score = 3.5
                signals.append(f"Moderate build: {change_mb:+.1f}M bbl")
            elif change_mb < 5:
                score = 2.5
                signals.append(f"Significant build: {change_mb:+.1f}M bbl")
            else:
                score = 1.0
                signals.append(f"Large inventory build: {change_mb:+.1f}M bbl")

            # Multi-week trend
            if len(records) >= 4:
                vals = [float(r.get("value", 0)) for r in records[:4]]
                trend = vals[-1] - vals[0]  # older - newest (reversed order)
                trend_mb = trend / 1000.0
                if trend_mb > 5:
                    score = min(10, score + 1.0)
                    signals.append(f"4-week draw trend: {-trend_mb:.1f}M bbl")
                elif trend_mb < -5:
                    score = max(0, score - 1.0)
                    signals.append(f"4-week build trend: {-trend_mb:.1f}M bbl")

        except (ValueError, TypeError, IndexError) as e:
            logger.warning(f"EIA inventory parse error: {e}")
            signals.append("EIA inventory: parse error")

        return score, signals

    async def _check_spr(self) -> tuple:
        """Check Strategic Petroleum Reserve levels."""
        signals = []
        score = 5.0

        records = await self._fetch_eia_series("WCSSTUS1", length=5)
        if not records or len(records) < 2:
            signals.append("SPR data: unavailable")
            return score, signals

        try:
            latest = float(records[0].get("value", 0))
            previous = float(records[1].get("value", 0))
            change = latest - previous
            change_mb = change / 1000.0
            level_mb = latest / 1000.0

            signals.append(f"SPR level: {level_mb:.1f}M bbl (change: {change_mb:+.1f}M)")

            # SPR release = more supply = bearish (lower score)
            # SPR refill = less market supply = bullish (higher score)
            if change_mb < -5:
                score = 2.0
                signals.append("Large SPR release (bearish supply)")
            elif change_mb < -1:
                score = 3.5
                signals.append("SPR releasing")
            elif change_mb > 1:
                score = 7.0
                signals.append("SPR refilling (bullish)")
            elif change_mb > 5:
                score = 8.5
                signals.append("Large SPR refill (very bullish)")
            else:
                score = 5.0

            # Critically low SPR = less buffer = bullish for risk premium
            if level_mb < 300:
                score = min(10, score + 1.0)
                signals.append(f"SPR critically low at {level_mb:.0f}M bbl")

        except (ValueError, TypeError) as e:
            signals.append(f"SPR parse error: {str(e)[:50]}")

        return score, signals

    async def _check_production(self) -> tuple:
        """Check US crude production levels."""
        signals = []
        score = 5.0

        records = await self._fetch_eia_series("WCRFPUS2", length=5)
        if not records or len(records) < 2:
            signals.append("US production data: unavailable")
            return score, signals

        try:
            latest = float(records[0].get("value", 0))
            previous = float(records[1].get("value", 0))
            change = latest - previous  # thousands bbl/d

            signals.append(f"US production: {latest:.0f}K bbl/d (change: {change:+.0f}K)")

            # Rising production = more supply = bearish (lower score)
            if change > 200:
                score = 2.5
                signals.append("Sharp production increase (bearish)")
            elif change > 50:
                score = 3.5
                signals.append("Production rising")
            elif change < -200:
                score = 8.0
                signals.append("Sharp production decline (bullish)")
            elif change < -50:
                score = 6.5
                signals.append("Production declining")
            else:
                score = 5.0

            # Record high production is bearish
            if latest > 13500:
                score = max(0, score - 0.5)
                signals.append("Production near record highs")

        except (ValueError, TypeError) as e:
            signals.append(f"Production parse error: {str(e)[:50]}")

        return score, signals

    async def _check_refinery(self) -> tuple:
        """Check refinery utilization rate."""
        signals = []
        score = 5.0

        records = await self._fetch_eia_series("WPULEUS3", length=5)
        if not records or len(records) < 1:
            signals.append("Refinery utilization: unavailable")
            return score, signals

        try:
            latest = float(records[0].get("value", 0))
            signals.append(f"Refinery utilization: {latest:.1f}%")

            # High utilization = tight market = bullish
            # Low utilization = slack = bearish or turnaround
            if latest > 95:
                score = 8.0
                signals.append("Very high refinery utilization (tight)")
            elif latest > 93:
                score = 7.0
                signals.append("High refinery utilization")
            elif latest > 90:
                score = 5.5
            elif latest > 88:
                score = 4.0
                signals.append("Below-average refinery utilization")
            else:
                score = 3.0
                signals.append("Low refinery utilization (turnaround/weakness)")

        except (ValueError, TypeError) as e:
            signals.append(f"Refinery parse error: {str(e)[:50]}")

        return score, signals

    async def _check_imports_exports(self) -> tuple:
        """Check US crude oil import/export balance."""
        signals = []
        score = 5.0

        imports_data = await self._fetch_eia_series("WCRIMUS2", length=5)
        exports_data = await self._fetch_eia_series("WCREXUS2", length=5)

        if not imports_data or not exports_data:
            signals.append("Import/export data: unavailable")
            return score, signals

        try:
            latest_imports = float(imports_data[0].get("value", 0))
            latest_exports = float(exports_data[0].get("value", 0))
            net_imports = latest_imports - latest_exports

            signals.append(f"US imports: {latest_imports:.0f}K bbl/d, exports: {latest_exports:.0f}K bbl/d")
            signals.append(f"Net imports: {net_imports:.0f}K bbl/d")

            # Rising net imports = tighter global supply = bullish
            if len(imports_data) >= 2 and len(exports_data) >= 2:
                prev_imports = float(imports_data[1].get("value", 0))
                prev_exports = float(exports_data[1].get("value", 0))
                prev_net = prev_imports - prev_exports
                change = net_imports - prev_net

                if change > 300:
                    score = 7.0
                    signals.append("Net imports rising sharply (tighter global supply)")
                elif change > 100:
                    score = 6.0
                elif change < -300:
                    score = 3.0
                    signals.append("Net imports falling sharply (global oversupply)")
                elif change < -100:
                    score = 4.0
                else:
                    score = 5.0

            # High exports = US production strong but global demand pulling
            if latest_exports > 4500:
                score = min(10, score + 0.5)
                signals.append("Record-level US exports (strong global pull)")

        except (ValueError, TypeError) as e:
            signals.append(f"Import/export parse error: {str(e)[:50]}")

        return score, signals

    async def _check_exports(self) -> tuple:
        """Check US crude oil exports as a standalone signal."""
        signals = []
        score = 5.0

        records = await self._fetch_eia_series("WCREXUS2", length=10)
        if not records or len(records) < 2:
            signals.append("US crude exports: data unavailable")
            return score, signals

        try:
            latest = float(records[0].get("value", 0))
            previous = float(records[1].get("value", 0))
            change = latest - previous

            signals.append(f"US crude exports: {latest:.0f}K bbl/d (change: {change:+.0f}K)")

            # High exports = global demand pulling US crude = bullish
            if latest > 5000:
                score = 7.5
                signals.append("US exports at record levels -- strong global pull (bullish)")
            elif latest > 4000:
                score = 6.5
                signals.append("US exports elevated -- healthy global demand")
            elif latest > 3000:
                score = 5.5
                signals.append("US exports normal range")
            elif latest > 2000:
                score = 4.0
                signals.append("US exports below average -- weak global demand")
            else:
                score = 3.0
                signals.append("US exports very low -- bearish global demand signal")

            # Trend
            if len(records) >= 4:
                avg_recent = sum(float(r.get("value", 0)) for r in records[:2]) / 2
                avg_prior = sum(float(r.get("value", 0)) for r in records[2:4]) / 2
                trend = avg_recent - avg_prior
                if trend > 200:
                    score = min(10, score + 0.5)
                    signals.append(f"Export trend rising ({trend:+.0f}K)")
                elif trend < -200:
                    score = max(0, score - 0.5)
                    signals.append(f"Export trend falling ({trend:+.0f}K)")

        except (ValueError, TypeError) as e:
            signals.append(f"Export parse error: {str(e)[:50]}")

        return score, signals

    def _check_opec_spare(self) -> tuple:
        """OPEC spare capacity signal for supply risk premium.
        Hardcoded estimate ~3.5M bbl/d as of late 2026. Update from reports.
        """
        signals = []
        spare_mbd = 3.5

        signals.append(f"OPEC spare capacity: ~{spare_mbd:.1f}M bbl/d (estimate)")

        if spare_mbd < 1.5:
            score = 9.0
            signals.append("OPEC spare capacity critically low -- extreme risk premium")
        elif spare_mbd < 2.5:
            score = 7.5
            signals.append("OPEC spare capacity tight -- elevated risk premium, bullish")
        elif spare_mbd < 4.0:
            score = 5.5
            signals.append("OPEC spare capacity moderate")
        elif spare_mbd < 5.5:
            score = 4.0
            signals.append("OPEC spare capacity comfortable -- bearish for prices")
        else:
            score = 2.5
            signals.append("OPEC spare capacity very high -- ample buffer, bearish")

        return score, signals
