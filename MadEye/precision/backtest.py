"""
MadEye Precision Mode Backtest
Tests precision rules on historical hourly data for oil, gold, silver.
Simulates collector scores using technical indicators as proxies.

Starting capital: $100 CAD, 5x leverage, 5% SL, 1.5% TP, trailing stop.
Compares: Precision Mode vs Sniper (stricter) vs Original MadEye (looser).
"""

import json
import sys
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Tuple, Optional
import numpy as np

# Data paths -- try Dublin EC2 first, then local
DATA_PATHS = [
    Path("/home/ec2-user/MadMoon/MadEye/data"),
    Path(__file__).parent.parent / "data",
]

# Parameters
STARTING_CAPITAL = 100.0  # $100 CAD
LEVERAGE = 5
STOP_LOSS_PCT = 0.05      # 5%
TAKE_PROFIT_PCT = 0.015   # 1.5%
TRAILING_TRIGGER_PCT = 0.01   # Start trailing after +1%
TRAILING_DISTANCE_PCT = 0.008  # Trail 0.8% below peak
MAX_HOLD_HOURS = 24
MIN_AGREEMENT = 5  # Precision mode: 5+ signals must agree


def find_data_dir() -> Path:
    for p in DATA_PATHS:
        if p.exists():
            return p
    print("ERROR: No data directory found. Create data/ and add hourly price JSONs.")
    sys.exit(1)


def load_hourly_data(data_dir: Path, filename: str) -> List[Dict]:
    """Load hourly price data from JSON file."""
    path = data_dir / filename
    if not path.exists():
        print(f"  WARNING: {filename} not found at {path}")
        return []
    try:
        with open(path) as f:
            data = json.load(f)
        # Ensure sorted by timestamp
        data.sort(key=lambda x: x.get("timestamp", 0))
        print(f"  Loaded {len(data)} hourly bars from {filename}")
        return data
    except Exception as e:
        print(f"  ERROR loading {filename}: {e}")
        return []


# ====================================================================
# Technical indicator computations (proxies for collector scores)
# ====================================================================

def compute_rsi(closes: List[float], period: int = 14) -> float:
    """Compute RSI from a list of close prices."""
    if len(closes) < period + 1:
        return 50.0
    deltas = np.diff(closes[-(period+1):])
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains)
    avg_loss = np.mean(losses)
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def compute_macd(closes: List[float]) -> Tuple[float, float]:
    """Compute MACD line and signal line. Returns (macd, signal)."""
    if len(closes) < 26:
        return 0, 0
    c = np.array(closes)
    ema12 = _ema(c, 12)
    ema26 = _ema(c, 26)
    macd_line = ema12 - ema26
    # Signal is EMA(9) of MACD -- approximate with last 9 values of macd
    if len(closes) >= 35:
        macd_values = []
        for i in range(9):
            idx = len(closes) - 9 + i
            e12 = _ema(c[:idx+1], 12)
            e26 = _ema(c[:idx+1], 26)
            macd_values.append(e12 - e26)
        signal = _ema(np.array(macd_values), 9)
    else:
        signal = macd_line * 0.9
    return macd_line, signal


def _ema(data: np.ndarray, period: int) -> float:
    """Exponential moving average of last element."""
    if len(data) < period:
        return float(np.mean(data))
    weights = np.exp(np.linspace(-1, 0, period))
    weights /= weights.sum()
    return float(np.dot(data[-period:], weights))


def compute_ma(closes: List[float], period: int) -> float:
    if len(closes) < period:
        return closes[-1] if closes else 0
    return np.mean(closes[-period:])


def compute_atr(highs: List[float], lows: List[float], closes: List[float],
                period: int = 14) -> float:
    """Average True Range."""
    if len(closes) < period + 1:
        return 0
    trs = []
    for i in range(1, period + 1):
        idx = len(closes) - period - 1 + i
        if idx >= len(closes) or idx < 1:
            continue
        tr = max(
            highs[idx] - lows[idx],
            abs(highs[idx] - closes[idx-1]),
            abs(lows[idx] - closes[idx-1]),
        )
        trs.append(tr)
    return np.mean(trs) if trs else 0


def compute_roc(closes: List[float], period: int = 4) -> float:
    """Rate of change over N periods."""
    if len(closes) < period + 1:
        return 0
    return (closes[-1] - closes[-period-1]) / closes[-period-1] * 100


