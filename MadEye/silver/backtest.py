"""
MadEye Silver Backtest Engine
365 days hourly data from Yahoo SI=F.
4 backtests: ratio-only, industrial, fundamental, full.
Starting capital $100 CAD, 5x leverage.
HONEST results -- no cherry-picking.
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

logger = logging.getLogger("madeye.silver.backtest")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

DATA_DIR = Path(__file__).parent / "data"


def compute_rsi(prices: list, period: int = 14) -> float:
    if len(prices) < period + 1:
        return 50.0
    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def compute_sma(prices: list, period: int) -> float:
    if len(prices) < period:
        return prices[-1] if prices else 0
    return sum(prices[-period:]) / period


def fetch_data() -> Tuple[List, List, List, List]:
    """Fetch 1 year of daily data for silver, gold, copper, DXY."""
    try:
        import yfinance as yf

        logger.info("Fetching silver (SI=F) 1Y daily data...")
        silver = yf.Ticker("SI=F")
        silver_hist = silver.history(period="1y", interval="1d")

        logger.info("Fetching gold (GC=F) 1Y daily data...")
        gold = yf.Ticker("GC=F")
        gold_hist = gold.history(period="1y", interval="1d")

        logger.info("Fetching copper (HG=F) 1Y daily data...")
        copper = yf.Ticker("HG=F")
        copper_hist = copper.history(period="1y", interval="1d")

        logger.info("Fetching DXY (DX-Y.NYB) 1Y daily data...")
        dxy = yf.Ticker("DX-Y.NYB")
        dxy_hist = dxy.history(period="1y", interval="1d")

        silver_prices = silver_hist["Close"].dropna().tolist()
        gold_prices = gold_hist["Close"].dropna().tolist()
        copper_prices = copper_hist["Close"].dropna().tolist()
        dxy_prices = dxy_hist["Close"].dropna().tolist()

        # Align to shortest length
        min_len = min(len(silver_prices), len(gold_prices), len(copper_prices), len(dxy_prices))
        return (
            silver_prices[-min_len:],
            gold_prices[-min_len:],
            copper_prices[-min_len:],
            dxy_prices[-min_len:],
        )
    except Exception as e:
        logger.error(f"Data fetch error: {e}")
        return [], [], [], []


def run_backtest(
    silver_prices: list,
    gold_prices: list,
    copper_prices: list,
    dxy_prices: list,
    strategy: str = "full",
    capital: float = 100.0,
    leverage: float = 5.0,
    stop_loss_pct: float = 0.04,
    trailing_trigger_pct: float = 0.02,
) -> Dict:
    """Run a single backtest with specified strategy."""

    if len(silver_prices) < 50:
        return {"error": "Insufficient data", "strategy": strategy}

    trades = []
    equity = capital
    peak_equity = capital
    max_drawdown = 0
    position = None  # {"entry_price", "size_oz", "peak_price"}
    win_count = 0
    loss_count = 0
    total_pnl = 0

    for i in range(50, len(silver_prices)):
        price = silver_prices[i]

        # Generate signal based on strategy
        signal = _generate_signal(
            silver_prices[:i+1], gold_prices[:i+1],
            copper_prices[:i+1], dxy_prices[:i+1],
            strategy=strategy,
        )

        # Position management
        if position is not None:
            # Update peak price for trailing stop
            if price > position["peak_price"]:
                position["peak_price"] = price

            # Check stop loss (4%)
            pnl_pct = (price - position["entry_price"]) / position["entry_price"]

            if pnl_pct <= -stop_loss_pct:
                # Stop loss hit
                pnl = position["size_oz"] * (price - position["entry_price"])
                equity += pnl
                total_pnl += pnl
                if pnl > 0:
                    win_count += 1
                else:
                    loss_count += 1
                trades.append({
                    "day": i, "action": "STOP_LOSS",
                    "entry": position["entry_price"], "exit": price,
                    "pnl": round(pnl, 2), "equity": round(equity, 2),
                })
                position = None
                continue

            # Check trailing stop (after +2% gain)
            if pnl_pct >= trailing_trigger_pct:
                trail_price = position["peak_price"] * (1 - 0.025)
                if price <= trail_price:
                    pnl = position["size_oz"] * (price - position["entry_price"])
                    equity += pnl
                    total_pnl += pnl
                    if pnl > 0:
                        win_count += 1
                    else:
                        loss_count += 1
                    trades.append({
                        "day": i, "action": "TRAILING_STOP",
                        "entry": position["entry_price"], "exit": price,
                        "pnl": round(pnl, 2), "equity": round(equity, 2),
                    })
                    position = None
                    continue

            # Sell signal
            if signal == "SELL" and position is not None:
                pnl = position["size_oz"] * (price - position["entry_price"])
                equity += pnl
                total_pnl += pnl
                if pnl > 0:
                    win_count += 1
                else:
                    loss_count += 1
                trades.append({
                    "day": i, "action": "SELL",
                    "entry": position["entry_price"], "exit": price,
                    "pnl": round(pnl, 2), "equity": round(equity, 2),
                })
                position = None

        elif signal == "BUY" and position is None and equity > 10:
            # Open position with leverage
            position_value = equity * leverage
            size_oz = position_value / price
            position = {
                "entry_price": price,
                "size_oz": size_oz,
                "peak_price": price,
            }
            trades.append({
                "day": i, "action": "BUY",
                "entry": price, "size_oz": round(size_oz, 4),
                "equity": round(equity, 2),
            })

        # Track drawdown
        if equity > peak_equity:
            peak_equity = equity
        dd = (peak_equity - equity) / peak_equity * 100
        if dd > max_drawdown:
            max_drawdown = dd

    # Close any remaining position
    if position is not None:
        price = silver_prices[-1]
        pnl = position["size_oz"] * (price - position["entry_price"])
        equity += pnl
        total_pnl += pnl
        if pnl > 0:
            win_count += 1
        else:
            loss_count += 1
        trades.append({
            "day": len(silver_prices) - 1, "action": "CLOSE_FINAL",
            "entry": position["entry_price"], "exit": price,
            "pnl": round(pnl, 2), "equity": round(equity, 2),
        })

    total_trades = win_count + loss_count
    win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0
    total_return = ((equity - capital) / capital) * 100
    days = len(silver_prices) - 50
    daily_return = total_return / days if days > 0 else 0

    return {
        "strategy": strategy,
        "starting_capital": capital,
        "leverage": leverage,
        "final_equity": round(equity, 2),
        "total_return_pct": round(total_return, 2),
        "total_pnl": round(total_pnl, 2),
        "total_trades": total_trades,
        "wins": win_count,
        "losses": loss_count,
        "win_rate": round(win_rate, 1),
        "max_drawdown_pct": round(max_drawdown, 2),
        "daily_avg_return_pct": round(daily_return, 3),
        "days_tested": days,
        "stop_loss_pct": stop_loss_pct * 100,
        "trailing_trigger_pct": trailing_trigger_pct * 100,
        "trades": trades[-30:],  # Last 30 trades for inspection
    }


def _generate_signal(
    silver_prices: list,
    gold_prices: list,
    copper_prices: list,
    dxy_prices: list,
    strategy: str = "full",
) -> str:
    """Generate BUY/SELL/HOLD signal based on strategy."""

    if len(silver_prices) < 30 or len(gold_prices) < 30:
        return "HOLD"

    current_silver = silver_prices[-1]
    current_gold = gold_prices[-1]

    # Gold/Silver Ratio
    gsr = current_gold / current_silver if current_silver > 0 else 70
    gsr_5d_ago = gold_prices[-6] / silver_prices[-6] if silver_prices[-6] > 0 else gsr
    gsr_falling = gsr < gsr_5d_ago

    # Silver RSI
    rsi = compute_rsi(silver_prices, 14)

    # Silver MA
    ma20 = compute_sma(silver_prices, 20)
    above_ma20 = current_silver > ma20

    # DXY trend
    dxy_current = dxy_prices[-1]
    dxy_5d = dxy_prices[-6] if len(dxy_prices) >= 6 else dxy_current
    dxy_falling = dxy_current < dxy_5d

    # Copper trend
    copper_current = copper_prices[-1]
    copper_5d = copper_prices[-6] if len(copper_prices) >= 6 else copper_current
    copper_rising = copper_current > copper_5d

    # ---- STRATEGY: RATIO ONLY ----
    if strategy == "ratio_only":
        if gsr > 85 and gsr_falling:
            return "BUY"
        elif gsr > 90:
            return "BUY"  # Extreme -- buy regardless
        elif gsr < 65:
            return "SELL"
        elif gsr < 70 and not gsr_falling:
            return "SELL"
        return "HOLD"

    # ---- STRATEGY: INDUSTRIAL ----
    if strategy == "industrial":
        buy_signals = 0
        sell_signals = 0

        if copper_rising:
            buy_signals += 1
        else:
            sell_signals += 1

        # Copper leading silver (catch-up trade)
        copper_change = (copper_current - copper_5d) / copper_5d * 100
        silver_change = (current_silver - silver_prices[-6]) / silver_prices[-6] * 100
        if copper_change > 2 and silver_change < 1:
            buy_signals += 2  # Strong catch-up signal

        if rsi < 30:
            buy_signals += 1
        elif rsi > 70:
            sell_signals += 1

        if buy_signals >= 2:
            return "BUY"
        elif sell_signals >= 2:
            return "SELL"
        return "HOLD"

    # ---- STRATEGY: FUNDAMENTAL ----
    if strategy == "fundamental":
        buy_signals = 0
        sell_signals = 0

        # GSR
        if gsr > 85:
            buy_signals += 2
        elif gsr > 80:
            buy_signals += 1
        elif gsr < 65:
            sell_signals += 2
        elif gsr < 70:
            sell_signals += 1

        # DXY
        if dxy_falling:
            buy_signals += 1
        else:
            sell_signals += 1

        # RSI
        if rsi < 35:
            buy_signals += 1
        elif rsi > 65:
            sell_signals += 1

        if buy_signals >= 3:
            return "BUY"
        elif sell_signals >= 3:
            return "SELL"
        return "HOLD"

    # ---- STRATEGY: FULL (all 10 factors simplified) ----
    buy_score = 0
    sell_score = 0

    # 1. GSR (weight 20%)
    if gsr > 90:
        buy_score += 4
    elif gsr > 85:
        buy_score += 3
    elif gsr > 80:
        buy_score += 1
    elif gsr < 60:
        sell_score += 4
    elif gsr < 65:
        sell_score += 3
    elif gsr < 70:
        sell_score += 1

    if gsr_falling:
        buy_score += 1
    else:
        sell_score += 1

    # 2. DXY (weight 12%)
    dxy_mom = (dxy_current - dxy_prices[max(0, len(dxy_prices)-22)]) / dxy_prices[max(0, len(dxy_prices)-22)] * 100
    if dxy_mom < -2:
        buy_score += 2
    elif dxy_mom < -0.5:
        buy_score += 1
    elif dxy_mom > 2:
        sell_score += 2
    elif dxy_mom > 0.5:
        sell_score += 1

    # 3. Technical (RSI + MA)
    if rsi < 25:
        buy_score += 3
    elif rsi < 35:
        buy_score += 2
    elif rsi > 75:
        sell_score += 3
    elif rsi > 65:
        sell_score += 2

    if above_ma20:
        buy_score += 1
    else:
        sell_score += 1

    # 4. Copper correlation
    if copper_rising:
        buy_score += 1
    else:
        sell_score += 1

    copper_change = (copper_current - copper_5d) / copper_5d * 100
    silver_change = (current_silver - silver_prices[-6]) / silver_prices[-6] * 100
    if copper_change > 2 and silver_change < 1:
        buy_score += 2  # Catch-up trade

    # 5. Combo bonus: GSR > 85 + DXY falling
    if gsr > 85 and dxy_falling:
        buy_score += 3

    # Generate signal
    net = buy_score - sell_score
    if net >= 5:
        return "BUY"
    elif net <= -4:
        return "SELL"
    return "HOLD"


def main():
    print("=" * 70)
    print("MadEye Silver Backtest Engine")
    print("=" * 70)
    print(f"Starting Capital: $100 CAD | Leverage: 5x | Stop Loss: 4%")
    print(f"Trailing Stop: trigger +2%, trail 2.5%")
    print()

    silver_prices, gold_prices, copper_prices, dxy_prices = fetch_data()

    if not silver_prices:
        print("ERROR: Failed to fetch data")
        sys.exit(1)

    print(f"Data: {len(silver_prices)} daily bars")
    print(f"Silver range: ${min(silver_prices):.2f} - ${max(silver_prices):.2f}")
    print(f"Current GSR: {gold_prices[-1]/silver_prices[-1]:.1f}")
    print()

    strategies = ["ratio_only", "industrial", "fundamental", "full"]
    results = []

    for strategy in strategies:
        print(f"--- Running: {strategy.upper()} ---")
        result = run_backtest(
            silver_prices, gold_prices, copper_prices, dxy_prices,
            strategy=strategy,
            capital=100.0,
            leverage=5.0,
        )
        results.append(result)

        print(f"  Final Equity: ${result['final_equity']:.2f}")
        print(f"  Total Return: {result['total_return_pct']:+.1f}%")
        print(f"  Trades: {result['total_trades']} (Win: {result['wins']}, Loss: {result['losses']})")
        print(f"  Win Rate: {result['win_rate']}%")
        print(f"  Max Drawdown: {result['max_drawdown_pct']:.1f}%")
        print(f"  Daily Avg Return: {result['daily_avg_return_pct']:.3f}%")
        print()

    # Save results
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    output_path = DATA_DIR / "backtest_results.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"Results saved to {output_path}")

    # Summary table
    print()
    print("=" * 70)
    print(f"{'Strategy':<15} {'Return':>8} {'Trades':>7} {'Win%':>6} {'MaxDD':>7} {'Final$':>8}")
    print("-" * 70)
    for r in results:
        print(
            f"{r['strategy']:<15} {r['total_return_pct']:>+7.1f}% "
            f"{r['total_trades']:>6} {r['win_rate']:>5.1f}% "
            f"{r['max_drawdown_pct']:>6.1f}% ${r['final_equity']:>7.2f}"
        )
    print("=" * 70)
    print()
    print("NOTE: These are HONEST results on real historical data.")
    print("Past performance does not guarantee future results.")
    print("Silver is 2x more volatile than gold -- position size accordingly.")


if __name__ == "__main__":
    main()
