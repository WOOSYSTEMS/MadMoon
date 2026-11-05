"""
MadEye Precision Mode -- OANDA Trader
Executes trades based on precision signals.
5x leverage, 5% SL, 1.5% TP, trailing stop after +1%.
Max 3 positions (1 per commodity).
"""

import json
import logging
import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import httpx

logger = logging.getLogger("madeye.precision")

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# OANDA config paths
OANDA_CONFIG_PATHS = [
    Path.home() / ".oanda_config.json",
    Path("/home/ec2-user/MadMoonEye/backend/data/oanda_config.json"),
    Path(__file__).parent / "data" / "oanda_config.json",
]

# Position parameters
LEVERAGE = 5
STOP_LOSS_PCT = 0.05       # 5% stop loss
TAKE_PROFIT_PCT = 0.015    # 1.5% take profit
TRAILING_TRIGGER_PCT = 0.01  # Start trailing after +1% gain
TRAILING_DISTANCE_PCT = 0.008  # Trail 0.8% below peak
MAX_HOLD_HOURS = 24        # Max hold time
WEEKEND_CLOSE_HOUR_UTC = 20  # Friday 1PM PT = 20:00 UTC (PDT)

# Instrument configs
INSTRUMENTS = {
    "oil": {
        "instrument": "BCO_USD",
        "pip_size": 0.01,
        "min_units": 1,
    },
    "gold": {
        "instrument": "XAU_USD",
        "pip_size": 0.01,
        "min_units": 1,
    },
    "silver": {
        "instrument": "XAG_USD",
        "pip_size": 0.001,
        "min_units": 1,
    },
}


class Position:
    """Tracks a single open position."""

    def __init__(self, commodity: str, instrument: str, direction: str,
                 entry_price: float, units: int, entry_time: str,
                 voters: List[str] = None, trade_id: str = None):
        self.commodity = commodity
        self.instrument = instrument
        self.direction = direction  # "BUY" or "SELL"
        self.entry_price = entry_price
        self.units = units
        self.entry_time = entry_time
        self.voters = voters or []
        self.trade_id = trade_id

        # Tracking
        self.peak_price = entry_price
        self.trailing_active = False
        self.trailing_stop_price = 0.0
        self.current_price = entry_price
        self.unrealized_pl = 0.0
        self.unrealized_pl_pct = 0.0

    def update_price(self, price: float):
        """Update current price and trailing stop."""
        self.current_price = price

        # Calculate P/L
        if self.direction == "BUY":
            self.unrealized_pl_pct = (price - self.entry_price) / self.entry_price * 100
        else:
            self.unrealized_pl_pct = (self.entry_price - price) / self.entry_price * 100

        self.unrealized_pl = self.unrealized_pl_pct / 100 * self.entry_price * self.units

        # Update peak and trailing stop
        if self.direction == "BUY":
            if price > self.peak_price:
                self.peak_price = price
        else:
            if price < self.peak_price or self.peak_price == self.entry_price:
                self.peak_price = price

        # Activate trailing stop after +1% gain
        if self.unrealized_pl_pct >= TRAILING_TRIGGER_PCT * 100:
            self.trailing_active = True
            if self.direction == "BUY":
                self.trailing_stop_price = self.peak_price * (1 - TRAILING_DISTANCE_PCT)
            else:
                self.trailing_stop_price = self.peak_price * (1 + TRAILING_DISTANCE_PCT)

    def should_take_profit(self) -> bool:
        return self.unrealized_pl_pct >= TAKE_PROFIT_PCT * 100

    def should_stop_loss(self) -> bool:
        return self.unrealized_pl_pct <= -STOP_LOSS_PCT * 100

    def should_trailing_stop(self) -> bool:
        if not self.trailing_active:
            return False
        if self.direction == "BUY":
            return self.current_price <= self.trailing_stop_price
        else:
            return self.current_price >= self.trailing_stop_price

    def should_time_exit(self) -> bool:
        """Check if position has been held too long (24h)."""
        try:
            entry = datetime.fromisoformat(self.entry_time)
            now = datetime.now(timezone.utc)
            return (now - entry).total_seconds() > MAX_HOLD_HOURS * 3600
        except Exception:
            return False

    def should_weekend_close(self) -> bool:
        """Close before weekend: Friday 1PM PT = 20:00 UTC."""
        now = datetime.now(timezone.utc)
        return now.weekday() == 4 and now.hour >= WEEKEND_CLOSE_HOUR_UTC

    def to_dict(self) -> dict:
        return {
            "commodity": self.commodity,
            "instrument": self.instrument,
            "direction": self.direction,
            "entry_price": self.entry_price,
            "current_price": self.current_price,
            "units": self.units,
            "entry_time": self.entry_time,
            "trade_id": self.trade_id,
            "unrealized_pl": round(self.unrealized_pl, 2),
            "unrealized_pl_pct": round(self.unrealized_pl_pct, 3),
            "peak_price": self.peak_price,
            "trailing_active": self.trailing_active,
            "trailing_stop_price": round(self.trailing_stop_price, 4),
            "voters": self.voters,
        }