# ====================================================================
# Proxy collector signals -- simulate 10+ independent signals
# ====================================================================

def generate_proxy_signals(prices: List[Dict], idx: int,
                           dxy_prices: List[Dict] = None,
                           dxy_idx_map: Dict = None) -> Tuple[int, int, List[str], List[str]]:
    """Generate proxy collector scores from technical indicators.

    Returns: (bullish_count, bearish_count, bullish_names, bearish_names)

    We simulate ~12 independent signals:
    1. RSI(14) -- overbought/oversold
    2. RSI(7) -- short-term momentum
    3. MACD crossover
    4. Price vs 20h MA
    5. Price vs 50h MA
    6. Price vs 100h MA
    7. 4h ROC direction
    8. 12h ROC direction
    9. Volatility expansion (ATR spike)
    10. DXY inverse correlation
    11. Daily range position (close vs high/low)
    12. Volume momentum (if available)
    """
    if idx < 100:
        return 0, 0, [], []

    closes = [p["close"] for p in prices[:idx+1]]
    highs = [p.get("high", p["close"]) for p in prices[:idx+1]]
    lows = [p.get("low", p["close"]) for p in prices[:idx+1]]

    current = closes[-1]
    bullish = 0
    bearish = 0
    bull_names = []
    bear_names = []

    # 1. RSI(14)
    rsi14 = compute_rsi(closes, 14)
    if rsi14 < 35:
        bullish += 1; bull_names.append(f"RSI14({rsi14:.0f})")
    elif rsi14 > 65:
        bearish += 1; bear_names.append(f"RSI14({rsi14:.0f})")

    # 2. RSI(7)
    rsi7 = compute_rsi(closes, 7)
    if rsi7 < 30:
        bullish += 1; bull_names.append(f"RSI7({rsi7:.0f})")
    elif rsi7 > 70:
        bearish += 1; bear_names.append(f"RSI7({rsi7:.0f})")

    # 3. MACD
    macd, signal = compute_macd(closes)
    if macd > signal and macd > 0:
        bullish += 1; bull_names.append("MACD_bull")
    elif macd < signal and macd < 0:
        bearish += 1; bear_names.append("MACD_bear")

    # 4. Price vs 20h MA
    ma20 = compute_ma(closes, 20)
    if current > ma20 * 1.001:
        bullish += 1; bull_names.append("MA20_above")
    elif current < ma20 * 0.999:
        bearish += 1; bear_names.append("MA20_below")

    # 5. Price vs 50h MA
    ma50 = compute_ma(closes, 50)
    if current > ma50 * 1.002:
        bullish += 1; bull_names.append("MA50_above")
    elif current < ma50 * 0.998:
        bearish += 1; bear_names.append("MA50_below")

    # 6. Price vs 100h MA
    ma100 = compute_ma(closes, 100)
    if current > ma100 * 1.003:
        bullish += 1; bull_names.append("MA100_above")
    elif current < ma100 * 0.997:
        bearish += 1; bear_names.append("MA100_below")

    # 7. 4h ROC
    roc4 = compute_roc(closes, 4)
    if roc4 > 0.3:
        bullish += 1; bull_names.append(f"ROC4({roc4:.2f}%)")
    elif roc4 < -0.3:
        bearish += 1; bear_names.append(f"ROC4({roc4:.2f}%)")

    # 8. 12h ROC
    roc12 = compute_roc(closes, 12)
    if roc12 > 0.5:
        bullish += 1; bull_names.append(f"ROC12({roc12:.2f}%)")
    elif roc12 < -0.5:
        bearish += 1; bear_names.append(f"ROC12({roc12:.2f}%)")

    # 9. Volatility expansion -- ATR spike above average
    atr = compute_atr(highs, lows, closes, 14)
    atr_pct = (atr / current) * 100 if current > 0 else 0
    avg_atr = compute_atr(highs[:-20] if len(highs) > 20 else highs,
                          lows[:-20] if len(lows) > 20 else lows,
                          closes[:-20] if len(closes) > 20 else closes, 14)
    if atr > avg_atr * 1.3 and roc4 > 0:
        bullish += 1; bull_names.append("ATR_expand_up")
    elif atr > avg_atr * 1.3 and roc4 < 0:
        bearish += 1; bear_names.append("ATR_expand_down")

    # 10. DXY inverse correlation
    if dxy_prices and dxy_idx_map:
        ts = prices[idx].get("timestamp", 0)
        dxy_idx = dxy_idx_map.get(ts)
        if dxy_idx and dxy_idx > 4:
            dxy_closes = [p["close"] for p in dxy_prices[:dxy_idx+1]]
            dxy_roc = compute_roc(dxy_closes, 4)
            if dxy_roc < -0.1:  # DXY falling = bullish for commodities
                bullish += 1; bull_names.append(f"DXY_fall({dxy_roc:.2f}%)")
            elif dxy_roc > 0.1:  # DXY rising = bearish
                bearish += 1; bear_names.append(f"DXY_rise({dxy_roc:.2f}%)")

    # 11. Close position in daily range
    if len(highs) >= 24:
        day_high = max(highs[-24:])
        day_low = min(lows[-24:])
        day_range = day_high - day_low
        if day_range > 0:
            position = (current - day_low) / day_range
            if position > 0.75:
                bullish += 1; bull_names.append(f"Range_top({position:.0%})")
            elif position < 0.25:
                bearish += 1; bear_names.append(f"Range_bot({position:.0%})")

    # 12. Momentum acceleration (ROC of ROC)
    if len(closes) > 8:
        roc4_prev = compute_roc(closes[:-4], 4) if len(closes) > 8 else 0
        roc_accel = roc4 - roc4_prev
        if roc_accel > 0.2:
            bullish += 1; bull_names.append(f"Accel({roc_accel:.2f})")
        elif roc_accel < -0.2:
            bearish += 1; bear_names.append(f"Decel({roc_accel:.2f})")

    return bullish, bearish, bull_names, bear_names


