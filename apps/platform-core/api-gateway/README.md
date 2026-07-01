# Platform Core: API Gateway

FastAPI gateway: tenant auth middleware, product+tier plan-gating, request routing ke tiap product API. Agent-agnostic — dipakai semua vertical (trading, dan vertical masa depan).

`deps.py` punya `get_current_user()`: verifikasi Clerk session JWT (via JWKS, `PyJWKClient`), auto-provision row `platform_user` di login pertama, dan set `app.tenant_id` per-session utk RLS policy (Section B.4, belum diimplementasi di migration — placeholder yg sudah siap dipakai begitu RLS ditambahkan). `plan-gating` (cek `tenant.plan_tier` per endpoint) menyusul ronde berikutnya.

Sengaja **flat `main.py` + `requirements.txt`**, bukan `src/` package + `pyproject.toml`: Railpack (builder Railway) punya dukungan native yang jauh lebih reliable utk `requirements.txt` drpd pyproject.toml/setuptools polos (yg auto-detect-nya sempat gagal generate step install sama sekali). Modul top-level `main.py` otomatis importable via `python -m uvicorn main:app` tanpa perlu instalasi paket sendiri. `packages/db` (skema SQLAlchemy) **tidak** di-pip-install dari `requirements.txt` — Railpack copy `requirements.txt` ke layer terisolasi sebelum sisa repo ada, jadi `-e ../../../packages/db` gagal (`not a valid editable requirement`). Sebagai gantinya, `railway.toml`'s `startCommand` set `PYTHONPATH=../../../packages/db/src` supaya `kinetiq_db` diimport langsung dari source saat runtime (repo penuh sudah ter-copy di titik itu) — lihat `docs/deployment-runbook.md` gotcha #7.

**Railway**: set service Settings -> Source -> Root Directory ke `apps/platform-core/api-gateway` supaya Railway build folder ini (bukan scan seluruh monorepo). Build/start command dideklarasikan di `railway.toml` **di root repo** (bukan di folder ini) -- Railway config-as-code tidak ikut Root Directory, harus di root repo, tapi command di dalamnya tetap jalan relatif thd Root Directory yang di-set di dashboard. Perlu env var `DATABASE_URL` (sudah ada di Railway) dan `CLERK_JWKS_URL` (lihat `.env.example`, belum di-set -- cek Clerk Dashboard -> API Keys).

## Local dev

```bash
cd apps/platform-core/api-gateway
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL="postgresql://<user>:<pass>@<host>/<db>"
export CLERK_JWKS_URL="https://<frontend-api>/.well-known/jwks.json"
python -m uvicorn main:app --reload
curl localhost:8000/health
curl localhost:8000/me                                    # 401 without a token, expected
curl -H "Authorization: Bearer <clerk-session-jwt>" localhost:8000/me
```

See `docs/prd.md` (PRD + Rencana Teknis: Kinetiq) for full context and design decisions.
