"""Does the mean exist, and if it does, how many trades decide it.

Every expectancy this desk has reported is a **sample mean**: `edge/cost` per
trade, nats per span, median gains per instrument. A sample mean is a summary of
a distribution only when the distribution has one. Taleb's technical claim is
that for a sufficiently heavy tail it does not, and that is estimable rather
than rhetorical.

## The tail index decides which moments exist

For a payoff whose tail falls like `x^-alpha`:

* `alpha > 2` - finite variance, and a sample mean converges at the usual rate;
* `1 < alpha < 2` - **infinite variance**, so the mean exists but a standard
  error does not mean what it says and convergence is far slower than `1/sqrt(n)`;
* `alpha < 1` - **the mean does not exist**, and a sample mean is a statement
  about which extremes happened to land in the window rather than about the
  process.

Hill's estimator reads it off the top `k` order statistics,
`alpha = k / sum(log(x_i / x_k))`. It is notoriously sensitive to `k`, so `k` is
swept and the sweep is printed rather than a single number: an `alpha` quoted
without its `k` is an opinion.

## And concentration says how much of the answer is one trade

Separately from whether the mean exists, there is how many observations decide
it. Reported three ways, because each answers a different objection:

* **top share** - the fraction of total gain contributed by the largest 1%;
* **trades for half** - how many trades it takes to reach half the total gain,
  which is the number a reader of "expectancy 0.05" implicitly assumes is large;
* **trim sensitivity** - the mean with the top 1% removed, and whether it
  **changes sign**. A mean that flips when 1% of observations are dropped is not
  a property of the strategy.

## What it is pointed at

The objects this session actually computed expectancies on:

* **raw returns**, the base object everything else is built from;
* **barrier-trade payoffs net of cost**, which is what every `edge/cost` figure
  summarised.

And the **Deriv synthetics are the control**, not a simulation: they are
verified constant-volatility GBM with return kurtosis **3.19** against the
traded universe's **20.07**, so if these measures work the generated side should
read Mediocristan and the traded side should not.

Runs on the lab.
"""

from __future__ import annotations

import math
import os
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import relationship_screen as screen  # noqa: E402

#: Shares of the top order statistics Hill's estimator is read at.
KS = (0.01, 0.025, 0.05, 0.10)
#: Barrier geometry for the trade arm, in volatility units.
TARGET = float(os.environ.get("TARGET", "2.0"))
STOP = float(os.environ.get("STOP", "2.0"))
#: Trailing bars for the volatility unit, and bars between entries.
SPAN = int(os.environ.get("SPAN", "100"))
STRIDE = int(os.environ.get("STRIDE", "24"))
PATIENCE = int(os.environ.get("PATIENCE", "500"))


def hill(values, share: float) -> float:
    """Tail index from the top `share` of the absolute values."""
    import numpy as np

    sizes = np.sort(np.abs(np.asarray(values, dtype=float)))
    sizes = sizes[sizes > 0]
    k = int(len(sizes) * share)
    if k < 10:
        return float("nan")
    top = sizes[-k:]
    cut = sizes[-k]
    if cut <= 0:
        return float("nan")
    total = float(np.sum(np.log(top / cut)))
    return k / total if total > 0 else float("inf")


def concentration(values) -> dict[str, float]:
    """How few observations decide the mean, and whether dropping them flips it."""
    import numpy as np

    raw = np.asarray([v for v in values if math.isfinite(v)], dtype=float)
    if len(raw) < 200:
        return {}
    mean = float(raw.mean())
    order = np.sort(np.abs(raw))[::-1]
    total_abs = float(order.sum())
    cut = max(int(len(raw) * 0.01), 1)
    top_share = float(order[:cut].sum()) / total_abs if total_abs > 0 else float("nan")

    # Trades needed to reach half the total *gain*, counting only winners, which
    # is the quantity a reader of an expectancy implicitly assumes is large.
    wins = np.sort(raw[raw > 0])[::-1]
    half, taken = wins.sum() / 2.0, 0
    running = 0.0
    for value in wins:
        running += value
        taken += 1
        if running >= half:
            break
    # The mean with the largest 1% by absolute size removed.
    keep = np.argsort(np.abs(raw))[: len(raw) - cut]
    trimmed = float(raw[keep].mean())
    return {
        "mean": mean,
        "top1_share": top_share,
        "for_half": float(taken) / len(wins) if len(wins) else float("nan"),
        "trimmed": trimmed,
        # **The ratio, not the sign flip.** A planted alpha of 0.8 has a mean of
        # -66.2 against a trimmed -0.078 - a factor of 850 - and still reads
        # `flips = no`, because the sign survived by luck. The magnitude is what
        # says the mean is a statement about the window.
        "ratio": abs(mean / trimmed) if trimmed else float("inf"),
        "flips": 1.0 if mean * trimmed < 0 else 0.0,
        "kurtosis": float(((raw - mean) ** 4).mean() / (raw.var() ** 2))
        if raw.var() > 0
        else float("nan"),
        "n": float(len(raw)),
    }


