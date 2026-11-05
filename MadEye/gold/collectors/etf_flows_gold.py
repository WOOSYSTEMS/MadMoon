"""
MadEye Gold -- ETF Flows Collector (GLD, IAU)
Tracks institutional gold demand through ETF volume and price action.
Rising volume + rising price = bullish confirmation.
Weight: 8% of total signal.
"""

import logging
from typing import Dict, List, Tuple

from .base import BaseCollector

logger = logging.getLogger("madeye.gold")


class ETFFlowsGoldCollector(BaseCollector):
    name = "etf_flows_gold"
    category = "etf_flows"
    cache_ttl = 600  # 10 minutes

    async def collect(self) -> Dict:
        signals = []
        subscores = []

        # --- 1. GLD (SPDR Gold Shares) ---
        gld_score, gld_signals = await self._analyze_etf("GLD", "SPDR Gold Shares")
        subscores.append(("gld", gld_score, 0.50))
        signals.extend(gld_signals)

        # --- 2. IAU (iShares Gold Trust) ---
        iau_score, iau_signals = await self._analyze_etf("IAU", "iShares Gold Trust")
        subscores.append(("iau", iau_score, 0.30))
        signals.extend(iau_signals)

        # --- 3. Volume divergence analysis ---
        div_score, div_signals = await self._analyze_volume_divergence()
        subscores.append(("divergence", div_score, 0.20))
        signals.extend(div_signals)

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
                "gld_score": round(gld_score, 2),
                "iau_score": round(iau_score, 2),
                "divergence_score": round(div_score, 2),
            },
            confidence=confidence,
        )

    async def _analyze_etf(self, symbol: str, name: str) -> Tuple[float, List[str]]:
        """Analyze a gold ETF for price and volume signals."""
        signals = []
        score = 5.0

        try:
            import yfinance as yf
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="3mo")

            if hist.empty:
                return 5.0, [f"{symbol}: No data"]

            prices = hist["Close"].dropna().tolist()
            volumes = hist["Volume"].dropna().tolist()
            current = prices[-1]

            signals.append(f"{symbol}: ${current:.2f}")

            # Cache for divergence analysis
            self._set_cache(f"{symbol}_data", {
                "prices": prices[-60:],
                "volumes": volumes[-60:],
            })

            # Price trend (5-day)
            if len(prices) >= 6:
                price_change_5d = (current - prices[-6]) / prices[-6] * 100
                signals.append(f"{symbol} 5d: {price_change_5d:+.2f}%")

            # Volume analysis
            if len(volumes) >= 21:
                avg_vol_20 = sum(volumes[-21:-1]) / 20
                recent_vol = volumes[-1]
                vol_ratio = recent_vol / avg_vol_20 if avg_vol_20 > 0 else 1.0

                price_change = prices[-1] - prices[-2] if len(prices) >= 2 else 0

                if price_change > 0 and vol_ratio > 1.5:
                    score = 8.0
                    signals.append(f"{name}: Rising on {vol_ratio:.1f}x volume -- institutional buying confirmed")
                elif price_change > 0 and vol_ratio > 1.0:
                    score = 6.5
                    signals.append(f"{name}: Rising on normal volume")
                elif price_change > 0 and vol_ratio < 0.7:
                    score = 5.5
                    signals.append(f"{name}: Rising on low volume -- weak rally")
                elif price_change < 0 and vol_ratio > 1.5:
                    score = 2.5
                    signals.append(f"{name}: Falling on {vol_ratio:.1f}x volume -- institutional selling")
                elif price_change < 0 and vol_ratio > 1.0:
                    score = 3.5
                    signals.append(f"{name}: Falling on normal volume")
                elif price_change < 0 and vol_ratio < 0.7:
                    score = 5.5
                    signals.append(f"{name}: Falling on low volume -- selling exhaustion")
                else:
                    score = 5.0

                # Multi-day volume surge (3+ days of above-average volume)
                if len(volumes) >= 5:
                    high_vol_days = sum(1 for v in volumes[-5:] if v > avg_vol_20 * 1.3)
                    if high_vol_days >= 3:
                        if price_change > 0:
                            score = min(10, score + 1.0)
                            signals.append(f"{symbol}: {high_vol_days}/5 high-volume days with rising price -- accumulation")
                        else:
                            score = max(0, score - 1.0)
                            signals.append(f"{symbol}: {high_vol_days}/5 high-volume days with falling price -- distribution")

        except Exception as e:
            logger.warning(f"ETF {symbol} error: {e}")
            signals.append(f"{symbol} data unavailable")

        return score, signals

    async def _analyze_volume_divergence(self) -> Tuple[float, List[str]]:
        """Check for GLD/IAU volume divergence with gold price."""
        signals = []
        score = 5.0

        gld_data = self._get_cache("GLD_data", ignore_ttl=True)
        iau_data = self._get_cache("IAU_data", ignore_ttl=True)

        if not gld_data or not iau_data:
            return 5.0, ["ETF divergence: insufficient data"]

        gld_prices = gld_data.get("prices", [])
        gld_vols = gld_data.get("volumes", [])
        iau_prices = iau_data.get("prices", [])
        iau_vols = iau_data.get("volumes", [])

        if len(gld_prices) < 20 or len(iau_prices) < 20:
            return 5.0, ["ETF divergence: insufficient history"]

        # Check if both ETFs moving in same direction (confirmation)
        gld_5d = (gld_prices[-1] - gld_prices[-6]) / gld_prices[-6] * 100 if len(gld_prices) >= 6 else 0
        iau_5d = (iau_prices[-1] - iau_prices[-6]) / iau_prices[-6] * 100 if len(iau_prices) >= 6 else 0

        if gld_5d > 0.5 and iau_5d > 0.5:
            score = 7.5
            signals.append("GLD + IAU both rising -- broad institutional gold demand confirmed")
        elif gld_5d < -0.5 and iau_5d < -0.5:
            score = 2.5
            signals.append("GLD + IAU both falling -- institutional gold selling confirmed")
        elif abs(gld_5d - iau_5d) > 1.0:
            score = 5.0
            signals.append("GLD/IAU diverging -- mixed institutional signals")
        else:
            score = 5.0

        return score, signals
