"""
MadEye | Gold - XAU/USD Intelligence & Trading Signal Engine
FastAPI application with background data collection and scoring.
Port: 8801
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
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
(DATA_DIR / "cache").mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(DATA_DIR / "madeye_gold.log", mode="a"),
    ],
)
logger = logging.getLogger("madeye.gold")

from scorer import GoldScorer
from oanda_bridge import GoldOANDABridge

# Global instances
scorer: Optional[GoldScorer] = None
oanda: Optional[GoldOANDABridge] = None
background_tasks: list = []


async def run_tier1_loop():
    """Tier 1: DXY + Technical -- every 5 minutes."""
    while True:
        try:
            logger.info("Tier 1 (DXY, Technical) starting...")
            await scorer.run_tier(1)
            logger.info("Tier 1 complete")
        except Exception as e:
            logger.error(f"Tier 1 loop error: {e}")
        await asyncio.sleep(300)


async def run_tier2_loop():
    """Tier 2: Real Rates, Treasury, Geopolitical -- every 15 minutes."""
    while True:
        try:
            logger.info("Tier 2 (Rates, Treasury, Geopolitical) starting...")
            await scorer.run_tier(2)
            logger.info("Tier 2 complete")
        except Exception as e:
            logger.error(f"Tier 2 loop error: {e}")
        await asyncio.sleep(900)


async def run_tier3_loop():
    """Tier 3: CB, ETF, Inflation, Currency, Seasonal -- every 30 minutes."""
    while True:
        try:
            logger.info("Tier 3 (CB, ETF, Inflation, Currency, Seasonal) starting...")
            await scorer.run_tier(3)
            logger.info("Tier 3 complete")
        except Exception as e:
            logger.error(f"Tier 3 loop error: {e}")
        await asyncio.sleep(1800)


async def run_full_score_loop():
    """Full scoring every 15 minutes."""
    while True:
        try:
            logger.info("Full gold scoring cycle...")
            signal = await scorer.run_all()
            logger.info(
                f"Gold Signal: {signal['action']} | Net: {signal['net_score']} | "
                f"Conf: {signal['confidence']}"
            )
        except Exception as e:
            logger.error(f"Full score loop error: {e}")
        await asyncio.sleep(900)


async def run_oanda_loop():
    """OANDA bridge check every 60 seconds."""
    while True:
        try:
            result = await oanda.process_signal()
            if result.get("executed") and result["executed"] != "NONE":
                logger.info(f"OANDA Gold trade: {result}")
        except Exception as e:
            logger.error(f"OANDA Gold loop error: {e}")
        await asyncio.sleep(60)


def _load_api_keys() -> dict:
    """Load API keys from environment or data files."""
    keys = {}

    key_map = {
        "newsapi": ("NEWSAPI_KEY", "newsapi_key.txt", "9a1a0c6118414732871c9f72618818d9"),
        "alphavantage": ("ALPHAVANTAGE_KEY", "alphavantage_key.txt", "8S7DUSYD93O29PK9"),
        "fred": ("FRED_API_KEY", "fred_api_key.txt", "DEMO_KEY"),
    }

    for name, (env_var, filename, default) in key_map.items():
        # Check file first
        key_path = DATA_DIR / filename
        if key_path.exists():
            key = key_path.read_text().strip()
            if key:
                keys[name] = key
                os.environ[env_var] = key
                continue

        # Check parent data dir (oil system keys)
        parent_key_path = Path(__file__).parent.parent / "data" / filename
        if parent_key_path.exists():
            key = parent_key_path.read_text().strip()
            if key:
                keys[name] = key
                os.environ[env_var] = key
                continue

        # Environment variable
        key = os.environ.get(env_var, default)
        keys[name] = key

    active = {k: bool(v and v != "DEMO_KEY") for k, v in keys.items()}
    logger.info(f"API keys active: {', '.join(k for k, v in active.items() if v)}")
    logger.info(f"API keys missing: {', '.join(k for k, v in active.items() if not v) or 'none'}")
    return keys


@asynccontextmanager
async def lifespan(app: FastAPI):
    global scorer, oanda, background_tasks

    logger.info("=" * 60)
    logger.info("MadEye | Gold - XAU/USD Intelligence Engine starting...")
    logger.info("=" * 60)

    api_keys = _load_api_keys()

    scorer = GoldScorer(
        fred_key=api_keys.get("fred"),
        newsapi_key=api_keys.get("newsapi"),
        alphavantage_key=api_keys.get("alphavantage"),
    )

    oanda_config = os.environ.get("OANDA_CONFIG_PATH")
    oanda = GoldOANDABridge(config_path=oanda_config)

    # Initial collection
    logger.info("Running initial gold data collection...")
    try:
        signal = await scorer.run_all()
        logger.info(
            f"Initial gold signal: {signal['action']} | "
            f"Net: {signal['net_score']} | Conf: {signal['confidence']}"
        )
    except Exception as e:
        logger.error(f"Initial collection failed: {e}")

    # Start background tasks
    background_tasks = [
        asyncio.create_task(run_tier1_loop()),
        asyncio.create_task(run_tier2_loop()),
        asyncio.create_task(run_tier3_loop()),
        asyncio.create_task(run_full_score_loop()),
        asyncio.create_task(run_oanda_loop()),
    ]
    logger.info(f"Started {len(background_tasks)} background loops")

    yield

    logger.info("MadEye Gold shutting down...")
    for task in background_tasks:
        task.cancel()
    await asyncio.gather(*background_tasks, return_exceptions=True)
    if scorer:
        await scorer.close()
    if oanda:
        await oanda.close()
    logger.info("MadEye Gold shutdown complete")


# Create FastAPI app
app = FastAPI(
    title="MadEye | Gold",
    description="XAU/USD Intelligence & Trading Signal Engine",
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
    html_path = STATIC_DIR / "index.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text())
    return HTMLResponse(content="<h1>MadEye | Gold</h1><p>Dashboard not found.</p>")


@app.get("/api/signal")
async def get_signal():
    if scorer is None:
        raise HTTPException(status_code=503, detail="Scorer not initialized")
    signal = scorer.get_current_signal()
    if signal is None:
        raise HTTPException(status_code=404, detail="No signal computed yet")
    return JSONResponse(content=signal)


@app.get("/api/factors")
async def get_factors():
    if scorer is None:
        raise HTTPException(status_code=503, detail="Scorer not initialized")
    signal = scorer.get_current_signal()
    if signal is None:
        raise HTTPException(status_code=404, detail="No signal computed yet")

    factors = signal.get("factor_scores", {})
    return JSONResponse(content={
        "timestamp": signal.get("timestamp"),
        "factors": factors,
        "weights": {
            "dxy": {"weight": 5.0, "pct": "25%", "tier": 1},
            "technical_gold": {"weight": 2.0, "pct": "10%", "tier": 1},
            "real_rates": {"weight": 4.0, "pct": "20%", "tier": 2},
            "treasury": {"weight": 2.0, "pct": "10%", "tier": 2},
            "geopolitical_gold": {"weight": 2.0, "pct": "10%", "tier": 2},
            "central_banks": {"weight": 2.0, "pct": "10%", "tier": 3},
            "etf_flows_gold": {"weight": 1.6, "pct": "8%", "tier": 3},
            "inflation": {"weight": 1.4, "pct": "7%", "tier": 3},
            "currency_gold": {"weight": 1.0, "pct": "5%", "tier": 3},
            "seasonal_gold": {"weight": 1.0, "pct": "5%", "tier": 3},
        },
    })


@app.get("/api/history")
async def get_history(limit: int = 100):
    if scorer is None:
        raise HTTPException(status_code=503, detail="Scorer not initialized")
    history = scorer.get_history(limit=limit)
    return JSONResponse(content={"count": len(history), "signals": history})


@app.get("/api/price")
async def get_price():
    """Get live gold price from Yahoo Finance GC=F."""
    try:
        import yfinance as yf
        gold = yf.Ticker("GC=F")
        hist = gold.history(period="5d")

        if hist.empty:
            raise HTTPException(status_code=404, detail="No gold price data")

        latest = hist.iloc[-1]
        prev_close = hist.iloc[-2]["Close"] if len(hist) >= 2 else latest["Close"]

        return JSONResponse(content={
            "symbol": "GC=F",
            "name": "Gold Futures (XAU/USD)",
            "price": round(float(latest["Close"]), 2),
            "open": round(float(latest["Open"]), 2),
            "high": round(float(latest["High"]), 2),
            "low": round(float(latest["Low"]), 2),
            "volume": int(latest["Volume"]),
            "prev_close": round(float(prev_close), 2),
            "change": round(float(latest["Close"] - prev_close), 2),
            "change_pct": round(float((latest["Close"] - prev_close) / prev_close * 100), 2),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "history": [
                {
                    "date": str(idx.date()),
                    "close": round(float(row["Close"]), 2),
                    "volume": int(row["Volume"]),
                }
                for idx, row in hist.iterrows()
            ],
        })
    except ImportError:
        raise HTTPException(status_code=500, detail="yfinance not installed")
    except Exception as e:
        logger.error(f"Gold price fetch error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/oanda/status")
async def oanda_status():
    if oanda is None:
        raise HTTPException(status_code=503, detail="OANDA bridge not initialized")
    summary = await oanda.get_account_summary()
    positions = await oanda.get_open_positions()
    return JSONResponse(content={
        "configured": oanda.is_configured,
        "dry_run": oanda.is_dry_run,
        "instrument": "XAU_USD",
        "account": summary,
        "positions": positions,
        "recent_trades": oanda.get_trade_log(limit=20),
    })


@app.post("/api/refresh")
async def force_refresh():
    if scorer is None:
        raise HTTPException(status_code=503, detail="Scorer not initialized")
    signal = await scorer.run_all()
    return JSONResponse(content={"status": "refreshed", "signal": signal})


@app.get("/api/health")
async def health():
    signal = scorer.get_current_signal() if scorer else None
    return JSONResponse(content={
        "status": "ok",
        "engine": "MadEye | Gold",
        "version": "1.0.0",
        "commodity": "XAU/USD",
        "has_signal": signal is not None,
        "oanda_configured": oanda.is_configured if oanda else False,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("MADEYE_GOLD_PORT", "8801"))
    logger.info(f"Starting MadEye Gold on port {port}")
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        log_level="info",
    )
