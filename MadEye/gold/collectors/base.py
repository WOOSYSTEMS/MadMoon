"""
Base collector class for MadEye Gold.
All gold collectors inherit from this. Provides caching, error handling, and score persistence.
"""

import json
import os
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger("madeye.gold")

DATA_DIR = Path(__file__).parent.parent / "data"
CACHE_DIR = DATA_DIR / "cache"


class BaseCollector:
    """Base class for all MadEye Gold data collectors."""

    name: str = "base"
    category: str = "unknown"
    cache_ttl: int = 300  # seconds

    def __init__(self):
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._client: Optional[httpx.AsyncClient] = None
        self._last_score: Optional[Dict] = None
        self._load_last_score()

    def _load_last_score(self):
        """Load last known score from disk."""
        path = DATA_DIR / f"score_{self.name}.json"
        if path.exists():
            try:
                with open(path) as f:
                    self._last_score = json.load(f)
            except Exception:
                self._last_score = None

    def _save_score(self, score_data: Dict):
        """Persist score to disk."""
        path = DATA_DIR / f"score_{self.name}.json"
        try:
            with open(path, "w") as f:
                json.dump(score_data, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"[{self.name}] Failed to save score: {e}")

    async def get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=30.0,
                headers={"User-Agent": "MadEye/2.0 Gold Intelligence Engine"},
                follow_redirects=True,
            )
        return self._client

    async def fetch_json(self, url: str, params: Dict = None, cache_key: str = None) -> Optional[Dict]:
        """Fetch JSON from URL with caching."""
        if cache_key:
            cached = self._get_cache(cache_key)
            if cached is not None:
                return cached

        try:
            client = await self.get_client()
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            if cache_key:
                self._set_cache(cache_key, data)
            return data
        except Exception as e:
            logger.warning(f"[{self.name}] fetch_json failed for {url}: {e}")
            if cache_key:
                return self._get_cache(cache_key, ignore_ttl=True)
            return None

    async def fetch_text(self, url: str, params: Dict = None, cache_key: str = None) -> Optional[str]:
        """Fetch raw text from URL with caching."""
        if cache_key:
            cached = self._get_cache(cache_key)
            if cached is not None:
                return cached

        try:
            client = await self.get_client()
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            text = resp.text
            if cache_key:
                self._set_cache(cache_key, text)
            return text
        except Exception as e:
            logger.warning(f"[{self.name}] fetch_text failed for {url}: {e}")
            if cache_key:
                return self._get_cache(cache_key, ignore_ttl=True)
            return None

    def _get_cache(self, key: str, ignore_ttl: bool = False) -> Any:
        path = CACHE_DIR / f"{self.name}_{key}.json"
        if not path.exists():
            return None
        try:
            with open(path) as f:
                cached = json.load(f)
            if not ignore_ttl and time.time() - cached.get("ts", 0) > self.cache_ttl:
                return None
            return cached.get("data")
        except Exception:
            return None

    def _set_cache(self, key: str, data: Any):
        path = CACHE_DIR / f"{self.name}_{key}.json"
        try:
            with open(path, "w") as f:
                json.dump({"ts": time.time(), "data": data}, f, default=str)
        except Exception as e:
            logger.warning(f"[{self.name}] cache write failed: {e}")

    def make_result(
        self,
        score: float,
        direction: str,
        signals: list,
        details: Dict = None,
        confidence: float = 0.5,
    ) -> Dict:
        """Build a standardized score result."""
        score = max(0.0, min(10.0, score))
        result = {
            "collector": self.name,
            "category": self.category,
            "score": round(score, 2),
            "direction": direction,
            "confidence": round(confidence, 2),
            "signals": signals,
            "details": details or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._last_score = result
        self._save_score(result)
        return result

    async def collect(self) -> Dict:
        """Override in subclass. Must return make_result()."""
        raise NotImplementedError

    async def safe_collect(self) -> Dict:
        """Run collect() with full error handling. Never crashes."""
        try:
            result = await self.collect()
            logger.info(f"[{self.name}] score={result['score']} dir={result['direction']}")
            return result
        except Exception as e:
            logger.error(f"[{self.name}] collect() crashed: {e}", exc_info=True)
            if self._last_score:
                self._last_score["stale"] = True
                self._last_score["error"] = str(e)
                return self._last_score
            return self.make_result(
                score=5.0,
                direction="NEUTRAL",
                signals=[f"Collector error: {str(e)[:100]}"],
                confidence=0.0,
            )

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