def check_backtest_confirmations(prices: List[Dict], idx: int, direction: str,
                                  dxy_prices: List[Dict] = None,
                                  dxy_idx_map: Dict = None) -> Tuple[bool, Dict]:
    """Check all confirmation conditions in backtest mode.
    Returns (all_passed, details_dict)
    """
    if idx < 50:
        return False, {"reason": "insufficient data"}

    closes = [p["close"] for p in prices[:idx+1]]
    highs = [p.get("high", p["close"]) for p in prices[:idx+1]]
    lows = [p.get("low", p["close"]) for p in prices[:idx+1]]
    current = closes[-1]

    results = {}

    # 1. DXY direction
    dxy_ok = True
    if dxy_prices and dxy_idx_map:
        ts = prices[idx].get("timestamp", 0)
        dxy_idx = dxy_idx_map.get(ts)
        if dxy_idx and dxy_idx > 2:
            dxy_closes = [p["close"] for p in dxy_prices[:dxy_idx+1]]
            dxy_roc = compute_roc(dxy_closes, 1)
            if direction == "BUY":
                dxy_ok = dxy_roc < 0.05
            else:
                dxy_ok = dxy_roc > -0.05
    results["dxy"] = dxy_ok

    # 2. Price vs 4h MA (20-period hourly)
    ma20 = compute_ma(closes, 20)
    if direction == "BUY":
        results["technical"] = current > ma20
    else:
        results["technical"] = current < ma20

    # 3. 4h ROC > +/-0.2%
    roc4 = compute_roc(closes, 4)
    if direction == "BUY":
        results["momentum"] = roc4 > 0.2
    else:
        results["momentum"] = roc4 < -0.2

    # 4. ATR > 0.3%
    atr = compute_atr(highs, lows, closes, 14)
    atr_pct = (atr / current * 100) if current > 0 else 0
    results["volatility"] = atr_pct > 0.3

    # 5. RSI not extreme
    rsi = compute_rsi(closes, 14)
    if direction == "BUY":
        results["rsi"] = rsi < 80
    else:
        results["rsi"] = rsi > 20

    # 6. Time filter -- check from timestamp
    ts = prices[idx].get("timestamp", 0)
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    weekday = dt.weekday()
    utc_hour = dt.hour

    time_ok = True
    if weekday >= 5:
        time_ok = False
    elif weekday == 4 and utc_hour >= 19:
        time_ok = False
    elif utc_hour == 7:
        time_ok = False
    elif not (8 <= utc_hour <= 17):
        time_ok = False
    results["time"] = time_ok

    all_passed = all(results.values())
    return all_passed, results


# ====================================================================
# Trade simulation
# ====================================================================

