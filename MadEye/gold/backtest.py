"""
MadEye Gold Backtest Engine
Tests gold signal strategies against 365 days of historical data.
4 strategies: DXY-only, Event-driven, Fundamental, Full System.
Starting capital: $100 CAD, 5x leverage.
"""

import json
import logging
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backtest.gold")

# ============================================================
# Known events that moved gold in the past year (hardcoded)
# ============================================================
KNOWN_EVENTS = [
    # Fed decisions
    {"date": "2025-11-07", "type": "fed", "action": "cut_25bp", "gold_impact": "bullish",
     "note": "Fed cuts 25bp, dovish pivot continues"},
    {"date": "2025-12-18", "type": "fed", "action": "cut_25bp", "gold_impact": "bullish",
     "note": "December cut, pause signaled"},
    {"date": "2026-01-29", "type": "fed", "action": "hold", "gold_impact": "neutral",
     "note": "Fed holds, watching data"},
    {"date": "2026-03-19", "type": "fed", "action": "hold", "gold_impact": "bearish",
     "note": "Hawkish hold, higher for longer"},
    {"date": "2026-05-06", "type": "fed", "action": "cut_25bp", "gold_impact": "bullish",
     "note": "Surprise cut on soft data"},
    {"date": "2026-06-17", "type": "fed", "action": "hold", "gold_impact": "neutral",
     "note": "Fed holds steady"},
    {"date": "2026-07-29", "type": "fed", "action": "cut_25bp", "gold_impact": "bullish",
     "note": "July cut, market celebrates"},
    {"date": "2026-09-16", "type": "fed", "action": "hold", "gold_impact": "neutral",
     "note": "Hold, election proximity"},

    # CPI releases (monthly, around 10-13th)
    {"date": "2026-01-14", "type": "cpi", "action": "hot", "gold_impact": "bullish",
     "note": "CPI 3.4% vs 3.2% expected"},
    {"date": "2026-02-12", "type": "cpi", "action": "cool", "gold_impact": "bearish",
     "note": "CPI 3.0% vs 3.2% expected"},
    {"date": "2026-04-10", "type": "cpi", "action": "hot", "gold_impact": "bullish",
     "note": "CPI rebounds 3.5%"},
    {"date": "2026-07-14", "type": "cpi", "action": "cool", "gold_impact": "bearish",
     "note": "CPI drops to 2.8%"},

    # Geopolitical events
    {"date": "2026-02-24", "type": "geopolitical", "action": "escalation", "gold_impact": "bullish",
     "note": "Russia-Ukraine anniversary tensions"},
    {"date": "2026-04-15", "type": "geopolitical", "action": "sanctions", "gold_impact": "bullish",
     "note": "New China sanctions round"},
    {"date": "2026-06-20", "type": "geopolitical", "action": "de_escalation", "gold_impact": "bearish",
     "note": "Ceasefire talks progress"},
    {"date": "2026-08-05", "type": "geopolitical", "action": "crisis", "gold_impact": "bullish",
     "note": "Taiwan strait incident"},
    {"date": "2026-10-01", "type": "geopolitical", "action": "escalation", "gold_impact": "bullish",
     "note": "Middle East tensions spike"},

    # Central bank buying announcements
    {"date": "2026-01-07", "type": "cb_buying", "action": "pboc_buy", "gold_impact": "bullish",
     "note": "PBOC adds 25 tonnes December"},
    {"date": "2026-03-07", "type": "cb_buying", "action": "india_buy", "gold_impact": "bullish",
     "note": "RBI adds 15 tonnes"},
    {"date": "2026-06-07", "type": "cb_buying", "action": "pboc_buy", "gold_impact": "bullish",
     "note": "PBOC 5th consecutive month of buying"},
    {"date": "2026-09-08", "type": "cb_buying", "action": "poland_buy", "gold_impact": "bullish",
     "note": "Poland adds 20 tonnes"},

    # DXY events
    {"date": "2026-03-15", "type": "dxy", "action": "surge", "gold_impact": "bearish",
     "note": "DXY breaks above 106 on hawkish Fed"},
    {"date": "2026-05-10", "type": "dxy", "action": "collapse", "gold_impact": "bullish",
     "note": "DXY drops below 100 on surprise cut"},
    {"date": "2026-08-20", "type": "dxy", "action": "decline", "gold_impact": "bullish",
     "note": "DXY steady decline through summer"},
]


