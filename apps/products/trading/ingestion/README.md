# Trading: Ingestion

Worker Python: connector CEX (CCXT+native WS) & DEX (Hyperliquid, dYdX v4, GMX, Vertex, Drift, Meteora DLMM, new-pair listener) -> normalizer -> fallback chain -> writer ke Neon. Lihat PRD Section B.11 utk rekomendasi sumber data.

## Status implementasi

**`connectors/cex/ccxt_generic.py` + `ingest.py`** — connector pertama yg beneran ada: **Binance USDS-M perpetual futures, Bybit, dan Hyperliquid** (DEX-perp pertama, Fase 1 B.9), `funding_rate` + `ohlcv` doang (scope sengaja sempit dulu, bukan strategy engine, bukan fallback chain native WS/Coinalyze; itu semua nunggu ronde berikutnya). `ccxt_generic.py` sengaja generik (bukan `binance_ccxt.py` per-exchange spt versi awal) — ccxt expose unified API yg sama persis di semua exchange, jadi satu wrapper cukup; nambah venue baru = tambah 1 entry di `VENUES` dict dalam `ingest.py`, asal exchange-nya didukung ccxt dgn `fetchFundingRate` (atau `fetchFundingRates`, lihat catatan Hyperliquid di bawah) + `fetchOHLCV`.

**Hyperliquid butuh 2 penyesuaian nyata di `ccxt_generic.py`, bukan cuma nambah entry**, ketauan lewat `exchange.has` ccxt langsung (bukan asumsi):
1. `fetchFundingRate` (single-symbol) itu `False` utk Hyperliquid — cuma ada `fetchFundingRates` (plural, all-market). `fetch_funding_rate()` di `ccxt_generic.py` sekarang cek `exchange.has.get("fetchFundingRate")` dulu, fallback ke `fetch_funding_rates([symbol])[symbol]` kalau falsy — struktur hasilnya tetap sama (unified `FundingRate` shape), jadi sisa kode gak perlu tau bedanya.
2. Auth Hyperliquid pakai `walletAddress`/`privateKey`, bukan `apiKey`/`secret` spt CEX — tapi gak relevan di sini krn `funding_rate`/`ohlcv` public endpoint di semua venue (gak butuh key sama sekali). `VENUES["hyperliquid"]` set `api_key_env`/`api_secret_env` ke `None`/`None` (bukan nunjuk ke env var yg bakal di-ignore diam-diam oleh ccxt), dan `make_exchange()` skip config kredensial sepenuhnya kalau salah satu `None`.

**Bug nyata ketemu & di-fix pas nambah Hyperliquid**: `FUNDING_INTERVAL_HOURS` sebelumnya di-hardcode `8` utk SEMUA venue — ternyata ccxt beneran expose field `interval` per-response (`"8h"`, `"1h"`, dst, sudah ada di Binance & Bybit juga, cuma gak pernah dipakai). Hyperliquid funding settle **per jam** (`1h`), jauh beda dari asumsi 8h — kalau tetap hardcode, data funding Hyperliquid bakal salah total. Sekarang `fetch_funding_rate()` parse `interval` dari response ccxt, fallback ke `DEFAULT_FUNDING_INTERVAL_HOURS = 8` cuma kalau venue itu bener2 gak expose field ini.

**Symbol convention beda**: Hyperliquid perp di-quote pakai USDC (`"BTC/USDC:USDC"`), bukan USDT spt Binance/Bybit (`"BTC/USDT:USDT"`) — krn `--symbols` di CLI dipakai bareng utk semua `--venues` dalam satu invocation, Hyperliquid **wajib dijalankan di invocation terpisah** dgn symbol list-nya sendiri (lihat contoh command di bawah), gak bisa dicampur `--venues binance bybit hyperliquid` pakai satu `--symbols` yg sama.

Auto-provision `venue`/`instrument` row di first-run (idempotent per venue, sama pola dgn `platform_user` auto-provision di `api-gateway/deps.py`) — `venue.venue_type` sekarang per-venue dari `VENUES` dict (`"cex"` utk Binance/Bybit, `"dex"` utk Hyperliquid, sesuai `ck_venue_type` constraint di DB), upsert `funding_rate`/`ohlcv` via `db.merge()` (re-run aman, gak duplikat instrument/venue — funding_rate/ohlcv sendiri emang nambah row baru tiap fetch selama `ts` beda, itu time-series by design bukan bug), dan tulis `data_source_health` per venue+data_type (sukses/gagal + `consecutive_failures`) tiap kali fetch.

