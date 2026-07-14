# Kanban — Tracer-Bullet Slices

Menu task yang dirujuk oleh `docs/ai-coding-workflow.md` Section 2.2/2.3.
**Satu slice = satu sesi Claude Code** — jangan campur dua card dalam satu
sesi, jangan bawa satu sesi lintas card. Pilih satu card, baca section
`docs/prd.md` yang direferensikan card itu untuk spec/keputusan sebenarnya
(board ini sengaja tidak mengulang isinya), ikuti checklist workflow,
lalu pindahkan ke Done dan tambahkan card lanjutan apa pun yang muncul
dari situ.

Card yang belum punya acceptance test yang jelas perlu sesi scoping/
"grill-me" dulu (workflow doc Section 1.1) sebelum sesi implementasi
dibuka untuk card tersebut.

**13 Juli 2026**: scope Kinetiq dipangkas ke single-operator agentic
trading system (`apps/platform-core/*` dihapus, lihat `CLAUDE.md`), dan
compute pindah Railway -> Coolify. Card-card lama yang soal RBAC per
subscription/billing/dashboard-per-agent/multi-agent dashboard shell
dihapus dari board ini karena konsepnya sendiri sudah tidak berlaku
(tidak ada tenant/subscription lagi) — bukan cuma "diskip", tapi memang
sudah tidak relevan.

## To Do

- [ ] **Validasi perp/futures untuk pola Markoviz swarm** — pola
  `vibe-trading-ai` sudah tervalidasi untuk spot; jalankan walk-forward/
  PF-net-of-fees/bootstrap-CI dengan tingkat ketelitian yang sama seperti
  yang sudah dipakai untuk `fib_gann_timing`, sebelum pola ini dipercaya
  untuk perp/futures atau digabungkan ke shared research engine.
  Refs: `docs/prd.md` (bagian integrasi Markoviz), `docs/fib-gann-validation-brief.md`.
- [ ] **Redesain Telegram signal card / trading status / analysis UI** —
  Telegram UI `ai-perp-bot-core` yang sekarang belum sesuai kebutuhan
  Kinetiq (read-only monitor, 5-layer guardrails); ini bukan sekadar port
  langsung, tapi benar-benar redesign. Refs: `docs/prd.md`
  (bagian shadow trading / Telegram monitor).
- [ ] **Risk Hard Gate — regime gate & kNN risk memory: putuskan langkah
  lanjutan setelah validasi walk-forward NYATA GAGAL promosi** (validasi
  selesai 14 Juli 2026, angka lengkap di Done + `docs/validation-results/
  gated_campaign.json`) — **kedua gate TIDAK lolos** kriteria adopsi
  apapun di 4 seri produksi asli dengan setting default brief. Opsi yang
  belum diputuskan: (a) sweep `knn_k`/`knn_loss_threshold` (brief §4 sudah
  usulkan grid k∈{5,10,20}, threshold∈{0.5,0.6,0.7} — belum pernah
  dijalankan, base rate SL corpus ~52% bikin threshold 0.6 diduga
  terlalu rendah), (b) sweep `RISK_OFF_VOLATILITY_PERCENTILE`/
  `FREEZE_VOLATILITY_PERCENTILE`, (c) ukur dampak drawdown/tail-risk
  langsung (bukan cuma PF net) utk `volatility_regime_only` sesuai bar
  dua-bagian brief §3 yang belum pernah dihitung, atau (d) deprioritas
  pendekatan ini dan alokasikan sesi ke card lain. TIDAK ADA yang di-wire
  ke `execution/risk_gate.py` — itu tetap menunggu evidence positif dulu.
  Juga belum ada: daily-loss-limit/drawdown (`Position`/`OrderAuditLog`
  belum tracking running-PnL) dan correlation-based exposure cap (butuh
  multi-position tracking, sudah dideferred ke F7b di
  `margin-mode-brief.md`) — 2 sub-gate ini beda kelas masalah, tetap di
  luar scope brief di atas. Path CODEOWNERS-protected, wajib
  human-in-the-loop penuh begitu masuk implementasi.
- [ ] **Arbiter / meta-model v2 per-regime** — `agent-orchestrator/graphs/`
  masih kosong; baseline yang ada sekarang cuma logistic meta-model lama
  (sudah dikonfirmasi anti-prediktif, lihat `CLAUDE.md`). Refs:
  `docs/prd.md` (bagian arbiter), `docs/sonnet5-implementation-roadmap.md`
  Fase 3 (fit weights).
