"""Do the critical points of a fitted polynomial mark reversals?

**The claim.** Price follows a geometrical structure made of functions and their
derivatives; the points where the derivative vanishes are "nodes", and price
reverses at them. Fit a polynomial of degree `n` over a window, solve
`T'(t) = 0`, and you have located a turn before it happens.

**Why this is worth an hour rather than an argument.** A polynomial of degree `n`
has at most `n - 1` critical points, and where they fall is decided by the fit -
the window length and the degree - not by the process. Fit a cubic to *anything*,
including pure noise, and it will hand you a maximum and a minimum. So the claim
predicts something that a fitted curve produces unconditionally, which is the
signature of a method that reads its own parameters back.

That is a prior, not a result, and the prior has been wrong on this project
before: `frac_zero` and `n_distinct` both looked like nothing and both paid. So
it is measured, with the controls that make the measurement mean something.

## The design

At each bar, fit degree `n` over the trailing `window` by least squares, then
read the **second derivative at the right edge**. Negative is a local maximum -
the curve is arching over - so the node says *down*; positive says *up*. That is
the claim operationalised in the only causal way available: everything the fit
sees ends at the bar being scored.

Scored by AUC against the next bar's direction, which makes it directly
comparable with `research/sequencing.md`'s 0.50150 over 7.7M rows and
`research/families.md`'s 0.6627 on Range Break.

**Three controls, and the sweep is itself one.**

* **`surrogate`** - phase-randomised through `seqlab.surrogate_bars`: identical
  spectrum, no nonlinear structure. A fitted polynomial sees a spectrum.
* **`gbm`** - simulated at the feed's own measured sigma.
* **`shuffle`** - the target permuted, which catches the fit reading the answer.

Degree and window are two free parameters and sweeping both is a lot of chances
at 0.53, so the headline is `seqlab.max_of_k` over the whole grid rather than the
best cell.

    ./.secrets/lab.sh run research/harness/nodes.py
"""

from __future__ import annotations

import sys

import numpy as np

from research.harness import seqlab

#: Polynomial degrees. Two is a parabola and has exactly one critical point;
#: beyond about six the fit starts chasing the window's endpoints, which is the
#: artefact this study is looking for and worth including rather than excluding.
DEGREES = (2, 3, 4, 6)

#: Trailing bars the fit sees.
WINDOWS = (20, 40, 80, 160)

#: Timeframes, on the feeds where a market fact would live and on the family
#: where `generated.md` says there is nothing to find.
GRID = ("15m", "1h", "4h")

#: Fewest scored rows before a cell is reported.
FEWEST = 400


def curvature(prices: np.ndarray, degree: int, window: int) -> np.ndarray:
    """Second derivative of the fitted polynomial at each bar's right edge.

    **Everything the fit sees ends at the bar being scored**, which is what
    makes this causal. Fitting a window centred on the bar would hand the model
    the future and produce a beautiful number - the same look-ahead
    `research/foundation.md` priced at exactly zero on a different geometry, and
    which would not be zero here because the fit is over a short window where
    one future bar is a large share of it.

    Returned in units of the series' own scale, so degrees and windows are
    comparable: a raw second derivative shrinks as the window lengthens for
    reasons that have nothing to do with the curve.
    """
    n = len(prices)
    out = np.full(n, np.nan)
    if window < degree + 2 or n <= window:
        return out
    # The fit is on a fixed grid, so the design matrix and its pseudo-inverse
    # are built once rather than per bar - the whole sweep is otherwise hours.
    t = np.arange(window, dtype=float) / (window - 1.0)
    design = np.vander(t, degree + 1, increasing=True)
    pinv = np.linalg.pinv(design)
    edge = 1.0
    # Second derivative of sum(c_k t^k) at t = edge.
    powers = np.array([k * (k - 1) * edge ** (k - 2) if k >= 2 else 0.0 for k in range(degree + 1)])
    scale = np.std(prices[np.isfinite(prices)]) or 1.0
    for i in range(window, n):
        coefficients = pinv @ prices[i - window : i]
        out[i] = float(powers @ coefficients) / scale
    return out


