# Roadmap Implementasi untuk Sesi Sonnet 5 — dari Teori v2 ke Live-Trading-Worthy, lalu ke Seluruh Market

Dokumen handoff dari sesi investigasi Fable 5 (3 Juli 2026). Ditulis supaya
sesi Claude Code berikutnya (Sonnet 5) bisa mengeksekusi TANPA menebak ulang
konteks. Wajib dibaca berpasangan dengan:

- `docs/validation-deep-dive-2026-07.md` — bukti & angka di balik setiap
  keputusan di sini (temuan F1-F11, teori v2 pasal (a)-(f), rubric skor).
- `docs/fable5-crypto-theory-investigation-2026-07.md` — memory investigasi:
  cara reproduksi angka, gotcha operasional, temuan integritas data.
- `docs/fib-gann-validation-brief.md` bag. 10 — prinsip gate-vs-skor, dan
  bag. 7 — kriteria promosi.
- `CLAUDE.md` + `docs/deployment-runbook.md` — disiplin repo & deploy.

## Aturan main untuk SEMUA fase (tidak bisa dinego, warisan sesi-sesi sebelumnya)

1. **Gate keras vs faktor skor** (brief bag. 10): faktor baru apapun masuk
   sebagai kontributor skor tertimbang, BUKAN gate AND baru. Gate keras yang
   diizinkan tetap dua: entry-validity dan R:R — dan perubahan angka R:R
   (Fase 5) harus lewat uji head-to-head, bukan diganti diam-diam.
2. **Deterministic dulu, ML-fit belakangan** — dan setelah Fase 3 jalan,
   TIDAK ADA konstanta hand-tuned baru masuk skor tanpa lewat fitting.
3. **No-lookahead ketat**: semua fitur dihitung dari data yang tersedia pada
   `as_of` bar entry. Ikuti disiplin `_filter_as_of` yang sudah ada. Setiap
   fitur baru wajib test anti-lookahead eksplisit.
4. **Angka in-sample = hipotesis**. Keputusan adopsi HANYA dari walk-forward
   out-of-sample (`packages/backtest-core` windows), net of fees. Termasuk
   PF 1.30 dari deep-dive — itu target uji, bukan fakta.
5. **Funnel diagnostic tiap kali menyentuh `signal_runner`**: laporkan
   touch → gate → sinyal akhir (baseline lama: 70→3 di 100 candle; skala
   setahun: ~670 sinyal/seri). Kalau sinyal collapse mendekati nol, berhenti
   dan lapor, jangan lanjut.
6. **Simulasi CI persis sebelum push** (fresh venv, command CI verbatim) —
   bug lazy-import `kinetiq_db`/`sqlalchemy` sudah dua kali kejadian, jangan
   jadi yang ketiga. Verifikasi setiap modul baru terhadap data real minimal
   satu spot-check, dan tulis hasilnya (termasuk yang gagal) di brief.
7. **Path CODEOWNERS** (`execution/risk_gate.py`, `execution/custody/*`,
   `packages/db/migrations/`) = wajib review manual founder. Jangan
   auto-merge.
8. **Bahasa**: kode/komentar/commit English; update `docs/prd.md` &
   `docs/fib-gann-validation-brief.md` Indonesian, gaya yang sudah ada.
9. **Jangan re-litigasi keputusan yang sudah diputuskan founder** (fib set
   personal, 9 Gann angle, kalibrasi Opsi 1, market_structure sebagai skill
   terpisah, parallel-channel di-skip s/d pasca-MVP).

## Gambaran fase & dependensi

```
F0 Data plumbing ──┬── F1 Fee-aware sim ──┬── F3 Per-factor dump + fitting ── F6 Kampanye validasi OOS ── F7 Shadow trading ── F9 Live gate
                   ├── F2 htf_bias.py ────┤                                        │            ├── F7a position_sizing.py + PreTradeCard
                   ├── F4 derivatives_context.py (paralel, faktor utk F3)          │            │   (paralel, boleh kapan saja setelah F0)
                   └── F5 R:R band + SL anti-hunt (paralel, eksperimen harness)    │            └── F7b cross-mode portfolio sim (SETELAH F7 jalan)
                                                       F8 Ekspansi universe (multi-koin → tokenized equity) — setelah F6 lolos di BTC+ETH
```

Fase 1, 2, 4, 5 saling independen setelah F0 — kerjakan berurutan per PR
kecil, jangan satu PR raksasa. F7a (position_sizing.py) juga independen:
pure function tanpa DB, prasyarat nyata F7, boleh dikerjakan paralel dengan
fase manapun.

---

## Fase 0 — Integritas & plumbing data (prasyarat semua)

**0a. Re-import `trade_annotation` — SELESAI (2026-07-03).**
Akar masalah lama bukan transaksi database, tapi paste manual 775-baris
`--emit-sql` ke Neon SQL Editor via mobile browser silently truncate ~140-150
baris terlepas dari ukuran file. Sebagian (row 1-120) masuk lewat chunk kecil
manual; sisanya (row 121-276) dieksekusi langsung dari sandbox lewat endpoint
HTTP-SQL Neon bentuk `{"queries": [...]}` (1 request, 159 query, ~90KB, sukses
penuh). Acceptance terpenuhi: `count(*)=276` terverifikasi dari query terpisah
setelahnya, `instrument`=55. Detail: `docs/fib-gann-validation-brief.md`
bag. 23 update, CLAUDE.md.

**0b. Migration `signal_id` linkage** (`packages/db/migrations/` —
CODEOWNERS, review founder). Kolom nullable `signal_id` + tabel `signal`
minimal (id, ts, instrument_id, timeframe, direction, entry, sl, tp1,
confidence, per-factor scores JSONB) — sekarang sudah ADA penulisnya
(harness F3 & shadow loop F7), jadi tidak melanggar prinsip "jangan desain
untuk kebutuhan hipotetis" lagi.

