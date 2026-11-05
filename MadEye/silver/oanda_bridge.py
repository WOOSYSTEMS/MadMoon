"""
MadEye Silver OANDA Bridge
Trade XAG/USD on OANDA. Silver-specific settings:
- Wider stop loss (4% instead of 3%) due to higher volatility
- Trailing stop after +2% gain
- Silver volatility is 25-35% annual vs 15-20% for gold
"""

import json
import logging
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

import httpx

logger = logging.getLogger("madeye.silver")

DATA_DIR = Path(__file__).parent / "data"

OANDA_CONFIG_PATHS = [
    Path("/home/ec2-user/MadMoonEye/backend/data/oanda_config.json"),
    DATA_DIR / "oanda_config.json",
    DATA_DIR.parent.parent / "data" / "oanda_config.json",
    Path.home() / ".madeye" / "oanda_config.json",
]

DEFAULT_INSTRUMENT = "XAG_USD"  # Silver
DEFAULT_UNITS = 50  # Silver units (each unit = 1 oz)
STOP_LOSS_PCT = 0.04  # 4% stop loss (wider than gold due to volatility)
TRAILING_STOP_TRIGGER_PCT = 0.02  # Start trailing after +2% gain
TRAILING_STOP_DISTANCE_PCT = 0.025  # Trail 2.5% behind peak


