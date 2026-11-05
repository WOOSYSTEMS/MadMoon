"""
MadEye Sniper Mode — Scraper 4: Russian Energy Monitor
Scrapes TASS Energy RSS and NewsAPI for Russian oil supply signals.
"""

from typing import Dict
from .base_scraper import (
    fetch, parse_rss, fetch_newsapi, score_keywords, make_result, safe_run
)

FEEDS = {
    "tass_energy": "https://tass.com/rss/energy",
}

NEWSAPI_QUERY = "Russia oil production sanctions"

KEYWORDS = [
    "production cut", "opec+", "compliance", "sanctions", "shadow fleet",
    "urals crude", "export ban", "pipeline", "embargo", "price cap",
    "oil output", "barrel", "reduction", "voluntary cut", "supply",
    "russia oil", "gazprom", "rosneft", "lukoil", "transneft",
    "arctic", "diesel", "refined products", "g7", "insurance",
]

HIGH_WEIGHT = {
    "production cut": 3.0,
    "export ban": 3.0,
    "embargo": 3.0,
    "sanctions": 2.0,
    "shadow fleet": 2.5,
    "price cap": 2.0,
    "voluntary cut": 2.5,
}


def scrape() -> Dict:
    all_signals = []
    total_hits = 0
    articles_scanned = 0

    # TASS RSS
    for name, url in FEEDS.items():
        xml = fetch(url, ttl_seconds=1800)
        if xml:
            items = parse_rss(xml)
            for item in items:
                articles_scanned += 1
                text = f"{item.get('title', '')} {item.get('description', '')}"
                hits, matched = score_keywords(text, KEYWORDS, HIGH_WEIGHT)
                if hits > 0:
                    total_hits += hits
                    for kw in matched:
                        all_signals.append(f"{name}: {kw} — {item['title'][:80]}")

    # NewsAPI
    articles = fetch_newsapi(NEWSAPI_QUERY, ttl_seconds=1800)
    for art in articles:
        articles_scanned += 1
        text = f"{art.get('title', '')} {art.get('description', '')}"
        hits, matched = score_keywords(text, KEYWORDS, HIGH_WEIGHT)
        if hits > 0:
            total_hits += hits
            for kw in matched:
                all_signals.append(f"newsapi: {kw} — {art.get('title', '')[:80]}")

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

    confidence = min(1.0, articles_scanned / 25) if articles_scanned > 0 else 0.1

    result = make_result(score, confidence, all_signals[:20], "russian_energy")
    result["articles_scanned"] = articles_scanned
    result["total_keyword_hits"] = total_hits
    return result


def run() -> Dict:
    return safe_run("russian_energy", scrape)


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2))
