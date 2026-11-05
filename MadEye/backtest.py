"""
MadEye Backtest Engine
Tests the signal system against 365 days of 15-minute oil price data.
Starting capital: $100 CAD, 5x leverage on OANDA.
"""

import json
import time
import sys
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Tuple
import requests

def fetch_historical_prices(days: int = 365) -> List[Dict]:
    """Fetch 15-minute Brent crude data from Yahoo Finance."""
    print(f"Fetching {days} days of 15-minute data...")

    all_prices = []
    headers = {"User-Agent": "Mozilla/5.0"}

    # Yahoo Finance limits 15m data to 60 days per request
    # Need to make multiple requests
    end = int(datetime.now(timezone.utc).timestamp())
    chunk_days = 59  # max days per request for 15m interval

    for start_offset in range(0, days, chunk_days):
        chunk_end = end - (start_offset * 86400)
        chunk_start = chunk_end - (chunk_days * 86400)

        url = f"https://query1.finance.yahoo.com/v8/finance/chart/BZ=F?interval=15m&period1={chunk_start}&period2={chunk_end}"
        try:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code == 200:
                data = r.json()["chart"]["result"][0]
                timestamps = data["timestamp"]
                closes = data["indicators"]["quote"][0]["close"]
                highs = data["indicators"]["quote"][0]["high"]
                lows = data["indicators"]["quote"][0]["low"]
                volumes = data["indicators"]["quote"][0]["volume"]

                for ts, c, h, l, v in zip(timestamps, closes, highs, lows, volumes):
                    if c is not None:
                        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                        all_prices.append({
                            "timestamp": ts,
                            "datetime": dt.isoformat(),
                            "close": round(c, 2),
                            "high": round(h, 2) if h else c,
                            "low": round(l, 2) if l else c,
                            "volume": v or 0,
                        })
            time.sleep(0.5)
        except Exception as e:
            print(f"  Chunk error at offset {start_offset}: {e}")
            time.sleep(1)

    # Sort by timestamp and deduplicate
    all_prices.sort(key=lambda x: x["timestamp"])
    seen = set()
    unique = []
    for p in all_prices:
        if p["timestamp"] not in seen:
            seen.add(p["timestamp"])
            unique.append(p)

    print(f"Fetched {len(unique)} price points over {days} days")
    return unique


def compute_technical_signal(prices: List[Dict], idx: int) -> float:
    """Compute technical score (0-10) from price history at given index."""
    if idx < 200:
        return 5.0  # not enough data

    closes = [p["close"] for p in prices[max(0, idx-200):idx+1]]

    # RSI (14 periods)
    gains = []
    losses = []
    for i in range(1, min(15, len(closes))):
        diff = closes[-i] - closes[-i-1]
        if diff > 0:
            gains.append(diff)
        else:
            losses.append(abs(diff))

    avg_gain = sum(gains) / 14 if gains else 0.001
    avg_loss = sum(losses) / 14 if losses else 0.001
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    # Moving averages
    ma50 = sum(closes[-50:]) / 50 if len(closes) >= 50 else closes[-1]
    ma200 = sum(closes[-200:]) / 200 if len(closes) >= 200 else closes[-1]
    current = closes[-1]

    # Score
    score = 5.0

    # RSI
    if rsi < 30:
        score += 2  # oversold = buy
    elif rsi > 70:
        score -= 2  # overbought = sell

    # Price vs MAs
    if current > ma50:
        score += 1
    else:
        score -= 1
    if current > ma200:
        score += 1
    else:
        score -= 1

    # Golden/death cross
    if ma50 > ma200:
        score += 0.5
    else:
        score -= 0.5

    return max(0, min(10, score))