Standalone script utk sekarang, **belum di-wire ke Inngest** (self-hosted job scheduler yg direncanakan di B.1/B.9 — belum ada infra-nya sama sekali di repo ini). Jalankan manual/cron sementara.

**Catatan verifikasi**: logic upsert/idempotency/health-tracking (termasuk multi-venue: venue row terpisah per venue_type, instrument per-venue, health per venue+data_type), fallback `fetchFundingRates`, parsing `interval` dinamis, dan skip kredensial utk `api_key_env=None` — semua diverifikasi lewat mocked exchange object + Postgres 16 lokal beneran (migrasi `alembic upgrade head` dijalankan penuh, bukan cuma import check), termasuk regression check eksplisit bhw Binance/Bybit tetap dapat `funding_interval_hours=8`/`venue_type=cex` spt sebelumnya (dari sandbox Claude Code, yg diblokir network policy-nya ke `fapi.binance.com`/Bybit/`api.hyperliquid.xyz` — dikonfirmasi via `ex.load_markets()` beneran timeout `NetworkError`, bukan diasumsikan). **Panggilan jaringan asli ke Binance + Neon production sudah dites user sendiri & BERHASIL** (`BTC/USDT:USDT` & `ETH/USDT:USDT` di Binance, funding_rate + ohlcv, lewat proxy Webshare.io) — lihat gotcha proxy di bawah kalau nemu `InvalidProxySettings`/`407 Proxy Authentication Required` pas setup pertama kali. **Bybit & Hyperliquid belum dites via jaringan asli** (cuma mocked), krn sandbox Claude Code diblokir ke keduanya juga — coba jalankan sungguhan sblm dianggap kelar.

## Local dev

```bash
cd apps/products/trading/ingestion
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL="postgresql://<user>:<pass>@<host>/<db>"   # +psycopg dipaksa otomatis, lihat kinetiq_db.engine
# Opsional -- lihat .env.example utk penjelasan lengkap:
# export BINANCE_API_KEY="..."       # HARUS read-only key, funding_rate/ohlcv itu public endpoint
# export BINANCE_API_SECRET="..."
# export BYBIT_API_KEY="..."         # sama, harus read-only
# export BYBIT_API_SECRET="..."
# export PROXY_URL="http://user:pass@proxy-host:port"   # mis. Webshare.io, dipakai semua venue
#                                     # (ganti nama dari BINANCE_PROXY_URL versi sebelumnya)
PYTHONPATH=../../../../packages/db/src python ingest.py --venues binance bybit --symbols "BTC/USDT:USDT" "ETH/USDT:USDT" --timeframe 1h --limit 100

# Hyperliquid: invocation terpisah krn quote currency beda (USDC, bukan USDT) --
# gak bisa dicampur ke command di atas, --symbols dipakai bareng utk semua --venues.
# Public endpoint, gak butuh API key sama sekali (walletAddress/privateKey cuma
# perlu utk order/transfer, gak dipakai script ini).
PYTHONPATH=../../../../packages/db/src python ingest.py --venues hyperliquid --symbols "BTC/USDC:USDC" "ETH/USDC:USDC" --timeframe 1h --limit 100
```

`BINANCE_API_KEY`/`BYBIT_API_KEY`/`PROXY_URL` menyelesaikan dua masalah yg beda: API key (harus read-only per venue, jangan pernah kasih izin trading/withdrawal — script ini gak pernah submit order) cuma soal rate limit; proxy soal IP yg mungkin di-block/dibatasi (mis. IP cloud/datacenter kayak Railway) — request yg udah authenticated dari IP yg di-block tetap ke-block, jadi API key doang gak nyelesain masalah blocking. `PROXY_URL` sengaja satu env var dipakai semua venue (bukan per-exchange spt API key), krn IP blocking itu masalah jaringan, bukan spesifik ke satu exchange.

**Gotcha proxy yg kejadian pas setup real pertama kali** (keduanya sudah fixed di kode/didokumentasikan di sini biar gak keulang):
- `ccxt.base.errors.InvalidProxySettings: ...multiple conflicting proxy settings...` — sudah di-fix di `ccxt_generic.py` (cuma set `httpsProxy`, jangan `httpProxy` bareng, krn semua venue di sini selalu `https://`).
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