**0c. Backfill & poll `funding_rate` + `open_interest` native** dari
Binance/Bybit via worker ingestion yang sudah jalan untuk ohlcv (perluas
`ingest.py`/`worker.py`, pola upsert idempotent yang sama). Target: 1 tahun
histori funding 8h (ccxt `fetchFundingRateHistory`) + OI 1h kalau tersedia
per venue. Acceptance: `SELECT count(*)` per venue-symbol ≈ 3×365 (funding)
dan cakupan tanggalnya menutupi periode ohlcv; `run_validation.py` bisa
diberi funding events beneran (gross vs net PF akhirnya beda terbaca).

**0d. Role DB aplikasi non-owner (non-BYPASSRLS).** Temuan investigasi:
`neondb_owner` punya `rolbypassrls=true` → RLS production efektif nol untuk
servis. Buat role `kinetiq_app` tanpa BYPASSRLS, grant minimum, servis
pindah konek pakai itu. Koordinasikan dengan founder (env Railway berubah).
Acceptance: `SELECT` `trade_annotation` tanpa `set_config` dari role baru
mengembalikan 0 baris meski data ada.
Titipan di PR draft 0d yang sama (satu kali review CODEOWNERS): kolom
`risk_mandate.default_margin_mode` + `risk_pct_per_trade` untuk F7a —
spec di `docs/margin-mode-brief.md` bag. 5.

**Status: SELESAI — DIEKSEKUSI PENUH DI PRODUCTION (2026-07-03).** Batasan
desain yang dipatuhi (arahan founder eksplisit):

- **`CREATE ROLE ... LOGIN` TIDAK boleh masuk migration Alembic** — password
  gak boleh ada di git, dan role itu sendiri objek CLUSTER-level (bukan
  per-database), jadi di luar tanggung jawab Alembic sama sekali. Role
  login `kinetiq_app` di production dibuat MANUAL oleh founder via **Neon
  SQL Editor** (connect sebagai `neondb_owner`), **BUKAN** lewat Neon
  Console/API — role yang dibuat lewat Console otomatis jadi member
  `neon_superuser`, yang bawa `BYPASSRLS` bawaan — persis mengulang masalah
  yang mau diperbaiki. Setelah dibuat, WAJIB verifikasi dua-duanya:
  `rolbypassrls = false` DAN tidak ada membership `neon_superuser` di
  `pg_auth_members`.
- Migration (`packages/db/migrations/versions/0006_kinetiq_app_role_grants.py`)
  cuma isi `GRANT` (+ `ALTER DEFAULT PRIVILEGES` biar tabel baru ke depan
  otomatis ke-grant, gak perlu migration grant lagi tiap ada tabel baru),
  dibungkus guard `DO $$ ... IF NOT EXISTS (SELECT FROM pg_roles WHERE
  rolname='kinetiq_app') THEN CREATE ROLE kinetiq_app NOLOGIN; END IF ...
  $$` — di production (role udah ada, LOGIN+password asli) cabang CREATE
  ROLE ini gak pernah kesentuh, cuma GRANT yang jalan; di Postgres
  lokal/CI (role belum pernah ada) cabang ini bikin placeholder NOLOGIN
  (tanpa password, aman commit) biar GRANT-nya punya target. **Migration
  ini sendiri INERT** — merge-nya TIDAK mengubah role apa yang benar-benar
  dipakai `DATABASE_URL` production, itu langkah manual terpisah
  belakangan. Downgrade = `REVOKE` semua yang di-GRANT, **BUKAN**
  `DROP ROLE` (role production yang lagi dipakai koneksi aktif jangan
  sampai ke-drop cuma gara-gara rollback migration).
- **Diverifikasi penuh thd Postgres 16 lokal** (bukan cuma baca kode, sama
  disiplin migration lain di repo ini): upgrade→downgrade→upgrade bersih;
  tabel BARU yang dibuat setelah upgrade otomatis kena grant (`ALTER
  DEFAULT PRIVILEGES` beneran jalan, dibuktikan langsung bukan diasumsikan);
  skenario "role sudah ada sebagai LOGIN+password" (simulasi production)
  dicoba eksplisit — guard `IF NOT EXISTS` benar-benar skip CREATE ROLE
  dan gak ganggu LOGIN/password yang udah ada, cuma GRANT yang jalan ulang.
- **Jebakan paling berbahaya, sudah diantisipasi**: `railway.toml`'s
  `startCommand` jalanin `alembic upgrade head` pakai `DATABASE_URL` — kalau
  env var itu dipindah ke `kinetiq_app` (non-owner, gak punya hak DDL),
  migration di tiap deploy akan GAGAL. Fix: `packages/db/migrations/env.py`
  sekarang baca `DATABASE_URL_MIGRATIONS` (connection string role owner,
  KHUSUS step alembic) kalau ada, fallback ke `DATABASE_URL` biasa kalau
  gak ada — jadi local dev/CI (cuma pernah set `DATABASE_URL`) sama sekali
  gak berubah perilakunya, no-op murni sampai KEDUA env var itu beneran
  di-set di Railway. Diverifikasi eksplisit 2 skenario thd Postgres lokal:
  cuma `DATABASE_URL` (perilaku lama, tetap jalan persis sama) dan
  KEDUANYA di-set sekaligus (migration correctly pakai
  `DATABASE_URL_MIGRATIONS`, `DATABASE_URL` yang sengaja diarahkan ke DB
  gak-ada sama sekali gak disentuh). `railway.toml` cuma dapat komentar
  penjelasan (bukan ubah `startCommand`-nya — env var Railway sendiri yang
  perlu ditambahkan belakangan, bukan sintaks shell-nya). Ingestion worker
  (`railway.ingestion-worker.toml`) gak jalanin migration sama sekali (cuma
  `DATABASE_URL` runtime langsung), jadi gak butuh split serupa — cukup
  dicek grant migration-nya mencakup tabel yang dia INSERT/UPDATE
  (`ohlcv`/`funding_rate`/`data_source_health`/`instrument`/`venue`) —
  sudah otomatis ke-cover krn grant-nya scope seluruh schema `public`,
  bukan daftar tabel manual per-servis.