- [ ] **Deploy service trading lain ke Coolify begitu kodenya nyata** —
  `agent-orchestrator`/`execution`/`telegram-bot` masih skeleton/sebagian;
  ikuti pola `apps/products/trading/ingestion/Dockerfile` (Base Directory
  = repo root, COPY sibling module yang benar-benar dipakai) begitu ada
  yang siap dideploy. Refs: `docs/deployment-runbook.md` (Gotcha Coolify).

## Perlu didiskusikan dulu sebelum jadi slice

- **"vibe-trading kasih analisis tiap 4 jam"** — masih ambigu, belum jelas:
  apakah ini pola cron yang sudah ada di `vibe-trading-ai`/swarm config,
  atau perilaku reporting baru dari research engine Kinetiq (mis. weekly
  attribution report ala ENGGANG Fase 3)? Refs: `docs/prd.md`.
- **Migrasi kode/logic Markoviz masuk `apps/products/trading/*`** — beda
  dari migrasi infra (sudah selesai, Markoviz tetap jalan sbg proses
  Docker-nya sendiri di VM yang sama, unmanaged Coolify); ini soal
  kode/logic swarm digabung ke research engine. Refs: `docs/prd.md`.
- **Performa multi-timeframe research engine** — perlu sesi
  riset/implementasi khusus tersendiri. Refs: `docs/prd.md`.

## Done

- [x] **Audit VM Vultr yang sudah live (Markoviz)** — read-only, cek
  resource headroom (RAM 3.1Gi free/5.4Gi available, disk 125G/150G
  free, 4 vCPU) dan `docker ps` (Markoviz jalan sbg
  `ai-perp-bot-core-agent-1`/`-sidecar-1`, unmanaged Coolify, port
  internal-only — tidak ada konflik). 13 Juli 2026.
- [x] **Setup Coolify (project `kinetiq` + application
  `kinetiq-ingestion-worker`)** — menggantikan rencana docker-compose +
  Nginx + cron-polling manual (`docs/vultr-vm-migration-brief.md`) dengan
  Coolify self-hosted yang sudah terinstal di VM yang sama. Dockerfile-
  based deploy, terverifikasi live: menulis `funding_rate`/`ohlcv` nyata
  ke production Neon. 13 Juli 2026.
- [x] **Migration-runner Coolify** (`kinetiq-migration-runner` + Scheduled
  Task `alembic upgrade head` tiap 10 menit) — menutup gap sejak
  `api-gateway` dihapus. Standalone resource, sengaja tidak ditempel ke
  service lain (supaya tidak hilang lagi kalau service itu suatu saat
  dihapus/diganti — persis bug yang lagi ditutup ini). Terverifikasi:
  cron fire pertama sukses connect ke production Neon asli. 13 Juli 2026.
- [x] **On-chain BTC exchange flow ingestion (Arkham Intel API)** —
  tabel `onchain_exchange_flow` (collect-only, belum di-wire ke
  signal/confidence), 5 entity default (binance/coinbase/okx/bybit/
  kraken), histori harian penuh sejak 2012-2018. Data real transaksi
  on-chain (bukan data sintetis) -- tapi tetap perlu divalidasi
  korelasinya ke pergerakan harga sebelum dipakai sbg faktor sinyal,
  sama seperti faktor lain (lihat catatan `ConfluenceWeights`). Refs:
  `docs/prd.md`. 13 Juli 2026.
- [x] **Domain Coolify: pakai `*.sslip.io` bawaan dulu** (keputusan
  founder, 13 Juli 2026) — `kinetiq.app` custom domain ditunda, bukan
  dibatalkan.
- [x] **Risk Hard Gate v1** (`apps/products/trading/execution/risk_gate.py`)
  — kill-switch, symbol-universe permission, dan defensive re-check
  R:R/entry-validity (invariant yang sebenarnya sudah dijamin
  `generate_signals()`, dicek ulang di sini sebagai "trust but verify" di
  jalur safety-critical). Pure function, DB-free, tidak import tipe
  `Signal`/`ExitPlan` dari `agent-orchestrator` (tidak ada precedent
  cross-app import di repo ini) — pakai `RiskMandateSnapshot` sendiri.
  Semua rejection dikumpulkan (tidak fail-fast), sesuai audit-transparency
  ethos proyek ini. Regime gate + kNN risk memory + daily-loss + exposure
  cap sengaja TIDAK termasuk di sini (lihat card To Do di atas). Path
  CODEOWNERS-protected, PR wajib human-in-the-loop review. 13 Juli 2026.
