"""Tests for main.py's /trading/signals endpoint (Slice 2,
docs/post-research-vertical-slices.md). Real JWT verification and the real
Postgres session are out of scope here (see conftest.py) -- get_current_user
and get_db are overridden with fakes, so what's actually being exercised is
the real require_plan() gating logic and the real response-shaping code in
main.list_signals, matching the "TestClient + dependency override" pattern
already used for /trading/auto-execute/status (docs/prd.md).
"""

from datetime import datetime, timezone

import deps
import main
from fastapi.testclient import TestClient
from kinetiq_db.models import PlatformUser, Signal, Tenant

SIGNAL_ONLY_TENANT_ID = "22222222-2222-2222-2222-222222222222"
FREE_TENANT_ID = "11111111-1111-1111-1111-111111111111"

client = TestClient(main.app)


class FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def join(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, n):
        return FakeQuery(self._rows[:n])

    def all(self):
        return self._rows


class FakeSession:
    def __init__(self, tenants=None, signal_rows=None):
        self._tenants = tenants or {}
        self._signal_rows = signal_rows or []

    def get(self, model, id):
        if model is Tenant:
            return self._tenants.get(id)
        return None

    def query(self, *entities):
        return FakeQuery(self._signal_rows)


def _user(tenant_id=None, role="tenant"):
    return PlatformUser(id=1, tenant_id=tenant_id, role=role, email="a@b.com", clerk_user_id="u1")


def _override(user, session):
    main.app.dependency_overrides[deps.get_current_user] = lambda: user
    main.app.dependency_overrides[deps.get_db] = lambda: session


def teardown_function():
    main.app.dependency_overrides.clear()


def test_list_signals_rejects_plan_without_access():
    tenant = Tenant(id=FREE_TENANT_ID, plan_tier="free")
    _override(_user(tenant_id=FREE_TENANT_ID), FakeSession(tenants={FREE_TENANT_ID: tenant}))

    resp = client.get("/trading/signals")

    assert resp.status_code == 403


def test_list_signals_no_tenant_rejected():
    _override(_user(tenant_id=None), FakeSession())

    resp = client.get("/trading/signals")

    assert resp.status_code == 403


def test_list_signals_signal_only_plan_returns_data():
    tenant = Tenant(id=SIGNAL_ONLY_TENANT_ID, plan_tier="signal_only")
    signal = Signal(
        id=1,
        instrument_id=1,
        timeframe="1h",
        ts=datetime(2026, 7, 1, tzinfo=timezone.utc),
        direction="long",
        entry_price=100,
        stop_loss=95,
        take_profit_1=110,
        confidence=0.8,
    )
    session = FakeSession(
        tenants={SIGNAL_ONLY_TENANT_ID: tenant},
        signal_rows=[(signal, "BTC/USDT:USDT")],
    )
    _override(_user(tenant_id=SIGNAL_ONLY_TENANT_ID), session)

    resp = client.get("/trading/signals?limit=5")

    assert resp.status_code == 200
    body = resp.json()
    assert body == [
        {
            "id": 1,
            "instrument": "BTC/USDT:USDT",
            "timeframe": "1h",
            "ts": "2026-07-01T00:00:00+00:00",
            "direction": "long",
            "entry_price": "100",
            "stop_loss": "95",
            "take_profit_1": "110",
            "confidence": "0.8",
        }
    ]


def test_list_signals_auto_execute_plan_also_allowed():
    tenant = Tenant(id=SIGNAL_ONLY_TENANT_ID, plan_tier="auto_execute")
    session = FakeSession(tenants={SIGNAL_ONLY_TENANT_ID: tenant}, signal_rows=[])
    _override(_user(tenant_id=SIGNAL_ONLY_TENANT_ID), session)

    resp = client.get("/trading/signals")

    assert resp.status_code == 200
    assert resp.json() == []


def test_list_signals_superadmin_bypasses_plan_gate():
    _override(_user(tenant_id=None, role="superadmin"), FakeSession(signal_rows=[]))

    resp = client.get("/trading/signals")

    assert resp.status_code == 200
    assert resp.json() == []


def test_list_signals_limit_is_clamped():
    tenant = Tenant(id=SIGNAL_ONLY_TENANT_ID, plan_tier="signal_only")
    rows = [
        (
            Signal(
                id=i,
                instrument_id=1,
                timeframe="1h",
                ts=datetime(2026, 7, 1, tzinfo=timezone.utc),
                direction="long",
                entry_price=100,
                stop_loss=95,
                take_profit_1=None,
                confidence=0.8,
            ),
            "BTC/USDT:USDT",
        )
        for i in range(150)
    ]
    session = FakeSession(tenants={SIGNAL_ONLY_TENANT_ID: tenant}, signal_rows=rows)
    _override(_user(tenant_id=SIGNAL_ONLY_TENANT_ID), session)

    resp = client.get("/trading/signals?limit=500")

    assert resp.status_code == 200
    assert len(resp.json()) == 100
