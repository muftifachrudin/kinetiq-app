"""One-off pull of the 4 full-year 1h candle series from the production
ohlcv table via the Neon HTTP-SQL endpoint (raw Postgres connections hang
from the Claude Code sandbox; this endpoint is the one reachable path).
Writes candles_{venue}_{ASSET}.csv into the current working directory.
Requires DATABASE_URL in the environment.
"""
import os
import json
import urllib.request
import re
import csv
db=os.environ["DATABASE_URL"].strip()
m=re.match(r"postgresql://[^@]+@([^/?]+)/([^?]+)", db)
url=f"https://{m.group(1)}/sql"
def q(sql):
    req=urllib.request.Request(url, data=json.dumps({"query":sql,"params":[]}).encode(),
        headers={"Content-Type":"application/json","Neon-Connection-String":db})
    return json.loads(urllib.request.urlopen(req, timeout=120).read())["rows"]

series=[("binance","BTC/USDT:USDT"),("binance","ETH/USDT:USDT"),("bybit","BTC/USDT:USDT"),("bybit","ETH/USDT:USDT")]
for venue,sym in series:
    rows_all=[]
    offset=0
    while True:
        rows=q(f"""SELECT o.ts,o.open,o.high,o.low,o.close,o.volume
            FROM ohlcv o JOIN instrument i ON i.id=o.instrument_id JOIN venue v ON v.id=i.venue_id
            WHERE v.name='{venue}' AND i.symbol='{sym}' AND o.timeframe='1h'
            ORDER BY o.ts LIMIT 3000 OFFSET {offset}""")
        rows_all+=rows
        if len(rows)<3000:
            break
        offset+=3000
    fn=f"candles_{venue}_{sym.split('/')[0]}.csv"
    with open(fn,"w",newline="") as f:
        w=csv.writer(f)
        w.writerow(["ts","open","high","low","close","volume"])
        for r in rows_all:
            w.writerow([r["ts"],r["open"],r["high"],r["low"],r["close"],r["volume"]])
    print(fn, len(rows_all))
