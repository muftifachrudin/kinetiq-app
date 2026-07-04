# Vertical-Slice Breakdown: Post-Research Trading App Work

Companion to `docs/prd.md` Section B.9 (roadmap phases) and
`docs/sonnet5-implementation-roadmap.md` (strategy-research phases F0-F9).
Scope: the four areas of the trading app that are still genuinely at 0%
code while strategy research (F0-F6) is far along -- live order execution,
dashboard/UI, real Midtrans/XIDR billing, and Telegram notifications
(confirmed by directory audit: `apps/products/trading/{dashboard,execution,
telegram-bot}` and `apps/platform-core/{billing,notification,dashboard-shell}`
each contain only a `README.md`, no code).

## Why vertical, not per-layer

The natural per-layer plan reads as: "build `execution/` fully, then
`dashboard/` fully, then `billing/` fully, then `telegram-bot/` fully."
That produces four multi-week efforts where nothing is demonstrably working
until all four finish, and integration bugs between layers (auth wiring,
plan-gating, schema mismatches) surface only at the very end.

Instead, each slice below cuts through every layer needed to produce one
concrete, foundable-in-production capability -- DB → strategy/agent layer →
`api-gateway` (auth + plan-gating, already real) → the one new service the
slice needs → an external, observable proof point (a real Telegram message,
a real browser session, a real Midtrans sandbox transaction, a real testnet
fill). Each slice is independently mergeable and independently demoable to
the founder before the next one starts.

## What already exists and is reused by every slice

- `signal` table (migration 0008) is live in production and is being
  written continuously by the Shadow Tahap 1 loop in `ingestion-worker`
  (`docs/sonnet5-implementation-roadmap.md` F0e P3) -- no signal-writing
  work is needed for any slice below, only signal-*consuming* work.
- `api-gateway/deps.py`: Clerk JWT auth, tenant auto-provision, RLS session
  context, `require_plan(*tiers)` dependency factory -- reused as-is for
  gating in every slice, not rebuilt.
- `api-gateway/billing.py`'s `sync_tenant_plan()` -- reused by Slice 3 as
  the function a real webhook calls, replacing the manual
  `POST /billing/subscribe` stopgap as the *only* caller.
- RLS policies (migration 0002), append-only `order_audit_log` trigger
  (migration 0003) -- reused by Slice 4, not rebuilt.

## Slice 1 — Founder receives one real signal in Telegram

**Cuts through**: DB (one new nullable column linking a tenant to a
Telegram chat) → `telegram-bot` (new, minimal) → `api-gateway` plan-gating
(reused) → external proof (a real Telegram chat).

- Migration: `platform_user.telegram_chat_id` (nullable), set via a
  `/link <token>` bot command that exchanges a one-time token issued by
  `api-gateway` for the chat's numeric ID (avoids trusting a raw chat ID
  typed by the user).
- `telegram-bot`: polls `signal` table for rows newer than last-seen
  cursor, cross-references which tenants are `signal_only`/`auto_execute`
  plan and subscribed to that instrument (simplest first version: founder's
  own tenant only, hardcoded instrument list), formats and sends a message.
- **Verification (must be real, not mocked)**: founder's actual Telegram
  account receives a message that matches a real row in production
  `signal` within a few minutes of it being written by the ingestion
  worker's live loop.

## Slice 2 — Founder dashboard: login + see own signal history + plan tier

**Cuts through**: `api-gateway` (one new read endpoint) → `dashboard-shell`
(new Next.js app, first real code) → external proof (a real browser
session against production).

