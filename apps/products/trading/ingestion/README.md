# Trading: Ingestion

Worker Python: connector CEX (CCXT+native WS) & DEX (Hyperliquid, dYdX v4, GMX, Vertex, Drift, Meteora DLMM, new-pair listener) -> normalizer -> fallback chain -> writer ke Neon. Lihat PRD Section B.11 utk rekomendasi sumber data.

## Status implementasi

**`connectors/cex/binance_ccxt.py` + `ingest.py`** — connector pertama yg beneran ada: Binance USDS-M perpetual futures via CCXT, `funding_rate` + `ohlcv` doang (scope sengaja sempit dulu). Auto-provision `venue`/`instrument` row di first-run (idempotent, sama pola dgn `platform_user` auto-provision di `api-gateway/deps.py`), upsert `funding_rate`/`ohlcv` via `db.merge()` (re-run aman, gak duplikat), dan tulis `data_source_health` (sukses/gagal + `consecutive_failures`) tiap kali fetch — bukan strategy engine, bukan fallback chain (native WS/Coinalyze), bukan venue lain; itu semua nunggu ronde berikutnya.

Standalone script utk sekarang, **belum di-wire ke Inngest** (self-hosted job scheduler yg direncanakan di B.1/B.9 — belum ada infra-nya sama sekali di repo ini). Jalankan manual/cron sementara.

**Catatan verifikasi**: logic upsert/idempotency/health-tracking diverifikasi lewat mocked exchange object + Postgres lokal (dari sandbox Claude Code, yg diblokir network policy-nya ke `fapi.binance.com`). **Panggilan jaringan asli ke Binance + Neon production sudah dites user sendiri & BERHASIL** (`BTC/USDT:USDT` & `ETH/USDT:USDT`, funding_rate + ohlcv, lewat proxy Webshare.io) — lihat gotcha proxy di bawah kalau nemu `InvalidProxySettings`/`407 Proxy Authentication Required` pas setup pertama kali.

## Local dev

```bash
cd apps/products/trading/ingestion
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL="postgresql://<user>:<pass>@<host>/<db>"   # +psycopg dipaksa otomatis, lihat kinetiq_db.engine
# Opsional -- lihat .env.example utk penjelasan lengkap:
# export BINANCE_API_KEY="..."       # HARUS read-only key, funding_rate/ohlcv itu public endpoint
# export BINANCE_API_SECRET="..."
# export BINANCE_PROXY_URL="http://user:pass@proxy-host:port"   # mis. Webshare.io, kalau IP ke-block Binance
PYTHONPATH=../../../../packages/db/src python ingest.py --symbols "BTC/USDT:USDT" "ETH/USDT:USDT" --timeframe 1h --limit 100
```

`BINANCE_API_KEY`/`BINANCE_PROXY_URL` menyelesaikan dua masalah yg beda: API key (harus read-only, jangan pernah kasih izin trading/withdrawal — script ini gak pernah submit order) cuma soal rate limit; proxy soal IP yg mungkin di-block/dibatasi Binance (mis. IP cloud/datacenter kayak Railway) — request yg udah authenticated dari IP yg di-block tetap ke-block, jadi API key doang gak nyelesain masalah blocking.

**Gotcha proxy yg kejadian pas setup real pertama kali** (keduanya sudah fixed di kode/didokumentasikan di sini biar gak keulang):
- `ccxt.base.errors.InvalidProxySettings: ...multiple conflicting proxy settings...` — sudah di-fix di `binance_ccxt.py` (cuma set `httpsProxy`, jangan `httpProxy` bareng, krn Binance API selalu `https://`).
- `407 Proxy Authentication Required` — ini BUKAN soal concurrent user/plan Webshare, murni salah copy username/password proxy (`user:pass@host:port`). Test isolasi paling gampang, gak perlu Python sama sekali:
  ```bash
  curl.exe --proxy "http://user:pass@host:port/" https://ipv4.webshare.io/
  ```
  Kalau ini balikin sebuah IP address, kredensial proxy-nya valid dan masalahnya ada di tempat lain (mis. `DATABASE_URL` yg salah, bukan proxy).

Cek hasilnya:
```sql
SELECT * FROM venue;
SELECT * FROM instrument;
SELECT * FROM funding_rate ORDER BY ts DESC LIMIT 5;
SELECT * FROM ohlcv ORDER BY ts DESC LIMIT 5;
SELECT * FROM data_source_health;
```

See `docs/prd.md` (PRD + Rencana Teknis: Kinetiq) for full context and design decisions.
