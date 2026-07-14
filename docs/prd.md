# PRD + Rencana Teknis: Kinetiq — Sistem Trading Agentic Single-Operator

**Repo**: `kinetiq-app`, branch default `main`. **Owner**: Mufti (solo/single-operator).

## Catatan Pivot (13 Juli 2026)

Repo ini **dulunya** dirancang sbg "Multi-Agent AI Trading SaaS" multi-tenant (billing Midtrans/XIDR, auth Clerk, `apps/platform-core/*` sbg lapisan generik utk vertical non-trading di masa depan, meme-sniper/DLMM sbg modul V2/V3). Scope dipersempit jadi **sistem trading agentic single-operator** (BTC perp dulu) — tidak ada lagi SaaS, multi-tenant, billing, atau vertical lain. `apps/platform-core/*` (billing, agent-registry, api-gateway, notification, dashboard-shell, guardrails, llm-gateway, mcp-server) dihapus total, dan migration `packages/db/migrations/versions/0009_drop_platform_core_and_tenancy.py` mencabut RLS + `tenant_id` dari semua tabel trading serta tabel `tenant`/`platform_user`/`llm_config`/`token_package`/`tenant_token_ledger` (`tenant_credential` di-rename jadi `credential`). Detail keputusan & alasan: `CLAUDE.md`. Riwayat SaaS lama (RBAC per-langganan, token billing, dual payment gateway, brainstorm nama bisnis, dsb) sengaja **tidak** direplikasi di dokumen ini — itu histori git, bukan rencana aktif.

Di perubahan yang sama, **roadmap & arsitektur "ENGGANG"** (dokumen terpisah yang disusun founder, mengonsolidasi MARKOVIZ V5 + brief-brief Kinetiq + riset lanskap trading-agent 2026) dijadikan **struktur utama dokumen ini** — bukan repo/produk terpisah, langsung merged ke `docs/prd.md` sesuai keputusan founder. Codename "ENGGANG" (burung enggang gading, Kalimantan Barat: terbang tinggi tapi cuma hinggap di dahan yang sudah teruji kuat) tidak dipakai sbg nama produk, cuma filosofi desain: ambisi tinggi, tiap komponen wajib lolos gate kuantitatif sebelum dipijak fase berikutnya.

---

## 0. Ringkasan Eksekutif & Target

Kinetiq adalah sistem trading agentic single-operator: **modul sinyal deterministik → arbiter → risk hard gate → shadow trading → live canary**, dgn disiplin walk-forward OOS ketat di tiap fase. Fokus instrumen: **BTC perp dulu** (USDT-M, bukan spot — semua validasi sejauh ini di perp).

**Definisi "skor terbaik yang jujur"** (dari riset lanskap trading-agent 2026, bukan angka backtest yang di-inflasi):

| Metrik | Benchmark terverifikasi terbaik | Target Kinetiq |
|---|---|---|
| Profit Factor OOS (net fee+funding) | Freqtrade honest range 1.0–1.3 | **≥1.3 di ≥4/6 window walk-forward** |
| Sharpe live | DeepFundAgent 1.39–1.96 (live) | **≥1.0 live 90 hari, ≥1.4 aspirasional** |
| Max drawdown | TradingAgents <2.2% (backtest, tidak realistis) | **≤15% live, hard stop di 20%** |
| Directional accuracy per modul | QuantAgent 50.7–55.3 | **≥55% OOS per modul, tanpa bias arah >65/35** |

Sharpe 5-8 yang sering muncul di paper riset adalah artefak window pendek, **bukan target** — PF 1.3-1.5 OOS & Sharpe 1.0-1.5 live yang jujur sudah persentil teratas dunia nyata.

**Insight kunci yang membentuk desain:**
1. Baseline MARKOVIZ V5 (PF 0.56 BTC / 0.69 ETH, net-negatif — lihat §2) konsisten dgn hasil OOS jujur di seluruh bidang: bukan berarti edge-nya tidak ada, tapi belum ditemukan/di-gate dgn benar. Fase 0-1 fokus di sini.
2. **Arsitektur > model** — role split modul deterministik/arbiter/risk-gate lebih menentukan drpd backbone LLM manapun.
3. **Deterministik dulu, LLM belakangan** — struktur (BOS/CHoCH), Fib/Gann, indikator dihitung numerik; LLM cuma arbiter/penjelas read-only, tidak pernah eksekusi.
4. **Risk sebagai hard gate**, bukan advisor — veto berlapis (regime, kNN risk memory, R:R, exposure caps).

---

## 1. Goals & Non-Goals

**Goals:**
- G1: Menemukan & memvalidasi edge dgn PF OOS ≥1.3 pada BTC (per-simbol, bukan agregat) via pipeline attribution → hypothesis → walk-forward.
- G2: Orkestrasi agentic (analyst modules → arbiter → risk gate → execution) yang terbukti mengalahkan baseline meta-model MARKOVIZ V5 DAN buy-and-hold di window OOS yang sama.
- G3: Shadow trading (paper, data live) minimal 60 hari dgn fidelity score ≥85% sebelum capital live.
- G4: Live canary capital kecil + kill-switch otomatis, lalu loop fine-tuning bulanan berbasis attribution.
- G5: Komponen dibangun reusable (rule-of-two extraction — promosikan ke modul generik setelah dipakai ≥2 tempat), tapi **tidak ada lagi lapisan platform generik "utk vertical masa depan"** — itu bagian dari SaaS yang sudah dibatalkan.

