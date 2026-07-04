# Platform Core: Dashboard Shell

Next.js shell: login, billing/plan management, product switcher antar vertical. Tiap product vertical mount UI-nya sbg halaman di dalam shell ini.

See `docs/prd.md` (PRD + Rencana Teknis: Kinetiq) for full context and design decisions.

## Slice 2 (docs/post-research-vertical-slices.md)

First real code in this app: Clerk login + a read-only signal history table,
proving the vertical end-to-end (real browser session -> real Clerk login ->
`api-gateway`'s plan-gated `/trading/signals` -> rendered in a real page)
rather than building the full dashboard (positions, equity curve,
trade-annotation UI) before anything is demoable.

- `app/layout.tsx` / `app/AuthHeaderControls.tsx`: `ClerkProvider` + sign-in/
  user button in the header. Uses `useAuth()`'s `isLoaded`/`isSignedIn`
  flags rather than `@clerk/nextjs`'s `<SignedIn>`/`<SignedOut>` components --
  those were removed in the `@clerk/nextjs` v7 major installed here in favor
  of a `<Show>` primitive whose prop shape wasn't documented yet at the time
  this was written; the hook-based check is stable across Clerk versions.
- `app/page.tsx`: calls `GET /me` (plan tier) and `GET /trading/signals?limit=20`
  against `api-gateway`, using the Clerk session token via `getToken()`. A
  403 from `/trading/signals` (wrong plan tier) is rendered as a distinct,
  expected state -- not conflated with a network/server error.
- `proxy.ts` (Next.js 16's replacement for the deprecated `middleware.ts`
  convention): wires `clerkMiddleware()` so Clerk's session context is
  available on every request.

## Local dev

```bash
npm install
cp .env.example .env.local   # fill in Clerk keys from the same Clerk
                              # project api-gateway verifies JWTs against,
                              # and NEXT_PUBLIC_API_GATEWAY_URL
npm run dev
```

Requires `api-gateway` running locally (or pointed at the Railway
deployment) with a matching `CLERK_JWKS_URL` -- login will otherwise
succeed against Clerk but every `api-gateway` call will 401.

## Not yet verified against real production

This was built and build/lint/dev-boot verified in a sandboxed environment
without real Clerk credentials or network access to the deployed
`api-gateway` -- someone with real Clerk keys and the Railway URL needs to
confirm an actual login + a real `signal_only`/`auto_execute` tenant seeing
real rows before this is considered done for Slice 2's acceptance criteria.
