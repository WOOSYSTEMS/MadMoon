"""
MadEye Silver -- XAG/USD Trading Signal Engine
FastAPI application on port 8802.
10-factor scoring with Gold/Silver ratio as the unique edge.
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
        logging.FileHandler(Path(__file__).parent / "data" / "madeye_silver.log", mode="a"),
    ],
)
logger = logging.getLogger("madeye.silver")

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
(DATA_DIR / "cache").mkdir(parents=True, exist_ok=True)

from scorer import SilverScorer
from oanda_bridge import OANDABridgeSilver

# Global instances
scorer: Optional[SilverScorer] = None
oanda: Optional[OANDABridgeSilver] = None
background_tasks: list = []


async def run_tier1_loop():
    """Tier 1: GSR, DXY, Real Rates -- every 5 minutes."""
    while True:
        try:
            logger.info("Tier 1 (GSR, DXY, Real Rates) starting...")
            await scorer.run_tier(1)
            logger.info("Tier 1 complete")
        except Exception as e:
            logger.error(f"Tier 1 error: {e}")
        await asyncio.sleep(300)


async def run_tier2_loop():
    """Tier 2: Industrial, Copper, Technical -- every 15 minutes."""
    while True:
        try:
            logger.info("Tier 2 (Industrial, Copper, Technical) starting...")
            await scorer.run_tier(2)
            logger.info("Tier 2 complete")
        except Exception as e:
            logger.error(f"Tier 2 error: {e}")
        await asyncio.sleep(900)


async def run_tier3_loop():
    """Tier 3: ETF Flows, COMEX, Geopolitical, Seasonal -- every 30 minutes."""
    while True:
        try:
            logger.info("Tier 3 (ETF, COMEX, Geopolitical, Seasonal) starting...")
            await scorer.run_tier(3)
            logger.info("Tier 3 complete")
        except Exception as e:
            logger.error(f"Tier 3 error: {e}")
        await asyncio.sleep(1800)


async def run_full_score_loop():
    """Full scoring every 15 minutes."""
    while True:
        try:
            logger.info("Full silver scoring cycle...")
            signal = await scorer.run_all()
            logger.info(
                f"Silver Signal: {signal['action']} | Score: {signal['net_score']} | "
                f"GSR: {signal.get('gsr_ratio', 'N/A')} | Conf: {signal['confidence']}"
            )
        except Exception as e:
            logger.error(f"Full score error: {e}")
        await asyncio.sleep(900)


async def run_oanda_loop():
    """OANDA bridge check every 60 seconds."""
    while True:
        try:
            result = await oanda.process_signal()
            if result.get("executed") and result["executed"] != "NONE":
                logger.info(f"OANDA silver trade: {result}")
        except Exception as e:
            logger.error(f"OANDA loop error: {e}")
        await asyncio.sleep(60)


def _load_key(filename: str, env_var: str, default: str = "") -> str:
    # Check silver/data first, then parent MadEye/data
    for base in [DATA_DIR, DATA_DIR.parent.parent / "data"]:
        path = base / filename
        if path.exists():
            key = path.read_text().strip()
            if key:
                os.environ[env_var] = key
                return key
    return os.environ.get(env_var, default)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global scorer, oanda, background_tasks

    logger.info("=" * 60)
    logger.info("MadEye Silver (XAG/USD) Engine starting...")
    logger.info("=" * 60)

    # Load API keys
    newsapi_key = _load_key("newsapi_key.txt", "NEWSAPI_KEY")
    fred_key = _load_key("fred_api_key.txt", "FRED_API_KEY", "DEMO_KEY")
    av_key = _load_key("alphavantage_key.txt", "ALPHAVANTAGE_KEY")

    logger.info(f"API keys: NewsAPI={'yes' if newsapi_key else 'no'}, "
                f"FRED={'yes' if fred_key != 'DEMO_KEY' else 'demo'}, "
                f"AlphaVantage={'yes' if av_key else 'no'}")

    # Initialize scorer
    scorer = SilverScorer(
        newsapi_key=newsapi_key,
        fred_key=fred_key,
        alphavantage_key=av_key,
    )

    # Initialize OANDA bridge
    oanda = OANDABridgeSilver()

    # Initial collection
    logger.info("Running initial silver data collection...")
    try:
        signal = await scorer.run_all()
        logger.info(
            f"Initial signal: {signal['action']} | Score: {signal['net_score']} | "
            f"GSR: {signal.get('gsr_ratio', 'N/A')}"
        )
    except Exception as e:
        logger.error(f"Initial collection failed: {e}")

    # Background tasks
    background_tasks = [
        asyncio.create_task(run_tier1_loop()),
        asyncio.create_task(run_tier2_loop()),
        asyncio.create_task(run_tier3_loop()),
        asyncio.create_task(run_full_score_loop()),
        asyncio.create_task(run_oanda_loop()),
    ]
    logger.info(f"Started {len(background_tasks)} background loops")

    yield

    logger.info("MadEye Silver shutting down...")
    for task in background_tasks:
        task.cancel()
    await asyncio.gather(*background_tasks, return_exceptions=True)
    if scorer:
        await scorer.close()
    if oanda:
        await oanda.close()
    logger.info("MadEye Silver shutdown complete")


app = FastAPI(
    title="MadEye Silver",
    description="XAG/USD Trading Signal Engine -- 10 Factor Analysis",
    version="1.0.0",
    lifespan=lifespan,
)

STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    html_path = STATIC_DIR / "index.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text())
    return HTMLResponse(content="<h1>MadEye Silver</h1><p>Dashboard not found.</p>")


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
    return JSONResponse(content={
        "timestamp": signal.get("timestamp"),
        "factors": signal.get("factor_scores", {}),
        "factor_weights": {k: {"weight": v} for k, v in
            {
                "gold_silver_ratio": 3.0,
                "industrial_demand": 2.25,
                "dxy_silver": 1.8,
                "real_rates_silver": 1.5,
                "etf_flows_silver": 1.5,
                "technical_silver": 1.5,
                "comex_silver": 1.2,
                "geopolitical_silver": 1.2,
                "copper_correlation": 1.05,
                "seasonal_silver": 0.75,
            }.items()
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
    """Get live silver price from Yahoo Finance."""
    try:
        import yfinance as yf

        silver = yf.Ticker("SI=F")
        gold = yf.Ticker("GC=F")
        copper = yf.Ticker("HG=F")

        silver_hist = silver.history(period="5d")
        gold_hist = gold.history(period="5d")
        copper_hist = copper.history(period="5d")

        if silver_hist.empty:
            raise HTTPException(status_code=404, detail="No silver price data")

        latest = silver_hist.iloc[-1]
        prev_close = silver_hist.iloc[-2]["Close"] if len(silver_hist) >= 2 else latest["Close"]

        silver_price = float(latest["Close"])
        gold_price = float(gold_hist.iloc[-1]["Close"]) if not gold_hist.empty else 0
        copper_price = float(copper_hist.iloc[-1]["Close"]) if not copper_hist.empty else 0
        gsr = gold_price / silver_price if silver_price > 0 else 0

        return JSONResponse(content={
            "symbol": "SI=F",
            "name": "Silver (XAG/USD)",
            "price": round(silver_price, 2),
            "open": round(float(latest["Open"]), 2),
            "high": round(float(latest["High"]), 2),
            "low": round(float(latest["Low"]), 2),
            "volume": int(latest["Volume"]),
            "prev_close": round(float(prev_close), 2),
            "change": round(silver_price - float(prev_close), 2),
            "change_pct": round((silver_price - float(prev_close)) / float(prev_close) * 100, 2),
            "gold_price": round(gold_price, 2),
            "gold_silver_ratio": round(gsr, 2),
            "copper_price": round(copper_price, 4),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "history": [
                {
                    "date": str(idx.date()),
                    "close": round(float(row["Close"]), 2),
                    "volume": int(row["Volume"]),
                }
                for idx, row in silver_hist.iterrows()
            ],
        })
    except ImportError:
        raise HTTPException(status_code=500, detail="yfinance not installed")
    except Exception as e:
        logger.error(f"Price fetch error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/oanda/status")
async def oanda_status():
    if oanda is None:
        raise HTTPException(status_code=503, detail="OANDA not initialized")
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
    if scorer is None:
        raise HTTPException(status_code=503, detail="Scorer not initialized")
    signal = await scorer.run_all()
    return JSONResponse(content={"status": "refreshed", "signal": signal})


@app.get("/api/health")
async def health():
    signal = scorer.get_current_signal() if scorer else None
    return JSONResponse(content={
        "status": "ok",
        "engine": "MadEye Silver",
        "version": "1.0.0",
        "instrument": "XAG/USD",
        "has_signal": signal is not None,
        "oanda_configured": oanda.is_configured if oanda else False,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("MADEYE_SILVER_PORT", "8802"))
    logger.info(f"Starting MadEye Silver on port {port}")
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False, log_level="info")
