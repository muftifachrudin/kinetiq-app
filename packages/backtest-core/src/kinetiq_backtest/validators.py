"""Sanity checks over a generated window set. Kept separate from the
generators themselves (windowing.py) so a hand-built or externally-loaded
window list can be validated the same way as a generated one.
"""

import datetime

from kinetiq_backtest.types import WalkForwardWindow


def validate_window_set(
    windows: list[WalkForwardWindow],
    embargo: datetime.timedelta = datetime.timedelta(0),
    allow_test_overlap: bool = False,
) -> None:
    """Raises ValueError on the first violation found. WalkForwardWindow's
    own __post_init__ already rejects a leak/inverted window at
    construction time; this additionally checks properties that only make
    sense across the whole set: embargo gap, duplicate IDs, and (unless
    allow_test_overlap=True) overlapping test ranges between windows."""
    seen_ids: set[int] = set()
    for w in windows:
        if w.window_id in seen_ids:
            raise ValueError(f"duplicate window_id: {w.window_id}")
        seen_ids.add(w.window_id)

        gap = w.test_start - w.train_end
        if gap < embargo:
            raise ValueError(
                f"window {w.window_id}: embargo gap {gap} is shorter than required {embargo}"
            )

    if not allow_test_overlap:
        by_test_start = sorted(windows, key=lambda w: w.test_start)
        for a, b in zip(by_test_start, by_test_start[1:]):
            if b.test_start < a.test_end:
                raise ValueError(
                    f"windows {a.window_id} and {b.window_id} have overlapping test ranges "
                    f"(pass allow_test_overlap=True if this is intentional)"
                )