def compute_momentum_signal(prices: List[Dict], idx: int) -> float:
    """Compute momentum score from recent price action."""
    if idx < 20:
        return 5.0

    closes = [p["close"] for p in prices[max(0, idx-20):idx+1]]

    # Short-term momentum (last 4 hours = 16 bars at 15min)
    if len(closes) >= 16:
        short_change = (closes[-1] - closes[-16]) / closes[-16] * 100
    else:
        short_change = 0

    # Medium-term momentum (last day = ~96 bars)
    if len(closes) >= 96:
        med_change = (closes[-1] - closes[-96]) / closes[-96] * 100
    else:
        med_change = (closes[-1] - closes[0]) / closes[0] * 100

    score = 5.0

    # Short-term
    if short_change > 1:
        score += 2
    elif short_change > 0.3:
        score += 1
    elif short_change < -1:
        score -= 2
    elif short_change < -0.3:
        score -= 1

    # Medium-term
    if med_change > 3:
        score += 1.5
    elif med_change > 1:
        score += 0.5
    elif med_change < -3:
        score -= 1.5
    elif med_change < -1:
        score -= 0.5

    return max(0, min(10, score))


def compute_volatility_signal(prices: List[Dict], idx: int) -> float:
    """High volatility = opportunity. Compute from recent range."""
    if idx < 20:
        return 5.0

    recent = prices[max(0, idx-20):idx+1]
    highs = [p["high"] for p in recent]
    lows = [p["low"] for p in recent]
    closes = [p["close"] for p in recent]

    avg_range = sum(h - l for h, l in zip(highs, lows)) / len(highs)
    avg_price = sum(closes) / len(closes)
    volatility_pct = (avg_range / avg_price) * 100

    # Higher volatility = more opportunity
    if volatility_pct > 1.5:
        return 7.5  # high vol = opportunity
    elif volatility_pct > 0.8:
        return 6.0
    elif volatility_pct < 0.3:
        return 4.0  # too quiet
    return 5.0


def generate_signal(prices: List[Dict], idx: int) -> Tuple[str, float, float]:
    """
    Generate BUY/SELL/HOLD signal from multiple factors.
    Returns (action, net_score, confidence)
    """
    tech_score = compute_technical_signal(prices, idx)
    momentum_score = compute_momentum_signal(prices, idx)
    vol_score = compute_volatility_signal(prices, idx)

    # Center scores around 0
    tech_centered = (tech_score - 5) * 1.5   # weight 1.5x
    momentum_centered = (momentum_score - 5) * 2.0  # weight 2x (most important for short-term)
    vol_centered = (vol_score - 5) * 1.0     # weight 1x

    net_score = tech_centered + momentum_centered + vol_centered

    # Confidence based on agreement
    scores = [tech_score, momentum_score, vol_score]
    all_bullish = all(s > 5.5 for s in scores)
    all_bearish = all(s < 4.5 for s in scores)
    confidence = 0.8 if (all_bullish or all_bearish) else 0.5

    if net_score > 5:
        return "BUY", net_score, confidence
    elif net_score < -5:
        return "SELL", net_score, confidence
    else:
        return "HOLD", net_score, confidence


