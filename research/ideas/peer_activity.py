"""Can a peer's activity drive this instrument's `Q`, beyond its own activity?

Two of this desk's largest measured effects sit next to each other and have
never been crossed.

* **Relationships are contemporaneous and live in volatility.** Median
  cross-instrument volatility correlation **+0.5170**, with 104 of 107 pairs
  beating their rotation null - against 0 of 190 on price lead-lag and 0 of
  1,625 on baskets. Whatever instruments share, they share it in variance and
  they share it *now*;
* **activity drives variance.** `statespace-activity-on-q.md`: a bar's own tick
  count on `Q` is worth **+2197** nats median against the clock's +675, on 8 of
  8 traded instruments.

So if two instruments' variances move together, and variance is driven by
activity, a **peer's** activity should carry information about this
instrument's variance. That is the arm.

## The null that decides it

Peer activity is correlated with own activity - a busy hour is busy everywhere -
so a peer arm will score well simply by being a noisy copy of the own arm.
Two things separate those:

* the **joint** arm against own alone. If the peer is only a proxy, adding it
  to the own arm earns nothing;
* a **rotated peer**, whose volume series is rotated in time. That keeps the
  peer's marginal distribution and its own serial structure exactly, and
  destroys only its alignment to this instrument's bars. A peer arm that
  survives rotation was reading the calendar, not the peer.

Both are reported, and the rotated arm is the one to read first.

## The controls

A **generated** peer, whose tick count is fixed by Deriv's generator, carries
no participant activity at all - so it must earn nothing, and if it does not,
the harness is reading something other than activity. And a generated
**target**, whose own variance is specified, cannot be helped by anything.

Runs on the lab.
"""

from __future__ import annotations

import math
import os
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from till_infinity.statespace.driven import Driven  # noqa: E402
from till_infinity.statespace.pacing import Pace  # noqa: E402
from till_infinity.statespace.seasonal import Seasonal  # noqa: E402

HOUR = 3600.0
CACHE = Path(os.environ.get("SEQLAB_CACHE", str(Path.home() / "till_infinity/data/seqlab")))
FRAME = os.environ.get("FRAME", "1h")
LIMIT = int(os.environ.get("LIMIT", "30000"))
SEED = 20261013
GRID = tuple(float(x) for x in os.environ.get("GRID", "0.03,0.0625,0.125,0.25,0.5,1,2").split(","))
EXPONENT = float(os.environ.get("EXPONENT", "2"))
ROTATIONS = int(os.environ.get("ROTATIONS", "6"))

#: `(target, peer, why)`. Pairs chosen for a **reason**, not by search: each is
#: a relationship this desk has already measured, so the arm tests a named
#: hypothesis rather than fishing across a grid of pairs.
PAIRS = (
    ("EURUSD", "GBPUSD", "two dollar majors, the strongest vol pair here"),
    ("GBPUSD", "EURUSD", "the same pair, the other way round"),
    ("XAUUSD", "XAGUSD", "the two precious metals"),
    ("XAGUSD", "XAUUSD", "and back"),
    ("USDCAD", "US_Oil", "the commodity-currency link, measured at -0.2260"),
    ("AUDUSD", "XAUUSD", "the other commodity-currency link, +0.1135"),
    ("USDJPY", "EURUSD", "a major against a major with no story"),
    # Controls: a generated peer has no participant activity to lend.
    ("EURUSD", "Boom_500_Index", "CONTROL: a generated peer"),
    ("XAUUSD", "Step_Index_200", "CONTROL: a generated peer"),
    # And a generated target cannot be helped by anything.
    ("Boom_500_Index", "EURUSD", "CONTROL: a generated target"),
)


def load(name: str):
    import numpy as np

    path = CACHE / f"{name}.{FRAME}.npz"
    if not path.exists():
        return None
    with np.load(path) as bundle:
        if not {"time", "close", "volume"} <= set(bundle.keys()):
            return None
        order = np.argsort(bundle["time"])
        times = bundle["time"][order]
        closes = bundle["close"][order]
        volumes = bundle["volume"][order]
    keep = (closes > 0) & (volumes > 0)
    times, closes, volumes = times[keep], closes[keep], volumes[keep]
    if len(times) > LIMIT:
        times, closes, volumes = times[-LIMIT:], closes[-LIMIT:], volumes[-LIMIT:]
    if len(times) < 5000:
        return None
    return times, np.log(closes), volumes


def together(target, peer):
    """The target's bars, with the peer's volume at the same timestamps."""
    import numpy as np

    stamps = np.intersect1d(target[0], peer[0])
    if len(stamps) < 5000:
        return None
    _, ti, _ = np.intersect1d(target[0], stamps, return_indices=True)
    _, pi, _ = np.intersect1d(peer[0], stamps, return_indices=True)
    return stamps, target[1][ti], target[2][ti], peer[2][pi]


class Driver:
    """Own activity, a peer's, or their normalised product."""

    def __init__(self, *, own: bool, peer: bool, exponent: float) -> None:
        self.own = Pace(exponent=exponent) if own else None
        self.peer = Pace(exponent=exponent) if peer else None
        self.mean = 0.0

    def control(self, mine: float, theirs: float) -> float:
        factor = 1.0
        if self.own is not None:
            self.own.update(mine)
            factor *= self.own.factor(mine)
        if self.peer is not None:
            self.peer.update(theirs)
            factor *= self.peer.factor(theirs)
        if self.own is None or self.peer is None:
            return factor - 1.0
        # The product of two mean-one factors is not mean-one when they are
        # correlated, and two instruments' activity is correlated by the very
        # effect this arm is testing. Renormalised for the same reason
        # `pacing.Both` is.
        if not math.isfinite(factor) or factor <= 0:
            return 0.0
        if not self.mean:
            self.mean = factor
        else:
            self.mean += (1.0 - 0.5 ** (1.0 / 60.0)) * (factor - self.mean)
        return (factor / self.mean - 1.0) if self.mean > 0 else 0.0