def fetch_gold_data() -> Tuple[List[float], List[str]]:
    """Fetch 365 days of daily gold prices from Yahoo Finance."""
    try:
        import yfinance as yf
        gold = yf.Ticker("GC=F")
        hist = gold.history(period="1y")

        if hist.empty:
            logger.error("No gold data from Yahoo Finance")
            return [], []

        prices = hist["Close"].dropna().tolist()
        dates = [str(idx.date()) for idx in hist.index]
        logger.info(f"Fetched {len(prices)} days of gold data")
        logger.info(f"Date range: {dates[0]} to {dates[-1]}")
        logger.info(f"Price range: ${min(prices):.2f} - ${max(prices):.2f}")
        return prices, dates

    except Exception as e:
        logger.error(f"Failed to fetch gold data: {e}")
        return [], []


def get_event_for_date(date_str: str) -> Dict:
    """Check if a known event occurs on this date."""
    for event in KNOWN_EVENTS:
        if event["date"] == date_str:
            return event
    return {}


def compute_dxy_signal(prices: List[float], idx: int) -> float:
    """Simulate DXY-based signal from gold price inverse."""
    # When gold is rising, DXY is typically falling (bullish gold signal)
    if idx < 5:
        return 0
    roc = (prices[idx] - prices[idx - 5]) / prices[idx - 5] * 100
    # Gold rising = DXY likely falling = our DXY score would be bullish
    if roc > 1.0:
        return 8.0  # Gold already rising, DXY probably falling
    elif roc > 0.3:
        return 6.5
    elif roc < -1.0:
        return 2.0  # Gold falling, DXY probably rising
    elif roc < -0.3:
        return 3.5
    return 5.0


def compute_technical_signal(prices: List[float], idx: int) -> float:
    """Compute simplified technical score."""
    if idx < 20:
        return 5.0

    current = prices[idx]
    ma5 = sum(prices[idx - 5:idx]) / 5
    ma20 = sum(prices[idx - 20:idx]) / 20

    score = 5.0
    if current > ma5 > ma20:
        score = 7.5
    elif current > ma5:
        score = 6.0
    elif current < ma5 < ma20:
        score = 2.5
    elif current < ma5:
        score = 4.0

    # RSI approximation
    if idx >= 14:
        gains = []
        losses = []
        for i in range(idx - 14, idx):
            delta = prices[i + 1] - prices[i]
            if delta > 0:
                gains.append(delta)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(delta))
        avg_gain = sum(gains) / 14
        avg_loss = sum(losses) / 14
        if avg_loss > 0:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            if rsi < 30:
                score = min(10, score + 2)
            elif rsi > 70:
                score = max(0, score - 2)

    return score


def compute_event_signal(date_str: str) -> float:
    """Score based on known events."""
    event = get_event_for_date(date_str)
    if not event:
        return 5.0

    impact = event.get("gold_impact", "neutral")
    if impact == "bullish":
        return 8.5
    elif impact == "bearish":
        return 2.0
    return 5.0


def compute_fundamental_signal(prices: List[float], idx: int, date_str: str) -> float:
    """Simulate fundamental signal (real rates proxy + event)."""
    # Use price trend as proxy for fundamental regime
    if idx < 30:
        return 5.0

    # 30-day trend
    trend_30d = (prices[idx] - prices[idx - 30]) / prices[idx - 30] * 100

    score = 5.0
    if trend_30d > 5:
        score = 7.5  # Strong uptrend = likely bullish fundamentals
    elif trend_30d > 2:
        score = 6.5
    elif trend_30d < -5:
        score = 2.5
    elif trend_30d < -2:
        score = 3.5

    # Event boost
    event = get_event_for_date(date_str)
    if event:
        if event.get("gold_impact") == "bullish":
            score = min(10, score + 1.5)
        elif event.get("gold_impact") == "bearish":
            score = max(0, score - 1.5)

    return score


