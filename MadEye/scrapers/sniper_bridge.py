"""
MadEye Sniper Mode — OANDA Auto-Trader Bridge
Reads sniper_signal.json and executes oil trades on OANDA.

RULES:
  - SNIPER BUY: open long WTI_USD, 10x leverage, full balance, 2% hard stop
  - After +1.5% gain: switch to trailing stop at 1% below peak
  - Max hold: 48 hours
  - Take profit: +5% or trailing stop hit
  - Only 1 position at a time
  - Never trade weekends (close Friday 4PM EST, reopen Sunday 10PM EST)
  - Log every trade with entry reason (which scrapers fired)
"""

import os
import json
import time
import logging
import requests
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional

# Setup logging
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "logs")
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SNIPER] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(LOG_DIR, "sniper_bridge.log")),
    ]
)
log = logging.getLogger("sniper")

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
SIGNAL_FILE = os.path.join(DATA_DIR, "sniper_signal.json")
POSITION_FILE = os.path.join(DATA_DIR, "sniper_position.json")
TRADE_LOG_FILE = os.path.join(DATA_DIR, "sniper_trades.jsonl")

# OANDA config — reads from Dublin config or environment
OANDA_CONFIG_PATHS = [
    os.path.expanduser("~/.oanda_config.json"),
    "/home/ec2-user/kossinna/oanda_config.json",
    os.path.join(DATA_DIR, "oanda_config.json"),
]

INSTRUMENT = "WTICO_USD"  # WTI Crude Oil on OANDA
LEVERAGE = 10
HARD_STOP_PCT = 0.02      # 2% hard stop loss
TRAILING_TRIGGER_PCT = 0.015  # 1.5% gain triggers trailing
TRAILING_DISTANCE_PCT = 0.01  # 1% trailing stop
TAKE_PROFIT_PCT = 0.05    # 5% take profit
MAX_HOLD_HOURS = 48
POLL_INTERVAL = 30         # check every 30 seconds


class OandaClient:
    """Minimal OANDA v20 REST client."""

    def __init__(self, account_id: str, token: str, practice: bool = True):
        self.account_id = account_id
        self.token = token
        base = "https://api-fxpractice.oanda.com" if practice else "https://api-fxtrade.oanda.com"
        self.base_url = base
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def _get(self, path: str) -> Optional[Dict]:
        try:
            r = requests.get(f"{self.base_url}{path}", headers=self.headers, timeout=10)
            if r.status_code == 200:
                return r.json()
            log.error(f"OANDA GET {path}: {r.status_code} {r.text[:200]}")
        except Exception as e:
            log.error(f"OANDA GET {path}: {e}")
        return None

    def _post(self, path: str, data: Dict) -> Optional[Dict]:
        try:
            r = requests.post(f"{self.base_url}{path}", headers=self.headers, json=data, timeout=10)
            if r.status_code in (200, 201):
                return r.json()
            log.error(f"OANDA POST {path}: {r.status_code} {r.text[:200]}")
        except Exception as e:
            log.error(f"OANDA POST {path}: {e}")
        return None

    def _put(self, path: str, data: Dict) -> Optional[Dict]:
        try:
            r = requests.put(f"{self.base_url}{path}", headers=self.headers, json=data, timeout=10)
            if r.status_code in (200, 201):
                return r.json()
            log.error(f"OANDA PUT {path}: {r.status_code} {r.text[:200]}")
        except Exception as e:
            log.error(f"OANDA PUT {path}: {e}")
        return None

    def get_account(self) -> Optional[Dict]:
        return self._get(f"/v3/accounts/{self.account_id}")

    def get_price(self, instrument: str) -> Optional[float]:
        data = self._get(f"/v3/accounts/{self.account_id}/pricing?instruments={instrument}")
        if data and "prices" in data and len(data["prices"]) > 0:
            price = data["prices"][0]
            bid = float(price.get("bids", [{}])[0].get("price", 0))
            ask = float(price.get("asks", [{}])[0].get("price", 0))
            return (bid + ask) / 2
        return None

    def get_balance(self) -> float:
        data = self.get_account()
        if data and "account" in data:
            return float(data["account"].get("balance", 0))
        return 0.0

    def get_open_positions(self, instrument: str) -> Optional[Dict]:
        data = self._get(f"/v3/accounts/{self.account_id}/positions/{instrument}")
        if data and "position" in data:
            pos = data["position"]
            long_units = int(pos.get("long", {}).get("units", "0"))
            short_units = int(pos.get("short", {}).get("units", "0"))
            if long_units != 0 or short_units != 0:
                return pos
        return None

    def open_long(self, instrument: str, units: int, stop_loss: float, take_profit: float) -> Optional[Dict]:
        order = {
            "order": {
                "type": "MARKET",
                "instrument": instrument,
                "units": str(units),
                "stopLossOnFill": {"price": f"{stop_loss:.5f}"},
                "takeProfitOnFill": {"price": f"{take_profit:.5f}"},
                "timeInForce": "FOK",
            }
        }
        return self._post(f"/v3/accounts/{self.account_id}/orders", order)

    def close_position(self, instrument: str) -> Optional[Dict]:
        return self._put(
            f"/v3/accounts/{self.account_id}/positions/{instrument}/close",
            {"longUnits": "ALL"}
        )

    def update_stop_loss(self, trade_id: str, stop_loss: float) -> Optional[Dict]:
        return self._put(
            f"/v3/accounts/{self.account_id}/trades/{trade_id}/orders",
            {"stopLoss": {"price": f"{stop_loss:.5f}"}}
        )

    def get_open_trades(self, instrument: str) -> list:
        data = self._get(f"/v3/accounts/{self.account_id}/openTrades")
        if data and "trades" in data:
            return [t for t in data["trades"] if t.get("instrument") == instrument]
        return []