**Non-Goals (eksplisit):**
- ❌ Vision-LLM baca chart di jalur produksi (boleh eksperimen riset terisolasi dgn kill-criterion, lihat §8).
- ❌ Multi-agent debate bebas teks antar modul (menambah noise, bukan sinyal).
- ❌ Universe luas — BTC-first; ekspansi simbol lain (ETH, dst) hanya via gate walk-forward per-simbol yang sama (temuan: mekanisme robust lintas bursa Binance/Bybit tapi TIDAK generalize ke ETH — lihat §2).
- ❌ LLM memegang eksekusi/parameter live dlm bentuk apa pun.
- ❌ HFT/sub-menit — timeframe kerja 1h/4h/Daily sesuai kekuatan metode fib/gann.
- ❌ Multi-tenant SaaS, billing, RBAC per-langganan, meme-sniper/DLMM sbg modul aktif — histori, bukan roadmap (lihat catatan pivot di atas). Tabel `token_launch_event`/`dlmm_position` masih ada di skema (dorman, tidak dipakai jalur aktif manapun).

---

## 2. Status Implementasi (live, di-update tiap ada progres nyata)

> Ringkasan padat riwayat rekayasa nyata. Detail lengkap tiap temuan (koordinat exact, angka test, reproduksi) ada di `docs/fib-gann-validation-brief.md`, `docs/sonnet5-implementation-roadmap.md`, `docs/validation-deep-dive-2026-07.md`, `docs/fable5-crypto-theory-investigation-2026-07.md`, dan `docs/deployment-runbook.md` — dokumen ini sengaja tidak menduplikasi angka/section itu, cuma merujuk.

**Baseline & infra:**
- CI (`.github/workflows/ci.yml`) hijau; `.github/CODEOWNERS` wajibkan review manual utk `execution/risk_gate.py`, `execution/custody/`, `packages/db/migrations/`.
- **Compute**: Railway → self-hosted **Coolify** di VM Vultr yang sama dgn Markoviz (`ai-perp-bot-core`, live, **tidak dikelola Coolify**, docker-compose sendiri) — Docker-build based (bukan Railpack/buildpack), tiap servis deployable butuh `Dockerfile` sendiri (`apps/products/trading/ingestion/Dockerfile` sbg contoh pertama). Sudah live & terverifikasi: `kinetiq-ingestion-worker` jalan di Coolify, menulis `funding_rate`/`ohlcv` nyata ke Neon production. Detail gotcha & migrasi: `docs/deployment-runbook.md`.
- **DB**: Neon Postgres, tidak ikut migrasi compute. Branch default project bernama `production` (bukan `main`) — `neon-preview-branch`/`schema-diff-action` pakai nama itu. `DATABASE_URL` mentah defaultnya salah pilih driver `psycopg2`; semua servis wajib panggil `kinetiq_db.engine.normalize_db_url()` supaya jadi `psycopg` v3.
- **Keamanan produksi RESOLVED (Fase 0d)**: role lama `neondb_owner` (dipakai `DATABASE_URL` production) ternyata `rolbypassrls=true`, artinya `FORCE ROW LEVEL SECURITY` efektif nol utk trafik service sendiri. Fix: role non-owner `kinetiq_app` (`rolbypassrls=false`, bukan anggota `neon_superuser`) dibuat via SQL manual, dipakai `api-gateway`(lama)/`ingestion` worker utk koneksi normal; `DATABASE_URL_MIGRATIONS` terpisah (tetap `neondb_owner`) khusus `alembic upgrade head`. RLS tenant-based ini sekarang murni sejarah pasca migration 0009 (tidak ada tenant lagi), tapi pola "role app non-owner, role migrasi terpisah" tetap dipakai.
- `order_audit_log` append-only via `BEFORE UPDATE OR DELETE` trigger (bukan `REVOKE`, yang no-op utk table owner) — masih berlaku persis.

**Ingestion (`apps/products/trading/ingestion`) — connector CEX/DEX pertama, terverifikasi hidup:**
- Binance USDS-M perp + Bybit via CCXT (`connectors/cex/ccxt_generic.py`, generik lintas exchange — nambah venue = 1 entry `VENUES` dict), scope `funding_rate`+`ohlcv`. Terverifikasi jaringan asli ke Binance+Neon production (BTC/USDT, ETH/USDT, via proxy Webshare.io); Bybit baru diverifikasi lewat deploy Railway/Coolify asli (bukan cuma mock). Dua bug proxy nyata: ccxt `InvalidProxySettings` (jangan set `httpProxy`+`httpsProxy` bareng) dan `407 Proxy Authentication Required` (salah copy password, bukan masalah plan Webshare).
- **Hyperliquid** (DEX perp pertama) ditambah — butuh 2 penyesuaian nyata di `ccxt_generic.py`: `fetchFundingRate` single-symbol `False` di Hyperliquid (fallback ke plural), dan `FUNDING_INTERVAL_HOURS` yang sebelumnya hardcode 8 utk semua venue ternyata salah utk Hyperliquid (settle per jam, `"1h"`) — fix: parse field `interval` dari response, fallback ke `DEFAULT_FUNDING_INTERVAL_HOURS=8`. Terverifikasi via jaringan Hyperliquid asli dari Termux (Android, tanpa proxy): 752 market, funding interval 1h asli, OHLCV asli.
- **Fallback chain** (`native_fallback.py`): ccxt dicoba dulu, native REST Binance/Bybit dipakai setelah 3 kegagalan berturut (`data_source_health.consecutive_failures`). Awalnya tidak baca `PROXY_URL` (bug, fixed) — kalau kegagalan asalnya IP-blocking, fallback tanpa proxy ikut gagal, bikin fitur ini percuma.
- **Partitioning otomatis** (`0004_partition_rollover.py` + `infra/neon/partitioning/rollover.sql`): 7 tabel partisi ternyata tidak pernah punya partisi range nyata sejak migration 0001 (semua data numpuk di partisi `DEFAULT`, termasuk data production). Fungsi `kinetiq_ensure_month_partition()` generik lintas tabel, tangani kasus Postgres menolak `ATTACH PARTITION` kalau `DEFAULT` masih punya row yang match range itu (harus dipindah keluar dulu) dan generated-column `price_basis.basis`/`basis_pct` (butuh column-list eksplisit, exclude kolom `GENERATED ALWAYS`).
- **Backfill + worker polling kontinu** (`worker.py`, `fetch_ohlcv_range()` dgn paging): terverifikasi produksi — backfill 365 hari × Binance+Bybit × BTC/ETH (8760 candle/instrumen 1h) sukses via Deploy Log asli, total 35.040 candle baru masuk production sekaligus jadi verifikasi jaringan asli pertama utk Bybit.

