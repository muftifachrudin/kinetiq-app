# Memory Investigasi — Crypto Trading Theory Validation (Claude Fable 5, 3 Juli 2026)

Catatan memory permanen dari sesi investigasi Fable 5 atas kegagalan run
validasi pertama (`run-validation.yml` #2: PF net > 1.3 hanya 2/10 window).
Dokumen ini adalah **jejak bukti + cara reproduksi + gotcha operasional** —
kesimpulan analitis lengkapnya ada di `docs/validation-deep-dive-2026-07.md`
(jangan diduplikasi ke sini; kalau dua dokumen ini nanti bertentangan, angka
di deep-dive yang menang karena dia yang di-generate langsung dari data).
Roadmap eksekusi untuk sesi implementasi berikutnya (Sonnet 5):
`docs/sonnet5-implementation-roadmap.md`.

## 1. Apa yang diinvestigasi & dari data mana

| Sumber | Isi | Lokasi/cara akses |
|---|---|---|
| `ohlcv` production (Neon) | 4 seri × 8.763 candle 1h, 2025-07-03 → 2026-07-03: BTC & ETH × Binance & Bybit (`BTC/USDT:USDT` dst. = **USDT-M perpetual**, bukan spot) | HTTP-SQL endpoint (lihat bag. 4) |
| Run validasi CI #2 | Report JSON/MD asli run yang "meleset" (10 window, 2 lolos) | Artifact `validation-report-28649458531` di GitHub Actions; angka window juga tersalin di deep-dive bag. 2 |
| Replikasi 4 seri | 2.683 sinyal → 2.679 trade non-censored berlabel triple-barrier | Script `validation/deep_dive_2026_07/` (commit ini) + summary `docs/validation-results/replication-2026-07-03.json` |
| CoinGlass Hobbyist | 399-400 hari harian × 2 koin: price, OI agg, funding (Binance & Bybit), taker buy/sell, global L/S account ratio, top-trader L/S position ratio, liquidation agg | Script `coinglass_pull.py` + `cg_analysis.py` (folder yang sama) |
| `trade_annotation` production | **KOSONG** — temuan integritas data, lihat bag. 5 | — |

## 2. Ringkasan temuan (angka kunci saja — detail & interpretasi di deep-dive)

1. Mekanisme robust lintas bursa: Jaccard sinyal Binance↔Bybit 72.9% (BTC) /
   73.8% (ETH); PF pooled per venue nyaris identik (1.086 vs 1.120 BTC;
   0.874 vs 0.905 ETH). Kegagalan ≠ noise data.
2. Tidak generalize ke ETH: window lolos 2-3/10 (BTC) vs 0-1/10 (ETH).
3. Confidence score ANTI-prediktif: pearson r = -0.054; bucket conf<0.5
   PF 2.06 vs conf≥0.75 PF 0.94. Bobot hand-tuned menyesatkan.
4. LONG PF 0.84 vs SHORT PF 1.12 (tahun bear, tanpa bias HTF — yang diuji
   memang baru single-timeframe, bukan teori penuh founder).
5. SL wick-hunt: 52% trade mati SL; ≤5 bar PF 0.36 vs 13-20 bar PF 2.16;
   TIMEOUT PF 5.56 (+0.78% mean).
6. Band R:R 1.5-2 = band terburuk (PF 0.76); rr∈[2,5) sehat (PF 1.16).
7. Fee material & belum dimodel (taker-taker 0.10%/rt membalik mean trade
   jadi negatif); funding sepele untuk holding ~11 jam (~0.006%).
8. OI-fuel: kuat DESKRIPTIF (fuel-confirmed |ret| 1.80× BTC / 2.71× ETH),
   lemah PREDIKTIF (H+1: 1.61% vs 1.46%), dan TIDAK membedakan hasil trade
   (PF 0.97 vs 0.96). Kesimpulan: indikator koinsiden/rezim, bukan arah.
9. Positioning contrarian kecil-konsisten 2 koin: funding≥p90 BTC → next-day
   -0.45%; SHORT saat crowd-long PF 1.17 vs LONG-nya 0.79; top-trader <
   kerumunan → next-day negatif; liq-cascade 20/20 hari top-long-liq
   closing turun.
10. Kombinasi kausal `searah-SMA200(1h) + rr∈[2,5)`: PF pooled 0.97 → 1.298
    gross / 1.131 net taker fee, konsisten 4 seri (BTC 1.50, ETH 1.18) —
    **status: hipotesis in-sample**, wajib uji walk-forward OOS.
11. CoinGlass Hobbyist interval `1h` = HTTP 403 (dikonfirmasi langsung,
    bukan asumsi lagi). Daily-only berdiri.

## 3. Cara mereproduksi (untuk sesi berikutnya)

Script analisis di `apps/products/trading/agent-orchestrator/validation/deep_dive_2026_07/`
(one-off analysis script, BUKAN production code — lihat README di folder itu):

1. `pull_data.py` — tarik 4 seri candle dari `ohlcv` production via Neon
   HTTP-SQL (paginated 3.000 baris/request) → `candles_{venue}_{asset}.csv`.
2. `replicate.py <venue> <asset>` — jalankan pipeline persis run CI
   (`generate_signals` → `simulate_trades` → `compute_metrics` + window
   walk-forward yang sama) → `result_{venue}_{asset}.json` berisi metrik per
   window + dump per-trade (ts, direction, confidence, rr, outcome,
   return_pct, bars_held). ±3-5 menit/seri (walk O(n²)).
   Perbedaan metodologis yang DISENGAJA vs `run_validation.py`: sinyal
   di-generate sekali atas seri penuh (as_of walk sudah kausal, hasil per
   window identik; trade di tepi window resolve dgn data lanjutan alih-alih
   censored). Direplikasi cocok dgn run CI (BTC-Binance 2/10, pola PF sama).
3. `coinglass_pull.py` — tarik 400 hari harian CoinGlass → `coinglass_raw.json`.
   `cg_analysis.py` — feature table harian → `cg_daily_features.json` +
   analisis fuel/funding/L-S standalone.
4. `slices.py` — replikasi + irisan (direction/confidence/session/R:R/
   bars_held/structure) + join CoinGlass per tanggal entry.
5. `implementable.py` — uji filter kausal (SMA50/200, prev-day drift, R:R
   band, kombinasi) + breakdown per aset/venue/bulan → `pooled_trades.json`.

Urutan: 1 → 2 (4×) → 3 → 4 → 5. Kebutuhan env: `DATABASE_URL`,
`COINGLASS_API_KEY`; venv dengan `packages/backtest-core` ter-install
(`pip install -e packages/backtest-core pyyaml`).

## 4. Gotcha operasional yang ditemukan sesi ini (baru, belum ada di runbook)

- **Neon HTTP-SQL** (`https://<endpoint-host>/sql`, header
  `Neon-Connection-String`): payload single = `{"query": "...", "params": []}`;
  bentuk multi-statement yang JALAN adalah `{"queries": [{"query": ...,
  "params": []}, ...]}` (array of objects — array of plain strings DITOLAK
  `data did not match any variant of untagged enum Payload`). Session state
  (`set_config`) preserve antar statement dalam satu request.
- **`neondb_owner` di production punya `rolbypassrls = true`.** Artinya
  SEMUA kebijakan RLS (termasuk `FORCE ROW LEVEL SECURITY`) TIDAK berlaku
  untuk koneksi app/worker yang memakai role ini di production. Verifikasi
  RLS yang selama ini dilakukan terhadap Postgres lokal dengan role
  non-superuser tetap benar secara logika kebijakan, tapi **efek proteksi
  real di production = nol selama servis konek sebagai owner** — isolasi
  tenant produksi saat ini bergantung pada disiplin `set_config` +
  clause WHERE aplikasi, bukan pada RLS. Catat untuk keputusan arsitektur:
  role aplikasi terpisah (non-owner, non-bypassrls) adalah perbaikan yang
  benar; JANGAN diklaim "RLS melindungi production" sampai itu dilakukan.
- **CoinGlass v4**: endpoint per-pair (`price/history`,
  `funding-rate/history`, `taker-buy-sell-volume/history`,
  `global-long-short-account-ratio/history`,
  `top-long-short-position-ratio/history`) WAJIB param `exchange=` (400
  tanpa itu); endpoint agregat (`open-interest/aggregated-history`,
  `liquidation/aggregated-history`) pakai `symbol=BTC` (coin, bukan pair)
  dan liquidation wajib `exchange_list=`. Rate limit nyata: sempat
  connection-reset saat request beruntun — kasih jeda ~2.5s antar call.
  Interval `1h` → HTTP 403 di Hobbyist (daily-only TERKONFIRMASI).
- **GitHub Actions artifact** run #2 (`validation-report-28649458531`)
  expire 2026-10-01 — angka pentingnya sudah disalin ke deep-dive & summary
  JSON sebelum expire.

## 5. Temuan integritas data yang MASIH OPEN (butuh action founder)

`trade_annotation` production **kosong total**: `pg_relation_size = 0 byte`
(heap tidak pernah ditulis satu baris pun), `pg_stat_user_tables.n_tup_ins=0`,
`instrument` hanya 4 baris (import 276 posisi seharusnya auto-provision 53
simbol) — dicek dengan role BYPASSRLS jadi bukan efek filter RLS. Padahal
brief bag. 21 mencatat import "sukses & terverifikasi count=276" (3 Juli).
Project Neon `late-mouse-59772749` hanya punya 1 branch (`production`,
dibuat 1 Juli) — jadi bukan salah branch di project ini. Hipotesis paling
mungkin: transaksi Neon SQL Editor ter-rollback setelah verifikasi (count
dibaca DI DALAM transaksi yang sama sebelum COMMIT sukses), atau verifikasi
terjadi di project/console berbeda. **Action: re-run file `--emit-sql` di
Neon SQL Editor, lalu verifikasi `SELECT count(*)` dari SESSION BARU yang
terpisah** (bukan di transaksi yang sama). Semua jalur agreement-rate,
shadow_pair, dan analisis behavior trade real founder tetap buntu sampai
ini beres.

## 6. Status klaim-klaim lama setelah investigasi ini

| Klaim sebelumnya | Status sekarang |
|---|---|
| "OI sebagai bahan bakar" (bag. 9 brief, 89 hari, 1 koin) | Direplikasi 399 hari × 2 koin secara deskriptif; TAPI terbukti lemah sebagai prediktor & tidak membedakan hasil trade — downgrade dari "kandidat bobot arah" jadi "konteks rezim volatilitas" |
| "CoinGlass Hobbyist daily-only" (asumsi B.11) | TERKONFIRMASI langsung (403 pada `1h`) |
| "Bobot ConfluenceWeights starting point yang wajar" | DIBANTAH — anti-prediktif di 2.679 sampel (r=-0.05) |
| "Belum ada data untuk Part #2 fitting" | TIDAK BERLAKU LAGI — 2.679 label triple-barrier tersedia dari replikasi, bertambah tiap run |
| "Import 276 trade real sukses ke production" (bag. 21) | DIBANTAH oleh state DB saat ini — lihat bag. 5 |
| "RLS FORCE melindungi data tenant di production" | PERLU KUALIFIKASI — bypassrls pada role owner yang dipakai servis (bag. 4) |
| Kriteria promosi bag. 7 (PF>1.3 di ≥2/3 window) | Diuji beneran pertama kali: GAGAL pada sistem sekarang (2-3/10 BTC, 0-1/10 ETH); tetap dipakai sebagai target, dengan tambahan "net of fees" |
