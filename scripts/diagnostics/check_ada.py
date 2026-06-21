
import pandas as pd
from pathlib import Path

def check_ada():
    path = Path("data/ohlcv/ADA-USDT/1h.parquet")
    if not path.exists():
        print("Path not found")
        return
    
    df = pd.read_parquet(path)
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
    nov_2025 = df[(df['timestamp'] >= '2025-11-01T00:00:00Z') & (df['timestamp'] < '2025-11-02T00:00:00Z')]
    if nov_2025.empty:
        print("No data for Nov 2025")
    else:
        print("ADA Nov 1, 2025:")
        print(nov_2025.head(5))

if __name__ == "__main__":
    check_ada()
