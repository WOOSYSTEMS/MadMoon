"""
MadEye Gold -- Inflation Data Collector
CPI, PPI, PCE data. Gold is the classic inflation hedge.
Higher than expected inflation = bullish gold.
Weight: 7% of total signal.
"""

import logging
from typing import Dict, List, Tuple

from .base import BaseCollector

logger = logging.getLogger("madeye.gold")


class InflationCollector(BaseCollector):
    name = "inflation"
    category = "inflation"
    cache_ttl = 3600  # 1 hour (macro data updates slowly)

    def __init__(self, fred_key: str = None):
        super().__init__()
        self.fred_key = fred_key or "DEMO_KEY"

    async def collect(self) -> Dict:
        signals = []
        subscores = []

        # --- 1. CPI (Headline) ---
        cpi_score, cpi_signals = await self._analyze_series(
            "CPIAUCSL", "CPI (Headline)", target=2.0
        )
        subscores.append(("cpi", cpi_score, 0.30))
        signals.extend(cpi_signals)

        # --- 2. Core CPI ---
        core_score, core_signals = await self._analyze_series(
            "CPILFESL", "Core CPI (ex Food/Energy)", target=2.0
        )
        subscores.append(("core_cpi", core_score, 0.25))
        signals.extend(core_signals)

        # --- 3. PCE (Fed's preferred) ---
        pce_score, pce_signals = await self._analyze_series(
            "PCEPI", "PCE Price Index", target=2.0
        )
        subscores.append(("pce", pce_score, 0.25))
        signals.extend(pce_signals)

        # --- 4. Core PCE ---
        cpce_score, cpce_signals = await self._analyze_series(
            "PCEPILFE", "Core PCE (ex Food/Energy)", target=2.0
        )
        subscores.append(("core_pce", cpce_score, 0.20))
        signals.extend(cpce_signals)

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
                "cpi_score": round(cpi_score, 2),
                "core_cpi_score": round(core_score, 2),
                "pce_score": round(pce_score, 2),
                "core_pce_score": round(cpce_score, 2),
            },
            confidence=confidence,
        )

    async def _analyze_series(self, series_id: str, label: str, target: float = 2.0) -> Tuple[float, List[str]]:
        """Fetch FRED inflation series and compute YoY rate and trend."""
        signals = []
        score = 5.0

        try:
            url = "https://api.stlouisfed.org/fred/series/observations"
            params = {
                "series_id": series_id,
                "api_key": self.fred_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 15,  # ~15 months for YoY
                "units": "pc1",  # Percent change from year ago
            }
            data = await self.fetch_json(url, params=params, cache_key=f"fred_{series_id}")

            if data and "observations" in data:
                obs = [o for o in data["observations"] if o["value"] != "."]
                if obs:
                    latest_yoy = float(obs[0]["value"])
                    signals.append(f"{label} YoY: {latest_yoy:.2f}%")

                    # Above target = inflation running hot = bullish gold
                    if latest_yoy > 5.0:
                        score = 9.5
                        signals.append(f"{label} far above {target}% target -- strong inflation hedge demand")
                    elif latest_yoy > 4.0:
                        score = 8.5
                        signals.append(f"{label} well above target -- bullish gold as inflation hedge")
                    elif latest_yoy > 3.0:
                        score = 7.5
                        signals.append(f"{label} above target -- gold as inflation hedge")
                    elif latest_yoy > target:
                        score = 6.5
                        signals.append(f"{label} above {target}% target -- mild inflation pressure")
                    elif latest_yoy > target - 0.5:
                        score = 5.0
                        signals.append(f"{label} near target")
                    elif latest_yoy > 1.0:
                        score = 4.0
                        signals.append(f"{label} below target -- disinflation, less gold demand")
                    else:
                        score = 3.0
                        signals.append(f"{label} very low -- deflation risk, mixed for gold")

                    # Trend: rising inflation = more bullish
                    if len(obs) >= 3:
                        prev = float(obs[2]["value"])
                        trend = latest_yoy - prev

                        if trend > 0.3:
                            score = min(10, score + 1.0)
                            signals.append(f"{label} trend: accelerating (+{trend:.2f}pp) -- inflation re-igniting")
                        elif trend > 0.1:
                            score = min(10, score + 0.5)
                            signals.append(f"{label} trend: rising ({trend:+.2f}pp)")
                        elif trend < -0.3:
                            score = max(0, score - 1.0)
                            signals.append(f"{label} trend: decelerating ({trend:+.2f}pp) -- inflation cooling")
                        elif trend < -0.1:
                            score = max(0, score - 0.5)
                            signals.append(f"{label} trend: easing ({trend:+.2f}pp)")

                    # Surprise factor: if latest > consensus, extra bullish
                    # (We approximate "surprise" by comparing to 3-month average)
                    if len(obs) >= 4:
                        avg_3m = sum(float(o["value"]) for o in obs[1:4]) / 3
                        surprise = latest_yoy - avg_3m
                        if surprise > 0.2:
                            score = min(10, score + 0.5)
                            signals.append(f"{label}: upside surprise vs 3mo avg ({surprise:+.2f}pp)")
                        elif surprise < -0.2:
                            score = max(0, score - 0.5)
                            signals.append(f"{label}: downside surprise vs 3mo avg ({surprise:+.2f}pp)")

        except Exception as e:
            logger.warning(f"FRED {series_id} error: {e}")
            signals.append(f"{label} data unavailable")

        return score, signals
