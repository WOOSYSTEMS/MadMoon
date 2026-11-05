"""
MadEye Gold -- Currency Correlation Collector
EUR/USD, USD/JPY, BTC correlation with gold.
EUR rising = USD weak = bullish gold.
JPY strengthening = risk-off confirmation.
BTC falling while gold rising = safe haven shift confirmed.
Weight: 5% of total signal.
"""

import logging
from typing import Dict, List, Tuple

from .base import BaseCollector

logger = logging.getLogger("madeye.gold")


class CurrencyGoldCollector(BaseCollector):
    name = "currency_gold"
    category = "currency"
    cache_ttl = 600  # 10 minutes

    async def collect(self) -> Dict:
        signals = []
        subscores = []

        # --- 1. EUR/USD ---
        eur_score, eur_signals = await self._analyze_pair("EURUSD=X", "EUR/USD", inverse=False)
        subscores.append(("eurusd", eur_score, 0.35))
        signals.extend(eur_signals)

        # --- 2. USD/JPY ---
        jpy_score, jpy_signals = await self._analyze_pair("JPY=X", "USD/JPY", inverse=True)
        subscores.append(("usdjpy", jpy_score, 0.30))
        signals.extend(jpy_signals)

        # --- 3. BTC/USD ---
        btc_score, btc_signals = await self._analyze_btc_correlation()
        subscores.append(("btc", btc_score, 0.20))
        signals.extend(btc_signals)

        # --- 4. Cross-currency confirmation ---
        confirm_score, confirm_signals = self._cross_confirm(subscores)
        subscores.append(("confirm", confirm_score, 0.15))
        signals.extend(confirm_signals)

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
                "eurusd_score": round(eur_score, 2),
                "usdjpy_score": round(jpy_score, 2),
                "btc_score": round(btc_score, 2),
            },
            confidence=confidence,
        )

    async def _analyze_pair(self, symbol: str, label: str, inverse: bool = False) -> Tuple[float, List[str]]:
        """Analyze a currency pair's rate of change for gold signal."""
        signals = []
        score = 5.0

        try:
            import yfinance as yf
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="1mo")

            if hist.empty:
                return 5.0, [f"{label}: No data"]

            prices = hist["Close"].dropna().tolist()
            current = prices[-1]
            signals.append(f"{label}: {current:.4f}")

            self._set_cache(f"{symbol}_prices", prices[-30:])

            if len(prices) >= 6:
                roc_5 = (current - prices[-6]) / prices[-6] * 100

                # For EUR/USD: rising EUR = weak USD = bullish gold
                # For USD/JPY: falling = JPY strengthening = risk-off = bullish gold
                effective_roc = -roc_5 if inverse else roc_5

                if effective_roc > 1.0:
                    score = 8.5
                    if not inverse:
                        signals.append(f"{label} rising sharply ({roc_5:+.3f}%) -- USD weak, bullish gold")
                    else:
                        signals.append(f"{label} falling sharply ({roc_5:+.3f}%) -- risk-off, bullish gold")
                elif effective_roc > 0.3:
                    score = 7.0
                    signals.append(f"{label} trend supports gold ({roc_5:+.3f}%)")
                elif effective_roc < -1.0:
                    score = 2.0
                    if not inverse:
                        signals.append(f"{label} falling sharply ({roc_5:+.3f}%) -- USD strong, bearish gold")
                    else:
                        signals.append(f"{label} rising sharply ({roc_5:+.3f}%) -- risk-on, bearish gold")
                elif effective_roc < -0.3:
                    score = 3.5
                    signals.append(f"{label} trend headwind for gold ({roc_5:+.3f}%)")
                else:
                    score = 5.0

        except Exception as e:
            logger.warning(f"Currency {symbol} error: {e}")
            signals.append(f"{label} data unavailable")

        return score, signals

    async def _analyze_btc_correlation(self) -> Tuple[float, List[str]]:
        """BTC falling while gold rising = safe haven rotation confirmed."""
        signals = []
        score = 5.0

        try:
            import yfinance as yf

            btc = yf.Ticker("BTC-USD")
            btc_hist = btc.history(period="1mo")

            gold = yf.Ticker("GC=F")
            gold_hist = gold.history(period="1mo")

            if btc_hist.empty or gold_hist.empty:
                return 5.0, ["BTC/Gold correlation: insufficient data"]

            btc_prices = btc_hist["Close"].dropna().tolist()
            gold_prices = gold_hist["Close"].dropna().tolist()

            if len(btc_prices) >= 6 and len(gold_prices) >= 6:
                btc_roc = (btc_prices[-1] - btc_prices[-6]) / btc_prices[-6] * 100
                gold_roc = (gold_prices[-1] - gold_prices[-6]) / gold_prices[-6] * 100

                signals.append(f"BTC 5d: {btc_roc:+.2f}%, Gold 5d: {gold_roc:+.2f}%")

                self._set_cache("btc_gold_roc", {"btc": btc_roc, "gold": gold_roc})

                # BTC falling + Gold rising = classic safe haven rotation
                if btc_roc < -3 and gold_roc > 0:
                    score = 9.0
                    signals.append("BTC falling, Gold rising -- SAFE HAVEN ROTATION confirmed")
                elif btc_roc < 0 and gold_roc > 1:
                    score = 7.5
                    signals.append("BTC weak, Gold strong -- safe haven preference")
                elif btc_roc > 5 and gold_roc < 0:
                    score = 2.5
                    signals.append("BTC surging, Gold falling -- risk-on rotation away from gold")
                elif btc_roc > 3 and gold_roc > 3:
                    score = 6.0
                    signals.append("Both BTC and Gold rising -- inflation/debasement hedge")
                elif btc_roc < -3 and gold_roc < -3:
                    score = 3.5
                    signals.append("Both BTC and Gold falling -- USD strength, liquidity drain")
                else:
                    score = 5.0

        except Exception as e:
            logger.warning(f"BTC correlation error: {e}")
            signals.append("BTC/Gold correlation unavailable")

        return score, signals

    def _cross_confirm(self, subscores: list) -> Tuple[float, List[str]]:
        """Check if multiple currency signals confirm the same direction."""
        signals = []
        score = 5.0

        bullish_count = sum(1 for _, s, _ in subscores if s >= 6.5)
        bearish_count = sum(1 for _, s, _ in subscores if s <= 3.5)

        if bullish_count >= 2:
            score = 8.0
            signals.append(f"Currency cross-confirmation: {bullish_count}/3 bullish for gold")
        elif bearish_count >= 2:
            score = 2.0
            signals.append(f"Currency cross-confirmation: {bearish_count}/3 bearish for gold")
        elif bullish_count > 0 and bearish_count > 0:
            score = 5.0
            signals.append("Currency signals mixed -- no clear confirmation")
        else:
            score = 5.0

        return score, signals