def run_backtest(prices: List[Dict], starting_capital: float = 100.0,
                 leverage: int = 5, stop_loss_pct: float = 0.03,
                 take_profit_pct: float = 0.05,
                 check_interval: int = 4) -> Dict:
    """
    Run backtest over price history.

    check_interval: check signal every N bars (4 = every hour at 15min bars)
    """
    capital = starting_capital
    position = None  # {"entry_price": x, "entry_idx": i, "stop_loss": x, "take_profit": x}
    trades = []
    peak_capital = capital
    max_drawdown = 0
    signals_generated = 0

    print(f"\nRunning backtest...")
    print(f"  Capital: ${capital:.2f} CAD")
    print(f"  Leverage: {leverage}x")
    print(f"  Stop loss: {stop_loss_pct*100}%")
    print(f"  Take profit: {take_profit_pct*100}%")
    print(f"  Check interval: every {check_interval} bars ({check_interval * 15} min)")
    print(f"  Price points: {len(prices)}")
    print()

    for i in range(200, len(prices)):
        current_price = prices[i]["close"]

        # Check stop loss / take profit if in position
        if position:
            pnl_pct = (current_price - position["entry_price"]) / position["entry_price"]

            # Stop loss
            if current_price <= position["stop_loss"]:
                loss = pnl_pct * capital * leverage
                capital += loss
                trades.append({
                    "entry_idx": position["entry_idx"],
                    "exit_idx": i,
                    "entry_price": position["entry_price"],
                    "exit_price": current_price,
                    "pnl_pct": round(pnl_pct * 100, 3),
                    "pnl_usd": round(loss, 2),
                    "reason": "STOP_LOSS",
                    "entry_time": prices[position["entry_idx"]]["datetime"],
                    "exit_time": prices[i]["datetime"],
                    "capital_after": round(capital, 2),
                })
                position = None
                continue

            # Take profit
            if current_price >= position["take_profit"]:
                gain = pnl_pct * capital * leverage
                capital += gain
                trades.append({
                    "entry_idx": position["entry_idx"],
                    "exit_idx": i,
                    "entry_price": position["entry_price"],
                    "exit_price": current_price,
                    "pnl_pct": round(pnl_pct * 100, 3),
                    "pnl_usd": round(gain, 2),
                    "reason": "TAKE_PROFIT",
                    "entry_time": prices[position["entry_idx"]]["datetime"],
                    "exit_time": prices[i]["datetime"],
                    "capital_after": round(capital, 2),
                })
                position = None
                continue

        # Check signal every N bars
        if i % check_interval != 0:
            continue

        signals_generated += 1
        action, score, confidence = generate_signal(prices, i)

        # Execute
        if action == "BUY" and position is None and confidence > 0.5:
            position = {
                "entry_price": current_price,
                "entry_idx": i,
                "stop_loss": round(current_price * (1 - stop_loss_pct), 2),
                "take_profit": round(current_price * (1 + take_profit_pct), 2),
            }

        elif action == "SELL" and position is not None:
            pnl_pct = (current_price - position["entry_price"]) / position["entry_price"]
            pnl_usd = pnl_pct * capital * leverage
            capital += pnl_usd
            trades.append({
                "entry_idx": position["entry_idx"],
                "exit_idx": i,
                "entry_price": position["entry_price"],
                "exit_price": current_price,
                "pnl_pct": round(pnl_pct * 100, 3),
                "pnl_usd": round(pnl_usd, 2),
                "reason": "SIGNAL_SELL",
                "entry_time": prices[position["entry_idx"]]["datetime"],
                "exit_time": prices[i]["datetime"],
                "capital_after": round(capital, 2),
            })
            position = None

        # Track drawdown
        if capital > peak_capital:
            peak_capital = capital
        dd = (peak_capital - capital) / peak_capital * 100
        if dd > max_drawdown:
            max_drawdown = dd

        # Blow-up protection
        if capital <= 0:
            print("  BLOWN UP at bar", i)
            break

        # Progress
        if i % 5000 == 0:
            pct = (i - 200) / (len(prices) - 200) * 100
            print(f"  {pct:.0f}% complete | Capital: ${capital:.2f} | Trades: {len(trades)}")

    # Close any open position at end
    if position:
        current_price = prices[-1]["close"]
        pnl_pct = (current_price - position["entry_price"]) / position["entry_price"]
        pnl_usd = pnl_pct * capital * leverage
        capital += pnl_usd
        trades.append({
            "entry_price": position["entry_price"],
            "exit_price": current_price,
            "pnl_pct": round(pnl_pct * 100, 3),
            "pnl_usd": round(pnl_usd, 2),
            "reason": "END_OF_DATA",
            "capital_after": round(capital, 2),
        })

    # Calculate stats
    wins = [t for t in trades if t["pnl_usd"] > 0]
    losses = [t for t in trades if t["pnl_usd"] <= 0]
    win_rate = len(wins) / len(trades) * 100 if trades else 0
    total_pnl = capital - starting_capital
    roi = total_pnl / starting_capital * 100

    avg_win = sum(t["pnl_usd"] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t["pnl_usd"] for t in losses) / len(losses) if losses else 0
    profit_factor = abs(sum(t["pnl_usd"] for t in wins) / sum(t["pnl_usd"] for t in losses)) if losses and sum(t["pnl_usd"] for t in losses) != 0 else 999

    # Monthly breakdown
    monthly = {}
    for t in trades:
        month = t.get("exit_time", "")[:7]
        if month:
            if month not in monthly:
                monthly[month] = {"pnl": 0, "trades": 0, "wins": 0}
            monthly[month]["pnl"] += t["pnl_usd"]
            monthly[month]["trades"] += 1
            if t["pnl_usd"] > 0:
                monthly[month]["wins"] += 1

    results = {
        "starting_capital": starting_capital,
        "final_capital": round(capital, 2),
        "total_pnl": round(total_pnl, 2),
        "roi_pct": round(roi, 2),
        "total_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 1),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": round(profit_factor, 2),
        "max_drawdown_pct": round(max_drawdown, 2),
        "peak_capital": round(peak_capital, 2),
        "signals_generated": signals_generated,
        "leverage": leverage,
        "monthly": monthly,
        "trades": trades,
    }

    return results


