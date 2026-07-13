# Kinetiq

Sistem trading agentic single-operator (BTC perp lebih dulu) — modul sinyal deterministik -> arbiter -> risk hard gate -> shadow trading -> live canary, dengan disiplin validasi walk-forward OOS yang ketat. Bukan lagi SaaS multi-tenant: `apps/platform-core/*` dan layer tenant/RLS di database dihapus 13 Juli 2026 saat scope dipersempit ke fokus tunggal ini.

Lihat **`docs/prd.md`** untuk PRD + rencana teknis lengkap (arsitektur, data model, roadmap fase, dan keputusan desain), dan **`docs/deployment-runbook.md`** untuk gotcha operasional Coolify/Neon/CI (wajib dibaca sebelum ubah config deploy atau `.github/workflows/ci.yml`). `CLAUDE.md` merangkum poin-poin kritisnya utk sesi Claude Code berikutnya.

## Struktur Repo

```
apps/
  products/trading/  # satu-satunya vertical: ingestion, agent-orchestrator, strategy-engine, execution, inngest-functions, dashboard, telegram-bot
packages/
  schemas/           # Pydantic + Zod data contracts
  db/                # SQLAlchemy models + Alembic migrations
  config/            # shared env/feature-flag config
infra/
  neon/              # migrations + time-series partitioning scripts
docs/
  prd.md               # PRD + rencana teknis (sumber kebenaran)
  deployment-runbook.md  # gotcha operasional Coolify/Neon/CI, dari kejadian nyata
CLAUDE.md            # ringkasan memory utk sesi Claude Code
```

Setiap direktori `apps/**` punya `README.md` singkat yang menjelaskan tanggung jawabnya dan merujuk ke bagian PRD yang relevan.

## Status

Compute pindah dari Railway ke Coolify self-hosted di VM Vultr (13 Juli 2026) bersamaan dengan pemangkasan scope ke single-operator trading agentic. Lihat "Status Implementasi" di `docs/prd.md` untuk state paling update (apa yang sudah nyata jalan vs baru rencana).