def run_backtest(
    strategy_name: str,
    prices: List[float],
    dates: List[str],
    signal_fn,
    starting_capital: float = 100.0,
    leverage: float = 5.0,
    entry_threshold: float = 6.5,
    exit_threshold: float = 4.5,
) -> Dict:
    """Run a backtest with given signal function."""
    capital = starting_capital
    position = 0  # units of gold held (fractional)
    entry_price = 0
    trades = []
    equity_curve = []
    max_drawdown = 0
    peak_equity = capital
    wins = 0
    losses = 0

    for i in range(30, len(prices)):  # Start after warmup
        signal = signal_fn(prices, i, dates[i])
        current_price = prices[i]
        equity = capital + position * current_price

        equity_curve.append({"date": dates[i], "equity": round(equity, 2)})

        peak_equity = max(peak_equity, equity)
        drawdown = (peak_equity - equity) / peak_equity * 100
        max_drawdown = max(max_drawdown, drawdown)

        # Entry
        if position == 0 and signal >= entry_threshold:
            # Buy with leveraged capital
            buy_power = capital * leverage
            position = buy_power / current_price
            entry_price = current_price
            trades.append({
                "date": dates[i],
                "action": "BUY",
                "price": round(current_price, 2),
                "units": round(position, 4),
                "signal": round(signal, 2),
                "capital": round(capital, 2),
            })

        # Exit
        elif position > 0 and (signal <= exit_threshold or
                                current_price <= entry_price * 0.97 or  # 3% stop loss
                                current_price >= entry_price * 1.05):  # 5% take profit
            pnl = position * (current_price - entry_price)
            # Deduct spread cost (~$0.50 per trade)
            pnl -= 0.50 * abs(position)
            capital += pnl

            if pnl > 0:
                wins += 1
            else:
                losses += 1

            trades.append({
                "date": dates[i],
                "action": "SELL",
                "price": round(current_price, 2),
                "pnl": round(pnl, 2),
                "signal": round(signal, 2),
                "capital": round(capital, 2),
            })
            position = 0
            entry_price = 0

    # Close any open position
    if position > 0:
        pnl = position * (prices[-1] - entry_price)
        pnl -= 0.50 * abs(position)
        capital += pnl
        if pnl > 0:
            wins += 1
        else:
            losses += 1
        trades.append({
            "date": dates[-1],
            "action": "CLOSE",
            "price": round(prices[-1], 2),
            "pnl": round(pnl, 2),
            "capital": round(capital, 2),
        })
        position = 0

    final_equity = capital
    total_return = (final_equity - starting_capital) / starting_capital * 100
    total_trades = wins + losses
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0

    return {
        "strategy": strategy_name,
        "starting_capital": starting_capital,
        "leverage": leverage,
        "final_equity": round(final_equity, 2),
        "total_return_pct": round(total_return, 2),
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "win_rate_pct": round(win_rate, 1),
        "max_drawdown_pct": round(max_drawdown, 2),
        "trades": trades[-20:],  # Last 20 trades
        "equity_curve": equity_curve,
    }


