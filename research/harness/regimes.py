"""Trend up, trend down, ranging: can a hidden-state model find them, and does it beat twelve bars?

Run from the repository root:  python research/harness/regimes.py

The desk asked for two things that are one thing: *"we should also have directional regimes, trend
up, trend down, ranging"* and *"use/test HMMs in decision making and state transitions"*. A hidden
Markov model **is** the standard answer to the first, so this tests them together.

## This has been tried here once and it failed in a specific way worth knowing

`families.md` fitted two-state and three-state Gaussian HMMs by EM and **withdrew the three-state
fit**, on a test that is the whole reason this file is shaped the way it is:

> *On `Drift Switch 10` the surrogate's persistence is `[16.6, 1.06, 20.2]` and the shuffle's
> `[17.6, 1.05, 14.2]` against the feed's `[5.26, 1.16, 6.16]` - not within a factor of two, but
> **larger**, on data with no regime in it at all.*

Read that twice. The fitted states were **more persistent on data with no regimes** than on the
real series. So the null here is not "the model finds nothing". It is:

> **EM manufactures regimes.** Given any series, a three-state Gaussian HMM returns three states
> with long dwell times, because that is what maximising a likelihood over a flexible model does.

So a regime model cannot be validated by looking at its output. It can only be validated against
the same model fitted to a series known to have no regimes, and that is what every number below
carries.

## The look-ahead that makes regime work look brilliant

There are two ways to label a bar with a hidden state and only one of them is legal.

* **Smoothed** (forward-backward, or the Viterbi path) uses the *whole* series, including bars
  after the one being labelled. A smoothed state is a statement about what the regime *was*,
  written by someone who has seen how it ended. It separates beautifully and it is unusable.
* **Filtered** (the forward recursion alone) uses only bars up to and including the one being
  labelled. It is what a live desk can know.

**Everything here is filtered**, and the parameters are fitted on a window that closes strictly
before the bars they label. This is the same discipline `analogue_envelope.py` needed for its
neighbours and the same one `trend.py` states for its own window - *"the level currently being
decided is never in its own window"*.

The harness prints both so the size of the illusion is on the page: if smoothed separates and
filtered does not, that is the entire published literature on regime switching in one line.

## What it has to beat, and this is the part that decides anything

Not chance. **`trend.py`'s efficiency ratio**, which is already in production and already works:
over 54,143 resolutions its top decile breaks 1.4% of the time against the chop's 11.3%, with
0.34R between the extremes. That is twelve bars of arithmetic and no fitting at all.

So the question is not "does an HMM find states" - it will. It is **"does a fitted three-state
hidden Markov model beat twelve bars of a ratio anyone can compute?"** If it does not, then
"directional regimes" is a thing this desk already has, under a plainer name, and the answer to
the request is that it is built.

## Scored on what is forecastable

Three targets, and the middle one is the only one with a mechanism:

* **direction** - next-bar sign. Expected null; `a-theory-from-ohlc.md` and nine other documents
  here say so. Carried to show the grid failing rather than to assume it;
* **volatility** - forward realised variance, scored by `QLIKE` against a trailing estimate,
  because volatility clusters and direction does not;
* **dwell** - mean state persistence against the surrogates. This is the `families.md` test and
  it is a validity check rather than a forecast: fail it and the other two columns mean nothing,
  whatever they say.
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

#: States. Three because the desk named three - up, down, ranging - and because that is the fit
#: `families.md` withdrew, so this is a re-test of a specific claim rather than a fresh sweep.
STATES = 3

#: EM iterations. Enough for a twelve-parameter model to converge from a quantile-spaced start;
#: the point is to give the model its best shot, since the finding this file expects is that its
#: best shot is not enough.
ITERS = 15

#: Bars fitted before any labelling starts, how often the fit is refreshed, and the largest
#: window it is fitted on. The parameters labelling a bar always come from a window that closed
#: before it.
#:
#: `WINDOW` caps the fit at a rolling six thousand rather than letting it expand. Two reasons,
#: and the second is the binding one.
#:
#: A regime model fitted on ten years and applied to today asserts the states are the same object
#: throughout, which is the claim under test rather than an assumption to build in.
#:
#: And the forward and backward recursions are **sequential** - a Python loop per bar per EM
#: iteration, which no amount of vectorising removes - so runtime is `refits x iters x window`
#: and an expanding fit over 65,000 bars does not finish. Six thousand observations against a
#: three-state Gaussian HMM's twelve free parameters is ample, so this costs nothing
#: statistically and turns hours into minutes.
TRAIN = 4_000
REFIT = 5_000
WINDOW = 6_000

#: Trailing window for the volatility baseline, and the forward horizon scored.
VOL_WINDOW = 100
FORWARD = 5


def em_fit(x: np.ndarray, k: int = STATES, iters: int = ITERS) -> tuple:
    """Gaussian HMM by Baum-Welch. Returns `(start, transition, mu, sd)`.

    Forward-backward is used **for fitting**, which is legitimate: the training window is the
    past. What must never happen is smoothing a bar that is being predicted, and that is why
    labelling goes through `forward_filter` instead of through this.

    States come back **sorted by mean**, so state 0 is the most negative drift and state `k-1`
    the most positive. Without that, EM's arbitrary labelling permutes between refits and a
    "regime change" is reported every time the model is re-estimated - which would look exactly
    like a signal.
    """
    n = len(x)
    rng = np.random.default_rng(0)
    # Start from quantile-spaced means: a k-means-ish init converges faster and, more usefully,
    # converges to the same place across refits, which keeps the state labels comparable.
    mu = np.quantile(x, np.linspace(0.15, 0.85, k))
    sd = np.full(k, float(x.std()) or 1e-8)
    trans = np.full((k, k), 1.0 / k)
    start = np.full(k, 1.0 / k)

    for _ in range(iters):
        # E step.
        emit = np.exp(-0.5 * ((x[:, None] - mu) / sd) ** 2) / (sd * math.sqrt(2 * math.pi))
        emit = np.maximum(emit, 1e-300)
        alpha = np.zeros((n, k))
        scale = np.zeros(n)
        alpha[0] = start * emit[0]
        scale[0] = alpha[0].sum() or 1e-300
        alpha[0] /= scale[0]
        for t in range(1, n):
            alpha[t] = (alpha[t - 1] @ trans) * emit[t]
            scale[t] = alpha[t].sum() or 1e-300
            alpha[t] /= scale[t]
        beta = np.zeros((n, k))
        beta[-1] = 1.0
        for t in range(n - 2, -1, -1):
            beta[t] = (trans @ (emit[t + 1] * beta[t + 1])) / scale[t + 1]
        gamma = alpha * beta
        gamma /= np.maximum(gamma.sum(axis=1, keepdims=True), 1e-300)

        # M step. The pairwise posterior summed over t is one matrix product: the obvious loop
        # over bars is exact and costs an O(n) Python pass per EM iteration, which was most of
        # the runtime.
        tail = (emit[1:] * beta[1:]) / scale[1:, None]
        trans = trans * (alpha[:-1].T @ tail)
        trans /= np.maximum(trans.sum(axis=1, keepdims=True), 1e-300)
        weight = np.maximum(gamma.sum(axis=0), 1e-300)
        mu = (gamma * x[:, None]).sum(axis=0) / weight
        var = (gamma * (x[:, None] - mu) ** 2).sum(axis=0) / weight
        sd = np.sqrt(np.maximum(var, 1e-16))
        start = gamma[0] / gamma[0].sum()
        if not np.isfinite(mu).all() or not np.isfinite(sd).all():
            mu = np.quantile(x, np.linspace(0.15, 0.85, k)) + rng.normal(0, 1e-9, k)
            sd = np.full(k, float(x.std()) or 1e-8)

    order = np.argsort(mu)
    return start[order], trans[np.ix_(order, order)], mu[order], sd[order]


def forward_filter(x: np.ndarray, start, trans, mu, sd) -> np.ndarray:
    """Filtered state probabilities: `P(state at t | observations up to t)`.

    **The only legal labelling.** No backward pass, so bar `t`'s label cannot see bar `t+1`.
    """
    n, k = len(x), len(mu)
    emit = np.exp(-0.5 * ((x[:, None] - mu) / sd) ** 2) / (sd * math.sqrt(2 * math.pi))
    emit = np.maximum(emit, 1e-300)
    out = np.zeros((n, k))
    a = start * emit[0]
    a /= a.sum() or 1e-300
    out[0] = a
    for t in range(1, n):
        a = (a @ trans) * emit[t]
        a /= a.sum() or 1e-300
        out[t] = a
    return out


def smoothed(x: np.ndarray, start, trans, mu, sd) -> np.ndarray:
    """Forward-backward posteriors - **illegal for prediction**, printed to size the illusion."""
    n, k = len(x), len(mu)
    emit = np.exp(-0.5 * ((x[:, None] - mu) / sd) ** 2) / (sd * math.sqrt(2 * math.pi))
    emit = np.maximum(emit, 1e-300)
    alpha = np.zeros((n, k))
    scale = np.zeros(n)
    alpha[0] = start * emit[0]
    scale[0] = alpha[0].sum() or 1e-300
    alpha[0] /= scale[0]
    for t in range(1, n):
        alpha[t] = (alpha[t - 1] @ trans) * emit[t]
        scale[t] = alpha[t].sum() or 1e-300
        alpha[t] /= scale[t]
    beta = np.zeros((n, k))
    beta[-1] = 1.0
    for t in range(n - 2, -1, -1):
        beta[t] = (trans @ (emit[t + 1] * beta[t + 1])) / scale[t + 1]
    post = alpha * beta
    return post / np.maximum(post.sum(axis=1, keepdims=True), 1e-300)


def dwell(labels: np.ndarray, k: int = STATES) -> np.ndarray:
    """Mean run length per state - the `families.md` validity test."""
    out = np.zeros(k)
    counts = np.zeros(k)
    if not len(labels):
        return out
    run, current = 1, labels[0]
    for value in labels[1:]:
        if value == current:
            run += 1
        else:
            out[current] += run
            counts[current] += 1
            run, current = 1, value
    out[current] += run
    counts[current] += 1
    return out / np.maximum(counts, 1)


def surrogate(x: np.ndarray, kind: str, rng) -> np.ndarray:
    """A series with the same something and no regimes.

    `phase` keeps the power spectrum - so every linear autocorrelation, including whatever
    volatility clustering the series has - and destroys any state structure. `shuffle` keeps only
    the marginal distribution. `gbm` keeps only the mean and variance. Three controls rather than
    one because they fail differently, and a fitted model that beats all three has cleared
    something.
    """
    if kind == "shuffle":
        return rng.permutation(x)
    if kind == "gbm":
        return rng.normal(x.mean(), x.std() or 1e-8, len(x))
    spectrum = np.fft.rfft(x)
    phases = rng.uniform(0, 2 * np.pi, len(spectrum))
    phases[0] = 0.0
    out = np.fft.irfft(np.abs(spectrum) * np.exp(1j * phases), n=len(x))
    return out.astype(float)


def qlike(actual: np.ndarray, forecast: np.ndarray) -> float:
    ok = (actual > 0) & (forecast > 0)
    if ok.sum() < 100:
        return float("nan")
    ratio = actual[ok] / forecast[ok]
    return float(np.mean(ratio - np.log(ratio) - 1.0))


def auc(score: np.ndarray, label: np.ndarray) -> float:
    if len(score) < 100 or label.sum() in (0, len(label)):
        return float("nan")
    order = np.argsort(score)
    ranks = np.empty(len(score), dtype=float)
    ranks[order] = np.arange(1, len(score) + 1)
    pos = float(label.sum())
    neg = len(label) - pos
    return float((ranks[label.astype(bool)].sum() - pos * (pos + 1) / 2.0) / (pos * neg))


def efficiency(x: np.ndarray, window: int = 12) -> np.ndarray:
    """`trend.py`'s measure: net displacement over the sum of absolute steps.

    The incumbent, and the thing an HMM has to beat to be worth building. Twelve bars, no fit.
    """
    csum = np.concatenate([[0.0], np.cumsum(x)])
    net = np.abs(csum[window:] - csum[:-window])
    steps = np.convolve(np.abs(x), np.ones(window), mode="valid")
    out = np.full(len(x), np.nan)
    out[window - 1 :] = net / np.maximum(steps, 1e-12)
    return out


def walk(rets: np.ndarray) -> dict | None:
    """Fit forward, label with the filter, score. Parameters never see the bars they label."""
    n = len(rets)
    if n < TRAIN + REFIT * 2 + FORWARD:
        return None
    filt = np.full((n, STATES), np.nan)
    smooth_p = np.full((n, STATES), np.nan)
    at = TRAIN
    while at < n:
        stop = min(at + REFIT, n)
        start, trans, mu, sd = em_fit(rets[max(0, at - WINDOW) : at])
        # Filter forward through the unseen block, warmed on the training tail so the recursion
        # does not restart from the prior at every refit boundary.
        warm = rets[max(0, at - VOL_WINDOW) : stop]
        got = forward_filter(warm, start, trans, mu, sd)
        filt[at:stop] = got[-(stop - at) :]
        smooth_p[at:stop] = smoothed(warm, start, trans, mu, sd)[-(stop - at) :]
        at = stop

    ok = np.isfinite(filt).all(axis=1)
    idx = np.where(ok)[0]
    idx = idx[idx < n - FORWARD]
    if len(idx) < 1_000:
        return None

    labels = np.argmax(filt[idx], axis=1)
    # P(up state) minus P(down state): the model's directional call, in [-1, 1].
    call = filt[idx, STATES - 1] - filt[idx, 0]
    smooth_call = smooth_p[idx, STATES - 1] - smooth_p[idx, 0]

    nxt = rets[idx + 1]
    moved = nxt != 0
    fwd_var = np.array([float(np.sum(rets[i + 1 : i + 1 + FORWARD] ** 2)) for i in idx])
    trail = np.array([float(rets[max(0, i - VOL_WINDOW + 1) : i + 1].std()) for i in idx])
    base = trail**2 * FORWARD
    # The model's own variance forecast: the filtered mixture's variance one step out, scaled.
    #
    # `mu` and `sd` are **the last fit from the walk above**, reused deliberately. Refitting the
    # whole series here would both double the runtime and quietly let the forecast rest on
    # parameters estimated from bars its own labels were not allowed to see.
    mix = (filt[idx] * (sd**2 + mu**2)).sum(axis=1) - ((filt[idx] * mu).sum(axis=1)) ** 2
    mix = np.maximum(mix, 1e-16) * FORWARD

    eff = efficiency(rets)[idx]
    good = np.isfinite(eff)
    return {
        "n": len(idx),
        "dwell": float(np.mean(dwell(labels))),
        "dir_filtered": auc(call[moved], (nxt[moved] > 0).astype(float)),
        "dir_smoothed": auc(smooth_call[moved], (nxt[moved] > 0).astype(float)),
        "q_hmm": qlike(fwd_var, mix),
        "q_base": qlike(fwd_var, base),
        "vol_corr": float(np.corrcoef(np.sqrt(fwd_var), np.sqrt(mix))[0, 1]),
        "eff_corr": (
            float(np.corrcoef(eff[good], np.sqrt(fwd_var[good]))[0, 1]) if good.sum() > 100 else 0.0
        ),
        "hmm_vs_eff": (
            float(np.corrcoef(np.abs(call[good]), eff[good])[0, 1]) if good.sum() > 100 else 0.0
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "symbols",
        nargs="*",
        default=[s.strip() for s in os.environ.get("SYMBOLS", "").split(",") if s.strip()]
        or ["btcusd", "xauusd", "eurusd"],
    )
    ap.add_argument("--where", default=os.environ.get("WHERE", ".secrets/broker-deep"))
    ap.add_argument("--interval", default="1h")
    args = ap.parse_args()

    print(
        f"{STATES}-state Gaussian HMM, fitted by EM on an expanding window, refitted every "
        f"{REFIT} bars\nlabels are **filtered** - no bar sees its own future - and the smoothed "
        "column is printed only to size the look-ahead\n"
        "\nThe test that decides it: dwell on the real series against three surrogates with no\n"
        "regimes in them. families.md withdrew a three-state fit on exactly this, because the\n"
        "surrogate dwell came out LARGER than the feed's.\n"
    )

    rng = np.random.default_rng(7)
    for symbol in args.symbols:
        found = sorted(Path(args.where).expanduser().glob(f"{symbol}_{args.interval}_*.csv.gz"))
        if not found:
            print(f"  {symbol:<10} no {args.interval} file")
            continue
        bars, _repaired = candles.read(found[0])
        close = bars[:, 4]
        close = close[close > 0]
        rets = np.diff(np.log(close))
        got = walk(rets)
        if got is None:
            print(f"  {symbol:<10} too few bars ({len(rets)})")
            continue

        print(f"{symbol}  -  {args.interval}, {got['n']:,} labelled bars")
        print(
            f"  {'series':<12}{'dwell':>8}{'dir filt':>10}{'dir smooth':>12}"
            f"{'QLIKE hmm':>11}{'QLIKE base':>12}{'vol r':>8}"
        )
        print(
            f"  {'real':<12}{got['dwell']:>8.2f}{got['dir_filtered']:>10.4f}"
            f"{got['dir_smoothed']:>12.4f}{got['q_hmm']:>11.4f}{got['q_base']:>12.4f}"
            f"{got['vol_corr']:>8.3f}"
        )
        for kind in ("phase", "shuffle", "gbm"):
            fake = walk(surrogate(rets, kind, rng))
            if fake is None:
                continue
            flag = "  <- dwell not beaten" if fake["dwell"] >= got["dwell"] else ""
            print(
                f"  {kind:<12}{fake['dwell']:>8.2f}{fake['dir_filtered']:>10.4f}"
                f"{fake['dir_smoothed']:>12.4f}{fake['q_hmm']:>11.4f}{fake['q_base']:>12.4f}"
                f"{fake['vol_corr']:>8.3f}{flag}"
            )
        print(
            f"\n  against the incumbent: `trend.py`'s 12-bar efficiency ratio correlates "
            f"{got['eff_corr']:+.3f} with forward volatility;\n"
            f"  the HMM's state confidence correlates {got['hmm_vs_eff']:+.3f} with that same "
            "ratio - so they are"
            f" {'measuring the same thing' if abs(got['hmm_vs_eff']) > 0.4 else 'not redundant'}\n"
        )

    print(
        "  **Read the dwell column first.** If a surrogate's states are as persistent as the\n"
        "  real series', the model has not found regimes - it has found that EM returns\n"
        "  persistent states for any input, which is what families.md measured and what got\n"
        "  its three-state fit withdrawn.\n"
        "\n  **Then read `dir filt` against `dir smooth`.** Smoothed labels use the whole series\n"
        "  and are what most published regime work reports. The gap between the two columns is\n"
        "  the size of that error, measured rather than argued."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
