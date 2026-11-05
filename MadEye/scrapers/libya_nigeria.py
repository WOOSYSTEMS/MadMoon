"""
MadEye Sniper Mode — Scraper 8: Libya/Nigeria Oil Disruption Monitor
Tracks African oil supply disruptions via NewsAPI and GDELT.
"""

from typing import Dict
from .base_scraper import (
    fetch, fetch_newsapi, score_keywords, make_result, safe_run
)

NEWSAPI_QUERIES = [
    "Libya oil OR Libya pipeline OR Libya force majeure",
    "Nigeria pipeline OR Niger Delta OR Nigeria oil attack",
]

KEYWORDS = [
    "militia", "blockade", "force majeure", "shut-in", "pipeline attack",
    "export terminal", "occupation", "protest", "armed group",
    "es sider", "ras lanuf", "sharara", "el feel", "waha",
    "bonny", "forcados", "brass", "qua iboe", "escravos",
    "shut down", "production halt", "closure", "sabotage",
    "militia", "kidnapping", "niger delta avengers", "mend",
    "oil theft", "bunkering", "vandalism", "explosion",
    "haftar", "lna", "gna", "tripoli", "benghazi",
]

HIGH_WEIGHT = {
    "force majeure": 4.0,
    "shut-in": 3.5,
    "pipeline attack": 3.5,
    "blockade": 3.0,
    "sabotage": 3.0,
    "production halt": 3.0,
    "sharara": 2.5,  # Libya's biggest field
    "es sider": 2.5,  # Libya's biggest terminal
    "explosion": 2.5,
}

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc?query=(Libya%20OR%20Nigeria)%20oil&mode=artlist&maxrecords=20&format=json"


def check_gdelt() -> tuple:
    """Check GDELT for recent Libya/Nigeria oil articles."""
    signals = []
    bonus = 0
    raw = fetch(GDELT_URL, ttl_seconds=900)
    if raw:
        try:
            import json
            data = json.loads(raw)
            articles = data.get("articles", [])
            for art in articles[:10]:
                title = art.get("title", "").lower()
                hits, matched = score_keywords(title, KEYWORDS, HIGH_WEIGHT)
                if hits > 0:
                    bonus += hits
                    signals.append(f"gdelt: {', '.join(matched)} — {art.get('title', '')[:60]}")
        except:
            pass
    return signals, bonus


def scrape() -> Dict:
    all_signals = []
    total_hits = 0
    articles_scanned = 0

    for query in NEWSAPI_QUERIES:
        articles = fetch_newsapi(query, ttl_seconds=900, page_size=20)
        for art in articles:
            articles_scanned += 1
            text = f"{art.get('title', '')} {art.get('description', '')}".lower()
            hits, matched = score_keywords(text, KEYWORDS, HIGH_WEIGHT)
            if hits > 0:
                total_hits += hits
                for kw in matched:
                    all_signals.append(f"newsapi: {kw} — {art.get('title', '')[:60]}")

    # GDELT
    gdelt_signals, gdelt_bonus = check_gdelt()
    all_signals.extend(gdelt_signals)
    total_hits += gdelt_bonus

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

    result = make_result(score, confidence, all_signals[:20], "libya_nigeria")
    result["articles_scanned"] = articles_scanned
    result["total_keyword_hits"] = total_hits
    return result


def run() -> Dict:
    return safe_run("libya_nigeria", scrape)


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2))
