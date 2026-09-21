"""First passage with jumps: deriving what a barrier trade is worth, then checking it.

Run from the repository root:  python research/harness/overshoot_theory.py

Every barrier result in this repository is scored against `b / (a + b)`, the driftless
first-passage probability. That formula assumes **continuous paths**: price cannot reach a
distant level without passing through every level between. `jump_odds.py` picked instruments
built to violate that, and `costs.md` found the violation costs real money. This derives the
exact replacement and verifies it by simulation.

The physics is one idea - **a driftless price is a martingale, so its expected value is
conserved across any stopping rule** - which is optional stopping, and is the probabilistic
form of a conservation law. Everything below is that plus bookkeeping.

## The derivation

Let `X` be the log-price, driftless, starting at zero, with barriers at `+a` (target) and `-b`
(stop). Let `tau` be the first time it leaves the corridor.

On a **continuous** path `X_tau` is exactly `+a` or `-b`. On a path with jumps it is not: the
process lands somewhere beyond, and the excess is the **overshoot**, which is the central object
of Levy first-passage theory. Define

    U = X_tau - a  >= 0     on an upward exit
    D = -X_tau - b >= 0     on a downward exit

and write `p = P(upward exit)`, `u = E[U | up]`, `d = E[D | down]`.

Optional stopping gives `E[X_tau] = X_0 = 0`, so

    p (a + u) - (1 - p) (b + d) = 0

and therefore

    **p = (b + d) / (a + u + b + d)**                                          (1)

which is the exact driftless jump generalisation, reducing to `b / (a + b)` when the overshoots
vanish. That is the formula every study here should have been scored against.

## What it says about money, which is the surprising part

A barrier trade does not collect `X_tau`. It collects what its orders fill at, and the two
sides fill differently:

* a **target** is a limit order - it fills at `a` exactly, or not at all. The favourable
  overshoot `u` is **not collected**;
* a **stop** is a market order - it fills through the book, so the adverse overshoot `d` **is**
  paid.

So realised expectancy is

    E[P&L] = p a - (1 - p) (b + d)

Substituting (1), with `S = a + u + b + d`:

    E[P&L] = [ (b + d) a - (a + u)(b + d) ] / S
           = (b + d)(a - a - u) / S
           = **- u (b + d) / S**                                              (2)

**Strictly negative, and proportional to `u` - the overshoot on the side you are trying to
win.** Not `d`. The adverse overshoot appears in the expression and cancels out of the sign.

This is worth stating plainly because it is counter-intuitive and it corrects an argument made
in `maker_exits.py`. That harness reasoned that a limit target avoids slippage and is therefore
the safer exit. The derivation says the opposite: **on a jump process the limit target is the
mistake, not the stop.** A market target instead collects `a + u`, and then

    E[P&L] = p (a + u) - (1 - p)(b + d) = 0

exactly - fair, by construction, for any barriers and any jump structure.

The measurement had already said so. `stop-free.md` records Boom always-long going from +0.002
to **-0.084** when a 1 TR limit target was added, and concluded that "capping the upside is not
a risk control, it is the removal of the edge". That was an empirical finding with a hand-waved
explanation; (2) is the explanation, and it is exact.

## What this settles: the Boom result was a benchmark error

Measured on the same bars, recording the overshoot on **both** sides at reward-to-risk one:

| instrument | side | n | measured p | u | d | fair by (1) | excess |
|---|---|---|---|---|---|---|---|
| Boom 1000 | short | 16,231 | 0.5406 | 0.291 | 0.514 | **0.5397** | **+0.09%** |
| Crash 1000 | long | 16,235 | 0.5399 | 0.292 | 0.520 | 0.5406 | -0.06% |
| Boom 500 | short | 15,719 | 0.5252 | 0.308 | 0.449 | 0.5256 | -0.04% |
| Crash 500 | long | 15,719 | 0.5277 | 0.310 | 0.456 | 0.5265 | +0.12% |

**The measured hit rate matches (1) to within 0.12 points on all four instruments.**

`jump_odds.py` scored Boom shorts at 54.1% against `b / (a + b) = 0.5000` and reported +4.1
points as the one large structural deviation in this research. Against the correct driftless
jump benchmark the excess is **+0.09 points** - fair to three decimals.

So there was never an edge. What was measured was the overshoot structure of a jump process,
and `b / (a + b)` was the wrong yardstick for exactly the instruments chosen because they
violate its assumption. The irony is on the record: `jump_odds.py`'s own docstring says "that
formula assumes continuous paths... two of this broker's instruments are built to violate that",
and then scored them against it anyway.

This supersedes the explanation in `costs.md`, which attributed the collapse to slippage being
larger than the edge. The cleaner statement is that **the edge did not exist to be eroded**. The
slippage measurement stands on its own merits - the costs are real and the 0.063 live figure is
the right one - but it was not what killed this result.

It also resolves the three facts that could not all be innocent. Boom rose 64.9% while its
shorts won 54.1%, and at six trades a day that seemed to imply +32% a year on a rising
instrument. All three are consistent once 54.1% is recognised as the fair rate rather than an
excess: a fair bet compounds to nothing, which is what the price path shows.

## The drifted extension, which the data demanded

Measured across 34 instruments, (1) explains the synthetics and **fails on everything else**:
Boom 1000 goes from 4.31% off the naive benchmark to 0.24% off the corrected one, while USDCHF
goes from 4.48% to **5.24% - worse**, and EURJPY from 1.28% to 3.22%.

The reason is the assumption. (1) came from optional stopping on a **martingale**, and FX pairs
and equity indices have real drift over seven years. The fix is Wald's identity: if `X_t - mu t`
is the martingale, then

    E[X_tau] = mu E[tau]

so writing `m = mu E[tau]` - the **drift captured over the holding period**, in barrier units -
the same bookkeeping gives

    **p = (b + d + m) / (a + u + b + d)**                                      (3)

which reduces to (1) at zero drift and to `b / (a + b)` when the overshoots also vanish. `m` is
measurable in the same loop that measures everything else: it is the mean log return over the
realised holding period, in true ranges.

## And then the result that closes the programme

Substituting (3) into the limit-target expectancy, with `S = a + u + b + d`:

    E[P&L] = [ m (a + b + d) - u (b + d) ] / S                                 (4)

so a limit-target trade pays only when

    m > u (b + d) / (a + b + d)                                               (5)

At `a = b = 1` and the measured `u ~ d ~ 0.5`, that threshold is **0.30 true ranges of drift per
trade** - an enormous requirement, and the exact cost of capping the upside.

With a **market** target, which collects `a + u`, everything cancels:

    E[P&L] = p (a + u) - (1 - p) (b + d) = **m = mu E[tau]**                   (6)

**A barrier trade with market orders on both sides earns exactly the drift over its holding
period, and nothing else.** The barrier distances, the reward-to-risk ratio, the jump structure
and both overshoots all cancel out.

That is the one-line explanation of this entire research programme. Every study here searched
over **barrier geometry** - stop and target placement, reward-to-risk ratios, which level to
place them at - and (6) says geometry cannot produce expectancy at all. Only drift over the
holding period can. `premium_discount.py` tracking `a / (a + b)` across 314,794 rows,
`patterns.md`'s measured moves, `jump_odds.py`'s ratio sweep, `stretch.py`'s 1536 cells: all of
them were varying a quantity that (6) says is irrelevant.

It also says where to look instead, and it is not a level or a pattern: **a directional forecast
with a horizon**, since `m = mu E[tau]` is the only term left.

## What this script does

Verifies (1) and (2) by simulation on a driftless jump-diffusion - Brownian motion plus a
compound Poisson jump term - where the true answer is unknown analytically but the identities
must hold regardless. If the simulated `p` does not match (1), the derivation is wrong; if it
does, every barrier study here has a corrected benchmark.
"""