class PrecisionTrader:
    """OANDA execution engine for precision mode."""

    def __init__(self):
        self.config = self._load_config()
        self._client: Optional[httpx.AsyncClient] = None
        self.positions: Dict[str, Position] = {}  # commodity -> Position
        self.trade_history: List[Dict] = []
        self._load_state()

    def _load_config(self) -> Dict:
        for path in OANDA_CONFIG_PATHS:
            if path.exists():
                try:
                    with open(path) as f:
                        config = json.load(f)
                    logger.info(f"OANDA config loaded from {path}")
                    return config
                except Exception as e:
                    logger.warning(f"Failed to load config from {path}: {e}")

        logger.warning("No OANDA config found -- precision trader in DRY RUN mode")
        return {
            "api_url": "https://api-fxpractice.oanda.com",
            "account_id": "",
            "api_key": "",
            "dry_run": True,
        }

    def _load_state(self):
        """Load positions and trade history from disk."""
        # Trade history
        path = DATA_DIR / "precision_trades.json"
        if path.exists():
            try:
                with open(path) as f:
                    self.trade_history = json.load(f)
            except Exception:
                self.trade_history = []

        # Open positions
        path = DATA_DIR / "precision_positions.json"
        if path.exists():
            try:
                with open(path) as f:
                    pos_data = json.load(f)
                for commodity, pd in pos_data.items():
                    self.positions[commodity] = Position(
                        commodity=pd["commodity"],
                        instrument=pd["instrument"],
                        direction=pd["direction"],
                        entry_price=pd["entry_price"],
                        units=pd["units"],
                        entry_time=pd["entry_time"],
                        voters=pd.get("voters", []),
                        trade_id=pd.get("trade_id"),
                    )
                    self.positions[commodity].peak_price = pd.get("peak_price", pd["entry_price"])
                    self.positions[commodity].trailing_active = pd.get("trailing_active", False)
                    self.positions[commodity].trailing_stop_price = pd.get("trailing_stop_price", 0)
            except Exception as e:
                logger.error(f"Failed to load positions: {e}")

    def _save_state(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        # Save positions
        pos_data = {k: v.to_dict() for k, v in self.positions.items()}
        try:
            with open(DATA_DIR / "precision_positions.json", "w") as f:
                json.dump(pos_data, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save positions: {e}")

        # Save trade history (last 500)
        try:
            with open(DATA_DIR / "precision_trades.json", "w") as f:
                json.dump(self.trade_history[-500:], f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save trade history: {e}")

    @property
    def is_configured(self) -> bool:
        return bool(self.config.get("account_id") and self.config.get("api_key"))

    @property
    def is_dry_run(self) -> bool:
        return self.config.get("dry_run", True) or not self.is_configured

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            api_key = self.config.get("api_key", "")
            self._client = httpx.AsyncClient(
                base_url=self.config.get("api_url", "https://api-fxpractice.oanda.com"),
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "Accept-Datetime-Format": "RFC3339",
                },
                timeout=15.0,
            )
        return self._client

    async def get_account_balance(self) -> float:
        """Get current account balance in account currency."""
        if self.is_dry_run:
            return 100.0  # Default $100 CAD for dry run

        try:
            client = await self._get_client()
            account_id = self.config["account_id"]
            resp = await client.get(f"/v3/accounts/{account_id}/summary")
            resp.raise_for_status()
            data = resp.json()
            return float(data.get("account", {}).get("balance", 100))
        except Exception as e:
            logger.error(f"Balance fetch error: {e}")
            return 100.0

    def _compute_units(self, balance: float, price: float, commodity: str) -> int:
        """Compute position size: full balance * 5x leverage."""
        if price <= 0:
            return 0

        # Full balance compounding with 5x leverage
        notional = balance * LEVERAGE
        units = int(notional / price)

        min_units = INSTRUMENTS.get(commodity, {}).get("min_units", 1)
        return max(min_units, units)

    async def get_current_price(self, instrument: str) -> Optional[float]:
        """Get current price from OANDA."""
        if self.is_dry_run:
            # Use Yahoo Finance as fallback for dry run
            try:
                import yfinance as yf
                symbol_map = {
                    "BCO_USD": "BZ=F",
                    "XAU_USD": "GC=F",
                    "XAG_USD": "SI=F",
                }
                symbol = symbol_map.get(instrument, instrument)
                ticker = yf.Ticker(symbol)
                hist = ticker.history(period="1d", interval="1m")
                if not hist.empty:
                    return float(hist.iloc[-1]["Close"])
            except Exception:
                pass
            return None

        try:
            client = await self._get_client()
            account_id = self.config["account_id"]
            resp = await client.get(
                f"/v3/accounts/{account_id}/pricing",
                params={"instruments": instrument},
            )
            resp.raise_for_status()
            data = resp.json()
            prices = data.get("prices", [])
            if prices:
                bid = float(prices[0].get("bids", [{}])[0].get("price", 0))
                ask = float(prices[0].get("asks", [{}])[0].get("price", 0))
                return (bid + ask) / 2
        except Exception as e:
            logger.error(f"Price fetch error for {instrument}: {e}")
        return None

    async def open_position(self, commodity: str, direction: str,
                            voters: List[str] = None, confidence: float = 0.0) -> Dict:
        """Open a new position for a commodity."""
        if commodity in self.positions:
            return {
                "status": "SKIP",
                "reason": f"Already have open {commodity} position",
            }

        if len(self.positions) >= 3:
            return {
                "status": "SKIP",
                "reason": "Max 3 positions reached",
            }

        inst_config = INSTRUMENTS.get(commodity)
        if not inst_config:
            return {"status": "ERROR", "reason": f"Unknown commodity: {commodity}"}

        instrument = inst_config["instrument"]
        balance = await self.get_account_balance()
        price = await self.get_current_price(instrument)

        if not price:
            return {"status": "ERROR", "reason": f"Could not get price for {instrument}"}

        units = self._compute_units(balance, price, commodity)
        if units <= 0:
            return {"status": "ERROR", "reason": "Computed 0 units"}

        # For SELL, units are negative
        order_units = units if direction == "BUY" else -units

        # Calculate SL and TP prices
        if direction == "BUY":
            sl_price = round(price * (1 - STOP_LOSS_PCT), 5)
            tp_price = round(price * (1 + TAKE_PROFIT_PCT), 5)
        else:
            sl_price = round(price * (1 + STOP_LOSS_PCT), 5)
            tp_price = round(price * (1 - TAKE_PROFIT_PCT), 5)

        trade_info = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": "OPEN",
            "commodity": commodity,
            "instrument": instrument,
            "direction": direction,
            "units": abs(units),
            "price": price,
            "sl_price": sl_price,
            "tp_price": tp_price,
            "balance": balance,
            "leverage": LEVERAGE,
            "confidence": confidence,
            "voters": voters or [],
        }

        trade_id = None

        if self.is_dry_run:
            trade_info["status"] = "DRY_RUN"
            trade_id = f"dry_{commodity}_{int(datetime.now(timezone.utc).timestamp())}"
            logger.info(
                f"[DRY RUN] OPEN {direction} {commodity}: {units} units @ {price:.2f} "
                f"SL={sl_price:.2f} TP={tp_price:.2f}"
            )
        else:
            try:
                client = await self._get_client()
                account_id = self.config["account_id"]

                order_data = {
                    "order": {
                        "type": "MARKET",
                        "instrument": instrument,
                        "units": str(order_units),
                        "timeInForce": "FOK",
                        "positionFill": "DEFAULT",
                        "stopLossOnFill": {
                            "price": str(sl_price),
                            "timeInForce": "GTC",
                        },
                        "takeProfitOnFill": {
                            "price": str(tp_price),
                            "timeInForce": "GTC",
                        },
                    }
                }

                resp = await client.post(
                    f"/v3/accounts/{account_id}/orders",
                    json=order_data,
                )
                resp.raise_for_status()
                result = resp.json()

                fill_tx = result.get("orderFillTransaction", {})
                trade_id = fill_tx.get("tradeOpened", {}).get("tradeID")
                fill_price = float(fill_tx.get("price", price))

                trade_info["status"] = "FILLED"
                trade_info["fill_price"] = fill_price
                trade_info["trade_id"] = trade_id
                trade_info["oanda_response"] = result

                price = fill_price  # Use actual fill price

                logger.info(
                    f"OANDA OPEN {direction} {commodity}: {units} @ {fill_price:.2f} "
                    f"SL={sl_price:.2f} TP={tp_price:.2f} trade_id={trade_id}"
                )

            except Exception as e:
                trade_info["status"] = "ERROR"
                trade_info["error"] = str(e)
                logger.error(f"OANDA open error for {commodity}: {e}")
                self.trade_history.append(trade_info)
                self._save_state()
                return trade_info

        # Track position locally
        pos = Position(
            commodity=commodity,
            instrument=instrument,
            direction=direction,
            entry_price=price,
            units=abs(units),
            entry_time=datetime.now(timezone.utc).isoformat(),
            voters=voters or [],
            trade_id=trade_id,
        )
        self.positions[commodity] = pos

        self.trade_history.append(trade_info)
        self._save_state()
        return trade_info

    async def close_position(self, commodity: str, reason: str = "manual") -> Dict:
        """Close an open position."""
        if commodity not in self.positions:
            return {"status": "SKIP", "reason": f"No open {commodity} position"}

        pos = self.positions[commodity]
        current_price = await self.get_current_price(pos.instrument) or pos.current_price

        trade_info = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": "CLOSE",
            "commodity": commodity,
            "instrument": pos.instrument,
            "direction": pos.direction,
            "entry_price": pos.entry_price,
            "exit_price": current_price,
            "units": pos.units,
            "entry_time": pos.entry_time,
            "reason": reason,
            "voters": pos.voters,
        }

        # Calculate P/L
        if pos.direction == "BUY":
            pl_pct = (current_price - pos.entry_price) / pos.entry_price * 100
        else:
            pl_pct = (pos.entry_price - current_price) / pos.entry_price * 100

        pl_amount = pl_pct / 100 * pos.entry_price * pos.units
        trade_info["pl_pct"] = round(pl_pct, 3)
        trade_info["pl_amount"] = round(pl_amount, 2)

        if self.is_dry_run:
            trade_info["status"] = "DRY_RUN"
            logger.info(
                f"[DRY RUN] CLOSE {commodity} {pos.direction}: "
                f"entry={pos.entry_price:.2f} exit={current_price:.2f} "
                f"P/L={pl_pct:+.2f}% ({reason})"
            )
        else:
            try:
                client = await self._get_client()
                account_id = self.config["account_id"]

                # Close by putting opposite units
                if pos.direction == "BUY":
                    resp = await client.put(
                        f"/v3/accounts/{account_id}/positions/{pos.instrument}/close",
                        json={"longUnits": "ALL"},
                    )
                else:
                    resp = await client.put(
                        f"/v3/accounts/{account_id}/positions/{pos.instrument}/close",
                        json={"shortUnits": "ALL"},
                    )
                resp.raise_for_status()
                result = resp.json()
                trade_info["status"] = "CLOSED"
                trade_info["oanda_response"] = result

                logger.info(
                    f"OANDA CLOSE {commodity} {pos.direction}: "
                    f"entry={pos.entry_price:.2f} exit={current_price:.2f} "
                    f"P/L={pl_pct:+.2f}% ({reason})"
                )

            except Exception as e:
                trade_info["status"] = "ERROR"
                trade_info["error"] = str(e)
                logger.error(f"OANDA close error for {commodity}: {e}")

        # Remove from active positions
        del self.positions[commodity]

        self.trade_history.append(trade_info)
        self._save_state()
        return trade_info

    async def manage_positions(self):
        """Check all open positions for exit conditions. Called every 30 seconds."""
        for commodity in list(self.positions.keys()):
            pos = self.positions[commodity]

            # Get fresh price
            price = await self.get_current_price(pos.instrument)
            if not price:
                continue

            pos.update_price(price)

            # Check exit conditions in priority order
            if pos.should_take_profit():
                await self.close_position(commodity, reason="TAKE_PROFIT")
                continue

            if pos.should_stop_loss():
                await self.close_position(commodity, reason="STOP_LOSS")
                continue

            if pos.should_trailing_stop():
                await self.close_position(
                    commodity,
                    reason=f"TRAILING_STOP (trail={pos.trailing_stop_price:.4f})"
                )
                continue

            if pos.should_time_exit():
                await self.close_position(commodity, reason="MAX_HOLD_24H")
                continue

            if pos.should_weekend_close():
                await self.close_position(commodity, reason="WEEKEND_CLOSE")
                continue

        self._save_state()

    async def process_signals(self, signals: Dict[str, Dict]):
        """Process precision engine signals and open/close positions."""
        for commodity, signal_data in signals.items():
            sig = signal_data.get("signal", "HOLD")

            if sig in ("BUY", "SELL"):
                if commodity not in self.positions:
                    voters = signal_data.get("bullish_voters", []) if sig == "BUY" \
                        else signal_data.get("bearish_voters", [])
                    confidence = signal_data.get("confidence", 0)

                    await self.open_position(
                        commodity=commodity,
                        direction=sig,
                        voters=voters,
                        confidence=confidence,
                    )

            # If signal reversed while holding, close existing position
            if commodity in self.positions:
                pos = self.positions[commodity]
                if (sig == "BUY" and pos.direction == "SELL") or \
                   (sig == "SELL" and pos.direction == "BUY"):
                    await self.close_position(commodity, reason="SIGNAL_REVERSAL")

    def get_positions(self) -> List[Dict]:
        return [pos.to_dict() for pos in self.positions.values()]

    def get_trade_history(self, limit: int = 100) -> List[Dict]:
        return self.trade_history[-limit:]

    def get_performance(self) -> Dict:
        """Calculate performance metrics from trade history."""
        closed_trades = [
            t for t in self.trade_history
            if t.get("action") == "CLOSE" and "pl_pct" in t
        ]

        if not closed_trades:
            return {
                "total_trades": 0,
                "win_rate": 0,
                "total_pl_pct": 0,
                "avg_win": 0,
                "avg_loss": 0,
                "best_trade": 0,
                "worst_trade": 0,
                "max_drawdown": 0,
                "per_commodity": {},
            }

        wins = [t for t in closed_trades if t["pl_pct"] > 0]
        losses = [t for t in closed_trades if t["pl_pct"] <= 0]

        total_pl_pct = sum(t["pl_pct"] for t in closed_trades)
        win_rate = len(wins) / len(closed_trades) * 100 if closed_trades else 0

        # Per-commodity breakdown
        per_commodity = {}
        for commodity in ["oil", "gold", "silver"]:
            ct = [t for t in closed_trades if t.get("commodity") == commodity]
            if ct:
                cw = [t for t in ct if t["pl_pct"] > 0]
                per_commodity[commodity] = {
                    "trades": len(ct),
                    "wins": len(cw),
                    "win_rate": round(len(cw) / len(ct) * 100, 1) if ct else 0,
                    "total_pl_pct": round(sum(t["pl_pct"] for t in ct), 2),
                }

        # Max drawdown (simple cumulative)
        cumulative = 0
        peak = 0
        max_dd = 0
        for t in closed_trades:
            cumulative += t["pl_pct"]
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative
            if dd > max_dd:
                max_dd = dd

        return {
            "total_trades": len(closed_trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(win_rate, 1),
            "total_pl_pct": round(total_pl_pct, 2),
            "avg_win": round(
                sum(t["pl_pct"] for t in wins) / len(wins), 2
            ) if wins else 0,
            "avg_loss": round(
                sum(t["pl_pct"] for t in losses) / len(losses), 2
            ) if losses else 0,
            "best_trade": round(max(t["pl_pct"] for t in closed_trades), 2),
            "worst_trade": round(min(t["pl_pct"] for t in closed_trades), 2),
            "max_drawdown": round(max_dd, 2),
            "per_commodity": per_commodity,
            "open_positions": len(self.positions),
        }

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
