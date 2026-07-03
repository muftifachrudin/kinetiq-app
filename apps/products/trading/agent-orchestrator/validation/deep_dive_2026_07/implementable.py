"""Test IMPLEMENTABLE (no-lookahead) filters on the pooled backtest trades."""
import collections
import csv
import datetime
import json
import statistics

def pf(rets):
    gains = sum(r for r in rets if r > 0)
    losses = -sum(r for r in rets if r < 0)
    return (gains / losses) if losses > 0 else None

# load candles into dict for SMA computation
closes={}
for venue in ("binance","bybit"):
    for asset in ("BTC","ETH"):
        rows=list(csv.DictReader(open(f"candles_{venue}_{asset}.csv")))
        closes[(venue,asset)]=[float(r["close"]) for r in rows]

cg=json.load(open("cg_daily_features.json"))
all_tr=[]
for venue in ("binance","bybit"):
    for asset in ("BTC","ETH"):
        d=json.load(open(f"result_{venue}_{asset}.json"))
        cl=closes[(venue,asset)]
        for t in d["trades"]:
            if t["censored"]:
                continue
            i=t["index"]
            t["venue"],t["asset"]=venue,asset
            t["date"]=t["ts"][:10]
            # HTF trend proxies computable at entry (close index i known at bar close)
            sma200 = sum(cl[max(0,i-199):i+1])/min(200,i+1)   # ~8.3 hari
            sma50  = sum(cl[max(0,i-49):i+1])/min(50,i+1)     # ~2 hari
            t["above200"]=cl[i]>sma200
            t["above50"]=cl[i]>sma50
            # prev-day drift from CoinGlass table (previous calendar day = known)
            dt0=datetime.date.fromisoformat(t["date"])
            prev=(dt0-datetime.timedelta(days=1)).isoformat()
            f=cg[asset].get(prev)
            t["prev_drift_up"]= (f["price_ret"]>0) if f else None
            all_tr.append(t)

def rep(name, tr):
    v=[t["return_pct"] for t in tr]
    if len(v)<10:
        print(f"{name:44s} n={len(v)} (kecil)")
        return
    wr=sum(1 for r in v if r>0)/len(v)
    p=pf(v)
    print(f"{name:44s} n={len(v):4d} PF={p:.3f} WR={wr:.1%} mean={statistics.mean(v)*100:+.3f}%")

print("baseline:")
rep("ALL", all_tr)
print()
print("-- Filter tren HTF (tanpa lookahead):")
rep("LONG  & close>SMA200(1h) [trend up]", [t for t in all_tr if t["direction"]=="LONG" and t["above200"]])
rep("LONG  & close<SMA200 [countertrend]", [t for t in all_tr if t["direction"]=="LONG" and not t["above200"]])
rep("SHORT & close<SMA200 [trend down]", [t for t in all_tr if t["direction"]=="SHORT" and not t["above200"]])
rep("SHORT & close>SMA200 [countertrend]", [t for t in all_tr if t["direction"]=="SHORT" and t["above200"]])
rep("ALIGNED sma200 (dir==trend)", [t for t in all_tr if (t["direction"]=="LONG")==t["above200"]])
rep("COUNTER sma200", [t for t in all_tr if (t["direction"]=="LONG")!=t["above200"]])
print()
rep("ALIGNED sma50", [t for t in all_tr if (t["direction"]=="LONG")==t["above50"]])
rep("COUNTER sma50", [t for t in all_tr if (t["direction"]=="LONG")!=t["above50"]])
print()
print("-- Prev-day drift (implementable versi 'day drift'):")
rep("dir == prev-day drift", [t for t in all_tr if t["prev_drift_up"] is not None and (t["direction"]=="LONG")==t["prev_drift_up"]])
rep("dir != prev-day drift", [t for t in all_tr if t["prev_drift_up"] is not None and (t["direction"]=="LONG")!=t["prev_drift_up"]])
print()
print("-- R:R re-gate:")
rep("rr >= 2.0", [t for t in all_tr if (t["rr"] or 0)>=2])
rep("rr 2.0-5.0", [t for t in all_tr if 2<=(t["rr"] or 0)<5])
print()
print("-- KOMBINASI implementable:")
combo=[t for t in all_tr if (t["direction"]=="LONG")==t["above200"] and 2<=(t["rr"] or 0)<5]
rep("aligned200 & rr∈[2,5)", combo)
for a in ("BTC","ETH"):
    rep(f"  ..{a} only", [t for t in combo if t["asset"]==a])
for v_ in ("binance","bybit"):
    rep(f"  ..{v_} only", [t for t in combo if t["venue"]==v_])
# per-window PF of combo (does it pass promotion?)
print()
print("-- KOMBINASI per window (all 4 series pooled by test month):")
bym=collections.defaultdict(list)
for t in combo:
    bym[t["ts"][:7]].append(t["return_pct"])
for mth in sorted(bym):
    v=bym[mth]
    print(f"   {mth}: n={len(v):3d} PF={pf(v) if pf(v) is not None else float('inf'):.3f}")
json.dump([{k:t.get(k) for k in ("ts","venue","asset","direction","return_pct","confidence","rr","above200","above50","bars_held","outcome","date")} for t in all_tr], open("pooled_trades.json","w"))
