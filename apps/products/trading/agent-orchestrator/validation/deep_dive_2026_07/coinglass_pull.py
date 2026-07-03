"""One-off pull of ~400 days of daily CoinGlass Hobbyist data for BTC & ETH.

Writes coinglass_raw.json in the current working directory. Requires
COINGLASS_API_KEY in the environment. Gotchas (verified 3 Jul 2026):
per-pair endpoints require exchange=; aggregated endpoints take the coin
symbol (BTC) and liquidation requires exchange_list=; interval=1h returns
HTTP 403 on the Hobbyist plan (daily-only); burst requests get connection
resets, so keep the ~2.5s sleep between calls.
"""
import os, json, urllib.request, time

KEY = os.environ["COINGLASS_API_KEY"]
BASE = "https://open-api-v4.coinglass.com/api"


def get(path, **params):
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    for attempt in range(5):
        req = urllib.request.Request(f"{BASE}/{path}?{qs}", headers={"CG-API-KEY": KEY, "accept": "application/json"})
        try:
            return json.loads(urllib.request.urlopen(req, timeout=30).read())
        except Exception:
            time.sleep(2 * (attempt + 1))
    return {"error": "failed after retries"}


out = {}
for coin, pair in [("BTC", "BTCUSDT"), ("ETH", "ETHUSDT")]:
    out[coin] = {}
    out[coin]["oi"] = get("futures/open-interest/aggregated-history", symbol=coin, interval="1d", limit=400)
    time.sleep(2.5)
    out[coin]["liq"] = get("futures/liquidation/aggregated-history", symbol=coin, interval="1d", limit=400, exchange_list="Binance,Bybit,OKX")
    time.sleep(2.5)
    for name, path, exchange in [
        ("price", "futures/price/history", "Binance"),
        ("funding", "futures/funding-rate/history", "Binance"),
        ("funding_bybit", "futures/funding-rate/history", "Bybit"),
        ("taker", "futures/taker-buy-sell-volume/history", "Binance"),
        ("gls", "futures/global-long-short-account-ratio/history", "Binance"),
        ("tls", "futures/top-long-short-position-ratio/history", "Binance"),
    ]:
        d = get(path, symbol=pair, interval="1d", limit=400, exchange=exchange)
        out[coin][name] = d
        n = len(d.get("data", [])) if isinstance(d.get("data"), list) else "ERR"
        print(coin, name, "code=", d.get("code"), "n=", n, flush=True)
        time.sleep(2.5)
json.dump(out, open("coinglass_raw.json", "w"))
print("saved coinglass_raw.json")
