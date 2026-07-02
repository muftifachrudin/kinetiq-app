# packages/backtest-core

Shared walk-forward windowing utilities for Kinetiq strategy validation harnesses. One definition of "how a walk-forward window is built and checked", reused by every backtest caller instead of drifting independently per-strategy. First consumer: `fib_gann_backtest` (see `apps/products/trading/agent-orchestrator/validation/`, not yet built).

## Why two window generators, not one

- `generate_windows_by_calendar()` — duration-driven (`train_months`/`test_months`/`embargo_days`), month arithmetic via `dateutil.relativedelta` so month-length variance and leap years are handled correctly. Defaults to `WindowMode.ANCHORED` (expanding train). This is what `fib_gann_backtest` uses.
- `generate_windows_by_candles()` — index-driven (`in_sample_len`/`out_sample_len`/`warmup_len` in candle counts), matching the scheme `ai-perp-bot-core`'s MARKOVIZ V5 already uses in `src/walkforward.ts` (`isLen=2000, oosLen=700, warmup=200`, rolling mode — confirmed by reading that file directly). Defaults to `WindowMode.ROLLING` to match it.

These were tuned independently for different systems; forcing one scheme onto the other would either break MARKOVIZ V5 comparability or impose an arbitrary calendar scheme MARKOVIZ V5 never used. `WalkForwardWindow` itself is duration-agnostic (four concrete UTC timestamps), so both generators produce the same type and `validate_window_set()`/downstream consumers don't need to know which one ran.

## Usage

```python
import datetime
from kinetiq_backtest import generate_windows_by_calendar, validate_window_set, WindowMode

windows = generate_windows_by_calendar(
    start=datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc),
    end=datetime.datetime(2025, 1, 1, tzinfo=datetime.timezone.utc),
    train_months=6,
    test_months=1,
    embargo_days=1,
    mode=WindowMode.ANCHORED,
)
validate_window_set(windows, embargo=datetime.timedelta(days=1))
```

All datetimes must be timezone-aware (UTC) -- naive datetimes are rejected at construction, not silently assumed-UTC.

## Local dev

```bash
cd packages/backtest-core
pip install -e ".[dev]"
pytest tests/
```

See `docs/prd.md` for full context and design decisions (fib_gann_timing validation harness brief).
