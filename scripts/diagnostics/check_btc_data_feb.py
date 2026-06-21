
import pandas as pd
from pathlib import Path

def check_data():
    path = Path("data/ohlcv/BTC-USDT/1h.parquet")
    if not path.exists():
        print("Path not found")
        return
    
    df = pd.read_parquet(path)
    print(f"Total rows: {len(df)}")
    
    # Filter for Feb 2026
    feb_2026 = df[(df['timestamp'] >= '2026-02-01') & (df['timestamp'] < '2026-03-01')]
    if feb_2026.empty:
        print("No data for Feb 2026")
    else:
        print("Sample data from Feb 2026:")
        print(feb_2026.head(5))

if __name__ == "__main__":
    check_data()
