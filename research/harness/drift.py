"""Report the break model's weights, and whether they are actually settling.

"Settling" is not a weight being small, it is the **movement between checks**
shrinking - so that is what this tracks, rather than leaving it to be eyeballed
across messages.

## Two ways this has lied, both fixed here

**It read a file nothing writes.** The path was hardcoded to `models.pkl`,
which stopped being the live state when the store moved to msgpack on
2026-09-04. The pickle sat unchanged from 07:05 onwards, so every check
compared one frozen snapshot against itself, movement came out at exactly
0.000, and it reported `SETTLED` three times in a row. A model that is not
being read cannot be seen to move.

**It unpickled by hand.** `pickle.load` on the raw file resolves module paths
literally, so the moment `structures/` grew subpackages it died with
`No module named 'till_infinity.structures.anomaly'` - and because the digest
runs it last over ssh, its exit code became the link's, and the watcher
reported the host unreachable for an hour while it was answering fine.

Both are the same mistake: reaching around `store.load`, which knows where the
state is, which format it is in, and how to follow a class that moved.

Run inside the container:

    docker exec till-infinity python /tmp/drift.py
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime

from till_infinity.structures import store

DIRECTORY = "/app/.data/structures"
#: On the mounted volume, not /tmp. The container is recreated on every deploy
#: and there have been a dozen today, so a mark in /tmp meant this reported
#: "first look" every time and the movement between checks - the thing it
#: exists to measure - was never once computed.
MARK = "/app/.data/drift.mark"
#: Total absolute movement across all weights, below which it is settling.
CALM = 0.05
#: Consecutive calm checks before saying so, once.
STREAK = 3


def find_breaks(node: object, depth: int = 0, seen: set[int] | None = None) -> object | None:
    """The `Breaks` model, wherever in the state it happens to sit."""
    seen = set() if seen is None else seen
    if depth > 8 or id(node) in seen:
        return None
    seen.add(id(node))
    if type(node).__name__ == "Breaks":
        return node
    if isinstance(node, dict):
        values: list = list(node.values())[:500]
    elif isinstance(node, list | tuple):
        values = list(node)[:80]
    elif hasattr(node, "__dict__"):
        values = list(vars(node).values())[:120]
    else:
        values = [getattr(node, k, None) for k in getattr(type(node), "__slots__", ())[:120]]
    for value in values:
        got = find_breaks(value, depth + 1, seen)
        if got is not None:
            return got
    return None


def main() -> None:
    state = store.load(DIRECTORY)
    if not state:
        print("drift: no state to read")
        return
    model = find_breaks(state)
    if model is None:
        print("drift: no break model in the state")
        return

    inner = getattr(model, "model", None)
    weights = list(getattr(inner, "weights", ()) or ())
    seen = float(getattr(inner, "seen", 0.0) or 0.0)
    if not weights:
        print(f"drift: the break model has no weights yet (seen {seen:.0f})")
        return

    from till_infinity.structures.learning.breaking import NAMES

    was: dict = {}
    if os.path.exists(MARK):
        try:
            with open(MARK) as fh:
                was = json.load(fh)
        except Exception:
            was = {}

    # The mark on the volume outlives this script, and an older version of it
    # wrote `weights` as a name->value mapping. Zipping a list of floats against
    # a dict iterates its *keys*, so the comparison died on `float - str`.
    # Normalised rather than assumed, since the file is not versioned.
    raw = was.get("weights") or []
    if isinstance(raw, dict):
        raw = [raw.get(name) for name in NAMES]
    before = [v for v in raw if isinstance(v, int | float)]
    moved = (
        sum(abs(a - b) for a, b in zip(weights, before, strict=False))
        if len(before) == len(weights)
        else None
    )
    # **A file that has not been rewritten cannot show movement**, and calling
    # that "settled" is the same mistake one level down: this script reported
    # SETTLED three times off a `models.pkl` frozen at 07:05. The state is
    # saved on its own cadence, so two checks inside one save window read the
    # same bytes and would score a perfect 0.000. Movement is only counted when
    # the file has actually been rewritten since the last look.
    stamped = os.path.getmtime(f"{DIRECTORY}/{store.STATE_FILE}")
    fresh = stamped != was.get("mtime")
    calm = int(was.get("calm") or 0)
    if moved is not None and not fresh:
        moved = None
    elif moved is not None and moved < CALM:
        calm += 1
    elif moved is not None:
        calm = 0

    named = " · ".join(
        f"{name} {value:+.3f}"
        for name, value in sorted(zip(NAMES, weights, strict=False), key=lambda kv: -abs(kv[1]))
    )
    stamp = datetime.now(UTC).strftime("%H:%M")
    if moved is None and not fresh:
        print(f"{stamp} breaks unchanged on disk since the last look, seen {seen:.0f}")
    elif moved is None:
        print(f"{stamp} breaks first look, seen {seen:.0f}: {named}")
    elif calm == STREAK:
        print(
            f"{stamp} breaks SETTLED - moved {moved:.3f} over {STREAK} checks, "
            f"seen {seen:.0f}: {named}"
        )
    elif calm < STREAK:
        print(f"{stamp} breaks moved {moved:.3f}, seen {seen:.0f}: {named}")

    with open(MARK, "w") as fh:
        json.dump({"weights": weights, "calm": calm, "seen": seen, "mtime": stamped}, fh)


if __name__ == "__main__":
    main()
