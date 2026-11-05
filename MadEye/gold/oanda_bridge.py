"""
MadEye Gold OANDA Bridge
Connects to OANDA for auto-trading XAU/USD based on MadEye Gold signals.
Sniper logic: only trade when 3+ factors score 8+.
Trailing stop, max 48h hold, no weekends.
"""

import json
import logging
import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Optional

import httpx

logger = logging.getLogger("madeye.gold")

DATA_DIR = Path(__file__).parent / "data"

# OANDA config paths
OANDA_CONFIG_PATHS = [
    Path.home() / ".oanda_config.json",
    Path.home() / ".madeye" / "oanda_config.json",
    DATA_DIR / "oanda_config.json",
]

DEFAULT_INSTRUMENT = "XAU_USD"  # Gold vs USD
DEFAULT_UNITS = 1  # Gold is expensive per unit (1 unit = 1 oz = ~$2600)
STOP_LOSS_DISTANCE = 30.0  # $30 stop loss on gold (~1.2%)
TRAILING_STOP_DISTANCE = 20.0  # $20 trailing stop
MAX_HOLD_HOURS = 48  # Close positions older than 48 hours
MIN_SNIPER_FACTORS = 3  # Need 3+ factors scoring 8+ to enter
MIN_CONFIDENCE = 0.35  # Minimum overall confidence to trade


