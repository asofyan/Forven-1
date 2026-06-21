
import pyarrow.parquet as pq
from pathlib import Path

def check_meta():
    path = Path("data/ohlcv/BTC-USDT/1h.parquet")
    if not path.exists():
        print("Path not found")
        return
    
    meta = pq.read_metadata(path)
    print(f"Num rows: {meta.num_rows}")
    print(f"Metadata: {meta.metadata}")

if __name__ == "__main__":
    check_meta()