**`packages/backtest-core`** (`kinetiq_backtest`): `WalkForwardWindow` (frozen dataclass, UTC-aware, reject naive datetime & leak) — 2 generator terpisah krn skema MARKOVIZ V5 (candle-count, rolling) dan skema `fib_gann_backtest` (kalender bulan, anchored) beda beneran: `generate_windows_by_calendar()` dan `generate_windows_by_candles()`, plus `validate_window_set()` (no-leak, embargo gap, no-overlap). 21+ unit test, diverifikasi via fresh venv persis command CI.

**Baseline MARKOVIZ V5** (dibaca langsung dari `ai-perp-bot-core`, bukan asumsi): sistem "7-pillar" (OBI+funding+ΔOI+CVD dkk) penghasil sinyal LONG/SHORT/SKIP — **bukan** literal Markowitz mean-variance optimizer. Walk-forward berbasis jumlah candle (`isLen=2000, oosLen=700, warmup=200`, rolling), Sharpe di-annualize `periodsPerYear=35040` (basis 15-menit bar), funding cost tidak otomatis masuk PnL. **Hasil OOS existing: PF 0.56 BTC, PF 0.69 ETH — net-negatif, dikonfirmasi asli.**

**Kalibrasi & bug fib/gann (semua diverifikasi thd data production/TradingView asli, bukan cuma test sintetis):**
- **Gann Fan rate formula** (`price_per_time_unit = swing_price_range / swing_duration_in_bars`) CONFIRMED cocok terhadap **3 set koordinat exact TradingView** yang diberikan founder langsung dari tool "Coordinates": BTC/USDT 1h uptrend (58,005.0@bar127 → 60,908.9@bar177, rate 58.078/bar), BTC/USDT 4h downtrend (67,284.8@bar197 → 62,233.3@bar214, rate 297.147/bar), SOL/USDT 1h (64.03@bar127 → 73.84@bar157, rate 0.327/bar) — generalisasi lintas instrumen & arah trend terbukti, bukan kebetulan cocok BTC saja.
- Ditemukan & di-fix di jalan: `gann_base_rate()` awalnya cuma terima urutan basis-sebelum-pivot (asumsi skema live-signal); pola manual founder gambar fan justru origin lebih awal dari titik kedua — fix jadi order-agnostic (`abs(pivot.index - basis_leg_start.index)`).
- **Bug nyata: `compute_fib_levels()` arahnya TERBALIK.** Di-fit least-squares ke 9 level exact dari tool Fib Retracement TradingView (BTC/USDT 1h) → formula benar `swing_low + level*leg` (R²=1.000000), bukan `swing_high - level*leg` seperti asumsi awal (meleset ratusan dolar, bukan rounding). Level `3.618` juga ketemu aktif tapi belum ada di default extension levels — ditambahkan.
- **Bug nyata: entry price bisa jatuh di sisi salah stop-loss** (pivot ZigZag confirm dgn lag, harga sudah tembus level SL struktural intrabar sebelum confluence check di close candle) — fix: `_entry_is_valid()` menolak sinyal sebelum R:R gate dievaluasi.
- **Bug nyata: sinyal fire di bar konfirmasi pivot, bukan di bar sentuhan/retracement asli ke garis** — cek ke 14 seed sintetis: 0 dari puluhan sinyal lama yang benar-benar nembak di bar konfirmasi (semua delay 2-10 bar). Fix: `generate_signals()` memantau tiap bar setelah pivot confirm sampai `fib_gann_confluence_score() > 0` (harga benar-benar menyentuh garis), retry ke sentuhan berikutnya kalau gate gagal.
- Level Fib custom founder (retracement 0.382/0.5/0.618/0.786/0.886, extension 1.13/1.272/1.414/1.618/2/2.272/2.618/3.618), 9-angle Gann standar, ZigZag/ATR swing detection (threshold 1.5-2x ATR14) — semua RESOLVED & diimplementasi di `fib_gann_timing.py`.