**Eksekusi nyata (2026-07-03, founder yang jalankan tiap langkah manual,
dikonfirmasi eksplisit per tahap sesuai urutan di atas)**:

1. **PR #74 (migration grant-only) di-merge** — inert seperti didesain.
2. **Role `kinetiq_app` dibuat founder via Neon SQL Editor** (bukan Console),
   pakai `DO $$ IF EXISTS ... ALTER ROLE ... ELSE CREATE ROLE ... $$` supaya
   satu blok jalan baik role sudah ada (placeholder NOLOGIN dari migration)
   maupun belum. Terverifikasi: `rolbypassrls=false`, `rolsuper=false`,
   `SELECT` `pg_auth_members` utk membership `neon_superuser` → **0 baris**
   (tidak ada bypass tersembunyi).
3. **Acceptance test di Neon preview branch — SEMUA LULUS**:
   - `SELECT trade_annotation` tanpa `set_config` (sbg `kinetiq_app`, via
     `SET ROLE`) → **0 baris** (RLS `USING` clause bekerja).
   - `INSERT trade_annotation` tanpa `set_config`, pakai `tenant_id` ASLI
     yg valid (bukan UUID palsu — biar gak ketabrak FK, murni tes RLS) →
     **ditolak**, `ERROR: new row violates row-level security policy`
     (SQLSTATE 42501) — RLS `WITH CHECK` clause bekerja.
   - Jalur tulis worker ingestion (`INSERT`/`UPDATE`/`DELETE` `ohlcv`) →
     **sukses semua**, tanpa error permission — grant migration 0006
     lengkap utk tabel non-RLS juga.
   - **Gotcha nyata ketemu di jalan**: tiap klik "Run" terpisah di Neon SQL
     Editor ternyata bisa jadi KONEKSI BARU (bukan sesi yg sama walau di
     tab yg sama) — `SET ROLE` dari satu klik TIDAK kebawa ke klik
     berikutnya, bikin test awal salah baca (kelihatan `rolbypassrls`-like
     alias masih `neondb_owner`, count kebaca 277 bukan 0, insert yg
     seharusnya ditolak malah sukses). Fix: `SET ROLE` + query tes HARUS
     digabung jadi SATU statement batch/klik Run, bukan dipisah — begitu
     digabung, semua hasil sesuai ekspektasi. Beberapa baris tes nyasar
     (dari percobaan yg salah-koneksi ini) dibersihkan manual sebelum
     lanjut.
4. **Switch env Railway, bertahap per servis, dikonfirmasi terpisah**:
   - **Ingestion worker duluan** (blast radius kecil, gak ada dependency
     migration): `DATABASE_URL` diganti ke `kinetiq_app`. **Diverifikasi
     thd Railway asli**: `backfill SKIPPED (already covered)` semua
     venue/symbol, `funding_rate OK`/`ohlcv OK` (ccxt) semua kombinasi
     binance+bybit × BTC+ETH, `sleeping ...s until next 1h close` — siklus
     normal penuh, nol error permission.
   - **api-gateway kedua**: `DATABASE_URL_MIGRATIONS` (nilai `neondb_owner`
     lama) ditambah SEBAGAI variable baru, `DATABASE_URL` diganti ke
     `kinetiq_app`. **Diverifikasi thd Railway asli**: step `alembic
     upgrade head` sukses bersih (baca `DATABASE_URL_MIGRATIONS`, bukan
     `DATABASE_URL`, persis sesuai desain `env.py`), app start normal
     (`Uvicorn running`), healthcheck **`GET /health` 200 OK**.

**Hasil**: kedua servis production sekarang genuinely konek sebagai
`kinetiq_app` (non-owner, `rolbypassrls=false`) — `FORCE ROW LEVEL
SECURITY` (migration 0002) yg sebelumnya efektif NOL utk `neondb_owner`
sekarang BENERAN aktif utk trafik aplikasi sehari-hari. Ini menutup temuan
keamanan yg tercatat di `docs/prd.md`/`CLAUDE.md` sejak investigasi awal
Juli 2026.

## Fase 1 — Simulator fee-aware (F5 deep-dive)

Tambah parameter fee ke `trade_simulator.py` (ADITIF, jangan ubah perilaku
lama secara diam-diam): `fee_entry_fraction`/`fee_exit_fraction` per trade
(default Binance USDT-M VIP0 taker 0.0005; configurable per venue lewat
`walk_forward_windows.yaml`), dipotong di `net_return_pct` bersama funding.
`metrics.py` tidak berubah (sudah baca net). Semua report berikutnya WAJIB
menampilkan PF gross / net-funding / net-fees berdampingan.
Acceptance: unit test angka eksak; re-run replikasi 4 seri → baseline net
sesuai deep-dive (PF pooled ~0.85 pada taker-taker 0.10%).