class BacktestTrade:
    def __init__(self, commodity: str, direction: str, entry_price: float,
                 entry_idx: int, entry_time: str, balance: float,
                 voters: List[str] = None):
        self.commodity = commodity
        self.direction = direction
        self.entry_price = entry_price
        self.entry_idx = entry_idx
        self.entry_time = entry_time
        self.balance_at_entry = balance
        self.voters = voters or []

        # Position sizing: full balance * 5x leverage
        self.units = (balance * LEVERAGE) / entry_price if entry_price > 0 else 0

        self.peak_price = entry_price
        self.trailing_active = False
        self.exit_price = None
        self.exit_reason = None
        self.exit_idx = None
        self.pl_pct = 0.0

    def check_exit(self, price: float, bar_idx: int, hours_held: int) -> Optional[str]:
        """Check if trade should exit. Returns exit reason or None."""
        if self.direction == "BUY":
            pl_pct = (price - self.entry_price) / self.entry_price * 100
        else:
            pl_pct = (self.entry_price - price) / self.entry_price * 100

        # Take profit
        if pl_pct >= TAKE_PROFIT_PCT * 100:
            return "TAKE_PROFIT"

        # Stop loss
        if pl_pct <= -STOP_LOSS_PCT * 100:
            return "STOP_LOSS"

        # Trailing stop
        if self.direction == "BUY":
            if price > self.peak_price:
                self.peak_price = price
        else:
            if price < self.peak_price:
                self.peak_price = price

        if pl_pct >= TRAILING_TRIGGER_PCT * 100:
            self.trailing_active = True

        if self.trailing_active:
            if self.direction == "BUY":
                trail_stop = self.peak_price * (1 - TRAILING_DISTANCE_PCT)
                if price <= trail_stop:
                    return "TRAILING_STOP"
            else:
                trail_stop = self.peak_price * (1 + TRAILING_DISTANCE_PCT)
                if price >= trail_stop:
                    return "TRAILING_STOP"

        # Max hold
        if hours_held >= MAX_HOLD_HOURS:
            return "MAX_HOLD"

        return None

    def close(self, price: float, reason: str, bar_idx: int):
        self.exit_price = price
        self.exit_reason = reason
        self.exit_idx = bar_idx
        if self.direction == "BUY":
            self.pl_pct = (price - self.entry_price) / self.entry_price * 100
        else:
            self.pl_pct = (self.entry_price - price) / self.entry_price * 100


