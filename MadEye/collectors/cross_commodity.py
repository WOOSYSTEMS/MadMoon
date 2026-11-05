"""
MadEye Cross-Commodity Collector
Tracks gold, copper, natural gas correlations with oil.
Copper/oil ratio = demand health check.
Gold = inflation hedge correlation.
Natural gas substitution effect.
Baltic Dry Index = trade activity.
"""

import logging
from typing import Dict

from .base import BaseCollector

logger = logging.getLogger("madeye")

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"


class CrossCommodityCollector(BaseCollector):
    name = "cross_commodity"
    category = "cross_commodity"
    cache_ttl = 1800  # 30 minutes

    def __init__(self, fred_key: str = None):
        super().__init__()
        self.fred_key = fred_key or "DEMO_KEY"

    async def collect(self) -> Dict:
        signals = []
        subscores = []

        # --- 1. Copper / Oil ratio (demand health) ---
        copper_score, copper_signals = await self._check_copper_oil()
        subscores.append(copper_score)
        signals.extend(copper_signals)

        # --- 2. Gold correlation (inflation hedge) ---
        gold_score, gold_signals = await self._check_gold()
        subscores.append(gold_score)
        signals.extend(gold_signals)

        # --- 3. Natural gas substitution ---
        gas_score, gas_signals = await self._check_natgas()
        subscores.append(gas_score)
        signals.extend(gas_signals)

        # --- 4. Baltic Dry Index (trade activity) ---
        bdi_score, bdi_signals = await self._check_bdi()
        subscores.append(bdi_score)
        signals.extend(bdi_signals)

        # Weighted: Copper 35%, Gold 20%, NatGas 20%, BDI 25%
        weights = [0.35, 0.20, 0.20, 0.25]
        composite = sum(s * w for s, w in zip(subscores, weights)) / sum(weights)

        if composite >= 6.5:
            direction = "BULLISH"
        elif composite <= 3.5:
            direction = "BEARISH"
        else:
            direction = "NEUTRAL"

        confidence = min(1.0, len([s for s in subscores if s != 5.0]) / max(len(subscores), 1))

        return self.make_result(
            score=composite,
            direction=direction,
            signals=signals,
            details={
                "copper_oil_score": round(copper_score, 2),
                "gold_score": round(gold_score, 2),
                "natgas_score": round(gas_score, 2),
                "bdi_score": round(bdi_score, 2),
            },
            confidence=confidence,
        )

    async def _check_copper_oil(self) -> tuple:
        """Copper/oil ratio as demand health indicator."""
        signals = []
        score = 5.0

        try:
            import yfinance as yf

            copper = yf.Ticker("HG=F")
            oil = yf.Ticker("BZ=F")

            cu_hist = copper.history(period="1mo")
            oil_hist = oil.history(period="1mo")

            if cu_hist.empty or oil_hist.empty:
                signals.append("Copper/oil: data unavailable")
                return score, signals

            cu_price = float(cu_hist["Close"].iloc[-1])
            oil_price = float(oil_hist["Close"].iloc[-1])

            # Copper/oil ratio (copper in cents/lb, oil in $/bbl)
            # Typical range: ~4-6
            ratio = (cu_price * 100) / oil_price if oil_price > 0 else 0
            signals.append(f"Copper: ${cu_price:.2f}/lb | Oil: ${oil_price:.2f}/bbl | Ratio: {ratio:.2f}")

            # Check relative performance (1 month)
            if len(cu_hist) >= 10 and len(oil_hist) >= 10:
                cu_start = float(cu_hist["Close"].iloc[0])
                oil_start = float(oil_hist["Close"].iloc[0])

                cu_return = ((cu_price - cu_start) / cu_start) * 100 if cu_start > 0 else 0
                oil_return = ((oil_price - oil_start) / oil_start) * 100 if oil_start > 0 else 0

                relative = cu_return - oil_return
                signals.append(f"1M returns -- Copper: {cu_return:+.1f}% | Oil: {oil_return:+.1f}% | Relative: {relative:+.1f}%")

                # Copper outperforming oil = healthy demand rally (bullish for oil)
                # Oil outperforming copper = supply shock (unsustainable, bearish medium-term)
                if relative > 5:
                    score = 7.5
                    signals.append("Copper outperforming oil -- healthy demand-driven rally (bullish)")
                elif relative > 2:
                    score = 6.5
                    signals.append("Copper slightly outperforming -- demand supporting")
                elif relative < -5:
                    score = 3.0
                    signals.append("Oil outperforming copper -- possible supply shock (unsustainable)")
                elif relative < -2:
                    score = 4.0
                    signals.append("Oil slightly outperforming copper -- demand concern")
                else:
                    score = 5.5
                    signals.append("Copper/oil in sync -- balanced market")

        except ImportError:
            signals.append("Copper/oil: yfinance not installed")
        except Exception as e:
            logger.warning(f"Copper/oil check error: {e}")
            signals.append(f"Copper/oil: error ({str(e)[:60]})")

        return score, signals

    async def _check_gold(self) -> tuple:
        """Gold as inflation/risk hedge correlation with oil."""
        signals = []
        score = 5.0

        try:
            import yfinance as yf

            gold = yf.Ticker("GC=F")
            oil = yf.Ticker("BZ=F")

            gold_hist = gold.history(period="1mo")
            oil_hist = oil.history(period="1mo")

            if gold_hist.empty or oil_hist.empty:
                signals.append("Gold/oil: data unavailable")
                return score, signals

            gold_price = float(gold_hist["Close"].iloc[-1])
            oil_price = float(oil_hist["Close"].iloc[-1])

            # Gold/oil ratio
            ratio = gold_price / oil_price if oil_price > 0 else 0
            signals.append(f"Gold: ${gold_price:.2f}/oz | Gold/Oil ratio: {ratio:.1f}")

            # Check if gold is surging (inflation hedge demand)
            if len(gold_hist) >= 10:
                gold_start = float(gold_hist["Close"].iloc[0])
                gold_return = ((gold_price - gold_start) / gold_start) * 100 if gold_start > 0 else 0

                if gold_return > 5:
                    score = 6.5
                    signals.append(f"Gold surging ({gold_return:+.1f}%) -- inflation fears, supports oil")
                elif gold_return > 2:
                    score = 6.0
                    signals.append(f"Gold rising ({gold_return:+.1f}%) -- mild inflation signal")
                elif gold_return < -5:
                    score = 3.5
                    signals.append(f"Gold falling ({gold_return:+.1f}%) -- deflation/risk-off, bearish oil")
                elif gold_return < -2:
                    score = 4.0
                    signals.append(f"Gold declining ({gold_return:+.1f}%)")
                else:
                    score = 5.0
                    signals.append("Gold stable")

            # High gold/oil ratio = oil relatively cheap
            if ratio > 30:
                score = min(10, score + 0.5)
                signals.append(f"Gold/oil ratio very high ({ratio:.0f}) -- oil cheap relative to gold")
            elif ratio < 15:
                score = max(0, score - 0.5)
                signals.append(f"Gold/oil ratio low ({ratio:.0f}) -- oil expensive relative to gold")

        except ImportError:
            signals.append("Gold: yfinance not installed")
        except Exception as e:
            logger.warning(f"Gold check error: {e}")
            signals.append(f"Gold: error ({str(e)[:60]})")

        return score, signals

    async def _check_natgas(self) -> tuple:
        """Natural gas substitution effect -- gas spike > $7 = oil demand rises."""
        signals = []
        score = 5.0

        try:
            import yfinance as yf

            natgas = yf.Ticker("NG=F")
            ng_hist = natgas.history(period="1mo")

            if ng_hist.empty:
                signals.append("Natural gas: data unavailable")
                return score, signals

            ng_price = float(ng_hist["Close"].iloc[-1])
            signals.append(f"Natural gas (NG=F): ${ng_price:.2f}/MMBtu")

            # Gas spike > $7 = substitution to oil (bullish oil)
            if ng_price > 10:
                score = 8.5
                signals.append("NatGas extreme spike (>$10) -- strong substitution to oil, very bullish")
            elif ng_price > 7:
                score = 7.5
                signals.append("NatGas high (>$7) -- substitution effect boosts oil demand")
            elif ng_price > 5:
                score = 6.0
                signals.append("NatGas elevated -- mild substitution pressure")
            elif ng_price > 3:
                score = 5.0
                signals.append("NatGas normal range")
            elif ng_price > 2:
                score = 4.5
                signals.append("NatGas cheap -- favors gas over oil")
            else:
                score = 3.5
                signals.append("NatGas very cheap (<$2) -- gas heavily preferred over oil")

            # Trend
            if len(ng_hist) >= 10:
                ng_start = float(ng_hist["Close"].iloc[0])
                ng_return = ((ng_price - ng_start) / ng_start) * 100 if ng_start > 0 else 0
                if ng_return > 20:
                    score = min(10, score + 1.0)
                    signals.append(f"NatGas surging ({ng_return:+.1f}%) -- substitution accelerating")
                elif ng_return < -20:
                    score = max(0, score - 0.5)
                    signals.append(f"NatGas plunging ({ng_return:+.1f}%)")

        except ImportError:
            signals.append("NatGas: yfinance not installed")
        except Exception as e:
            logger.warning(f"NatGas check error: {e}")
            signals.append(f"NatGas: error ({str(e)[:60]})")

        return score, signals

    async def _check_bdi(self) -> tuple:
        """Baltic Dry Index -- global trade activity indicator."""
        signals = []
        score = 5.0

        # Try FRED first for BDI-like data
        try:
            data = await self.fetch_json(
                FRED_BASE,
                params={
                    "series_id": "DBDIBDI",
                    "api_key": self.fred_key,
                    "file_type": "json",
                    "sort_order": "desc",
                    "limit": "30",
                },
                cache_key="fred_bdi",
            )
            if data and "observations" in data:
                values = []
                for obs in data["observations"]:
                    v = obs.get("value", ".")
                    if v != ".":
                        values.append(float(v))
                    if len(values) >= 20:
                        break

                if values:
                    current_bdi = values[0]
                    signals.append(f"Baltic Dry Index (FRED): {current_bdi:.0f}")

                    if current_bdi > 3000:
                        score = 8.0
                        signals.append("BDI very high -- booming trade activity (bullish oil)")
                    elif current_bdi > 2000:
                        score = 7.0
                        signals.append("BDI elevated -- strong trade demand")
                    elif current_bdi > 1500:
                        score = 6.0
                        signals.append("BDI above average -- healthy trade")
                    elif current_bdi > 1000:
                        score = 5.0
                        signals.append("BDI average")
                    elif current_bdi > 500:
                        score = 3.5
                        signals.append("BDI below average -- weak trade")
                    else:
                        score = 2.0
                        signals.append("BDI very low -- trade collapse, bearish")

                    # Trend
                    if len(values) >= 5:
                        prev = values[4]
                        change_pct = ((current_bdi - prev) / prev) * 100 if prev > 0 else 0
                        if change_pct > 15:
                            score = min(10, score + 1.0)
                            signals.append(f"BDI surging ({change_pct:+.1f}%)")
                        elif change_pct < -15:
                            score = max(0, score - 1.0)
                            signals.append(f"BDI declining ({change_pct:+.1f}%)")

                    return score, signals
        except Exception as e:
            logger.warning(f"FRED BDI error: {e}")

        # Fallback: Yahoo Finance ^BDI
        try:
            import yfinance as yf
            bdi = yf.Ticker("^BDI")
            bdi_hist = bdi.history(period="1mo")
            if not bdi_hist.empty:
                bdi_val = float(bdi_hist["Close"].iloc[-1])
                signals.append(f"Baltic Dry Index (Yahoo): {bdi_val:.0f}")

                if bdi_val > 2000:
                    score = 7.5
                elif bdi_val > 1000:
                    score = 5.5
                else:
                    score = 3.0
                return score, signals
        except Exception as e:
            logger.warning(f"Yahoo BDI error: {e}")

        signals.append("Baltic Dry Index: data unavailable")
        return score, signals
