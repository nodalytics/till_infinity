"""Why the published spread is three times too small, and whether R was covering for it.

`dispersion-noise.md` measured the estimator's sampling variance at **0.265**
and then found that on real bars the filter needs **R near 1.0** for its
one-step innovations to have unit variance, while the constant-sigma control
needs 0.28 - the simulated constant. It called the excess latent movement `Q`
is not absorbing and named a `Q` sweep as the next run.

**That sweep would be sweeping a lever that already moves itself.** Every
member in `Pooled` is wrapped in `adapting.Adapting` in matching mode by
default, whose entire job is to drive the exponentially weighted square of its
standardised innovation to 1.0. If each member is matched and the pool is not,
no amount of `Q` fixes it, because the gap is not in the members.

## What the gap actually is, on the evidence already on disk

`pooling.py` chooses `shrinking` for the spread rule, and records why: the
alternative, `mixture`, is the law of total variance and "cannot fall below the
members' own disagreement", and it **lost by up to threefold on CRPS**. The
same docstring says "the members disagree far more than their individual
uncertainties justify".

So the published spread deliberately **excludes** the between-member term,
while the members individually have their `Q` matched to their own
innovations. A pool built that way is over-confident by exactly the term it
drops - which is what a `var z` of 3.2 to 3.8 at the measured `R` is.

And that gives a second reading of the shipped `noise = 0.67`: it is 2.5x the
estimator's sampling variance, and at that value the published `var z` lands at
1.2 to 1.4. **`R` has been covering for the pooling rule.** Two choices made
independently, each defensible alone, that only calibrate together.

## What it found, so the docstring does not outlive the result

The premise below is **wrong**, and measuring it was the point. The members are
not matched on markets - `E[z^2]` reads 2.0 to 3.1 per member at the measured
`R` - and they are matched to within 3% on the constant-sigma control. So the
excess is inside the members before any pooling rule applies, and `mixture`
fixes the published spread at 15m while overshooting at 1h. `pool-spread.md`
has the table. The default did not move.

## The grid, and why it is a grid rather than a sweep

`mixture` was rejected on CRPS **at the old R**, and `refit-the-parameter-a-
lever-multiplies` is the standing lesson: a rule that adds variance was judged
against a noise already 2.5x too large, so it was over-wide twice and could not
have won. Rule and `R` have to move together or neither reading means anything.

* rules: `shrinking` (shipped), `mixture` (law of total variance), `argmax`;
* `R`: the measured 0.265, an intermediate 0.40, the shipped 0.67;
* one reference arm with `adapt=False`, which is what every `rule` and `alpha`
  figure in `pooling.py` was originally measured on.

Scored one step ahead against the next bar's observation: `var z` for whether
the spread is honest, CRPS for what the rule was chosen on, and the breach rate
of `Readout.covering` at three coverages for what a consumer actually sees. The
constant-sigma Deriv family is the control: there the members have nothing to
disagree about, so `shrinking` and `mixture` should converge and `var z` should
sit at one when `R` is the measured value.

**The per-member diagnostic settles the premise.** Under the shipped
configuration the harness also reports `E[z^2]` for each member against the
pool's, so "the members are matched and the pool is not" is a measurement
rather than an inference from two docstrings.
"""

from __future__ import annotations

import math
import sys
from collections import deque
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
for q in (HERE, HERE.parent, HERE.parents[1]):
    sys.path.insert(0, str(q))

from pattern_fingerprint import CACHE, classify, load  # noqa: E402

from till_infinity.statespace.diagnostics import crps  # noqa: E402
from till_infinity.statespace.engine import dispersion  # noqa: E402
from till_infinity.statespace.facade import Desk  # noqa: E402
from till_infinity.statespace.adapting import MOST, Adapting  # noqa: E402
from till_infinity.statespace.pacing import Pace  # noqa: E402
from till_infinity.statespace.pooling import DEFAULT, LEVERS, Pooled, _factories  # noqa: E402