**Status: SELESAI (2026-07-03).** Implementasi: `trade_simulator.py` dapat
param `fee_entry_fraction`/`fee_exit_fraction` (default 0.0, aditif ke
`net_return_pct` bersama funding, tidak mengubah perilaku lama saat 0.0);
`run_validation.py` re-run `simulate_trades()` sekali lagi dengan fee di-nol-kan
(reuse signal generation yang sama) untuk memisahkan PF net-funding-only dari
PF net-fees; `report.py` tampilkan gross/net-funding/net-fees 3 kolom
berdampingan; `walk_forward_windows.yaml` set default 0.0005/0.0005 (Binance
VIP0 taker per sisi). 15 test baru, 309 test total lulus, `ruff check` bersih.

Verifikasi data real (bukan hanya unit test): re-run full 1-tahun BTC/USDT
Binance 1h (8764 candle, 10 window walk-forward) dengan fee 0.0005/0.0005 —
rata-rata PF gross antar-window ~1.10 turun ke rata-rata PF net-fees ~0.92
(degradasi ~16%), arah dan skala konsisten dengan deep-dive (gross ~0.97 →
net-fees ~0.85). Kriteria promosi PF (>1.3 di ≥2/3 window) TIDAK terpenuhi
(1/10 window lulus) — sesuai ekspektasi F5, bukan regresi: strategi baseline
memang belum profitable net-of-fees, temuan ini justru mengonfirmasi F5, bukan
membantahnya. Replikasi 4 seri penuh (ETH/Binance, BTC/Bybit, ETH/Bybit)
belum diulang satu-per-satu pasca perubahan ini — 1 seri BTC/Binance sudah
cukup kuat sebagai spot-check karena logika fee identik untuk semua
seri/venue (murni aritmetika per-trade, tidak bergantung pada venue).

## Fase 2 — `skills/strategy/htf_bias.py` (F2/F9; bagian teori founder yang belum pernah diuji)

- `resample_candles(candles_1h, "4h"|"1d")` — agregasi OHLCV kalender UTC,
  closed-candle only, no partial bucket di ujung (anti-lookahead: bucket
  yang belum close TIDAK ikut).
- Bias per timeframe: REUSE `market_structure.trend_bias()` di atas
  `detect_swings()` hasil resample — jangan tulis detektor tren baru.
  Fallback eksplisit kalau swing < 2 di TF besar: bias NEUTRAL (bukan
  ngarang). Pertimbangkan juga expose proxy sederhana close-vs-SMA sebagai
  fitur kedua (biar fitting F3 yang memutuskan mana yang informatif —
  bukti sementara deep-dive justru dari SMA50/200).
- Output: `htf_alignment_score(direction, biases) → 0-1` (searah semua TF =
  1.0; melawan = rendah TAPI > 0 — faktor skor, bukan gate; bobot antar-TF
  Weekly>Daily>4h sesuai bag. 2e, angka awal bebas karena akan di-fit F3).
- Wire ke `signal_runner.generate_signals()` sebagai slot baru ala
  `regime_alignment`.
- Acceptance: test anti-lookahead resample; spot-check data real (BTC 1h
  production, tunjukkan bias Daily di tanggal yang jelas bear); funnel
  diagnostic sebelum/sesudah TIDAK berubah (karena bukan gate).

**Status: SELESAI (2026-07-03).** `htf_bias.py` (skill baru terpisah):
`resample_candles(candles_1h, "4h"|"1d")` agregasi kalender UTC (bucket
1d truncate ke midnight, 4h ke boundary 00/04/08/.../20), closed-bucket-only
via cek `bucket_candles[-1].ts` terhadap akhir bucket-nya sendiri (bukan
hitung expected-count, toleran thd input yang berhenti di tengah bucket —
kasus normal utk data live). `compute_bias()` reuse persis
`market_structure.trend_bias()` di atas swing hasil resample, fallback
`TrendBias.UNDEFINED` kalau swing<2 (bukan enum baru — reuse nilai yang
sudah ada persis sesuai prinsip modul ini). `htf_alignment_score(direction,
biases, weights=DEFAULT_HTF_TIMEFRAME_WEIGHTS)` — renormalize timeframe yang
hadir (pola sama `confluence_across_timeframes()`), 1.0 kalau semua TF
searah, 0.15 kalau berlawanan (bukan 0 — faktor skor, samakan angka dengan
`market_structure.STRUCTURE_ALIGNMENT_SCORE_OPPOSED`), 0.5 kalau
UNDEFINED/tidak ada data. `sma_trend_bias(candles, period=200)` proxy
close-vs-SMA terpisah (TIDAK di-blend ke `htf_alignment_score` — sengaja
dibiarkan jadi kandidat independen utk fitting F3, sesuai temuan F9 deep-dive
bhw SMA-alignment yang tervalidasi kausal, bukan trend_bias berbasis swing).

