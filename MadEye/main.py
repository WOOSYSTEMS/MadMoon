"""
MadEye - Oil Price Intelligence & Trading Signal Engine
FastAPI application with background data collection and scoring.
"""

import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(Path(__file__).parent / "data" / "madeye.log", mode="a"),
    ],
)
logger = logging.getLogger("madeye")

# Ensure data directory exists
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
(DATA_DIR / "cache").mkdir(parents=True, exist_ok=True)

from scorer import MadEyeScorer
from oanda_bridge import OANDABridge

# Global instances
scorer: Optional[MadEyeScorer] = None
oanda: Optional[OANDABridge] = None
background_tasks: list = []


async def run_tier1_loop():
    """Run Tier 1 collectors (geopolitical, supply) every 5 minutes."""
    while True:
        try:
            logger.info("Tier 1 collection starting...")
            await scorer.run_tier(1)
            logger.info("Tier 1 collection complete")
        except Exception as e:
            logger.error(f"Tier 1 loop error: {e}")
        await asyncio.sleep(300)  # 5 minutes


async def run_tier2_loop():
    """Run Tier 2 collectors (financial, shipping, crack_spread, spreads, demand_advanced) every 15 minutes."""
    while True:
        try:
            logger.info("Tier 2 collection starting...")
            await scorer.run_tier(2)
            logger.info("Tier 2 collection complete")
        except Exception as e:
            logger.error(f"Tier 2 loop error: {e}")
        await asyncio.sleep(900)  # 15 minutes


async def run_tier3_loop():
    """Run Tier 3 collectors (technical, sentiment, cross_commodity) every 30 minutes."""
    while True:
        try:
            logger.info("Tier 3 collection starting...")
            await scorer.run_tier(3)
            logger.info("Tier 3 collection complete")
        except Exception as e:
            logger.error(f"Tier 3 loop error: {e}")
        await asyncio.sleep(1800)  # 30 minutes


async def run_tier4_loop():
    """Run Tier 4 collectors (weather, satellite, floating_storage, etf_flows) every 6 hours."""
    while True:
        try:
            logger.info("Tier 4 collection starting...")
            await scorer.run_tier(4)
            logger.info("Tier 4 collection complete")
        except Exception as e:
            logger.error(f"Tier 4 loop error: {e}")
        await asyncio.sleep(21600)  # 6 hours


async def run_full_score_loop():
    """Run full scoring every 15 minutes."""
    while True:
        try:
            logger.info("Full scoring cycle starting...")
            signal = await scorer.run_all()
            logger.info(
                f"Signal: {signal['action']} | Net Score: {signal['net_score']} | "
                f"Confidence: {signal['confidence']}"
            )
        except Exception as e:
            logger.error(f"Full score loop error: {e}")
        await asyncio.sleep(900)  # 15 minutes


async def run_oanda_loop():
    """Run OANDA bridge check every 60 seconds."""
    while True:
        try:
            result = await oanda.process_signal()
            if result.get("executed") and result["executed"] != "NONE":
                logger.info(f"OANDA trade executed: {result}")
        except Exception as e:
            logger.error(f"OANDA loop error: {e}")
        await asyncio.sleep(60)


def _load_key_file(filename: str, env_var: str, default: str = "") -> str:
    """Load API key from data/<filename> or environment variable."""
    key_path = DATA_DIR / filename
    if key_path.exists():
        key = key_path.read_text().strip()
        if key:
            os.environ[env_var] = key
            return key
    return os.environ.get(env_var, default)


