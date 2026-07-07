# Kanban — Tracer-Bullet Slices

The task menu referenced by `docs/ai-coding-workflow.md` Section 2.2/2.3.
**One slice = one Claude Code session** — don't mix two cards into one
session, don't carry a session across cards. Pick a card, read the
`docs/prd.md` section(s) it links to for the actual spec/decisions (this
board deliberately doesn't restate them), follow the workflow checklist,
then move it to Done and add whatever follow-on cards it revealed.

Cards without a clear acceptance test yet need a scoping/"grill-me" session
first (workflow doc Section 1.1) before an implementation session opens
against them.

## To Do

- [ ] **Perp/futures validation for the Markoviz swarm pattern** — `vibe-trading-ai`'s
  pattern looks validated for spot; run the same walk-forward/PF-net-of-fees/
  bootstrap-CI rigor already used for `fib_gann_timing` before trusting it
  for perp/futures or combining it into the shared research engine.
  Refs: `docs/prd.md` B.6c, `docs/fib-gann-validation-brief.md`.
- [ ] **Redesign Telegram signal card / trading status / analysis UI** —
  current `ai-perp-bot-core` Telegram UI isn't business-ready; not a direct
  port, a real redesign pass. Refs: `docs/prd.md` B.6c, B.14.
- [ ] **RBAC per agent subscription (web app)** — route/middleware-level
  guard on Next.js using `agent_subscription`, no new RBAC library. Refs:
  `docs/prd.md` B.14c, B.14b (`agent_subscription` table).
- [ ] **Sidecar credential management page — trading agent first** — one
  form per agent type, starting with CEX/DEX API keys. Refs: `docs/prd.md`
  B.3b, B.14c.
- [ ] **Per-agent dashboard — trading first** — dashboard shape is agent-
  specific; don't build a generic multi-agent dashboard shell yet (that's
  still an open discussion, see below). Refs: `docs/prd.md` B.14c.
- [ ] **Billing/subscription management page** — architecturally separate
  route/state from any agent's config pages. Refs: `docs/prd.md` B.14c,
  `apps/platform-core/billing/` (B.2).

## Needs discussion before it's a slice

- **Combined dashboard shape for multi-agent subscribers** (tab switcher?
  single merged page? user-arranged widgets?) — explicitly not decided,
  don't implement until discussed. Refs: `docs/prd.md` B.14c.
- **"vibe-trading gives analysis every 4 hours"** — ambiguous, unresolved:
  existing cron pattern in `vibe-trading-ai`/swarm config, or a new
  Kinetiq research-engine reporting behavior? Refs: `docs/prd.md` B.6c.
- **Vultr VM migration** (Railway+Neon → self-hosted) — needs its own
  briefing (tech stack, Postgres PITR/branching replacement, deploy
  workflow). Refs: `docs/prd.md` B.1 revision note.
- **Multi-timeframe research engine performance** — needs a dedicated
  research/implementation session of its own. Refs: `docs/prd.md` B.6c.

## Done

(nothing yet filed here from this doc's introduction — everything before
7 July 2026 was tracked via the session's own task list rather than this
board; start using this board going forward.)
