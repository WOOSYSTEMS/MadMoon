"""
MadEye Oil Spreads Collector
Brent-WTI spread, futures curve (contango/backwardation), time spreads.
Backwardation = bullish (tight supply now), Contango = bearish (oversupply).
"""

import logging
from typing import Dict

from .base import BaseCollector

logger = logging.getLogger("madeye")


class SpreadsCollector(BaseCollector):
    name = "spreads"
    category = "spreads"
    cache_ttl = 1800  # 30 minutes

    async def collect(self) -> Dict:
        signals = []
        subscores = []

        # --- 1. Brent-WTI spread ---
        bw_score, bw_signals = await self._check_brent_wti()
        subscores.append(bw_score)
        signals.extend(bw_signals)

        # --- 2. Futures curve structure ---
        curve_score, curve_signals = await self._check_curve_structure()
        subscores.append(curve_score)
        signals.extend(curve_signals)

        # --- 3. Calendar spreads ---
        cal_score, cal_signals = await self._check_calendar_spread()
        subscores.append(cal_score)
        signals.extend(cal_signals)

        # Weighted: Brent-WTI 25%, Curve structure 45%, Calendar 30%
        weights = [0.25, 0.45, 0.30]
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
                "brent_wti_score": round(bw_score, 2),
                "curve_score": round(curve_score, 2),
                "calendar_score": round(cal_score, 2),
            },
            confidence=confidence,
        )

    async def _check_brent_wti(self) -> tuple:
        """Check Brent-WTI spread for Atlantic basin tightness."""
        signals = []
        score = 5.0

        try:
            import yfinance as yf

            brent = yf.Ticker("BZ=F")
            wti = yf.Ticker("CL=F")

            brent_hist = brent.history(period="1mo")
            wti_hist = wti.history(period="1mo")

            if brent_hist.empty or wti_hist.empty:
                signals.append("Brent-WTI spread: data unavailable")
                return score, signals

            brent_price = float(brent_hist["Close"].iloc[-1])
            wti_price = float(wti_hist["Close"].iloc[-1])
            spread = brent_price - wti_price

            signals.append(f"Brent: ${brent_price:.2f} | WTI: ${wti_price:.2f} | Spread: ${spread:.2f}")

            # Normal spread: $2-5
            # Wide > $8 = European tightness = bullish
            # Negative = unusual
            if spread > 10:
                score = 8.5
                signals.append("Brent-WTI very wide (>$10) -- severe Atlantic basin tightness (very bullish)")
            elif spread > 8:
                score = 7.5
                signals.append("Brent-WTI wide (>$8) -- European supply tightness (bullish)")
            elif spread > 5:
                score = 6.5
                signals.append("Brent-WTI above normal ($5-8) -- moderate tightness")
            elif spread > 2:
                score = 5.0
                signals.append("Brent-WTI normal range ($2-5)")
            elif spread > 0:
                score = 4.0
                signals.append("Brent-WTI narrow (<$2) -- ample supply")
            else:
                score = 3.0
                signals.append("Brent-WTI inverted -- unusual, US tightness or Brent weakness")

            # Trend
            if len(brent_hist) >= 5 and len(wti_hist) >= 5:
                prev_brent = float(brent_hist["Close"].iloc[-5])
                prev_wti = float(wti_hist["Close"].iloc[-5])
                prev_spread = prev_brent - prev_wti
                change = spread - prev_spread

                if change > 2:
                    score = min(10, score + 1.0)
                    signals.append(f"Brent-WTI widening ({change:+.2f}) -- tightening")
                elif change < -2:
                    score = max(0, score - 1.0)
                    signals.append(f"Brent-WTI narrowing ({change:+.2f}) -- easing")

        except ImportError:
            signals.append("Brent-WTI: yfinance not installed")
        except Exception as e:
            logger.warning(f"Brent-WTI spread error: {e}")
            signals.append(f"Brent-WTI: error ({str(e)[:60]})")

        return score, signals

    async def _check_curve_structure(self) -> tuple:
        """Check futures curve: front month vs 6-month vs 12-month."""
        signals = []
        score = 5.0

        try:
            import yfinance as yf

            # Front month Brent
            front = yf.Ticker("BZ=F")
            front_hist = front.history(period="5d")

            if front_hist.empty:
                signals.append("Futures curve: no front month data")
                return score, signals

            front_price = float(front_hist["Close"].iloc[-1])

            # Try to get deferred months via WTI calendar contracts
            # CL=F is front month, CLZ24, CLH25 etc are deferred
            # Use multiple tickers for curve estimation
            wti_front = yf.Ticker("CL=F")
            wti_hist = wti_front.history(period="5d")

            if wti_hist.empty:
                signals.append("Futures curve: no WTI data for curve")
                return score, signals

            wti_price = float(wti_hist["Close"].iloc[-1])
            signals.append(f"Front month Brent: ${front_price:.2f} | WTI: ${wti_price:.2f}")

            # Use 5-day price trend as proxy for curve shape
            # Rising prices = market in backwardation mode (demand > supply)
            # Falling prices = contango mode (oversupply)
            if len(front_hist) >= 5:
                price_5d_ago = float(front_hist["Close"].iloc[0])
                change_pct = ((front_price - price_5d_ago) / price_5d_ago) * 100

                if change_pct > 3:
                    score = 7.5
                    signals.append(f"Strong backwardation signal -- prices rising {change_pct:+.1f}% in 5d")
                    signals.append("Backwardation = immediate demand > supply (bullish)")
                elif change_pct > 1:
                    score = 6.5
                    signals.append(f"Mild backwardation signal -- prices up {change_pct:+.1f}%")
                elif change_pct < -3:
                    score = 2.5
                    signals.append(f"Contango signal -- prices falling {change_pct:+.1f}% in 5d")
                    signals.append("Contango = oversupply / weak demand (bearish)")
                elif change_pct < -1:
                    score = 3.5
                    signals.append(f"Mild contango signal -- prices down {change_pct:+.1f}%")
                else:
                    score = 5.0
                    signals.append("Futures curve: flat/neutral")

        except ImportError:
            signals.append("Futures curve: yfinance not installed")
        except Exception as e:
            logger.warning(f"Futures curve error: {e}")
            signals.append(f"Futures curve: error ({str(e)[:60]})")

        return score, signals

    async def _check_calendar_spread(self) -> tuple:
        """Check front-to-back calendar spread via price momentum."""
        signals = []
        score = 5.0

        try:
            import yfinance as yf

            brent = yf.Ticker("BZ=F")
            hist = brent.history(period="1mo")

            if hist.empty or len(hist) < 10:
                signals.append("Calendar spread proxy: insufficient data")
                return score, signals

            # Use 1-week vs 1-month momentum as proxy for time spread
            current = float(hist["Close"].iloc[-1])
            week_ago = float(hist["Close"].iloc[-5]) if len(hist) >= 5 else current
            month_ago = float(hist["Close"].iloc[0])

            week_mom = ((current - week_ago) / week_ago) * 100 if week_ago > 0 else 0
            month_mom = ((current - month_ago) / month_ago) * 100 if month_ago > 0 else 0

            signals.append(f"Brent 1W momentum: {week_mom:+.2f}% | 1M momentum: {month_mom:+.2f}%")

            # Short-term momentum > long-term = backwardation (demand now)
            if week_mom > 0 and week_mom > month_mom:
                score = 7.0
                signals.append("Short-term momentum accelerating -- backwardation signal (bullish)")
            elif week_mom > 0:
                score = 6.0
                signals.append("Positive short-term momentum")
            elif week_mom < 0 and week_mom < month_mom:
                score = 3.0
                signals.append("Short-term momentum decelerating -- contango signal (bearish)")
            elif week_mom < 0:
                score = 4.0
                signals.append("Negative short-term momentum")
            else:
                score = 5.0

        except ImportError:
            signals.append("Calendar spread: yfinance not installed")
        except Exception as e:
            logger.warning(f"Calendar spread error: {e}")
            signals.append(f"Calendar spread: error ({str(e)[:60]})")

        return score, signals
