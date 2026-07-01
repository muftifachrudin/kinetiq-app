# Platform Core: API Gateway

FastAPI gateway: tenant auth middleware, product+tier plan-gating, request routing ke tiap product API. Agent-agnostic — dipakai semua vertical (trading, dan vertical masa depan).

Saat ini baru skeleton minimal (`/health` doang) supaya Railway ada yang bisa di-build/deploy — tenant auth middleware & plan-gating (`deps.py`) menyusul ronde berikutnya.

Sengaja **flat `main.py` + `requirements.txt`**, bukan `src/` package + `pyproject.toml`: Railpack (builder Railway) punya dukungan native yang jauh lebih reliable utk `requirements.txt` drpd pyproject.toml/setuptools polos (yg auto-detect-nya sempat gagal generate step install sama sekali). Modul top-level `main.py` otomatis importable via `python -m uvicorn main:app` tanpa perlu instalasi paket sendiri.

**Railway**: set service Settings -> Source -> Root Directory ke `apps/platform-core/api-gateway` supaya Railway build folder ini (bukan scan seluruh monorepo). Build/start command dideklarasikan di `railway.toml` **di root repo** (bukan di folder ini) -- Railway config-as-code tidak ikut Root Directory, harus di root repo, tapi command di dalamnya tetap jalan relatif thd Root Directory yang di-set di dashboard.

## Local dev

```bash
cd apps/platform-core/api-gateway
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn main:app --reload
curl localhost:8000/health
```

See `docs/prd.md` (PRD + Rencana Teknis: Kinetiq) for full context and design decisions.
