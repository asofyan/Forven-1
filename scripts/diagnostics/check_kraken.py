
import ccxt
import pandas as pd
from datetime import datetime, timezone

def check_kraken():
    # Nov 1, 2025
    since_ms = 1761955200000 
    ex = ccxt.kraken()
    
    for symbol in ["BTC/USD", "BTC/USDT"]:
        try:
            rows = ex.fetch_ohlcv(symbol, timeframe="1h", since=since_ms, limit=1)
            if rows:
                print(f"Kraken {symbol} Price: {rows[0][4]}")
            else:
                print(f"Kraken {symbol} No data")
        except Exception as e:
            print(f"Kraken {symbol} error: {e}")

if __name__ == "__main__":
    check_kraken()
