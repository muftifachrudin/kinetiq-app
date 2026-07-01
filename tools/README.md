# Tools

Manual/local-only helper scripts and pages -- not part of any deployed service.

`manual-test-console.html`: a standalone page (no build step) for clicking
through `api-gateway`'s Clerk login -> `/me` -> `/billing/subscribe` ->
plan-gated endpoint flow in a real browser, instead of needing `curl`/a
terminal. Setup instructions are in the file's top comment. Requires
`api-gateway` to have CORS enabled (see `main.py`), which it does as of
this file being added.
