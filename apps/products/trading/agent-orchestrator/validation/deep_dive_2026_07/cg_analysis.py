"""Daily derivatives context from CoinGlass: build per-day feature table for BTC & ETH."""
import json, datetime, statistics
d=json.load(open("coinglass_raw.json"))
def day(ms): return datetime.datetime.fromtimestamp(int(ms)/1000, datetime.timezone.utc).date()
tables={}
for coin in ("BTC","ETH"):
    t={}
    def put(name, rows, fn):
        for r in rows: t.setdefault(day(r["time"]), {})[name]=fn(r)
    put("price_close", d[coin]["price"]["data"], lambda r: float(r["close"]))
    put("oi_close", d[coin]["oi"]["data"], lambda r: float(r["close"]))
    put("funding", d[coin]["funding"]["data"], lambda r: float(r["close"]))
    put("funding_bybit", d[coin]["funding_bybit"]["data"], lambda r: float(r["close"]))
    put("liq_long", d[coin]["liq"]["data"], lambda r: float(r["aggregated_long_liquidation_usd"]))
    put("liq_short", d[coin]["liq"]["data"], lambda r: float(r["aggregated_short_liquidation_usd"]))
    put("taker_buy", d[coin]["taker"]["data"], lambda r: float(r["taker_buy_volume_usd"]))
    put("taker_sell", d[coin]["taker"]["data"], lambda r: float(r["taker_sell_volume_usd"]))
    put("gls", d[coin]["gls"]["data"], lambda r: float(r["global_account_long_short_ratio"]))
    put("tls", d[coin]["tls"]["data"], lambda r: float(r["top_position_long_short_ratio"]))
    days=sorted(t)
    # derived: price/oi direction, fuel quadrant, funding percentile
    feats={}
    for i in range(1,len(days)):
        cur,prev=t[days[i]],t[days[i-1]]
        if "price_close" not in cur or "price_close" not in prev or "oi_close" not in cur or "oi_close" not in prev: continue
        pr=(cur["price_close"]-prev["price_close"])/prev["price_close"]
        oir=(cur["oi_close"]-prev["oi_close"])/prev["oi_close"]
        f={}
        f["price_ret"]=pr; f["oi_ret"]=oir
        f["fuel"]= "confirmed" if (pr>0)==(oir>0) else "unfueled"
        f["quadrant"]=("up" if pr>0 else "down")+"_"+("oi_up" if oir>0 else "oi_down")
        for k in ("funding","funding_bybit","gls","tls","liq_long","liq_short","taker_buy","taker_sell"):
            if k in cur: f[k]=cur[k]
        feats[days[i].isoformat()]=f
    tables[coin]=feats
json.dump(tables, open("cg_daily_features.json","w"))
print({c:len(tables[c]) for c in tables})
# quick sanity: funding distribution
for coin in tables:
    fr=[v["funding"] for v in tables[coin].values() if "funding" in v]
    fr.sort()
    print(coin,"funding daily close: min",fr[0],"p25",fr[len(fr)//4],"med",fr[len(fr)//2],"p75",fr[3*len(fr)//4],"max",fr[-1])
