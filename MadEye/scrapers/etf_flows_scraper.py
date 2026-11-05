"""
MadEye Sniper Mode — ETF Flows Scraper
Synchronous wrapper around the etf_flows collector for the scraper manager.
"""

import asyncio
from .base_scraper import make_result, safe_run

SCRAPER_NAME = "etf_flows"


def _scrape():
    from collectors.etf_flows import ETFFlowsCollector
    collector = ETFFlowsCollector()

    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(collector.safe_collect())
    finally:
        loop.run_until_complete(collector.close())
        loop.close()

    return {
        "score": result.get("score", 0),
        "confidence": result.get("confidence", 0),
        "signals": result.get("signals", []),
        "source": SCRAPER_NAME,
        "timestamp": result.get("timestamp", ""),
    }


def run():
    return safe_run(SCRAPER_NAME, _scrape)
