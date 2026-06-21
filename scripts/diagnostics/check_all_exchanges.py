
import ccxt
import pandas as pd
from datetime import datetime, timezone

def check_exchanges():
    symbol = "BTC/USDT"
    # Nov 1, 2025
    since_ms = 1761955200000 
    
    exchanges = ["binance", "kraken", "bybit", "okx"]
    for ex_id in exchanges:
        try:
            ex_cls = getattr(ccxt, ex_id)
            ex = ex_cls()
            rows = ex.fetch_ohlcv(symbol if ex_id != "kraken" else "BTC/USD", timeframe="1h", since=since_ms, limit=1)
            if rows:
                print(f"{ex_id} BTC Price: {rows[0][4]}")
            else:
                print(f"{ex_id} No data")
        except Exception as e:
            print(f"{ex_id} error: {e}")

if __name__ == "__main__":
    check_exchanges()
