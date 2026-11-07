"""Does knowing the forward volatility state make a directional rule pay?

    ./.secrets/lab.sh run research/harness/atrstate.py

The label is a three-state one: the forward excursion over the next `HORIZON`
bars, divided by the ATR at entry, is **well below** a threshold, **near** it,
or **well above**. The application is the one that was asked for - fade only
when well below is expected, break out only when well above, stand aside when
near - and each is read against the same rule unfiltered.

## The oracle comes before the model

This measures the gate with the **true** forward state, not a prediction. That
ordering is the whole point: if a rule does not pay when gated on perfect
knowledge of the forward volatility class, then how predictable that class is
does not matter, and a classifier would be work spent on a ceiling that is
already below zero. Only if the oracle pays is there a prediction problem worth
having.

`auc-is-free-on-volatility-targets` is why the model is not the first step
anyway: a volatility target reads AUC 0.805 on a *constant-volatility* process
and 0.525 within strata, with trailing-volatility incumbents alone at
0.74-0.78. A high AUC here would mean almost nothing.

## Two controls, and the second is the one that bites

`unfiltered` is the comparison that was asked for. It is necessary and not
sufficient: **on a net-negative book any rule that trades less shows a profit
improvement**, so a gate that refuses two thirds of trades will look good
against the full book whatever it selects on. `random-gate` therefore keeps the
same duty cycle and chooses at random. Every pause rule tested on this desk
beat its baseline and none beat its own random twin, at p 0.45-0.51.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

DATA = Path.home() / "till_infinity" / "data" / "btc"
SYMBOL = "BTCUSD"
HORIZON = 24
ATR_N = 14
BREAKOUT_N = 24
#: The quoted round trip, from `btccost.py` 2026-11-07.
COST_PX = 18.86
#: (well-below, well-above) cuts as **percentiles of the excursion itself**,
#: not as fixed ATR multiples.
#:
#: The first run of this used multiples of 0.5 to 3.0 and was nearly
#: uninformative: a 24-bar excursion accumulates, so its median is **5.04**
#: ATR and the 10th-to-90th range is 2.62 to 10.41. "Above 3.0" therefore
#: selected 92-100% of bars and "below 1.5" selected 0.2%, so the gate was
#: either everything or fourteen trades. Percentiles put the threshold search
#: in the space where the distribution actually lives.
QUANTILES = [(10, 90), (25, 75), (33, 67)]

#: Trailing window the ATR regime is ranked within. Long enough to span
#: several regimes, short enough that the rank is about now.
REGIME_WINDOW = 500
REGIME_BUCKETS = 5
SEED = 20261107
DRAWS = 2000


def load() -> dict[str, np.ndarray]:
    with np.load(DATA / f"{SYMBOL}.1h.npz") as data:
        return {k: data[k] for k in ("time", "open", "high", "low", "close")}


def atr(high, low, close, n):
    prev = np.concatenate(([close[0]], close[:-1]))
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev), np.abs(low - prev)))
    out = np.full(len(tr), np.nan)
    for i in range(n, len(tr)):
        out[i] = tr[i - n : i].mean()
    return out


def forward_excursion(bars, unit) -> np.ndarray:
    """(max high - min low) over the next HORIZON bars, in ATR units.

    The *excursion*, not the net move: the question is how much range the
    market covers, which is what decides whether a fade gets its reversion or
    a breakout gets its follow-through.
    """
    high, low = bars["high"], bars["low"]
    n = len(high)
    out = np.full(n, np.nan)
    for i in range(n - HORIZON - 1):
        if not np.isfinite(unit[i]) or unit[i] <= 0.0:
            continue
        window = slice(i + 1, i + HORIZON + 1)
        out[i] = (high[window].max() - low[window].min()) / unit[i]
    return out


def rules(bars, unit) -> dict[str, np.ndarray]:
    """Side per bar for each rule, 0 where it does not fire.

    Both are deliberately plain. The question is whether a volatility gate
    helps a rule, so the rule must be simple enough that the gate is the only
    thing varying.
    """
    close, high, low = bars["close"], bars["high"], bars["low"]
    n = len(close)
    fade = np.zeros(n)
    breakout = np.zeros(n)
    for i in range(BREAKOUT_N, n):
        if not np.isfinite(unit[i]) or unit[i] <= 0.0:
            continue
        step = close[i] - close[i - 1]
        if abs(step) > unit[i]:
            fade[i] = -np.sign(step)
        window = slice(i - BREAKOUT_N, i)
        if close[i] > high[window].max():
            breakout[i] = 1.0
        elif close[i] < low[window].min():
            breakout[i] = -1.0
    return {"fade": fade, "breakout": breakout}


def outcomes(bars, unit, side: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(R net of cost, firing mask) holding HORIZON bars at a one-ATR risk."""
    close = bars["close"]
    n = len(close)
    r = np.full(n, np.nan)
    for i in range(n - HORIZON - 1):
        if side[i] == 0.0 or not np.isfinite(unit[i]) or unit[i] <= 0.0:
            continue
        r[i] = side[i] * (close[i + HORIZON] - close[i]) / unit[i] - COST_PX / unit[i]
    return r, np.isfinite(r)


