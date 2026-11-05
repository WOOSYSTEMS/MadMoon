"""
MadEye Sniper Mode — Scraper 5: OPEC Monitor
Tracks OPEC website RSS and NewsAPI for production/meeting signals.
"""

from datetime import datetime, timezone
from typing import Dict
from .base_scraper import (
    fetch, parse_rss, fetch_newsapi, score_keywords, make_result, safe_run
)

OPEC_RSS = "https://www.opec.org/opec_web/en/rss/rss.xml"
NEWSAPI_QUERY = "OPEC meeting OR OPEC cut OR OPEC production"

KEYWORDS = [
    "emergency meeting", "production cut", "quota", "compliance", "surprise",
    "output", "barrel", "voluntary", "unplanned", "agreement",
    "extension", "rollback", "reduce", "increase", "saudi",
    "opec+", "meeting", "ministerial", "extraordinary", "decision",
    "supply", "market balance", "demand", "surplus", "deficit",
]

HIGH_WEIGHT = {
    "emergency meeting": 4.0,
    "production cut": 3.0,
    "surprise": 3.0,
    "extraordinary": 3.0,
    "unplanned": 3.0,
    "voluntary": 2.0,
}

# Known OPEC meeting dates (2026-2027) — update as announced
OPEC_MEETING_DATES = [
    "2026-06-01", "2026-09-01", "2026-11-27", "2026-12-01",
    "2027-03-01", "2027-06-01",
]


def days_to_next_meeting() -> int:
    """Days until next known OPEC meeting."""
    now = datetime.now(timezone.utc).date()
    for d in OPEC_MEETING_DATES:
        try:
            meeting = datetime.strptime(d, "%Y-%m-%d").date()
            if meeting >= now:
                return (meeting - now).days
        except:
            continue
    return 999


def scrape() -> Dict:
    all_signals = []
    total_hits = 0
    articles_scanned = 0

    # OPEC RSS
    xml = fetch(OPEC_RSS, ttl_seconds=900)
    if xml:
        items = parse_rss(xml)
        for item in items:
            articles_scanned += 1
            text = f"{item.get('title', '')} {item.get('description', '')}"
            hits, matched = score_keywords(text, KEYWORDS, HIGH_WEIGHT)
            if hits > 0:
                total_hits += hits
                for kw in matched:
                    all_signals.append(f"opec_rss: {kw} — {item['title'][:80]}")

    # NewsAPI
    articles = fetch_newsapi(NEWSAPI_QUERY, ttl_seconds=900)
    for art in articles:
        articles_scanned += 1
        text = f"{art.get('title', '')} {art.get('description', '')}"
        hits, matched = score_keywords(text, KEYWORDS, HIGH_WEIGHT)
        if hits > 0:
            total_hits += hits
            for kw in matched:
                all_signals.append(f"newsapi: {kw} — {art.get('title', '')[:80]}")

    # Proximity bonus: meeting within 3 days = elevated attention
    days = days_to_next_meeting()
    meeting_bonus = 0
    if days <= 1:
        meeting_bonus = 4
        all_signals.append(f"OPEC meeting TOMORROW or TODAY")
    elif days <= 3:
        meeting_bonus = 2
        all_signals.append(f"OPEC meeting in {days} days")
    elif days <= 7:
        meeting_bonus = 1
        all_signals.append(f"OPEC meeting in {days} days")

    raw_score = total_hits + meeting_bonus

    if raw_score >= 20:
        score = 10
    elif raw_score >= 15:
        score = 8
    elif raw_score >= 10:
        score = 6
    elif raw_score >= 6:
        score = 4
    elif raw_score >= 3:
        score = 2
    else:
        score = 0

    confidence = min(1.0, articles_scanned / 20) if articles_scanned > 0 else 0.1

    result = make_result(score, confidence, all_signals[:20], "opec_monitor")
    result["articles_scanned"] = articles_scanned
    result["total_keyword_hits"] = total_hits
    result["days_to_meeting"] = days
    return result


def run() -> Dict:
    return safe_run("opec_monitor", scrape)


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2))
