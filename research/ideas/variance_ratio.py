"""Does the stop band's `sqrt(q)` scaling hold, as a variance and as a barrier?

`risk/forecast.band(f, bars=q)` is the one-bar Student-t band times `sqrt(q)`,
and the module says in so many words that **`bars` above one is unmeasured**:
on a steady 20-pip 15m bar the one-bar band is 30 pips against a rule's own
60, while the same band over `smc-bos-causal`'s 96-bar hold is 295 pips - five
times the rule's own. So switching `bars>1` on is currently a decision with no
number behind it, and this is the number.

## Two questions, and only the second one licenses anything

**The variance ratio** `VR(q) = Var(r(q)) / (q * Var(r))` says whether the
terminal q-bar variance scales as `q`. It is the clean textbook test and it is
*not* sufficient here, because a stop is a **barrier**: the position dies on
the running excursion, not on where price is at bar q. A series can have
`VR(q) = 1` exactly and still breach a `sqrt(q)` band far more often than its
nominal rate, because the maximum of a path exceeds its endpoint.

**The barrier rate** is therefore the decision: of the windows where the
forecast is ready, what share ever reach `+-band(f, q)` within q bars, against
the 0.10 the band's `TAU` names. And the useful form of the answer is the
*multiplier it would need*: the 0.90 quantile of the realised q-bar excursion
in units of the forecast, divided by the shipped `student_stop(0.90, 4) *
sqrt(q)`. One means the scaling is right. Above one means the band understates
by that factor.

## Arms

Per instrument, never pooled only - `pooled-medians-invert-subgroups` recorded
a pooled median agreeing with a claim every subgroup refuted.

* **real** - the market.
* **shuffle** - the same returns in 24-bar blocks, reordered. Keeps the
  marginal and the within-block clustering, destroys the ordering between
  blocks. If the real deviation from `sqrt(q)` survives here it is not an
  ordering effect.
* **iid** - Gaussian with the matched variance. **The control that must come
  out at one**, and whose barrier rate must match the theory: if it does not,
  the measurement is broken rather than the market interesting.
* **Volatility 25/75 Index** ride along as the independent placebo pair, per
  `carry-an-independent-placebo-pair` - two Deriv indices in every harness,
  which caught two leaks in one run.

Heteroskedasticity-robust `z*` accompanies every overlapping VR, because
**VR's null is one only under homoskedasticity** and this book is anything but:
seasonality alone runs FX at 3x between 14-15 UTC and the quiet hours.

## Re-running

    ./.secrets/lab.sh run research/ideas/variance_ratio.py            # the table
    ./.secrets/lab.sh run research/ideas/variance_ratio.py MODE=power # the sweep
"""

from __future__ import annotations

import math
import os
import random
import statistics
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from till_infinity.risk.forecast import ALPHA, WARM, RangeForecast  # noqa: E402
from till_infinity.risk.quantiles import DOF, TAU, student_stop  # noqa: E402

DATA = Path.home() / "till_infinity" / "data" / "seqlab"

#: The horizons. 2-20 is the question as posed; 48 and 96 are the holds the
#: traded rules actually carry - `smc-bos-causal` names a 96-bar clock - and
#: they are where a `sqrt(q)` band would do its damage.
HORIZONS = (2, 5, 10, 20, 48, 96)

#: Block length for the shuffled twin, in 15m bars. Six hours: long enough to
#: keep a session's clustering inside a block, short enough that a year has
#: hundreds of blocks to reorder.
BLOCK = 24

#: The two Deriv volatility indices, as the placebo pair rather than as data.
PLACEBO = ("Volatility 25 Index", "Volatility 75 Index")

SEED = 20261110

#: Draws per synthetic arm, per instrument. **Not one.** A single realisation
#: has no sampling spread, so its deviation from the nominal cannot be told
#: from its noise - and when the draw is shared across instruments, as it was
#: here, the pooled median is that one draw rather than a pool at all.
REPLICATES = 5
LEAST_BARS = 4_000
BAND = student_stop(TAU, DOF)


