"""
MadEye Sniper Mode — Scraper 3: Saudi State Media Monitor
Scrapes SPA and Al Arabiya RSS feeds for oil infrastructure signals.
"""

from typing import Dict, List
from .base_scraper import (
    fetch, parse_rss, score_keywords, make_result, safe_run
)

FEEDS = {
    "spa": "https://www.spa.gov.sa/rss/en",
    "alarabiya": "https://www.alarabiya.net/rss",
}

KEYWORDS = [
    "aramco", "pipeline", "refinery", "airport", "intercepted",
    "missile", "drone", "damage", "production", "export",
    "houthi", "attack", "defense", "explosion", "fire",
    "oil facility", "terminal", "sabotage", "disruption",
    "patriot", "air defense", "debris", "casualties",
]

HIGH_WEIGHT = {
    "aramco": 3.0,
    "intercepted": 2.5,
    "explosion": 3.0,
    "damage": 2.5,
    "disruption": 2.5,
    "fire": 2.0,
    "pipeline": 2.0,
    "refinery": 2.0,
    "sabotage": 3.0,
}


def scrape() -> Dict:
    all_signals = []
    total_hits = 0
    articles_scanned = 0

    for name, url in FEEDS.items():
        xml = fetch(url, ttl_seconds=600)
        if not xml:
            all_signals.append(f"{name}: FEED_UNREACHABLE")
            continue

        items = parse_rss(xml)
        for item in items:
            articles_scanned += 1
            text = f"{item.get('title', '')} {item.get('description', '')}"
            hits, matched = score_keywords(text, KEYWORDS, HIGH_WEIGHT)
            if hits > 0:
                total_hits += hits
                for kw in matched:
                    sig = f"{name}: {kw} — {item['title'][:80]}"
                    all_signals.append(sig)

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

    result = make_result(score, confidence, all_signals[:20], "saudi_media")
    result["articles_scanned"] = articles_scanned
    result["total_keyword_hits"] = total_hits
    return result


def run() -> Dict:
    return safe_run("saudi_media", scrape)


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2))
