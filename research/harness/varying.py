"""Every number this package publishes, and whether any of it varies.

## Why

`run_vol` and `pivot` read identically zero across 20,000 production outcomes
and nothing noticed until somebody cut by them by hand. `run_vol` had no
producer; `pivot`'s levels were skipped on the first line of `Engine.check`;
`round` could not form a level at all. Three different faults with one
symptom, and the symptom is the only cheap thing about them.

So this asks the question mechanically, of every producer at once:

    journal  - the authoritative answer wherever the record reaches. A field
               constant across thousands of real outcomes is dead in
               production, subject to the caveat below.
    fixture  - for everything the journal cannot reach, or cannot reach yet:
               a synthetic book rich enough to exercise every producer, so a
               field that is still constant is a genuine candidate.

## The caveat that is load-bearing

**Constant is not dead.** Nine macro features were called dead here on
2026-09-11 and every one carried real, moving values: they are *slow*.
`macro_us_core_inflation` is published monthly, so it is constant in any window
shorter than a month and will always look dead in one. Every reading below
carries the span it was measured over, in days, for exactly that reason - a
verdict without a window is not a verdict.

## The three kinds a genuine constant turns out to be

1. **No producer.** Nothing writes it (`run_vol` until 2026-09-11).
2. **Producer never reached.** It is written, but a guard upstream can never
   pass (`pivot`: `Engine.check` asked for a daily volatility estimate that no
   bar stream warms).
3. **Constant by construction.** The arithmetic cannot produce two values
   (`round`: a grid 2.5 volatility units apart against a clustering tolerance
   of 1.0, so every cluster held one point and `form` needs three). These are
   *provable* rather than sampled, and a proof beats a measurement.

## Running it

    .venv/bin/python research/harness/varying.py fixture
    .venv/bin/python research/harness/varying.py journal .data/journal/fresh.db

The journal route takes any journal database, including a read-only copy of
production's. It streams off the `entries_kind` index newest-first and never
materialises the table, so it is safe to point at a live file - but the
production instance has two cores and has been OOM-killed twenty-three times,
so run it against a copy, or over ssh at `nice -n 19` beside a copy of
`till_infinity/shared/liveness.py`, and never inside the container.

The fixture route is the synthetic book from `tests/test_published.py`, which
is where it lives because that is where it is *asserted*. This module adds the
readable table and the journal route; it does not own a second copy of the
book.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from till_infinity.shared import liveness

# --------------------------------------------------------------- the record


#: Distinct values tracked per field. A cap rather than a set, so a survey of a
#: million rows cannot grow without bound on a field that is a price.
CAP = 4_000


def _rows(db: str | Path, kind: str, limit: int, shape: str | None, stride: int) -> Iterator[tuple]:
    """Journal contexts, newest first, off the `(kind, time)` index.

    `stride` takes one row in N over a much longer window, which is the only
    way to see a weekly series without reading the whole database.
    """
    conn = sqlite3.connect(f"file:{Path(db)}?mode=ro", uri=True, timeout=20.0)
    conn.execute("PRAGMA query_only=ON")
    try:
        found = conn.execute(
            "SELECT time, context FROM entries WHERE kind=? ORDER BY time DESC LIMIT ?",
            (kind, limit * stride),
        )
        for i, (when, raw) in enumerate(found):
            if stride > 1 and i % stride:
                continue
            try:
                got = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if not isinstance(got, dict):
                continue
            if shape and got.get("shape") != shape:
                continue
            yield float(when), got
    finally:
        conn.close()


def spans(rows: Sequence[tuple[float, dict]]) -> dict[str, tuple[float, float]]:
    """First and last time each numeric field was *seen*, per field.

    Separate from the survey because a field present on a tenth of the rows was
    measured over a tenth of the window, and reporting the sample's span as if
    it were the field's is how a young field gets called dead.
    """
    found: dict[str, tuple[float, float]] = {}
    for when, got in rows:
        for key, value in got.items():
            if not isinstance(value, int | float) or isinstance(value, bool):
                continue
            lo, hi = found.get(key, (when, when))
            found[key] = (min(lo, when), max(hi, when))
    return found


def table(label: str, rows: Sequence[tuple[float, dict]]) -> str:
    """One producer's fields, worst first, with the window behind each."""
    readings = liveness.survey([got for _when, got in rows])
    window = spans(rows)
    lines = [f"===== {label}: {len(rows)} rows, {len(readings)} numeric fields ====="]
    lines.append(
        f"{'field':34s} {'seen':>7s} {'dist':>6s} {'top%':>6s} {'zero%':>6s} {'days':>7s}  verdict"
    )

    def order(item):
        name, reading = item
        return (0 if reading.constant is not None else (1 if reading.near_constant else 2), name)

    for name, reading in sorted(readings.items(), key=order):
        lo, hi = window.get(name, (0.0, 0.0))
        days = (hi - lo) / 86400.0
        if reading.constant is not None:
            verdict = f"CONSTANT {reading.constant:g}"
        elif reading.near_constant:
            verdict = f"near-constant ({reading.distinct} values)"
        else:
            verdict = f"{reading.distinct} values"
        lines.append(
            f"{name:34s} {reading.seen:7d} {reading.distinct:6d} {reading.share_top:6.3f} "
            f"{reading.share_zero:6.3f} {days:7.2f}  {verdict}"
        )
    return "\n".join(lines)