RULES = ("shrinking", "mixture", "argmax")
NOISES = (0.265, 0.670)
#: The matching loop's clamp. `adapting.MOST` ships at 1e3 and
#: `adapting_strata.md` measured every traded member **pinned against it**,
#: with the loop converging at a factor of 1.3 to 4.2 million once released -
#: so the first column here is the shipped configuration and the second is the
#: one where the members can reach their own target.
CLAMPS = (MOST, 1e7)
COVERS = (0.90, 0.95, 0.99)

FRAMES = ("15m", "1h")
TRADED = ("fx_major", "fx_cross", "metal")
CONTROLS = ("volatility",)
PER_CLASS = 3
LIMIT = 12_000
WARM = 500


def _prepared(rule: str, adapt: bool, feed: str, interval: str, most: float = MOST) -> Desk:
    """A desk whose one member is built with the rule under test.

    `Desk.read` only builds a member when the key is missing, so seeding all
    three of its maps is enough to change the rule without touching the
    package. Seeding `_members` alone raises on the next line, where `_paces`
    is read.
    """
    desk = Desk()
    key = (feed, interval)
    if adapt:
        built = _factories(DEFAULT)
        desk._members[key] = Pooled(
            names=DEFAULT,
            rule=rule,
            _pool=[
                Adapting(build=make, lever=LEVERS.get(name, "jerk"), mode="matching", most=most)
                for name, make in zip(DEFAULT, built, strict=False)
            ],
        )
    else:
        desk._members[key] = Pooled(rule=rule, adapt=False)
    desk._paces[key] = Pace(exponent=desk.exponent)
    desk._residuals[key] = deque(maxlen=desk.window)
    return desk


def _score(
    bars: dict,
    frame: str,
    feed: str,
    noise: float,
    rule: str,
    adapt: bool = True,
    most: float = MOST,
) -> dict[str, float]:
    """One pass of the service's own path, at one rule, noise and clamp."""
    desk = _prepared(rule, adapt, feed, frame, most)
    when = bars["time"]
    o, h, lo, c = bars["open"], bars["high"], bars["low"], bars["close"]
    breaches = dict.fromkeys(COVERS, 0)
    seen = scored = 0
    total_crps = 0.0
    zs: list[float] = []
    members: dict[str, list[float]] = {}
    previous = None
    for i in range(len(c)):
        value = dispersion(float(o[i]), float(h[i]), float(lo[i]), float(c[i]))
        if value is None:
            continue
        seen += 1
        if previous is not None and seen > WARM:
            scored += 1
            for cover in COVERS:
                band = previous.covering(cover)
                if not band.low <= value <= band.high:
                    breaches[cover] += 1
            if previous.quantiles:
                total_crps += crps(previous.quantiles, value)
        got = desk.read(feed, frame, float(when[i]), value, noise)
        if seen > WARM:
            zs.append(got.surprise)
            pool = desk._members[(feed, frame)]
            for name, sub in zip(pool.names, pool._pool, strict=False):
                standardised = float(getattr(sub, "last_standardised", 0.0))
                if math.isfinite(standardised):
                    members.setdefault(name, []).append(standardised)
        previous = got
    if scored < 1_000:
        return {}
    out = {f"breach_{int(100 * cover)}": breaches[cover] / scored for cover in COVERS}
    out["zvar"] = float(np.var(zs)) if zs else float("nan")
    out["crps"] = total_crps / scored
    out["n"] = float(scored)
    for name, values in members.items():
        out[f"member.{name}"] = float(np.mean(np.square(values)))
    return out


