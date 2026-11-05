"""How often does the live trigger actually fire, and is 3.0 rare?

    ./.secrets/lab.sh run research/harness/surprise_rate.py SEQLAB=$HOME/till_infinity/data/seqlab

## The question

`deciding.TRIGGER` and `proposing.TRIGGER` are **3.0**, and the constant's own
comment justifies it:

> 3.0 rather than 2.0 because `band-coverage.md` measured the 0.99 interval
> breaching at 0.0006 to 0.0018 - a 3-sigma reading is genuinely rare here,
> where on a Gaussian assumption it would not be.

The live desk disagrees. On 2026-11-05 it read `readouts=441 proposals=40`
over five hours - **9.1%** - where a Gaussian 3-sigma is 0.27% and the
comment's own evidence says the model's bands are *conservative*, so it should
be rarer still. A trigger meant to fire about once in 370 readouts fired once
in eleven.

Only two things can be true: the live `surprise` is not distributed the way
`band-coverage.md` measured, or the live model is under-dispersed - its
variance estimate too small, so every innovation reads too large. This
separates them by running the **production engine** over long histories and
reading the whole distribution rather than its tail alone.

## What is reported

Per instrument: the share of readouts at or above 2, 3 and 4, against three
references - a Gaussian, a Student-t at 4 degrees of freedom (which
`no-gaussian-band-is-calibrated` found fixes the one-bar band on 64 of 64 out
of sample), and the empirical quantiles of the series' own standardised
returns. If the engine's surprise matches a t-4 rather than a Gaussian, the
trigger is doing what a 3-sigma threshold does on fat tails and the constant
is misnamed rather than the model broken.
"""

from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

SEQLAB = os.environ.get("SEQLAB", ".data/seqlab")
BASE = os.environ.get("BASE", "15m")
INTERVAL = os.environ.get("INTERVAL", "15m")
SYMBOLS = [s for s in os.environ.get("SYMBOLS", "").split("|") if s] or [
    "EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "Volatility 75 Index", "Step Index",
]
LIMIT = int(os.environ.get("LIMIT", "60000"))


def bars(symbol: str) -> list[dict]:
    z = np.load(f"{SEQLAB}/{symbol}.{BASE}.npz")
    t, o, h, l, c = z["time"], z["open"], z["high"], z["low"], z["close"]
    if len(t) > LIMIT:
        t, o, h, l, c = (a[-LIMIT:] for a in (t, o, h, l, c))
    feed = f"MT5:{symbol}"
    return [
        {
            "feed": feed, "interval": INTERVAL, "time": float(t[i]),
            "open": float(o[i]), "high": float(h[i]), "low": float(l[i]),
            "close": float(c[i]), "volume": 0.0, "closed": True,
        }
        for i in range(len(t))
    ]


def main() -> None:
    import tempfile

    from scipy import stats

    from till_infinity.statespace.config import Settings
    from till_infinity.statespace.engine import Engine
    from till_infinity.statespace.proposing import TRIGGER

    gauss = 2.0 * (1.0 - stats.norm.cdf(TRIGGER))
    t4 = 2.0 * (1.0 - stats.t.cdf(TRIGGER, df=4))
    print(f"trigger {TRIGGER}: gaussian {gauss:.4%}, student-t(4) {t4:.4%}\n")
    print(f"{'instrument':22s} {'readouts':>9s} {'>=2':>8s} {'>=3':>8s} {'>=4':>8s} {'sd':>7s}")

    for symbol in SYMBOLS:
        try:
            payloads = bars(symbol)
        except FileNotFoundError:
            print(f"{symbol:22s} (not in the cache)")
            continue
        with tempfile.TemporaryDirectory() as directory:
            engine = Engine(
                settings=Settings(
                    state_dir=directory,
                    intervals=(INTERVAL,),
                    feeds=(f"MT5:{symbol}",),
                )
            )
            seen: list[float] = []
            for payload in payloads:
                readout = engine.observe_bar(payload)
                if readout is not None:
                    seen.append(abs(float(readout.surprise)))
        if not seen:
            print(f"{symbol:22s} {0:9d}  no readouts - check the feed and interval names")
            continue
        a = np.asarray(seen)
        print(
            f"{symbol:22s} {len(a):9d} {(a >= 2).mean():8.3%} {(a >= 3).mean():8.3%} "
            f"{(a >= 4).mean():8.3%} {a.std():7.2f}"
        )


if __name__ == "__main__":
    main()