def print_results(results: Dict):
    """Print formatted backtest results."""
    print()
    print("=" * 60)
    print("MADEYE BACKTEST RESULTS")
    print("=" * 60)
    print(f"  Starting capital:   ${results['starting_capital']:.2f} CAD")
    print(f"  Final capital:      ${results['final_capital']:.2f} CAD")
    print(f"  Total P/L:          ${results['total_pnl']:.2f}")
    print(f"  ROI:                {results['roi_pct']:.1f}%")
    print(f"  Leverage:           {results['leverage']}x")
    print()
    print(f"  Total trades:       {results['total_trades']}")
    print(f"  Wins:               {results['wins']}")
    print(f"  Losses:             {results['losses']}")
    print(f"  Win rate:           {results['win_rate']}%")
    print(f"  Avg win:            ${results['avg_win']:.2f}")
    print(f"  Avg loss:           ${results['avg_loss']:.2f}")
    print(f"  Profit factor:      {results['profit_factor']:.2f}")
    print(f"  Max drawdown:       {results['max_drawdown_pct']:.1f}%")
    print(f"  Peak capital:       ${results['peak_capital']:.2f}")
    print()
    print("  MONTHLY BREAKDOWN:")
    for month in sorted(results["monthly"].keys()):
        m = results["monthly"][month]
        wr = m["wins"] / m["trades"] * 100 if m["trades"] > 0 else 0
        sign = "+" if m["pnl"] >= 0 else ""
        print(f"    {month}: {sign}${m['pnl']:.2f} | {m['trades']} trades | {wr:.0f}% win rate")

    print()
    print("  LAST 10 TRADES:")
    for t in results["trades"][-10:]:
        sign = "+" if t["pnl_usd"] >= 0 else ""
        print(f"    {t.get('entry_time','')[:16]} -> {t.get('exit_time','')[:16]} | {t['reason']:<12} | {sign}${t['pnl_usd']:.2f} ({sign}{t['pnl_pct']}%) | Balance: ${t['capital_after']:.2f}")

    print("=" * 60)


if __name__ == "__main__":
    # Fetch data
    prices = fetch_historical_prices(days=365)

    if len(prices) < 1000:
        print(f"Only got {len(prices)} price points. Yahoo may limit 15m data to 60 days.")
        print("Running with available data...")

    # Run backtest
    results = run_backtest(
        prices,
        starting_capital=100.0,
        leverage=5,
        stop_loss_pct=0.03,
        take_profit_pct=0.05,
        check_interval=4,  # check every hour
    )

    # Print results
    print_results(results)

    # Save results
    output_path = "/Users/nnavindu/MadMoon/MadEye/data/backtest_results.json"
    import os
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {output_path}")
