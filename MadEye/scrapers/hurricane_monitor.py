"""
MadEye Sniper Mode — Scraper 10: Hurricane / Gulf of Mexico Monitor
Tracks NOAA NHC RSS and NewsAPI for GoM weather threats to oil platforms.
"""

import re
from typing import Dict
from .base_scraper import (
    fetch, parse_rss, fetch_newsapi, score_keywords, make_result, safe_run
)

NHC_RSS = "https://www.nhc.noaa.gov/index-at.xml"
NEWSAPI_QUERY = "hurricane gulf mexico OR tropical storm gulf"

KEYWORDS = [
    "hurricane", "tropical storm", "tropical depression",
    "gulf of mexico", "gulf coast", "oil platform", "evacuation",
    "shut-in", "production halt", "offshore", "platform",
    "category", "landfall", "storm surge", "wind speed",
    "bureau of safety", "bsee", "shut in",
]

HIGH_WEIGHT = {
    "hurricane": 2.0,
    "evacuation": 3.0,
    "shut-in": 4.0,
    "production halt": 4.0,
    "landfall": 2.5,
    "category": 2.0,
}

# GoM approximate bounding box (lat/lon)
GOM_LAT_MIN = 18.0
GOM_LAT_MAX = 31.0
GOM_LON_MIN = -98.0
GOM_LON_MAX = -80.0


def extract_storm_info(text: str) -> Dict:
    """Extract storm details from NHC feed text."""
    info = {"name": None, "category": None, "wind_mph": None, "near_gom": False}

    # Storm name
    name_match = re.search(r'(?:Hurricane|Tropical Storm|Tropical Depression)\s+(\w+)', text)
    if name_match:
        info["name"] = name_match.group(0)

    # Category
    cat_match = re.search(r'Category\s+(\d)', text)
    if cat_match:
        info["category"] = int(cat_match.group(1))

    # Wind speed
    wind_match = re.search(r'(\d+)\s*mph', text)
    if wind_match:
        info["wind_mph"] = int(wind_match.group(1))

    # Check if near GoM (look for coordinates or "gulf" mentions)
    if "gulf" in text.lower() or "mexico" in text.lower():
        info["near_gom"] = True

    # Look for lat/lon
    coord_match = re.search(r'(\d+\.?\d*)\s*N.*?(\d+\.?\d*)\s*W', text)
    if coord_match:
        lat = float(coord_match.group(1))
        lon = -float(coord_match.group(2))
        if GOM_LAT_MIN <= lat <= GOM_LAT_MAX and GOM_LON_MIN <= lon <= GOM_LON_MAX:
            info["near_gom"] = True

    return info


def scrape() -> Dict:
    all_signals = []
    total_hits = 0
    articles_scanned = 0
    active_storms = []

    # NOAA NHC RSS
    xml = fetch(NHC_RSS, ttl_seconds=900)
    if xml:
        items = parse_rss(xml)
        for item in items:
            articles_scanned += 1
            text = f"{item.get('title', '')} {item.get('description', '')}"
            storm_info = extract_storm_info(text)

            if storm_info["name"]:
                active_storms.append(storm_info)
                if storm_info["near_gom"]:
                    bonus = 3
                    if storm_info["category"] and storm_info["category"] >= 3:
                        bonus = 6
                    elif storm_info["category"] and storm_info["category"] >= 1:
                        bonus = 4
                    total_hits += bonus
                    all_signals.append(f"NHC: {storm_info['name']} near GoM (cat {storm_info.get('category', '?')}, {storm_info.get('wind_mph', '?')} mph)")

            hits, matched = score_keywords(text, KEYWORDS, HIGH_WEIGHT)
            if hits > 0:
                total_hits += hits
                for kw in matched:
                    all_signals.append(f"nhc: {kw} — {item['title'][:60]}")
    else:
        all_signals.append("nhc: FEED_UNREACHABLE")

    # NewsAPI
    articles = fetch_newsapi(NEWSAPI_QUERY, ttl_seconds=900)
    for art in articles:
        articles_scanned += 1
        text = f"{art.get('title', '')} {art.get('description', '')}".lower()
        hits, matched = score_keywords(text, KEYWORDS, HIGH_WEIGHT)
        if hits > 0:
            total_hits += hits
            for kw in matched:
                all_signals.append(f"newsapi: {kw} — {art.get('title', '')[:60]}")

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

    confidence = min(1.0, articles_scanned / 15) if articles_scanned > 0 else 0.1

    result = make_result(score, confidence, all_signals[:20], "hurricane_monitor")
    result["articles_scanned"] = articles_scanned
    result["total_keyword_hits"] = total_hits
    result["active_storms_near_gom"] = [s for s in active_storms if s["near_gom"]]
    return result


def run() -> Dict:
    return safe_run("hurricane_monitor", scrape)


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2))
