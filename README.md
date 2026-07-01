# Kinetiq

Multi-agent AI trading SaaS — perpetual futures & spot untuk MVP, dengan meme-sniper dan DLMM sebagai modul lanjutan, dibangun di atas Platform Core yang agent-agnostic (siap menampung vertical non-trading seperti agent exam/chatbot/content-creator di masa depan).

Lihat **`docs/prd.md`** untuk PRD + rencana teknis lengkap (arsitektur, data model, roadmap fase, budget, dan keputusan desain).

## Struktur Repo

```
apps/
  platform-core/     # agent-agnostic: auth, billing, agent-registry, llm-gateway, notification, dashboard-shell, agent-sdk, guardrails, mcp-server
  products/trading/  # vertical pertama: ingestion, agent-orchestrator, strategy-engine, execution, inngest-functions, dashboard, telegram-bot
packages/
  schemas/           # Pydantic + Zod data contracts
  db/                # SQLAlchemy models + Alembic migrations
  config/            # shared env/feature-flag config
infra/
  railway/           # per-service Railway config
  neon/              # migrations + time-series partitioning scripts
docs/
  prd.md             # PRD + rencana teknis (sumber kebenaran)
```

Setiap direktori `apps/**` punya `README.md` singkat yang menjelaskan tanggung jawabnya dan merujuk ke bagian PRD yang relevan.

## Status

Proyek masih di tahap bootstrap (Fase 0 di roadmap `docs/prd.md`). Struktur direktori sudah di-scaffold; implementasi kode (koneksi Railway/Neon/Stripe/Clerk/OpenRouter, migrasi awal, CI penuh) menyusul secara bertahap.