def forecasts(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    """`RangeForecast` over the whole series, vectorised. NaN until warm.

    Asserted against the shipped class in `check()` rather than trusted: the
    production path is what trades, and a harness that re-implements it tests
    the re-implementation.
    """
    previous = np.concatenate(([np.nan], close[:-1]))
    span = high - low
    true_range = np.where(
        np.isnan(previous),
        span,
        np.maximum(span, np.maximum(np.abs(high - previous), np.abs(low - previous))),
    )
    out = np.full(len(close), np.nan)
    value = 0.0
    bars = 0
    for i, one in enumerate(true_range):
        bars += 1
        if one > 0.0:
            value = one if value <= 0.0 else value + ALPHA * (one - value)
        if bars >= WARM and value > 0.0:
            out[i] = value
    return out


def check() -> None:
    """The vectorised forecast is the shipped one, on real-shaped input."""
    rng = random.Random(SEED)
    high, low, close = [], [], []
    price = 1.1
    for _ in range(400):
        price += rng.gauss(0.0, 0.0008)
        span = abs(rng.gauss(0.0, 0.0006)) + 1e-5
        high.append(price + span / 2)
        low.append(price - span / 2)
        close.append(price)
    mine = forecasts(np.array(high), np.array(low), np.array(close))
    theirs = RangeForecast()
    for i, (h, lo, c) in enumerate(zip(high, low, close, strict=True)):
        theirs.update(h, lo, c)
        if theirs.ready:
            assert abs(mine[i] - theirs.value) < 1e-12, (i, mine[i], theirs.value)
        else:
            assert math.isnan(mine[i]), i
    print("the vectorised forecast matches `risk.forecast.RangeForecast`")


def variance_ratio(returns: np.ndarray, q: int) -> tuple[float, float]:
    """`VR(q)` on overlapping windows, and Lo-MacKinlay's robust `z*`.

    The robust form is the one that matters: under homoskedasticity the null
    variance of `VR` is a constant, and under this book's volatility it is
    not - so a plain `z` would call heteroskedasticity structure.
    """
    n = len(returns)
    if n < 4 * q:
        return float("nan"), float("nan")
    mu = returns.mean()
    centred = returns - mu
    var1 = float((centred**2).sum() / (n - 1))
    if var1 <= 0:
        return float("nan"), float("nan")
    rolled = np.convolve(returns, np.ones(q), mode="valid")
    m = n - q + 1
    varq = float(((rolled - q * mu) ** 2).sum() / (m * q))
    vr = varq / var1
    # The heteroskedasticity-consistent variance of VR - 1.
    delta = 0.0
    squared = centred**2
    bottom = float((squared.sum()) ** 2)
    for j in range(1, q):
        top = float((squared[j:] * squared[:-j]).sum())
        # **No extra `n`.** Lo-MacKinlay's `delta(j)` is already
        # `sum(e^2 e^2) / (sum e^2)^2`, which is O(1/n), so multiplying by `n`
        # made the null variance O(1) and every `z*` read -0.00 - a test that
        # cannot reject, which is worse than no test.
        delta += ((2.0 * (q - j) / q) ** 2) * (top / bottom)
    return vr, (vr - 1.0) / math.sqrt(delta) if delta > 0 else float("nan")


def barrier(
    high: np.ndarray, low: np.ndarray, close: np.ndarray, f: np.ndarray, q: int
) -> tuple[float, float, float, float]:
    """Breach rates for a `sqrt(q)`-scaled band, and the multiplier it needs.

    Returns `(terminal, excursion, needed)`:

    * `terminal` - share of windows whose *close* at `q` is beyond the band.
      This is what `VR` speaks to, and nominal is `1 - TAU`.
    * `excursion` - share that ever reach it inside the window. **This is the
      one a stop lives on**, read off the highs and lows rather than the
      closes, because a stop is filled by a touch.
    * `needed` - the `TAU` quantile of the realised excursion in units of the
      forecast, over `BAND * sqrt(q)`. One means `sqrt(q)` is right.

    **Non-overlapping windows**, stepping `q`. Overlapping ones would reuse
    each bar in `q` windows and inflate any count built from them -
    `overlapping-outcome-windows-leak` recorded a direction AUC of 0.79
    collapsing to 0.51 on exactly that.
    """
    usable = np.where(~np.isnan(f))[0]
    usable = usable[usable + q < len(close)]
    if len(usable) == 0:
        return float("nan"), float("nan"), float("nan"), float("nan")
    starts = usable[:: max(1, q)]
    if len(starts) < 30:
        return float("nan"), float("nan"), float("nan"), float("nan")

    def excursion(at: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Touch excursion, close-only excursion, and the terminal move.

        **Both excursions, because only one of them compares across arms.**
        The synthetic arms re-hang the *real* bar ranges on a synthetic close
        path, so their highs and lows do not scale with their own steps - the
        iid control's touch multiplier fell from 0.99 to 0.86 across `q` on
        that incoherence alone, which is the arm that must be flat. Measured
        on closes every arm is coherent with its own path, so the close-only
        column is the one that licenses a scaling and the touch column is what
        a stop on the real series actually needs.
        """
        base = close[at]
        ahead_h = np.array([high[i + 1 : i + q + 1].max() for i in at])
        ahead_l = np.array([low[i + 1 : i + q + 1].min() for i in at])
        runs = np.array([np.abs(close[i + 1 : i + q + 1] - close[i]).max() for i in at])
        return np.maximum(ahead_h - base, base - ahead_l), runs, np.abs(close[at + q] - base)

    reach, _runs, ends = excursion(starts)
    want = BAND * math.sqrt(q) * f[starts]
    # **The rate is non-overlapping and the quantile is not.** A breach *rate*
    # built from overlapping windows counts each bar q times, which is the
    # inflation `overlapping-outcome-windows-leak` recorded. A *quantile* of
    # the excursion distribution is consistently estimated either way - only
    # its standard error is affected - and the non-overlapping version has too
    # few windows to read a 0.90 quantile at q=96: the iid control's own
    # multiplier fell from 0.99 to 0.91 across q on that bias alone, which is
    # the arm that must be flat.
    allow = usable[usable + q < len(close)]
    touch, runs, _ = excursion(allow)
    scale = BAND * math.sqrt(q)
    needed = float(np.quantile(touch / f[allow], TAU)) / scale
    on_close = float(np.quantile(runs / f[allow], TAU)) / scale
    return float((ends > want).mean()), float((reach > want).mean()), needed, on_close


def block_shuffle(returns: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    blocks = [returns[i : i + BLOCK] for i in range(0, len(returns), BLOCK)]
    rng.shuffle(blocks)
    return np.concatenate(blocks)


def rebuild(close0: float, returns: np.ndarray, spans: np.ndarray, places: np.ndarray):
    """A series from log returns, re-hanging the real bar shapes on it.

    The shapes travel with their own bar - `walk-geometry`'s construction and
    the reason it is not opened at the previous close: the market's own mean
    gap is negative on 10 of 12 stores and removing it is a different null.
    """
    close = close0 * np.exp(np.cumsum(returns))
    span = spans[: len(close)]
    low = close - places[: len(close)] * span
    return low + span, low, close


def table(mode: str) -> None:
    print(
        f"{'instrument':22} {'arm':8} {'q':>4} {'VR':>7} {'z*':>7} "
        f"{'term':>6} {'exc':>6} {'touch':>6} {'close':>7}"
    )
    rows: dict[tuple[str, int], list[float]] = {}
    found = sorted(DATA.glob("*.15m.npz"))
    for path in found:
        name = path.name.replace(".15m.npz", "")
        with np.load(path) as data:
            high, low, close = (data[k].astype(float) for k in ("high", "low", "close"))
        if len(close) < LEAST_BARS:
            continue
        keep = close > 0
        high, low, close = high[keep], low[keep], close[keep]
        returns = np.diff(np.log(close))
        span = high - low
        places = np.where(span > 0, (close - low) / np.where(span > 0, span, 1.0), 0.5)
        # **Seeded per instrument, and replicated.** One `default_rng(SEED)`
        # inside this loop gave every instrument the *same* normal draw, and
        # `VR` is scale-invariant - so AUDCAD and GBPJPY read an identical
        # 0.999/0.981/0.955/0.924/0.903/0.888 and "23 of 31 cells at z* < -2"
        # was one cell counted 31 times. A control with no sampling spread
        # cannot say whether a deviation is inside its own noise.
        seed = np.random.SeedSequence([SEED, abs(hash(name)) % (2**32)])
        rng = np.random.default_rng(seed)
        draws: dict[str, list] = {"real": [(high, low, close)]}
        if mode != "quick":
            draws["shuffle"] = [
                rebuild(close[0], block_shuffle(returns, rng), span, places)
                for _ in range(REPLICATES)
            ]
            draws["iid"] = [
                rebuild(close[0], rng.normal(0.0, returns.std(), len(returns)), span, places)
                for _ in range(REPLICATES)
            ]
        for arm, series in draws.items():
            got: dict[int, list[tuple[float, float, float, float, float, float]]] = {}
            for h, lo, c in series:
                f = forecasts(h, lo, c)
                r = np.diff(np.log(c))
                for q in HORIZONS:
                    vr, z = variance_ratio(r, q)
                    term, exc, need, on_close = barrier(h, lo, c, f, q)
                    got.setdefault(q, []).append((vr, z, term, exc, need, on_close))
            for q in HORIZONS:
                vr, z, term, exc, need, on_close = (
                    statistics.median(one) for one in zip(*got[q], strict=True)
                )
                print(
                    f"{name:22} {arm:8} {q:4d} {vr:7.3f} {z:7.2f} "
                    f"{term:6.3f} {exc:6.3f} {need:6.3f} {on_close:7.3f}"
                )
                if not math.isnan(need) and name not in PLACEBO:
                    rows.setdefault((arm, q), []).append((need, on_close))
    print()
    print(
        f"{'arm':8} {'q':>4} {'touch':>7} {'min':>7} {'max':>7} "
        f"{'close':>7} {'min':>7} {'max':>7} {'n':>4}"
    )
    for (arm, q), got in sorted(rows.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        touch = [a for a, _ in got]
        shut = [b for _, b in got]
        print(
            f"{arm:8} {q:4d} {statistics.median(touch):7.3f} {min(touch):7.3f} "
            f"{max(touch):7.3f} {statistics.median(shut):7.3f} {min(shut):7.3f} "
            f"{max(shut):7.3f} {len(got):4d}"
        )


if __name__ == "__main__":
    check()
    table(os.environ.get("MODE", "full"))
