# PRD + Rencana Teknis: Kinetiq — Multi-Agent AI Trading SaaS

**Nama bisnis terpilih: "Kinetiq"** (dari "kinetic" — sejalan analogi fisika pasar milik founder: waktu, jarak/harga, momentum/volume). Repo GitHub (`agent-trading-perp`) akan di-rename mengikuti nama ini setelah rencana ini di-approve (lihat Section C.4).

## Context

Proyek ini awalnya dirancang sebagai bot trading perpetual futures pribadi, penerus dari bot lama user ("Markoviz" / `ai-perp-bot-core`), dengan acuan arsitektur [HKUDS/Vibe-Trading](https://github.com/HKUDS/Vibe-Trading). Setelah diskusi lebih lanjut, scope berubah signifikan:

1. **User adalah trader perp aktif 5 tahun** dengan track record nyata (profit $30→$1000 dalam 1 minggu, peak $1000→$10.000), mengandalkan **Fibonacci retracement (modifikasi) + Gann Fan** sebagai metode entry-timing utama, sebelumnya di MEXC (high leverage), sekarang migrasi ke Binance untuk kualitas data.
2. User punya **teori pasar sendiri**: pola musiman per timeframe yang saling berkaitan lintas timeframe (analogi "meta" game — ada yang "di-buff/di-nerf" secara temporer), dan analogi fisika (waktu, jarak/harga, volume/berat) untuk menjelaskan bagaimana perilaku seluruh partisipan pasar (retail, institusi, whale) tercermin di chart. Observasi pasar: altseason belum terbentuk cycle ini meski BTC sudah ATH.
3. **Pivot scope**: bukan lagi bot pribadi single-asset, tapi **platform SaaS multi-agent** yang mencakup spot, perp/futures, meme-sniper, dan DLMM (liquidity provision) — dengan alasan bisnis: banyak trader mau bayar untuk bot semacam ini, apalagi era tokenisasi saham/equity akan memperluas pasar.
4. Keputusan bisnis yang sudah dikonfirmasi user: **(a)** monetisasi = subscription, **non-custodial** (user pegang API key/wallet sendiri, kita tidak pernah pegang dana — menghindari beban regulasi custodian/fund manager); **(b)** MVP = **Perp + Spot dulu**, Meme-sniper & DLMM menyusul sebagai modul agent terpisah; **(c)** dua tier layanan: **signal-only** (alert, tanpa eksekusi) dan **auto-execute** (eksekusi penuh via API key/wallet user).

Repo saat ini kosong total (belum ada commit) — ini rencana greenfield, branch `claude/trading-bot-architecture-tp2vzj`.

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
- **Akun superadmin (founder/personal use)**: role `superadmin` (bukan sekadar admin) yang bypass billing/plan-gating dan pakai resource/API-key/LLM budget milik founder sendiri — dipakai user utk pemakaian pribadi sejak hari pertama tanpa perlu berlangganan produk sendiri. Saat pelanggan baru subscribe & bayar via Stripe, akun `tenant` baru otomatis ter-provision dgn plan sesuai pembayaran — alur self-serve, tidak perlu setup manual (lihat B.13).
- Harga & billing engine: Stripe subscriptions, plan gating di level API (`packages/config` + middleware `apps/platform-core/api-gateway/deps.py`), usage metering per tenant (jumlah agent aktif, jumlah exchange terhubung) untuk tier-based limit.
- **Legal workstream (di luar scope teknis, wajib sebelum go-live)**: ToS/disclaimer "not financial advice", data privacy (API key encryption at rest sudah didesain), cek regulasi per-yurisdiksi target (banyak negara mengatur "trading bot" atau "signal service" berbeda dari investment advisory selama non-custodial & user execute sendiri keputusan — tapi ini butuh review hukum aktual, bukan asumsi saya).

### A.4 Cakupan Fitur per Fase (product view — detail teknis di Part B.9)

| Fase | Fitur produk |
|---|---|
| MVP | **Sudah berbentuk bisnis penuh sejak awal**: web app minimal (signup/login, subscribe & bayar via Stripe, superadmin & admin panel) + Telegram signal-tier + Perp & Spot agent + paper trading + Fib+Gann timing overlay + Markowitz-extended portfolio suggestion + agent belajar penuh dari gaya trading founder (lihat B.6b) |
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
| Auth & Billing | Auth: Clerk atau Auth.js (session/JWT) — pilih Clerk kalau mau cepat (built-in org/user management cocok utk B2C SaaS). Billing: Stripe Subscriptions + Stripe usage records utk metering, di-model per **product+tier** (`trading:signal_only`, `trading:auto_execute`, dst) bukan hardcode trading | standar industri SaaS; product+tier model supaya siap ditambah vertical baru (exam/chatbot/content) tanpa rombak billing |
| Platform Core vs Product Vertical | Pisahkan `apps/platform-core/*` (tenant, auth, billing, agent-registry, LLM gateway, notification — agent-agnostic) dari `apps/products/trading/*` (spesifik trading) | visi bisnis user: trading = vertical pertama, agent exam/chatbot/content-creator/task menyusul sbg vertical baru yang reuse Platform Core (lihat A.6) |
| Time-series | Native Postgres range-partitioning by time (manual, dikelola Inngest) + TimescaleDB (Apache-2, tanpa compression) opsional | Neon dukung timescaledb sejak PG18 (Feb 2026) tapi tanpa compression/tiering — partitioning manual jadi primary bet (terverifikasi) |
| Orchestration | **Inngest self-hosted di Railway** | self-hosting resmi sejak Inngest 1.0 (terverifikasi), event-driven step function pas utk pola ingest→trigger; dievaluasi vs Trigger.dev/Temporal Cloud/custom-queue-di-Neon dan ditolak (lihat plan versi sebelumnya utk detail — Neon PgBouncer transaction-mode tidak support LISTEN/NOTIFY) |
| LLM Observability | **Langfuse Cloud** (bukan self-host) utk MVP | self-host Langfuse butuh 6 container, beban ops besar drpd benefit di tahap ini |
| CEX data/exec | CCXT + CCXT Pro (WS) unified, native WS fallback per exchange utk liquidation feed | 100+ exchange, minim maintenance |
| DEX data/exec | Native SDK per protokol: Hyperliquid, dYdX v4, GMX, Vertex, Drift (perp); Meteora DLMM SDK (LP); Solana/EVM new-pair listener (meme-sniper) | tidak ada unifikasi matang utk on-chain |
| Backend | Python 3.11+ (FastAPI, LangGraph) utk data layer, strategy engine, agent orchestration | ekosistem quant/ML, ikut pola Vibe-Trading |
| Job glue & frontend | TypeScript: Inngest functions + Next.js dashboard + billing webhook handler | konsisten dgn pola Vibe-Trading |
| Interface MVP | Telegram bot (signal tier) | latency rendah, effort kecil, akses darimana saja |
| Interface lanjutan | Web dashboard (Next.js, + billing/plan management) → Mobile app | dashboard utk riset/backtest visual + subscription management |
| Custody | Non-custodial per-tenant: API key trade-only/no-withdraw (CEX), agent-wallet/session-key (DEX), envelope encryption per-tenant (data key unik per tenant, master key di KMS/Railway secret) | dikonfirmasi user; isolasi per-tenant mencegah satu key bocor berdampak ke tenant lain |
| LLM Provider | **OpenRouter** sbg provider utama (satu API key, akses banyak model/vendor sekaligus) diakses lewat `platform-core/llm-gateway`, dgn adapter interface tetap provider-agnostic (bisa tambah direct OpenAI/Anthropic/DeepSeek API key nanti tanpa ubah kontrak) | dikonfirmasi user (paket all-in-one OpenRouter), plus jaga fleksibilitas kalau nanti mau direct API utk model tertentu (lebih murah/cepat) |
| Role & Access | 3 level: **superadmin** (founder, bypass billing, pakai resource sendiri, kontrol penuh konfigurasi platform) — **admin** (mengatur LLM/model per agent & per tier, feature flag, monitoring — bisa didelegasikan ke tim nanti) — **tenant/customer** (subscriber biasa, akses sesuai plan yg dibayar) | wajib disebut eksplisit oleh user; jadi dasar `llm_config` dinamis per agent (lihat B.13) |

### B.2 Struktur Direktori (Platform Core generik + Trading sbg product vertical pertama)

```
agent-trading-perp/
├── apps/
│   ├── platform-core/               # AGENT-AGNOSTIC — reusable utk vertical apapun (trading, exam, chatbot, dst)
│   │   ├── api-gateway/             # FastAPI: tenant auth middleware, product+tier plan-gating, routing ke tiap product API
│   │   ├── billing/                 # Stripe webhook handler, subscription state sync -> Neon (per product+tier)
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
│           └── telegram-bot/               # MVP interface, plan-gated command via platform-core notification
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
    stripe_customer_id TEXT,
    stripe_subscription_status TEXT,
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

0. **Bootstrap + Platform Core minimal** (2-3 minggu): monorepo, CI, Railway+Neon, migration awal (termasuk `tenant`/RLS/`role`/`llm_config` dari hari pertama), Inngest self-host, Langfuse Cloud, **web app minimal** (auth via Clerk, halaman signup, Stripe checkout, superadmin+admin panel dasar termasuk konfigurasi LLM per agent — lihat B.13), akun superadmin founder dibuat manual sbg langkah setup pertama.
1. **MVP Data Layer** (2-3 minggu, bisa paralel dgn fase 0 bagian akhir): 2 CEX (Binance, Bybit) + 1 DEX perp (Hyperliquid) connector, fallback chain, partitioning otomatis.
2. **Strategy & Paper Trading + Trader Profile** (3-4 minggu): `markowitz_perp` + `markowitz_spot` + `risk_parity` + **`fib_gann_timing`** + **`market_regime`** + **`trader_profile`/anotasi founder (B.6b)**, backtest funding-aware, LangGraph rebalance graph (paper only), risk gate.
3. **Signal Tier Launch** (1-2 minggu, paralel fase 2): Telegram bot signal-only terhubung ke tenant yg sudah subscribe via web app fase 0 — **first revenue milestone** (founder sendiri jadi user pertama via akun superadmin, tanpa perlu bayar).
4. **Auto-Execute Tier** (2-3 minggu): execution live perp+spot (testnet→mainnet notional kecil), per-tenant custody, kill switch battle-tested dari paper, billing gate utk tier ini.
5. **Web Dashboard Lengkap** (2-3 minggu): Next.js — positions, equity curve, trade-annotation UI (utk B.6b), plan/billing management self-serve penuh.
6. **Meme-Sniper Module (V2)** (3-4 minggu): new-pair listener (Solana + 1 EVM chain), token_safety_score, snipe execution, add-on tier terpisah, **agent-registry** tinggal daftarkan module baru (bukti "kemudahan tambah agent baru" dari A.6/B.13).
7. **DLMM Module (V3)** (3-4 minggu): Meteora integration, IL/fee tracking, auto-rebalance range.
8. **Ekspansi (ongoing/eksplorasi)**: exchange/DEX lain, mobile app, tokenized equity (reuse pola broker-connector Vibe-Trading, mis. Alpaca), prediction market, vertical non-trading (agent exam/chatbot/content-creator/task — tinggal tambah `apps/products/<vertical>/` baru, reuse Platform Core). NFT/GameDefi tidak masuk roadmap kecuali ada validasi demand baru.

### B.10 Verification Plan (tambahan dari rencana sebelumnya)
Semua poin verification sebelumnya (unit test connector, fallback chain, strategy backtest, risk gate, kill switch drill, Inngest retry test, Langfuse trace, **paper/live boundary test — kritis**, load/latency, disaster recovery) **tetap berlaku**, ditambah:

12. **Tenant isolation test**: 2 tenant dummy, assert query salah satu tenant tidak pernah mengembalikan row tenant lain (test RLS langsung, bukan cuma via ORM).
13. **Billing/plan-gating test**: assert user di plan `signal_only` tidak bisa hit endpoint auto-execute (403), assert webhook Stripe downgrade plan langsung mematikan akses fitur terkait dalam SLA singkat.
14. **Fib+Gann backtest validation**: bandingkan sinyal algoritmik vs anotasi manual user pada sample chart historis (sanity check bahwa formalisasi merepresentasikan metode aslinya), lalu walk-forward test independen ≥ 90 hari sebelum dipakai live.
15. **Token safety gate test**: fixture token dgn kombinasi flag (liquidity unlocked, mint not renounced, honeypot simulasi gagal) → assert snipe di-block di setiap kasus, tidak ada bypass.

### B.11 Rekomendasi Sumber Data Derivatif (harga vs kelengkapan vs kecepatan)

Sudah diverifikasi via riset terkini (bukan asumsi lama): **CCXT Pro sudah digabung jadi bagian gratis CCXT sejak versi 1.95+** (WebSocket untuk 100+ exchange, termasuk funding rate/OI/orderbook, tanpa biaya lisensi terpisah) — jadi biaya data CEX inti tetap $0 di luar compute.

| Sumber | Cakupan | Harga | Kelengkapan | Kecepatan/Infra | Rekomendasi peran |
|---|---|---|---|---|---|
| **CCXT (+ built-in WS)** | 100+ CEX: funding rate, OI, orderbook, trades | Gratis (open-source) | Tinggi utk CEX, tidak cover DEX/on-chain | WS native per-exchange, cukup cepat, tapi kualitas antar-exchange tidak seragam | **Primary source CEX** (sudah di rencana) |
| **Native exchange WS/REST** (Binance, Bybit, OKX) | Fallback per-exchange, termasuk liquidation stream yg tidak selalu ada di CCXT | Gratis | Tinggi (data langsung dari sumber) | Tercepat (tanpa layer abstraksi), tapi maintenance per-exchange lebih besar | **Fallback wajib** utk liquidation feed & data yg CCXT belum cover |
| **Coinalyze API** | Funding rate, OI, liquidation, long/short ratio — agregat lintas exchange | Gratis (syarat: cantumkan atribusi sumber) | Bagus utk cross-check/cross-exchange view, tapi retensi intraday terbatas (~1500-2000 datapoint, di-hapus harian) & rate limit 40 req/menit | Cukup cepat utk polling interval menitan, bukan utk real-time tick | **Cross-check/fallback murah** — bagus dipakai di Fase 1-2 sblm ada budget data premium |
| **CoinGlass API** | Funding rate, OI, liquidation heatmap, long/short ratio, options, L2/L3 orderbook — cakupan paling lengkap & institutional-grade | Berbayar: Hobbyist $29/bln, Startup $79/bln, Standard $299/bln, Professional $699/bln (tahunan lebih murah) | Paling lengkap di kelas retail-to-pro, sering jadi rujukan trader utk liquidation heatmap | Infra cepat, dirancang utk institutional/quant use-case | **Upgrade opsional saat scale** (Fase 4+/6, terutama utk meme-sniper & liquidation heatmap presisi) — mulai dari tier Hobbyist $29/bln |
| **CoinGecko / CoinMarketCap API** | BTC dominance, Altcoin Season Index, market cap ranking | Free tier tersedia (CoinGecko Demo/CMC Basic) | Cukup utk kebutuhan `market_regime` skill (bukan tick-level) | Cepat, cache-friendly (data ini tidak perlu real-time) | **Primary source utk market_regime skill** |
| **GoPlus Security API / Honeypot.is** | Token safety check (mint authority, liquidity lock, honeypot simulation) utk meme-sniper | Free tier tersedia, paid tier utk volume tinggi | Cukup utk gate keamanan dasar | Perlu low-latency krn snipe window singkat (detik) — cek keduanya paralel utk redundansi | **Wajib** utk `token_safety_score` skill (Fase 6) |
| **DexScreener / Birdeye API** | New-pair listing, harga real-time multichain (meme-sniper) | DexScreener gratis (rate-limited); Birdeye ada tier berbayar utk kecepatan lebih tinggi | Baik utk deteksi awal | DexScreener cukup utk MVP meme-sniper; Birdeye kalau butuh latency lebih rendah saat scale | **DexScreener dulu (gratis)**, upgrade Birdeye kalau latency jadi bottleneck |

**Prinsip budget data**: kombinasi gratis (CCXT + native WS + Coinalyze + CoinGecko + DexScreener/GoPlus) sudah cukup lengkap secara fungsional. **Karena user sudah menyiapkan budget khusus utk akurasi data** (bukan cuma bootstrap seminimal mungkin), rekomendasi direvisi: mulai **CoinGlass tier Hobbyist ($29/bln)** langsung dari **Fase 1 (MVP Data Layer)**, bukan ditunda ke Fase 4 — alasan: cross-exchange liquidation heatmap & OI presisi tinggi langsung menambah kualitas sinyal `fib_gann_timing`/`market_regime` sejak awal, dan $29/bln relatif kecil dibanding potensi dampaknya ke akurasi (yg secara eksplisit jadi prioritas user: "akurasi sinyal dan eksekusi profitable"). Naikkan ke tier Startup ($79/bln) begitu masuk Fase 6 (meme-sniper, butuh cakupan token lebih luas & rate limit lebih tinggi).

### B.12 Rencana Budget Bulanan (estimasi, harga terverifikasi Juli 2026)

| Komponen | MVP (Fase 0-3, low traffic) | Growth (Fase 4-7, live trading + meme-sniper) |
|---|---|---|
| Railway (compute multi-service: api, ingestion, agent-orchestrator, execution, inngest, telegram-bot, dashboard) | Pro plan $20/bln + usage ≈ **$50-100/bln** | Usage naik seiring service & traffic ≈ **$150-400/bln** |
| Neon Postgres | Launch plan usage-based (compute $0.106/CU-hr, storage $0.35/GB-bln, tanpa minimum bulanan) ≈ **$10-30/bln** | Scale plan ($0.222/CU-hr, SLA 99.95%) seiring volume time-series naik ≈ **$100-300/bln** |
| Inngest self-host | Hanya compute (masuk Railway di atas) + optional Redis addon ≈ **$0-15/bln** | sama, naik sedikit seiring service | **$10-30/bln** |
| Langfuse | Hobby (gratis, 50rb unit/bln) ≈ **$0** | Core $29/bln atau Pro $199/bln (kalau butuh retensi lebih lama/compliance) | **$29-199/bln** |
| Data derivatif | CCXT + native WS + Coinalyze + CoinGecko (gratis) **+ CoinGlass Hobbyist** (direvisi masuk MVP krn budget sudah disiapkan) ≈ **$29/bln** | CoinGlass Startup begitu masuk Fase 6 (meme-sniper) ≈ **$79/bln** |
| Auth (Clerk) | Free tier ≈ **$0** | Paid tier seiring MAU naik ≈ **$25-100/bln** |
| KMS (envelope encryption master key) | ≈ **$1-5/bln** | ≈ **$5-15/bln** |
| Stripe | Tanpa biaya bulanan, 2.9%+$0.30 per transaksi | sama (scales with revenue) |
| Domain/SSL | ≈ **$1/bln** (tahunan) | sama |
| LLM API (via OpenRouter — model murah/cepat utk task rutin, model lebih mahal khusus keputusan strategi) | **$20-50/bln** (volume rendah, testing/founder-only) | **$200-1000+/bln** — **variable cost terbesar**, tergantung jumlah tenant aktif & frekuensi agent invocation |
| **Total estimasi** | **≈ $115-230/bln** | **≈ $600-2150+/bln** (didominasi LLM usage saat tenant bertambah) |

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

**Keputusan: "Kinetiq"** — dipilih user. Repo GitHub `agent-trading-perp` akan di-rename ke `kinetiq` (atau variasi serupa, dikonfirmasi saat eksekusi) setelah rencana ini di-approve.

---

### Critical Files untuk Implementasi
- `packages/db/models.py` + migrations — skema lengkap termasuk `tenant`, RLS policy (Section B.3/B.4)
- `apps/platform-core/api-gateway/deps.py` — tenant context middleware + product+tier plan-gating (dasar isolasi SaaS & fondasi multi-vertical, Section A.6/B.2)
- `apps/platform-core/llm-gateway/` — abstraksi provider LLM + cost tracking, dipakai semua vertical (trading sekarang, exam/chatbot/content-creator nanti)
- `apps/products/trading/agent-orchestrator/skills/strategy/fib_gann_timing.py` — formalisasi metode trading user, paling sensitif secara bisnis (core IP)
- `apps/products/trading/agent-orchestrator/graphs/portfolio_rebalance_graph.py` — mengikat strategy engine + risk gate + execution (perp & spot)
- `apps/products/trading/execution/risk_gate.py` — mandatory checkpoint guardrail
- `apps/platform-core/billing/` — Stripe webhook → tenant.plan_tier sync per product, dasar monetisasi
- `apps/platform-core/llm-gateway/resolve_config.py` — resolve `llm_config` hierarchy (tenant→product→global) & panggil OpenRouter, dasar fleksibilitas model per agent (Section B.13)
- `apps/products/trading/agent-orchestrator/skills/strategy/trader_profile.py` — kalibrasi `fib_gann_timing` terhadap anotasi trading founder (Section B.6b)
- `apps/platform-core/agent-sdk/base_agent_graph.py` — kontrak dasar LangGraph yang dipakai ulang semua vertical (Section C.1)
- `apps/platform-core/mcp-server/` — expose skill registry sbg MCP tools (Section C.2)
- `.github/workflows/ci.yml` + `.github/workflows/deploy.yml` — CI dgn Neon branch-per-PR, auto-merge dgn pengecualian path sensitif (Section C.3)
- `infra/neon/partitioning/*.sql` — strategi partitioning time-series
