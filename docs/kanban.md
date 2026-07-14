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
- [ ] **Risk Hard Gate — regime gate + kNN risk memory** — 2 dari 4
  sub-gate ENGGANG di `docs/prd.md` masih belum bisa dibangun bertanggung
  jawab: regime gate (FREEZE/RISK_OFF) belum ada classifier-nya sama
  sekali (`market_regime.py` belum ada), dan kNN risk memory belum ada
  spec apapun (belum ada feature list/distance metric/k value/threshold
  veto di dokumen manapun) plus histori trade real (`trade_annotation`)
  masih terlalu sedikit untuk membangun "kemiripan ke historical losses"
  yang berarti. Masing-masing butuh sesi desain terpisah dulu sebelum
  jadi slice implementasi. Juga belum ada: daily-loss-limit/drawdown
  (`Position`/`OrderAuditLog` belum tracking running-PnL) dan
  correlation-based exposure cap (butuh multi-position tracking, sudah
  dideferred ke F7b di `margin-mode-brief.md`). Path CODEOWNERS-protected,
  wajib human-in-the-loop penuh.
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

(Semua yang terjadi sebelum 7 Juli 2026 dilacak lewat task list milik
sesi masing-masing, bukan lewat board ini.)
