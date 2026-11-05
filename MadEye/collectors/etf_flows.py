"""
MadEye ETF Flows Collector
Tracks USO and BNO oil ETF prices/volume as institutional flow proxy.
Volume spikes = institutional activity.
Monthly roll dates = predictable selling pressure.
"""

import logging
from datetime import datetime, timezone
from typing import Dict

from .base import BaseCollector

logger = logging.getLogger("madeye")


class ETFFlowsCollector(BaseCollector):
    name = "etf_flows"
    category = "etf_flows"
    cache_ttl = 1800  # 30 minutes

    async def collect(self) -> Dict:
        signals = []
        subscores = []

        # --- 1. USO (US Oil Fund) ---
        uso_score, uso_signals = await self._check_etf("USO", "United States Oil Fund")
        subscores.append(uso_score)
        signals.extend(uso_signals)

        # --- 2. BNO (Brent Oil Fund) ---
        bno_score, bno_signals = await self._check_etf("BNO", "United States Brent Oil Fund")
        subscores.append(bno_score)
        signals.extend(bno_signals)

        # --- 3. Roll date pressure ---
        roll_score, roll_signals = self._check_roll_dates()
        subscores.append(roll_score)
        signals.extend(roll_signals)

        # Weighted: USO 40%, BNO 30%, Roll dates 30%
        weights = [0.40, 0.30, 0.30]
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
                "uso_score": round(uso_score, 2),
                "bno_score": round(bno_score, 2),
                "roll_score": round(roll_score, 2),
            },
            confidence=confidence,
        )

    async def _check_etf(self, ticker: str, name: str) -> tuple:
        """Check an oil ETF for price action and volume signals."""
        signals = []
        score = 5.0

        try:
            import yfinance as yf

            etf = yf.Ticker(ticker)
            hist = etf.history(period="1mo")

            if hist.empty:
                signals.append(f"{ticker}: data unavailable")
                return score, signals

            current_price = float(hist["Close"].iloc[-1])
            current_vol = int(hist["Volume"].iloc[-1])

            # Average volume over the month
            avg_vol = hist["Volume"].mean()
            vol_ratio = current_vol / avg_vol if avg_vol > 0 else 1.0

            signals.append(f"{ticker} ({name}): ${current_price:.2f}")
            signals.append(f"{ticker} volume: {current_vol:,} (avg: {int(avg_vol):,}, ratio: {vol_ratio:.1f}x)")

            # Volume spike detection
            if vol_ratio > 3.0:
                signals.append(f"{ticker} MASSIVE volume spike ({vol_ratio:.1f}x avg) -- major institutional flow")
            elif vol_ratio > 2.0:
                signals.append(f"{ticker} high volume ({vol_ratio:.1f}x avg) -- institutional interest")
            elif vol_ratio < 0.3:
                signals.append(f"{ticker} very low volume -- no institutional interest")

            # Price momentum
            if len(hist) >= 5:
                week_ago = float(hist["Close"].iloc[-5])
                week_change = ((current_price - week_ago) / week_ago) * 100 if week_ago > 0 else 0

                if week_change > 5 and vol_ratio > 1.5:
                    score = 8.0
                    signals.append(f"{ticker} rallying on high volume ({week_change:+.1f}%) -- strong institutional buying")
                elif week_change > 3:
                    score = 7.0
                    signals.append(f"{ticker} up {week_change:+.1f}% on week -- bullish flows")
                elif week_change > 0:
                    score = 5.5
                elif week_change < -5 and vol_ratio > 1.5:
                    score = 2.0
                    signals.append(f"{ticker} selling off on high volume ({week_change:+.1f}%) -- institutional liquidation")
                elif week_change < -3:
                    score = 3.0
                    signals.append(f"{ticker} down {week_change:+.1f}% -- bearish flows")
                elif week_change < 0:
                    score = 4.5
                else:
                    score = 5.0

            # Volume-only signal (even without price movement)
            if vol_ratio > 2.5 and abs(score - 5.0) < 1:
                # High volume but flat price = consolidation before move
                score = 5.5
                signals.append(f"{ticker} high volume consolidation -- expect breakout")

        except ImportError:
            signals.append(f"{ticker}: yfinance not installed")
        except Exception as e:
            logger.warning(f"{ticker} check error: {e}")
            signals.append(f"{ticker}: error ({str(e)[:60]})")

        return score, signals

    def _check_roll_dates(self) -> tuple:
        """Check if we're near monthly futures roll dates.
        Front month expiry typically 3 business days before 25th of month.
        During roll, ETFs sell front month and buy deferred = selling pressure.
        """
        signals = []
        score = 5.0

        now = datetime.now(timezone.utc)
        day = now.day

        # Roll period is typically days 18-22 of each month
        # When ETFs roll from front to next month, they sell current = downward pressure
        if 18 <= day <= 22:
            score = 3.5
            signals.append(f"Monthly ETF roll period (day {day}) -- selling pressure on front month")
            signals.append("USO/BNO rolling contracts -- predictable selling pressure on near month")
        elif 15 <= day <= 17 or 23 <= day <= 25:
            score = 4.5
            signals.append(f"Near ETF roll window (day {day}) -- mild pressure expected")
        elif 1 <= day <= 5:
            score = 5.5
            signals.append("Post-roll period -- fresh positioning, slightly bullish")
        else:
            score = 5.0
            signals.append(f"Normal period (day {day}) -- no roll pressure")

        return score, signals