**Modul skill lain yang sudah diimplementasi & diverifikasi thd data production asli** (semua sbg *kontributor skor*, bukan gate baru — lihat prinsip §7): `market_structure.py` (BOS/CHoCH + `structure_alignment_score`), `level_strength.py` (touch tracker + golden-ratio weighting 0.618/1.618, Part #1 deterministik; Part #2 fitting belum), `duration_prediction.py` (persentil durasi + probabilitas outcome, murni informational), `post_stop_behavior.py` (RETRACE_TO_ENTRY vs REVERSAL_CONTINUATION), `session_bias.py` (klasifikasi sesi Asia/London/NY), `htf_bias.py` (bias multi-timeframe Weekly/Daily/4h, reuse `market_structure.trend_bias()`), `derivatives_context.py` (funding/OI sbg konteks), `position_sizing.py` (F7a). Validation harness lengkap (`validation/fib_gann_backtest/`: `signal_runner.py`, `data_loader.py`, `trade_simulator.py` funding-aware, `metrics.py` PF/Sharpe/DD gross&net, `report.py`, `run_validation.py`, `configs/walk_forward_windows.yaml`) — **semua komponen bag. 6 brief validasi sudah dibangun**, sisanya soal volume data & hasil walk-forward (lihat di bawah).

**Data trade real & shadow-simulation:** `trade_annotation` diperluas kolom eksekusi nyata (leverage, margin_mode, fill price, fees/funding paid, exit_reason_real — brief bag. 7). Import 276 posisi closed dari CSV Binance Futures (`import_binance_position_history.py`) — **production sekarang genuinely terisi 276 baris** (klaim sukses pertama sempat salah krn silent-truncation paste manual Neon SQL Editor via mobile browser, root cause operasional bukan data/logic; fix final: transaksi multi-statement lewat Neon HTTP-SQL endpoint bentuk `{"queries":[...]}`, 159 query sekali jalan — **dicatat permanen di CLAUDE.md**, jangan pakai paste manual utk bulk-write lagi). Leverage/liquidation-aware simulator (`docs/shadow-simulator-brief.md` bag. 1-2) & `shadow_pair.py` (divergence attribution parsial, 6 komponen) juga sudah ada, tapi field eksekusi 276 trade itu masih NULL semua (leverage/exit_reason_real/funding) — attribution penuh nunggu trade baru yang field-nya terisi.

**Walk-forward run pertama — GAGAL kriteria promosi (dan ini valid secara riset, bukan kegagalan implementasi):** run pertama (BTC/USDT 1h Binance, 8760 candle, 10 window) cuma lolos **2/10 window** (PF net >1.3). Deep-dive lanjutan (replikasi 4 seri BTC/ETH × Binance/Bybit, 2.679 trade berlabel, overlay CoinGlass 399 hari) menemukan: mekanisme robust lintas bursa (Jaccard sinyal ~73%, PF nyaris identik Binance vs Bybit) TAPI TIDAK generalize ke ETH; confidence score `ConfluenceWeights` hand-tuned ternyata **anti-prediktif** (pearson r=-0.05); fee trading (0.10% round-trip taker) material — PF gross ~1.10 turun ke PF net-fees ~0.92; funding sendiri sepele di holding ~11 jam; OI-fuel deskriptif kuat (1.8-2.7x same-day) tapi lemah prediktif utk arah trade H+1 (bukan direction weight). Kombinasi HTF-align SMA200 + R:R∈[2,5) menaikkan PF pooled 0.97→1.30 gross **in-sample** — hipotesis, bukan hasil final, cuma teradopsi lewat walk-forward OOS net-of-fees. `fit_weights.py` (logistic elastic-net, refit per window) sudah dibangun tapi median AUC OOS 0.522 — kriteria adopsi (>0.55) belum terpenuhi, `ConfluenceWeights` default belum diganti. Kolom kandidat `sma_trend_bias_alignment` (bukan `trend_bias` berbasis swing yang sekarang di-wire) naikkan AUC ke 0.617 kalau diikutkan — kandidat kuat, belum diadopsi. Roadmap eksekusi lengkap (F0-F9, per fase granular di bawah level Fase 0-5 ENGGANG di §6) & rubric skor 3/10→10/10: `docs/sonnet5-implementation-roadmap.md`; analisis penuh + teori v2: `docs/validation-deep-dive-2026-07.md`; evidence trail + status klaim: `docs/fable5-crypto-theory-investigation-2026-07.md`.

**Integrasi Markoviz (keputusan 6-7 Juli 2026) — digabung ke mesin riset yang sama, bukan strategi terpisah** (lihat §6 "Yang Direuse vs Dibangun Baru" utk peta lengkap): swarm 4-agent Markoviz (`funding_basis_analyst`/`liquidation_analyst`/`flow_analyst`/`desk_risk_manager`, bobot funding 35%/liquidation 25%/flow 40%) akan diuji ulang lewat disiplin fitting yang sama (kriteria adopsi median AUC>0.55, korelasi OOS>0) — **tidak diasumsikan benar cuma karena sudah live**, krn funding/OI sudah terbukti empiris jadi indikator regime-volatilitas, bukan prediktor arah (temuan F4/derivatives_context di atas). Dua catatan wajib sebelum integrasi penuh: (a) UI Telegram Markoviz saat ini belum layak dipakai langsung, perlu didesain ulang; (b) validasi Kinetiq sejauh ini 100% di perp, swarm Markoviz (historisnya juga perp) tetap wajib lolos uji walk-forward sendiri di perp sebelum dipercaya, **jangan asumsikan pola apa pun otomatis valid tanpa gate yang sama**.

**Gap yang masih terbuka:**
- Risk hard gate: `execution/risk_gate.py` (v1, 13 Juli 2026) sudah ADA — kill-switch, symbol-universe permission, dan defensive re-check R:R/entry-validity. Regime gate (FREEZE/RISK_OFF) dan kNN risk memory veto: **desain sudah selesai** (`docs/regime-gate-knn-risk-memory-brief.md`, 14 Juli 2026) — classifier volatilitas causal + fallback OI-fuel utk regime gate, kNN atas corpus 2.679 trade simulasi (bukan 276 baris `trade_annotation` yang terlalu tipis), keduanya reuse infrastruktur `gated_campaign.py`/`fit_weights.py` yang sudah ada. Implementasi + validasi walk-forward nyata **belum dikerjakan** — itu sesi terpisah. Daily-loss-limit & correlation-based exposure cap masih belum ada desain sama sekali (butuh running-PnL tracking & multi-position tracking yang belum ada).
- Arbiter (meta-model per-regime + LLM arbiter opsional) belum dibangun — `fit_weights.py` baru fitting bobot confidence, bukan orkestrasi antar-modul.
- `graphs/` (LangGraph) masih kosong, belum disambung ke apa pun; `execution/` sudah punya `risk_gate.py` (v1), tapi order/position adapter (CCXT unified + native DEX signing) dan `custody/` masih skeleton.
- Shadow trading (60 hari live-paper, fidelity score) & live canary belum dimulai — prasyarat Fase 1-2 (§6) belum lolos gate.
- Native fallback Binance/Bybit belum dites via jaringan asli (field-shape baru dari dokumentasi publik).
- pgvector, Telegram monitor read-only 5-layer guardrail — sudah ada spesifikasi lengkap (`docs/llm-telegram-guardrails-brief.md`) tapi belum diimplementasi kode.

---

## 3. Arsitektur Sistem

### 3.1 Diagram alur (target, per layer — status implementasi tiap layer di §2/§6)

```
[Data Layer — point-in-time store]
  OHLCV multi-venue │ funding/OI/basis/orderbook/liquidation │ market_sentiment
        │ (semua ts "as-known-at", backtester wajib punya look-ahead detector)
        ▼
[Layer 1 — Modul Analis Deterministik]
  A. Structure Module: BOS/CHoCH (market_structure.py) — ADA
  B. Fib/Gann Module: ZigZag/ATR swing, fib custom, 9-angle Gann — ADA, dikalibrasi thd TradingView asli
  C. Faktor skor tambahan: level_strength, htf_bias, session_bias, duration_prediction, post_stop_behavior, derivatives_context — ADA (informational, belum semua di-fit ke confidence)
  D. Flow/Macro Module (orderbook wall, regime classifier ala Markoviz) — BELUM di-port ke mesin riset ini
        │ output: Signal per pivot yang baru confirm (skema `signal` table, factor_scores JSONB)
        ▼
[Layer 2 — Arbiter]
  - Meta-model per-regime (fit_weights.py, logistic elastic-net, refit per window) — ADA tapi BELUM lolos kriteria adopsi (AUC OOS 0.522)
  - LLM Arbiter (opsional, read-only explain/narrasi — TIDAK PERNAH menghasilkan order) — BELUM dibangun
        ▼
[Layer 3 — Risk Hard Gate]  ← veto berlapis, deterministik
  1. Regime gate (FREEZE/RISK_OFF → no-trade) — desain SELESAI (`docs/regime-gate-knn-risk-memory-brief.md`), implementasi+validasi belum
  2. kNN risk memory (veto/size-down berbasis kemiripan histori rugi) — desain SELESAI (`docs/regime-gate-knn-risk-memory-brief.md`), implementasi+validasi belum
  3. R:R gate ≥1.5 + kill-switch + symbol-universe permission — ADA (`execution/risk_gate.py` v1, `passes_risk_reward_gate()`)
  4. Exposure caps (leverage, korelasi, daily loss, cooldown) — leverage/notional sudah di `position_sizing.py` (downstream, bukan gate); korelasi/daily-loss/cooldown belum jadi gate runtime (butuh running-PnL & multi-position tracking dulu)
        ▼
[Layer 4 — Execution & Shadow]
  - Shadow simulator (fidelity score, divergence attribution) — sebagian (`shadow_pair.py`), belum ada live signal writer
  - Live executor (limit-first, slippage budget) — `execution/` masih skeleton
        ▼
[Layer 5 — Observability & Memory]
  - Attribution engine (IC, beta decomposition, walk-forward metrics) — ADA (`metrics.py`, deep-dive analysis)
  - Hypothesis registry — belum ada sbg sistem formal (temuan tercatat di docs/*.md, bukan DB)
  - Telegram monitor read-only, 5-layer guardrails — spesifikasi lengkap (`docs/llm-telegram-guardrails-brief.md`), belum diimplementasi kode
```

### 3.2 Prinsip desain (binding)
- **Point-in-time everywhere.** Fitur/label cuma dari data yang tersedia pada timestamp keputusan; backtester perlu look-ahead detector eksplisit.
- **Per-regime, per-simbol.** Tidak ada metrik agregat sbg gate — temuan robust-lintas-bursa-tapi-tidak-ke-ETH (§2) adalah bukti konkret kenapa.
- **LLM = read-only explain/hypothesis/narration.** Jalur keputusan trading (sinyal → confluence → R:R gate → risk envelope) 100% deterministik; LLM tidak pernah memodifikasi state/posisi/threshold, termasuk lewat percakapan natural-language (lihat §8).
- **Gate keras vs faktor skor** (standing rule, `docs/fib-gann-validation-brief.md` bag. 10): gate keras (reject total) HANYA utk yang struktural invalid (entry di sisi salah SL, R:R jelek — 2 gate yang ada). Semua faktor baru (level strength, OI/volume fuel, bias sesi, reversal, durasi, htf_bias) masuk sbg kontributor skor tertimbang ke `confidence`, bukan gate AND baru. Fitting + regularisasi (Fase 3, `fit_weights.py`) yang menentukan bobot mana yang berguna, bukan ditebak manual.
- **Satu perubahan per siklus** (Fase 5/fine-tuning) — ubah dua hal sekaligus bikin attribution rusak.

### 3.3 Tech stack (realita implementasi, bukan target abstrak)
Berbeda dari draf arsitektur awal ENGGANG yang membayangkan monorepo `packages/core` (TypeScript, reuse engine Markoviz) + `packages/research` (Python sidecar) + Redis bus + SQLite hypothesis registry — implementasi nyata Kinetiq sejauh ini **satu monorepo Python**: `packages/db` (SQLAlchemy + Alembic, source of truth schema), `packages/backtest-core` (walk-forward windowing, dipakai bersama `fib_gann_backtest`), `apps/products/trading/agent-orchestrator/skills/strategy/*` (semua modul Layer 1 di atas), `apps/products/trading/ingestion` (connector data). Redis bus, SQLite hypothesis registry, dan LangGraph arbiter dari blueprint ENGGANG **belum dibangun** — dicatat sbg arah target Fase 2/5 (§6), bukan klaim yang sudah ada. Markoviz (`ai-perp-bot-core`, TypeScript) tetap repo terpisah; integrasinya sejauh ini konseptual (uji ulang sinyalnya lewat mesin fitting Python yang sama), bukan penggabungan kode.

---

## 4. Data Model (Current — `packages/db/src/kinetiq_db/models.py`, post-migration 0009, tanpa `tenant_id`)

| Tabel | Peran |
|---|---|
| `venue`, `instrument` | Dimensi: bursa (cex/dex) & instrumen per bursa |
| `data_source_health` | Tracking `consecutive_failures` per venue+data_type, dipakai fallback chain |
| `funding_rate`, `open_interest`, `price_basis`, `orderbook_snapshot`, `liquidation_event`, `market_sentiment`, `ohlcv` | Time-series, range-partitioned by `ts` (partisi bulanan via `kinetiq_ensure_month_partition()`) |
| `strategy`, `portfolio_target`, `position` | State strategi & posisi (paper/live via `is_paper`) |
| `order_audit_log` | Append-only (trigger `BEFORE UPDATE OR DELETE`, berlaku bahkan thd table owner) |
| `risk_mandate` | Hard cap per `account_id` (max_leverage, max_drawdown_pct, kill_switch_active, dst) — PK sekarang `account_id` saja (bukan lagi composite dgn tenant_id) |
| `credential` | Envelope-encrypted API key/agent-wallet (rename dari `tenant_credential`) |
| `token_launch_event`, `dlmm_position` | Sisa skema meme-sniper (V2) / DLMM (V3) — dorman, bukan bagian roadmap aktif (§1) |
| `signal` | Mirror persisten `signal_runner.Signal` (F0b) — factor_scores JSONB per-faktor, ditulis validation harness & (nanti) live loop F7 |
| `trade_annotation` | Anotasi trade founder (real & simulasi), extended dgn kolom eksekusi nyata (leverage, fill price, fees/funding paid, exit_reason_real), `signal_id` link ke `signal` |

Tidak ada `tenant`/`platform_user`/`llm_config`/`token_package`/`tenant_token_ledger` lagi — dihapus migration 0009. Tidak ada RLS aktif di tabel manapun sekarang (dicabut migration 0009) — sistem single-operator tidak butuh isolasi antar-tenant.

---

## 5. Infra & Deploy

- **Compute**: Coolify self-hosted di VM Vultr (Docker-build based — tiap servis butuh `Dockerfile` sendiri, tidak ada Root-Directory workaround ala Railway; servis yang butuh `packages/db` harus `COPY` eksplisit ke image-nya). VM yang sama menjalankan Markoviz **tanpa dikelola Coolify** — jangan asumsikan perubahan sisi Coolify terisolasi dari itu tanpa cek `docker ps` dulu.
- **DB**: Neon Postgres, tidak berubah oleh migrasi compute. Branch default `production` (bukan `main`).
- **Migrasi**: `alembic upgrade head` wajib jadi langkah deploy eksplisit (entrypoint/startCommand) tiap servis — CI hijau di `neon-preview-branch` cuma membuktikan branch ephemeral per-PR ter-migrate, bukan `production` asli.
- Detail gotcha operasional lengkap (bug Railway lama, Neon driver, deploy Coolify): **`docs/deployment-runbook.md`** (sedang direvisi paralel, rujuk nama dokumennya, jangan duplikasi isinya di sini).

---

## 6. Roadmap Fase (kerangka ENGGANG, dgn status Kinetiq aktual)

> Tiap fase punya exit gate kuantitatif — tidak lolos gate = tidak lanjut fase berikutnya. Detail eksekusi granular (F0-F9, lebih detail dari Fase 0-5 di bawah) ada di `docs/sonnet5-implementation-roadmap.md`; hasil tiap langkah di `docs/fib-gann-validation-brief.md`.

### Fase 0 — Foundation & Diagnosis
**Tujuan**: tahu persis kenapa PF baseline 0.56/0.69 sebelum membangun apa pun baru. **Status: SELESAI.** Attribution diagnostic (IC, beta decomposition, replikasi 4 seri) sudah jalan (§2); root cause: fee belum dihitung, confidence hand-tuned anti-prediktif, tidak ada HTF-bias. Point-in-time store & look-ahead detector sudah ada di `packages/backtest-core`.

### Fase 1 — Deterministic Signal Rebuild
**Tujuan**: Layer 1 lengkap, tervalidasi per-modul. **Status: SEBAGIAN BESAR SELESAI** — fib/gann/market-structure/level-strength/htf-bias/session-bias/duration/post-stop semua sudah diimplementasi & diverifikasi thd data production (§2). **Belum**: pruning formal 7-pillar MARKOVIZ berdasarkan IC (nunggu integrasi §2 "Integrasi Markoviz" selesai diuji ulang), per-module validation harness formal (accuracy≥55% OOS ATAU IC signifikan p<0.05, tanpa bias arah) belum dijalankan sbg gate eksplisit per modul — exit gate ini masih longgar dibanding definisi ENGGANG.

### Fase 2 — Arbiter + Risk Hard Gate
**Tujuan**: dari sinyal jadi keputusan ter-gate. **Status: PARSIAL.** `fit_weights.py` (meta-model per-regime, refit per window) sudah ada tapi median AUC OOS 0.522 — **exit gate PF net ≥1.0 di ≥4/6 window BELUM diverifikasi lolos** (run pertama 2/10 window; kombinasi HTF+R:R band masih hipotesis in-sample). Risk hard gate: `execution/risk_gate.py` v1 (13 Juli 2026) sudah ADA — kill-switch, symbol-universe permission, defensive re-check R:R/entry-validity, pure function & DB-free. Regime gate & kNN risk memory veto: **desain selesai** (`docs/regime-gate-knn-risk-memory-brief.md`, 14 Juli 2026), reuse infrastruktur `gated_campaign.py`/`fit_weights.py` yang sudah ada — implementasi + validasi walk-forward nyata masih sesi terpisah, belum ada angka PF/promoted sungguhan. Exposure caps runtime (korelasi/daily-loss/cooldown) masih belum ada desain sama sekali. LLM Arbiter opsional (feature-flag OFF default, dibandingkan A/B vs meta-model murni) belum dibangun. Baseline harness (vs buy-and-hold, vs MARKOVIZ logistic lama) sebagian ada lewat `metrics.py`.

### Fase 3 — Shadow Trading (minimal 60 hari kalender)
**Tujuan**: bukti sistem hidup di data live sama dgn backtest. **Status: BELUM DIMULAI** — prasyarat (Fase 2 lolos gate PF≥1.0 di ≥4/6 window) belum terpenuhi. Building block yang sudah ada: `shadow_pair.py` (pairing + divergence attribution parsial, 6 komponen), leverage/liquidation-aware simulator. **Belum ada**: live signal writer ke tabel `signal` (F7), Telegram monitor read-only, weekly attribution report otomatis.

### Fase 4 — Live Canary (minimal 90 hari)
**Tujuan**: live dgn blast radius minimal. **Status: BELUM DIMULAI.** Kill-switch MANUAL (`RiskMandateSnapshot.kill_switch_active`, dicek `execution/risk_gate.py` v1) sudah ADA; kill-switch OTOMATIS (DD 20%→flat, daily loss limit, anomaly detector, heartbeat monitor) belum dibangun — butuh running-PnL tracking dulu. `execution/custody/` (order/position adapter, key vault) masih skeleton kosong. `position_sizing.py` (F7a, PreTradeCard) sudah ada sbg building block paralel.

### Fase 5 — Fine-Tuning Loop (kontinu, mulai Fase 3)
Ritme operasional, bukan fase terpisah: mingguan (attribution → hypothesis baru), bulanan (retrain walk-forward, weight update lewat backtest gate dulu), per-kuartal (review regime classifier, pillar pruning, evaluasi eksperimen riset). **Status: pola sudah dipraktikkan secara informal** (tiap temuan deep-dive langsung dicatat & diuji ulang — lihat riwayat panjang di §2 dan `docs/fib-gann-validation-brief.md`), tapi belum diotomasi sbg cadence terjadwal.

**Kill criteria proyek** (jujur ke diri sendiri): kalau setelah 2 siklus penuh Fase 0→2 PF OOS BTC tetap <1.0, kesimpulannya edge dari kombinasi metode saat ini tidak ada — pivot ke "infrastruktur validasi" sbg nilai yang tetap terpakai (harness, disiplin walk-forward, temuan negatif yang jujur), bukan dibuang.

---

## 7. Success Metrics & Kill Criteria per Fase

| Fase | Metrik lolos | Kill criteria |
|---|---|---|
| 0 | Root cause teridentifikasi | — (diagnosis selalu jalan) |
| 1 | Per modul: acc ≥55% OOS / IC signifikan, bias arah <65/35 | Modul <52% & tanpa IC → buang |
| 2 | PF net ≥1.0 di ≥4/6 window (ambang masuk shadow; 1.3 gate live) | Setelah 3 iterasi meta-model masih <1.0 → kembali ke Fase 1 |
| 3 | PF ≥1.3, fidelity ≥85%, DD ≤15%, 60 hari, ≥30 trade BTC | PF <1.0 selama 30 hari shadow → stop, kembali ke Fase 2 |
| 4 | PF ≥1.3, Sharpe ≥1.0, DD ≤15%, 90 hari live | DD 20% → auto-flat; PF <0.9 selama 60 hari → turun ke shadow |

Verification plan tambahan yang tetap berlaku (dari rencana sebelumnya, minus item tenant/billing): unit test connector & fallback chain, strategy backtest, risk gate, kill switch drill, **paper/live boundary test** (kritis), load/latency, disaster recovery, fib+gann backtest validation (sinyal algoritmik vs anotasi manual founder + walk-forward independen ≥90 hari sebelum live).

---

## 8. Keamanan & Guardrails

- Paper/live separation, DB-based kill switch, bounded autonomy via `risk_mandate`, liquidation protection, append-only audit ledger (`order_audit_log`).
- **Posisi LLM dikunci** (`docs/llm-telegram-guardrails-brief.md`): jalur keputusan trading 100% deterministik, LLM cuma sah utk 4 peran read-only (explain layer, hypothesis generation offline, anomaly narration, conversational interface) — tidak pernah memodifikasi state/posisi/threshold walau diminta lewat chat. Aksi finansial apa pun **tidak tersedia via Telegram sama sekali**; aksi non-finansial pun wajib command terstruktur (`/pause`, `/settings`), bukan diinterpretasi LLM.
- Model ancaman 6 kategori (prompt injection, kebocoran system prompt/IP formula, eksekusi tak sah, jailbreak konten non-trading, halusinasi angka, dst) + pertahanan 5 lapis (scope-by-construction, input gate, system prompt hardening, output gate, audit log) — spesifikasi lengkap di `docs/llm-telegram-guardrails-brief.md`, belum diimplementasi kode.
- API key venue: scoped trade-only (tanpa withdrawal), disimpan envelope-encrypted (`credential` table), tidak pernah masuk repo.
- Audit log append-only utk semua keputusan trade (input packet → gate results → order) — utk forensik & attribution, bukan cuma compliance (yang sudah tidak relevan tanpa tenant).

---

## 9. Yang Direuse vs Dibangun Baru

| Komponen | Status |
|---|---|
| Ingestion (Binance/Bybit/Hyperliquid via ccxt, fallback chain, partitioning) | ✅ Selesai & live production |
| `packages/backtest-core` (walk-forward windowing) | ✅ Selesai, dipakai `fib_gann_backtest` |
| fib/gann/market-structure/level-strength/htf-bias/session-bias/duration/post-stop skills | ✅ Selesai, diverifikasi thd data real |
| `fit_weights.py` (fitting confidence per window) | ♻️ Ada, belum lolos kriteria adopsi (AUC 0.522) |
| Swarm 4-agent Markoviz (funding/liquidation/flow) | ♻️ Digabung ke mesin riset yang sama, WAJIB diuji ulang lewat fitting yang sama sebelum dipercaya arah trade — funding/OI terbukti indikator regime, bukan prediktor arah |
| Logistic/GBM meta-model Markoviz | ♻️ Jadi baseline pembanding (bukan reuse kode langsung — beda fitur/label/model, lihat §2), diganti per-regime v2 (`fit_weights.py`) |
| Risk hard gate v1 (kill-switch, symbol-universe, R:R re-check) — `execution/risk_gate.py` | ✅ Selesai (13 Juli 2026) |
| Risk hard gate — desain regime gate + kNN risk memory (`docs/regime-gate-knn-risk-memory-brief.md`) | ✅ Desain selesai (14 Juli 2026), implementasi+validasi belum |
| Risk hard gate — exposure caps runtime (korelasi/daily-loss/cooldown) | 🆕 Belum dibangun, belum ada desain |
| Arbiter (meta-model orkestrasi + LLM arbiter opsional) | 🆕 Belum dibangun |
| Kill-switch & live canary infra | 🆕 Belum dibangun |
| Shadow simulator penuh (fidelity score, live signal writer) | 🆕 Sebagian (`shadow_pair.py`), belum lengkap |
| Telegram monitor read-only + guardrails | 🆕 Spesifikasi ada, kode belum |

---

## 10. Rekomendasi Sumber Data Derivatif

Kombinasi gratis (CCXT + native WS fallback + CoinGecko utk market-regime context) sudah cukup fungsional utk data inti. **CoinGlass** paling lengkap di kelas retail-to-pro (funding OHLC, OI aggregated, liquidation history/heatmap, long/short ratio, options Max Pain/IV, ETF flow) — dipakai tier **Hobbyist ($29/bln)**. Beda dari rencana SaaS lama: **karena sistem ini sekarang single-operator, bukan lagi dipakai melayani pelanggan berbayar, batasan ToS Hobbyist "personal use only" otomatis tetap compliant secara permanen** — tidak ada lagi keharusan upgrade ke tier Standard ($299/bln) sebelum "launch ke pelanggan" (item itu gugur bersama SaaS-nya). Catatan teknis yang tetap berlaku: Hobbyist **daily-only** (interval=1h return 403), endpoint per-pair butuh `exchange=` eksplisit, jaga jeda ~2.5 detik antar-panggilan.

Data baru dari CoinGlass yang belum masuk skema (`options_max_pain`, `etf_flow`, `on_chain_exchange_balance`) tetap dicatat sbg item eksplorasi, bukan kebutuhan MVP.

---

## 11. Budget Bulanan (estimasi kasar, skala single-operator — bukan lagi proyeksi per-tenant SaaS)

| Komponen | Estimasi |
|---|---|
| VM Vultr (Coolify + Markoviz, sunk cost — biaya inkremental Kinetiq kemungkinan kecil/nol kalau headroom cukup) | perlu audit langsung ke akun Vultr, belum diverifikasi presisi di sini |
| Neon Postgres | Launch plan usage-based ≈ $10-30/bln di skala data sekarang |
| CoinGlass Hobbyist | $29/bln (lihat §10 — permanen, tidak perlu upgrade) |
| Domain/SSL | ≈ $1/bln |
| LLM API (OpenRouter, dipakai terbatas — dev-assist & (nanti) LLM arbiter/explain read-only) | volume rendah selama belum ada arbiter/Telegram monitor berjalan |

Item lama yang gugur bersama SaaS: Clerk auth, Langfuse observability-per-tenant, biaya Midtrans/XIDR per-transaksi, KMS envelope-encryption per-tenant scaling — semua itu asumsi multi-tenant yang tidak lagi berlaku.

---

## 12. Referensi Dokumen

- `CLAUDE.md` — konvensi repo, keputusan infra terkini, aturan bahasa.
- `docs/deployment-runbook.md` — gotcha operasional Coolify/Neon/CI (sedang direvisi paralel).
- `docs/fib-gann-validation-brief.md` — spesifikasi & log validasi lengkap fib_gann_timing (rasio eksak, kalibrasi, threshold gate, seluruh riwayat eksperimen bernomor 1-36+).
- `docs/sonnet5-implementation-roadmap.md` — roadmap eksekusi granular F0-F9 (lebih detail dari Fase 0-5 di §6), rubric skor 3/10→10/10.
- `docs/validation-deep-dive-2026-07.md` — analisis walk-forward pertama + teori v2 + rubric skor.
- `docs/fable5-crypto-theory-investigation-2026-07.md` — evidence trail & status klaim (confirmed/rejected/pending).
- `docs/shadow-simulator-brief.md` — spesifikasi leverage/liquidation-aware simulator & shadow-pairing.
- `docs/llm-telegram-guardrails-brief.md` — model ancaman & spesifikasi guardrail conversational interface.
- `docs/margin-mode-brief.md` — spesifikasi margin mode (isolated MVP, cross F7b).
- `docs/vultr-vm-migration-brief.md` — histori migrasi compute Railway→Vultr VM (superseded sebagian oleh keputusan Coolify, lihat CLAUDE.md).
- `docs/ai-coding-workflow.md` — konvensi sesi coding AI di repo ini (alignment→planning→execution→review).

---

*Dokumen ini living document — di-update tiap ada keputusan arsitektur/progres nyata, bukan snapshot statis. Jangan biarkan drift jadi log debugging murni; detail granular tetap tempatnya di dokumen-dokumen §12.*
