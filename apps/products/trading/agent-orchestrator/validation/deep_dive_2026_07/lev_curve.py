"""PF(margin-scale) vs leverage curve on real trades, with liquidation-
before-SL mechanics (isolated, flat MMR, cushion = 1/L - MMR).
Also per-trade max_safe_leverage distribution (buffer_k=1.0 x ATR14)."""
import json
import csv
import statistics

MMR = 0.004
FEE_RT = 0.0007  # maker entry + blended exit (best-config F12)
def pf(v):
    gains = sum(r for r in v if r > 0)
    losses = -sum(r for r in v if r < 0)
    return gains / losses if losses > 0 else None
def load(venue,asset):
    rows=list(csv.DictReader(open(f"candles_{venue}_{asset}.csv")))
    return [(float(r["open"]),float(r["high"]),float(r["low"]),float(r["close"])) for r in rows]

def atr14(candles,i):
    trs=[]
    for k in range(max(1,i-13),i+1):
        h, low = candles[k][1], candles[k][2]
        pc=candles[k-1][3]
        trs.append(max(h-low,abs(h-pc),abs(low-pc)))
    return sum(trs)/len(trs)

def replay_lev(t,candles,L,be=None,mom=None,max_hold=20):
    """Return margin-scale net return; liquidation loses full margin."""
    e=t["entry"]
    sl=t["sl"]
    tp=t["tp1"]
    long_=t["direction"]=="LONG"
    sgn=1.0 if long_ else -1.0
    R=abs(e-sl)
    stop=sl
    be_armed=False
    cushion=1.0/L-MMR
    liq = e*(1-cushion) if long_ else e*(1+cushion)
    seq=candles[t["index"]+1:t["index"]+1+max_hold]
    if not seq:
        return None,False
    for _o,h,low,c in seq:
        # liquidation check BEFORE SL (same discipline as simulate_leveraged_trade)
        if (low<=liq) if long_ else (h>=liq):
            return -1.0, True   # -100% margin
        if (low<=stop) if long_ else (h>=stop):
            return L*(sgn*(stop-e)/e - FEE_RT), False
        if (h>=tp) if long_ else (low<=tp):
            return L*(sgn*(tp-e)/e - FEE_RT), False
        fav=sgn*(c-e)
        if be is not None and not be_armed and fav>=be*R:
            stop=e
            be_armed=True
        if mom is not None and fav<=-mom*R:
            return L*(sgn*(c-e)/e - FEE_RT), False
    return L*(sgn*(seq[-1][3]-e)/e - FEE_RT), False

trades=[]
for venue in ("binance","bybit"):
    for asset in ("BTC","ETH"):
        d=json.load(open(f"result_{venue}_{asset}.json"))
        candles=load(venue,asset)
        for t in d["trades"]:
            if t["censored"]:
                continue
            i=t["index"]
            closes=[c[3] for c in candles[max(0,i-199):i+1]]
            aligned=(t["direction"]=="LONG")==(candles[i][3]>sum(closes)/len(closes))
            if not (aligned and t["rr"] and 2<=t["rr"]<5):
                continue
            a=atr14(candles,i)
            # max_safe: cushion*e >= |e-sl| + buffer_k*ATR  ->  L <= 1/((|e-sl|+ATR)/e + MMR)
            need=(abs(t["entry"]-t["sl"])+1.0*a)/t["entry"]
            t["max_safe"]=1.0/(need+MMR)
            t["asset"]=asset
            t["candles"]=candles
            trades.append(t)

ms=sorted(t["max_safe"] for t in trades)
print(f"max_safe_leverage distribution (stack, n={len(ms)}, SL default 0.25-0.5xATR, buffer 1xATR):")
print(f"  p05={ms[int(0.05*len(ms))]:.1f}x p25={ms[len(ms)//4]:.1f}x p50={ms[len(ms)//2]:.1f}x p75={ms[3*len(ms)//4]:.1f}x p95={ms[int(0.95*len(ms))]:.1f}x")
print()
print(f"{'L':>4s} {'PF_margin':>9s} {'liq_n':>6s} {'liq%':>6s} {'mean%/margin':>12s}  (per-asset exit: BTC be1 / ETH mom0.3)")
for L in (2,3,5,8,10,12,15,20,25,30,40,50):
    rets=[]
    liqs=0
    for t in trades:
        kw = {"be":1.0} if t["asset"]=="BTC" else {"mom":0.3}
        r,liq=replay_lev(t,t["candles"],L,**kw)
        if r is None:
            continue
        rets.append(r)
        liqs+=liq
    print(f"{L:4d} {pf(rets):9.3f} {liqs:6d} {100*liqs/len(rets):5.1f}% {statistics.mean(rets)*100:+11.2f}%")
