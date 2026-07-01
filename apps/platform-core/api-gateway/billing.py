"""Stopgap tenant/plan provisioning -- NOT the real billing integration.

Section B.16's Midtrans/XIDR webhook-driven flow isn't wired up yet (no
payment provider account exists -- both are still pending manual setup by
the founder). This module exists purely so the plan-gating (`deps.require_plan`)
and RLS policies already shipped can be exercised against a real tenant via
the actual HTTP API with a real Clerk session, instead of only via raw SQL.

Once a real payment webhook lands in `apps/platform-core/billing/`, calling
this to grant a paid tier must be replaced by that webhook's confirmed
payment event -- a user must never be able to self-assign `auto_execute` (or
any paid tier) with no payment behind it. Don't extend this endpoint's scope
in the meantime; it's a testing stopgap, not a design to build on.
"""

from kinetiq_db.models import PlatformUser, Tenant
from sqlalchemy.orm import Session

VALID_PLAN_TIERS = ("signal_only", "auto_execute", "meme_addon", "dlmm_addon")


def sync_tenant_plan(user: PlatformUser, plan_tier: str, db: Session) -> Tenant:
    if plan_tier not in VALID_PLAN_TIERS:
        raise ValueError(f"invalid plan_tier: {plan_tier!r}")

    if user.tenant_id is None:
        tenant = Tenant(email=user.email, plan_tier=plan_tier)
        db.add(tenant)
        db.flush()
        user.tenant_id = tenant.id
    else:
        tenant = db.get(Tenant, user.tenant_id)
        tenant.plan_tier = plan_tier

    db.commit()
    db.refresh(tenant)
    return tenant