def load_oanda_config() -> Optional[Dict]:
    """Load OANDA config from known paths."""
    for path in OANDA_CONFIG_PATHS:
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    config = json.load(f)
                if config.get("account_id") and config.get("token"):
                    log.info(f"Loaded OANDA config from {path}")
                    return config
            except:
                continue

    # Try environment variables
    account_id = os.environ.get("OANDA_ACCOUNT_ID")
    token = os.environ.get("OANDA_TOKEN")
    if account_id and token:
        return {"account_id": account_id, "token": token, "practice": True}

    return None


def is_weekend() -> bool:
    """Check if it's weekend trading hours (Friday 4PM EST - Sunday 10PM EST)."""
    now = datetime.now(timezone.utc)
    # Convert to EST (UTC-5)
    est = now - timedelta(hours=5)
    weekday = est.weekday()  # 0=Mon, 4=Fri, 5=Sat, 6=Sun

    if weekday == 4 and est.hour >= 16:  # Friday after 4PM
        return True
    if weekday == 5:  # Saturday
        return True
    if weekday == 6 and est.hour < 22:  # Sunday before 10PM
        return True
    return False


def load_position() -> Optional[Dict]:
    if os.path.exists(POSITION_FILE):
        try:
            with open(POSITION_FILE, "r") as f:
                return json.load(f)
        except:
            pass
    return None


def save_position(position: Optional[Dict]):
    if position is None:
        if os.path.exists(POSITION_FILE):
            os.remove(POSITION_FILE)
        return
    with open(POSITION_FILE, "w") as f:
        json.dump(position, f, indent=2)


def log_trade(trade: Dict):
    """Append trade to log file."""
    with open(TRADE_LOG_FILE, "a") as f:
        f.write(json.dumps(trade) + "\n")


def read_signal() -> Optional[Dict]:
    """Read the current sniper signal."""
    if not os.path.exists(SIGNAL_FILE):
        return None
    try:
        with open(SIGNAL_FILE, "r") as f:
            return json.load(f)
    except:
        return None


