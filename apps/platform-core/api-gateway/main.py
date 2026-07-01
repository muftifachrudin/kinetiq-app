from deps import get_current_user
from fastapi import Depends, FastAPI
from kinetiq_db.models import PlatformUser

app = FastAPI(title="Kinetiq API Gateway")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/me")
def me(user: PlatformUser = Depends(get_current_user)) -> dict[str, str | None]:
    return {
        "id": str(user.id),
        "tenant_id": str(user.tenant_id) if user.tenant_id else None,
        "email": user.email,
        "role": user.role,
    }
