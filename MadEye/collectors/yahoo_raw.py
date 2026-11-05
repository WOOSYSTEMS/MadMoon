"""
Raw Yahoo Finance HTTP client. No yfinance dependency.
"""
import urllib.request
import json


def get_price(symbol: str) -> dict:
    """Get current price data for a symbol."""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=5d"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        data = json.loads(urllib.request.urlopen(req, timeout=10).read())
        result = data["chart"]["result"][0]
        meta = result["meta"]
        quotes = result["indicators"]["quote"][0]

        price = meta.get("regularMarketPrice", 0)
        prev = meta.get("chartPreviousClose", meta.get("previousClose", price))

        closes = [c for c in (quotes.get("close") or []) if c is not None]

        return {
            "price": price,
            "prev_close": prev,
            "change": price - prev,
            "change_pct": ((price - prev) / prev * 100) if prev else 0,
            "closes": closes,
            "high": quotes.get("high", [None])[-1],
            "low": quotes.get("low", [None])[-1],
            "volume": quotes.get("volume", [None])[-1],
        }
    except Exception as e:
        return {"price": None, "error": str(e)}


def get_history(symbol: str, period: str = "1mo") -> list:
    """Get historical closes."""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range={period}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        data = json.loads(urllib.request.urlopen(req, timeout=10).read())
        result = data["chart"]["result"][0]
        closes = result["indicators"]["quote"][0].get("close", [])
        return [c for c in closes if c is not None]
    except:
        return []
