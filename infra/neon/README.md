# Infra: Neon

Migrations (Alembic) + partitioning scripts (native range-partitioning by time, pengganti TimescaleDB compression yg tidak tersedia di Neon). Lihat PRD Section B.11/C.3 utk strategi branch-per-PR.

## Partitioning (`partitioning/`)

`kinetiq_ensure_month_partition(table, month)` (dibuat via migration `packages/db/migrations/versions/0004_partition_rollover.py`) adalah satu-satunya logic partitioning, dipakai 2 kali: sekali oleh migration 0004 itu sendiri (backfill data yg udah kadung numpuk di partisi `DEFAULT` sejak migration 0001 — production py `funding_rate`/`ohlcv` beneran spanning akhir Juni-awal Juli 2026), dan berulang oleh `partitioning/rollover.sql` (bikin partisi bulan berjalan + N bulan ke depan, idempotent, dijalankan manual/cron sampai Inngest ada — lihat `apps/products/trading/ingestion/README.md` utk pola yg sama). Detail lengkap + gotcha (kenapa harus pindahin data dari DEFAULT dulu sblm ATTACH, kenapa generated column `price_basis.basis`/`basis_pct` butuh column-list eksplisit) ada di komentar migration 0004 — semua diverifikasi lewat upgrade→downgrade→upgrade penuh thd Postgres 16 lokal beneran, bukan cuma baca kode.

Jalanin rollover job:
```bash
psql "$DATABASE_URL" -f infra/neon/partitioning/rollover.sql
```

See `docs/prd.md` (PRD + Rencana Teknis: Kinetiq) for full context and design decisions.
