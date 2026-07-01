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
  railway/           # per-service Railway config (catatan/docs; config-as-code aktual ada di railway.toml root repo)
  neon/              # migrations + time-series partitioning scripts
docs/
  prd.md             # PRD + rencana teknis (sumber kebenaran)
railway.toml         # Railway config-as-code utk service pertama (api-gateway) -- wajib di root repo, lihat catatan di file itu
```

Setiap direktori `apps/**` punya `README.md` singkat yang menjelaskan tanggung jawabnya dan merujuk ke bagian PRD yang relevan.

## Status

Fase 0 (bootstrap) sedang berjalan -- lihat "Status Implementasi" di `docs/prd.md` untuk state paling update (apa yang sudah nyata jalan vs baru rencana). Ringkas: CI hijau thd Neon asli, skema DB Fase 0 lengkap, `api-gateway` skeleton pertama sudah live di Railway. Auth (Clerk), billing (Midtrans+XIDR), dan sisa service lain menyusul.
