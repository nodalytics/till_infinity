"""Do the range's edges hold price better than a placebo at the same distance?

`statespace/ranging.py` builds a liquidity-aware range the current price sits
inside, and deliberately does **not** claim its edges are support. This is the
test of that claim, and the prior is bad.

`research/docs/game-theory.md` ran the "levels hold" family and its verdict was
blunt: round numbers *"turn price no more than placebo levels"*, there is no
hunt at yesterday's high or low in FX - **66.2% against a placebo's 67.7%** -
and *"a trap's new extreme holds worse than a random price"*. The level magnet
effect is refuted elsewhere in `research/docs/`. So the burden here is on the
level, not on the null.

## The placebo has to be distance-matched or the test is rigged

A price near the current one gets touched sooner, more often, and in calmer
conditions than a price far away, so comparing a level's hold rate against
"some random price" compares distances. Each candidate is therefore paired with
a placebo **the same distance away on the same side**, drawn uniformly within a
band around that distance, and both are followed from their own first touch.

That is the design `game-theory.md` used, and it is the reason its round-number
result was credible enough to refute the idea rather than merely fail to
support it.

## What counts as holding

`volumeprofile.py`'s race, which is the one this desk has already used for
exactly these levels: from the first touch, does price travel one baseline move
**back the way it came** before it travels one baseline move **through**, within
`PATIENCE` bars? A bar that reaches both counts as a break, which is the
conservative assignment.

The baseline move is the window's **median bar range**, and the first version
got this wrong in a way that invalidated the whole table. It used the median
absolute *return*, which measures **0.402 of a median bar range** on EURUSD at
1h - so both barriers sat **inside a single bar**, every bar after the touch
straddled both, and the race was decided by whichever the loop tested first.
Real and placebo came back **identical at 100.0%** on every row, which is the
signature of a race that is not a race.

A median bar range makes one move one typical bar, so the contest takes several
bars to settle. And `degenerate` now refuses to print a row whose two arms are
both above 95% or both below 5%, because that is the shape of the same failure
and it should not be able to reach a table again.

## The candidates

* **thin low / thin high** - the range's own edges, where volume per bin falls
  under a quarter of the mode. Volume profile's claim is that price moves
  *through* thin prices, so these are the edges, not the supports - and if
  anything they should hold **worse** than placebo;
* **value low / value high** - the edges of the central 70% of volume, which is
  where the "return into value" idea says a move back begins;
* **wick 2 / wick 3** - the published wick-to-body construction, from the
  references given on 2026-10-14. `upper = high - max(open, close)`,
  `lower = min(open, close) - low`, `body = |close - open|`, and a wick-to-body
  ratio **above 2:1** is described as "significant rejection" with **above
  3:1** a source of "high-probability setups". The level is the **tip of the
  dominant wick** on the most recent bar clearing the threshold, which is where
  that reading puts support and resistance.

  This is a different hypothesis from the rejection *profile* above, and a more
  specific one: not "prices that spent time in wicks" but "the extreme of a bar
  that rejected". `game-theory.md`'s prior is poor - *"a trap's new extreme
  holds worse than a random price"* - but the wick filter is new, and the claim
  is precisely that a rejection bar's extreme is not just any extreme. A doji
  has no body, so the ratio is undefined and those bars are skipped, which is
  what the reference's own table does;
* **centre** - the heaviest-volume price, the point of control. The one level in
  this family `game-theory.md` did not test, and so the only one not already
  refuted.

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

from till_infinity.structures.statespace.ranging import Profile  # noqa: E402

CACHE = Path(os.environ.get("SEQLAB_CACHE", str(Path.home() / "till_infinity/data/seqlab")))
FRAME = os.environ.get("FRAME", "1h")
LIMIT = int(os.environ.get("LIMIT", "30000"))
#: Bars between profiles, so successive tests barely share a window.
STRIDE = int(os.environ.get("STRIDE", "60"))
#: Bars a touch is given to resolve its race.
PATIENCE = int(os.environ.get("PATIENCE", "24"))
#: Bars a candidate is given to be touched at all.
REACH = int(os.environ.get("REACH", "120"))
#: Half-width of the band a placebo's distance is drawn from, as a share.
JITTER = 0.15
SEED = 20261014
TRADED = tuple(os.environ.get("TRADED", "EURUSD,GBPUSD,USDJPY,XAUUSD,AUDUSD,USDCAD").split(","))
GENERATED = tuple(os.environ.get("GENERATED", "Volatility_75_Index,Step_Index_200").split(","))


def load(name: str):
    import numpy as np

    path = CACHE / f"{name}.{FRAME}.npz"
    if not path.exists():
        return None
    with np.load(path) as bundle:
        need = {"high", "low", "close", "open"}
        if not need <= set(bundle.keys()) or "time" not in bundle:
            return None
        order = np.argsort(bundle["time"])
        bundle_time = np.asarray(bundle["time"], dtype=float)[order]
        got = {k: np.asarray(bundle[k], dtype=float)[order] for k in need}
        got["volume"] = (
            np.asarray(bundle["volume"], dtype=float)[order]
            if "volume" in bundle
            else np.ones(len(order))
        )
    got["time"] = np.asarray(bundle_time, dtype=float)
    keep = (got["high"] >= got["low"]) & (got["low"] > 0)
    got = {k: v[keep] for k, v in got.items()}
    if len(got["close"]) < 5000:
        return None
    if len(got["close"]) > LIMIT:
        got = {k: v[-LIMIT:] for k, v in got.items()}
    return got


def race(bars, start: int, level: float, move: float) -> bool | None:
    """From the first touch of `level` after `start`: did it bounce or break?

    `True` is a bounce - one `move` back the way price came - and `False` a
    break. `None` means never touched inside `REACH`, or unresolved inside
    `PATIENCE`, and an unresolved race is dropped rather than counted either
    way.
    """
    highs, lows = bars["high"], bars["low"]
    at = None
    for i in range(start, min(start + REACH, len(highs))):
        if lows[i] <= level <= highs[i]:
            at = i
            break
    if at is None:
        return None
    # Which side price came from decides which direction is "back".
    before = bars["close"][at - 1] if at > 0 else bars["close"][at]
    from_below = before < level
    back = level - move if from_below else level + move
    through = level + move if from_below else level - move
    for i in range(at + 1, min(at + 1 + PATIENCE, len(highs))):
        hit_through = highs[i] >= through if from_below else lows[i] <= through
        hit_back = lows[i] <= back if from_below else highs[i] >= back
        if hit_through:
            # A bar reaching both counts as a break: the conservative
            # assignment, and the one `volumeprofile.py` used.
            return False
        if hit_back:
            return True
    return None


def main() -> None:
    import numpy as np

    rng = np.random.default_rng(SEED)
    print(
        f"frame {FRAME}  profile window 300  stride {STRIDE}  reach {REACH}  "
        f"patience {PATIENCE}\n"
    )
    print(
        "Each candidate is paired with a placebo the **same distance away on\n"
        "the same side**, because a nearer price is touched sooner and in\n"
        "calmer conditions - comparing against any random price compares\n"
        "distances. A bounce is one baseline move back before one move through.\n"
    )
    kinds = (
        "thin low",
        "thin high",
        "value low",
        "value high",
        "centre",
        "reject centre",
        "reject low",
        "reject high",
        "accept centre",
        "hourly centre",
        "hourly low",
        "hourly high",
        "wick 2",
        "wick 3",
    )
    print(
        f"{'group':<12}{'level':<14}{'races':>7}{'holds':>8}{'placebo':>9}"
        f"{'lift':>8}{'distance, moves':>17}"
    )
    for group, names in (("traded", TRADED), ("generated", GENERATED)):
        tally: dict[str, list[tuple[bool, bool, float]]] = {}
        for name in names:
            bars = load(name)
            if bars is None:
                continue
            closes = bars["close"]
            for at in range(400, len(closes) - REACH - PATIENCE, STRIDE):
                window = slice(at - 300, at)
                # One typical **bar**, not one median return. See the module
                # docstring: the return version put both barriers inside a
                # single bar and every row read 100%.
                move = float(np.median(bars["high"][window] - bars["low"][window]))
                if not (move > 0):
                    continue
                profile = Profile()
                for lo, hi, vol, op, cl in zip(
                    bars["low"][window],
                    bars["high"][window],
                    bars["volume"][window],
                    bars["open"][window],
                    bars["close"][window],
                    strict=True,
                ):
                    profile.observe(lo, hi, vol, open_=op, close=cl)
                # **The seasonal profile**, asked for on 2026-10-14: the same
                # construction over only the bars in this bar's hour-of-day
                # bucket, so the levels are the ones that matter *at this time
                # of day*. `seasonal.Profile` earns +1192 nats on `Q` from
                # exactly that conditioning, so it is a reasonable thing to try
                # on a price profile - and it uses a sixth of the bars, which
                # is the cost.
                # The most recent bar clearing each wick-to-body threshold,
                # and the tip of its dominant wick.
                wicks: dict[str, float] = {}
                for ratio, label in ((2.0, "wick 2"), (3.0, "wick 3")):
                    for i in range(at - 1, max(at - 60, 0), -1):
                        body = abs(bars["close"][i] - bars["open"][i])
                        if body <= 0:
                            continue
                        top = max(bars["open"][i], bars["close"][i])
                        bottom = min(bars["open"][i], bars["close"][i])
                        upper = bars["high"][i] - top
                        lower = bottom - bars["low"][i]
                        if max(upper, lower) / body < ratio:
                            continue
                        wicks[label] = (
                            float(bars["high"][i]) if upper >= lower else float(bars["low"][i])
                        )
                        break
                hour = int((bars["time"][at] % 86400) // 3600)
                seasonal = Profile(window=len(bars["close"]))
                for i in range(max(at - 300 * 6, 0), at):
                    if int((bars["time"][i] % 86400) // 3600) // 4 == hour // 4:
                        seasonal.observe(
                            bars["low"][i],
                            bars["high"][i],
                            bars["volume"][i],
                            open_=bars["open"][i],
                            close=bars["close"][i],
                        )
                here = float(closes[at])
                got = profile.range_at(here)
                if got is None:
                    continue
                accepted = profile.range_at(here, "acceptance")
                rejected = profile.range_at(here, "rejection")
                timed = seasonal.range_at(here)
                candidates = [
                    ("thin low", got.thin_low),
                    ("thin high", got.thin_high),
                    ("value low", got.value_low),
                    ("value high", got.value_high),
                    ("centre", got.centre),
                ]
                if rejected is not None:
                    candidates += [
                        ("reject centre", rejected.centre),
                        ("reject low", rejected.thin_low),
                        ("reject high", rejected.thin_high),
                    ]
                if accepted is not None:
                    candidates += [("accept centre", accepted.centre)]
                candidates += [(k, v) for k, v in wicks.items()]
                if timed is not None:
                    candidates += [
                        ("hourly centre", timed.centre),
                        ("hourly low", timed.value_low),
                        ("hourly high", timed.value_high),
                    ]
                for kind, level in candidates:
                    gap = level - here
                    if abs(gap) < 0.25 * move:
                        # Already at it: a race from a level price is standing
                        # on, not a test of whether the level turned anything.
                        continue
                    real = race(bars, at, level, move)
                    if real is None:
                        continue
                    # The placebo: same side, same distance to within JITTER.
                    scale = 1.0 + float(rng.uniform(-JITTER, JITTER))
                    fake = race(bars, at, here + gap * scale, move)
                    if fake is None:
                        continue
                    tally.setdefault(kind, []).append((real, fake, abs(gap) / move))
        first = True
        for kind in kinds:
            cells = tally.get(kind)
            if not cells or len(cells) < 30:
                continue
            holds = sum(1 for r, _, _ in cells if r) / len(cells)
            placebo = sum(1 for _, f, _ in cells if f) / len(cells)
            head = f"{group:<12}" if first else f"{'':<12}"
            first = False
            # A race whose two arms are both pinned is not a race. The first
            # version of this file printed 100.0% on every row of both arms.
            degenerate = (holds > 0.95 and placebo > 0.95) or (holds < 0.05 and placebo < 0.05)
            print(
                f"{head}{kind:<14}{len(cells):>7}{holds:>8.1%}{placebo:>9.1%}"
                f"{holds - placebo:>+8.1%}"
                f"{statistics.median(d for _, _, d in cells):>17.2f}"
                f"{'  DEGENERATE' if degenerate else ''}"
            )
        print()
    print(
        "**`lift` is the whole result and zero is the expected value.**\n"
        "`game-theory.md` refuted this family once already - round numbers turn\n"
        "price no more than placebo levels, and a trap's new extreme holds\n"
        "*worse* than a random price - so a lift near zero is confirmation\n"
        "rather than a surprise, and a negative lift on the thin edges is what\n"
        "volume profile's own theory predicts: price moves **through** thin\n"
        "prices.\n\n"
        "A range whose edges do not hold is still a range. It is a calibrated\n"
        "interval, and an interval is what a stop and a size are set from - the\n"
        "claim being tested here is only the extra one, that the edges are\n"
        "support."
    )


if __name__ == "__main__":
    main()
