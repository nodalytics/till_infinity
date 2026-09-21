"""Does price scale diffusively? A first-principles check on this repository's own arithmetic.

Run from the repository root:  python research/harness/scaling.py

Almost every cost argument here rests on one unexamined assumption: that price scales like a
diffusion, so a move over `tau` bars grows as `sqrt(tau)`. It is what licenses

* "carry is linear in holding time while any edge is at best its square root" (`stop-free.md`);
* true range as *the* unit, since a fixed multiple of it means the same thing at every horizon;
* the whole first-passage apparatus, where `b / (a + b)` and its jump correction both assume a
  process whose second moment grows linearly in time.

**None of that was ever measured on this data.** This measures it.

## The structure function, and what the exponents mean

For a process observed over lag `tau`, the `q`-th absolute moment of the increment scales as

    <|x(t + tau) - x(t)|^q> ~ tau^(zeta_q)

`zeta_q` is the structure-function exponent. Three cases, and they are distinguishable:

* **pure diffusion** - `zeta_q = q / 2` exactly, for every `q`. A straight line through the
  origin of slope one half;
* **multifractal** - `zeta_q` is *concave* in `q`. Bouchaud gives the quadratic form
  `zeta_q = (q/2)[1 - lambda^2 (q - 2)]` with `lambda^2` about 0.05, measured on equity indices.
  Note `zeta_2 = 1` identically in that form, so variance still grows linearly and only the
  higher moments bend;
* **trending or mean-reverting** - `zeta_2` itself departs from 1, which would break the true
  range as a unit and every horizon comparison built on it.

**`zeta_2` is the load-bearing number.** If it is 1 the repository's scaling arithmetic stands.
If not, the claim that edges grow as `sqrt(time)` while carry grows linearly needs redoing, and
with it the conclusion that long horizons are hopeless.

## The second test: an over-identifying restriction

Bouchaud's volatility feedback recursion, which uses only absolute returns and so runs on bars:

    sigma_k = sigma_{k-1} + K (sigma_0 - sigma_{k-1}) + g |dx_{k-1}|

has a stationary distribution whose tail exponent satisfies `mu - 1 ~ K / g^2`. The return
distribution's own tail exponent `mu` is separately measurable by a Hill estimator.

So **the same `mu` is reachable two ways** - from the feedback parameters and from the tail
directly - and they have to agree. That is a genuine over-identifying restriction available with
bars alone, and it is rare: almost nothing in this repository can be checked against itself.

Reported values to compare against: `mu` close to **3** on pooled intraday US equities, closer to
**5** for the S&P 500 over 1991-1995, and rising toward Gaussian as the lag grows - so the lag at
which `mu` is measured has to be stated, which is why it is swept here.

## What this is not

Not a signal, and not a step toward one. Every quantity here is a function of `|increment|`, so
by the argument in `a-theory-from-ohlc.md` it carries no directional information: the signed
series is near-unpredictable past a few minutes while the absolute series has long memory. This
is a check on the *units and exponents* the rest of the work is denominated in.

A diagnostic that confirms the assumption is worth running precisely because so much rests on
it, and nobody had.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "training"))

import candles  # noqa: E402

#: Lags in bars. Log-spaced, since the fit is a slope in log-log.
LAGS = (1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144)

#: Moment orders. Kept under 6 because `<|dx|^q>` needs `mu > q` to exist at all, and `mu`
#: is around 3 to 5 - asking for the eighth moment of a series whose fourth barely converges
#: measures the largest observation and nothing else.
ORDERS = (0.5, 1.0, 1.5, 2.0, 3.0, 4.0)

#: Tail fraction for the Hill estimator, and the minimum tail count to report one.
TAIL = 0.05
MIN_TAIL = 200


def structure(close: np.ndarray, lag: int, q: float) -> float:
    """`<|x(t+lag) - x(t)|^q>` on log prices, using every available overlap."""
    logs = np.log(close[close > 0])
    if len(logs) <= lag:
        return float("nan")
    step = np.abs(logs[lag:] - logs[:-lag])
    good = step[np.isfinite(step)]
    return float(np.mean(good**q)) if len(good) else float("nan")


def zeta(close: np.ndarray, q: float) -> tuple[float, float]:
    """Slope and R^2 of `log <|dx|^q>` against `log lag` - the exponent `zeta_q`."""
    xs, ys = [], []
    for lag in LAGS:
        got = structure(close, lag, q)
        if np.isfinite(got) and got > 0:
            xs.append(math.log(lag))
            ys.append(math.log(got))
    if len(xs) < 4:
        return float("nan"), float("nan")
    x = np.array(xs)
    y = np.array(ys)
    a = np.polyfit(x, y, 1)
    fit = np.polyval(a, x)
    ss = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - float(np.sum((y - fit) ** 2)) / ss if ss > 0 else float("nan")
    return float(a[0]), r2


def hill(close: np.ndarray, lag: int) -> tuple[float, int]:
    """Hill estimate of the tail exponent `mu` of `|increment|` at this lag.

    The Hill estimator is `mu = 1 / mean(log(x_i / x_min))` over the top `TAIL` fraction.
    It is badly biased for small tails and for series with slowly varying tails - Lux's
    standing criticism of econophysics exponent estimates - so the tail count is printed
    beside it and a short tail is reported as missing rather than as a number.
    """
    logs = np.log(close[close > 0])
    if len(logs) <= lag:
        return float("nan"), 0
    step = np.abs(logs[lag:] - logs[:-lag])
    step = step[np.isfinite(step) & (step > 0)]
    if len(step) < MIN_TAIL / TAIL:
        return float("nan"), 0
    cut = np.quantile(step, 1.0 - TAIL)
    tail = step[step >= cut]
    if len(tail) < MIN_TAIL or cut <= 0:
        return float("nan"), len(tail)
    return float(1.0 / np.mean(np.log(tail / cut))), len(tail)


def feedback(close: np.ndarray) -> tuple[float, float, float]:
    """Fit `sigma_k = sigma_{k-1} + K(sigma_0 - sigma_{k-1}) + g|dx_{k-1}|`, return K, g, mu.

    `sigma` is unobservable, so `|dx|` stands in for it - which the source itself notes is a
    noisy proxy and is exactly the bar-data situation. Regressing `|dx_k|` on `|dx_{k-1}|` and
    a constant gives `1 - K + g` as the slope, so `K` and `g` are not separately identified
    from this regression alone; the intercept gives `K sigma_0`, which with the sample mean of
    `|dx|` pins `K`, and `g` follows. Stated plainly because the identification is weak and
    the resulting `mu` should be read as an order of magnitude.
    """
    logs = np.log(close[close > 0])
    step = np.abs(np.diff(logs))
    step = step[np.isfinite(step)]
    if len(step) < 1000:
        return float("nan"), float("nan"), float("nan")
    y, x = step[1:], step[:-1]
    slope, intercept = np.polyfit(x, y, 1)
    mean = float(step.mean())
    if mean <= 0 or not np.isfinite(slope):
        return float("nan"), float("nan"), float("nan")
    k = float(intercept) / mean  # intercept = K * sigma_0, with sigma_0 ~ mean|dx|
    g = float(slope) - 1.0 + k
    # **This identification does not work, and the run proved it.** `g` comes out at 1e-4 or
    # smaller because the regression slope is almost exactly `1 - K`, leaving no separately
    # identified feedback term - so `K / g^2` explodes to 1e10 and beyond, which is not a tail
    # exponent, it is a divide-by-nearly-zero. Reported as missing rather than as a number.
    #
    # The reason is structural rather than a coding slip: `sigma` is latent and `|dx|` is a
    # very noisy proxy for it, so regressing one proxy on its own lag cannot separate mean
    # reversion from feedback. Testing this restriction properly needs an actual latent-
    # volatility estimate - a filter - which is the one method worth taking from the particle-
    # methods literature and is not built here.
    mu = float("nan") if (not np.isfinite(g) or abs(g) < 0.01) else 1.0 + k / (g * g)
    return k, g, mu


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "symbols",
        nargs="*",
        default=[s.strip() for s in os.environ.get("SYMBOLS", "").split(",") if s.strip()]
        or ["xauusd", "eurusd", "boom_1000_index", "volatility_75_index"],
    )
    ap.add_argument("--where", default=os.environ.get("WHERE", ".secrets/broker-deep"))
    ap.add_argument("--interval", default="1h")
    args = ap.parse_args()

    print(
        "structure-function exponents. Pure diffusion is zeta_q = q/2 exactly;\n"
        "concave in q is multifractal; zeta_2 away from 1 breaks true range as a unit.\n"
        f"\n  {'instrument':<26}" + "".join(f"{f'z{q:g}':>8}" for q in ORDERS) + f"{'R2(z2)':>8}"
    )
    rows = []
    for symbol in args.symbols:
        found = sorted(Path(args.where).expanduser().glob(f"{symbol}_{args.interval}_*.csv.gz"))
        if not found:
            continue
        bars, _repaired = candles.read(found[0])
        if len(bars) < 5000:
            continue
        close = bars[:, 4]
        zs = {}
        r2_of_two = float("nan")
        for q in ORDERS:
            z, r2 = zeta(close, q)
            zs[q] = z
            if q == 2.0:
                r2_of_two = r2
        if not np.isfinite(zs.get(2.0, float("nan"))):
            continue
        rows.append((symbol, zs, close))
        print(f"  {symbol:<26}" + "".join(f"{zs[q]:>8.3f}" for q in ORDERS) + f"{r2_of_two:>8.4f}")

    if rows:
        print(f"  {'pure diffusion':<26}" + "".join(f"{q / 2:>8.3f}" for q in ORDERS))
        lam = 0.05
        print(
            f"  {'multifractal, lam2=0.05':<26}"
            + "".join(f"{(q / 2) * (1 - lam * (q - 2)):>8.3f}" for q in ORDERS)
        )
        z2 = np.array([r[1][2.0] for r in rows])
        print(
            f"\n  zeta_2 across {len(rows)} instruments: median {np.median(z2):.4f}, "
            f"range {z2.min():.3f} to {z2.max():.3f}"
        )
        print(
            "  **This is the load-bearing number.** At 1.0 the repository's scaling\n"
            "  arithmetic stands: variance grows linearly, moves grow as sqrt(time), and\n"
            "  carry being linear in time really does outrun any edge."
        )

    print(
        f"\n  tail exponent mu by lag, and the feedback cross-check\n"
        f"\n  {'instrument':<26}"
        + "".join(f"{f'mu@{lag}':>9}" for lag in (1, 8, 55))
        + f"{'K':>8}{'g':>8}{'mu(K,g)':>10}"
    )
    for symbol, _zs, close in rows:
        line = f"  {symbol:<26}"
        for lag in (1, 8, 55):
            mu, count = hill(close, lag)
            line += f"{mu:>9.2f}" if np.isfinite(mu) and count >= MIN_TAIL else f"{'-':>9}"
        k, g, mu_kg = feedback(close)
        line += f"{k:>8.3f}{g:>8.3f}" + (f"{mu_kg:>10.2f}" if np.isfinite(mu_kg) else f"{'-':>10}")
        print(line)

    print(
        "\n  Reported elsewhere: mu near 3 on pooled intraday US equities, near 5 for the\n"
        "  S&P 500 over 1991-95, rising toward Gaussian as the lag grows - so mu should\n"
        "  increase left to right across the lag columns, and a flat or falling row is a\n"
        "  sign the Hill estimator is being driven by a handful of observations.\n"
        "\n  mu(K,g) was meant to reach the same exponent through the volatility-feedback\n"
        "  parameters instead of the tail, as an over-identifying restriction. **It does not\n"
        "  work and is reported as missing.** The regression slope is almost exactly 1 - K,\n"
        "  so no feedback term is separately identified, g lands near zero and K/g^2\n"
        "  explodes. That is structural, not a coding slip: sigma is latent and |dx| is too\n"
        "  noisy a proxy to separate mean reversion from feedback. Testing the restriction\n"
        "  needs a real latent-volatility filter, which is the one method worth taking from\n"
        "  the particle-methods literature and is not built here."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
