
import json
import urllib.request

HYPERLIQUID_INFO_URL = "https://api.hyperliquid.xyz/info"

def get_btc_price():
    payload = {"type": "metaAndAssetCtxs"}
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        HYPERLIQUID_INFO_URL,
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        resp = json.loads(response.read())
        meta, ctxs = resp[0], resp[1]
        universe = meta.get("universe", [])
        for idx, asset in enumerate(universe):
            if asset.get("name") == "BTC":
                print(f"HyperLiquid BTC Price: {ctxs[idx].get('mid')}")
                return

if __name__ == "__main__":
    get_btc_price()