def main() -> None:
    print(
        "Is the published spread too small because `Q` is, or because the pool\n"
        "drops the between-member term? Rule and R swept together, because the\n"
        "rule was chosen on CRPS at an R now measured 2.5x too large.\n"
        f"R candidates {NOISES}, rules {RULES}, scored one step ahead.\n",
        flush=True,
    )
    groups: dict[str, list[str]] = {}
    for path in sorted(CACHE.glob("*.1h.npz")):
        name = path.name[: -len(".1h.npz")]
        groups.setdefault(classify(name), []).append(name)
    wanted = {k: v[:PER_CLASS] for k, v in groups.items() if k in TRADED + CONTROLS}
    print("classes:", ", ".join(f"{k} ({len(v)})" for k, v in sorted(wanted.items())), flush=True)

    for frame in FRAMES:
        rows: dict[tuple[str, str, float, float], list[dict[str, float]]] = {}
        reference: dict[str, list[dict[str, float]]] = {}
        for klass, names in sorted(wanted.items()):
            for name in names:
                bars = load(name, frame)
                if bars is None:
                    continue
                bars = {k: v[-LIMIT:] for k, v in bars.items()}
                for most in CLAMPS:
                    for rule in RULES:
                        for noise in NOISES:
                            got = _score(bars, frame, name, noise, rule, most=most)
                            if got:
                                rows.setdefault((klass, rule, noise, most), []).append(got)
                got = _score(bars, frame, name, 0.670, "shrinking", adapt=False)
                if got:
                    reference.setdefault(klass, []).append(got)
        if not rows:
            print(f"\n=== {frame}: nothing loaded", flush=True)
            continue

        for klass in sorted({k for k, _, _, _ in rows}):
            print(f"\n=== {frame}, {klass}")
            print(
                f"{'clamp':>8}{'rule':>10}{'R':>8}{'n':>9}{'var z':>9}{'CRPS':>9}"
                f"{'breach .90':>12}{'breach .95':>12}{'breach .99':>12}"
            )
            for most in CLAMPS:
                for rule in RULES:
                    for noise in NOISES:
                        got = rows.get((klass, rule, noise, most))
                        if not got:
                            continue
                        take = lambda key: float(np.median([g[key] for g in got]))  # noqa: E731
                        shipped = (rule, noise, most) == ("shrinking", 0.670, MOST)
                        print(
                            f"{most:>8.0e}{rule:>10}{noise:>8.3f}"
                            f"{int(sum(g['n'] for g in got)):>9,}"
                            f"{take('zvar'):>9.3f}{take('crps'):>9.4f}"
                            f"{take('breach_90'):>12.4f}{take('breach_95'):>12.4f}"
                            f"{take('breach_99'):>12.4f}{' <-' if shipped else ''}",
                            flush=True,
                        )
            got = reference.get(klass)
            if got:
                take = lambda key: float(np.median([g[key] for g in got]))  # noqa: E731
                print(
                    f"{'un-adapted':>10}{0.670:>8.3f}{int(sum(g['n'] for g in got)):>9,}"
                    f"{take('zvar'):>9.3f}{take('crps'):>9.4f}"
                    f"{take('breach_90'):>12.4f}{take('breach_95'):>12.4f}"
                    f"{take('breach_99'):>12.4f}",
                    flush=True,
                )

            # The premise, measured: each member's own E[z^2] against the pool's.
            for most in CLAMPS:
                released = rows.get((klass, "shrinking", 0.265, most)) or []
                names = sorted({k[7:] for g in released for k in g if k.startswith("member.")})
                if not names:
                    continue
                parts = [
                    f"{name} "
                    f"{float(np.median([g[f'member.{name}'] for g in released if f'member.{name}' in g])):.2f}"
                    for name in names
                ]
                pool = float(np.median([g["zvar"] for g in released]))
                print(
                    f"  clamp {most:.0e}, R=0.265: E[z^2] per member "
                    f"{', '.join(parts)}  |  pool {pool:.2f}"
                )
            shipped = rows.get((klass, "shrinking", 0.265, MOST)) or []
            names = sorted({k[7:] for g in shipped for k in g if k.startswith("member.")})
            if names:
                parts = [
                    f"{name} {float(np.median([g[f'member.{name}'] for g in shipped if f'member.{name}' in g])):.2f}"
                    for name in names
                ]
                pool = float(np.median([g["zvar"] for g in shipped]))
                print(f"  at R=0.265, E[z^2] per member: {', '.join(parts)}  |  pool {pool:.2f}")
    print(
        "\n\nThe premise is the last line of each block. If every member sits near one\n"
        "and the pool sits at three, the spread is not a `Q` problem and no sweep of\n"
        "`Q` can reach it - the missing term is the members' disagreement, which\n"
        "`shrinking` drops by construction and `mixture` is the law of total\n"
        "variance for. Then the only question left is what `mixture` costs on CRPS\n"
        "once `R` is the measured 0.265 rather than the 0.67 it was rejected at.",
        flush=True,
    )


if __name__ == "__main__":
    main()
