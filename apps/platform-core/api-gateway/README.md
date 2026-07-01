# Platform Core: API Gateway

FastAPI gateway: tenant auth middleware, product+tier plan-gating, request routing ke tiap product API. Agent-agnostic — dipakai semua vertical (trading, dan vertical masa depan).

Saat ini baru skeleton minimal (`/health` doang) supaya Railway ada yang bisa di-build/deploy — tenant auth middleware & plan-gating (`deps.py`) menyusul ronde berikutnya.

**Railway**: set service Settings -> Source -> Root Directory ke `apps/platform-core/api-gateway` supaya Railway build folder ini (bukan scan seluruh monorepo). Build/start command sudah dideklarasikan di `railway.toml`.

## Local dev

```bash
cd apps/platform-core/api-gateway
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
uvicorn kinetiq_api_gateway.main:app --reload
curl localhost:8000/health
```

See `docs/prd.md` (PRD + Rencana Teknis: Kinetiq) for full context and design decisions.