- `api-gateway`: `GET /trading/signals?limit=20` -- read-only, no
  tenant_id filter needed (signal table has none, matches its "shared
  strategy-engine output" design already documented in `models.py`), but
  still behind `require_plan("signal_only", "auto_execute")` so the gate
  itself is exercised end-to-end, not just declared.
- `dashboard-shell`: Clerk login (same Clerk project as `api-gateway`),
  calls `/me` for plan tier + `/trading/signals` for the list, renders a
  plain table. No charts/equity-curve yet -- that depends on Slice 4's
  position data existing at all, and would be premature here.
- **Verification**: real browser session, real Clerk login, real data
  fetched from Neon production rendered in the page -- not a storybook/mock
  state.

## Slice 3 — Real payment flow: Midtrans sandbox → webhook → plan upgrade

**Cuts through**: `platform-core/billing` (new) → Midtrans webhook →
`api-gateway`'s existing `sync_tenant_plan()` → external proof (a plan-gated
endpoint flipping access without any manual DB edit).

- `billing`: Midtrans Snap transaction creation endpoint + webhook receiver
  that verifies the Midtrans signature (`order_id` + `status_code` +
  `gross_amount` + server key, per Midtrans notification spec) before
  calling `sync_tenant_plan()`.
- Retire the `POST /billing/subscribe` self-assign stopgap as a directly
  callable path once this lands (per its own docstring warning in
  `api-gateway/billing.py` -- it was never meant to survive real
  integration) -- keep the function, remove the unauthenticated trigger.
- XIDR/StraitsX integration follows the same shape once the founder's
  Sole Trader account activates (`docs/prd.md` B.16); do not block this
  slice on it, Midtrans alone proves the vertical.
- **Verification**: a real Midtrans **sandbox** transaction completes, the
  webhook fires against the real `api-gateway` (Railway), and
  `GET /trading/auto-execute/status` measurably flips from 403 to 200 for
  that tenant with zero manual SQL.

## Slice 4 — One real testnet order, end-to-end, with kill switch + audit log

**Cuts through**: `execution` + `execution/custody` (new) → risk gate (new,
hard gates only) → `order_audit_log` (existing, append-only) → external
proof (a real exchange testnet fill).

- Prerequisite check, not a rebuild: `min_rr_threshold`/gate logic already
  exists in `signal_runner.py`/`fib_gann_timing.py` from the research
  harness -- reuse the same entry-validity + R:R hard gates here rather
  than re-deriving them, per the roadmap's "gate keras vs faktor skor"
  rule. This slice does **not** need the strategy to have passed the F6
  promotion criteria to prove the execution *plumbing* works on testnet
  small notional -- but per `docs/sonnet5-implementation-roadmap.md`,
  routing this to **mainnet** real money remains gated on promotion
  passing; flag that explicitly rather than silently crossing it.
- `execution/custody`: per-tenant exchange API key storage, encrypted via
  KMS (`KMS_MASTER_KEY_ID` already provisioned per `docs/prd.md` Status
  Implementasi), read-only at rest until an order is placed.
- Mandate + kill-switch endpoint, forked from Vibe-Trading's
  Profiles→Service→Types pattern per `docs/prd.md` B.9 phase 0 note
  (not yet actually forked -- this slice is where that fork happens).
- **Verification**: a manually-triggered real signal places a real
  **testnet** order via ccxt, exchange confirms the fill via its own API
  (not just "no exception raised"), `order_audit_log` gets one row, a
  second attempt after engaging the kill switch is provably blocked before
  reaching the exchange call.

## Ordering and why

1 → 2 → 3 → 4. Telegram (1) is cheapest and reuses the most existing
infrastructure (the signal loop is already live), so it's the fastest path
to the founder holding something real in hand. Dashboard (2) is the first
slice needing new frontend infra, worth doing once so slice 4's future
position/equity view has somewhere to render. Billing (3) unblocks real
paying users and is a prerequisite for slice 4 mattering commercially
(`auto_execute` plan-gating is meaningless while billing is a stopgap).
Execution (4) is last and intentionally testnet-only in this breakdown --
per the existing roadmap's non-negotiable rule, going to mainnet is a
separate, explicitly-gated decision on top of this slice, not part of it.

Each slice ships as its own PR; do not combine two slices into one PR even
though they touch overlapping files (e.g. both 1 and 2 touch `api-gateway`)
-- the point of slicing this way is that each PR is independently
demoable and revertable.