def barrier_payoffs(times, values, spreads):
    """Symmetric barrier trades on a demeaned series, net of their own cost."""
    import numpy as np

    moves = np.diff(values)
    drift = float(moves.mean())
    values = np.concatenate([[values[0]], values[0] + np.cumsum(moves - drift)])
    moves = np.diff(values)
    out = []
    for at in range(SPAN, len(values) - PATIENCE, STRIDE):
        sigma = float(np.std(moves[at - SPAN : at]))
        if sigma <= 0:
            continue
        up, down = values[at] + TARGET * sigma, values[at] - STOP * sigma
        for ahead in range(1, PATIENCE + 1):
            here = values[at + ahead]
            if here >= up or here <= down:
                cost = 2.0 * float(np.mean(spreads[at - SPAN : at])) / sigma
                out.append((here - values[at]) / sigma - cost)
                break
    return out


def report(label: str, values) -> None:
    got = concentration(values)
    if not got:
        print(f"{label:<30}  too few")
        return
    hills = [hill(values, k) for k in KS]
    print(
        f"{label:<30}{got['mean']:>+10.4f}{got['trimmed']:>+10.4f}"
        + f"{got['ratio']:>9.1f}"
        + f"{'yes' if got['flips'] else 'no':>7}{got['top1_share']:>9.3f}"
        f"{got['for_half']:>9.3f}{got['kurtosis']:>9.1f}"
        + "".join(f"{h:>7.2f}" if math.isfinite(h) else f"{'-':>7}" for h in hills)
        + f"{got['n']:>8.0f}"
    )


def header() -> None:
    print(
        f"{'':<30}{'mean':>10}{'trimmed':>10}{'ratio':>9}{'flips':>7}{'top 1%':>9}"
        f"{'half':>9}{'kurt':>9}"
        + "".join(f"{f'a@{k:g}':>7}" for k in KS)
        + f"{'n':>8}"
    )


def planted() -> None:
    """Known tail indices, so the estimator is checked before it is believed."""
    import numpy as np
    from scipy import stats

    print("=" * 128)
    print("ARM 0  planted: Hill has to recover a known alpha before it reads an unknown one")
    print("=" * 128)
    header()
    rng = np.random.default_rng(11)
    n = 20_000
    report("gaussian, alpha infinite", rng.standard_normal(n))
    for nu in (3.0, 1.5, 0.8):
        # A Student-t's tail index **is** its degrees of freedom.
        draws = stats.t.rvs(nu, size=n, random_state=int(nu * 100))
        report(f"student t, alpha = {nu:g}", draws)
    print(
        "\n`a@k` is Hill's estimator at that share of the top order statistics,\n"
        "and the row is the sweep because the estimator is sensitive to `k` - an\n"
        "alpha quoted without its `k` is an opinion. The t rows must read near\n"
        "their own degrees of freedom or nothing below can be trusted.\n\n"
        "**alpha below 2 means infinite variance and below 1 means the mean does\n"
        "not exist**, so the `alpha = 0.8` row is the case where a sample mean is\n"
        "a statement about the window rather than the process."
    )


def main() -> None:
    print(
        f"barrier geometry ({TARGET}, {STOP}) in volatility units, entries every\n"
        f"{STRIDE} bars, Hill swept at {KS}\n"
    )
    planted()

    traded = [n for n in screen.TRADED if screen.load(n) is not None][:8]
    generated = [
        n for n in screen.universe(screen.FRAME, cap=40) if screen.load(n) is not None
    ][:6]

    import numpy as np

    print("\n" + "=" * 128)
    print("ARM 1  raw returns, the object everything else is built from")
    print("=" * 128)
    header()
    for name in traded:
        got = screen.load(name)
        report(name, np.diff(got[1]))
    for name in generated:
        got = screen.load(name)
        report(f"*{name}", np.diff(got[1]))

    print("\n" + "=" * 128)
    print("ARM 2  barrier payoffs net of cost, which is what every expectancy summarised")
    print("=" * 128)
    header()
    pooled: dict[str, list[float]] = {"traded": [], "generated": []}
    for kind, names in (("traded", traded), ("generated", generated)):
        for name in names:
            got = screen.load(name)
            if got is None:
                continue
            payoffs = barrier_payoffs(got[0], got[1], got[2])
            if len(payoffs) >= 200:
                report(("" if kind == "traded" else "*") + name, payoffs)
            pooled[kind].extend(payoffs)
    print()
    for kind, values in pooled.items():
        report(f"pooled {kind}", values)
    print(
        "\n**`ratio` is the one to read first**, not `flips`. It is the mean over\n"
        "the mean with the largest 1% removed, and a planted alpha of 0.8 reads\n"
        "850 there while still showing `flips = no` because its sign survived by\n"
        "luck. A ratio far from 1 says the expectancy is a statement about which\n"
        "extremes landed in the sample.\n\n"
        "`half` is the share of winning trades needed to reach half the total\n"
        "gain. A reader of 'expectancy 0.05' assumes that number is large."
    )


if __name__ == "__main__":
    main()
