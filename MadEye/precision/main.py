"""
MadEye Precision Mode -- FastAPI Application
Port 8803

Background loops:
- Precision engine: every 5 minutes (evaluate all 3 commodities)
- Position manager: every 30 seconds (check exits, trailing stops)
"""

import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# Setup logging
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(DATA_DIR / "precision.log", mode="a"),
    ],
)
logger = logging.getLogger("madeye.precision")

from engine import PrecisionEngine
from confirmations import ConfirmationChecker
from trader import PrecisionTrader

# Globals
engine = None
confirmations = None
trader = None
background_tasks = []


async def precision_engine_loop():
    """Run precision engine every 5 minutes."""
    while True:
        try:
            logger.info("Precision engine evaluation starting...")
            signals = await engine.evaluate_all(confirmations)

            # Process signals through trader
            await trader.process_signals(signals)

            for commodity, sig in signals.items():
                s = sig.get("signal", "?")
                n = sig.get("n_agreeing", 0)
                total = sig.get("total_collectors", 0)
                logger.info(f"  {commodity.upper()}: {s} ({n}/{total} agree)")

        except Exception as e:
            logger.error(f"Precision engine loop error: {e}", exc_info=True)
        await asyncio.sleep(300)  # 5 minutes


async def position_manager_loop():
    """Check positions every 30 seconds for exits."""
    while True:
        try:
            if trader and trader.positions:
                await trader.manage_positions()
        except Exception as e:
            logger.error(f"Position manager error: {e}", exc_info=True)
        await asyncio.sleep(30)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global engine, confirmations, trader, background_tasks

    logger.info("=" * 60)
    logger.info("MadEye PRECISION MODE starting on port 8803...")
    logger.info("=" * 60)

    # Initialize components
    engine = PrecisionEngine()
    confirmations = ConfirmationChecker()
    trader = PrecisionTrader()

    logger.info(f"OANDA configured: {trader.is_configured}")
    logger.info(f"Dry run mode: {trader.is_dry_run}")
    logger.info(f"Open positions: {len(trader.positions)}")

    # Run initial evaluation
    try:
        logger.info("Running initial precision evaluation...")
        signals = await engine.evaluate_all(confirmations)
        for commodity, sig in signals.items():
            logger.info(
                f"  {commodity.upper()}: {sig.get('signal', '?')} "
                f"({sig.get('n_agreeing', 0)}/{sig.get('total_collectors', 0)} agree)"
            )
    except Exception as e:
        logger.error(f"Initial evaluation failed: {e}")

    # Start background loops
    background_tasks = [
        asyncio.create_task(precision_engine_loop()),
        asyncio.create_task(position_manager_loop()),
    ]
    logger.info("Background loops started (engine=5min, positions=30s)")

    yield

    # Shutdown
    logger.info("Precision mode shutting down...")
    for task in background_tasks:
        task.cancel()
    await asyncio.gather(*background_tasks, return_exceptions=True)
    if engine:
        await engine.close()
    if confirmations:
        await confirmations.close()
    if trader:
        await trader.close()
    logger.info("Precision mode shutdown complete")


# FastAPI app
app = FastAPI(
    title="MadEye Precision",
    description="Precision Mode Trading Engine -- 90%+ Win Rate Target",
    version="1.0.0",
    lifespan=lifespan,
)

# Static files
STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# --- Routes ---

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    html_path = STATIC_DIR / "index.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text())
    return HTMLResponse(content="<h1>MadEye Precision</h1><p>Dashboard not found</p>")


@app.get("/api/signal")
async def get_signals():
    """Current precision signals for all 3 commodities."""
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    signals = engine.get_current_signals()
    if not signals:
        raise HTTPException(status_code=404, detail="No signals computed yet")

    return JSONResponse(content=signals)


@app.get("/api/signal/{commodity}")
async def get_signal_commodity(commodity: str):
    """Get precision signal for a specific commodity."""
    signals = engine.get_current_signals() if engine else {}
    if commodity not in signals:
        raise HTTPException(status_code=404, detail=f"No signal for {commodity}")
    return JSONResponse(content=signals[commodity])


@app.get("/api/positions")
async def get_positions():
    """All open positions with live P/L."""
    if trader is None:
        raise HTTPException(status_code=503, detail="Trader not initialized")

    positions = trader.get_positions()
    return JSONResponse(content={
        "count": len(positions),
        "positions": positions,
        "max_positions": 3,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


@app.get("/api/history")
async def get_history(limit: int = 100):
    """Trade history with full details."""
    if trader is None:
        raise HTTPException(status_code=503, detail="Trader not initialized")

    history = trader.get_trade_history(limit=limit)
    return JSONResponse(content={
        "count": len(history),
        "trades": history,
    })


@app.get("/api/performance")
async def get_performance():
    """Win rate, P/L, drawdown, per-commodity breakdown."""
    if trader is None:
        raise HTTPException(status_code=503, detail="Trader not initialized")

    perf = trader.get_performance()
    perf["timestamp"] = datetime.now(timezone.utc).isoformat()
    perf["dry_run"] = trader.is_dry_run
    return JSONResponse(content=perf)


@app.get("/api/engine/history")
async def get_engine_history(limit: int = 100):
    """Signal evaluation history from precision engine."""
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    history = engine.get_history(limit=limit)
    return JSONResponse(content={
        "count": len(history),
        "evaluations": history,
    })


@app.post("/api/refresh")
async def force_refresh():
    """Force a full precision evaluation cycle."""
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    signals = await engine.evaluate_all(confirmations)
    await trader.process_signals(signals)

    return JSONResponse(content={
        "status": "refreshed",
        "signals": signals,
        "positions": trader.get_positions(),
    })


@app.get("/api/health")
async def health():
    return JSONResponse(content={
        "status": "ok",
        "engine": "MadEye Precision",
        "version": "1.0.0",
        "dry_run": trader.is_dry_run if trader else True,
        "open_positions": len(trader.positions) if trader else 0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PRECISION_PORT", "8803"))
    logger.info(f"Starting MadEye Precision on port {port}")
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        log_level="info",
    )