def journal(db: str | Path) -> str:
    """Every producer the journal reaches, dense and recent then sparse and long."""
    out = []
    for label, kind, shape, limit, stride in (
        ("decisions (level), recent", "decision", "level", 30_000, 1),
        ("decisions (level), 1-in-20 across the record", "decision", "level", 20_000, 20),
        ("outcomes, recent", "outcome", None, 30_000, 1),
        ("outcomes, 1-in-20 across the record", "outcome", None, 20_000, 20),
        ("observations (level), recent", "observation", "level", 30_000, 1),
    ):
        rows = list(_rows(db, kind, limit, shape, stride))
        if rows:
            out.append(table(label, rows))
    return "\n\n".join(out)


# -------------------------------------------------------------- the fixture
#
# **Borrowed from `tests/test_published.py`, not copied.** The synthetic book is
# the gate that runs in CI, and a second copy here would be the one that rots -
# `pyproject.toml` excludes `research` from both ruff and pytest, so this file
# has no lint gate and no test gate, and a fixture living only here is exactly
# the shape `research/inert.md` records twice already. What this module adds is
# the *journal* route and a readable table; the book itself belongs with the
# assertion it feeds.


def _gate():
    """The test module that owns the synthetic book."""
    import importlib.util

    here = Path(__file__).resolve().parents[2] / "tests" / "test_published.py"
    spec = importlib.util.spec_from_file_location("test_published", here)
    if spec is None or spec.loader is None:  # pragma: no cover - a broken checkout
        raise RuntimeError(f"cannot load the fixture from {here}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture(days: float | None = None, seed: int = 11) -> str:
    """Run the rich book and report what every producer put on a call."""
    import asyncio

    gate = _gate()
    got = asyncio.run(gate.drive(gate.DAYS if days is None else days, seed))
    published, resolved = got["published"], got["resolved"]
    print(f"  {len(published)} published, {len(resolved)} resolved")
    out = []
    if published:
        out.append(table("published level signals (fixture)", [(0.0, r) for r in published]))
    if resolved:
        out.append(table("resolved touch features (fixture)", [(0.0, r) for r in resolved]))
    return "\n\n".join(out)


def main() -> None:
    what = sys.argv[1] if len(sys.argv) > 1 else "fixture"
    if what == "journal":
        print(journal(sys.argv[2] if len(sys.argv) > 2 else ".data/journal/journal.db"))
    else:
        print(fixture(float(sys.argv[2]) if len(sys.argv) > 2 else None))


if __name__ == "__main__":
    main()