class SniperBridge:
    def __init__(self):
        self.client: Optional[OandaClient] = None
        self.position: Optional[Dict] = None
        self.running = False
        self.peak_price = 0.0

    def initialize(self) -> bool:
        """Load OANDA config and connect."""
        config = load_oanda_config()
        if not config:
            log.error("No OANDA config found. Create ~/.oanda_config.json with account_id, token, practice fields.")
            return False

        self.client = OandaClient(
            account_id=config["account_id"],
            token=config["token"],
            practice=config.get("practice", True),
        )

        # Test connection
        account = self.client.get_account()
        if not account:
            log.error("Failed to connect to OANDA")
            return False

        balance = float(account.get("account", {}).get("balance", 0))
        log.info(f"Connected to OANDA. Account: {config['account_id']} Balance: ${balance:.2f}")

        self.position = load_position()
        if self.position:
            log.info(f"Existing position loaded: entry={self.position.get('entry_price')}")

        return True

    def calculate_units(self, price: float, balance: float) -> int:
        """Calculate position size: full balance * leverage."""
        # Units = (balance * leverage) / price
        # For CFD oil: 1 unit = 1 barrel
        units = int((balance * LEVERAGE) / price)
        return max(1, units)

    def open_sniper_position(self, signal: Dict):
        """Open a SNIPER BUY position."""
        if self.position:
            log.warning("Position already open — skipping")
            return

        if is_weekend():
            log.info("Weekend — no trading")
            return

        price = self.client.get_price(INSTRUMENT)
        if not price:
            log.error("Cannot get price — skipping entry")
            return

        balance = self.client.get_balance()
        if balance < 10:
            log.error(f"Insufficient balance: ${balance:.2f}")
            return

        units = self.calculate_units(price, balance)
        stop_loss = round(price * (1 - HARD_STOP_PCT), 5)
        take_profit = round(price * (1 + TAKE_PROFIT_PCT), 5)

        log.warning(f"OPENING SNIPER LONG: {units} units @ ${price:.2f}")
        log.warning(f"  Stop: ${stop_loss:.2f} ({HARD_STOP_PCT*100}%) | TP: ${take_profit:.2f} ({TAKE_PROFIT_PCT*100}%)")
        log.warning(f"  Reason: {signal.get('reason', 'unknown')}")
        log.warning(f"  Firing scrapers: {signal.get('firing_scrapers', [])}")

        result = self.client.open_long(INSTRUMENT, units, stop_loss, take_profit)
        if result:
            trade_data = result.get("orderFillTransaction", {})
            fill_price = float(trade_data.get("price", price))

            self.position = {
                "entry_price": fill_price,
                "units": units,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "entry_time": datetime.now(timezone.utc).isoformat(),
                "signal_reason": signal.get("reason", ""),
                "firing_scrapers": signal.get("firing_scrapers", []),
                "individual_scores": signal.get("individual_scores", {}),
                "composite_score": signal.get("composite_score", 0),
                "trailing_active": False,
                "trade_id": trade_data.get("id", ""),
            }
            self.peak_price = fill_price
            save_position(self.position)

            log_trade({
                "action": "OPEN_LONG",
                "price": fill_price,
                "units": units,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "reason": signal.get("reason", ""),
                "firing_scrapers": signal.get("firing_scrapers", []),
                "scores": signal.get("individual_scores", {}),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

            log.warning(f"POSITION OPENED: {units} units @ ${fill_price:.2f}")
        else:
            log.error("FAILED to open position")

    def manage_position(self):
        """Manage open position: trailing stop, max hold, weekend close."""
        if not self.position:
            return

        price = self.client.get_price(INSTRUMENT)
        if not price:
            return

        entry = self.position["entry_price"]
        gain_pct = (price - entry) / entry

        # Update peak
        if price > self.peak_price:
            self.peak_price = price

        # Check max hold
        entry_time = datetime.fromisoformat(self.position["entry_time"])
        hours_held = (datetime.now(timezone.utc) - entry_time).total_seconds() / 3600
        if hours_held >= MAX_HOLD_HOURS:
            log.warning(f"MAX HOLD ({MAX_HOLD_HOURS}h) reached — closing position")
            self._close_position("MAX_HOLD", price, gain_pct)
            return

        # Check weekend
        if is_weekend():
            log.warning("Weekend approaching — closing position")
            self._close_position("WEEKEND_CLOSE", price, gain_pct)
            return

        # Trailing stop logic
        if gain_pct >= TRAILING_TRIGGER_PCT and not self.position.get("trailing_active"):
            log.info(f"Gain {gain_pct*100:.2f}% >= {TRAILING_TRIGGER_PCT*100}% — activating trailing stop")
            self.position["trailing_active"] = True
            save_position(self.position)

        if self.position.get("trailing_active"):
            trailing_stop = self.peak_price * (1 - TRAILING_DISTANCE_PCT)
            if price <= trailing_stop:
                log.warning(f"TRAILING STOP HIT: price ${price:.2f} <= trailing ${trailing_stop:.2f}")
                self._close_position("TRAILING_STOP", price, gain_pct)
                return

            # Update stop loss on broker if price made new high
            if price == self.peak_price and self.position.get("trade_id"):
                trades = self.client.get_open_trades(INSTRUMENT)
                for trade in trades:
                    self.client.update_stop_loss(trade["id"], trailing_stop)
                log.info(f"Updated trailing stop to ${trailing_stop:.2f} (peak ${self.peak_price:.2f})")

        log.info(f"Position: entry=${entry:.2f} current=${price:.2f} gain={gain_pct*100:+.2f}% held={hours_held:.1f}h trailing={'ON' if self.position.get('trailing_active') else 'OFF'}")

    def _close_position(self, reason: str, price: float, gain_pct: float):
        """Close the current position."""
        result = self.client.close_position(INSTRUMENT)
        pnl = (price - self.position["entry_price"]) * self.position["units"]

        log_trade({
            "action": "CLOSE",
            "reason": reason,
            "entry_price": self.position["entry_price"],
            "exit_price": price,
            "units": self.position["units"],
            "gain_pct": round(gain_pct * 100, 2),
            "pnl_usd": round(pnl, 2),
            "hours_held": round(
                (datetime.now(timezone.utc) - datetime.fromisoformat(self.position["entry_time"])).total_seconds() / 3600, 1
            ),
            "original_reason": self.position.get("signal_reason", ""),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        log.warning(f"POSITION CLOSED: reason={reason} gain={gain_pct*100:+.2f}% PnL=${pnl:+.2f}")
        self.position = None
        self.peak_price = 0.0
        save_position(None)

    def run(self):
        """Main loop: poll signal file, manage positions."""
        if not self.initialize():
            log.error("Initialization failed. Exiting.")
            return

        self.running = True
        log.info("=" * 50)
        log.info("SNIPER BRIDGE STARTED")
        log.info(f"Instrument: {INSTRUMENT}")
        log.info(f"Leverage: {LEVERAGE}x")
        log.info(f"Stop: {HARD_STOP_PCT*100}% | Trailing: {TRAILING_DISTANCE_PCT*100}% after +{TRAILING_TRIGGER_PCT*100}%")
        log.info(f"TP: {TAKE_PROFIT_PCT*100}% | Max hold: {MAX_HOLD_HOURS}h")
        log.info("=" * 50)

        try:
            while self.running:
                if is_weekend() and not self.position:
                    log.info("Weekend — sleeping 1 hour")
                    time.sleep(3600)
                    continue

                # Read signal
                signal = read_signal()

                if self.position:
                    # Manage existing position
                    self.manage_position()
                elif signal and signal.get("sniper_buy"):
                    # Check signal freshness (must be < 5 minutes old)
                    sig_time = signal.get("timestamp", "")
                    try:
                        sig_dt = datetime.fromisoformat(sig_time)
                        age = (datetime.now(timezone.utc) - sig_dt).total_seconds()
                        if age < 300:  # < 5 min old
                            self.open_sniper_position(signal)
                        else:
                            log.info(f"Signal too old ({age:.0f}s) — skipping")
                    except:
                        log.warning("Cannot parse signal timestamp")

                time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            log.info("Keyboard interrupt")
            if self.position:
                log.warning("Position still open! Close manually or restart bridge.")
        finally:
            self.running = False
            log.info("Sniper bridge stopped.")

    def stop(self):
        self.running = False


def main():
    bridge = SniperBridge()
    bridge.run()


if __name__ == "__main__":
    main()
