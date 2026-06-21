
import ccxt
def check():
    ex = ccxt.binance()
    print(f"Binance current BTC/USDT: {ex.fetch_ticker('BTC/USDT')['last']}")
if __name__ == "__main__":
    check()
