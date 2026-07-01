from billing import sync_tenant_plan
from deps import get_current_user, get_db, require_plan
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from kinetiq_db.models import PlatformUser, Tenant
from pydantic import BaseModel
from sqlalchemy.orm import Session

app = FastAPI(title="Kinetiq API Gateway")

# Wide open for now: no dashboard-shell frontend exists yet with a known
# domain to allowlist, and auth here is bearer-token based (not cookies), so
# allow_credentials stays False -- there's no CSRF exposure from allowing any
# origin. Tighten to the real frontend domain(s) once dashboard-shell ships.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SubscribeRequest(BaseModel):
    plan_tier: str


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/me")
def me(
    user: PlatformUser = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict[str, str | None]:
    plan_tier = None
    if user.tenant_id is not None:
        tenant = db.get(Tenant, user.tenant_id)
        plan_tier = tenant.plan_tier if tenant else None
    return {
        "id": str(user.id),
        "tenant_id": str(user.tenant_id) if user.tenant_id else None,
        "email": user.email,
        "role": user.role,
        "plan_tier": plan_tier,
    }


@app.post("/billing/subscribe")
def subscribe(
    body: SubscribeRequest,
    user: PlatformUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Stopgap self-service tenant/plan provisioning -- see billing.py docstring.
    Not the real Midtrans/XIDR webhook flow (Section B.16), which doesn't exist yet."""
    try:
        tenant = sync_tenant_plan(user, body.plan_tier, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"tenant_id": str(tenant.id), "plan_tier": tenant.plan_tier}


@app.get("/trading/auto-execute/status")
def auto_execute_status(tenant: Tenant | None = Depends(require_plan("auto_execute"))) -> dict[str, str]:
    """Placeholder proving plan-gating works end-to-end; real auto-execute
    business logic lives in apps/products/trading once that vertical is built."""
    return {"status": "not_implemented", "plan_tier": tenant.plan_tier if tenant else "superadmin"}
