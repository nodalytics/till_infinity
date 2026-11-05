"""Does expectancy per proposal hold up as the trigger falls?

    ./.secrets/lab.sh run research/harness/trigger_expectancy.py SEQLAB=$HOME/till_infinity/data/seqlab

`surprise-rate.md` measured what the threshold costs in *events*: 15.2-17.4%
of readouts at 1.5 sigma, 6.2-7.9% at 2.0, 0.9-1.9% at 3.0. A firing rate is
not an edge, and the only thing that justifies a lower threshold is expectancy
per proposal holding up as it falls - because **cost scales linearly with the
event count and edge does not**.

So this reports, per trigger: the signed continuation in units of the
pre-event volatility forecast, its day-block bootstrap interval, the quoted
round trip it has to clear, and the sign-flip surrogate on the same cells. The
surrogate keeps every `|return|` in order and randomises the signs, so it
holds the volatility path exactly and destroys direction - anything that
appears there is volatility, not skill.

Deliberately narrow: no exits, no fills, no stop. It is a conditional mean,
not a trade, and a favourable reading here is a reason to build the barrier
test rather than to move a live constant.
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

SEQLAB = os.environ.get("SEQLAB", ".data/seqlab")
BASE = os.environ.get("BASE", "15m")
TRADED = ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "XAUUSD")
WALKS = ("Volatility 75 Index", "Step Index")
TRIGGERS = (1.5, 2.0, 2.5, 3.0, 4.0)
HORIZON = 12
VOL_SPAN = 60
#: Quoted round trips in forecast units, from `impulse-vol.md`: the per-bar
#: `spread` column is unusable - 3.3-8.3x below the quote on FX and 6.5x above
#: it on a synthetic - so the cost line uses the quote.
COST = 0.22
SEED = 20261105


def series(symbol: str) -> np.ndarray | None:
    try:
        z = np.load(f"{SEQLAB}/{symbol}.{BASE}.npz")
    except FileNotFoundError:
        return None
    close = np.log(np.asarray(z["close"], dtype=float))
    return np.diff(close)


def dress(r: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    vol = pd.Series(np.abs(r)).ewm(span=VOL_SPAN, min_periods=VOL_SPAN).mean().shift(1).to_numpy()
    return vol, r / vol


def forward(r: np.ndarray, vol: np.ndarray, k: int) -> np.ndarray:
    cum = np.concatenate([[0.0], np.cumsum(r)])
    n = len(r)
    out = np.full(n, np.nan)
    i = np.arange(n - k)
    out[i] = (cum[i + 1 + k] - cum[i + 1]) / vol[i]
    return out


def blocks(day: np.ndarray, value: np.ndarray, rng, draws: int = 300) -> tuple[float, float, float]:
    keys = pd.unique(day)
    by = {k: value[day == k] for k in keys}
    means = np.array([
        np.concatenate([by[k] for k in rng.choice(keys, size=len(keys), replace=True)]).mean()
        for _ in range(draws)
    ])
    return float(value.mean()), float(np.quantile(means, 0.05)), float(np.quantile(means, 0.95))


def main() -> None:
    rng = np.random.default_rng(SEED)
    rows = []
    for symbol in (*TRADED, *WALKS):
        r = series(symbol)
        if r is None:
            print(f"skip {symbol} (not in the cache)", file=sys.stderr)
            continue
        kind = "walk" if symbol in WALKS else "real"
        day = (np.arange(len(r)) // 96).astype(np.int64)
        for arm, path in (("real", r), ("signflip", np.abs(r) * rng.choice((-1.0, 1.0), len(r)))):
            vol, z = dress(path)
            fwd = forward(path, vol, HORIZON)
            for trigger in TRIGGERS:
                ok = (np.abs(z) >= trigger) & np.isfinite(fwd)
                if ok.sum() < 200:
                    continue
                cont = fwd[ok] * np.sign(z[ok])
                mean, lo, hi = blocks(day[ok], cont, rng)
                rows.append({
                    "symbol": symbol, "kind": kind, "arm": arm, "trigger": trigger,
                    "events": int(ok.sum()), "rate": float(ok.mean()),
                    "cont": mean, "lo": lo, "hi": hi, "net": mean - COST,
                })
        print(f"{symbol} done", file=sys.stderr, flush=True)

    d = pd.DataFrame(rows)
    where = os.environ.get("OUT", "trigger_expectancy.csv")
    d.to_csv(where, index=False)

    print(f"\ncost line: {COST} forecast units (quoted round trip)\n")
    for kind in ("real", "walk"):
        part = d[(d.kind == kind) & (d.arm == "real")]
        if part.empty:
            continue
        print(f"=== {kind} markets, signed continuation at k={HORIZON} ===")
        g = part.groupby("trigger").agg(
            insts=("symbol", "nunique"), events=("events", "sum"), rate=("rate", "mean"),
            cont=("cont", "mean"), lo=("lo", "mean"), hi=("hi", "mean"), net=("net", "mean"),
        )
        g["beats_cost"] = part.groupby("trigger").apply(
            lambda x: int((x.lo > COST).sum()), include_groups=False
        )
        print(g.round(4).to_string(), "\n")
    flip = d[(d.kind == "real") & (d.arm == "signflip")]
    print("=== sign-flip surrogate, traded markets ===")
    print(flip.groupby("trigger")["cont"].agg(["mean", "std"]).round(4).to_string())


if __name__ == "__main__":
    main()