def _load_all_api_keys() -> dict:
    """Load all API keys from data/*.txt files and set environment variables."""
    keys = {
        "eia": _load_key_file("eia_api_key.txt", "EIA_API_KEY", "DEMO_KEY"),
        "newsapi": _load_key_file("newsapi_key.txt", "NEWSAPI_KEY"),
        "alphavantage": _load_key_file("alphavantage_key.txt", "ALPHAVANTAGE_KEY"),
        "nasa_firms": _load_key_file("nasa_firms_key.txt", "NASA_FIRMS_KEY"),
        "fred": _load_key_file("fred_api_key.txt", "FRED_API_KEY", "DEMO_KEY"),
    }
    active = {k: bool(v and v != "DEMO_KEY") for k, v in keys.items()}
    logger.info(f"API keys loaded: {', '.join(k for k, v in active.items() if v)}")
    logger.info(f"API keys missing: {', '.join(k for k, v in active.items() if not v) or 'none'}")
    return keys


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown."""
    global scorer, oanda, background_tasks

    logger.info("=" * 60)
    logger.info("MadEye Oil Price Intelligence Engine starting...")
    logger.info("=" * 60)

    # Load all API keys from data/*.txt files
    api_keys = _load_all_api_keys()

    # Initialize scorer with real API keys
    scorer = MadEyeScorer(
        eia_key=api_keys["eia"],
        fred_key=api_keys["fred"],
        newsapi_key=api_keys["newsapi"],
        alphavantage_key=api_keys["alphavantage"],
    )

    # Initialize OANDA bridge
    oanda_config = os.environ.get("OANDA_CONFIG_PATH")
    oanda = OANDABridge(config_path=oanda_config)

    # Run initial full collection
    logger.info("Running initial data collection...")
    try:
        signal = await scorer.run_all()
        logger.info(
            f"Initial signal: {signal['action']} | "
            f"Net Score: {signal['net_score']} | "
            f"Confidence: {signal['confidence']}"
        )
    except Exception as e:
        logger.error(f"Initial collection failed: {e}")

    # Start background tasks
    background_tasks = [
        asyncio.create_task(run_tier1_loop()),
        asyncio.create_task(run_tier2_loop()),
        asyncio.create_task(run_tier3_loop()),
        asyncio.create_task(run_tier4_loop()),
        asyncio.create_task(run_full_score_loop()),
        asyncio.create_task(run_oanda_loop()),
    ]
    logger.info(f"Started {len(background_tasks)} background collection loops")

    yield

    # Shutdown
    logger.info("MadEye shutting down...")
    for task in background_tasks:
        task.cancel()
    await asyncio.gather(*background_tasks, return_exceptions=True)
    if scorer:
        await scorer.close()
    if oanda:
        await oanda.close()
    logger.info("MadEye shutdown complete")


# Create FastAPI app
app = FastAPI(
    title="MadEye",
    description="Oil Price Intelligence & Trading Signal Engine",
    version="1.0.0",
    lifespan=lifespan,
)

# Static files
STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# --- API Routes ---

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    """Serve the MadEye dashboard."""
    html_path = STATIC_DIR / "index.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text())
    return HTMLResponse(content="<h1>MadEye</h1><p>Dashboard not found. Place index.html in /static/</p>")


@app.get("/api/signal")
async def get_signal():
    """Get current trading signal with all factor scores."""
    if scorer is None:
        raise HTTPException(status_code=503, detail="Scorer not initialized")

    signal = scorer.get_current_signal()
    if signal is None:
        raise HTTPException(status_code=404, detail="No signal computed yet")

    return JSONResponse(content=signal)


@app.get("/api/factors")
async def get_factors():
    """Get detailed breakdown of all 14 factor categories."""
    if scorer is None:
        raise HTTPException(status_code=503, detail="Scorer not initialized")

    signal = scorer.get_current_signal()
    if signal is None:
        raise HTTPException(status_code=404, detail="No signal computed yet")

    factors = signal.get("factor_scores", {})
    return JSONResponse(content={
        "timestamp": signal.get("timestamp"),
        "factors": factors,
        "tier_weights": {
            "geopolitical": {"weight": 3.0, "tier": 1},
            "supply": {"weight": 3.0, "tier": 1},
            "financial": {"weight": 2.5, "tier": 2},
            "shipping": {"weight": 2.0, "tier": 2},
            "crack_spread": {"weight": 2.0, "tier": 2},
            "spreads": {"weight": 2.0, "tier": 2},
            "demand_advanced": {"weight": 2.0, "tier": 2},
            "sentiment": {"weight": 2.0, "tier": 3},
            "technical": {"weight": 1.5, "tier": 3},
            "cross_commodity": {"weight": 1.5, "tier": 3},
            "satellite": {"weight": 1.5, "tier": 4},
            "floating_storage": {"weight": 1.0, "tier": 4},
            "etf_flows": {"weight": 1.0, "tier": 4},
            "weather": {"weight": 0.5, "tier": 4},
        },
    })


@app.get("/api/history")
async def get_history(limit: int = 100):
    """Get historical signals and their accuracy."""
    if scorer is None:
        raise HTTPException(status_code=503, detail="Scorer not initialized")

    history = scorer.get_history(limit=limit)
    return JSONResponse(content={
        "count": len(history),
        "signals": history,
    })


@app.get("/api/price")
async def get_price():
    """Get live Brent crude oil price via raw Yahoo Finance HTTP."""
    from collectors.yahoo_raw import get_price as yget
    from datetime import datetime, timezone
    data = yget("BZ=F")
    if data.get("price") is None:
        raise HTTPException(status_code=503, detail=data.get("error", "Price unavailable"))
    return {
        "symbol": "BZ=F",
        "name": "Brent Crude Oil",
        "price": round(data["price"], 2),
        "ask": round(data["price"] + 0.04, 2),
        "bid": round(data["price"] - 0.03, 2),
        "open": round(data.get("high", data["price"]), 2),
        "high": round(data.get("high", data["price"]), 2),
        "low": round(data.get("low", data["price"]), 2),
        "volume": data.get("volume", 0) or 0,
        "prev_close": round(data["prev_close"], 2),
        "change": round(data["change"], 2),
        "change_pct": round(data["change_pct"], 2),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "history": [{"close": round(c, 2)} for c in (data.get("closes") or [])[-5:]],
    }


@app.get("/api/oanda/status")
async def oanda_status():
    """Get OANDA bridge status."""
    if oanda is None:
        raise HTTPException(status_code=503, detail="OANDA bridge not initialized")

    summary = await oanda.get_account_summary()
    positions = await oanda.get_open_positions()

    return JSONResponse(content={
        "configured": oanda.is_configured,
        "dry_run": oanda.is_dry_run,
        "account": summary,
        "positions": positions,
        "recent_trades": oanda.get_trade_log(limit=20),
    })


@app.post("/api/refresh")
async def force_refresh():
    """Force a full data collection and scoring cycle."""
    if scorer is None:
        raise HTTPException(status_code=503, detail="Scorer not initialized")

    signal = await scorer.run_all()
    return JSONResponse(content={
        "status": "refreshed",
        "signal": signal,
    })


@app.get("/api/keys")
async def api_keys_status():
    """Check which API keys are active."""
    keys_status = {}
    key_files = {
        "eia": "eia_api_key.txt",
        "newsapi": "newsapi_key.txt",
        "alphavantage": "alphavantage_key.txt",
        "nasa_firms": "nasa_firms_key.txt",
        "fred": "fred_api_key.txt",
    }
    free_apis = {
        "yahoo_finance": "Free (BZ=F, DX-Y.NYB, ^OVX)",
        "fred": "Free (economic data)",
        "gdelt": "Free (geopolitical events, news tone)",
        "cftc_cot": "Free (trader positioning)",
        "cboe_ovx": "Free (oil volatility CSV)",
        "hormuz_tracker": "Free (hormuz.data-tracking.net)",
        "noaa_nhc": "Free (hurricane data)",
    }
    for name, filename in key_files.items():
        path = DATA_DIR / filename
        if path.exists():
            key = path.read_text().strip()
            keys_status[name] = {
                "active": bool(key and key != "DEMO_KEY"),
                "key_preview": key[:4] + "..." + key[-4:] if len(key) > 8 else "***",
                "source": "file",
            }
        else:
            env_key = os.environ.get(f"{name.upper()}_API_KEY", "")
            keys_status[name] = {
                "active": bool(env_key and env_key != "DEMO_KEY"),
                "key_preview": "env" if env_key else "missing",
                "source": "env" if env_key else "none",
            }

    return JSONResponse(content={
        "api_keys": keys_status,
        "free_apis": free_apis,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


@app.get("/api/health")
async def health():
    """Health check endpoint."""
    signal = scorer.get_current_signal() if scorer else None
    return JSONResponse(content={
        "status": "ok",
        "engine": "MadEye",
        "version": "2.0.0",
        "has_signal": signal is not None,
        "oanda_configured": oanda.is_configured if oanda else False,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("MADEYE_PORT", "8800"))
    logger.info(f"Starting MadEye on port {port}")
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        log_level="info",
    )
