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
from kinetiq_db.models import PlatformUser
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