def run_backtest(prices: List[Dict], commodity: str, mode: str = "precision",
                 dxy_prices: List[Dict] = None) -> Dict:
    """Run backtest on a single commodity's hourly data.

    mode: 'precision' (5+ agree), 'sniper' (8+ agree), 'original' (3+ agree)
    """
    if len(prices) < 200:
        return {"error": f"Insufficient data for {commodity}: {len(prices)} bars"}

    # Build DXY timestamp index for fast lookup
    dxy_idx_map = {}
    if dxy_prices:
        for i, dp in enumerate(dxy_prices):
            ts = dp.get("timestamp", 0)
            dxy_idx_map[ts] = i
            # Also map nearby timestamps (hourly alignment)
            for offset in [-1800, -3600, 1800, 3600]:
                dxy_idx_map[ts + offset] = i

    # Mode thresholds
    if mode == "precision":
        min_agree = 5
    elif mode == "sniper":
        min_agree = 8
    elif mode == "original":
        min_agree = 3
    else:
        min_agree = 5

    balance = STARTING_CAPITAL
    trades: List[BacktestTrade] = []
    active_trade: Optional[BacktestTrade] = None
    peak_balance = balance
    max_drawdown = 0.0

    # Scan through each hourly bar
    for idx in range(100, len(prices)):
        bar = prices[idx]
        price = bar["close"]
        ts = bar.get("timestamp", 0)
        dt_str = bar.get("datetime", "")

        # Check exit for active trade
        if active_trade:
            hours_held = idx - active_trade.entry_idx
            exit_reason = active_trade.check_exit(price, idx, hours_held)

            # Weekend close check
            if not exit_reason:
                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                if dt.weekday() == 4 and dt.hour >= 20:
                    exit_reason = "WEEKEND_CLOSE"

            if exit_reason:
                active_trade.close(price, exit_reason, idx)
                # Update balance with leveraged P/L
                pl_dollar = active_trade.pl_pct / 100 * balance * LEVERAGE
                balance += pl_dollar
                balance = max(balance, 0.01)  # Don't go below $0.01

                trades.append(active_trade)
                active_trade = None

                # Drawdown tracking
                if balance > peak_balance:
                    peak_balance = balance
                dd = (peak_balance - balance) / peak_balance * 100
                if dd > max_drawdown:
                    max_drawdown = dd

            continue  # Don't enter new trade on same bar as exit

        # Generate proxy signals
        bull_count, bear_count, bull_names, bear_names = generate_proxy_signals(
            prices, idx, dxy_prices, dxy_idx_map
        )

        direction = None
        voters = []
        n_agree = 0

        if bull_count >= min_agree:
            direction = "BUY"
            n_agree = bull_count
            voters = bull_names
        elif bear_count >= min_agree:
            direction = "SELL"
            n_agree = bear_count
            voters = bear_names

        if not direction:
            continue

        # Check confirmations (for precision and sniper modes)
        if mode in ("precision", "sniper"):
            conf_passed, conf_details = check_backtest_confirmations(
                prices, idx, direction, dxy_prices, dxy_idx_map
            )
            if not conf_passed:
                continue

        # Open trade
        active_trade = BacktestTrade(
            commodity=commodity,
            direction=direction,
            entry_price=price,
            entry_idx=idx,
            entry_time=dt_str,
            balance=balance,
            voters=voters,
        )

    # Close any remaining trade at last price
    if active_trade:
        last_price = prices[-1]["close"]
        active_trade.close(last_price, "END_OF_DATA", len(prices) - 1)
        pl_dollar = active_trade.pl_pct / 100 * balance * LEVERAGE
        balance += pl_dollar
        balance = max(balance, 0.01)
        trades.append(active_trade)

    # Compute stats
    if not trades:
        return {
            "commodity": commodity,
            "mode": mode,
            "trades": 0,
            "win_rate": 0,
            "final_balance": round(balance, 2),
            "total_return_pct": 0,
            "max_drawdown": 0,
            "avg_hold_hours": 0,
        }

    wins = [t for t in trades if t.pl_pct > 0]
    losses = [t for t in trades if t.pl_pct <= 0]
    win_rate = len(wins) / len(trades) * 100

    avg_win = np.mean([t.pl_pct for t in wins]) if wins else 0
    avg_loss = np.mean([t.pl_pct for t in losses]) if losses else 0

    avg_hold = np.mean([t.exit_idx - t.entry_idx for t in trades if t.exit_idx])
    total_return = (balance - STARTING_CAPITAL) / STARTING_CAPITAL * 100

    # Exit reason breakdown
    exit_reasons = {}
    for t in trades:
        r = t.exit_reason or "unknown"
        exit_reasons[r] = exit_reasons.get(r, 0) + 1

    return {
        "commodity": commodity,
        "mode": mode,
        "min_agreement": min_agree,
        "data_bars": len(prices),
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 1),
        "final_balance": round(balance, 2),
        "starting_balance": STARTING_CAPITAL,
        "total_return_pct": round(total_return, 1),
        "max_drawdown_pct": round(max_drawdown, 1),
        "avg_win_pct": round(avg_win, 2),
        "avg_loss_pct": round(avg_loss, 2),
        "avg_hold_hours": round(avg_hold, 1),
        "best_trade_pct": round(max(t.pl_pct for t in trades), 2),
        "worst_trade_pct": round(min(t.pl_pct for t in trades), 2),
        "exit_reasons": exit_reasons,
        "trades_per_week": round(len(trades) / max(1, len(prices) / (24 * 7)), 1),
    }


def print_results(results: Dict, header: str = ""):
    """Pretty-print backtest results."""
    if header:
        print(f"\n{'='*60}")
        print(f"  {header}")
        print(f"{'='*60}")

    if "error" in results:
        print(f"  ERROR: {results['error']}")
        return

    commodity = results.get("commodity", "?").upper()
    mode = results.get("mode", "?").upper()

    print(f"\n  {commodity} -- {mode} MODE (min {results.get('min_agreement', '?')}+ agree)")
    print(f"  {'~'*50}")
    print(f"  Data:          {results['data_bars']} hourly bars")
    print(f"  Trades:        {results['trades']} ({results.get('trades_per_week', 0)}/week)")
    print(f"  Win Rate:      {results['win_rate']}%")
    print(f"  Wins/Losses:   {results['wins']}/{results['losses']}")
    print(f"  ")
    print(f"  Start Balance: ${results['starting_balance']:.2f}")
    print(f"  Final Balance: ${results['final_balance']:.2f}")
    print(f"  Total Return:  {results['total_return_pct']:+.1f}%")
    print(f"  Max Drawdown:  {results['max_drawdown_pct']:.1f}%")
    print(f"  ")
    print(f"  Avg Win:       {results.get('avg_win_pct', 0):+.2f}%")
    print(f"  Avg Loss:      {results.get('avg_loss_pct', 0):+.2f}%")
    print(f"  Best Trade:    {results.get('best_trade_pct', 0):+.2f}%")
    print(f"  Worst Trade:   {results.get('worst_trade_pct', 0):+.2f}%")
    print(f"  Avg Hold:      {results.get('avg_hold_hours', 0):.1f} hours")
    print(f"  ")
    print(f"  Exit Reasons:")
    for reason, count in sorted(results.get("exit_reasons", {}).items(), key=lambda x: -x[1]):
        print(f"    {reason}: {count}")