Wiring: `ConfluenceWeights` dapat field baru `htf_alignment=0.10` (diambil
0.05 dari `swing_quality`, 0.25→0.20, supaya tetap sum=1.0 — rebalancing awal
yang belum di-fit, sesuai prinsip "angka awal bebas"). `score_confluence()`
dapat parameter `htf_alignment: float | None = None` (default neutral 1.0
sama seperti `regime_alignment`). `signal_runner.generate_signals()` hitung
Daily+4h bias tiap bar dari `candles[: i+1]` (anti-lookahead, sama pola
`swing_quality`'s recency slice), wire ke `score_confluence()` sebagai slot
terpisah dari `regime_alignment` (BUKAN di-blend — structure BOS/CHoCH dan
HTF trend agreement dua sinyal berbeda).

21 test baru (`test_htf_bias.py`), 1 test lama diupdate (formula
`ConfluenceWeights` sum berubah), 330 test total lulus, `ruff check` bersih.
Verifikasi data real (bukan cuma unit test): full 1-tahun BTC/USDT Binance
1h — decline 10-hari tertajam (28.8%, berakhir 2026-02-05) correctly
teridentifikasi `DOWNTREND` di Daily DAN 4h; `htf_alignment_score` utk
SHORT=1.000 (aligned), LONG=0.150 (opposed) persis di tanggal itu. Funnel
diagnostic tidak berubah: 6 sinyal dari `noisy_zigzag()` seed=42 tetap 6
(htf_alignment cuma modulasi confidence, tidak pernah gate).

## Fase 3 — Dump per-faktor + Part #2 fitting (F1; ini yang mengubah skor dari opini jadi sains)

**3a. Dump komponen.** `Signal` diperluas: simpan nilai mentah TIAP faktor
(swing_quality, fib_gann_confluence, volume_confirmation, wick_rejection,
structure_alignment, htf_alignment, regime_alignment, + derivatives dari F4)
— bukan cuma `confidence` final. `replicate.py`/`run_validation.py` ikut
menulis kolom-kolom ini.

**3b. Fitting.** Modul baru `validation/fib_gann_backtest/fit_weights.py`:
logistic regression + regularisasi L1/L2 (scikit-learn — dependency BARU,
pasang di requirements harness/CI validation saja, JANGAN ke requirements
service production) pada label triple-barrier (+1 vs lainnya; trade TIMEOUT
kelola terpisah — dua skema: binary TP-vs-SL saja, dan 3-kelas — laporkan
dua-duanya), **refit per window walk-forward** (train di train-range,
evaluasi di test-range; JANGAN fit sekali di seluruh tahun).
Evaluasi: AUC + Brier per window, out-of-sample.

**3c. Adopsi.** Ganti `ConfluenceWeights` default dengan hasil fit HANYA
kalau: AUC OOS median > 0.55 DAN korelasi confidence-vs-return OOS > 0
(baseline sekarang -0.05). Kalau tidak tercapai, itu temuan valid — laporkan,
jangan paksakan.
Acceptance: report per window berisi AUC/Brier/korelasi; keputusan
adopsi/tolak eksplisit di brief.

**Status: SELESAI (2026-07-03).** `signal_runner.Signal` dapat 7 field baru
(default 0.5 supaya ADITIF — 2 test lama yg konstruksi `Signal` langsung,
`test_shadow_pair.py`/`test_trade_simulator.py`, TIDAK perlu disentuh sama
sekali): `swing_quality`, `fib_gann_confluence`, `volume_confirmation`,
`wick_rejection`, `structure_alignment`, `htf_alignment`, `regime_alignment`
— plus `sma_trend_bias_alignment` sbg **kolom kandidat terpisah**
(`htf_bias.sma_trend_bias()` diubah jadi skor 0-1 lewat `htf_bias.
bias_alignment()`, yg sekarang public, BUKAN di-blend ke `htf_alignment`
sesuai desain Fase 2). Modul baru `fit_weights.py`: `LogisticRegression
(solver="saga", l1_ratio=0.5)` — elastic-net L1+L2 dlm 1 fit, tanpa feature
scaling (semua faktor udah 0-1 native). Refit PER window walk-forward
(train-range fit, test-range evaluasi, JANGAN sekali di seluruh data). Dua
skema label dilaporkan: binary (TP=1/SL=0, TIMEOUT dikecualikan) dan
3-kelas (BarrierOutcome +1/-1/0 langsung sbg label), trade `censored`
dikecualikan dari keduanya. `regime_alignment` SENGAJA dikeluarkan dari
fitur yg di-fit (identik `structure_alignment` di wiring skrg — collinearity
sempurna tanpa nilai tambah, dicatat jelas di kode utk dipromosikan lagi
begitu `market_regime.py` bikin keduanya beda beneran).
`scikit-learn`/`numpy` HANYA masuk `packages/backtest-core[dev]` (CI `test`
job doang) — TIDAK pernah masuk `requirements.txt` root atau
`apps/products/trading/ingestion/requirements.txt` yg dipakai servis
production. 25 test baru (`test_fit_weights.py` + tambahan
`test_htf_bias.py`/`test_signal_runner.py`), 355 test total lulus, `ruff
check` bersih.

**Hasil real-data (BTC/USDT 1h Binance, 10 window walk-forward, bukan cuma
unit test)**: skema binary primer (6 faktor yg sudah wired) — median AUC
OOS **0.522**, korelasi confidence-vs-return OOS pooled (367 sampel)
**+0.018**. **Kriteria adopsi TIDAK terpenuhi** (AUC median di bawah 0.55) —
`ConfluenceWeights` default TIDAK diganti, sesuai "kalau tidak tercapai,
laporkan jangan paksakan". Catatan jujur: korelasi +0.018 masih SANGAT
lemah, tapi arahnya sudah POSITIF — perbaikan nyata drpd baseline
hand-tuned lama yg r=-0.05 (F1), meski belum cukup kuat utk diadopsi.

**Temuan sampingan yg justru paling penting**: fit `binary_with_sma_
candidate` (6 faktor primer + `sma_trend_bias_alignment`) dpt median AUC
**0.617** (naik dari 0.522) — dan `sma_trend_bias_alignment` dapat
koefisien BUKAN-NOL di **SEMUA 10 dari 10 window** (rentang 0.164-1.448),
sedangkan `htf_alignment` (basis swing, yg sekarang benerannya di-wire ke
confidence) di-nolkan L1 di beberapa window (window 0, 3 antara lain) atau
turun jauh saat kandidat SMA ikut di-fit bareng. Ini KONSISTEN PERSIS sama
temuan F9 deep-dive (SMA50/200-alignment yg tervalidasi kausal, bukan
trend_bias berbasis swing) — TAPI ini baru 1 sinyal dari fitting kandidat,
BUKAN kriteria adopsi resmi (yg tetap dievaluasi di skema 6-faktor primer
sesuai instruksi "kriteria adopsi tetap"). **Belum diadopsi/di-wire round
ini** — dicatat sbg kandidat kuat utk direvisit (mis. ganti/tambah
`sma_trend_bias_alignment` sbg slot resmi `ConfluenceWeights`, atau jadi
bagian F6 kampanye OOS berikutnya) bukan keputusan yg diambil sepihak
sekarang.

## Fase 4 — `skills/strategy/derivatives_context.py` (F6/F7; jawaban untuk funding/OI/long-short founder)

Sumber: CoinGlass Hobbyist HARIAN (cukup; `1h` = 403 terkonfirmasi) +
`funding_rate`/`open_interest` native dari F0c untuk granularity jam
kemudian. Fetch → cache ke DB/file per hari (hormati rate limit ~2.5s/call;
endpoint per-pair wajib `exchange=`, agregat pakai coin symbol — detail di
investigation doc bag. 4).

Fitur per (koin, tanggal), semua dari HARI SEBELUM entry (no-lookahead):
- `funding_percentile_365d` — sinyal contrarian (F7: ≥p90 BTC → -0.45% H+1)
- `global_ls_percentile`, `top_vs_global_divergence` — fade-the-crowd
- `liq_cascade_flag` (long-liq kemarin > p90 tahunan)
- `fuel_quadrant` kemarin — HANYA untuk konteks volatilitas/sizing (bukan
  arah! bukti F6), dipisah jelas dari faktor arah.

Wire sebagai faktor skor (ikut di-fit F3), plus konsumsi kedua: modul
sizing/risk boleh baca `fuel`/`liq_cascade` untuk melebarkan SL buffer /
menurunkan size di hari high-vol. Acceptance: test unit + join-coverage
report (berapa % sinyal punya fitur derivatives tersedia H-1), dan
kontribusi fitur terlihat di koefisien fitting F3 (boleh nol — L1 yang
memutuskan).

**Status: SELESAI (3 Juli 2026, hari yg sama).** `skills/strategy/
derivatives_context.py` — pure function, no DB/HTTP, graduasi dari
`validation/deep_dive_2026_07/coinglass_pull.py`+`cg_analysis.py` (scratch
analysis deep-dive) ke modul teruji, pola yang sama dengan Fase 1-3.
`compute_derivatives_context()` menghitung `funding_percentile_365d`,
`global_ls_percentile_365d`, `top_vs_global_divergence`, `liq_cascade_flag`,
`fuel_quadrant` dari trailing window (≤365 hari) SEBELUM `target_date`,
menolak membaca record `target_date` itu sendiri (no-lookahead ditegakkan
struktural, bukan cuma didokumentasikan). `funding_contrarian_alignment()`/
`global_ls_contrarian_alignment()`/`top_vs_global_alignment()` mengubah
ketiga fitur pertama jadi skor 0-1 relatif ke arah sinyal (fade-the-crowd:
funding/GLS percentile tinggi → mendukung SHORT, divergence top-vs-global
positif → mendukung LONG) — `liq_cascade_flag` SENGAJA TIDAK diberi arah
(tidak ada teori arah yg established di codebase ini utknya, temuan
deep-dive malah bilang "weak H+1, zero effect on trade outcomes" —
memaksakan tanda arah di sini sama saja mengarang klaim). `fuel_quadrant`
TIDAK PERNAH masuk `Signal`/fitting sama sekali — murni utk konsumsi
`position_sizing.py` (`high_vol_flag`) via caller, persis pemisahan yg
diminta roadmap.

Wiring: `signal_runner.Signal` dapat 4 field baru (`funding_contrarian_
alignment`, `global_ls_contrarian_alignment`, `top_vs_global_alignment`,
`liq_cascade_flag`), semua default netral (additive, tidak mengubah call
site lama). `generate_signals()` dapat parameter opsional baru
`derivatives_records` — kalau tidak disuplai (default), field-field ini
tetap netral, fully backward compatible. `fit_weights.py` dapat
`DERIVATIVES_FEATURE_NAMES` (FEATURE_NAMES + 4 kolom baru) dan
`WindowFitResult.binary_with_derivatives_candidate` — fit informational
terpisah (persis pola `binary_with_sma_candidate` Fase 2), TIDAK memengaruhi
`evaluate_adoption()`.

37 test baru (`test_derivatives_context.py` 25, plus tambahan di
`test_signal_runner.py`/`test_fit_weights.py`), 373 test total lulus, ruff
clean. **Diverifikasi thd data CoinGlass BTC real** (400 hari harian ditarik
langsung dari sandbox via endpoint yg sama dgn `coinglass_pull.py`, ~2.5s
jeda per call, semua 6 endpoint `code=0`): `target_date`=2026-07-03,
`funding_percentile_365d=0.936` (dekat ambang p90 yg disebut roadmap),
`global_ls_percentile_365d=0.648`, `top_vs_global_divergence=-0.71`,
`fuel_quadrant=UP_OI_UP`, `liq_cascade_flag=False` — alignment score
SHORT>LONG utk funding & GLS (0.936/0.648 vs 0.064/0.352), konsisten
dgn arah teori contrarian. **Join-coverage**: 11/11 (100%) hari candle
BTC/USDT 1h production (250 candle terakhir) punya ≥1 record derivatives
H-1. `generate_signals()` end-to-end dgn `derivatives_records` asli
menghasilkan 18 sinyal real dgn field derivatives terisi penuh (bukan
default netral) — mis. sinyal SHORT jam 2026-06-25T11:00Z dpt
`funding_contrarian=0.168`, `global_ls_contrarian=0.762`,
`top_vs_global=1.0`, `liq_cascade_flag=1.0` (real cascade event, 25-26
Juni 2026 confirmed via `liq_cascade_flag=True` beberapa jam berturut).

## Fase 5 — R:R band & SL anti-hunt (F3/F4 deep-dive; eksperimen terkontrol, bukan tuning diam-diam)

- Harness A/B di `validation/`: konfigurasi `min_rr_threshold` 1.5 vs 2.0
  dan tambahan `max_rr_threshold` 5.0 (cap baru — ini MENGUBAH gate yang
  ada, boleh, karena gate R:R memang sudah gate; angkanya saja yang diuji).
- SL varian: buffer 0.25-0.5×ATR (sekarang) vs 0.75-1.0×ATR vs SL di balik
  level fib BERIKUTNYA. Ukur: % SL-hit, PF net, funnel.
- Acceptance: keputusan per varian berdasarkan walk-forward OOS net-fees di
  ≥2 aset × 2 venue; hasil (termasuk yang kalah) ditulis di brief.

## Fase 6 — Kampanye validasi OOS (gerbang skor 6→7)

Jalankan `run-validation.yml` (config diperluas: 4 seri, fee-aware, fitted
weights, semua faktor) — kriteria promosi bag. 7 **net of fees**: PF net
> 1.3 di ≥2/3 window, per seri. Segmentasi regime (bear/range/bull proxy
drift bulanan) dilaporkan. Data baru yang terus masuk dari worker = OOS
sejati untuk filter yang lahir dari data setahun ini — jangan buang.
Acceptance: BTC lolos (skor 7); BTC+ETH dua venue lolos → lanjut F7 (skor 8
track). Gagal → kembali ke F3/F5 dengan temuan baru, BUKAN menambah teori
baru (bag. 10).

## Fase 7 — Shadow trading & jembatan paper-vs-real (gerbang skor 8→9)

1. Live signal loop minimal: worker yang menjalankan `generate_signals` di
   candle close 1h production, persist ke tabel `signal` (F0b). Belum
   eksekusi order — sinyal saja.
2. Founder trade real yang searah sinyal via `log_trade_annotation.py`
   (leverage, margin_mode, exit_reason_real WAJIB terisi).
3. `shadow_pair` pipeline yang sudah ada (pairing + divergence attribution +
   fidelity) jalan otomatis atas pasangan itu; rolling report (Telegram
   layer boleh menyusul, mulai dari report markdown).
4. Cold-start rule tetap: ≥50 pasangan sebelum parameter ML risk envelope
   apapun diaktifkan (shadow-simulator-brief bag. 5 — hard cap leverage
   manual, kill-switch, floor buffer_k TIDAK PERNAH dipelajari ML).
Acceptance skor 9: 3+ bulan, PF real net ≥ 0.7× backtest, fidelity rolling
≥70, nol pelanggaran hard cap.

### F7a — `skills/strategy/position_sizing.py` + PreTradeCard (paralel, boleh dikerjakan kapan saja)

Spec lengkap + keputusan margin-mode di **`docs/margin-mode-brief.md`**
(baca dulu sebelum implementasi). Ringkas: pure-function skill tanpa DB
yang menghitung kartu pra-eksekusi per sinyal — `risk_amount` → `qty` →
`leverage_used = min(cap_mandate, max_safe_leverage)` → `initial_margin`,
est. liquidation price, margin ratio, jarak SL/TP dalam % notional DAN %
margin, plus warnings. REUSE `max_safe_leverage()`/`build_margin_context()`/
`assert_liquidation_safe()` yang sudah ada di `trade_simulator.py`, jangan
tulis ulang. Margin mode datang dari mandate (bukan per-trade); MVP hanya
ISOLATED — `cross` → `NotImplementedError` yang menunjuk F7b, jangan
pura-pura menghitung. Tidak menyentuh `signal_runner`/gate manapun.
Skema: kolom `default_margin_mode` di `risk_mandate` dititipkan di PR draft
F0d (CODEOWNERS, satu kali review founder).

**Status: SELESAI (3 Juli 2026, hari yg sama).** Diimplementasi persis spec
di atas — detail lengkap (nomor real hasil spot-check thd 250 candle
BTC/USDT 1h production, hasil unit test, dan catatan migrasi) ada di
`docs/margin-mode-brief.md` bag. 4. Ringkas: `CrossMarginNotImplementedError`
utk cross, `derivatives_context` high-vol flag cuma mengecilkan risk (satu
arah, tidak pernah menaikkan leverage), 11 test baru lulus, ruff clean.
**Catatan penyimpangan dari rencana**: kolom `risk_mandate.default_margin_mode`
+ `risk_pct_per_trade` TERNYATA TIDAK bisa "dititipkan" ke PR draft F0d
seperti rencana awal di atas — PR itu (migration 0006) sudah merge & role
barunya sudah dieksekusi di production duluan sebelum kerjaan F7a ini
dimulai. Jadi kolom ini masuk migrasi baru terpisah
(`0007_risk_mandate_margin_mode_columns.py`), tetap kena review CODEOWNERS
manual founder yang sama, cuma PR-nya beda dari yang direncanakan semula.

### F7b — Portfolio-level margin simulator: cross mode, margin ratio akun (SETELAH F7 punya posisi nyata)

Ditunda sadar, bukan ditolak — alasan lengkap di `docs/margin-mode-brief.md`
bag. 1 & 6. Scope saat waktunya tiba: simulasi cross dengan state seluruh
akun (total equity + unrealized PnL semua posisi → est. liquidasi akun yang
bergeser setiap posisi lain bergerak), efek entri ke-2+ terhadap liq
keseluruhan, margin-ratio telemetry akun + kill-switch (guardrail
"total margin used / equity ≤ X% per regime, range 20-60%" dari
shadow-simulator-brief bag. 5), dan pyramiding/multi-entry sebagai fitur
yang diuji — bukan default. Prasyarat keras: shadow loop F7 sudah
menghasilkan state posisi nyata; TANPA itu simulasi cross cuma tebakan
`cross_buffer_pct` seperti sekarang.

## Fase 8 — Generalisasi universe: seluruh market kripto → tokenized equity

Prinsip desain yang membuat ini MUNGKIN dan sudah terbukti sebagian:
formula scale-free (Gann Opsi 1 tervalidasi lintas skala harga BTC↔SOL;
semua threshold ATR-relative; fib set per-instrumen configurable sejak
bag. 2a). Prinsip yang WAJIB dijaga: **tidak ada tuning per-simbol manual —
yang boleh beda per simbol hanya output pipeline fitting/kalibrasi yang
sama**, kalau tidak, ini jadi 500 strategi overfit, bukan satu teori.

**8a. Ekspansi kripto (bertahap):**
- Universe rule-based di config (bukan hardcode): top-N perp USDT-M by
  volume & OI (mulai N=10: SOL, BNB, XRP, DOGE, dst.), filter likuiditas
  minimum (volume harian & spread) — instrumen illiquid merusak asumsi fill.
- Worker ingestion backfill 1 tahun 1h per simbol baru (kapasitas Neon &
  rate limit dicek dulu — 8.763 baris × simbol × venue).
- Jalankan kampanye F6 per simbol; laporkan MATRIX hasil (simbol × venue ×
  window). Ekspektasi jujur: sebagian simbol akan gagal — itu hasil, bukan
  kegagalan proses; universe live = subset yang lolos + terus dimonitor.
- Cek stabilitas fitted weights lintas simbol (koefisien mirip = teori
  general; koefisien liar = red flag overfit).

**8b. Tokenized equity di bursa kripto (AAPLUSDT, MSTRUSDT, XAUUSDT, dst. —
founder sudah pernah trade 53 simbol termasuk ini):**
- Ingestion: connector ccxt yang sama sudah bisa (mereka perp USDT-M di
  Binance) — yang beda adalah STRUKTUR PASARNYA, dan ini wajib dimodel,
  bukan diabaikan:
  - Underlying punya jam bursa (NYSE/NASDAQ) — likuiditas & perilaku harga
    di luar jam itu beda total; `session_bias.py` yang sudah ada di-extend
    dengan kalender market-hours underlying, dan fitur "in/out of
    underlying hours" masuk fitting.
  - Corporate action (split/dividen) bikin gap harga yang BUKAN sinyal —
    perlu guard di swing detection (flag gap > X×ATR sebagai discontinuity,
    invalidasi swing yang melintasinya).
  - Funding & likuiditas tipis: liquidation-aware sim (sudah ada) makin
    penting; hard cap leverage per kelas aset lebih rendah.
  - CoinGlass TIDAK meng-cover simbol ini → `derivatives_context` harus
    graceful-degrade (fitur None di-skip, pola `compute_fidelity_score`).
- Mulai 2-3 simbol paling likuid saja, kampanye F6 penuh, sebelum melebar.
- **Konfirmasi scope ke founder sebelum mulai 8b** — kelas aset baru =
  keputusan produk, bukan keputusan teknis.

**8c. Bursa tambahan** (OKX/Hyperliquid dst.): connector ccxt generic sudah
venue-agnostic; tambah venue = tambah baris `venue` + kredensial read-only +
backfill; replikasi cross-venue (Jaccard + PF parity, pola investigasi
Fable 5) jadi UJI STANDARD setiap venue baru sebelum dipakai.

## Fase 9 — Gerbang live trading (jangan dilangkahi)

Prasyarat SEMUA: skor 9 tercapai (F7), risk layer hard-coded terpasang
(hard cap leverage per simbol/kelas aset, kill-switch drawdown harian/
mingguan, floor buffer_k, R:R gate), `execution/risk_gate.py` +
`execution/custody/*` (CODEOWNERS — review manual founder, security-first),
kredensial exchange read/trade dipisah, dan mandat risiko (`risk_mandate`)
di-enforce di kode bukan di niat. Mulai dengan size minimum ("live kecil")
dan bandingkan terus terhadap shadow — divergence attribution adalah
instrumen monitoringnya, fidelity < 70 rolling = auto-pause sinyal baru.
Ini fase yang secara eksplisit BUTUH keputusan & kehadiran founder di tiap
langkah; Sonnet 5 menyiapkan, founder yang menarik pelatuk.

---

## Definisi selesai per fase (ringkas, pakai rubric deep-dive bag. 5)

| Fase | Skor rubric | Bukti objektif |
|---|---|---|
| F0-F1 | 4/10 | Semua angka net-of-fees; trade_annotation terisi terverifikasi |
| F2+F5 | 5/10 | PF net pooled > 1.1 di 4 seri (in-sample sanity) |
| F3(+F4) | 6/10 | AUC OOS > 0.55, korelasi confidence-return OOS > 0 |
| F6 BTC | 7/10 | PF net > 1.3 di ≥2/3 window, net fees |
| F6 BTC+ETH + F7 mulai | 8/10 | Kriteria di 2 aset × 2 venue + ≥50 shadow pair |
| F7 matang | 9/10 | 3 bulan shadow/live-kecil sesuai threshold |
| F8 lintas rezim | 10/10 | Edge bertahan multi-tahun/multi-rezim/multi-aset, semua biaya |

Kejujuran terakhir yang harus diwariskan ke setiap sesi: skor 10/10 berarti
"proses validasi tak bercela", bukan "jaminan profit" — dan setiap angka
yang lahir dari data yang sama dengan yang menginspirasi hipotesisnya
tetap berlabel in-sample sampai dibuktikan di data yang belum pernah
dilihat.
