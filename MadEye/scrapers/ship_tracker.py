"""
MadEye Sniper Mode — Scraper 7: Shipping Disruption Monitor
Tracks Hormuz/Suez shipping disruptions via NewsAPI and public trackers.
"""

from typing import Dict
from .base_scraper import (
    fetch, fetch_newsapi, score_keywords, make_result, safe_run
)

NEWSAPI_QUERY = "tanker attack OR shipping disruption OR suez canal OR hormuz strait"

KEYWORDS = [
    "tanker attack", "shipping disruption", "suez canal", "hormuz",
    "strait of hormuz", "bab al-mandab", "red sea", "piracy",
    "seizure", "detained", "warning", "closure", "blockade",
    "reroute", "cape of good hope", "insurance premium", "war risk",
    "houthi", "drone attack", "missile", "navy escort",
    "tanker fire", "oil spill", "grounding", "collision",
    "chokepoint", "transit", "shipping lane",
]

HIGH_WEIGHT = {
    "tanker attack": 4.0,
    "closure": 4.0,
    "blockade": 4.0,
    "seizure": 3.0,
    "hormuz": 3.0,
    "bab al-mandab": 3.0,
    "war risk": 2.5,
    "reroute": 2.5,
    "shipping disruption": 3.0,
}

HORMUZ_TRACKER_URL = "https://hormuz.data-tracking.net/"


def check_hormuz_tracker() -> tuple:
    """Try to scrape Hormuz tracker for crossing data. Returns (signals, bonus_score)."""
    signals = []
    bonus = 0
    html = fetch(HORMUZ_TRACKER_URL, ttl_seconds=1800)
    if html:
        # Look for any numbers that might indicate crossing counts
        import re
        numbers = re.findall(r'(\d+)\s*(?:crossings?|transits?|vessels?)', html.lower())
        if numbers:
            signals.append(f"hormuz_tracker: {numbers[0]} vessel references found")
        # If page mentions disruption/warning
        if any(w in html.lower() for w in ["disruption", "warning", "closure", "attack"]):
            bonus = 3
            signals.append("hormuz_tracker: DISRUPTION language detected")
    else:
        signals.append("hormuz_tracker: UNREACHABLE (may indicate regional disruption)")
    return signals, bonus


def scrape() -> Dict:
    all_signals = []
    total_hits = 0
    articles_scanned = 0

    # NewsAPI
    articles = fetch_newsapi(NEWSAPI_QUERY, ttl_seconds=300, page_size=30)
    for art in articles:
        articles_scanned += 1
        text = f"{art.get('title', '')} {art.get('description', '')}".lower()
        hits, matched = score_keywords(text, KEYWORDS, HIGH_WEIGHT)
        if hits > 0:
            total_hits += hits
            for kw in matched:
                all_signals.append(f"newsapi: {kw} — {art.get('title', '')[:60]}")

    # Hormuz tracker
    tracker_signals, tracker_bonus = check_hormuz_tracker()
    all_signals.extend(tracker_signals)
    total_hits += tracker_bonus

    if total_hits >= 20:
        score = 10
    elif total_hits >= 15:
        score = 8
    elif total_hits >= 10:
        score = 6
    elif total_hits >= 6:
        score = 4
    elif total_hits >= 3:
        score = 2
    else:
        score = 0

    confidence = min(1.0, articles_scanned / 20) if articles_scanned > 0 else 0.1

    result = make_result(score, confidence, all_signals[:20], "ship_tracker")
    result["articles_scanned"] = articles_scanned
    result["total_keyword_hits"] = total_hits
    return result


def run() -> Dict:
    return safe_run("ship_tracker", scrape)


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2))