def report(name: str, values: np.ndarray, rng, base: float | None = None) -> float:
    if len(values) < 8:
        print(f"  {name:22s} n {len(values):5d}   too few")
        return float("nan")
    mean = float(np.mean(values))
    boots = [
        float(np.mean(values[rng.integers(0, len(values), len(values))])) for _ in range(DRAWS)
    ]
    lo, hi = float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))
    delta = f"{mean - base:+8.3f}" if base is not None else "        "
    print(
        f"  {name:22s} n {len(values):5d}  meanR {mean:+7.3f}  [{lo:+7.3f},{hi:+7.3f}] {delta}"
    )
    return mean


def main() -> int:
    rng = np.random.default_rng(SEED)
    bars = load()
    unit = atr(bars["high"], bars["low"], bars["close"], ATR_N)
    excursion = forward_excursion(bars, unit)
    sides = rules(bars, unit)

    print(f"{SYMBOL} H1, {len(bars['close'])} bars, horizon {HORIZON}, cost {COST_PX:g} px")
    print(
        f"forward excursion / ATR: median {np.nanmedian(excursion):.2f}, "
        f"10th {np.nanpercentile(excursion, 10):.2f}, 90th {np.nanpercentile(excursion, 90):.2f}\n"
    )

    for rule_name, side in sides.items():
        r, fires = outcomes(bars, unit, side)
        print(f"=== {rule_name} ===")
        base = report("unfiltered", r[fires], rng)
        for low_q, high_q in QUANTILES:
            low_cut = float(np.nanpercentile(excursion, low_q))
            high_cut = float(np.nanpercentile(excursion, high_q))
            # The gate the rule is entitled to: a fade wants a BIG excursion
            # to revert into, a breakout wants one to follow through.
            want_high = rule_name == "breakout"
            state_ok = (
                (excursion >= high_cut) if want_high else (excursion <= low_cut)
            ) & np.isfinite(excursion)
            gated = fires & state_ok
            if gated.sum() < 8:
                continue
            share = gated.sum() / fires.sum()
            oracle = report(
                f"oracle p{low_q}/p{high_q}={low_cut:.1f}/{high_cut:.1f} ({share:.0%})",
                r[gated],
                rng,
                base,
            )
            # Same duty cycle, chosen at random: the arm that catches a gate
            # whose only virtue is trading less.
            pool = np.flatnonzero(fires)
            picked = rng.choice(pool, size=int(gated.sum()), replace=False)
            report(f"  random-gate ({share:.0%})", r[picked], rng, base)
            if np.isfinite(oracle) and oracle <= base:
                print("      oracle does not beat unfiltered - no prediction problem here")
        print()

    # ──── the causal version: today's ATR regime, which needs no foresight ────
    #
    # The oracle above reads the future. This buckets each bar by where its
    # **trailing** ATR sits in its own recent history, which is knowable at the
    # bar - and volatility is the one thing this desk has measured as
    # persistent (forward volatility runs +0.167 to +0.355 of a forecast unit
    # above a matched placebo on 8 of 8 traded markets). So a regime gate is a
    # gate that could actually be traded, where the oracle is only a ceiling.
    print("=== by trailing ATR regime (causal - no foresight) ===")
    rank = np.full(len(unit), np.nan)
    for i in range(REGIME_WINDOW, len(unit)):
        window = unit[i - REGIME_WINDOW : i]
        if np.isfinite(unit[i]) and np.isfinite(window).sum() > REGIME_WINDOW // 2:
            rank[i] = float(np.nanmean(window <= unit[i]))
    edges = np.linspace(0.0, 1.0, REGIME_BUCKETS + 1)
    for rule_name, side in sides.items():
        r, fires = outcomes(bars, unit, side)
        print(f"  {rule_name}:")
        for b in range(REGIME_BUCKETS):
            inside = fires & (rank >= edges[b]) & (rank < edges[b + 1] + (1e-9 if b == REGIME_BUCKETS - 1 else 0.0))
            if inside.sum() < 8:
                continue
            share = inside.sum() / fires.sum()
            report(f"    ATR q{b + 1}/5 ({share:.0%})", r[inside], rng)
        pool = np.flatnonzero(fires)
        picked = rng.choice(pool, size=max(int(0.2 * len(pool)), 8), replace=False)
        report("    random 20%", r[picked], rng)
        print()

    print(
        "Read the oracle rows first. They are the ceiling a classifier could reach with\n"
        "perfect foresight of the volatility class; if a ceiling is at or below\n"
        "`unfiltered`, the class is not worth predicting however predictable it is. And an\n"
        "oracle that beats `unfiltered` but not `random-gate` is only trading less."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
