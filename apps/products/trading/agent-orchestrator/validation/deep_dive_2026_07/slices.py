"""Slice diagnostics over the 4 replication results + CoinGlass daily join."""
import json
import statistics

def pf(rets):
    gains = sum(r for r in rets if r > 0)
    losses = -sum(r for r in rets if r < 0)
    return (gains / losses) if losses > 0 else None

def load(venue, asset):
    d=json.load(open(f"result_{venue}_{asset}.json"))
    for t in d["trades"]:
        t["venue"]=venue
        t["asset"]=asset
        t["date"]=t["ts"][:10]
        t["hour"]=int(t["ts"][11:13])
    return d

results={ (v,a): load(v,a) for v in ("binance","bybit") for a in ("BTC","ETH") }

print("="*80)
print("A. PER-SERIES WALK-FORWARD (replication)")
for (v,a),d in results.items():
    wins=[w for w in d["windows"] if w["pf_net"] is not None]
    npass=sum(1 for w in wins if w["pf_net"]>1.3)
    pooled=[t["return_pct"] for t in d["trades"] if not t["censored"]]
    wr=sum(1 for r in pooled if r>0)/len(pooled)
    print(f"{v:8s} {a}: signals={d['n_signals']:4d} windows_pass={npass}/{len(wins)} pooledPF={pf(pooled):.3f} winrate={wr:.1%} n={len(pooled)}")
    print("   perwindow PF:", [f"{w['pf_net']:.2f}" if w["pf_net"] else "-" for w in d["windows"]])

print()
print("B. CROSS-VENUE SIGNAL OVERLAP (same asset, binance vs bybit)")
for a in ("BTC","ETH"):
    s1={(t["ts"],t["direction"]) for t in results[("binance",a)]["trades"]}
    s2={(t["ts"],t["direction"]) for t in results[("bybit",a)]["trades"]}
    inter=len(s1&s2)
    union=len(s1|s2)
    print(f"{a}: binance={len(s1)} bybit={len(s2)} overlap={inter} jaccard={inter/union:.2%}")

all_tr=[t for d in results.values() for t in d["trades"] if not t["censored"]]
print()
print(f"C. POOLED SLICES (n={len(all_tr)} non-censored, 4 series)")
def slice_report(name, keyfn):
    groups={}
    for t in all_tr:
        groups.setdefault(keyfn(t),[]).append(t["return_pct"])
    print(f"-- {name}")
    for k in sorted(groups, key=str):
        v=groups[k]
        wr=sum(1 for r in v if r>0)/len(v)
        print(f"   {str(k):24s} n={len(v):4d} PF={pf(v) if pf(v) is not None else float('nan'):.3f} WR={wr:.1%} mean={statistics.mean(v)*100:+.3f}%")
slice_report("direction", lambda t: t["direction"])
slice_report("confidence bucket", lambda t: "conf<0.5" if t["confidence"]<0.5 else ("0.5-0.65" if t["confidence"]<0.65 else ("0.65-0.75" if t["confidence"]<0.75 else ">=0.75")))
slice_report("structure event", lambda t: t["structure"] or "none")
slice_report("outcome", lambda t: t["outcome"])
slice_report("session (UTC h)", lambda t: "asia(0-8)" if t["hour"]<8 else ("london(8-13)" if t["hour"]<13 else ("overlap(13-16)" if t["hour"]<16 else ("ny(16-21)" if t["hour"]<21 else "off(21-24)"))))
slice_report("R:R bucket", lambda t: "rr<2" if (t["rr"] or 0)<2 else ("2-3" if t["rr"]<3 else ("3-5" if t["rr"]<5 else ">=5")))
slice_report("bars_held", lambda t: "<=5" if t["bars_held"]<=5 else ("6-12" if t["bars_held"]<=12 else "13-20"))

print()
print("D. CONFIDENCE INFORMATIVENESS: corr(confidence, return)")
xs=[t["confidence"] for t in all_tr]
ys=[t["return_pct"] for t in all_tr]
mx_, my=statistics.mean(xs), statistics.mean(ys)
cov=sum((x-mx_)*(y-my) for x,y in zip(xs,ys))/len(xs)
corr=cov/(statistics.pstdev(xs)*statistics.pstdev(ys))
print(f"pearson r = {corr:+.4f}")

print()
print("E. COINGLASS DAILY JOIN (fuel/funding/L-S conditioning, trade-day of entry)")
cg=json.load(open("cg_daily_features.json"))
def cgf(t):
    return cg[t["asset"]].get(t["date"])
for name, cond in [
    ("fuel=confirmed", lambda f,t: f["fuel"]=="confirmed"),
    ("fuel=unfueled", lambda f,t: f["fuel"]=="unfueled"),
    ("SHORT & funding>=p75(0.006)", lambda f,t: t["direction"]=="SHORT" and f.get("funding",0)>=0.006),
    ("LONG & funding>=p75(0.006)", lambda f,t: t["direction"]=="LONG" and f.get("funding",0)>=0.006),
    ("SHORT & crowd long (gls hi)", lambda f,t: t["direction"]=="SHORT" and f.get("gls",0)>=2.0),
    ("LONG & crowd long (gls hi)", lambda f,t: t["direction"]=="LONG" and f.get("gls",0)>=2.0),
    ("dir matches day drift", lambda f,t: (f["price_ret"]>0)==(t["direction"]=="LONG")),
    ("dir against day drift", lambda f,t: (f["price_ret"]>0)!=(t["direction"]=="LONG")),
]:
    v=[t["return_pct"] for t in all_tr if cgf(t) and cond(cgf(t),t)]
    if len(v)<5:
        print(f"   {name:32s} n={len(v)} (too small)")
        continue
    wr=sum(1 for r in v if r>0)/len(v)
    print(f"   {name:32s} n={len(v):4d} PF={pf(v):.3f} WR={wr:.1%} mean={statistics.mean(v)*100:+.3f}%")
