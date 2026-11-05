"""
MadEye Sniper Mode — Scraper 11: EIA Inventory Pre-Release Monitor
Uses EIA API for weekly inventory data + NewsAPI for consensus/surprise signals.
API inventory (Tuesday evening) comes BEFORE EIA report (Wednesday morning).
"""

import json as json_mod
from datetime import datetime, timezone, timedelta
from typing import Dict
from .base_scraper import (
    fetch, fetch_newsapi, score_keywords, make_result, safe_run, DATA_DIR
)
import os

EIA_API_KEY = "hFz7MGqCdj6hbhRTNpLRgGNK7pGbqbkC87JjWgtP"

# EIA API series for weekly crude inventory
# WCESTUS1 = weekly ending stocks of crude oil
EIA_INVENTORY_URL = f"https://api.eia.gov/v2/petroleum/stoc/wstk/data/?api_key={EIA_API_KEY}&frequency=weekly&data[0]=value&facets[product][]=EPC0&facets[duoarea][]=NUS&sort[0][column]=period&sort[0][direction]=desc&length=5"

NEWSAPI_QUERIES = [
    "EIA inventory OR crude stockpile",
    "API inventory crude oil",
]

KEYWORDS = [
    "draw", "build", "surprise", "unexpected", "consensus",
    "inventory", "stockpile", "crude stocks", "million barrels",
    "larger than expected", "smaller than expected", "bullish",
    "bearish", "supply tightening", "oversupply",
]

HIGH_WEIGHT = {
    "surprise": 3.0,
    "unexpected": 3.0,
    "larger than expected": 3.0,
    "smaller than expected": 3.0,
    "supply tightening": 2.5,
}

HISTORY_FILE = os.path.join(DATA_DIR, "eia_history.json")


def load_history() -> list:
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f:
                return json_mod.load(f)
        except:
            pass
    return []


def save_history(history: list):
    try:
        with open(HISTORY_FILE, "w") as f:
            json_mod.dump(history[-52:], f, indent=2)  # keep 1 year
    except:
        pass


def fetch_eia_inventory() -> tuple:
    """Fetch latest EIA inventory data. Returns (latest_value, change, signals)."""
    signals = []
    raw = fetch(EIA_INVENTORY_URL, ttl_seconds=1800)
    if not raw:
        return None, None, ["eia_api: UNREACHABLE"]

    try:
        data = json_mod.loads(raw)
        records = data.get("response", {}).get("data", [])
        if len(records) < 2:
            return None, None, ["eia_api: insufficient data"]

        latest = float(records[0].get("value", 0))
        previous = float(records[1].get("value", 0))
        change = latest - previous
        period = records[0].get("period", "")

        # Save to history
        history = load_history()
        if not history or history[-1].get("period") != period:
            history.append({"period": period, "value": latest, "change": change})
            save_history(history)

        if change < -5:  # >5M barrel draw = very bullish
            signals.append(f"EIA: MAJOR DRAW {change:.1f}M barrels (period {period})")
        elif change < -2:
            signals.append(f"EIA: Draw {change:.1f}M barrels (period {period})")
        elif change > 5:
            signals.append(f"EIA: MAJOR BUILD +{change:.1f}M barrels (period {period})")
        elif change > 2:
            signals.append(f"EIA: Build +{change:.1f}M barrels (period {period})")
        else:
            signals.append(f"EIA: Flat {change:+.1f}M barrels (period {period})")

        return latest, change, signals

    except Exception as e:
        return None, None, [f"eia_api: parse error — {str(e)[:50]}"]


def scrape() -> Dict:
    all_signals = []
    total_score_points = 0
    articles_scanned = 0

    # EIA API data
    latest_val, change, eia_signals = fetch_eia_inventory()
    all_signals.extend(eia_signals)

    # Score EIA change (draws are bullish for oil = good for sniper long)
    if change is not None:
        if change < -8:
            total_score_points += 8  # massive draw
        elif change < -5:
            total_score_points += 6
        elif change < -2:
            total_score_points += 3
        elif change > 5:
            total_score_points -= 2  # big build = bearish
        elif change > 2:
            total_score_points -= 1

    # NewsAPI for consensus/surprise
    for query in NEWSAPI_QUERIES:
        articles = fetch_newsapi(query, ttl_seconds=1800)
        for art in articles:
            articles_scanned += 1
            text = f"{art.get('title', '')} {art.get('description', '')}".lower()
            hits, matched = score_keywords(text, KEYWORDS, HIGH_WEIGHT)
            if hits > 0:
                # Check if surprise is bullish (draw > expected) or bearish
                is_draw = any(w in text for w in ["draw", "decline", "fell", "drop"])
                is_surprise = any(w in text for w in ["surprise", "unexpected", "larger than", "smaller than"])
                if is_draw and is_surprise:
                    total_score_points += 3
                    all_signals.append(f"SURPRISE DRAW — {art.get('title', '')[:60]}")
                elif is_surprise:
                    total_score_points += 1
                    for kw in matched:
                        all_signals.append(f"newsapi: {kw} — {art.get('title', '')[:60]}")

    # Check if it's near EIA release time (Tuesday evening / Wednesday morning)
    now = datetime.now(timezone.utc)
    weekday = now.weekday()  # 0=Mon, 1=Tue, 2=Wed
    if weekday == 1 and now.hour >= 20:  # Tuesday evening (API release)
        total_score_points += 1
        all_signals.append("TIMING: API inventory release window (Tuesday evening)")
    elif weekday == 2 and now.hour < 15:  # Wednesday before EIA
        total_score_points += 1
        all_signals.append("TIMING: EIA report day (Wednesday)")

    if total_score_points >= 10:
        score = 10
    elif total_score_points >= 7:
        score = 8
    elif total_score_points >= 5:
        score = 6
    elif total_score_points >= 3:
        score = 4
    elif total_score_points >= 1:
        score = 2
    else:
        score = 0

    confidence = 0.5
    if latest_val is not None:
        confidence += 0.3
    if articles_scanned > 5:
        confidence += 0.2
    confidence = min(1.0, confidence)

    result = make_result(score, confidence, all_signals[:20], "eia_prerelease")
    result["articles_scanned"] = articles_scanned
    result["latest_inventory_mb"] = latest_val
    result["inventory_change_mb"] = change
    return result


def run() -> Dict:
    return safe_run("eia_prerelease", scrape)


if __name__ == "__main__":
    print(json_mod.dumps(run(), indent=2))
