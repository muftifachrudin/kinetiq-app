"""Tenant auth middleware: verifies a Clerk session JWT, resolves it to a
`platform_user` row (auto-provisioning on first login), and sets the
Postgres session variable RLS policies key off (Section B.4/B.13).
"""

import os
from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException, Request
from jwt import PyJWKClient
from kinetiq_db.engine import normalize_db_url
from kinetiq_db.models import PlatformUser, Tenant
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

_engine = create_engine(normalize_db_url(os.environ["DATABASE_URL"]))
SessionLocal = sessionmaker(bind=_engine)


@lru_cache
def _jwk_client() -> PyJWKClient:
    return PyJWKClient(os.environ["CLERK_JWKS_URL"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(request: Request, db: Session = Depends(get_db)) -> PlatformUser:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = auth_header.removeprefix("Bearer ")

    try:
        signing_key = _jwk_client().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token, signing_key.key, algorithms=["RS256"], options={"verify_aud": False}
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}") from exc

    clerk_user_id = claims["sub"]
    user = db.query(PlatformUser).filter_by(clerk_user_id=clerk_user_id).one_or_none()
    if user is None:
        email = claims.get("email") or f"{clerk_user_id}@unknown.clerk"
        user = PlatformUser(clerk_user_id=clerk_user_id, email=email, role="tenant")
        db.add(user)
        db.commit()
        db.refresh(user)

    # RLS policies (Section B.4) key off this session-local setting.
    if user.tenant_id is not None:
        db.execute(text("SET app.tenant_id = :tenant_id"), {"tenant_id": str(user.tenant_id)})

    return user


def require_plan(*allowed_tiers: str):
    """Dependency factory: gate an endpoint by the caller's `tenant.plan_tier`.

    `role='superadmin'` always bypasses (Section A.3/B.13: founder isn't
    subject to billing/plan-gating). Any other user must have a tenant whose
    `plan_tier` is one of `allowed_tiers`, or the request is rejected with 403.
    """

    def _check(
        user: PlatformUser = Depends(get_current_user), db: Session = Depends(get_db)
    ) -> Tenant | None:
        if user.role == "superadmin":
            return None

        if user.tenant_id is None:
            raise HTTPException(status_code=403, detail="No tenant associated with this account")

        tenant = db.get(Tenant, user.tenant_id)
        if tenant is None or tenant.plan_tier not in allowed_tiers:
            current = tenant.plan_tier if tenant else None
            raise HTTPException(
                status_code=403,
                detail=f"Requires plan tier {allowed_tiers}, current plan is {current!r}",
            )
        return tenant

    return _check
