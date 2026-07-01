# Platform Core: Billing

Dual-provider (Midtrans + IDRX, Xendit/Paddle direncanakan fase lanjutan) — tiap provider adapter tipis di `providers/{midtrans.py, idrx.py}` yang implement kontrak sama (`verify_webhook()`, `parse_payment_event()`, `create_checkout_link()`), funnel ke `sync_tenant_plan()` inti + update `tenant_token_ledger`. Subscription state sync ke Neon (tabel `tenant`), di-model per product+tier (mis. `trading:signal_only`, `trading:auto_execute`). Lihat PRD Section B.16.

See `docs/prd.md` (PRD + Rencana Teknis: Kinetiq) for full context and design decisions.
