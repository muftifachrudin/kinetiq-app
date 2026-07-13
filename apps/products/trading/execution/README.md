# Trading: Execution

Unified order/position adapter (CCXT unified + native DEX signing) + `risk_gate.py` (mandatory checkpoint guardrail, v1 done — kill-switch, symbol-universe permission, defensive R:R re-check; regime gate + kNN risk memory still undesigned) + `custody/` (envelope-encrypted key vault, non-custodial, still skeleton).

See `docs/prd.md` (Layer 3 — Risk Hard Gate) for full context and design decisions.