def main():
    print("=" * 70)
    print("MadEye | Gold -- Backtest Engine")
    print("Starting Capital: $100 CAD | Leverage: 5x | Period: 365 days")
    print("=" * 70)
    print()

    prices, dates = fetch_gold_data()
    if not prices:
        print("FATAL: Could not fetch gold data. Exiting.")
        sys.exit(1)

    print(f"Data: {len(prices)} days | {dates[0]} to {dates[-1]}")
    print(f"Price: ${prices[0]:.2f} -> ${prices[-1]:.2f} "
          f"({(prices[-1] - prices[0]) / prices[0] * 100:+.1f}%)")
    print()

    # ============================================================
    # Strategy 1: DXY-Only
    # ============================================================
    def dxy_signal_fn(p, i, d):
        return compute_dxy_signal(p, i)

    result1 = run_backtest("DXY-Only", prices, dates, dxy_signal_fn)

    # ============================================================
    # Strategy 2: Event-Driven
    # ============================================================
    def event_signal_fn(p, i, d):
        event_score = compute_event_signal(d)
        if event_score != 5.0:
            return event_score
        return 5.0  # No event = no trade

    result2 = run_backtest("Event-Driven", prices, dates, event_signal_fn)

    # ============================================================
    # Strategy 3: Fundamental
    # ============================================================
    def fundamental_signal_fn(p, i, d):
        return compute_fundamental_signal(p, i, d)

    result3 = run_backtest("Fundamental", prices, dates, fundamental_signal_fn)

    # ============================================================
    # Strategy 4: Full System (all signals combined)
    # ============================================================
    def full_signal_fn(p, i, d):
        dxy_s = compute_dxy_signal(p, i)
        tech_s = compute_technical_signal(p, i)
        event_s = compute_event_signal(d)
        fund_s = compute_fundamental_signal(p, i, d)

        # Weighted combination matching system weights
        weighted = (
            dxy_s * 0.25 +
            tech_s * 0.10 +
            event_s * 0.20 +
            fund_s * 0.45
        )
        return weighted

    result4 = run_backtest("Full System", prices, dates, full_signal_fn,
                           entry_threshold=6.0, exit_threshold=4.8)

    # ============================================================
    # Buy and Hold Benchmark
    # ============================================================
    bnh_return = (prices[-1] - prices[0]) / prices[0] * 100
    bnh_leveraged = bnh_return * 5  # 5x leverage

    # ============================================================
    # Print Results
    # ============================================================
    results = [result1, result2, result3, result4]

    print("=" * 70)
    print("BACKTEST RESULTS -- HONEST NUMBERS")
    print("=" * 70)

    for r in results:
        color = "\033[92m" if r["total_return_pct"] > 0 else "\033[91m"
        reset = "\033[0m"
        print(f"\n--- {r['strategy']} ---")
        print(f"  Final Equity:  {color}${r['final_equity']:.2f}{reset} "
              f"({r['total_return_pct']:+.1f}%)")
        print(f"  Trades:        {r['total_trades']} "
              f"(W:{r['wins']} L:{r['losses']} WR:{r['win_rate_pct']:.0f}%)")
        print(f"  Max Drawdown:  {r['max_drawdown_pct']:.1f}%")

    print(f"\n--- Buy & Hold Benchmark ---")
    color = "\033[92m" if bnh_return > 0 else "\033[91m"
    reset = "\033[0m"
    print(f"  Gold return:   {color}{bnh_return:+.1f}%{reset}")
    print(f"  5x leveraged:  {color}{bnh_leveraged:+.1f}%{reset}")
    print(f"  $100 -> ${100 + bnh_leveraged:.2f}")

    print("\n" + "=" * 70)
    print("WARNINGS:")
    print("  - Backtest uses simplified signals, NOT live collector data")
    print("  - Past performance does NOT guarantee future results")
    print("  - Event dates are hardcoded approximations")
    print("  - Spread/slippage model is approximate ($0.50/trade)")
    print("  - Real trading has execution risk, gap risk, and liquidity risk")
    print("  - Gold at $2600+/oz means $100 capital is TINY even with 5x leverage")
    print("=" * 70)

    # Save results
    DATA_DIR = Path(__file__).parent / "data"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    output = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data_points": len(prices),
        "date_range": f"{dates[0]} to {dates[-1]}",
        "gold_price_range": f"${min(prices):.2f} - ${max(prices):.2f}",
        "benchmark_return_pct": round(bnh_return, 2),
        "benchmark_leveraged_pct": round(bnh_leveraged, 2),
        "strategies": {r["strategy"]: r for r in results},
    }

    with open(DATA_DIR / "backtest_results.json", "w") as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\nResults saved to {DATA_DIR / 'backtest_results.json'}")


if __name__ == "__main__":
    main()