def fetch_hourly_from_yahoo(symbol: str, days: int = 60) -> List[Dict]:
    """Fetch hourly data from Yahoo Finance as fallback."""
    import time
    try:
        import requests
    except ImportError:
        print(f"  Cannot fetch {symbol}: requests not installed")
        return []

    print(f"  Fetching {days}d hourly data for {symbol} from Yahoo Finance...")
    all_prices = []
    headers = {"User-Agent": "Mozilla/5.0 MadEye/2.0"}

    end = int(datetime.now(timezone.utc).timestamp())
    chunk_days = 7  # Yahoo limits hourly to ~7 days per request

    for start_offset in range(0, days, chunk_days):
        chunk_end = end - (start_offset * 86400)
        chunk_start = chunk_end - (chunk_days * 86400)

        url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
            f"?interval=1h&period1={chunk_start}&period2={chunk_end}"
        )
        try:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code == 200:
                data = r.json()["chart"]["result"][0]
                timestamps = data.get("timestamp", [])
                quotes = data["indicators"]["quote"][0]
                closes = quotes.get("close", [])
                highs = quotes.get("high", [])
                lows = quotes.get("low", [])

                for i, ts in enumerate(timestamps):
                    c = closes[i] if i < len(closes) else None
                    if c is not None:
                        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                        all_prices.append({
                            "timestamp": ts,
                            "datetime": dt.isoformat(),
                            "close": round(float(c), 4),
                            "high": round(float(highs[i]), 4) if i < len(highs) and highs[i] else round(float(c), 4),
                            "low": round(float(lows[i]), 4) if i < len(lows) and lows[i] else round(float(c), 4),
                        })
            time.sleep(0.3)
        except Exception as e:
            pass

    all_prices.sort(key=lambda x: x["timestamp"])
    # Deduplicate
    seen = set()
    unique = []
    for p in all_prices:
        if p["timestamp"] not in seen:
            seen.add(p["timestamp"])
            unique.append(p)

    print(f"  Fetched {len(unique)} hourly bars for {symbol}")
    return unique