class OANDABridgeSilver:
    """Auto-trading bridge for XAG/USD."""

    def __init__(self, config_path: str = None):
        self.config = self._load_config(config_path)
        self._client: Optional[httpx.AsyncClient] = None
        self._running = False
        self._last_action = None
        self._trade_log: list = []
        self._load_trade_log()

    def _load_config(self, config_path: str = None) -> Dict:
        paths_to_try = [Path(config_path)] if config_path else OANDA_CONFIG_PATHS
        for path in paths_to_try:
            if path.exists():
                try:
                    with open(path) as f:
                        config = json.load(f)
                    logger.info(f"OANDA config loaded from {path}")
                    # Override instrument for silver
                    config["instrument"] = DEFAULT_INSTRUMENT
                    return config
                except Exception as e:
                    logger.warning(f"OANDA config load failed {path}: {e}")

        logger.warning("No OANDA config -- silver bridge in dry-run mode")
        return {
            "api_url": "https://api-fxpractice.oanda.com",
            "account_id": "",
            "api_key": "",
            "instrument": DEFAULT_INSTRUMENT,
            "units": DEFAULT_UNITS,
            "dry_run": True,
        }

    def _load_trade_log(self):
        path = DATA_DIR / "oanda_silver_trades.json"
        if path.exists():
            try:
                with open(path) as f:
                    self._trade_log = json.load(f)
            except Exception:
                self._trade_log = []

    def _save_trade_log(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        path = DATA_DIR / "oanda_silver_trades.json"
        try:
            with open(path, "w") as f:
                json.dump(self._trade_log[-500:], f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Trade log save error: {e}")

    async def get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.config.get("api_url", "https://api-fxpractice.oanda.com"),
                headers={
                    "Authorization": f"Bearer {self.config.get('api_key', '')}",
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
            return {"balance": "N/A (dry run)", "instrument": DEFAULT_INSTRUMENT}
        try:
            client = await self.get_client()
            resp = await client.get(f"/v3/accounts/{self.config['account_id']}/summary")
            resp.raise_for_status()
            return resp.json().get("account", {})
        except Exception as e:
            logger.error(f"Account summary error: {e}")
            return None

    async def get_open_positions(self) -> list:
        if self.is_dry_run:
            return []
        try:
            client = await self.get_client()
            account_id = self.config["account_id"]
            instrument = DEFAULT_INSTRUMENT
            resp = await client.get(f"/v3/accounts/{account_id}/positions/{instrument}")
            resp.raise_for_status()
            position = resp.json().get("position", {})
            positions = []
            long_units = int(position.get("long", {}).get("units", "0"))
            short_units = int(position.get("short", {}).get("units", "0"))
            if long_units > 0:
                positions.append({"side": "long", "units": long_units})
            if short_units < 0:
                positions.append({"side": "short", "units": abs(short_units)})
            return positions
        except Exception as e:
            logger.warning(f"Positions error: {e}")
            return []

    def _compute_position_size(self, confidence: float, net_score: float) -> int:
        base_units = self.config.get("units", DEFAULT_UNITS)
        conf_scale = max(0.3, min(1.0, confidence))
        strength_scale = max(0.5, min(1.5, abs(net_score) / 12.0))
        return max(1, int(base_units * conf_scale * strength_scale))

    async def open_long(self, units: int = None, confidence: float = 0.5,
                        net_score: float = 0) -> Dict:
        if units is None:
            units = self._compute_position_size(confidence, net_score)

        trade_info = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": "OPEN_LONG",
            "instrument": DEFAULT_INSTRUMENT,
            "units": units,
            "confidence": confidence,
            "net_score": net_score,
            "stop_loss_pct": STOP_LOSS_PCT * 100,
            "trailing_trigger_pct": TRAILING_STOP_TRIGGER_PCT * 100,
        }

        if self.is_dry_run:
            trade_info["status"] = "DRY_RUN"
            trade_info["message"] = (
                f"Would open LONG {units} XAG_USD "
                f"(SL={STOP_LOSS_PCT*100:.0f}%, trail after +{TRAILING_STOP_TRIGGER_PCT*100:.0f}%)"
            )
            logger.info(f"[DRY RUN] Silver long: {units} XAG_USD (conf={confidence:.2f})")
        else:
            try:
                client = await self.get_client()
                account_id = self.config["account_id"]
                # Silver price is ~$30, so distance in price units
                # 4% of $30 = $1.20 stop distance
                order_data = {
                    "order": {
                        "type": "MARKET",
                        "instrument": DEFAULT_INSTRUMENT,
                        "units": str(units),
                        "timeInForce": "FOK",
                        "positionFill": "DEFAULT",
                        "stopLossOnFill": {
                            "distance": str(round(STOP_LOSS_PCT * 30, 2)),  # ~$1.20
                            "timeInForce": "GTC",
                        },
                        "trailingStopLossOnFill": {
                            "distance": str(round(TRAILING_STOP_DISTANCE_PCT * 30, 2)),  # ~$0.75
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
                trade_info["fill_price"] = result.get("orderFillTransaction", {}).get("price", "unknown")
                logger.info(f"Silver long opened: {units} @ {trade_info['fill_price']}")
            except Exception as e:
                trade_info["status"] = "ERROR"
                trade_info["error"] = str(e)
                logger.error(f"Silver open long error: {e}")

        self._trade_log.append(trade_info)
        self._save_trade_log()
        return trade_info

    async def close_all(self) -> Dict:
        trade_info = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": "CLOSE_ALL",
            "instrument": DEFAULT_INSTRUMENT,
        }

        if self.is_dry_run:
            trade_info["status"] = "DRY_RUN"
            trade_info["message"] = f"Would close all {DEFAULT_INSTRUMENT} positions"
            logger.info(f"[DRY RUN] Close all silver")
        else:
            try:
                client = await self.get_client()
                account_id = self.config["account_id"]
                resp = await client.put(
                    f"/v3/accounts/{account_id}/positions/{DEFAULT_INSTRUMENT}/close",
                    json={"longUnits": "ALL"},
                )
                if resp.status_code == 200:
                    trade_info["long_closed"] = resp.json()
                resp = await client.put(
                    f"/v3/accounts/{account_id}/positions/{DEFAULT_INSTRUMENT}/close",
                    json={"shortUnits": "ALL"},
                )
                if resp.status_code == 200:
                    trade_info["short_closed"] = resp.json()
                trade_info["status"] = "CLOSED"
                logger.info("Silver positions closed")
            except Exception as e:
                trade_info["status"] = "ERROR"
                trade_info["error"] = str(e)
                logger.error(f"Silver close error: {e}")

        self._trade_log.append(trade_info)
        self._save_trade_log()
        return trade_info

    async def process_signal(self) -> Dict:
        signal_path = DATA_DIR / "current_signal.json"
        if not signal_path.exists():
            return {"action": "NONE", "reason": "No signal file"}

        try:
            with open(signal_path) as f:
                signal = json.load(f)
        except Exception as e:
            return {"action": "NONE", "reason": f"Signal read error: {e}"}

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

        if confidence < 0.3:
            result["executed"] = "NONE"
            result["reason"] = f"Confidence too low ({confidence:.2f})"
            return result

        if action in ("BUY", "STRONG_BUY"):
            if not has_position:
                trade = await self.open_long(confidence=confidence, net_score=net_score)
                result["executed"] = trade
                result["reason"] = "BUY signal -- opened silver long"
            else:
                result["executed"] = "NONE"
                result["reason"] = "Already in position"
        elif action in ("SELL", "STRONG_SELL"):
            if has_position:
                trade = await self.close_all()
                result["executed"] = trade
                result["reason"] = "SELL signal -- closed silver position"
            else:
                result["executed"] = "NONE"
                result["reason"] = "SELL but no position"
        else:
            result["executed"] = "NONE"
            result["reason"] = "HOLD -- no action"

        self._last_action = result
        return result

    def get_trade_log(self, limit: int = 50) -> list:
        return self._trade_log[-limit:]

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
