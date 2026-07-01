# Platform Core: LLM Gateway

Abstraksi provider LLM (default OpenRouter) + cost tracking lintas semua vertical. Resolve `llm_config` dgn hierarchy tenant->product->global (lihat PRD Section B.13) dan enforce per-tenant LLM budget.

See `docs/prd.md` (PRD + Rencana Teknis: Kinetiq) for full context and design decisions.