class GoldOANDABridge:
    """Auto-trading bridge for XAU/USD based on MadEye Gold signals."""

    def __init__(self, config_path: str = None):
        self.config = self._load_config(config_path)
        self._client: Optional[httpx.AsyncClient] = None
        self._running = False
        self._last_action = None
        self._trade_log: list = []
        self._open_trade_time: Optional[datetime] = None
        self._load_trade_log()

    def _load_config(self, config_path: str = None) -> Dict:
        paths_to_try = [Path(config_path)] if config_path else OANDA_CONFIG_PATHS

        for path in paths_to_try:
            if path.exists():
                try:
                    with open(path) as f:
                        config = json.load(f)
                    logger.info(f"OANDA Gold config loaded from {path}")
                    return config
                except Exception as e:
                    logger.warning(f"Failed to load OANDA config from {path}: {e}")

        logger.warning("No OANDA config found -- Gold bridge in dry-run mode")
        return {
            "api_url": "https://api-fxpractice.oanda.com",
            "account_id": "",
            "api_key": "",
            "instrument": DEFAULT_INSTRUMENT,
            "units": DEFAULT_UNITS,
            "dry_run": True,
        }

    def _load_trade_log(self):
        path = DATA_DIR / "oanda_gold_trades.json"
        if path.exists():
            try:
                with open(path) as f:
                    self._trade_log = json.load(f)
            except Exception:
                self._trade_log = []

    def _save_trade_log(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        path = DATA_DIR / "oanda_gold_trades.json"
        try:
            with open(path, "w") as f:
                json.dump(self._trade_log[-500:], f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save gold trade log: {e}")

    async def get_client(self) -> httpx.AsyncClient:
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

    @property
    def is_configured(self) -> bool:
        return bool(self.config.get("account_id") and self.config.get("api_key"))

    @property
    def is_dry_run(self) -> bool:
        return self.config.get("dry_run", True) or not self.is_configured

    async def get_account_summary(self) -> Optional[Dict]:
        if self.is_dry_run:
            return {"balance": "N/A (dry run)", "unrealizedPL": "N/A", "openTradeCount": 0}
        try:
            client = await self.get_client()
            account_id = self.config["account_id"]
            resp = await client.get(f"/v3/accounts/{account_id}/summary")
            resp.raise_for_status()
            return resp.json().get("account", {})
        except Exception as e:
            logger.error(f"OANDA account summary error: {e}")
            return None

    async def get_open_positions(self) -> list:
        if self.is_dry_run:
            return []
        try:
            client = await self.get_client()
            account_id = self.config["account_id"]
            instrument = self.config.get("instrument", DEFAULT_INSTRUMENT)
            resp = await client.get(f"/v3/accounts/{account_id}/positions/{instrument}")
            resp.raise_for_status()
            position = resp.json().get("position", {})

            long_units = int(position.get("long", {}).get("units", "0"))
            short_units = int(position.get("short", {}).get("units", "0"))

            positions = []
            if long_units > 0:
                positions.append({"side": "long", "units": long_units})
            if short_units < 0:
                positions.append({"side": "short", "units": abs(short_units)})
            return positions
        except Exception as e:
            logger.warning(f"OANDA positions error: {e}")
            return []

    def _check_sniper_conditions(self, signal: Dict) -> tuple:
        """Check if 3+ factors score 8+ (sniper entry condition)."""
        factor_scores = signal.get("factor_scores", {})
        high_conviction_factors = []

        for name, data in factor_scores.items():
            raw = data.get("raw_score", 5.0)
            if raw >= 8.0:
                high_conviction_factors.append((name, raw))

        passed = len(high_conviction_factors) >= MIN_SNIPER_FACTORS
        return passed, high_conviction_factors

    def _check_weekend_close(self) -> bool:
        """Should we close before weekend?"""
        now = datetime.now(timezone.utc)
        # Close on Friday after 19:00 UTC (2PM ET)
        return now.weekday() == 4 and now.hour >= 19

    def _check_max_hold(self) -> bool:
        """Has position been held too long?"""
        if self._open_trade_time:
            elapsed = datetime.now(timezone.utc) - self._open_trade_time
            return elapsed > timedelta(hours=MAX_HOLD_HOURS)
        return False

    async def open_long(self, units: int = None, confidence: float = 0.5,
                        net_score: float = 0) -> Dict:
        """Open a long XAU/USD position."""
        if units is None:
            base_units = self.config.get("units", DEFAULT_UNITS)
            # Scale by confidence
            conf_scale = max(0.5, min(1.5, confidence * 2))
            units = max(1, int(base_units * conf_scale))

        instrument = self.config.get("instrument", DEFAULT_INSTRUMENT)

        trade_info = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": "OPEN_LONG",
            "instrument": instrument,
            "units": units,
            "confidence": confidence,
            "net_score": net_score,
        }

        if self.is_dry_run:
            trade_info["status"] = "DRY_RUN"
            trade_info["message"] = (
                f"Would open LONG {units} {instrument} "
                f"(SL=${STOP_LOSS_DISTANCE}, trail=${TRAILING_STOP_DISTANCE})"
            )
            logger.info(f"[DRY RUN] Gold long: {units} {instrument} (conf={confidence:.2f})")
            self._open_trade_time = datetime.now(timezone.utc)
        else:
            try:
                client = await self.get_client()
                account_id = self.config["account_id"]

                order_data = {
                    "order": {
                        "type": "MARKET",
                        "instrument": instrument,
                        "units": str(units),
                        "timeInForce": "FOK",
                        "positionFill": "DEFAULT",
                        "stopLossOnFill": {
                            "distance": str(STOP_LOSS_DISTANCE),
                            "timeInForce": "GTC",
                        },
                        "trailingStopLossOnFill": {
                            "distance": str(TRAILING_STOP_DISTANCE),
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
                trade_info["status"] = "FILLED"
                trade_info["response"] = result
                trade_info["fill_price"] = (
                    result.get("orderFillTransaction", {}).get("price", "unknown")
                )
                self._open_trade_time = datetime.now(timezone.utc)
                logger.info(
                    f"OANDA Gold long: {units} {instrument} @ {trade_info['fill_price']}"
                )
            except Exception as e:
                trade_info["status"] = "ERROR"
                trade_info["error"] = str(e)
                logger.error(f"OANDA Gold long error: {e}")

        self._trade_log.append(trade_info)
        self._save_trade_log()
        return trade_info

    async def open_short(self, units: int = None, confidence: float = 0.5,
                         net_score: float = 0) -> Dict:
        """Open a short XAU/USD position."""
        if units is None:
            base_units = self.config.get("units", DEFAULT_UNITS)
            conf_scale = max(0.5, min(1.5, confidence * 2))
            units = max(1, int(base_units * conf_scale))

        instrument = self.config.get("instrument", DEFAULT_INSTRUMENT)

        trade_info = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": "OPEN_SHORT",
            "instrument": instrument,
            "units": units,
            "confidence": confidence,
            "net_score": net_score,
        }

        if self.is_dry_run:
            trade_info["status"] = "DRY_RUN"
            trade_info["message"] = f"Would open SHORT {units} {instrument}"
            logger.info(f"[DRY RUN] Gold short: {units} {instrument}")
            self._open_trade_time = datetime.now(timezone.utc)
        else:
            try:
                client = await self.get_client()
                account_id = self.config["account_id"]
                order_data = {
                    "order": {
                        "type": "MARKET",
                        "instrument": instrument,
                        "units": str(-units),
                        "timeInForce": "FOK",
                        "positionFill": "DEFAULT",
                        "stopLossOnFill": {
                            "distance": str(STOP_LOSS_DISTANCE),
                            "timeInForce": "GTC",
                        },
                        "trailingStopLossOnFill": {
                            "distance": str(TRAILING_STOP_DISTANCE),
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
                trade_info["status"] = "FILLED"
                trade_info["response"] = result
                self._open_trade_time = datetime.now(timezone.utc)
            except Exception as e:
                trade_info["status"] = "ERROR"
                trade_info["error"] = str(e)

        self._trade_log.append(trade_info)
        self._save_trade_log()
        return trade_info

    async def close_all(self) -> Dict:
        instrument = self.config.get("instrument", DEFAULT_INSTRUMENT)

        trade_info = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": "CLOSE_ALL",
            "instrument": instrument,
        }

        if self.is_dry_run:
            trade_info["status"] = "DRY_RUN"
            trade_info["message"] = f"Would close all {instrument} positions"
            logger.info(f"[DRY RUN] Close all gold positions")
            self._open_trade_time = None
        else:
            try:
                client = await self.get_client()
                account_id = self.config["account_id"]
                resp = await client.put(
                    f"/v3/accounts/{account_id}/positions/{instrument}/close",
                    json={"longUnits": "ALL"},
                )
                if resp.status_code == 200:
                    trade_info["long_closed"] = resp.json()
                resp = await client.put(
                    f"/v3/accounts/{account_id}/positions/{instrument}/close",
                    json={"shortUnits": "ALL"},
                )
                if resp.status_code == 200:
                    trade_info["short_closed"] = resp.json()
                trade_info["status"] = "CLOSED"
                self._open_trade_time = None
            except Exception as e:
                trade_info["status"] = "ERROR"
                trade_info["error"] = str(e)

        self._trade_log.append(trade_info)
        self._save_trade_log()
        return trade_info

    async def process_signal(self) -> Dict:
        """Read current signal and execute sniper trade logic."""
        signal_path = DATA_DIR / "current_signal.json"
        if not signal_path.exists():
            return {"action": "NONE", "reason": "No signal file found"}

        try:
            with open(signal_path) as f:
                signal = json.load(f)
        except Exception as e:
            return {"action": "NONE", "reason": f"Signal file read error: {e}"}

        action = signal.get("action", "HOLD")
        net_score = signal.get("net_score", 0)
        confidence = signal.get("confidence", 0)

        positions = await self.get_open_positions()
        has_position = len(positions) > 0

        result = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "signal_action": action,
            "net_score": net_score,
            "confidence": confidence,
            "has_position": has_position,
            "executed": None,
        }

        # --- Weekend close ---
        if has_position and self._check_weekend_close():
            trade = await self.close_all()
            result["executed"] = trade
            result["reason"] = "Weekend close -- closing all gold positions"
            return result

        # --- Max hold time ---
        if has_position and self._check_max_hold():
            trade = await self.close_all()
            result["executed"] = trade
            result["reason"] = f"Max hold ({MAX_HOLD_HOURS}h) exceeded -- closing"
            return result

        # --- Minimum confidence ---
        if confidence < MIN_CONFIDENCE:
            result["executed"] = "NONE"
            result["reason"] = f"Confidence too low ({confidence:.2f} < {MIN_CONFIDENCE})"
            return result

        # --- Sniper check for entry ---
        sniper_passed, high_factors = self._check_sniper_conditions(signal)

        if action in ("BUY", "STRONG_BUY"):
            if not has_position:
                if sniper_passed or action == "STRONG_BUY":
                    trade = await self.open_long(confidence=confidence, net_score=net_score)
                    factor_names = [f"{n}={s:.1f}" for n, s in high_factors]
                    result["executed"] = trade
                    result["reason"] = (
                        f"SNIPER BUY: {len(high_factors)} factors at 8+ "
                        f"[{', '.join(factor_names)}]"
                    )
                else:
                    result["executed"] = "NONE"
                    result["reason"] = (
                        f"BUY signal but only {len(high_factors)} factors at 8+ "
                        f"(need {MIN_SNIPER_FACTORS})"
                    )
            else:
                result["executed"] = "NONE"
                result["reason"] = "BUY signal but already in position"

        elif action in ("SELL", "STRONG_SELL"):
            if has_position:
                trade = await self.close_all()
                result["executed"] = trade
                result["reason"] = "SELL signal -- closing gold position"
            else:
                if sniper_passed or action == "STRONG_SELL":
                    trade = await self.open_short(confidence=confidence, net_score=net_score)
                    result["executed"] = trade
                    result["reason"] = "SNIPER SHORT: strong bearish signal"
                else:
                    result["executed"] = "NONE"
                    result["reason"] = "SELL signal but no position and sniper not met"

        elif action in ("WEAK_SELL",):
            if has_position:
                trade = await self.close_all()
                result["executed"] = trade
                result["reason"] = "WEAK SELL with position -- closing for safety"
            else:
                result["executed"] = "NONE"
                result["reason"] = "WEAK SELL, no position -- no action"

        else:
            result["executed"] = "NONE"
            result["reason"] = f"{action} signal -- no action"

        self._last_action = result
        return result

    def get_trade_log(self, limit: int = 50) -> list:
        return self._trade_log[-limit:]

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
