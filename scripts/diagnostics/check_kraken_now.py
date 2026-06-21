
import ccxt
def check():
    ex = ccxt.kraken()
    print(f"Kraken current BTC/USD: {ex.fetch_ticker('BTC/USD')['last']}")
if __name__ == "__main__":
    check()
