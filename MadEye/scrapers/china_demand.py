"""
MadEye Sniper Mode — Scraper 9: China Demand Signal Monitor
Tracks Chinese oil import and manufacturing signals via NewsAPI.
"""

import re
from typing import Dict
from .base_scraper import (
    fetch_newsapi, score_keywords, make_result, safe_run
)

NEWSAPI_QUERY = "China oil import OR China PMI OR China manufacturing"

KEYWORDS = [
    "china oil import", "china pmi", "china manufacturing",
    "china demand", "china refinery", "china crude", "china stockpile",
    "teapot refinery", "shandong", "strategic reserve",
    "china economic", "china gdp", "china stimulus",
    "china lockdown", "china slowdown", "china recovery",
]

# PMI thresholds: >51 bullish, <49 bearish for oil
# We look for PMI numbers in headlines


def extract_pmi(text: str) -> float:
    """Try to extract a PMI number from text."""
    patterns = [
        r'pmi\s*(?:at|of|to|hits?|rose?|fell?|drops?)?\s*(\d+\.?\d*)',
        r'(\d+\.?\d*)\s*pmi',
        r'pmi[^0-9]*(\d+\.?\d*)',
    ]
    for pat in patterns:
        m = re.search(pat, text.lower())
        if m:
            try:
                val = float(m.group(1))
                if 30 <= val <= 65:  # reasonable PMI range
                    return val
            except:
                pass
    return 0.0


def scrape() -> Dict:
    all_signals = []
    articles_scanned = 0
    pmi_values = []
    demand_bullish = 0
    demand_bearish = 0

    articles = fetch_newsapi(NEWSAPI_QUERY, ttl_seconds=1800, page_size=30)
    for art in articles:
        articles_scanned += 1
        text = f"{art.get('title', '')} {art.get('description', '')}".lower()

        # Check for PMI values
        pmi = extract_pmi(text)
        if pmi > 0:
            pmi_values.append(pmi)
            if pmi > 51:
                demand_bullish += 2
                all_signals.append(f"PMI {pmi} (BULLISH >51) — {art.get('title', '')[:60]}")
            elif pmi < 49:
                demand_bearish += 2
                all_signals.append(f"PMI {pmi} (BEARISH <49) — {art.get('title', '')[:60]}")
            else:
                all_signals.append(f"PMI {pmi} (NEUTRAL) — {art.get('title', '')[:60]}")

        # Keyword sentiment
        bullish_words = ["import surge", "record import", "demand recovery", "stockpile", "strategic reserve", "stimulus", "growth"]
        bearish_words = ["slowdown", "lockdown", "weak demand", "decline", "contraction", "recession"]

        for w in bullish_words:
            if w in text:
                demand_bullish += 1
                all_signals.append(f"BULLISH: {w} — {art.get('title', '')[:60]}")
                break
        for w in bearish_words:
            if w in text:
                demand_bearish += 1
                all_signals.append(f"BEARISH: {w} — {art.get('title', '')[:60]}")
                break

    # For sniper mode: high China demand = bullish oil (supports long)
    # Low demand = bearish (no sniper buy)
    net = demand_bullish - demand_bearish

    if net >= 8:
        score = 9
    elif net >= 5:
        score = 7
    elif net >= 3:
        score = 5
    elif net >= 1:
        score = 3
    elif net == 0:
        score = 1
    else:
        score = 0  # net bearish = no buy signal

    confidence = min(1.0, articles_scanned / 20) if articles_scanned > 0 else 0.1

    result = make_result(score, confidence, all_signals[:20], "china_demand")
    result["articles_scanned"] = articles_scanned
    result["demand_bullish"] = demand_bullish
    result["demand_bearish"] = demand_bearish
    result["net_signal"] = net
    result["pmi_values"] = pmi_values
    return result


def run() -> Dict:
    return safe_run("china_demand", scrape)


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2))