- [x] **Desain regime gate + kNN risk memory** (`docs/regime-gate-knn-
  risk-memory-brief.md`) — brief lengkap: pemisahan tegas regime-direction
  gate (sudah ada, sudah GAGAL kriteria promosi 34% vs ambang 66,66%) vs
  regime gate PRD (volatilitas FREEZE/RISK_OFF, baru didesain);
  classifier causal + fallback OI-fuel; kNN atas corpus 2.679 trade
  simulasi (bukan 276 baris `trade_annotation` yang terlalu tipis);
  jalur validasi reuse `gated_campaign.py`/`fit_weights.py`; jalur ke
  produksi eksplisit setelah lolos adopsi. Docs-only, belum ada kode/
  validasi nyata — itu jadi card implementasi terpisah di To Do. 14 Juli
  2026.
- [x] **Kode `volatility_regime_only` + `knn_risk_memory_only`
  (`gated_campaign.py`)** — implementasi persis sesuai
  `docs/regime-gate-knn-risk-memory-brief.md`: `realized_volatility()`/
  `volatility_regime_by_signal_index()` (causal, percentile trailing thd
  populasi volatilitas sebelumnya), `_fit_knn_risk_memory()`/
  `_knn_loss_fraction()` (`sklearn.neighbors.NearestNeighbors` atas corpus
  2.679 trade `fit_weights.py`, bukan `trade_annotation`). Keduanya jadi
  `GateConfig` baru (`volatility_regime_only`, `knn_risk_memory_only`) +
  `SizingConfig` baru (`volatility_regime_sizing`, size-down RISK_OFF/
  FREEZE, komposisi dgn `confidence_sizing`, tidak pernah menaikkan size).
  24 test baru (data sintetis) + 75/75 test `test_gated_campaign.py`
  lolos, `ruff` bersih. 14 Juli 2026.
- [x] **Validasi walk-forward NYATA: `volatility_regime_only` +
  `knn_risk_memory_only` — HASIL: TIDAK LOLOS promosi** (data real 4 seri
  produksi, `docs/validation-results/gated_campaign.json`, 14 Juli 2026,
  founder menyediakan `DATABASE_URL` `kinetiq_app` -- role read-only ini
  cukup krn cuma perlu SELECT, tidak perlu DDL `neondb_owner`; koneksi
  Postgres mentah tetap menggantung dari sandbox seperti biasa, dipakai
  Neon HTTP-SQL endpoint sbg jalur baca). Data: BTC/ETH x Binance/Bybit,
  ~26.640 candle/seri (2023-06-30 s/d hari ini, ~3 tahun -- lebih panjang
  dari catatan lama), `campaign.CAMPAIGN_CONFIGS[1]` (kandidat F5), 35
  window/seri.
  - **`volatility_regime_only`**: PF net turun tipis di 3/4 seri
    (binance_BTC 0.920→0.881, bybit_BTC 0.938→0.904, bybit_ETH
    1.046→1.027) dan nyaris sama di 1 (binance_ETH 1.039→1.026 tapi
    window lolos naik 10→11). Window lolos PF tertinggi cuma 11/35 (31%),
    jauh di bawah ambang 66,66% -- **`promoted=False` di semua seri**.
    Belum ada bukti manfaat nyata dgn threshold awal (P90/P97,5).
  - **`knn_risk_memory_only`**: veto rate EKSTREM (89-93% sinyal test
    di-veto) di ke-4 seri, DAN PF net LEBIH BURUK dari baseline di
    SEMUA 4 seri tanpa kecuali (paling parah bybit_ETH: 1.046→0.719).
    **`promoted=False` di semua seri.** Veto serapuh ini mengindikasikan
    `KNN_DEFAULT_LOSS_THRESHOLD=0.6` kemungkinan terlalu rendah utk data
    real -- base rate STOP_LOSS di corpus historis ~52% (2.679 trade,
    `CLAUDE.md`), jadi ambang 0.6 gampang terpicu di hampir semua sinyal.
  - **Kesimpulan: kedua gate TIDAK di-wire ke `execution/risk_gate.py`** --
    persis disiplin proyek ini (`ConfluenceWeights` lesson): desain yang
    kelihatan masuk akal tetap harus tunduk ke bukti nyata, bukan
    diasumsikan benar. Langkah lanjutan (sweep threshold, ukur drawdown
    langsung, atau deprioritaskan) belum diputuskan -- lihat card To Do.

(Semua yang terjadi sebelum 7 Juli 2026 dilacak lewat task list milik
sesi masing-masing, bukan lewat board ini.)
