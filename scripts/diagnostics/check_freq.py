
import pandas as pd
from pathlib import Path

def check_freq():
    path = Path("data/ohlcv/BTC-USDT/1h.parquet")
    df = pd.read_parquet(path)
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
    diffs = df['timestamp'].diff().tail(100)
    print("Last 100 timestamp differences:")
    print(diffs.value_counts())

if __name__ == "__main__":
    check_freq()