def score(stamps, values, mine, theirs, *, base, own: bool, peer: bool):
    """Held-out loglike on the second half, and the realised mean factor."""
    steps = [abs(values[i] - values[i - 1]) for i in range(1, len(values))]
    noise = statistics.pstdev(steps) or 1e-9
    start = len(stamps) // 2
    member = Driven(build=lambda: Seasonal(seasonal_on=False, level_wander=base), lever="level_wander")
    driver = Driver(own=own, peer=peer, exponent=EXPONENT)
    for when, value, a, b in zip(stamps, values, mine, theirs, strict=True):
        member.predict(float(when), driver.control(float(a), float(b)))
        member.update(float(value), noise * noise, float(when))
        if member.seen == start:
            member.loglike = 0.0
    return member.loglike, member.average


def best_base(stamps, values, mine, theirs, natural):
    found = []
    for multiple in GRID:
        base = natural * multiple
        if base <= 0:
            continue
        got, _ = score(stamps, values, mine, theirs, base=base, own=False, peer=False)
        if math.isfinite(got):
            found.append((got, base, multiple))
    if not found:
        return 0.0, float("nan")
    got, base, multiple = max(found)
    if multiple in (GRID[0], GRID[-1]):
        print(f"    (base pinned at grid edge {multiple}x)")
    return base, got


def main() -> None:
    import numpy as np

    print(f"frame {FRAME}  exponent {EXPONENT}  rotations {ROTATIONS}\n")
    print(
        "`own` is this instrument's own activity on Q, already measured at\n"
        "+2197 nats median. `peer` is the other instrument's activity instead.\n"
        "`both` is the normalised product, and it is the arm that says whether\n"
        "the peer carries anything the instrument's own activity does not.\n"
        "`peer rot` rotates the peer's volume in time, keeping its marginal and\n"
        "its serial structure and destroying only its alignment - read it first.\n"
    )
    print(
        f"{'target':<16}{'peer':<18}{'bars':>8}{'flat':>10}"
        f"{'own':>9}{'peer':>9}{'peer rot':>10}{'both':>9}{'adds':>7}"
    )
    picker = np.random.default_rng(SEED)
    rows = []
    for target_name, peer_name, why in PAIRS:
        target, peer = load(target_name), load(peer_name)
        if target is None or peer is None:
            print(f"{target_name:<16}{peer_name:<18}  not cached")
            continue
        got = together(target, peer)
        if got is None:
            print(f"{target_name:<16}{peer_name:<18}  too few common bars")
            continue
        stamps, values, mine, theirs = got
        gaps = np.diff(stamps[:500])
        dt = float(np.median(gaps)) / HOUR if len(gaps) else 1.0
        spread = float(np.std(np.diff(values))) or 1e-9
        base, flat = best_base(stamps, values, mine, theirs, spread * spread / dt)
        if base <= 0:
            continue
        own, _ = score(stamps, values, mine, theirs, base=base, own=True, peer=False)
        peer_got, _ = score(stamps, values, mine, theirs, base=base, own=False, peer=True)
        both, _ = score(stamps, values, mine, theirs, base=base, own=True, peer=True)
        spun = []
        for _ in range(ROTATIONS):
            shift = int(picker.integers(500, max(len(theirs) - 500, 501)))
            rolled = np.roll(theirs, shift)
            value, _ = score(stamps, values, mine, rolled, base=base, own=False, peer=True)
            spun.append(value - flat)
        rotated = statistics.median(spun)
        adds = both - flat > own - flat
        print(
            f"{target_name:<16}{peer_name:<18}{len(stamps):>8,}{flat:>10.0f}"
            f"{own - flat:>9.0f}{peer_got - flat:>9.0f}{rotated:>10.0f}"
            f"{both - flat:>9.0f}{'yes' if adds else 'no':>7}"
        )
        rows.append(
            {
                "target": target_name,
                "peer": peer_name,
                "control": why.startswith("CONTROL"),
                "own": own - flat,
                "peer": peer_got - flat,
                "rotated": rotated,
                "both": both - flat,
            }
        )

    if not rows:
        print("nothing scored")
        return

    print("\n" + "=" * 100)
    print("does the peer carry anything, once rotation and the own arm are allowed for")
    print("=" * 100)
    live = [r for r in rows if not r["control"]]
    checks = [r for r in rows if r["control"]]
    for label, here in (("named pairs", live), ("CONTROLS", checks)):
        if not here:
            continue
        print(
            f"\n{label}: {len(here)} cells\n"
            f"  own      median {statistics.median([r['own'] for r in here]):>9.0f}\n"
            f"  peer     median {statistics.median([r['peer'] for r in here]):>9.0f}\n"
            f"  peer rot median {statistics.median([r['rotated'] for r in here]):>9.0f}"
            "   <- the peer arm with alignment destroyed\n"
            f"  both     median {statistics.median([r['both'] for r in here]):>9.0f}"
        )
        beats = sum(1 for r in here if r["peer"] > r["rotated"])
        adds = sum(1 for r in here if r["both"] > r["own"])
        print(f"  peer beats its rotation on {beats} of {len(here)}")
        print(f"  both beats own alone on    {adds} of {len(here)}")
    print(
        "\n**The two questions are different and only the second one matters\n"
        "for the library.** A peer arm that beats rotation says peer activity\n"
        "carries variance information. `both` beating `own` says it carries\n"
        "information the instrument's *own* activity does not - and only that\n"
        "would justify a member reaching outside its own feed."
    )


if __name__ == "__main__":
    main()
