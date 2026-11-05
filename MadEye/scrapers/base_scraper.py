"""
MadEye Sniper Mode — Base Scraper
Shared utilities for all 12 scrapers: caching, retries, standard output format.
"""

import os
import json
import time
import hashlib
import requests
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from bs4 import BeautifulSoup

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
CACHE_DIR = os.path.join(DATA_DIR, "cache")
LOG_DIR = os.path.join(DATA_DIR, "logs")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

NEWSAPI_KEY = "9a1a0c6118414732871c9f72618818d9"
NEWSAPI_URL = "https://newsapi.org/v2/everything"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_result(score: int, confidence: float, signals: List[str], source: str, raw: Any = None) -> Dict:
    """Standard scraper output format."""
    return {
        "score": max(0, min(10, score)),
        "confidence": max(0.0, min(1.0, confidence)),
        "signals": signals,
        "source": source,
        "timestamp": now_iso(),
        "raw_count": len(raw) if isinstance(raw, list) else 0,
    }


def cache_key(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()


def get_cached(url: str, ttl_seconds: int = 300) -> Optional[str]:
    """Return cached response if fresh enough."""
    path = os.path.join(CACHE_DIR, cache_key(url) + ".json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        age = time.time() - data.get("cached_at", 0)
        if age < ttl_seconds:
            return data.get("content", "")
    except:
        pass
    return None


def set_cache(url: str, content: str):
    """Cache a response."""
    path = os.path.join(CACHE_DIR, cache_key(url) + ".json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"url": url, "content": content, "cached_at": time.time()}, f)
    except:
        pass


def fetch(url: str, ttl_seconds: int = 300, retries: int = 1) -> Optional[str]:
    """Fetch URL with caching and retry. Returns response text or None."""
    cached = get_cached(url, ttl_seconds)
    if cached is not None:
        return cached

    for attempt in range(retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code == 200:
                set_cache(url, r.text)
                return r.text
        except Exception as e:
            if attempt == retries:
                return None
            time.sleep(1)
    return None


def fetch_newsapi(query: str, ttl_seconds: int = 300, page_size: int = 20) -> List[Dict]:
    """Fetch from NewsAPI. Returns list of articles."""
    url = f"{NEWSAPI_URL}?q={requests.utils.quote(query)}&sortBy=publishedAt&pageSize={page_size}&apiKey={NEWSAPI_KEY}"
    cached = get_cached(url, ttl_seconds)
    if cached is not None:
        try:
            return json.loads(cached)
        except:
            pass

    for attempt in range(2):
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                data = r.json()
                articles = data.get("articles", [])
                set_cache(url, json.dumps(articles))
                return articles
        except:
            if attempt == 0:
                time.sleep(1)
    return []


def parse_rss(xml_text: str) -> List[Dict]:
    """Parse RSS feed XML into list of items."""
    items = []
    try:
        soup = BeautifulSoup(xml_text, "xml")
        for item in soup.find_all("item"):
            entry = {
                "title": item.find("title").text.strip() if item.find("title") else "",
                "description": item.find("description").text.strip() if item.find("description") else "",
                "link": item.find("link").text.strip() if item.find("link") else "",
                "pubDate": item.find("pubDate").text.strip() if item.find("pubDate") else "",
            }
            items.append(entry)
    except Exception:
        # Fallback: try html.parser
        try:
            soup = BeautifulSoup(xml_text, "html.parser")
            for item in soup.find_all("item"):
                entry = {
                    "title": item.find("title").text.strip() if item.find("title") else "",
                    "description": item.find("description").text.strip() if item.find("description") else "",
                    "link": item.find("link").text.strip() if item.find("link") else "",
                    "pubDate": item.find("pubDate").text.strip() if item.find("pubDate") else "",
                }
                items.append(entry)
        except:
            pass
    return items


def score_keywords(text: str, keywords: List[str], weights: Optional[Dict[str, float]] = None) -> tuple:
    """Score text against keywords. Returns (hit_count, matched_keywords)."""
    text_lower = text.lower()
    hits = 0
    matched = []
    for kw in keywords:
        if kw.lower() in text_lower:
            hits += 1
            matched.append(kw)
            if weights and kw.lower() in weights:
                hits += weights[kw.lower()] - 1  # extra weight
    return hits, matched


def load_last_result(scraper_name: str) -> Optional[Dict]:
    """Load last known result for a scraper (fallback on failure)."""
    path = os.path.join(DATA_DIR, f"last_{scraper_name}.json")
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except:
            pass
    return None


def save_result(scraper_name: str, result: Dict):
    """Save scraper result for fallback and logging."""
    path = os.path.join(DATA_DIR, f"last_{scraper_name}.json")
    try:
        with open(path, "w") as f:
            json.dump(result, f, indent=2)
    except:
        pass


def log_scraper(scraper_name: str, result: Dict):
    """Append to daily log file."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = os.path.join(LOG_DIR, f"{scraper_name}_{today}.jsonl")
    try:
        with open(path, "a") as f:
            f.write(json.dumps(result) + "\n")
    except:
        pass


def safe_run(scraper_name: str, scrape_fn):
    """Wrapper: run scraper, handle failures, return last known on crash."""
    try:
        result = scrape_fn()
        save_result(scraper_name, result)
        log_scraper(scraper_name, result)
        return result
    except Exception as e:
        fallback = load_last_result(scraper_name)
        if fallback:
            fallback["_fallback"] = True
            fallback["_error"] = str(e)
            return fallback
        return make_result(0, 0.0, [f"SCRAPER_ERROR: {str(e)[:100]}"], scraper_name)