from __future__ import annotations

import argparse

import numpy as np

#: Barriers, in the same units as the simulated log-price.
UP, DOWN = 1.0, 1.0

#: Jump intensity per step and the scale of the jump size, swept to cover
#: near-continuous through violently discontinuous.
INTENSITY = (0.0, 0.002, 0.01, 0.05)
JUMP_SCALE = (0.5, 1.5)

#: Per-step drift, to test (3) and (6). Zero recovers the martingale case.
DRIFTS = (0.0, 0.0002, -0.0002)

#: Diffusive step size, paths, and the cap on steps before a path is abandoned.
SIGMA = 0.02
PATHS = 40_000
MAX_STEPS = 400_000


def simulate(
    intensity: float, scale: float, skew: float, drift: float = 0.0, seed: int = 0
) -> dict:
    """One jump-diffusion, run to first passage. Returns p, u, d and expectancies.

    `skew` tilts the jump direction while keeping the process driftless: an upward jump
    probability `q` with sizes scaled so the mean jump is zero. This is what Boom is - jumps
    one way, compensated by drift the other - and it is the case where `b / (a + b)` fails.
    """
    rng = np.random.default_rng(seed)
    x = np.zeros(PATHS)
    alive = np.ones(PATHS, dtype=bool)
    exit_at = np.zeros(PATHS)
    held = np.zeros(PATHS)
    steps = 0

    # A driftless compound Poisson: upward jumps of size `up_size` with probability `skew`,
    # downward of `down_size` otherwise, chosen so the expected jump is exactly zero.
    up_size = scale * (1.0 - skew) / max(skew, 1e-9)
    down_size = scale

    while alive.any() and steps < MAX_STEPS:
        steps += 1
        n = int(alive.sum())
        step = rng.normal(drift, SIGMA, n)
        if intensity > 0:
            fires = rng.random(n) < intensity
            ups = rng.random(n) < skew
            step = step + np.where(fires, np.where(ups, up_size, -down_size), 0.0)
        x[alive] += step
        done = alive & ((x >= UP) | (x <= -DOWN))
        exit_at[done] = x[done]
        held[done] = steps
        alive = alive & ~done

    settled = exit_at != 0
    values = exit_at[settled]
    up = values >= UP
    p = float(up.mean())
    u = float((values[up] - UP).mean()) if up.any() else 0.0
    d = float((-values[~up] - DOWN).mean()) if (~up).any() else 0.0

    # `m` is the drift captured over the realised holding period, in barrier units.
    m = drift * float(held[settled].mean())
    predicted = (DOWN + d + m) / (UP + u + DOWN + d)
    # (2): limit target collects `a`, market stop pays `b + d`.
    limit_pnl = p * UP - (1 - p) * (DOWN + d)
    predicted_limit = (m * (UP + DOWN + d) - u * (DOWN + d)) / (UP + u + DOWN + d)
    # A market target collects `a + u`, which is fair by construction.
    market_pnl = p * (UP + u) - (1 - p) * (DOWN + d)
    return {
        "n": int(settled.sum()),
        "p": p,
        "u": u,
        "d": d,
        "naive": DOWN / (UP + DOWN),
        "predicted": predicted,
        "limit_pnl": limit_pnl,
        "predicted_limit": predicted_limit,
        "market_pnl": market_pnl,
        "m": m,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skew", type=float, default=0.2, help="upward jump probability")
    args = ap.parse_args()

    print(
        "driftless jump-diffusion, barriers at +1 / -1, upward jump probability "
        f"{args.skew:g}\n"
        "compensated so the mean jump is zero, which is the Boom construction\n"
        f"\n  {'drift':>8}{'lambda':>7}{'scale':>6}{'n':>8}{'m':>8}{'p':>8}"
        f"{'b/(a+b)':>8}{'(3)':>8}{'u':>6}{'d':>6}{'limit E':>9}{'(4)':>8}{'mkt E':>8}"
    )
    for drift in DRIFTS:
        for intensity in INTENSITY:
            for scale in JUMP_SCALE:
                if intensity == 0.0 and scale != JUMP_SCALE[0]:
                    continue  # no jumps, so scale is irrelevant
                got = simulate(intensity, scale, args.skew, drift)
                print(
                    f"  {drift:>+8.4f}{intensity:>7.3f}{scale:>6.2f}{got['n']:>8,}"
                    f"{got['m']:>+8.4f}{got['p']:>8.4f}"
                    f"{got['naive']:>8.4f}{got['predicted']:>8.4f}{got['u']:>6.2f}"
                    f"{got['d']:>6.2f}{got['limit_pnl']:>+9.4f}"
                    f"{got['predicted_limit']:>+8.4f}{got['market_pnl']:>+8.4f}"
                )

    print(
        "\n  `p` against `(1)` is the test of the derivation - they must agree, and where they\n"
        "  do the naive `b/(a+b)` column shows how far the formula every study here uses is\n"
        "  from the truth once jumps exist.\n"
        "\n  `limit E` against `(2)` tests the money identity, and `mkt E` must sit at zero:\n"
        "  a market target collects the favourable overshoot and the trade is exactly fair,\n"
        "  while a limit target forfeits it and is strictly negative. That is the cost of\n"
        "  capping the upside on a jump process, derived rather than observed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
