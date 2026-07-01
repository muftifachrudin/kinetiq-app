# Trading: Telegram Bot

Python (`python-telegram-bot`), thin wrapper around `agent-orchestrator`. Interface MVP (signal tier): hybrid conversational — free-form natural language for monitoring/Q&A, mandatory structured button confirmation for any state-changing action (trade execution, risk_mandate changes, kill switch) so `risk_gate.py` can never be bypassed. Plan-gated via apps/platform-core/notification. Lihat PRD Section B.14.

See `docs/prd.md` (PRD + Rencana Teknis: Kinetiq) for full context and design decisions.
