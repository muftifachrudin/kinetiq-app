# AI Coding Workflow — Kinetiq Project Convention

Adapted from Matt Pocock's "Full Walkthrough: Workflow for AI Coding" talk
(AI Engineer 2026). This is the **pull doc** referenced by `CLAUDE.md` —
detail lives here, not in `CLAUDE.md` itself, so the always-loaded context
stays thin (see "Push vs Pull" below). Read this before starting a new
feature, and re-read the checklist at the bottom before every session.

## 0. Smart zone vs dumb zone

Every session has a "smart zone" (roughly the first ~100K tokens) where the
model tracks instructions and project detail precisely. Past that, sessions
drift into a "dumb zone": more hallucination, forgotten earlier decisions,
old/new context bleeding together.

Practical implications for this repo:

- Don't run one Claude Code session for many hours without a reset. Prefer
  **`/clear` over `/compact`** when switching topics (e.g. moving from
  "strategy validation" to "shadow simulator" to "multi-agent platform
  pivot") — auto-summaries are noisy and can misprioritize. This is the
  **"Memento Principle"**: persist the decisions that matter into a durable
  file (`docs/prd.md`, a brief, `CLAUDE.md`, an issue) and start a clean
  session, rather than relying on `/compact` to carry everything forward.
- Start a **new session per topic**, not a continuation of a long one.

## 1. Alignment phase — before writing any code

### 1.1 Grill-me first

Before asking an agent to implement anything non-trivial, let the AI
interview *you* first — scope, edge cases, constraints, definition of
"done" — rather than jumping straight to a plan. Don't let the agent move
to planning until the design is actually clear and agreed, even if that
means several rounds of questions.

### 1.2 PRD as destination, not compiler spec

`docs/prd.md` is a **destination marker** — direction and key decisions,
not a precise mechanical spec the agent compiles into code. Don't
over-polish it: an over-detailed PRD rots faster once implementation
reveals better decisions. It should capture the problem being solved,
system constraints, success criteria, and key decisions — not every line
of behavior. Accept that it will drift out of sync with implementation
over time; don't chase 100% sync.

## 2. Planning phase — task breakdown

### 2.1 Tracer bullets (vertical slices)

Break work into vertical slices that cut through every layer (DB → API →
UI/output) at small scope, rather than horizontal layers ("all backend
first, then all frontend"). Each finished slice produces a real,
end-to-end-testable signal, and slices can be worked on independently
without agents colliding.

Example for a trading-vertical feature: not "implement all 7 pillar
signals," but "Aggressor Flow pillar: raw orderbook data → score → publish
to Redis → visible in dashboard log" — one slice, but end-to-end and
independently verifiable.

### 2.2 Kanban from the slices

Turn the slices into a Kanban board (To Do → In Progress → Review → Done).
This becomes the menu an agent picks tasks from, and the basis for the AFK
phase below. This project's board lives in `docs/kanban.md` — check it
before opening a new session.

### 2.3 One session = one slice (confirmed 7 July 2026)

Each Kanban card/tracer-bullet slice gets its **own dedicated session** —
don't fold two unrelated slices into one long session, and don't carry a
slice's implementation session into the next slice's work. This is what
makes "independently verifiable" in 2.1 actually true in practice: a slice
implemented in its own session can be tested end-to-end without depending
on another slice's in-flight, not-yet-committed state. It also keeps each
session inside the smart zone (Section 0) instead of accumulating unrelated
context across slices.

Practical routine for starting a new implementation session on this repo:

1. Open `docs/kanban.md`, pick (or add) the slice to work on.
2. Read the relevant `docs/prd.md` section(s) the slice references for the
   actual decisions/schema/constraints — the kanban entry should point to
   these, not restate them.
3. Follow the Section 6 checklist below for that slice.
4. Move the card to Done in `docs/kanban.md` once merged, and add any new
   follow-on slices it revealed.

## 3. Execution phase — human-in-the-loop first, then autonomous

### 3.1 TDD as the agent's feedback loop

Feedback-loop quality is the **ceiling** on agent output quality. Without an
objective way to know "is this correct," an agent stops at "looks like it
works" — not necessarily "is correct."

Flow: agent picks a task from the Kanban → writes the test first (per the
slice's spec/acceptance criteria) → implements until the test is green →
commits. Stay human-in-the-loop during this phase, correct misdirection
immediately, and **persist every correction** into a rule/skill/`CLAUDE.md`
entry rather than repeating it verbally every session.

For anything touching CODEOWNERS-protected paths (`execution/risk_gate.py`,
`execution/custody/*`, `packages/db/migrations/`) or strategy-critical
logic (scoring weights, gate thresholds), stay human-in-the-loop — don't
promote these to AFK regardless of how routine they start to feel.

### 3.2 AFK / autonomous mode

Only once a pattern is proven consistently correct for a given task type
(e.g. routine wiring, boilerplate CRUD, replicating an already-validated
pattern to a new venue/exchange) should it move to autonomous execution —
running multiple slices without real-time supervision. Curate the Kanban
first; don't jump to AFK for new architecture exploration.

## 4. Review phase — always in a clean session

Review agent-written code in a **new, clean session**, not the same one
used for implementation — the implementation session is full of
trial-and-error history and isn't a good vantage point for objective
review. After automated review, still do manual QA yourself — agent review
doesn't replace actually trying the feature, especially for anything that's
a matter of feel (UX, timing, signal false-positive rate).

## 5. Codebase design that agents work well with

### 5.1 Push vs pull standards

- **Push** (always active, lives in `CLAUDE.md`): things a reviewer must
  always obey — style, security constraints, architecture boundaries that
  must never be crossed.
- **Pull** (on-demand, lives in a separate skill/doc): guidance only
  relevant when an implementer actually needs it — e.g. how to use a
  specific library, a niche pattern. This doc is itself a pull doc.

Don't put everything in `CLAUDE.md` — that burns smart-zone budget from the
start of every session. Keep the mandatory, always-applicable rules there;
put the rest here or in a dedicated skill.

### 5.2 Agent-legible software

Code that's easy for a human to refactor is also easy for an agent to work
in. Deep modules (simple interface, complexity hidden inside) remain the
right target — agents don't replace the need for good software
fundamentals, they reward a clean codebase and punish a messy one.

## 6. Checklist — before starting a new feature

1. Start a **new/clean session** — don't continue a long-running one.
2. Run a "grill-me" round: let the AI interview you until the design is
   clear.
3. Write a short PRD entry — problem, constraints, success criteria (don't
   over-polish).
4. Break it into tracer bullets (vertical slices) → add to the Kanban.
5. Execute human-in-the-loop first: agent picks a task → writes a test →
   implements → commits.
6. Persist every correction into a rule/skill/`CLAUDE.md` entry, not just a
   one-off comment.
7. Once the pattern is stable, move similar tasks to autonomous/AFK mode.
8. Review in a new session, then do manual QA yourself.
9. Keep `CLAUDE.md` thin (push rules only); everything else is a pull
   doc/skill.

## Source

Video: Matt Pocock (@mattpocockuk), "Full Walkthrough: Workflow for AI
Coding," AI Engineer 2026. This document is adapted from a community
summary of that talk (not a verbatim transcript), tailored to this repo's
stack (Python/LangGraph + TypeScript + Redis + Postgres + Claude Code).
