import pandas as pd
from pathlib import Path

def check_data():
    path = Path("data/ohlcv/BTC-USDT/1h.parquet")
    if not path.exists():
        print("Path not found")
        return
    
    df = pd.read_parquet(path)
    print(f"Total rows: {len(df)}")
    print(f"Columns: {df.columns.tolist()}")
    
    # Filter for Nov 2025
    nov_2025 = df[(df['timestamp'] >= '2025-11-01') & (df['timestamp'] < '2025-12-01')]
    if nov_2025.empty:
        print("No data for Nov 2025")
    else:
        print("Sample data from Nov 2025:")
        print(nov_2025.head(5))
        print("\nTail data from Nov 2025:")
        print(nov_2025.tail(5))

if __name__ == "__main__":
    check_data()
