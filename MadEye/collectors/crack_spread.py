"""
MadEye Crack Spread Collector
Calculates 3:2:1 crack spread (refining margins) from Yahoo Finance.
High crack spread = refiners bidding for crude = bullish.
Low crack spread = refiners cutting runs = bearish.
"""

import logging
from typing import Dict

from .base import BaseCollector

logger = logging.getLogger("madeye")


class CrackSpreadCollector(BaseCollector):
    name = "crack_spread"
    category = "crack_spread"
    cache_ttl = 1800  # 30 minutes

    async def collect(self) -> Dict:
        signals = []
        score = 5.0
        confidence = 0.5

        try:
            import yfinance as yf

            # Fetch gasoline (RBOB), heating oil, and Brent crude
            gasoline = yf.Ticker("RB=F")
            heating = yf.Ticker("HO=F")
            crude = yf.Ticker("BZ=F")

            gas_hist = gasoline.history(period="5d")
            heat_hist = heating.history(period="5d")
            crude_hist = crude.history(period="5d")

            if gas_hist.empty or heat_hist.empty or crude_hist.empty:
                signals.append("Crack spread: insufficient price data")
                return self.make_result(score=5.0, direction="NEUTRAL",
                                        signals=signals, confidence=0.0)

            # Prices - gasoline and heating oil are in $/gallon, crude in $/barrel
            # 1 barrel = 42 gallons
            gas_price = float(gas_hist["Close"].iloc[-1]) * 42  # convert to $/barrel
            heat_price = float(heat_hist["Close"].iloc[-1]) * 42
            crude_price = float(crude_hist["Close"].iloc[-1])

            # 3:2:1 crack spread = (2 * gasoline + 1 * heating oil - 3 * crude) / 3
            crack = (2 * gas_price + 1 * heat_price - 3 * crude_price) / 3

            signals.append(f"3:2:1 crack spread: ${crack:.2f}/bbl")
            signals.append(f"Gasoline (RB=F): ${gas_price:.2f}/bbl equivalent")
            signals.append(f"Heating oil (HO=F): ${heat_price:.2f}/bbl equivalent")
            signals.append(f"Brent crude (BZ=F): ${crude_price:.2f}/bbl")

            # Score based on crack spread level
            if crack > 35:
                score = 9.5
                signals.append("Crack spread very high (>$35) -- refiners desperate for crude, very bullish")
            elif crack > 25:
                score = 8.0
                signals.append("Crack spread high (>$25) -- strong refining margins, bullish")
            elif crack > 20:
                score = 7.0
                signals.append("Crack spread above average -- healthy refining demand")
            elif crack > 15:
                score = 5.5
                signals.append("Crack spread normal range ($15-20)")
            elif crack > 10:
                score = 3.5
                signals.append("Crack spread low (<$15) -- refiners cutting runs, bearish")
            elif crack > 5:
                score = 2.0
                signals.append("Crack spread very low (<$10) -- severe demand destruction")
            else:
                score = 1.0
                signals.append("Crack spread collapsed (<$5) -- refiners shutting down")

            # Trend: compare to previous day
            if len(gas_hist) >= 2 and len(heat_hist) >= 2 and len(crude_hist) >= 2:
                prev_gas = float(gas_hist["Close"].iloc[-2]) * 42
                prev_heat = float(heat_hist["Close"].iloc[-2]) * 42
                prev_crude = float(crude_hist["Close"].iloc[-2])
                prev_crack = (2 * prev_gas + 1 * prev_heat - 3 * prev_crude) / 3

                change = crack - prev_crack
                pct_change = (change / abs(prev_crack) * 100) if prev_crack != 0 else 0

                signals.append(f"Crack spread change: {change:+.2f} ({pct_change:+.1f}%)")

                if pct_change > 10:
                    score = min(10, score + 1.0)
                    signals.append("Crack spread surging -- bullish momentum")
                elif pct_change < -10:
                    score = max(0, score - 1.0)
                    signals.append("Crack spread collapsing -- bearish momentum")

            confidence = 0.8

        except ImportError:
            signals.append("Crack spread: yfinance not installed")
            confidence = 0.0
        except Exception as e:
            logger.warning(f"Crack spread error: {e}")
            signals.append(f"Crack spread: error ({str(e)[:80]})")
            confidence = 0.1

        if score >= 6.5:
            direction = "BULLISH"
        elif score <= 3.5:
            direction = "BEARISH"
        else:
            direction = "NEUTRAL"

        return self.make_result(
            score=score,
            direction=direction,
            signals=signals,
            details={"crack_spread": round(crack, 2) if 'crack' in locals() else None},
            confidence=confidence,
        )
