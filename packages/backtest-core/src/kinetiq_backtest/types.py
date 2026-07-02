"""Shared walk-forward window type (docs/prd.md fib_gann_timing validation
harness design brief, Section 5 "shared walk-forward util"). Exists so
window-generation logic is defined exactly once and reused by every
backtest caller (fib_gann_backtest today, any future strategy validation)
instead of drifting independently per-strategy -- two strategies picking
different window definitions would make their results incomparable without
anyone realizing it.

WalkForwardWindow itself is duration-agnostic: it stores four concrete
timestamps, not a train_months/in_sample_len-style parameter. windowing.py
has two generators that produce it -- one calendar-duration-driven
(generate_windows_by_calendar, what fib_gann_backtest uses), one candle-
count-driven (generate_windows_by_candles, matching the scheme
ai-perp-bot-core's MARKOVIZ V5 already uses in src/walkforward.ts: fixed
in-sample/out-of-sample/warmup candle counts, not calendar months) -- so
neither caller is forced onto a scheme that doesn't match how its own
config was already tuned.
"""

import dataclasses
import datetime
import enum


class WindowMode(enum.Enum):
    ROLLING = "rolling"  # fixed-size train window, slides forward each step
    ANCHORED = "anchored"  # train window start is fixed, train_end expands each step


def require_utc(value: datetime.datetime, name: str) -> None:
    """Naive datetimes are rejected outright, not silently assumed-UTC --
    this is exactly the class of DST-adjacent bug walk-forward windowing
    should never allow (docs/prd.md validation harness brief, Section 7)."""
    if not isinstance(value, datetime.datetime):
        raise TypeError(f"{name} must be a datetime.datetime, got {type(value)!r}")
    if value.tzinfo is None:
        raise ValueError(
            f"{name} must be timezone-aware (UTC) -- naive datetimes are rejected, not assumed-UTC: {value!r}"
        )


@dataclasses.dataclass(frozen=True)
class WalkForwardWindow:
    """One train/test split. All four timestamps must be UTC-aware."""

    window_id: int
    train_start: datetime.datetime
    train_end: datetime.datetime
    test_start: datetime.datetime
    test_end: datetime.datetime

    def __post_init__(self) -> None:
        for field_name in ("train_start", "train_end", "test_start", "test_end"):
            require_utc(getattr(self, field_name), field_name)
        if self.train_end <= self.train_start:
            raise ValueError(f"window {self.window_id}: train_end must be after train_start")
        if self.test_end <= self.test_start:
            raise ValueError(f"window {self.window_id}: test_end must be after test_start")
        if self.test_start < self.train_end:
            raise ValueError(
                f"window {self.window_id}: test_start ({self.test_start}) is before "
                f"train_end ({self.train_end}) -- data leak"
            )
