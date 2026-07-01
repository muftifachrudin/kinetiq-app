# Platform Core: API Gateway

FastAPI gateway: tenant auth middleware, product+tier plan-gating, request routing ke tiap product API. Agent-agnostic — dipakai semua vertical (trading, dan vertical masa depan).

`deps.py` punya `get_current_user()`: verifikasi Clerk session JWT (via JWKS, `PyJWKClient`), auto-provision row `platform_user` di login pertama, dan set `app.is_superadmin`/`app.tenant_id` per-session via `set_config()` (bukan `SET ... = :param`, itu gak support bind parameter di Postgres) utk RLS policy (Section B.4, live sejak `packages/db` migration 0002). `require_plan(*allowed_tiers)`: dependency factory yg cek `tenant.plan_tier` — `role='superadmin'` selalu bypass, user tanpa tenant atau plan tidak cocok dapat 403. `GET /trading/auto-execute/status` di `main.py` adalah placeholder yg gated ke tier `auto_execute`, bukti alur plan-gating jalan end-to-end — bukan business logic asli, nunggu `apps/products/trading/*` beneran ditulis.

`billing.py`: `sync_tenant_plan()` + `POST /billing/subscribe` — **stopgap**, BUKAN integrasi Midtrans/XIDR asli (Section B.16, akun provider belum di-setup user). Cuma supaya plan-gating & RLS di atas bisa dites via HTTP sungguhan (login -> `/billing/subscribe {"plan_tier": "auto_execute"}` -> auto-provision `tenant` row & assign ke user -> `/trading/auto-execute/status` jadi 200), bukan cuma lewat raw SQL manual. Wajib diganti jadi hasil konfirmasi payment webhook begitu integrasi Midtrans/XIDR beneran ada — jangan biarkan user self-assign tier berbayar tanpa bayar.

**CORS diaktifkan** (`allow_origins=["*"]`, `allow_credentials=False`) — belum ada `dashboard-shell` dgn domain pasti utk di-allowlist, dan auth di sini bearer-token based (bukan cookie), jadi gak ada eksposur CSRF dari allow-all-origin ini. Wajib dipersempit ke domain frontend asli begitu `dashboard-shell` jadi. Dipakai `tools/manual-test-console.html` (lihat README di `tools/`) — halaman HTML mandiri utk klik-klik test alur Clerk login -> `/me` -> `/billing/subscribe` -> endpoint gated, tanpa perlu `curl`/terminal.

Sengaja **flat `main.py`**, bukan `src/` package + `pyproject.toml`: Railpack (builder Railway) punya dukungan native yang jauh lebih reliable utk `requirements.txt` drpd pyproject.toml/setuptools polos (yg auto-detect-nya sempat gagal generate step install sama sekali). `requirements.txt` sendiri sekarang tinggal di **root repo** (bukan folder ini) — lihat kenapa di bawah.

`packages/db` (skema SQLAlchemy) **tidak** di-pip-install sama sekali — direfer via `PYTHONPATH` di `railway.toml`'s `startCommand`. Railway's "Root Directory" setting scope seluruh build+runtime context ke satu subfolder itu saja; sibling directory di luar folder itu (spt `packages/db`) **tidak pernah ada** di container, baik saat build maupun runtime — ini kenapa dua percobaan awal gagal (`-e ../../../packages/db` maupun `PYTHONPATH=../../../packages/db/src` relatif thd Root Directory lama). Fix aktual: Root Directory di-set ke **repo root** (bukan folder ini lagi), `requirements.txt` dipindah ke repo root supaya Railpack's zero-config Python detection tetap native-jalan (tanpa custom `buildCommand`), dan `startCommand` set `PYTHONPATH=packages/db/src:apps/platform-core/api-gateway` (folder ini juga perlu masuk PYTHONPATH krn `main.py` bukan lagi otomatis di cwd). Detail lengkap: `docs/deployment-runbook.md` gotcha #7.

**Railway**: service Settings -> Source -> Root Directory harus **kosong (repo root)**, BUKAN `apps/platform-core/api-gateway` lagi. Build/start command dideklarasikan di `railway.toml` di root repo (config-as-code tidak pernah ikut Root Directory), dan sekarang command-nya juga asumsikan cwd = repo root. Perlu env var `DATABASE_URL` (sudah ada di Railway) dan `CLERK_JWKS_URL` (lihat `.env.example`, belum di-set -- cek Clerk Dashboard -> API Keys).

## Local dev

```bash
cd /path/to/repo/root
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL="postgresql://<user>:<pass>@<host>/<db>"
export CLERK_JWKS_URL="https://<frontend-api>/.well-known/jwks.json"
PYTHONPATH=packages/db/src:apps/platform-core/api-gateway python -m uvicorn main:app --reload
curl localhost:8000/health
curl localhost:8000/me                                    # 401 without a token, expected
curl -H "Authorization: Bearer <clerk-session-jwt>" localhost:8000/me
```

See `docs/prd.md` (PRD + Rencana Teknis: Kinetiq) for full context and design decisions.
