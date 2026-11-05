"""
MadEye Sniper Mode — Scraper 6: Oil Twitter/X Proxy Monitor
Uses NewsAPI as proxy for oil trading sentiment (X API too expensive).
"""

from typing import Dict
from .base_scraper import (
    fetch_newsapi, score_keywords, make_result, safe_run
)

QUERIES = [
    "oil trader OR crude oil alert OR brent crude breaking",
    "oil price surge OR oil supply shock OR crude spike",
]

BEARISH_SUPPLY = [
    "supply disruption", "pipeline shut", "export halt", "force majeure",
    "attack", "explosion", "fire", "sanctions", "embargo", "blockade",
    "production cut", "shut-in", "outage", "evacuation", "damage",
    "shortage", "deficit", "tightening", "squeeze", "risk premium",
]

BULLISH_DEMAND = [
    "demand surge", "recovery", "growth", "stockpile draw", "deficit",
    "economic growth", "manufacturing", "pmi", "refinery run",
]

BEARISH_DEMAND = [
    "demand destruction", "recession", "slowdown", "surplus", "glut",
    "oversupply", "build", "stockpile build", "weak demand",
]


def scrape() -> Dict:
    all_signals = []
    supply_negative = 0
    demand_positive = 0
    demand_negative = 0
    articles_scanned = 0

    for query in QUERIES:
        articles = fetch_newsapi(query, ttl_seconds=900, page_size=30)
        for art in articles:
            articles_scanned += 1
            text = f"{art.get('title', '')} {art.get('description', '')}".lower()

            # Count supply-negative headlines (bullish for oil price)
            for kw in BEARISH_SUPPLY:
                if kw in text:
                    supply_negative += 1
                    all_signals.append(f"SUPPLY_RISK: {kw} — {art.get('title', '')[:60]}")
                    break

            # Count demand signals
            for kw in BULLISH_DEMAND:
                if kw in text:
                    demand_positive += 1
                    break
            for kw in BEARISH_DEMAND:
                if kw in text:
                    demand_negative += 1
                    break

    # Score: supply disruption signals are what matter for sniper
    # supply_negative >= 5 means lots of disruption talk
    net_bullish = supply_negative + demand_positive - demand_negative

    if net_bullish >= 10:
        score = 10
    elif net_bullish >= 7:
        score = 8
    elif net_bullish >= 5:
        score = 6
    elif net_bullish >= 3:
        score = 4
    elif net_bullish >= 1:
        score = 2
    else:
        score = 0

    confidence = min(1.0, articles_scanned / 30) if articles_scanned > 0 else 0.1

    result = make_result(score, confidence, all_signals[:20], "oil_twitter")
    result["articles_scanned"] = articles_scanned
    result["supply_negative_count"] = supply_negative
    result["demand_positive_count"] = demand_positive
    result["demand_negative_count"] = demand_negative
    result["net_bullish"] = net_bullish
    return result


def run() -> Dict:
    return safe_run("oil_twitter", scrape)


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2))
