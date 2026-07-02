# PRD + Rencana Teknis: Kinetiq — Multi-Agent AI Trading SaaS

**Nama bisnis terpilih: "Kinetiq"** (dari "kinetic" — sejalan analogi fisika pasar milik founder: waktu, jarak/harga, momentum/volume). Repo GitHub (`agent-trading-perp`) akan di-rename jadi **`kinetiq-app`** (dikonfirmasi user) setelah rencana ini di-approve (lihat Section C.4).

## Context

Proyek ini awalnya dirancang sebagai bot trading perpetual futures pribadi, penerus dari bot lama user ("Markoviz" / `ai-perp-bot-core`), dengan acuan arsitektur [HKUDS/Vibe-Trading](https://github.com/HKUDS/Vibe-Trading). Setelah diskusi lebih lanjut, scope berubah signifikan:

1. **User adalah trader perp aktif 5 tahun** dengan track record nyata (profit $30→$1000 dalam 1 minggu, peak $1000→$10.000), mengandalkan **Fibonacci retracement (modifikasi) + Gann Fan** sebagai metode entry-timing utama, sebelumnya di MEXC (high leverage), sekarang migrasi ke Binance untuk kualitas data.
2. User punya **teori pasar sendiri**: pola musiman per timeframe yang saling berkaitan lintas timeframe (analogi "meta" game — ada yang "di-buff/di-nerf" secara temporer), dan analogi fisika (waktu, jarak/harga, volume/berat) untuk menjelaskan bagaimana perilaku seluruh partisipan pasar (retail, institusi, whale) tercermin di chart. Observasi pasar: altseason belum terbentuk cycle ini meski BTC sudah ATH.
3. **Pivot scope**: bukan lagi bot pribadi single-asset, tapi **platform SaaS multi-agent** yang mencakup spot, perp/futures, meme-sniper, dan DLMM (liquidity provision) — dengan alasan bisnis: banyak trader mau bayar untuk bot semacam ini, apalagi era tokenisasi saham/equity akan memperluas pasar.
4. Keputusan bisnis yang sudah dikonfirmasi user: **(a)** monetisasi = subscription, **non-custodial** (user pegang API key/wallet sendiri, kita tidak pernah pegang dana — menghindari beban regulasi custodian/fund manager); **(b)** MVP = **Perp + Spot dulu**, Meme-sniper & DLMM menyusul sebagai modul agent terpisah; **(c)** dua tier layanan: **signal-only** (alert, tanpa eksekusi) dan **auto-execute** (eksekusi penuh via API key/wallet user).

Repo: `kinetiq-app` (di-rename dari `agent-trading-perp`), branch default `main`, sudah tidak greenfield-kosong lagi — lihat **Status Implementasi** di bawah utk apa yg sudah nyata vs baru rencana.

### Status Implementasi (live, di-update tiap ada progres nyata — bukan cuma rencana)

**Sudah jalan & terverifikasi:**
- Repo `kinetiq-app`, branch `main` (default), CI (`.github/workflows/ci.yml`) hijau di semua push.
- `.github/CODEOWNERS` aktif — wajib review manual utk `execution/risk_gate.py`, `execution/custody/`, `packages/db/migrations/`.
- **Skema DB Fase 0 sudah ditulis & diverifikasi** (`packages/db/src/kinetiq_db/models.py` + `migrations/versions/0001_initial_schema.py`): 32 objek (25 tabel reguler + 7 tabel partisi), termasuk `tenant` (dgn `payment_provider`/`payment_customer_id`/`payment_subscription_status` generalized), `platform_user`, `llm_config`, `token_package`, `tenant_token_ledger`, seluruh tabel time-series derivatif, dan `trade_annotation`. Terverifikasi upgrade→downgrade→upgrade thd PostgreSQL 16 lokal.
- **Klarifikasi penting soal "koneksi Neon"**: yg diblokir network-policy itu cuma **sesi Claude Code ini** (sandbox), **BUKAN GitHub Actions runner**. Terbukti nyata: job `neon-preview-branch` sudah tereksekusi 3x lewat PR #1-#3 (workaround push-to-relay), dan step **"Create Neon branch for this PR" berhasil sukses** tiap kali — artinya `NEON_API_KEY`/`NEON_PROJECT_ID` valid & CI beneran connect ke Neon asli. Yang gagal cuma step migrasi (lihat bug di bawah), bukan koneksi Neon-nya.
- **Semua env var kredensial (Clerk, Midtrans, CoinGlass, Neon, OpenRouter, Langfuse, KMS_MASTER_KEY_ID, Railway token) sudah di-setup user langsung di Railway service Variables** — sebagian besar item "yg dibutuhkan dari user" di ronde sebelumnya sudah terpenuhi.

**Bug/gotcha operasional (Neon migration driver, Neon branch naming, 4x Railway/Railpack deploy bug)**: semua ditemukan & diperbaiki, terverifikasi thd Neon asli & Railway asli (bukan cuma lokal). **Detail lengkap tiap bug + root cause dipindah ke `docs/deployment-runbook.md`** (supaya PRD ini tidak jadi log debugging) — wajib dibaca sebelum ubah `railway.toml`/`ci.yml`/koneksi DB lagi. Ringkasan hasil akhir: CI (lint + Neon preview branch + migrate + schema-diff) hijau penuh thd Neon asli; `api-gateway` live & sehat di Railway (`Uvicorn running` + `GET /health` 200 OK, status Active/Online).

**Progres terbaru**: `api-gateway` sekarang py **tenant auth middleware nyata** (`deps.py`) — verifikasi Clerk session JWT via JWKS (`PyJWKClient`), auto-provision `platform_user` di login pertama (kolom baru `clerk_user_id`, ditambahkan ke migration 0001 & model), set `app.tenant_id` per-session (siap dipakai RLS begitu diimplementasi). Endpoint `/me` sbg bukti alur jalan end-to-end (401 tanpa token/token invalid, terverifikasi lokal), sekarang juga return `plan_tier` tenant. **Plan-gating juga sudah ada**: `deps.require_plan(*allowed_tiers)` — dependency factory yg cek `tenant.plan_tier` per endpoint, `role='superadmin'` selalu bypass (A.3/B.13), user tanpa tenant atau plan tidak cocok dapat 403. Dibuktikan lewat endpoint placeholder `GET /trading/auto-execute/status` (gated ke `auto_execute`, bukan business logic asli — nunggu `apps/products/trading/*` beneran ditulis) dan diverifikasi via `TestClient` + dependency override (signal_only->403, auto_execute->200, superadmin->200 bypass, no-tenant->403), krn butuh JWT Clerk asli utk test end-to-end penuh via HTTP. `packages/db` direfer dari `api-gateway` via `PYTHONPATH` di `startCommand` (`railway.toml`), **bukan** pip install apapun — root cause asli: Railway "Root Directory" scope seluruh build+runtime context ke satu subfolder saja, sibling directory (`packages/db`) tidak pernah ada di container itu, baik via editable pip install maupun subfolder-relative `PYTHONPATH` (dua percobaan awal, keduanya gagal). Fix final: Root Directory di-pindah ke **repo root**, `requirements.txt` ikut pindah ke repo root (supaya Railpack zero-config Python detection tetap native), `PYTHONPATH` di `startCommand` mencakup baik `packages/db/src` maupun folder `api-gateway` itu sendiri. Detail penuh & reproduksi lokal di `docs/deployment-runbook.md` gotcha #7. Logic normalisasi `DATABASE_URL` (driver `psycopg`) di-konsolidasi jadi helper bersama `kinetiq_db.engine.normalize_db_url()`, dipakai baik oleh `packages/db/migrations/env.py` maupun `api-gateway/deps.py` — supaya bug yg sama tidak perlu diperbaiki dua kali lagi kalau ada service baru.

**RLS policy (Section B.4) sekarang live** (`packages/db/migrations/versions/0002_add_rls_policies.py`): `tenant_isolation` policy di 9 tabel domain tenant-owned (`tenant_token_ledger`, `strategy`, `portfolio_target`, `position`, `order_audit_log`, `risk_mandate`, `tenant_credential`, `dlmm_position`, `trade_annotation`) + `llm_config` (dgn pengecualian `tenant_id IS NULL` supaya baris global/product-scope tetap keliatan semua tenant, sesuai hierarki resolve di B.13). `platform_user` sengaja TIDAK dikasih RLS — `deps.py` cari user by `clerk_user_id` sebelum `tenant_id` diketahui, kalau di-RLS lookup itu sendiri jadi buntu (login siapapun jadi gagal). Pakai `FORCE ROW LEVEL SECURITY` krn role `DATABASE_URL` saat ini = pemilik tabel (belum ada role app terpisah least-privilege) — tanpa FORCE, RLS jadi no-op total thd query app sendiri. Proses implementasi ini nemu 2 bug nyata yg sblmnya cuma "belum ketauan" (bukan baru muncul): (1) `SET x = :param` di `deps.py` (dipakai sejak PR tenant-auth) ternyata TIDAK support bind parameter (Postgres syntax error), gak pernah ketriger krn belum ada login sungguhan dgn `tenant_id` terisi — fix pakai `SELECT set_config(...)`; (2) custom GUC `app.*` yg belum pernah di-set di sesi tertentu bisa balikin `''` bukan `NULL` (begitu nama GUC itu pernah dipakai sesi lain di server yg sama) — fix pakai `NULLIF(current_setting(...), '')` sblm cast ke uuid. Diverifikasi lokal end-to-end pakai role non-superuser (superuser Postgres selalu bypass RLS, jadi gak valid dites pakai `postgres` role) yg jadi owner tabel (meniru role produksi apa adanya): fresh session tanpa context → 0 baris (fail-closed), tenant A cuma liat baris sendiri, cross-tenant INSERT ke-reject `WITH CHECK`, superadmin bypass liat semua. Detail penuh di `docs/deployment-runbook.md` bagian "Row-Level Security (RLS) gotchas".

**Riset payment/domain (blm actionable dari sisi saya, ini task manual user)**:
- **Domain `.app`**: registrar termurah — Cloudflare Registrar (wholesale, tanpa markup) atau Porkbun/NameSilo (~$5-15/tahun). `.app` wajib HTTPS by default, otomatis terpenuhi (Railway TLS).
- **XIDR (StraitsX)** dipilih drpd IDRX sbg provider stablecoin utama: regulated, StraitsX Indonesia Business Account terima tipe **"Sole Trader"** (KTP+NPWP pribadi saja, tanpa PT, verifikasi 1-3 hari kerja). Panduan apply: (1) siapkan NIB Perorangan (oss.go.id) + NPWP pribadi, (2) daftar StraitsX Indonesia Business Account tipe Sole Trader, (3) upload KTP+NPWP, (4) tunggu 1-3 hari kerja, (5) minta akses Payment API setelah aktif (detail teknis API belum diverifikasi mendalam, cek dashboard StraitsX langsung). IDRX dicatat sbg backup kalau StraitsX ada kendala.

**`order_audit_log` sekarang genuinely append-only** (`0003_order_audit_log_append_only.py`): bukan lewat `REVOKE UPDATE, DELETE` spt rencana awal — itu jadi no-op krn Postgres object owner selalu retain semua privilege terlepas dari GRANT/REVOKE (situasi sama persis kenapa RLS butuh `FORCE` di 0002: role `DATABASE_URL` = pemilik tabel). Dipakai `BEFORE UPDATE OR DELETE` trigger yg unconditionally reject kedua operasi itu, berlaku bahkan thd table owner sendiri (diverifikasi lokal: `UPDATE`/`DELETE` ditolak walau dijalankan sbg superuser `postgres`) — tidak ada bypass sama sekali, termasuk sesi superadmin, krn audit log yg bisa diedit oleh role manapun (setrusted apapun) bukan audit log beneran. Koreksi data harus lewat row baru (compensating entry), bukan edit histori.

**Billing/tenant-provisioning stopgap** (`api-gateway/billing.py` + `POST /billing/subscribe`): supaya plan-gating & RLS yg udah jalan bisa dites via HTTP API sungguhan (real Clerk JWT), bukan cuma raw SQL manual. **BUKAN** integrasi Midtrans/XIDR asli (Section B.16) — akun kedua provider itu masih belum di-setup user (masih pending verifikasi KTP/NPWP), jadi provider adapter beneran belum bisa dites. `sync_tenant_plan(user, plan_tier, db)`: kalau user blm py tenant, auto-provision `tenant` row baru + assign ke user (mirip alur self-serve yg dimaksud A.3, tapi tanpa validasi pembayaran apapun); kalau udah py tenant, update `plan_tier`-nya (simulasi upgrade/downgrade). Diverifikasi end-to-end via `TestClient` lewat alur penuh: user fresh (no tenant) → `/trading/auto-execute/status` 403 → `POST /billing/subscribe {"plan_tier":"auto_execute"}` → `/me` skrg py `tenant_id`+`plan_tier` → `/trading/auto-execute/status` jadi 200 → downgrade ke `signal_only` → 403 lagi. **Wajib diganti** jadi hasil konfirmasi payment webhook begitu integrasi Midtrans/XIDR beneran ada — sengaja gak boleh dibiarkan produksi lama-lama krn user bisa self-assign tier berbayar tanpa bayar sungguhan. Buat testing manual lewat browser tanpa perlu `curl`/terminal, ada `tools/manual-test-console.html` (halaman HTML mandiri, klik-klik Clerk login -> test tiap endpoint) — ini butuh CORS diaktifkan di `api-gateway` (`allow_origins=["*"]`, aman krn auth-nya bearer-token bukan cookie, jadi gak ada eksposur CSRF; wajib dipersempit begitu `dashboard-shell` py domain pasti).

**Insiden produksi nyata & fix**: tabel `platform_user` (dan semua tabel lain) ternyata **belum pernah ada** di database Neon `production` asli — CI `neon-preview-branch` cuma pernah jalan ke ephemeral per-PR branch (dihapus stlh PR selesai), gak pernah membuktikan `production` beneran ke-migrate. Ketauan lewat request `/me` pertama dgn token Clerk asli yg berhasil sampai ke query DB (login sebelumnya semua dites tanpa token, jadi selalu berhenti di 401 sblm nyentuh DB) — crash `psycopg.errors.UndefinedTable`. Fix: `railway.toml`'s `startCommand` sekarang jalanin `alembic upgrade head` otomatis sblm `uvicorn` start, tiap deploy (idempotent). Detail lengkap di `docs/deployment-runbook.md` Neon gotcha #0 — **wajib dibaca**, ini kelas bug yg gampang keulang kalau nambah service baru dgn migration sendiri.

**`apps/products/trading/ingestion` — connector CEX pertama yg beneran ada, dan sudah TERVERIFIKASI hidup**: Binance USDS-M perpetual futures + Bybit, via CCXT (`connectors/cex/ccxt_generic.py` + `ingest.py`), scope sengaja sempit — `funding_rate` + `ohlcv` doang. `ccxt_generic.py` sengaja generik (bukan per-exchange module spt versi awal `binance_ccxt.py`) — ccxt expose unified API yg sama persis lintas exchange, jadi 1 wrapper cukup; nambah venue baru = 1 entry baru di `VENUES` dict. Auto-provision `venue`/`instrument` per venue (idempotent), upsert time-series via `db.merge()`, tulis `data_source_health` per venue+data_type. Standalone script, **belum di-wire ke Inngest** (belum ada infra Inngest sama sekali di repo ini). Diverifikasi lokal via mocked exchange object (upsert/idempotency/health-tracking multi-venue, dari sandbox Claude Code yg diblokir ke `fapi.binance.com`/Bybit), **DAN diverifikasi user sendiri via panggilan jaringan asli ke Binance + Neon production — berhasil** (`BTC/USDT:USDT` & `ETH/USDT:USDT`, lewat proxy Webshare.io) — **Bybit belum dites via jaringan asli**, cuma mocked, msh nunggu verifikasi user. Support opsional `<VENUE>_API_KEY`/`<VENUE>_API_SECRET` per venue (harus read-only, funding_rate/ohlcv itu public endpoint jadi gak wajib) & `PROXY_URL` (satu env var dipakai semua venue, di-rename dari `BINANCE_PROXY_URL` — IP blocking itu masalah jaringan bukan spesifik exchange) — dua masalah beda, API key soal rate limit, proxy soal IP blocking, gak saling gantiin. Dua bug nyata ketemu & fixed pas setup real pertama kali: ccxt `InvalidProxySettings` (jangan set `httpProxy` dan `httpsProxy` bareng) dan `407 Proxy Authentication Required` (ternyata salah copy password proxy, bukan soal concurrent-user/plan Webshare — `curl --proxy` polos cara tercepat isolasi soal ini). Detail di `apps/products/trading/ingestion/README.md`.

**Hyperliquid (DEX perp pertama, Fase 1 B.9) ditambahkan ke `VENUES` dict** — tapi bukan sekadar 1 entry baru spt yg diasumsikan pola CEX sebelumnya, ccxt `exchange.has` expose 2 perbedaan nyata yg butuh perubahan di `ccxt_generic.py`: (1) `fetchFundingRate` (single-symbol) `False` di Hyperliquid, cuma ada `fetchFundingRates` (plural/all-market) — `fetch_funding_rate()` sekarang cek `exchange.has` dulu & fallback ke bentuk plural, index by symbol; (2) auth Hyperliquid pakai `walletAddress`/`privateKey` bukan `apiKey`/`secret` spt CEX, tapi moot krn `funding_rate`/`ohlcv` public endpoint semua venue — `VENUES["hyperliquid"]` set `api_key_env`/`api_secret_env` ke `None` (bukan nunjuk ke env var yg bakal di-ignore diam-diam oleh ccxt), `make_exchange()` skip config kredensial kalau `None`. **Bug nyata ketemu pas kerjain ini**: `FUNDING_INTERVAL_HOURS` sebelumnya hardcode `8` utk SEMUA venue, padahal ccxt beneran expose field `interval` per-response (sudah ada di Binance/Bybit jg, cuma gak pernah dipakai) — Hyperliquid funding settle per jam (`"1h"`), bukan 8h, kalau tetap hardcode data funding-nya salah total. Fix: parse `interval` dari response, fallback ke konstanta `DEFAULT_FUNDING_INTERVAL_HOURS=8` cuma kalau venue itu beneran gak expose field ini. `venue.venue_type` jg sekarang per-venue dari `VENUES` dict (`"dex"` utk Hyperliquid vs `"cex"` sebelumnya — dulu di-hardcode `"cex"` utk semua venue baru, latent bug yg baru ketauan pas nambah venue non-CEX pertama). Symbol convention beda (quote USDC, `"BTC/USDC:USDC"`, bukan USDT) — krn `--symbols` CLI dipakai bareng utk semua `--venues` dlm 1 invocation, Hyperliquid wajib dijalankan terpisah (lihat contoh command README), gak bisa dicampur `--venues binance bybit hyperliquid`. Diverifikasi lokal end-to-end via mocked exchange object **+ Postgres 16 lokal beneran** (`alembic upgrade head` dijalankan penuh dulu, bukan cuma import check) — venue_type, funding_interval_hours=1, idempotency re-run, dan regression check eksplisit bhw Binance/Bybit tetap `funding_interval_hours=8`/`venue_type=cex` spt sebelumnya (gak keregresi oleh perubahan generik di `ccxt_generic.py`). **Sekarang JUGA sudah TERVERIFIKASI via jaringan Hyperliquid asli** — user jalankan langsung dari Termux (Android/Pixel 8, bukan proxy cloud spt Binance, Hyperliquid gak butuh proxy sama sekali) ke `api.hyperliquid.xyz`: 752 market ke-load, `has.get("fetchFundingRate")` konfirmasi `False` sesuai dugaan (fallback plural yg beneran jalan), funding rate asli dgn `interval: "1h"` (bukan 8h), OHLCV candle asli. Detail 2 gotcha Termux (build `cryptography` gagal krn rustup gak support target Android — fix `pkg install python-cryptography`; `coincurve` dependency wajib di metadata ccxt tapi cuma opsional di kode-nya, bikin build macet — fix `pip install ccxt --no-deps` + install manual `requests`/`certifi`/`typing_extensions`) di `apps/products/trading/ingestion/README.md`.

**Partitioning otomatis (Fase 1 B.9) sekarang ada** (`packages/db/migrations/versions/0004_partition_rollover.py` + `infra/neon/partitioning/rollover.sql`). Ketauan lewat cek langsung ke production: 7 tabel partisi (`funding_rate`, `open_interest`, `price_basis`, `orderbook_snapshot`, `liquidation_event`, `market_sentiment`, `ohlcv`) dari migration 0001 gak pernah py partisi range beneran — semua data numpuk di partisi `DEFAULT` sejak awal, termasuk data production asli (`funding_rate`/`ohlcv` spanning 2026-06-27..07-01). Fungsi `kinetiq_ensure_month_partition(table, month)` (dibuat migration 0004, dipanggil ulang oleh `rollover.sql`) generik lintas 7 tabel & idempotent, tapi ketemu 1 kompleksitas nyata pas diverifikasi thd Postgres 16 lokal: Postgres nolak `ATTACH PARTITION` range baru kalau `DEFAULT` masih py row yg match range itu ("would be violated by some row") — jadi row-nya harus dipindah keluar DEFAULT dulu (`DELETE ... RETURNING` via CTE data-modifying, insert ke tabel standalone, baru `ATTACH`), bukan sesudah. Bug ke-2 ketemu pas testing: `price_basis.basis`/`basis_pct` (GENERATED ALWAYS) bikin `INSERT ... SELECT *` gagal ("cannot insert a non-DEFAULT value into column") — fix pakai column-list eksplisit dari `information_schema.columns` yg exclude `is_generated = 'ALWAYS'`, dipakai di upgrade DAN downgrade. Diverifikasi penuh upgrade→downgrade→upgrade thd Postgres 16 lokal beneran (bukan cuma baca kode): PK/FK/generated-column semua kepreserve benar stlh split, row ke-routing ke bulan yg tepat, `rollover.sql` terbukti bikin partisi baru beneran (bukan cuma no-op) pas dites manual utk bulan yg blm ada.

**Fallback chain (Fase 1 B.9/B.11) sekarang ada, scope: retry funding_rate+ohlcv doang** (bukan ingestion `liquidation_event` baru — itu br diputuskan scope beda krn primary-nya sendiri blm ada, di-skip dulu). `apps/products/trading/ingestion/connectors/cex/native_fallback.py`: ccxt selalu dicoba dulu tiap run, cuma kalau venue+data_type udah gagal 3x berturut-turut (`data_source_health.consecutive_failures` yg emang udah ada, gak perlu migration baru) baru kegagalan berikutnya jg nyoba REST native Binance/Bybit langsung sblm nyerah. Hyperliquid sengaja gak py fallback — connector ccxt-nya udah manggil `api.hyperliquid.xyz` langsung tanpa layer SDK terpisah (ketauan pas nambah Hyperliquid), jadi gak ada "native path" lain yg beda. Diverifikasi end-to-end via mocked ccxt + Postgres lokal: kegagalan di bawah threshold gak trigger fallback, kegagalan ke-4 trigger fallback & berhasil (row yg ke-tulis cocok data fallback, health pulih), skenario dua-duanya gagal tetap gagal bersih, skenario Hyperliquid (gak py fallback) gak crash. **Field-shape response Binance/Bybit di `native_fallback.py` didasarkan dokumentasi API publik, belum dites ke jaringan asli** (sandbox ini diblokir ke exchange, sama pola spt Bybit di connector utama) — 1 verifikasi gak sengaja: skenario ohlcv-tanpa-mock beneran nembak `fapi.binance.com` sungguhan & dapet `451` (diblokir, bukan mock), bukti wiring-nya nembak endpoint asli.

**Gap yg masih ada:**
- pgvector setup (C.1) — belum di-implement.
- RLS pakai `FORCE ROW LEVEL SECURITY` + session variable krn belum ada role app terpisah (least-privilege, non-owner) — dedicated app role yg beneran non-owner adalah hardening lanjutan yg belum dikerjakan.
- `api-gateway`: auth middleware & plan-gating sudah ada, tapi endpoint bisnis nyata belum ditulis (`/trading/auto-execute/status` masih placeholder).
- **Custom domain `kinetiq.app` di-skip dulu untuk fokus MVP** (keputusan user) — `api-gateway` production dipakai lewat domain default Railway (`kinetiq-id.up.railway.app`), bukan custom domain. Riset DNS/CNAME+TXT setup di atas tetap valid & dipakai nanti begitu domain custom mau diaktifkan lagi, bukan dibuang.
- **XIDR/StraitsX**: belum di-apply/didaftarkan oleh user — actionable items di atas. Sampai ini beres, `POST /billing/subscribe` cuma stopgap self-service (tanpa validasi pembayaran), bukan integrasi asli.
- `apps/products/trading/*` masih skeleton README-only utk `strategy-engine`, `agent-orchestrator`, `execution`, `telegram-bot`, `dashboard`, `inngest-functions` — belum ada kode aplikasi nyata. Cuma `ingestion` (connector Binance/Bybit/Hyperliquid CCXT di atas) yg udah py kode sungguhan & terverifikasi hidup (Binance, Hyperliquid) atau siap-tapi-belum-dites-jaringan-asli (Bybit, native fallback Binance/Bybit) sejauh ini.
- **Fase 1 (B.9) sekarang lengkap** dari sisi data-layer: 3 venue (Binance, Bybit, Hyperliquid), fallback chain (funding_rate/ohlcv doang), partitioning otomatis. Native fallback utk liquidation feed (B.11) msh nunggu `liquidation_event` ingestion primary ditulis dulu — itu bukan "fallback", itu ingestion baru dari nol.
- Native fallback Binance/Bybit (`native_fallback.py`) blm dites via jaringan asli (field-shape didasarkan dokumentasi API publik doang) — beda dgn Hyperliquid connector utama yg SUDAH terverifikasi jaringan asli (lihat di atas).

---

## PART A — Product (PRD)

### A.1 Ulasan Jujur atas Pendekatan Trading User (gap & cara bot menutupinya)

Ini bagian yang diminta eksplisit ("rekomendasi terbaik untuk menutupi kekurangan saya") — disampaikan apa adanya:

| Gap yang teridentifikasi | Risiko | Cara platform ini menutupinya |
|---|---|---|
| Hasil ($30→$1000, $1000→$10.000) dicapai dengan **high leverage** pada **sample kecil** — belum tentu edge statistik terbukti, bisa jadi varians tinggi yang kebetulan searah | Leverage tinggi = symmetric: bisa 30x profit secepat itu, bisa juga liquidated secepat itu. Tanpa disiplin sizing, satu bad streak bisa habis semua | `risk_mandate` (max_leverage, max_daily_loss, max_drawdown) + liquidation-buffer constraint di optimizer — **wajib**, tidak bisa di-bypass agent (Section B.7) |
| Fib retracement + Gann Fan itu **diskresioner/subjektif** ("waktu relatif, beda tiap orang" — kata user sendiri) | Tidak bisa di-backtest atau diotomasi kalau aturan tidak presisi; rawan confirmation bias (hanya ingat win, lupa loss) | Formalisasi jadi algoritma deterministik: auto swing-detection, Gann angle projection presisi, multi-timeframe confluence **scoring** (lihat B.6) — lalu **wajib backtest walk-forward** sebelum live (sudah ada di verification plan) |
| Reliance pada **satu metode, satu asset class** (perp saja) | Konsentrasi risiko — kalau metode Fib+Gann sedang tidak match kondisi pasar, tidak ada diversifikasi | Multi-agent (spot + perp, lalu meme + DLMM) dengan basis matematis berbeda (Markowitz portfolio math vs TA timing vs LP-fee math) — saling melengkapi, bukan taruhan pada satu edge |
| Observasi "altseason belum terbentuk" itu benar secara makro tapi **kalau di-hardcode ke strategi, jadi bias yang stale** begitu regime berubah | Overfitting ke kondisi cycle saat ini | Market-regime skill (BTC dominance, altseason index) dihitung **live**, bukan asumsi tetap — jadi otomatis adaptif kalau altseason mulai terbentuk |
| Pivot ke SaaS: user + tim (mungkin solo) akan pegang **uang/keputusan trading orang lain** | Liability & regulasi (investment advice, custodian) | Non-custodial by design (dikonfirmasi user) + ToS eksplisit "not financial advice, user mengontrol dana sendiri" — **wajib legal review sebelum publish**, saya bukan pengganti nasihat hukum |

### A.2 Target Pengguna & Kompetitor

- **Target**: trader crypto retail-to-semi-pro yang trading perp/spot aktif tapi tidak punya waktu/skill koding untuk sistemasi strategi mereka; juga trader yang mau eksposur ke meme-coin baru & DLMM tanpa monitor manual 24/7.
- **Kompetitor tidak langsung**: Vibe-Trading (open-source, riset-first, bukan SaaS/bukan fokus derivatives), 3Commas/Bitsgap (SaaS bot trading spot/futures mapan, non-custodial API-key model — pola bisnis paling mirip dgn yang kita mau tiru), Maestro/BananaGun/Photon (Telegram-based meme-sniper bot, model fee-per-trade), Meteora/DeFi LP management tools (untuk DLMM).
- **Diferensiasi**: kombinasi AI-agent (LangGraph) + data derivatif lengkap + strategy math (Markowitz-extended) + TA-timing overlay (Fib+Gann) dalam satu platform multi-asset — kompetitor di atas biasanya cuma cover satu domain.

### A.3 Model Bisnis (dikonfirmasi)

- **Non-custodial subscription SaaS**. User connect API key exchange (trade-only, no-withdraw) atau agent-wallet (DEX). Kita tidak pernah pegang dana.
- **Dua tier**:
  - **Signal tier** (lebih murah, liability rendah): alert via Telegram + dashboard — rebalance proposal, entry-timing signal (Fib+Gann confluence), risk warning (liquidation/funding spike) — user eksekusi manual.
  - **Auto-execute tier** (premium): platform submit order langsung via API key/wallet user, full risk-gate + kill-switch enforcement.
- **Akun superadmin (founder/personal use)**: role `superadmin` (bukan sekadar admin) yang bypass billing/plan-gating dan pakai resource/API-key/LLM budget milik founder sendiri — dipakai user utk pemakaian pribadi sejak hari pertama tanpa perlu berlangganan produk sendiri. Saat pelanggan baru subscribe & bayar via Midtrans (lihat B.16), akun `tenant` baru otomatis ter-provision dgn plan sesuai pembayaran — alur self-serve, tidak perlu setup manual (lihat B.13).
- Harga & billing engine: Midtrans recurring/subscription payment, plan gating di level API (`packages/config` + middleware `apps/platform-core/api-gateway/deps.py`), usage metering per tenant (jumlah agent aktif, jumlah exchange terhubung) untuk tier-based limit.
- **Legal workstream (di luar scope teknis, wajib sebelum go-live)**: ToS/disclaimer "not financial advice", data privacy (API key encryption at rest sudah didesain), cek regulasi per-yurisdiksi target (banyak negara mengatur "trading bot" atau "signal service" berbeda dari investment advisory selama non-custodial & user execute sendiri keputusan — tapi ini butuh review hukum aktual, bukan asumsi saya).

### A.4 Cakupan Fitur per Fase (product view — detail teknis di Part B.9)

| Fase | Fitur produk |
|---|---|
| MVP | **Sudah berbentuk bisnis penuh sejak awal**: web app minimal (signup/login, subscribe & bayar via Midtrans, superadmin & admin panel) + Telegram signal-tier + Perp & Spot agent + paper trading + Fib+Gann timing overlay + Markowitz-extended portfolio suggestion + agent belajar penuh dari gaya trading founder (lihat B.6b) |
| V1 | Auto-execute tier (perp+spot live), billing/subscription aktif, web dashboard basic |
| V2 | Meme-sniper agent (module baru) sbg add-on tier terpisah (risiko lebih tinggi, harga berbeda) |
| V3 | DLMM agent (module baru), mobile app |
| V4+ (eksplorasi, belum komitmen) | Tokenized equity (leverage koneksi ke broker existing pola Vibe-Trading: Alpaca dsb), prediction market (Polymarket-style, orderbook mirip binary option — cocok dgn arsitektur data existing). NFT & GameDefi **sengaja tidak diprioritaskan** — sifatnya ilikuid/tidak orderbook-driven, tidak cocok dgn pendekatan quant-signal platform ini; bisa direvisit kalau ada demand jelas. |

### A.5 Success Metrics (awal)
- Technical: signal precision (win-rate & expected-value dari Fib+Gann+Markowitz combo di paper trading ≥ 90 hari, sebelum buka auto-execute).
- Business: jumlah signup signal-tier → conversion ke auto-execute tier, churn rate, MRR.

### A.6 Visi Jangka Panjang: Bukan Cuma Trading Bot, tapi Platform Multi-Agent

User ingin bisnis ini nantinya juga punya **agent exam** (mis. bantu belajar/ujian), **agent chatbot**, **agent content creator**, **agent task**, dan agent lain di luar trading. Implikasinya buat rencana ini: **jangan bangun infrastruktur SaaS yang trading-only**, tapi pisahkan jadi dua lapis sejak hari pertama:

1. **Platform Core** (agent-agnostic): tenant/auth, billing/subscription, agent-registry (daftar "produk agent" apa saja yang tersedia per tenant), LLM gateway (satu titik abstraksi provider LLM + cost tracking lintas semua agent, bukan cuma trading), observability (Langfuse), notification (Telegram/email) — ini semua **tidak spesifik ke trading**, jadi bisa dipakai ulang persis sama saat nanti bikin agent exam/chatbot/content-creator.
2. **Product Vertical** (spesifik per jenis agent): trading (perp/spot/meme/dlmm) adalah **vertical pertama**, dibangun sekarang. Agent exam/chatbot/content-creator/task jadi vertical berikutnya — **tidak dirancang detail sekarang** (belum ada requirement jelas), tapi Platform Core dijaga generik supaya nambah vertical baru = nambah modul baru, bukan rombak ulang auth/billing/tenant yang sudah jalan.

Praktiknya: `tenant.plan_tier` dan billing di-desain per **product+tier** (mis. `trading:auto_execute`, `exam:pro` nanti), bukan hardcode ke satu domain trading — lihat perubahan struktur direktori & skema di B.2/B.3.

Ini prinsip "generalize the boring 20%, spesialisasi yang 80% karakteristik produk" — jangan over-engineer detail agent exam/chatbot sekarang karena requirement-nya belum ada, cukup pastikan pondasinya tidak mengunci ke trading doang.

---

## PART B — Technical Architecture

### B.1 Keputusan Arsitektur Kunci

| Area | Keputusan | Alasan |
|---|---|---|
| Compute | Railway (multi-service, multi-tenant aware) | fixed constraint user |
| DB utama | Neon Postgres (serverless, branching) | fixed constraint user |
| Multi-tenancy | Row-level: `tenant_id`/`account_id` di semua tabel domain (bukan DB-per-tenant — terlalu mahal di Neon utk skala awal), Postgres RLS policy per tenant sbg defense-in-depth | pola standar SaaS row-level multi-tenant, biaya lebih rendah drpd DB terpisah per user |
| Auth & Billing | Auth: Clerk (key sudah di-setup di Railway). Billing: **dual-provider Midtrans (fiat IDR) + XIDR/StraitsX (stablecoin regulated, IDRX sbg backup)** utk MVP, arsitektur `payment_provider` dinamis/pluggable — lihat B.16 | **Revisi ke-3** (Stripe→Paddle→Midtrans+IDRX→Midtrans+XIDR): krn target pasar sementara Indonesia & bisnis belum berbadan hukum (belum PT/CV), Xendit **tidak bisa dipakai dulu** (wajib legal entity). Midtrans jadi jalur utama pelanggan (verifikasi KTP, 1-3 hari), XIDR/StraitsX dipilih drpd IDRX krn lebih regulated & tetap terima tipe "Sole Trader" (KTP+NPWP, tanpa PT) — detail lengkap di B.16 |
| Platform Core vs Product Vertical | Pisahkan `apps/platform-core/*` (tenant, auth, billing, agent-registry, LLM gateway, notification — agent-agnostic) dari `apps/products/trading/*` (spesifik trading) | visi bisnis user: trading = vertical pertama, agent exam/chatbot/content-creator/task menyusul sbg vertical baru yang reuse Platform Core (lihat A.6) |
| Time-series | Native Postgres range-partitioning by time (manual, dikelola Inngest) + TimescaleDB (Apache-2, tanpa compression) opsional | Neon dukung timescaledb sejak PG18 (Feb 2026) tapi tanpa compression/tiering — partitioning manual jadi primary bet (terverifikasi) |
| Orchestration | **Inngest self-hosted di Railway** | self-hosting resmi sejak Inngest 1.0 (terverifikasi), event-driven step function pas utk pola ingest→trigger; dievaluasi vs Trigger.dev/Temporal Cloud/custom-queue-di-Neon dan ditolak (lihat plan versi sebelumnya utk detail — Neon PgBouncer transaction-mode tidak support LISTEN/NOTIFY) |
| LLM Observability | **Langfuse Cloud** (bukan self-host) utk MVP | self-host Langfuse butuh 6 container, beban ops besar drpd benefit di tahap ini |
| CEX data/exec | CCXT + CCXT Pro (WS) unified, native WS fallback per exchange utk liquidation feed | 100+ exchange, minim maintenance |
| DEX data/exec | Native SDK per protokol: Hyperliquid, dYdX v4, GMX, Vertex, Drift (perp); Meteora DLMM SDK (LP); Solana/EVM new-pair listener (meme-sniper) | tidak ada unifikasi matang utk on-chain |
| Backend | Python 3.11+ (FastAPI, LangGraph) utk data layer, strategy engine, agent orchestration | ekosistem quant/ML, ikut pola Vibe-Trading |
| Job glue & frontend | TypeScript: Inngest functions + Next.js dashboard (+ shadcn/ui, lihat B.14) + billing webhook handler | konsisten dgn pola Vibe-Trading |
| Interface MVP | Telegram bot (Python, signal tier) — **hybrid conversational** (natural language utk monitoring, structured confirm/tombol wajib utk aksi nyata) | latency rendah, effort kecil, akses darimana saja; conversational krn positioning "agent" bukan "bot command" (lihat B.14) |
| Interface lanjutan | Web dashboard (Next.js + shadcn/ui, + billing/plan management) → Mobile app | dashboard utk riset/backtest visual + subscription management |
| UI/UX & Branding | shadcn/ui + Tailwind (bukan fase desain Figma terpisah), branding minimal bertema "kinetic" dulu | prioritas kecepatan solo-founder ke MVP drpd investasi desain penuh di awal (lihat B.14) |
| Custody | Non-custodial per-tenant: API key trade-only/no-withdraw (CEX), agent-wallet/session-key (DEX), envelope encryption per-tenant (data key unik per tenant, master key di KMS/Railway secret) | dikonfirmasi user; isolasi per-tenant mencegah satu key bocor berdampak ke tenant lain |
| LLM Provider | **OpenRouter** sbg provider utama (satu API key, akses banyak model/vendor sekaligus) diakses lewat `platform-core/llm-gateway`, dgn adapter interface tetap provider-agnostic (bisa tambah direct OpenAI/Anthropic/DeepSeek API key nanti tanpa ubah kontrak) | dikonfirmasi user (paket all-in-one OpenRouter), plus jaga fleksibilitas kalau nanti mau direct API utk model tertentu (lebih murah/cepat) |
| Role & Access | 3 level: **superadmin** (founder, bypass billing, pakai resource sendiri, kontrol penuh konfigurasi platform) — **admin** (mengatur LLM/model per agent & per tier, feature flag, monitoring — bisa didelegasikan ke tim nanti) — **tenant/customer** (subscriber biasa, akses sesuai plan yg dibayar) | wajib disebut eksplisit oleh user; jadi dasar `llm_config` dinamis per agent (lihat B.13) |

### B.2 Struktur Direktori (Platform Core generik + Trading sbg product vertical pertama)

```
agent-trading-perp/
├── apps/
│   ├── platform-core/               # AGENT-AGNOSTIC — reusable utk vertical apapun (trading, exam, chatbot, dst)
│   │   ├── api-gateway/             # FastAPI: tenant auth middleware, product+tier plan-gating, routing ke tiap product API
│   │   ├── billing/                 # dual-provider: providers/{midtrans.py, idrx.py, xendit.py, paddle.py} adapter tipis + sync_tenant_plan() inti, subscription state sync -> Neon (per product+tier, lihat B.16)
│   │   ├── agent-registry/          # daftar product/vertical aktif per tenant, feature flag per tier
│   │   ├── llm-gateway/             # satu titik abstraksi provider LLM (OpenAI/Anthropic/DeepSeek/dst) + cost tracking lintas semua vertical
│   │   ├── notification/            # Telegram/email adapter generik, dipakai semua vertical
│   │   └── dashboard-shell/         # Next.js shell: login, billing/plan management, product switcher
│   │
│   └── products/
│       └── trading/                 # VERTICAL PERTAMA (fokus rencana ini)
│           ├── ingestion/
│           │   └── connectors/
│           │       ├── cex/                # ccxt_ws, binance_native, bybit_native, okx_native
│           │       ├── dex-perp/           # hyperliquid, dydx_v4, gmx_subgraph, vertex, drift
│           │       ├── dex-lp/             # meteora_dlmm.py (pool/bin/fee data)
│           │       └── new-pair-listener/  # solana (pump.fun/raydium) & evm (PairCreated events) utk meme-sniper
│           ├── agent-orchestrator/         # LangGraph, pakai llm-gateway dari platform-core
│           │   ├── graphs/
│           │   │   ├── portfolio_rebalance_graph.py   # perp+spot (Markowitz-extended)
│           │   │   ├── meme_snipe_graph.py            # V2
│           │   │   ├── dlmm_manage_graph.py           # V3
│           │   │   └── risk_review_graph.py
│           │   └── skills/
│           │       ├── data/            # funding_rate, open_interest, basis, liq_feed, ls_ratio, market_regime
│           │       ├── strategy/        # markowitz_perp, markowitz_spot, risk_parity, fib_gann_timing
│           │       ├── risk/            # liquidation_distance, leverage_sizing, drawdown_halt, token_safety_score
│           │       └── execution/
│           ├── strategy-engine/
│           │   └── optimizers/{markowitz_perp.py, markowitz_spot.py, risk_parity.py, constraints.py}
│           ├── execution/                  # unified order/position adapter + risk_gate.py + custody/ (per-tenant key vault)
│           ├── inngest-functions/          # ingest-*, rebalance-check, risk-halt-monitor, new-pair-watchdog, dlmm-rebalance-check
│           ├── dashboard/                  # Next.js: positions, strategies (mount di dashboard-shell sbg product page)
│           └── telegram-bot/               # Python (python-telegram-bot) — MVP interface, hybrid conversational + structured confirm utk aksi nyata (lihat B.14)
│
├── packages/
│   ├── schemas/                    # Pydantic + Zod
│   ├── db/                         # SQLAlchemy models + Alembic (tenant_id + product_key di semua tabel domain)
│   └── config/                     # plan-tier config (feature flags per product+tier)
├── infra/{railway/, neon/, docker-compose.local.yml}
├── docs/{architecture.md, data-model.md, security-guardrails.md, prd.md, adr/}
└── .github/workflows/
```

Catatan: vertical baru (agent exam/chatbot/content-creator/task) nanti masuk sbg folder baru di `apps/products/<nama-vertical>/`, reuse seluruh `apps/platform-core/*` tanpa perubahan — ini yang dimaksud "persiapan" di A.6.

### B.3 Data Model — Tambahan untuk Multi-Tenant & Multi-Agent

Semua tabel domain existing (Section sebelumnya: `strategy`, `portfolio_target`, `position`, `order_audit_log`, `risk_mandate`) **ditambah kolom `tenant_id`** + index composite `(tenant_id, ...)`. Tabel baru:

```sql
CREATE TABLE tenant (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE NOT NULL,
    plan_tier TEXT NOT NULL DEFAULT 'signal_only',   -- 'signal_only','auto_execute','meme_addon','dlmm_addon'
    payment_provider TEXT,                            -- 'midtrans' (MVP), 'xendit'/'paddle' (fase lanjutan) -- provider-agnostic, lihat B.16
    payment_customer_id TEXT,
    payment_subscription_status TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE tenant_credential (           -- envelope-encrypted per-tenant API key/wallet
    id BIGSERIAL PRIMARY KEY,
    tenant_id UUID REFERENCES tenant(id),
    venue_id SMALLINT REFERENCES venue(id),
    credential_type TEXT NOT NULL,          -- 'api_key_trade_only','agent_wallet'
    encrypted_payload BYTEA NOT NULL,
    data_key_encrypted BYTEA NOT NULL,      -- envelope encryption: data key wrapped by master KMS key
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Meme-sniper specific
CREATE TABLE token_launch_event (
    id BIGSERIAL PRIMARY KEY,
    chain TEXT NOT NULL,                    -- 'solana','ethereum','base',...
    token_address TEXT NOT NULL,
    pair_address TEXT,
    detected_at TIMESTAMPTZ NOT NULL,
    initial_liquidity_usd NUMERIC(24,4),
    safety_score NUMERIC(5,2),              -- 0-100, dari token_safety_score skill
    safety_flags JSONB                      -- {"liquidity_locked": true, "mint_renounced": false, ...}
);

-- DLMM specific
CREATE TABLE dlmm_position (
    id BIGSERIAL PRIMARY KEY,
    tenant_id UUID REFERENCES tenant(id),
    pool_address TEXT NOT NULL,
    lower_bin INT, upper_bin INT,
    liquidity_usd NUMERIC(24,4),
    fees_earned_usd NUMERIC(24,4) DEFAULT 0,
    impermanent_loss_usd NUMERIC(24,4) DEFAULT 0,
    opened_at TIMESTAMPTZ, closed_at TIMESTAMPTZ
);
```

### B.4 Row-Level Isolation
Postgres RLS policy `USING (tenant_id = current_setting('app.tenant_id')::uuid)` di semua tabel domain, di-set per-request oleh `apps/api/deps.py` — defense-in-depth di luar filtering di level ORM (kalau ada bug query lupa filter tenant, RLS tetap block).

### B.5 Strategy Engine — Perp & Spot (Markowitz-extended)
Sama seperti rencana sebelumnya (funding-carry, basis, momentum component; leverage/liquidation-buffer/funding-cost/concentration/correlation constraint; risk-parity sbg alternatif). **Tambahan utk Spot**: `markowitz_spot.py` = versi tanpa leverage/liquidation constraint (klasik Markowitz murni + funding-carry component dihilangkan karena spot tidak ada funding) — reuse >80% kode dari `markowitz_perp.py` via shared base class `PortfolioOptimizerBase`.

### B.6 Skill Baru — Fib + Gann Timing & Market Regime (dari pengalaman trading user)

**`skills/strategy/fib_gann_timing.py`** — formalisasi metode user jadi deterministik:
- Auto swing-detection (pivot high/low algorithmic, mis. fractal/zigzag dgn parameter lookback per timeframe) → hitung Fibonacci retracement/extension level dari swing terakhir.
- Gann Fan: proyeksi angle (1x1, 1x2, 2x1, dst) dari pivot yang sama, dihitung dgn price-per-time-unit ratio yang dikonfigurasi per instrumen (Gann angle sensitif terhadap skala harga & waktu, jadi tidak bisa satu setting global — catat sbg parameter per-instrumen yang di-kalibrasi, bukan hardcode).
- **Multi-timeframe confluence score**: agregasi sinyal dari weekly/daily/4h/1h — skor tinggi kalau level Fib+Gann saling align lintas timeframe (implementasi konkret dari analogi "meta" user: skor tinggi = pattern sedang "buffed"/kuat, skor rendah = "nerfed"/lemah).
- Output: bukan sinyal buy/sell langsung, tapi **entry-timing signal** (skor 0-100 + level harga kunci) yang jadi salah satu input `expected_return_components` di optimizer DAN dipakai `agent-orchestrator` sbg gate tambahan "kapan eksekusi", terpisah dari "berapa alokasi" (keputusan Markowitz).

**`skills/data/market_regime.py`**:
- BTC dominance & altseason index (mis. via CoinGecko/CMC API) — dipakai sbg bias makro live (bukan hardcode "altseason belum terbentuk", tapi dihitung ulang tiap hari).
- Seasonality stats (return distribution per hari-dlm-minggu / minggu-dlm-bulan dari data historis) — cross-timeframe correlation matrix antar timeframe utk instrumen yang sama.
- Feed sbg context tambahan ke `portfolio_rebalance_graph` node `ground`, bukan strategi berdiri sendiri.

### B.6b Trader Profile / "Meta Model" — Agent Belajar Gaya Trading (MVP: profil founder)

User mau agent "punya memory latihan yang berkembang" dan **untuk MVP meniru penuh gaya trading founder** supaya ada kesamaan visi antara analisis manual founder dan keputusan agent, sekaligus agent jadi asisten yang membantu menyempurnakan strateginya sendiri. Ini persis pola **Shadow Account** yang sudah ada di Vibe-Trading (extract trading behavior dari journal → profile keputusan → backtest rule vs actual) — kita adopsi & extend, bukan bikin dari nol:

- **`trader_profile` (MVP, single profile = founder)**: import histori trade founder (export dari Binance/MEXC) + anotasi manual (via web app: tandai swing point mana yg dipakai, level Fib/Gann mana yg dieksekusi, alasan entry/exit) → tabel `trade_annotation` (tenant_id, instrument_id, ts, swing_ref, fib_level, gann_angle, action, rationale_text).
- **Kalibrasi**: parameter `fib_gann_timing` (lookback swing-detection, bobot confluence per timeframe, threshold skor entry) di-fit supaya sinyal algoritmik **paling mendekati** keputusan riil founder di data historis — ukur dgn metrik "agreement rate" (persentase sinyal algoritmik yg match keputusan founder) sbg bagian dari verification plan (B.10).
- **Feedback loop berjalan**: tiap sinyal yg dikirim (Telegram/dashboard), founder confirm/reject/koreksi → tersimpan lagi ke `trade_annotation` → re-kalibrasi periodik (bukan real-time, cukup batch mingguan di awal) — ini mekanisme "belajar pesat" yg dimaksud user, scope-nya dulu **founder-only**.
- **Post-MVP (bukan scope sekarang, sengaja ditunda)**: per-tenant `trader_profile` (tiap pelanggan bisa personalisasi/kalibrasi agent versi mereka sendiri) + agregat lintas-tenant sbg peningkatan "meta-model" bisnis — ini butuh consent/privacy design eksplisit (data trading pelanggan sensitif) sebelum dikerjakan, dicatat sbg **item riset lanjutan**, bukan komitmen teknis di rencana ini.

### B.7 Keamanan & Guardrails (sama seperti sebelumnya + tenant isolation)
Paper/live separation, DB-based kill switch, bounded autonomy via `risk_mandate` (sekarang per `tenant_id`), liquidation protection, append-only audit ledger, non-custodial custody per-tenant (Section B.1/B.3) — **plus untuk meme-sniper**: `token_safety_score` skill sbg mandatory gate sebelum snipe (cek liquidity lock, mint authority renounced, simulasi sell/honeypot check via API pihak ketiga mis. GoPlus Security/Honeypot.is) — token dgn safety_score di bawah threshold otomatis di-skip, tidak peduli seberapa menarik momentum-nya.

### B.8 Orchestration Flow Tambahan

```
[meme-sniper] new-pair-listener (WS/RPC log subscription per chain)
  -> event "token.launched" -> Inngest fn `evaluate-new-token`
     -> token_safety_score skill (paralel: liquidity check, mint check, honeypot sim)
     -> jika lolos threshold -> event "token.snipe_candidate" -> notify (signal tier) ATAU auto-buy (auto-execute tier, size kecil sesuai risk_mandate khusus meme)

[dlmm] Inngest cron per pool aktif
  -> ambil current price & bin distribution -> hitung fee APR vs IL -> jika price keluar dari [lower_bin, upper_bin] -> trigger rebalance-range function
```

### B.9 Roadmap Fase (Revisi Final — web app & bentuk bisnis masuk dari MVP)

0. **Bootstrap + Platform Core minimal** (2-3 minggu): monorepo, CI, Railway+Neon, migration awal (termasuk `tenant`/RLS/`role`/`llm_config` dari hari pertama), Inngest self-host, Langfuse Cloud, **web app minimal** (auth via Clerk, halaman signup, checkout Midtrans+XIDR, superadmin+admin panel dasar termasuk konfigurasi LLM per agent — lihat B.13), akun superadmin founder dibuat manual sbg langkah setup pertama. **Fork & adaptasi dari Vibe-Trading (MIT license, dikonfirmasi — lihat catatan riset)**: pola `mcp_server.py` (FastMCP decorator + lazy singleton registry) utk `apps/platform-core/mcp-server/`, dan layered broker-connector abstraction (Profiles→Service→Types + mandate/kill-switch endpoint) utk `apps/products/trading/execution/`.
1. **MVP Data Layer** (2-3 minggu, bisa paralel dgn fase 0 bagian akhir): 2 CEX (Binance, Bybit) + 1 DEX perp (Hyperliquid) connector, fallback chain, partitioning otomatis. CoinGlass Hobbyist dipakai sbg sumber tambahan (internal/founder-only, lihat B.11).
2. **Strategy & Paper Trading + Trader Profile** (3-4 minggu): `markowitz_perp` + `markowitz_spot` + `risk_parity` + **`fib_gann_timing`** + **`market_regime`** + **`trader_profile`/anotasi founder (B.6b)**, backtest funding-aware, LangGraph rebalance graph (paper only), risk gate. **Fork pipeline Shadow Account Vibe-Trading** (`/agent/src/shadow_account/`: journal parse → extract behavior → generate rule → `run_shadow_backtest()` → persist/report) sbg skeleton `trader_profile`, adaptasi rule-extraction dari RSI+prior-return (equities-style) ke Fib-level+Gann-angle (crypto-perp style Anda).
3. **Signal Tier Launch** (1-2 minggu, paralel fase 2): Telegram bot signal-only terhubung ke tenant yg sudah subscribe via web app fase 0 — **first revenue milestone** (founder sendiri jadi user pertama via akun superadmin, tanpa perlu bayar). **Sebelum fase ini live ke pelanggan bayar: upgrade CoinGlass Hobbyist → Standard ($299/bln)** — wajib krn Hobbyist personal-use-only (lihat B.11/B.12).
4. **Auto-Execute Tier** (2-3 minggu): execution live perp+spot (testnet→mainnet notional kecil), per-tenant custody, kill switch battle-tested dari paper, billing gate utk tier ini.
5. **Web Dashboard Lengkap** (2-3 minggu): Next.js — positions, equity curve, trade-annotation UI (utk B.6b), plan/billing management self-serve penuh.
6. **Meme-Sniper Module (V2)** (3-4 minggu): new-pair listener (Solana + 1 EVM chain), token_safety_score, snipe execution, add-on tier terpisah, **agent-registry** tinggal daftarkan module baru (bukti "kemudahan tambah agent baru" dari A.6/B.13).
7. **DLMM Module (V3)** (3-4 minggu): Meteora integration, IL/fee tracking, auto-rebalance range.
8. **Ekspansi (ongoing/eksplorasi)**: exchange/DEX lain, mobile app, tokenized equity (reuse pola broker-connector Vibe-Trading, mis. Alpaca), prediction market, vertical non-trading (agent exam/chatbot/content-creator/task — tinggal tambah `apps/products/<vertical>/` baru, reuse Platform Core). NFT/GameDefi tidak masuk roadmap kecuali ada validasi demand baru.

### B.10 Verification Plan (tambahan dari rencana sebelumnya)
Semua poin verification sebelumnya (unit test connector, fallback chain, strategy backtest, risk gate, kill switch drill, Inngest retry test, Langfuse trace, **paper/live boundary test — kritis**, load/latency, disaster recovery) **tetap berlaku**, ditambah:

12. **Tenant isolation test**: 2 tenant dummy, assert query salah satu tenant tidak pernah mengembalikan row tenant lain (test RLS langsung, bukan cuma via ORM).
13. **Billing/plan-gating test**: assert user di plan `signal_only` tidak bisa hit endpoint auto-execute (403), assert notification/webhook Midtrans downgrade plan langsung mematikan akses fitur terkait dalam SLA singkat.
14. **Fib+Gann backtest validation**: bandingkan sinyal algoritmik vs anotasi manual user pada sample chart historis (sanity check bahwa formalisasi merepresentasikan metode aslinya), lalu walk-forward test independen ≥ 90 hari sebelum dipakai live.
15. **Token safety gate test**: fixture token dgn kombinasi flag (liquidity unlocked, mint not renounced, honeypot simulasi gagal) → assert snipe di-block di setiap kasus, tidak ada bypass.

### B.11 Rekomendasi Sumber Data Derivatif (harga vs kelengkapan vs kecepatan)

Sudah diverifikasi via riset terkini (bukan asumsi lama): **CCXT Pro sudah digabung jadi bagian gratis CCXT sejak versi 1.95+** (WebSocket untuk 100+ exchange, termasuk funding rate/OI/orderbook, tanpa biaya lisensi terpisah) — jadi biaya data CEX inti tetap $0 di luar compute.

| Sumber | Cakupan | Harga | Kelengkapan | Kecepatan/Infra | Rekomendasi peran |
|---|---|---|---|---|---|
| **CCXT (+ built-in WS)** | 100+ CEX: funding rate, OI, orderbook, trades | Gratis (open-source) | Tinggi utk CEX, tidak cover DEX/on-chain | WS native per-exchange, cukup cepat, tapi kualitas antar-exchange tidak seragam | **Primary source CEX** (sudah di rencana) |
| **Native exchange WS/REST** (Binance, Bybit, OKX) | Fallback per-exchange, termasuk liquidation stream yg tidak selalu ada di CCXT | Gratis | Tinggi (data langsung dari sumber) | Tercepat (tanpa layer abstraksi), tapi maintenance per-exchange lebih besar | **Fallback wajib** utk liquidation feed & data yg CCXT belum cover |
| **Coinalyze API** | Funding rate, OI, liquidation, long/short ratio — agregat lintas exchange | Gratis (syarat: cantumkan atribusi sumber) | Bagus utk cross-check/cross-exchange view, tapi retensi intraday terbatas (~1500-2000 datapoint, di-hapus harian) & rate limit 40 req/menit | Cukup cepat utk polling interval menitan, bukan utk real-time tick | **Cross-check/fallback murah** — bagus dipakai di Fase 1-2 sblm ada budget data premium |
| **CoinGlass API** | Funding rate OHLC + OI-weighted/volume-weighted, OI aggregated & per-exchange, liquidation history & heatmap model, long/short ratio (taker + top-trader), **options** (Max Pain, IV lintas Deribit/OKX/Bybit), **ETF flow**, **on-chain** exchange balance/transfer, L2/L3 orderbook tick-level — riset mendalam (Juli 2026) konfirmasi ini paling lengkap di kelas retail-to-pro, skema terunifikasi 30+ exchange (nilai unik vs CCXT: agregasi cross-exchange & metrik turunan yg tidak bisa didapat gratis) | Hobbyist $29/bln, Startup $79/bln, Standard $299/bln, Professional $699/bln (tahunan lebih murah) | **Hobbyist**: 80+ endpoint, **cuma data harian** (tidak ada hourly/15m/1m/tick — itu butuh Startup/Standard). **⚠️ Hobbyist = personal use only per ToS CoinGlass — commercial/SaaS deployment butuh tier Standard ($299/bln) minimum.** `price_basis` (mark/index) tidak disediakan langsung, perlu cross-reference native exchange | Rate limit 30 req/menit (Hobbyist) vs 300 req/menit (Standard); update 1 detik real-time semua tier, ada WebSocket | **Hobbyist dulu utk Fase 0-2** (internal/founder-only: paper trading, riset, kalibrasi trader_profile — masih personal use, compliant) → **wajib upgrade ke Standard $299/bln sebelum Fase 3** (Signal Tier Launch, pelanggan bayar pertama) baik utk kepatuhan ToS maupun dapat data hourly/tick-level yg lebih presisi utk sinyal |
| **CoinGecko / CoinMarketCap API** | BTC dominance, Altcoin Season Index, market cap ranking | Free tier tersedia (CoinGecko Demo/CMC Basic) | Cukup utk kebutuhan `market_regime` skill (bukan tick-level) | Cepat, cache-friendly (data ini tidak perlu real-time) | **Primary source utk market_regime skill** |
| **GoPlus Security API / Honeypot.is** | Token safety check (mint authority, liquidity lock, honeypot simulation) utk meme-sniper | Free tier tersedia, paid tier utk volume tinggi | Cukup utk gate keamanan dasar | Perlu low-latency krn snipe window singkat (detik) — cek keduanya paralel utk redundansi | **Wajib** utk `token_safety_score` skill (Fase 6) |
| **DexScreener / Birdeye API** | New-pair listing, harga real-time multichain (meme-sniper) | DexScreener gratis (rate-limited); Birdeye ada tier berbayar utk kecepatan lebih tinggi | Baik utk deteksi awal | DexScreener cukup utk MVP meme-sniper; Birdeye kalau butuh latency lebih rendah saat scale | **DexScreener dulu (gratis)**, upgrade Birdeye kalau latency jadi bottleneck |

**Prinsip budget data**: kombinasi gratis (CCXT + native WS + Coinalyze + CoinGecko + DexScreener/GoPlus) sudah cukup lengkap secara fungsional. **Karena user sudah menyiapkan budget khusus utk akurasi data**, tetap mulai **CoinGlass tier Hobbyist ($29/bln)** dari **Fase 1 (MVP Data Layer)** — tapi statusnya **internal/founder-only** (paper trading, riset, kalibrasi `trader_profile`), bukan buat melayani pelanggan bayar, karena ToS Hobbyist membatasi ke personal use. **Wajib upgrade ke Standard ($299/bln) sebelum Fase 3** (Signal Tier Launch — pelanggan bayar pertama), bukan cuma soal compliance tapi juga langsung dapat data hourly/tick-level yg lebih presisi utk sinyal (Hobbyist cuma daily-level). Naikkan ke tier Professional kalau nanti volume Fase 6 (meme-sniper) butuh rate limit lebih tinggi dari Standard.

**Data baru dari CoinGlass yang belum masuk skema** (temuan riset, potensi tabel/skill tambahan di fase lanjutan, belum komitmen di MVP): `options_max_pain`/`options_iv_snapshot` (Max Pain & IV lintas Deribit/OKX/Bybit — bisa jadi sinyal tambahan kalau nanti expand ke options), `etf_flow` (BTC/ETH ETF inflow/outflow, konteks makro), `on_chain_exchange_balance`/`on_chain_transfers` (proxy tekanan jual/beli whale). Dicatat sbg item eksplorasi Fase 8+, bukan scope MVP.

### B.12 Rencana Budget Bulanan (estimasi, harga terverifikasi Juli 2026)

| Komponen | MVP (Fase 0-3, low traffic) | Growth (Fase 4-7, live trading + meme-sniper) |
|---|---|---|
| Railway (compute multi-service: api, ingestion, agent-orchestrator, execution, inngest, telegram-bot, dashboard) | Pro plan $20/bln + usage ≈ **$50-100/bln** | Usage naik seiring service & traffic ≈ **$150-400/bln** |
| Neon Postgres | Launch plan usage-based (compute $0.106/CU-hr, storage $0.35/GB-bln, tanpa minimum bulanan) ≈ **$10-30/bln** | Scale plan ($0.222/CU-hr, SLA 99.95%) seiring volume time-series naik ≈ **$100-300/bln** |
| Inngest self-host | Hanya compute (masuk Railway di atas) + optional Redis addon ≈ **$0-15/bln** | sama, naik sedikit seiring service | **$10-30/bln** |
| Langfuse | Hobby (gratis, 50rb unit/bln) ≈ **$0** | Core $29/bln atau Pro $199/bln (kalau butuh retensi lebih lama/compliance) | **$29-199/bln** |
| Data derivatif | CCXT + native WS + Coinalyze + CoinGecko (gratis) **+ CoinGlass Hobbyist** (internal/founder-only, Fase 0-2) ≈ **$29/bln** | **Wajib naik ke CoinGlass Standard sebelum Fase 3** (Hobbyist personal-use-only per ToS, tidak boleh dipakai layani pelanggan bayar — lihat B.11) ≈ **$299/bln**, naik ke Professional kalau volume Fase 6 (meme-sniper) butuh rate limit lebih tinggi |
| Auth (Clerk) | Free tier ≈ **$0** | Paid tier seiring MAU naik ≈ **$25-100/bln** |
| KMS (envelope encryption master key) | ≈ **$1-5/bln** | ≈ **$5-15/bln** |
| Midtrans (via Midtrans GO/WhatsApp Onboarding, gantikan Paddle krn target market Indonesia — lihat Section B.16) | Tanpa biaya bulanan/setup, cuma biaya per transaksi sukses (persis kisaran, perlu cek tabel harga resmi Midtrans saat integrasi) | sama, mungkin migrasi ke skema Xendit/Midtrans tier lebih tinggi begitu PT/CV resmi (scales with revenue) |
| Domain/SSL | ≈ **$1/bln** (tahunan) | sama |
| LLM API (via OpenRouter — model murah/cepat utk task rutin, model lebih mahal khusus keputusan strategi) | **$20-50/bln** (volume rendah, testing/founder-only) | **$200-1000+/bln** — **variable cost terbesar**, tergantung jumlah tenant aktif & frekuensi agent invocation |
| **Total estimasi** | **≈ $115-230/bln** | **≈ $870-2420+/bln** (naik ~$270/bln dari revisi CoinGlass Standard sblm Fase 3; tetap didominasi LLM usage saat tenant bertambah) |

Catatan penting: LLM API adalah biaya variabel terbesar begitu ada trafik nyata — mitigasi: gunakan `llm_config` dinamis (B.13) supaya admin bisa assign model murah/cepat via OpenRouter (mis. kelas Haiku/DeepSeek) utk task rutin (data-check, formatting), reserve model premium hanya utk keputusan strategi kompleks; dan pastikan harga subscription tier menutup margin di atas estimasi LLM cost per tenant (butuh perhitungan unit economics setelah ada data pemakaian nyata, bukan asumsi di tahap plan).

### B.13 Role-Based Access & Konfigurasi LLM Dinamis per Agent

**Role** (`packages/db` tabel `platform_user` dgn kolom `role`):
- **superadmin**: founder/pemilik platform. Bypass billing & plan-gating, resource/API-key/LLM budget sendiri, akses penuh ke seluruh admin panel & data lintas tenant (utk keperluan operasional/dukungan, tetap tercatat di audit log).
- **admin**: dikonfigurasi utk mengatur `llm_config` (model per agent/skill), monitoring biaya LLM lintas tenant, feature flag per tier — role ini bisa didelegasikan ke tim di masa depan tanpa kasih akses superadmin penuh.
- **tenant/customer**: user subscriber biasa, akses dibatasi sesuai `tenant.plan_tier`.

**Konfigurasi LLM dinamis** (`llm_config` table, resolve hierarchy: tenant override → product default → global default):

```sql
CREATE TABLE llm_config (
    id SERIAL PRIMARY KEY,
    scope TEXT NOT NULL CHECK (scope IN ('global','product','tenant')),
    tenant_id UUID REFERENCES tenant(id),          -- NULL kalau scope != 'tenant'
    product_key TEXT,                              -- 'trading', NULL kalau scope = 'global'
    agent_skill_key TEXT NOT NULL,                 -- 'fib_gann_timing','portfolio_rebalance','market_regime', dst
    provider TEXT NOT NULL DEFAULT 'openrouter',   -- provider-agnostic, default OpenRouter
    model TEXT NOT NULL,                           -- mis. 'anthropic/claude-sonnet-5', 'deepseek/deepseek-v4' (format model-id OpenRouter)
    params JSONB,                                  -- temperature, max_tokens, dst
    updated_by UUID REFERENCES platform_user(id),
    updated_at TIMESTAMPTZ DEFAULT now()
);
```

`platform-core/llm-gateway` resolve config ini di runtime tiap kali agent-orchestrator memanggil skill — jadi admin bisa ganti model utk skill tertentu (mis. turunkan biaya `market_regime` pakai model murah, tapi `portfolio_rebalance` tetap model kuat) tanpa deploy ulang kode, cukup lewat admin panel di `dashboard-shell`. Karena provider utama OpenRouter (satu API key, banyak model), ganti `model` field saja cukup — tidak perlu urus API key berbeda per provider di tahap awal.

### B.14 UI/UX, Branding, Tech Stack Konsolidasi, & Conversational Interface Telegram

**UI/UX & Branding** — sebelumnya belum direncanakan (gap yang diangkat user). Keputusan: **jalur cepat**, bukan fase desain Figma terpisah — pakai **shadcn/ui + Tailwind** (component library siap pakai, langsung cocok dgn Next.js yg sudah dipilih di B.1) utk `apps/platform-core/dashboard-shell/` & `apps/products/trading/dashboard/`. Branding minimal dulu (logo + palet warna bertema "kinetic"/fisika: gradient dinamis, nuansa gerak/momentum, konsisten dgn narasi nama "Kinetiq"), investasi desain lebih serius ditunda sampai ada revenue/traksi nyata — supaya tidak menahan kecepatan solo-founder ke MVP. Flow UX inti yg wajib ada sebelum Fase 5 (Web Dashboard Lengkap): onboarding/signup, connect API key exchange, lihat posisi & sinyal, approve/reject rebalance, konfigurasi `risk_mandate`.

**Tech Stack Konsolidasi** (rangkuman dari keputusan yg sudah tersebar di B.1, disatukan di sini atas permintaan user):

| Layer | Bahasa/Tools |
|---|---|
| Backend/data/agent (platform-core + trading vertical) | Python 3.11 — FastAPI, LangGraph, SQLAlchemy+Alembic, CCXT |
| Job orchestration | TypeScript — Inngest functions |
| Web dashboard | TypeScript — Next.js + React + Tailwind + **shadcn/ui** |
| Database | PostgreSQL (Neon) |
| Infra-as-code | YAML (GitHub Actions), Railway config |
| **Telegram bot** | **Python** (`python-telegram-bot`) — keputusan baru, lihat di bawah |

**Telegram — tidak perlu Telegram Premium/Business**: terverifikasi, Bot API Telegram 100% gratis, tanpa tier berbayar utk fungsi dasar (kirim/terima pesan, inline button). Rate limit default (1 pesan/detik per chat, ~30 pesan/detik broadcast) jauh di atas kebutuhan Kinetiq di skala MVP. Opsi "paid broadcast" (Telegram Stars) cuma relevan kalau nanti broadcast >30 pesan/detik — bukan kebutuhan sekarang.

**Conversational Interface (ide baru user, disetujui dgn 1 syarat)**: Telegram bot tidak lagi command-only (`/positions`, `/pnl`), tapi **hybrid conversational**:
- Percakapan bebas natural-language utk monitoring/tanya-jawab (mis. "gimana performa BTC gue minggu ini?") — LLM interpret via `agent-orchestrator`.
- **Wajib structured confirmation** (tombol Ya/Tidak eksplisit atas proposal yg jelas) utk SEMUA aksi yg mengubah state/uang riil (eksekusi trade, ubah `risk_mandate`, kill switch) — natural language cuma jadi "pintu masuk" yg lebih ramah, TETAP wajib lewat `risk_gate.py` yg sama (Section B.7), tidak boleh jadi jalan pintas yg melewati gate.
- **Implikasi bahasa**: Telegram bot diimplementasi di **Python** (bukan TypeScript spt draft awal), jadi wrapper tipis yg langsung manggil `agent-orchestrator`/LangGraph, bukan logic terpisah — update `apps/products/trading/telegram-bot/` dari TS ke Python.
- **Implikasi biaya**: percakapan bebas = tiap pesan butuh LLM utk interpretasi (lebih mahal drpd command-matching biasa) — inilah yg jadi alasan model monetisasi berbasis token di bawah, bukan cuma flat-fee per tier.

### B.15 Model Monetisasi Berbasis Token (mengikuti pola API billing Claude/Anthropic)

User minta konsekuensi biaya LLM (dari conversational interface B.14) **dibebankan ke pengguna lewat model token**, mirip cara Anthropic/OpenAI jual API credit — bukan cuma flat subscription per tier (signal_only/auto_execute). Ini jadi **lapisan monetisasi tambahan**, bukan pengganti tier fitur yg sudah ada di B.3/A.3 (tier tetap menentukan fitur apa yg bisa diakses; paket token menentukan berapa banyak agent/LLM invocation yg bisa dipakai bulan itu).

**Skema baru** (`packages/db`, extend dari B.3):

```sql
CREATE TABLE token_package (            -- dikonfigurasi admin, dinamis, bukan hardcode
    id SERIAL PRIMARY KEY,
    package_key TEXT UNIQUE NOT NULL,        -- 'starter','growth','scale', dst
    name TEXT NOT NULL,
    monthly_token_allowance BIGINT NOT NULL,
    price_usd NUMERIC(10,2) NOT NULL,
    discount_pct NUMERIC(5,2) DEFAULT 0,     -- mis. diskon beli tahunan/bundle
    is_addon_topup BOOLEAN DEFAULT FALSE,    -- true kalau ini paket top-up tambahan (bukan paket dasar bulanan)
    is_active BOOLEAN DEFAULT TRUE,
    updated_by UUID REFERENCES platform_user(id),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE tenant_token_ledger (       -- append-only, transparan & auditable (pola sama spt order_audit_log)
    id BIGSERIAL PRIMARY KEY,
    tenant_id UUID REFERENCES tenant(id) NOT NULL,
    ts TIMESTAMPTZ DEFAULT now(),
    delta_tokens BIGINT NOT NULL,            -- positif (topup/reset bulanan) atau negatif (consumption)
    reason TEXT NOT NULL CHECK (reason IN ('monthly_reset','consumption','topup_purchase','admin_adjustment')),
    agent_skill_key TEXT,                    -- skill mana yg konsumsi token ini (NULL kalau bukan consumption)
    balance_after BIGINT NOT NULL
);

ALTER TABLE tenant ADD COLUMN token_package_id INT REFERENCES token_package(id);
```

**Keputusan desain (sesuai arahan user):**
- **Paket token dinamis**: admin atur `monthly_token_allowance`, `price_usd`, `discount_pct` per paket kapan saja lewat admin panel `dashboard-shell`, tanpa deploy ulang — pola sama persis dgn `llm_config` (B.13), bukan hardcode.
- **Diskon**: field `discount_pct` di `token_package` mendukung diskon per-paket (mis. bundle tahunan, promo) — admin yg atur, bukan logic hardcoded di kode.
- **Founder/superadmin bebas tanpa batasan token**: `platform-core/llm-gateway` budget-enforcement middleware (C.1) **skip cek `tenant_token_ledger` kalau `platform_user.role == 'superadmin'`** — konsisten dgn keputusan awal bahwa superadmin bypass billing/plan-gating (A.3/B.13), sekarang eksplisit juga cakup token cap.
- **Dokumentasi transparansi utk pengguna** (wajib, item baru): halaman publik `docs/token-usage.md` (ditampilkan juga di dashboard tenant) yg jelaskan dlm bahasa awam: apa itu "token" di konteks Kinetiq, estimasi token per jenis interaksi (mis. 1x cek sinyal vs 1x analisis rebalance penuh — angka pasti perlu dikalibrasi dari data pemakaian nyata Fase 2-3, jangan janjikan angka spesifik sebelum ada data), sisa kuota real-time (query `tenant_token_ledger`), riwayat pemakaian, kapan reset bulanan, cara beli top-up. Prinsipnya: pengguna harus bisa lihat persis kenapa kuota mereka berkurang — sama spt Anthropic Console kasih usage breakdown.
- **Alur beli/top-up**: paket dasar bulanan via Midtrans recurring payment (auto-reset `tenant_token_ledger` tiap siklus billing), top-up token pack via Midtrans one-time charge (nambah `delta_tokens` positif langsung, tidak nunggu reset bulanan).

**Roadmap placement**: desain skema di atas masuk **Fase 0** (sekalian dgn `llm_config`/`platform_user`, krn sama-sama fondasi billing dinamis), tapi angka konkret tiap paket (harga, alokasi token) **baru difinalisasi Fase 2-3** setelah ada data pemakaian LLM nyata dari paper trading (B.9) — supaya harga tidak asal tebak.

### B.16 Revisi Payment Gateway: Dual-Provider Midtrans + XIDR/StraitsX (IDRX sbg backup) utk MVP Indonesia-First (Dinamis)

User klarifikasi beberapa hal penting yang mengubah keputusan billing sebelumnya (B.1/A.3, sebelumnya Paddle):
1. **Xendit tidak bisa dipakai sekarang** — dikonfirmasi user & terverifikasi riset: Xendit **mewajibkan legal entity** (minimal sole proprietorship/CV/PT terdaftar), **tidak menerima akun bisnis perorangan murni**. Krn bisnis Kinetiq belum berbadan hukum, Xendit baru bisa dipakai setelah PT/CV resmi berdiri.
2. **Target pasar sementara adalah Indonesia**, bukan global — mengubah prioritas dari rekomendasi Paddle sebelumnya (Merchant of Record, bagus utk global/USD tapi tidak native ke metode pembayaran lokal Indonesia).
3. **User mau 2 jalur pembayaran sekaligus**, salah satunya **IDRX** (stablecoin Rupiah Indonesia) sbg jalur cepat utk **uji coba teknis** apakah integrasi payment gateway berhasil — sambil onboarding Midtrans (yg butuh verifikasi KTP beberapa hari kerja) berjalan paralel. Prinsip **arsitektur tetap dinamis/multi-provider**, supaya begitu Xendit approve (setelah badan hukum resmi), tinggal plug-in provider baru tanpa rombak.

**Provider #1 — Midtrans (fiat IDR, jalur utama utk pelanggan)**: via **Midtrans GO / WhatsApp Onboarding** (verifikasi KTP, tanpa perlu badan hukum). Recurring/subscription payment native, tanpa biaya bulanan/setup (cuma biaya per transaksi sukses), metode lokal (GoPay, VA bank transfer, QRIS) — detail lengkap sama seperti draft sebelumnya.

**Provider #2 — XIDR (StraitsX), gantikan IDRX sbg pilihan utama stablecoin**: riset lanjutan (atas usulan user) menemukan **XIDR** — stablecoin Rupiah 1:1 **regulated**, diterbitkan **StraitsX** (fintech Singapura mapan, dikenal lewat XSGD). Lebih disukai drpd IDRX krn: (a) status regulasi lebih jelas/diakui, (b) **StraitsX Indonesia Business Account mendukung tipe "Sole Trader"** — verifikasi cukup **KTP + NPWP pribadi** (bukan Akta Pendirian/SK Kemenkumham spt jalur PT), proses **1-3 hari kerja**, jadi tetap bisa diakses tanpa badan hukum resmi (sama spt Midtrans). **Panduan apply**: (1) siapkan NIB Perorangan (oss.go.id) + NPWP pribadi kalau belum py, (2) daftar StraitsX Indonesia Business Account pilih tipe **Sole Trader**, (3) upload KTP+NPWP, (4) tunggu verifikasi 1-3 hari kerja, (5) minta akses Payment API setelah akun aktif (detail teknis request/callback API belum diverifikasi mendalam — cek dashboard StraitsX langsung, jangan asumsikan identik dgn alur IDRX). **IDRX dicatat sbg alternatif/backup** (sudah diriset sebelumnya: multi-chain Polygon/Base/Lisk, Transaction/Payment API dgn alur redirect+callback mirip PSP biasa) kalau approval StraitsX ada kendala. Kenapa jalur stablecoin (baik XIDR maupun IDRX) tetap relevan:
- Cocok dgn positioning Kinetiq yg sudah crypto-native/non-custodial — pelanggan (trader crypto) terbiasa pakai wallet.
- Bagus utk validasi teknis cepat: alur redirect+callback mirip PSP biasa, jadi cara termudah memvalidasi arsitektur webhook→`tenant.plan_tier` sync (B.1/B.15) jalan end-to-end, sebelum Midtrans/StraitsX selesai onboarding penuh.

**Keputusan desain — arsitektur dinamis/multi-provider** (extend dari B.3):
- Kolom `tenant.payment_provider` (sudah digeneralisasi dari `stripe_*`/`paddle_*`) mendukung nilai `'midtrans' | 'xidr' | 'idrx' | 'xendit' | 'paddle'` — bukan enum tetap di kode, tapi row-based config spt `token_package`/`llm_config`, supaya nambah provider baru = nambah adapter baru, bukan rombak skema.
- Tiap provider py adapter tipis sendiri di `apps/platform-core/billing/providers/{midtrans.py, xidr.py, idrx.py, xendit.py, paddle.py}` yg implement kontrak sama (`verify_webhook()`, `parse_payment_event()`, `create_checkout_link()`) — funnel ke logic inti yg sama (`sync_tenant_plan()`, update `tenant_token_ledger`) — pola identik dgn `DerivativesDataSource` connector abstraction (B.11) & `ExchangeExecutionAdapter` (B.7), konsisten dgn prinsip arsitektur yg sudah dipakai di seluruh rencana ini.
- **Xendit** tetap dicatat sbg provider masa depan (Fase lanjutan, setelah PT Perorangan/CV resmi via OSS) — begitu approve, tinggal tambah `providers/xendit.py`, tidak perlu ubah `tenant`/`billing` core.
- **Paddle** didemote jadi opsi ekspansi global (bukan MVP) — tetap relevan kalau nanti target pelanggan meluas ke luar Indonesia (crypto trader cenderung global), dicatat bukan dibuang.

---

## PART C — Agentic Engineering Stack, MCP, & DevOps Otomasi

(Bagian ini menjawab langsung pertanyaan user: apakah stack orchestration saat ini — LangGraph+Inngest+Langfuse — sudah cukup optimal & reusable utk semua agent masa depan, apa peran MCP, dan bagaimana otomasi CI/CD-nya.)

### C.1 Stack Agentic Engineering — Evaluasi & Tambahan

Yang sudah tepat (dipertahankan): **LangGraph** (graph runtime tempat semua agent-vertical jalan), **Inngest** (job/event orchestration), **Langfuse** (observability). Tiga ini masing-masing punya peran berbeda & tidak overlap — pola ini sudah standar industri agentic engineering 2026. Tambahan yang membuatnya benar-benar **reusable lintas vertical** (trading sekarang, exam/chatbot/content-creator/task nanti):

| Komponen tambahan | Fungsi | Kenapa perlu |
|---|---|---|
| **`BaseAgentGraph` contract** (`platform-core/agent-sdk/`) | Kelas dasar LangGraph yang wajib diturunkan tiap graph vertical (node standar: `ground`→`plan`→`execute`→`validate`→`deliver`, auto-attach Langfuse callback, auto-resolve `llm_config`) | Tanpa ini, tiap vertical baru bikin boilerplate LangGraph dari nol. Dengan ini, agent exam/chatbot/content-creator tinggal isi node spesifik, infra tracing+LLM-routing otomatis ikut |
| **pgvector di Neon** (extension native Postgres, tidak perlu vector-DB terpisah) | Memory/RAG jangka panjang: embedding `trade_annotation` (B.6b), nanti embedding konten/percakapan utk vertical lain | Neon sudah jadi DB utama — pgvector adalah extension resmi, tidak nambah biaya infra baru, cocok dgn constraint "tetap di Neon" |
| **Langfuse Prompt Management & Datasets/Evals** (sudah built-in di Langfuse, belum dipakai eksplisit di rencana sebelumnya) | Versioning prompt per skill + regression-test otomatis (LLM-as-judge) tiap kali prompt/model diganti via `llm_config` | Krusial krn admin akan sering gonta-ganti model (B.13) — perlu cara obyektif memastikan ganti model tidak menurunkan kualitas sebelum di-deploy ke tenant |
| **Guardrail layer generik** (`platform-core/guardrails/`) | Validasi input/output tiap agent invocation (PII redaction, content-moderation, schema-validation output LLM) sbg middleware sebelum masuk `risk_gate` (trading) atau logic vertical lain | Agar tiap vertical baru otomatis dapat lapisan keamanan dasar tanpa nulis ulang; utk trading ini melengkapi (bukan menggantikan) `risk_gate.py` yang tetap jadi checkpoint keras |
| **Per-tenant LLM budget enforcement** (`llm-gateway` middleware) | Hard-cap token/biaya LLM per tenant per hari sesuai plan tier | Melindungi margin SaaS — tanpa ini satu tenant/agent yang "nyasar loop" bisa membengkakkan biaya OpenRouter tanpa batas |

Tidak direkomendasikan ganti LangGraph ke framework lain (CrewAI/AutoGen dsb) — LangGraph sudah dipilih krn selaras dgn pola Vibe-Trading & terintegrasi baik dgn Langfuse; ganti framework di titik ini cuma re-work tanpa benefit jelas.

### C.2 Peran MCP (Model Context Protocol)

MCP relevan lewat **dua arah**, keduanya bernilai tapi tidak blocking MVP:

1. **Platform kita SEBAGAI MCP server** (`apps/platform-core/mcp-server/`): expose skill/tool registry (funding rate lookup, backtest run, portfolio status, dst — read-only + write yang tetap lewat `risk_gate`) sbg MCP tools. Manfaat langsung: **founder bisa akses platform sendiri dari Claude Desktop/Claude Code** (ini yang dimaksud "simbiosis mutualisme" — Anda pakai Claude buat ngembangin & langsung operate platform-nya lewat MCP juga), dan membuka jalan integrasi partner/power-user di masa depan tanpa bikin API custom baru tiap kali.
2. **Platform kita SEBAGAI MCP client**: LangGraph node bisa konsumsi MCP server pihak ketiga sbg sumber tool yang terstandarisasi (drpd integrasi SDK bespoke tiap kali) — berguna terutama utk vertical non-trading nanti (mis. agent content-creator konsumsi MCP server untuk publishing/CMS).

**Rekomendasi**: masukkan sbg **Fase 2-3** (paralel dgn strategy engine), BUKAN prasyarat Fase 0/1 — MCP server internal cukup tipis untuk dibangun setelah skill registry (agent-orchestrator/skills) sudah stabil, supaya tidak dobel-desain kontrak tool sebelum bentuknya matang.

### C.3 CI/CD & Otomasi (GitHub Actions + Neon branching + Railway)

Terverifikasi via riset: Neon & Railway **sama-sama punya dukungan resmi** utk pola yang diminta user:

- **Neon**: GitHub Action resmi `neondatabase/create-branch-action` bikin **branch Neon terisolasi per PR** otomatis (data+schema copy-on-write, tanpa biaya storage penuh), `schema-diff-action` posting diff skema sbg komentar PR (review migrasi jadi visual), `delete-branch-action` otomatis cleanup saat PR ditutup. Alur: PR dibuka → branch Neon baru → Alembic migration jalan ke branch itu → test integration jalan ke branch terisolasi → PR closed/merged → branch dihapus (atau di-merge ke branch `main` Neon kalau PR merge ke `main` git).
- **Railway**: auto-deploy native saat push ke branch yang di-trigger (biasanya `main`) via GitHub integration bawaan (tanpa Action tambahan), plus `Railway Deploy Action`/CLI (pakai Project Token) utk preview-environment per-PR kalau mau staging terpisah per-fitur.
- **Auto-merge ke `main`**: direkomendasikan pakai **GitHub native auto-merge** (`gh pr merge --auto`) yang otomatis merge begitu semua **required status check** hijau (lint, type-check, unit+integration test thd Neon preview branch, migration dry-run) — **DENGAN PENGECUALIAN**: PR yang menyentuh path sensitif (`apps/products/trading/execution/risk_gate.py`, `apps/products/trading/execution/custody/*`, migration yang mengubah tabel `risk_mandate`/`tenant_credential`) **wajib manual review**, tidak boleh auto-merge murni — ini garis merah krn menyangkut uang riil & custody, otomasi penuh di titik ini terlalu berisiko meski secara teknis bisa.
- Implementasi: `.github/workflows/ci.yml` (lint+test+migration-dry-run pakai Neon branch), `.github/workflows/deploy.yml` (trigger dari Railway auto-deploy, tidak perlu Action manual kalau pakai integrasi native), branch protection rule di GitHub utk wajibkan check + CODEOWNERS review khusus path sensitif di atas.

### C.4 Ide Nama Bisnis (brainstorm, perlu keputusan Anda)

Mengaitkan tema besar rencana ini (matematika/Markowitz, analogi fisika pasar dari teori Anda, multi-agent AI) supaya nama terasa relevan & mudah diingat:

| Nama | Rasional |
|---|---|
| **AlphaSwarm** | Langsung komunikasikan "swarm of AI agents mencari alpha (excess return)" — paling jelas menjual konsep multi-agent trading ke calon pelanggan |
| **Kinetiq** | Dari "kinetic" — sejalan analogi fisika Anda (waktu, jarak, momentum pasar), terdengar modern/tech-native |
| **Convexa** | Dari "convexity" (istilah kuantitatif), terdengar premium/fintech, cocok kalau positioning ke trader lebih serius/institutional-feel |
| **Frontiq** | Dari "efficient frontier" (konsep inti Markowitz) + "IQ" — pas kalau mau tekankan sisi "smart/quant" |
| **Nexalpha** | "Nexus" (hub yang menghubungkan banyak agent) + "alpha" |

**Keputusan: "Kinetiq"** — dipilih user. Repo GitHub `agent-trading-perp` akan di-rename ke **`kinetiq-app`** (dikonfirmasi user) setelah rencana ini di-approve. Rename repo di GitHub otomatis membuat redirect dari URL lama, jadi remote git lokal tetap jalan tanpa perlu diubah manual.

---

### Critical Files untuk Implementasi
- `CLAUDE.md` (baru) + `docs/deployment-runbook.md` (baru) — memory & gotcha operasional Railway/Neon/CI dari kejadian nyata (saga 4-bug Railway + 2-bug Neon), wajib dibaca sebelum ubah `railway.toml`/`ci.yml` lagi di sesi mana pun
- `packages/db/models.py` + migrations — skema lengkap termasuk `tenant`, RLS policy (Section B.3/B.4)
- `apps/platform-core/api-gateway/{main.py, deps.py, requirements.txt}` (sengaja flat, bukan `src/`+`pyproject.toml` — lihat komentar di `railway.toml`) — `deps.py` sudah py tenant auth middleware (Clerk JWT verify + auto-provision `platform_user`) nyata; **plan-gating** (product+tier) masih menyusul (Section A.6/B.2/B.13)
- `packages/db/src/kinetiq_db/engine.py` (baru) — `normalize_db_url()`, helper bersama dipakai semua service yg konek DB (Neon/Railway kasih `DATABASE_URL` scheme polos yg salah default ke `psycopg2`)
- `railway.toml` (baru, di **root repo**, bukan di dalam folder service) — Railway config-as-code tidak ikut Root Directory, wajib di root repo per dokumentasi resmi; command di dalamnya tetap relatif thd Root Directory yg di-set di dashboard
- `.github/workflows/ci.yml` — `base_branch: production` (bukan `main`) di step `schema-diff-action`, krn nama branch default Neon project ini `production` — sudah terverifikasi sukses thd Neon asli
- `apps/platform-core/llm-gateway/` — abstraksi provider LLM + cost tracking, dipakai semua vertical (trading sekarang, exam/chatbot/content-creator nanti)
- `apps/products/trading/agent-orchestrator/skills/strategy/fib_gann_timing.py` — formalisasi metode trading user, paling sensitif secara bisnis (core IP)
- `apps/products/trading/agent-orchestrator/graphs/portfolio_rebalance_graph.py` — mengikat strategy engine + risk gate + execution (perp & spot)
- `apps/products/trading/execution/risk_gate.py` — mandatory checkpoint guardrail
- `apps/platform-core/billing/providers/{midtrans.py, xidr.py}` (+ `idrx.py` backup, `xendit.py`/`paddle.py` fase lanjutan) — adapter dual-provider → `sync_tenant_plan()` inti, dasar monetisasi dinamis (Section B.16)
- `packages/db/migrations/env.py` — fix normalisasi `DATABASE_URL` scheme ke driver `psycopg` v3 (bug nyata ditemukan dari log CI real Neon — lihat Status Implementasi)
- `apps/platform-core/llm-gateway/resolve_config.py` — resolve `llm_config` hierarchy (tenant→product→global) & panggil OpenRouter, dasar fleksibilitas model per agent (Section B.13)
- `apps/products/trading/agent-orchestrator/skills/strategy/trader_profile.py` — kalibrasi `fib_gann_timing` terhadap anotasi trading founder (Section B.6b)
- `apps/platform-core/agent-sdk/base_agent_graph.py` — kontrak dasar LangGraph yang dipakai ulang semua vertical (Section C.1)
- `apps/platform-core/mcp-server/` — expose skill registry sbg MCP tools (Section C.2)
- `.github/workflows/ci.yml` + `.github/workflows/deploy.yml` — CI dgn Neon branch-per-PR, auto-merge dgn pengecualian path sensitif (Section C.3)
- `infra/neon/partitioning/*.sql` — strategi partitioning time-series
- `THIRD_PARTY_LICENSES.md` (baru, Fase 0) — wajib catat atribusi MIT Vibe-Trading (HKUDS) utk tiap modul yang di-fork/adaptasi (mcp-server, broker-connector, shadow-account) sesuai keputusan reuse-kode di atas
- `apps/platform-core/llm-gateway/token_budget.py` (baru) — enforce `tenant_token_ledger` per invocation, skip cek kalau role superadmin (Section B.15)
- `docs/token-usage.md` (baru) — dokumentasi transparansi token utk pengguna (Section B.15)
- `apps/products/trading/telegram-bot/` — Python (`python-telegram-bot`), bukan TypeScript spt draft awal (Section B.14)
