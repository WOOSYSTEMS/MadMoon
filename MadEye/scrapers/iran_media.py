"""
MadEye Sniper Mode — Scraper 2: Iranian State Media Monitor
Scrapes PressTV, IRNA, and Fars News RSS feeds for oil-threat signals.
"""

from typing import Dict, List
from .base_scraper import (
    fetch, parse_rss, score_keywords, make_result, safe_run
)

FEEDS = {
    "presstv": "https://www.presstv.ir/RSS",
    "irna": "https://en.irna.ir/rss",
    "farsnews": "https://www.farsnews.ir/en/rss",
}

KEYWORDS = [
    "hormuz", "strait", "military", "drill", "missile", "irgc",
    "nuclear", "sanctions", "retaliation", "navy", "tanker",
    "oil", "blockade", "closure", "war", "attack", "defense",
    "revolutionary guard", "enrichment", "uranium", "centrifuge",
    "warning", "threat", "exercise", "fleet", "submarine",
]

HIGH_WEIGHT = {
    "hormuz": 3.0,
    "blockade": 3.0,
    "closure": 3.0,
    "retaliation": 2.5,
    "tanker": 2.5,
    "war": 2.0,
    "attack": 2.0,
    "strait": 2.0,
}


def scrape() -> Dict:
    all_signals = []
    total_hits = 0
    articles_scanned = 0

    for name, url in FEEDS.items():
        xml = fetch(url, ttl_seconds=300)
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

    # Score: 0 hits=0, 3=2, 6=4, 10=6, 15=8, 20+=10
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

    confidence = min(1.0, articles_scanned / 30) if articles_scanned > 0 else 0.1

    result = make_result(score, confidence, all_signals[:20], "iran_media")
    result["articles_scanned"] = articles_scanned
    result["total_keyword_hits"] = total_hits
    return result


def run() -> Dict:
    return safe_run("iran_media", scrape)


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2))
