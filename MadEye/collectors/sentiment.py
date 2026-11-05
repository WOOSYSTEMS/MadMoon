"""
MadEye Sentiment Collector
Google Trends for oil keywords, OVX volatility, CFTC COT positioning, GDELT tone.
Scores sentiment 0-10.
"""

import csv
import io
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .base import BaseCollector

logger = logging.getLogger("madeye")

OVX_CSV_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/OVX_History.csv"
FRED_OVX = "https://api.stlouisfed.org/fred/series/observations"
CFTC_API = "https://publicreporting.cftc.gov/resource/jun7-fc8e.json"
NEWSAPI_BASE = "https://newsapi.org/v2/everything"

def _load_newsapi_key():
    """Load NewsAPI key from data file or environment."""
    import os
    key_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "newsapi_key.txt")
    if os.path.exists(key_path):
        with open(key_path) as f:
            return f.read().strip()
    return os.environ.get("NEWSAPI_KEY", "")


class SentimentCollector(BaseCollector):
    name = "sentiment"
    category = "sentiment"
    cache_ttl = 1800  # 30 minutes

    def __init__(self, fred_key: str = None, newsapi_key: str = None):
        super().__init__()
        self.fred_key = fred_key or "DEMO_KEY"
        self.newsapi_key = newsapi_key or _load_newsapi_key()

    async def collect(self) -> Dict:
        signals = []
        subscores = []

        # --- 1. OVX (Oil Volatility Index) ---
        ovx_score, ovx_signals = await self._check_ovx()
        subscores.append(ovx_score)
        signals.extend(ovx_signals)

        # --- 2. GDELT News Sentiment/Tone ---
        tone_score, tone_signals = await self._check_gdelt_tone()
        subscores.append(tone_score)
        signals.extend(tone_signals)

        # --- 3. CFTC COT Positioning ---
        cot_score, cot_signals = await self._check_cot()
        subscores.append(cot_score)
        signals.extend(cot_signals)

        # --- 4. News Volume (attention indicator) ---
        vol_score, vol_signals = await self._check_news_volume()
        subscores.append(vol_score)
        signals.extend(vol_signals)

        # --- 5. Short Squeeze Detection ---
        squeeze_score, squeeze_signals = await self._check_short_squeeze()
        subscores.append(squeeze_score)
        signals.extend(squeeze_signals)

        # Weighted: OVX 25%, GDELT tone 20%, COT 25%, News volume 10%, Short squeeze 20%
        weights = [0.25, 0.20, 0.25, 0.10, 0.20]
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
                "ovx_score": round(ovx_score, 2),
                "tone_score": round(tone_score, 2),
                "cot_score": round(cot_score, 2),
                "news_volume_score": round(vol_score, 2),
                "short_squeeze_score": round(squeeze_score, 2),
            },
            confidence=confidence,
        )

    async def _check_ovx(self) -> tuple:
        """Check CBOE Oil Volatility Index (fear gauge) via Yahoo ^OVX, CBOE CSV, or FRED."""
        signals = []
        score = 5.0

        # Primary: Yahoo Finance ^OVX
        try:
            import yfinance as yf
            ovx_ticker = yf.Ticker("^OVX")
            ovx_hist = ovx_ticker.history(period="1mo")
            if not ovx_hist.empty:
                ovx_close = float(ovx_hist["Close"].iloc[-1])
                if ovx_close > 0:
                    signals.append(f"OVX (Yahoo): {ovx_close:.1f}")

                    if ovx_close > 60:
                        score = 7.5
                        signals.append("OVX extreme fear -- contrarian bullish")
                    elif ovx_close > 45:
                        score = 6.0
                        signals.append("OVX elevated -- high uncertainty")
                    elif ovx_close > 30:
                        score = 5.0
                        signals.append("OVX moderate")
                    elif ovx_close > 20:
                        score = 4.0
                        signals.append("OVX low -- complacency risk")
                    else:
                        score = 3.0
                        signals.append("OVX very low -- surprise move risk")

                    # Trend check
                    if len(ovx_hist) >= 6:
                        prev_close = float(ovx_hist["Close"].iloc[-6])
                        if prev_close > 0:
                            change = ((ovx_close - prev_close) / prev_close) * 100
                            if change > 20:
                                score = min(10, score + 1.5)
                                signals.append(f"OVX spiking ({change:+.0f}% week)")
                            elif change < -20:
                                score = max(0, score - 1.0)
                                signals.append(f"OVX declining ({change:+.0f}% week)")

                    return score, signals
        except Exception as e:
            logger.warning(f"Yahoo OVX fetch error: {e}")

        # Fallback: Try direct CBOE CSV
        csv_text = await self.fetch_csv(OVX_CSV_URL, cache_key="ovx_csv")
        if csv_text:
            try:
                reader = csv.DictReader(io.StringIO(csv_text))
                rows = list(reader)
                if rows:
                    # Last row is most recent
                    latest_row = rows[-1]
                    ovx_close = float(latest_row.get("CLOSE", latest_row.get("Close", 0)))

                    if ovx_close > 0:
                        signals.append(f"OVX: {ovx_close:.1f}")

                        # OVX interpretation:
                        # >50 = extreme fear, potential contrarian bullish
                        # 30-50 = elevated risk
                        # <25 = complacency, potential surprise coming
                        if ovx_close > 60:
                            score = 7.5  # Extreme fear = contrarian bullish
                            signals.append("OVX extreme fear -- contrarian bullish")
                        elif ovx_close > 45:
                            score = 6.0
                            signals.append("OVX elevated -- high uncertainty")
                        elif ovx_close > 30:
                            score = 5.0
                            signals.append("OVX moderate")
                        elif ovx_close > 20:
                            score = 4.0
                            signals.append("OVX low -- complacency risk")
                        else:
                            score = 3.0
                            signals.append("OVX very low -- surprise move risk")

                        # Trend check
                        if len(rows) >= 6:
                            prev_close = float(rows[-6].get("CLOSE", rows[-6].get("Close", 0)))
                            if prev_close > 0:
                                change = ((ovx_close - prev_close) / prev_close) * 100
                                if change > 20:
                                    score = min(10, score + 1.5)
                                    signals.append(f"OVX spiking ({change:+.0f}% week)")
                                elif change < -20:
                                    score = max(0, score - 1.0)
                                    signals.append(f"OVX declining ({change:+.0f}% week)")

                        return score, signals
            except Exception as e:
                logger.warning(f"OVX CSV parse error: {e}")

        # Fallback: FRED
        data = await self.fetch_json(
            FRED_OVX,
            params={
                "series_id": "OVXCLS",
                "api_key": self.fred_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": "10",
            },
            cache_key="fred_ovx",
        )
        if data and "observations" in data:
            for obs in data["observations"]:
                v = obs.get("value", ".")
                if v != ".":
                    ovx_val = float(v)
                    signals.append(f"OVX (FRED): {ovx_val:.1f}")
                    if ovx_val > 50:
                        score = 7.0
                    elif ovx_val > 30:
                        score = 5.0
                    elif ovx_val < 20:
                        score = 3.0
                    break

        if not signals:
            signals.append("OVX: data unavailable")

        return score, signals

    async def _check_gdelt_tone(self) -> tuple:
        """Check GDELT news tone for crude oil coverage."""
        signals = []
        score = 5.0

        url = "https://api.gdeltproject.org/api/v2/doc/doc"
        params = {
            "query": "crude+oil+OR+brent+crude+OR+oil+price",
            "mode": "tonechart",
            "format": "json",
        }

        data = await self.fetch_json(url, params=params, cache_key="gdelt_tone")
        if not data:
            signals.append("GDELT tone: unavailable")
            return score, signals

        try:
            # tonechart returns daily tone values
            if isinstance(data, list) and data:
                recent_tones = []
                for item in data[-7:]:  # Last 7 entries
                    tone = item.get("tone", item.get("value", None))
                    if tone is not None:
                        recent_tones.append(float(tone))

                if recent_tones:
                    avg_tone = sum(recent_tones) / len(recent_tones)
                    signals.append(f"GDELT oil news tone (7d avg): {avg_tone:.2f}")

                    # Negative tone = bearish sentiment in media = often contrarian bullish
                    # Positive tone = optimistic media
                    if avg_tone < -5:
                        score = 7.0  # Very negative media = contrarian bullish
                        signals.append("Very negative media tone -- contrarian bullish")
                    elif avg_tone < -2:
                        score = 6.0
                        signals.append("Negative media tone")
                    elif avg_tone > 5:
                        score = 3.0
                        signals.append("Very positive media tone -- contrarian bearish")
                    elif avg_tone > 2:
                        score = 4.0
                    else:
                        score = 5.0
            elif isinstance(data, dict):
                # Handle dict format
                tone = data.get("tone", data.get("avg_tone"))
                if tone is not None:
                    signals.append(f"GDELT tone: {float(tone):.2f}")
                else:
                    signals.append("GDELT tone: unexpected format")
            else:
                signals.append("GDELT tone: empty response")

        except Exception as e:
            logger.warning(f"GDELT tone parse error: {e}")
            signals.append(f"GDELT tone: parse error")

        return score, signals

    async def _check_cot(self) -> tuple:
        """Check CFTC Commitments of Traders positioning."""
        signals = []
        score = 5.0

        # CFTC Socrata API for COT data
        # Filter for crude oil (commodity code 067651)
        params = {
            "$where": "commodity_name like '%CRUDE OIL%'",
            "$order": "report_date_as_yyyy_mm_dd DESC",
            "$limit": "5",
        }

        data = await self.fetch_json(CFTC_API, params=params, cache_key="cftc_cot")
        if not data or not isinstance(data, list) or len(data) == 0:
            signals.append("CFTC COT: data unavailable")
            return score, signals

        try:
            latest = data[0]

            # Managed money (speculative) positioning
            mm_long = int(latest.get("m_money_positions_long_all", 0))
            mm_short = int(latest.get("m_money_positions_short_all", 0))
            mm_net = mm_long - mm_short

            # Commercial (hedger) positioning
            comm_long = int(latest.get("comm_positions_long_all", 0))
            comm_short = int(latest.get("comm_positions_short_all", 0))
            comm_net = comm_long - comm_short

            signals.append(f"Managed money net: {mm_net:+,} contracts")
            signals.append(f"Commercial net: {comm_net:+,} contracts")

            # Extreme positioning = contrarian signal
            if mm_net > 300000:
                score = 3.0  # Crowded long = reversal risk
                signals.append("Extreme speculative long -- crowded trade, bearish risk")
            elif mm_net > 200000:
                score = 4.0
                signals.append("High speculative longs")
            elif mm_net < 50000:
                score = 8.0  # Very few specs long = short-covering rally risk
                signals.append("Low speculative longs -- short-covering rally potential")
            elif mm_net < 100000:
                score = 7.0
                signals.append("Below-average speculative longs -- room to add")
            else:
                score = 5.5  # Normal positioning

            # Week-over-week change
            if len(data) >= 2:
                prev = data[1]
                prev_mm_long = int(prev.get("m_money_positions_long_all", 0))
                prev_mm_short = int(prev.get("m_money_positions_short_all", 0))
                prev_mm_net = prev_mm_long - prev_mm_short
                net_change = mm_net - prev_mm_net

                if net_change > 30000:
                    score = min(10, score + 1.0)
                    signals.append(f"Specs adding longs aggressively ({net_change:+,})")
                elif net_change < -30000:
                    score = max(0, score - 1.0)
                    signals.append(f"Specs reducing longs ({net_change:+,})")

        except (ValueError, TypeError, KeyError) as e:
            logger.warning(f"COT parse error: {e}")
            signals.append(f"COT: parse error ({str(e)[:50]})")

        return score, signals

    async def _check_news_volume(self) -> tuple:
        """Check oil news headline sentiment via NewsAPI and GDELT volume."""
        signals = []
        score = 5.0

        # Primary: NewsAPI headline sentiment
        if self.newsapi_key:
            params = {
                "q": "oil price OR crude oil OR brent crude",
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": "50",
                "apiKey": self.newsapi_key,
            }
            data = await self.fetch_json(
                NEWSAPI_BASE, params=params, cache_key="newsapi_sentiment"
            )
            if data and data.get("status") == "ok":
                articles = data.get("articles", [])
                total = len(articles)

                positive = 0
                negative = 0
                for art in articles:
                    title = (art.get("title", "") or "").lower()
                    desc = (art.get("description", "") or "").lower()
                    text = title + " " + desc

                    # Positive oil sentiment (bullish)
                    for kw in ["surge", "rally", "rise", "gain", "higher", "demand strong",
                                "supply tight", "disruption", "shortage", "cut"]:
                        if kw in text:
                            positive += 1
                            break
                    # Negative oil sentiment (bearish)
                    for kw in ["drop", "fall", "plunge", "crash", "decline", "surplus",
                                "oversupply", "demand weak", "recession", "glut"]:
                        if kw in text:
                            negative += 1
                            break

                signals.append(f"NewsAPI sentiment: {total} articles, {positive} bullish, {negative} bearish")

                if total > 0:
                    bull_pct = positive / total
                    bear_pct = negative / total
                    if bull_pct > 0.4 and bull_pct > bear_pct * 2:
                        score = 7.0
                        signals.append("Headlines strongly bullish")
                    elif bull_pct > bear_pct:
                        score = 6.0
                        signals.append("Headlines lean bullish")
                    elif bear_pct > 0.4 and bear_pct > bull_pct * 2:
                        score = 3.0
                        signals.append("Headlines strongly bearish")
                    elif bear_pct > bull_pct:
                        score = 4.0
                        signals.append("Headlines lean bearish")
                    else:
                        score = 5.0
                        signals.append("Headlines neutral/mixed")

                    # High volume = something happening
                    if total >= 40:
                        score = min(10, score + 0.5)
                        signals.append("Very high oil news volume")

                return score, signals

        # Fallback: GDELT volume
        url = "https://api.gdeltproject.org/api/v2/doc/doc"
        params = {
            "query": "oil+price+OR+crude+oil+OR+brent",
            "mode": "artlist",
            "maxrecords": "250",
            "format": "json",
            "timespan": "24h",
        }

        data = await self.fetch_json(url, params=params, cache_key="gdelt_volume_24h")
        if not data:
            signals.append("News volume check: unavailable")
            return score, signals

        articles = data.get("articles", [])
        count = len(articles)
        signals.append(f"Oil news volume (24h GDELT): {count} articles")

        if count > 200:
            score = 6.5
            signals.append("Very high news volume -- market-moving events likely")
        elif count > 100:
            score = 6.0
            signals.append("Above-average news coverage")
        elif count < 20:
            score = 4.0
            signals.append("Very low news coverage -- quiet market")

        return score, signals

    async def _check_short_squeeze(self) -> tuple:
        """Detect short squeeze potential.
        When COT shows extreme shorts + price is rising = squeeze potential.
        Extreme positioning + price moving against it = contrarian explosive move.
        """
        signals = []
        score = 5.0

        # Get COT data for positioning
        params = {
            "$where": "commodity_name like '%CRUDE OIL%'",
            "$order": "report_date_as_yyyy_mm_dd DESC",
            "$limit": "5",
        }

        cot_data = await self.fetch_json(CFTC_API, params=params, cache_key="cftc_cot_squeeze")

        if not cot_data or not isinstance(cot_data, list) or len(cot_data) < 2:
            signals.append("Short squeeze check: COT data unavailable")
            return score, signals

        try:
            latest = cot_data[0]
            prev = cot_data[1]

            mm_long = int(latest.get("m_money_positions_long_all", 0))
            mm_short = int(latest.get("m_money_positions_short_all", 0))
            mm_net = mm_long - mm_short

            prev_mm_long = int(prev.get("m_money_positions_long_all", 0))
            prev_mm_short = int(prev.get("m_money_positions_short_all", 0))
            prev_mm_net = prev_mm_long - prev_mm_short

            net_change = mm_net - prev_mm_net

            # Check if price is rising (from Yahoo Finance)
            price_rising = False
            price_change_pct = 0.0
            try:
                import yfinance as yf
                brent = yf.Ticker("BZ=F")
                hist = brent.history(period="5d")
                if len(hist) >= 2:
                    current_price = float(hist["Close"].iloc[-1])
                    prev_price = float(hist["Close"].iloc[0])
                    price_change_pct = ((current_price - prev_price) / prev_price) * 100
                    price_rising = price_change_pct > 1.0
            except Exception:
                pass

            # SHORT SQUEEZE CONDITIONS:
            # 1. High short interest (low net long or negative net)
            # 2. Price rising against shorts
            # 3. Shorts being covered (net change positive while previously very short)

            short_ratio = mm_short / max(mm_long, 1)

            if mm_net < 50000 and price_rising:
                # Extreme short positioning + price rising = SQUEEZE
                score = 9.0
                signals.append(f"SHORT SQUEEZE ALERT: Net={mm_net:+,}, price up {price_change_pct:+.1f}%")
                signals.append("Extreme short positioning being squeezed -- very bullish explosion potential")
            elif mm_net < 100000 and price_rising and net_change > 20000:
                # Shorts covering rapidly
                score = 8.0
                signals.append(f"Short covering detected: Net change {net_change:+,}, price rising")
                signals.append("Active short covering -- bullish momentum")
            elif mm_net < 100000 and price_rising:
                score = 7.0
                signals.append(f"Low longs ({mm_net:+,}) + price rising -- squeeze building")
            elif mm_net > 300000 and not price_rising:
                # Crowded long + price not going up = long squeeze risk
                score = 2.5
                signals.append(f"LONG SQUEEZE RISK: Net={mm_net:+,}, price stalling/falling")
                signals.append("Crowded longs may liquidate -- bearish risk")
            elif mm_net > 250000 and price_change_pct < -1:
                score = 3.0
                signals.append(f"Longs liquidating: Net={mm_net:+,}, price down {price_change_pct:+.1f}%")
            elif short_ratio > 0.8:
                score = 6.5
                signals.append(f"Short ratio elevated ({short_ratio:.2f}) -- squeeze potential if price rises")
            else:
                score = 5.0
                signals.append(f"Positioning normal: net={mm_net:+,}, short ratio={short_ratio:.2f}")

        except (ValueError, TypeError, KeyError) as e:
            logger.warning(f"Short squeeze check error: {e}")
            signals.append(f"Short squeeze: parse error ({str(e)[:50]})")

        return score, signals