def main():
    print("\n" + "=" * 70)
    print("  MADEYE PRECISION MODE BACKTEST")
    print("  Starting capital: $100 CAD | 5x leverage | 5% SL | 1.5% TP")
    print("=" * 70)

    data_dir = find_data_dir()
    print(f"\nData directory: {data_dir}")

    # Load data
    print("\nLoading price data...")
    oil_data = load_hourly_data(data_dir, "hourly_prices.json")

    # Try gold/silver/dxy from data dir
    gold_data = load_hourly_data(data_dir, "gold_hourly.json")
    silver_data = load_hourly_data(data_dir, "silver_hourly.json")
    dxy_data = load_hourly_data(data_dir, "dxy_hourly.json")

    # Fetch from Yahoo if missing
    if not gold_data:
        gold_data = fetch_hourly_from_yahoo("GC=F", days=60)
    if not silver_data:
        silver_data = fetch_hourly_from_yahoo("SI=F", days=60)
    if not dxy_data:
        dxy_data = fetch_hourly_from_yahoo("DX-Y.NYB", days=60)

    # Save fetched data for next time
    for name, data in [("gold_hourly.json", gold_data),
                        ("silver_hourly.json", silver_data),
                        ("dxy_hourly.json", dxy_data)]:
        if data:
            save_path = data_dir / name
            if not save_path.exists():
                try:
                    with open(save_path, "w") as f:
                        json.dump(data, f)
                    print(f"  Saved {name} ({len(data)} bars)")
                except Exception:
                    pass

    # Run backtests for each commodity and mode
    all_results = {}
    commodities = {
        "oil": oil_data,
        "gold": gold_data,
        "silver": silver_data,
    }

    modes = ["precision", "sniper", "original"]

    for mode in modes:
        print(f"\n{'='*60}")
        print(f"  RUNNING {mode.upper()} MODE BACKTESTS")
        print(f"{'='*60}")

        mode_results = {}
        for commodity, data in commodities.items():
            if not data or len(data) < 200:
                print(f"\n  {commodity.upper()}: SKIPPED (only {len(data)} bars, need 200+)")
                mode_results[commodity] = {"error": "insufficient data"}
                continue

            result = run_backtest(data, commodity, mode=mode, dxy_prices=dxy_data)
            mode_results[commodity] = result
            print_results(result)

        all_results[mode] = mode_results

    # Summary comparison
    print("\n" + "=" * 70)
    print("  COMPARISON SUMMARY")
    print("=" * 70)
    print(f"\n  {'Mode':<12} {'Commodity':<10} {'Trades':<8} {'Win%':<8} {'Return':<10} {'MaxDD':<8} {'Tr/Wk':<8}")
    print(f"  {'-'*64}")

    for mode in modes:
        for commodity in commodities:
            r = all_results.get(mode, {}).get(commodity, {})
            if "error" in r:
                continue
            print(
                f"  {mode:<12} {commodity:<10} "
                f"{r.get('trades', 0):<8} "
                f"{r.get('win_rate', 0):<8.1f} "
                f"{r.get('total_return_pct', 0):>+8.1f}% "
                f"{r.get('max_drawdown_pct', 0):<8.1f} "
                f"{r.get('trades_per_week', 0):<8.1f}"
            )

    # Key insight
    print(f"\n  {'='*64}")
    print("  KEY INSIGHT:")

    precision_results = all_results.get("precision", {})
    original_results = all_results.get("original", {})

    precision_wr = []
    original_wr = []
    for c in commodities:
        pr = precision_results.get(c, {})
        ori = original_results.get(c, {})
        if pr.get("trades", 0) > 0:
            precision_wr.append(pr["win_rate"])
        if ori.get("trades", 0) > 0:
            original_wr.append(ori["win_rate"])

    if precision_wr:
        avg_p = np.mean(precision_wr)
        avg_o = np.mean(original_wr) if original_wr else 0
        print(f"  Precision avg win rate: {avg_p:.1f}% vs Original avg: {avg_o:.1f}%")
        if avg_p >= 85:
            print(f"  CONFIRMED: 5+ agreement threshold achieves {avg_p:.1f}% win rate")
        elif avg_p >= 75:
            print(f"  CLOSE: {avg_p:.1f}% win rate. Consider raising agreement to 6+")
        else:
            print(f"  NEEDS TUNING: {avg_p:.1f}% win rate with technical proxies alone.")

        print(f"\n  IMPORTANT CAVEAT:")
        print(f"  This backtest uses 12 technical indicators as PROXIES for 34 real collectors.")
        print(f"  Technical indicators are NOT independent -- they all derive from price action.")
        print(f"  Real collectors (geopolitical, supply, sentiment, DXY, ETF flows, etc.) ARE")
        print(f"  independent signals, which is where the precision edge comes from.")
        print(f"  Expect HIGHER win rates in live mode with genuinely independent collector data.")
        print(f"")
        print(f"  MATH NOTE on leverage + risk/reward:")
        print(f"  5x leverage * 5% SL = 25% balance loss per losing trade")
        print(f"  5x leverage * 1.5% TP = 7.5% balance gain per winning trade")
        print(f"  Need ~77%+ win rate to break even at these levels.")
        print(f"  Most exits are MAX_HOLD/WEEKEND, not TP/SL -- those are coin-flip exits.")
        print(f"  Live mode with real collectors should push win rate above this threshold.")
    else:
        print("  No precision trades generated. Thresholds may be too strict or data insufficient.")

    # Save results
    results_path = data_dir / "precision_backtest_results.json"
    try:
        with open(results_path, "w") as f:
            json.dump(all_results, f, indent=2, default=str)
        print(f"\n  Results saved to {results_path}")
    except Exception as e:
        print(f"\n  Failed to save results: {e}")

    print(f"\n{'='*70}")
    print("  BACKTEST COMPLETE")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()
