from deps import get_current_user, get_db, require_plan
from fastapi import Depends, FastAPI
from kinetiq_db.models import PlatformUser, Tenant
from sqlalchemy.orm import Session

app = FastAPI(title="Kinetiq API Gateway")


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


@app.get("/trading/auto-execute/status")
def auto_execute_status(tenant: Tenant | None = Depends(require_plan("auto_execute"))) -> dict[str, str]:
    """Placeholder proving plan-gating works end-to-end; real auto-execute
    business logic lives in apps/products/trading once that vertical is built."""
    return {"status": "not_implemented", "plan_tier": tenant.plan_tier if tenant else "superadmin"}
