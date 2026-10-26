"""`argmax` scores best in the grid. What does winner-take-all cost in continuity?

[`pool-spread.md`](../docs/pool-spread.md)'s grid has already answered the
scoring question, so this does not re-ask it. At the shipped `R = 0.670`,
across both frames and both clamps, `argmax` reads `var z` of **1.009 to
1.063** - the closest to one of any rule - and **the lowest CRPS of all twelve
arms on every class** (0.5146 against `shrinking`'s 0.5242 on fx_cross 1h), for
a band cost of +0.003 to +0.008.

**What the grid cannot see is that `argmax` is a different kind of estimator.**
`shrinking` and `mixture` are weighted blends, so their published `value` and
`spread` move as smoothly as their members do. `argmax` is winner-take-all:
`_combine` picks the single most precise member and publishes **its** state and
**its** spread, so when the winner changes, both jump discontinuously with
nothing in the data necessarily having jumped.

`pooling.py` says the switching is where the value comes from - "beats a member
chosen at random each step by 4.7-fold, and one good member held throughout by
5.3-fold" - and that was measured on **log closes**, where a jump in the
published level is a jump in a price forecast. Here the published quantity goes
onto a decision card and may one day size a trade, so the question is what the
switching costs an output rather than what it earns a score.

## What this measures

Per class, at the shipped `R` and the shipped clamp, for all three rules:

* **switch rate** - the share of bars on which the argmax winner changes, and
  the mean run length between switches. A rule that switches every other bar
  is a different object from one that holds for a day;
* **jump size** - the median and 99th percentile of `|d log_variance|` and of
  `|d log spread|` between consecutive publications, against the same
  quantities for `shrinking`. A consumer differencing the published series sees
  this directly;
* **how much of the jump is the switch** - the same statistics restricted to
  the bars where the winner changed, against the bars where it did not. If
  they are the same, the switching is not what moves the output and the
  continuity worry is unfounded;
* **which members win, and how often.** `pooling.py` exposes `weights` as a
  one-hot vector for exactly this. A rule that picks one member 95% of the time
  is that member with extra steps, and `statespace-estimator-on-touches.md`'s
  5.6x came from pooling rather than from selection.

The constant-sigma family is the null: there the members agree, so the winner
should be near-arbitrary and the jumps should be small - a rule that produces
large jumps *there* is producing them from nothing.

**No pre-registered ship criterion, deliberately.** The grid's band line
already fails for every rule including this one (`argmax` 0.1099-0.1163 against
0.090-0.110), so nothing here can ship on its own. This is here to say what
`argmax` would cost if the band question is ever solved, and to stop it being
adopted on a CRPS win alone.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
for q in (HERE, HERE.parent, HERE.parents[1]):
    sys.path.insert(0, str(q))

from pattern_fingerprint import CACHE, classify, load  # noqa: E402

from till_infinity.statespace.engine import dispersion  # noqa: E402
from till_infinity.statespace.pooling import DEFAULT, Pooled  # noqa: E402

#: The shipped configuration, because that is the one a decision would be made
#: in. `adapting-strata.md` measured the clamp not binding here.
NOISE = 0.670
RULES = ("shrinking", "mixture", "argmax")

FRAMES = ("1h", "15m")
TRADED = ("fx_major", "fx_cross", "metal")
CONTROLS = ("volatility",)
PER_CLASS = 3
LIMIT = 12_000
WARM = 500


def _fold(values: np.ndarray, stamps: np.ndarray, rule: str) -> dict[str, np.ndarray]:
    """Fold once, recording the published series and who won each bar."""
    pool = Pooled(names=DEFAULT, rule=rule)
    value = np.full(len(values), np.nan)
    spread = np.full(len(values), np.nan)
    winner = np.full(len(values), -1)
    for i, one in enumerate(values):
        pool.predict(float(stamps[i]), 0.0)
        pool.update(float(one), NOISE, float(stamps[i]))
        value[i] = float(pool.value)
        spread[i] = float(pool.variance) + NOISE
        weights = tuple(pool.weights)
        if weights:
            winner[i] = int(max(range(len(weights)), key=lambda k: weights[k]))
    return {"value": value, "spread": spread, "winner": winner}


def _continuity(got: dict[str, np.ndarray]) -> dict[str, float]:
    value = got["value"][WARM:]
    spread = got["spread"][WARM:]
    winner = got["winner"][WARM:]
    moved = np.abs(np.diff(value))
    widened = np.abs(np.diff(np.log(np.maximum(spread, 1e-300))))
    switched = winner[1:] != winner[:-1]
    runs = []
    length = 0
    for flag in switched:
        length += 1
        if flag:
            runs.append(length)
            length = 0
    out = {
        "switch_rate": float(switched.mean()),
        "run_length": float(np.median(runs)) if runs else math.inf,
        "d_value_p50": float(np.median(moved)),
        "d_value_p99": float(np.quantile(moved, 0.99)),
        "d_spread_p50": float(np.median(widened)),
        "d_spread_p99": float(np.quantile(widened, 0.99)),
    }
    if switched.any() and (~switched).any():
        out["d_value_on_switch"] = float(np.median(moved[switched]))
        out["d_value_on_hold"] = float(np.median(moved[~switched]))
    else:
        out["d_value_on_switch"] = math.nan
        out["d_value_on_hold"] = float(np.median(moved))
    counts = np.bincount(winner[winner >= 0], minlength=len(DEFAULT)).astype(float)
    share = counts / max(counts.sum(), 1.0)
    for name, part in zip(DEFAULT, share, strict=False):
        out[f"won.{name}"] = float(part)
    return out


def _series(name: str, frame: str) -> tuple[np.ndarray, np.ndarray] | None:
    bars = load(name, frame)
    if bars is None:
        return None
    bars = {k: v[-LIMIT:] for k, v in bars.items()}
    out: list[float] = []
    when: list[float] = []
    for i in range(len(bars["close"])):
        one = dispersion(
            float(bars["open"][i]),
            float(bars["high"][i]),
            float(bars["low"][i]),
            float(bars["close"][i]),
        )
        if one is not None:
            out.append(one)
            when.append(float(bars["time"][i]))
    values = np.asarray(out, dtype=float)
    stamps = np.asarray(when, dtype=float)
    return (values, stamps) if len(values) > WARM + 2_000 else None


def main() -> None:
    print(
        "`argmax` scores best in the grid; this asks what winner-take-all costs a\n"
        f"published series. Shipped configuration: R = {NOISE}, default clamp, because\n"
        "that is where a decision would be made. The grid already answered scoring,\n"
        "so nothing here re-asks it - and nothing here can ship on its own, because\n"
        "the band line fails for every rule including this one.\n",
        flush=True,
    )
    groups: dict[str, list[str]] = {}
    for path in sorted(CACHE.glob("*.1h.npz")):
        name = path.name[: -len(".1h.npz")]
        groups.setdefault(classify(name), []).append(name)
    wanted = {k: v[:PER_CLASS] for k, v in groups.items() if k in TRADED + CONTROLS}
    print("classes:", ", ".join(f"{k} ({len(v)})" for k, v in sorted(wanted.items())), flush=True)

    for frame in FRAMES:
        print(f"\n=== {frame}: continuity of the published series")
        print(
            f"{'class':>12}{'rule':>10}{'switch/bar':>12}{'run':>7}"
            f"{'|dvalue| p50':>14}{'p99':>9}{'|dlogsd2| p50':>15}{'p99':>9}"
            f"{'switch/hold':>13}"
        )
        for klass, names in sorted(wanted.items()):
            series = [got for got in (_series(n, frame) for n in names) if got is not None]
            if not series:
                continue
            shares: dict[str, dict[str, float]] = {}
            for rule in RULES:
                rows = [_continuity(_fold(v, t, rule)) for v, t in series]
                take = lambda key: float(np.median([r[key] for r in rows]))  # noqa: E731
                ratio = take("d_value_on_switch") / max(take("d_value_on_hold"), 1e-12)
                print(
                    f"{klass:>12}{rule:>10}{take('switch_rate'):>12.4f}"
                    f"{take('run_length'):>7.1f}{take('d_value_p50'):>14.4f}"
                    f"{take('d_value_p99'):>9.4f}{take('d_spread_p50'):>15.4f}"
                    f"{take('d_spread_p99'):>9.4f}{ratio:>13.2f}",
                    flush=True,
                )
                shares[rule] = {n: take(f"won.{n}") for n in DEFAULT}
            won = ", ".join(f"{n} {shares['argmax'][n]:.2f}" for n in DEFAULT)
            print(f"{'':>12}argmax won: {won}")
    print(
        "\n\n`switch/hold` is the ratio of the median published move on a bar where the\n"
        "winner changed to one where it did not. Near one means the switching is not\n"
        "what moves the output and the continuity worry is unfounded; well above one\n"
        "means `argmax` publishes jumps the data did not make. And a class where one\n"
        "member wins almost every bar is that member with extra steps - the 5.6x in\n"
        "`statespace-pooling-exponent.md` came from pooling, not from selecting.",
        flush=True,
    )


if __name__ == "__main__":
    main()