def score(prices: np.ndarray, degree: int, window: int) -> tuple[float, int]:
    """AUC of the node's call against the next bar, and the rows it used.

    A local maximum - negative curvature - is the claim saying *down*, so the
    score that should exceed 0.5 is `-curvature` against a fall. Written as
    `auc(curvature, up)` because a positive curvature is the call for *up*, and
    the direction of the inequality is the part easiest to get backwards.
    """
    bend = curvature(prices, degree, window)
    forward = np.full(len(prices), np.nan)
    forward[:-1] = np.diff(prices)
    ok = np.isfinite(bend) & np.isfinite(forward)
    if ok.sum() < FEWEST:
        return float("nan"), int(ok.sum())
    up = (forward[ok] > 0).astype(int)
    if up.min() == up.max():
        return float("nan"), int(ok.sum())
    return seqlab.auc(bend[ok], up), int(ok.sum())


def main() -> int:
    rng = np.random.default_rng(29)
    print("Do the critical points of a fitted polynomial mark reversals?\n")
    print("AUC of the fitted curvature at the window's right edge against the next bar.")
    print("0.50 is no information. Degree and window are swept, so read the max-of-k.\n")

    groups = {"real": list(seqlab.REAL), "volatility": list(seqlab.VOLATILITY)[:10]}

    for name, symbols in groups.items():
        print("=" * 84)
        print(name.upper())
        print("=" * 84)
        print(
            f"{'degree':>7} {'window':>7} {'cells':>6} {'rows':>10}  "
            f"{'feed':>8} {'surrogate':>10} {'gbm':>8} {'shuffle':>8}"
        )
        best_real, best_control = 0.5, 0.5
        for degree in DEGREES:
            for window in WINDOWS:
                feed_s, sur_s, gbm_s, shuf_s, rows, cells = [], [], [], [], 0, 0
                for broker in symbols:
                    for interval in GRID:
                        try:
                            bars = seqlab.load(broker, interval)
                        except Exception:  # noqa: BLE001
                            continue
                        closes = np.asarray(bars["close"], dtype=float)
                        logs = np.log(np.maximum(closes, 1e-12))
                        sigma = float(np.std(np.diff(logs), ddof=1))
                        if sigma <= 0:
                            continue
                        a, n = score(logs, degree, window)
                        if not np.isfinite(a):
                            continue
                        cells += 1
                        rows += n
                        feed_s.append(a)

                        try:
                            sur = seqlab.surrogate_bars(bars, rng)
                            sl = np.log(np.maximum(np.asarray(sur["close"], float), 1e-12))
                            b, _ = score(sl, degree, window)
                            if np.isfinite(b):
                                sur_s.append(b)
                        except Exception:  # noqa: BLE001
                            pass

                        walk = logs[0] + np.cumsum(rng.normal(0.0, sigma, len(logs)))
                        c, _ = score(walk, degree, window)
                        if np.isfinite(c):
                            gbm_s.append(c)

                        shuffled = logs.copy()
                        steps = np.diff(shuffled)
                        rng.shuffle(steps)
                        d, _ = score(
                            np.concatenate(([logs[0]], logs[0] + np.cumsum(steps))), degree, window
                        )
                        if np.isfinite(d):
                            shuf_s.append(d)
                if not cells:
                    continue

                def mean(xs: list[float]) -> float:
                    return float(np.mean(xs)) if xs else float("nan")

                f, s2, g, h = mean(feed_s), mean(sur_s), mean(gbm_s), mean(shuf_s)
                best_real = max(best_real, f if np.isfinite(f) else 0.5)
                for control in (s2, g, h):
                    if np.isfinite(control):
                        best_control = max(best_control, control)
                print(
                    f"{degree:>7} {window:>7} {cells:>6} {rows:>10,}  "
                    f"{f:>8.4f} {s2:>10.4f} {g:>8.4f} {h:>8.4f}"
                )
        print(
            f"\n  best feed cell {best_real:.4f} against the best control cell "
            f"{best_control:.4f} over {len(DEGREES) * len(WINDOWS)} configurations"
        )
        print()

    print("Reading it: a fitted curve hands you a maximum and a minimum whatever it is")
    print("fitted to, so the number that matters is the feed against its own surrogate,")
    print("not the feed against 0.50.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
