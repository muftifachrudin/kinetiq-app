# Platform Core: Billing

Dual-provider (Midtrans + IDRX, Xendit/Paddle direncanakan fase lanjutan) — tiap provider adapter tipis di `providers/{midtrans.py, idrx.py}` yang implement kontrak sama (`verify_webhook()`, `parse_payment_event()`, `create_checkout_link()`), funnel ke `sync_tenant_plan()` inti + update `tenant_token_ledger`. Subscription state sync ke Neon (tabel `tenant`), di-model per product+tier (mis. `trading:signal_only`, `trading:auto_execute`). Lihat PRD Section B.16.

**Belum ada kode nyata di sini** (masih skeleton README) — akun Midtrans/StraitsX sendiri belum di-setup user (masih pending verifikasi KTP/NPWP), jadi provider adapter asli belum bisa dites. Sementara itu, ada **stopgap** `sync_tenant_plan()` + endpoint `POST /billing/subscribe` di `apps/platform-core/api-gateway/billing.py` — bukan integrasi payment gateway asli, cuma supaya plan-gating & RLS yg udah jalan bisa dites lewat HTTP API sungguhan (bukan raw SQL). Begitu webhook Midtrans/XIDR beneran ada di modul ini, self-service upgrade di stopgap itu wajib diganti jadi hasil konfirmasi payment webhook — user gak boleh bisa self-assign tier berbayar tanpa bayar beneran.

See `docs/prd.md` (PRD + Rencana Teknis: Kinetiq) for full context and design decisions.
