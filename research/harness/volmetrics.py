"""R-squared and the rest, for every volatility forecaster, on one replay.

`volhorizon.py` scores members with `consensus_vol.Score` - one minus a
symmetric relative error - because that is the scoreboard already inside the
package. It is bounded and robust and it is **not comparable to anything
outside this repository**, which makes "is 0.83 good?" unanswerable.

So this reports the standard set instead, all of them out-of-sample by
construction: every example is predicted before it is learned, in time order,
which is the discipline `learning/facto.py` sets out and the only honest one
here - two bars minutes apart are nearly the same observation, so a shuffled
split measures memorisation.

**R-squared is against the right baseline, and that is the whole difficulty.**
Reported against the mean it is nearly meaningless for volatility: the series
is so autocorrelated that predicting the last value explains most of the
variance, and any model looks excellent. So two are reported:

* `R2_mean` - the textbook one, against predicting the sample mean. Flattering.
* `R2_naive` - against predicting **the last realised value**. This is the one
  that matters, and it is negative for a model that is worse than persistence.
  It is the same quantity as "beats naive" in `volhorizon.py`, expressed on a
  scale a reader outside this repository can interpret.

There is deliberately no AUC. AUC ranks a *classifier*; this is a regression
onto a positive continuous quantity and there is no threshold to sweep. Where
a direction question is asked of these models later - "will the next bar be
livelier than this one" - AUC becomes the right tool and this is not that.
"""

from __future__ import annotations

import math
import os
import sqlite3
import statistics as st
import sys

sys.path.insert(0, "/app")

from till_infinity.structures.context import sessions  # noqa: E402
from till_infinity.structures.learning.facto import Model as Facto  # noqa: E402
from till_infinity.structures.vol.consensus_vol import MAD_TO_SIGMA  # noqa: E402
from till_infinity.structures.vol.volatility import Book  # noqa: E402

DB = os.environ.get("PRICES", "/app/.data/prices/prices.db")
INTERVALS = tuple(os.environ.get("INTERVALS", "5m,15m,1h").split(","))
LIMIT = int(os.environ.get("LIMIT", "400000"))
FEEDS = tuple(f for f in os.environ.get("FEEDS", "").split(",") if f)
HALF = os.environ.get("HALF", "")
SECONDS = {"1m": 60.0, "5m": 300.0, "15m": 900.0, "30m": 1800.0, "1h": 3600.0}


def stats(said: list[float], actual: list[float], naive: list[float]) -> dict[str, float]:
    """Every number this reports, for one forecaster."""
    n = len(actual)
    if n < 100:
        return {}
    err = [p - a for p, a in zip(said, actual)]
    mean = st.fmean(actual)
    ss_res = math.fsum(e * e for e in err)
    ss_mean = math.fsum((a - mean) ** 2 for a in actual)
    ss_naive = math.fsum((b - a) ** 2 for b, a in zip(naive, actual))
    # Pearson between forecast and outcome: how much of the *ordering* is right,
    # which a badly calibrated but informative model still gets.
    ms = st.fmean(said)
    cov = math.fsum((p - ms) * (a - mean) for p, a in zip(said, actual))
    ds = math.sqrt(math.fsum((p - ms) ** 2 for p in said))
    da = math.sqrt(ss_mean)
    return {
        "n": float(n),
        "R2_mean": 1.0 - ss_res / ss_mean if ss_mean > 0 else 0.0,
        "R2_naive": 1.0 - ss_res / ss_naive if ss_naive > 0 else 0.0,
        "MAE": st.fmean([abs(e) for e in err]),
        "RMSE": math.sqrt(ss_res / n),
        "corr": cov / (ds * da) if ds > 0 and da > 0 else 0.0,
    }


def run() -> None:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=300.0)
    marks = ",".join("?" for _ in INTERVALS)
    where = f"interval IN ({marks})"
    args: list = list(INTERVALS)
    if FEEDS:
        where += f" AND feed IN ({','.join('?' for _ in FEEDS)})"
        args += list(FEEDS)
    rows = conn.execute(
        f"SELECT feed, interval, ts, open, high, low, close, volume FROM bars "
        f"WHERE {where} ORDER BY ts ASC LIMIT ?",
        (*args, LIMIT),
    ).fetchall()
    if HALF:
        cut = len(rows) // 2
        rows = rows[:cut] if HALF == "first" else rows[cut:]
    print(f"{len(rows):,} bars, {len({r[0] for r in rows})} feeds\n")

    book = Book()
    clock = sessions.Clock()
    # The factorisation machine, fed the identical rows the tree gets. An FM
    # models pairwise interactions through latent factors, which is the same
    # claim the tree is making by a different route - so this is the fair
    # comparison for "does modelling interactions help", with the model family
    # as the only difference.
    fm = Facto()
    # Everything is compared on the **log correction** the tree predicts, not on
    # raw bps: on bps a single violent synthetic dominates every sum here and
    # R-squared becomes a statement about that instrument.
    said: dict[str, list[float]] = {k: [] for k in ("naive", "har", "learned", "facto")}
    actual: list[float] = []
    pending: dict[str, tuple] = {}

    for feed, interval, ts, open_, high, low, close, volume in rows:
        if not all(isinstance(v, int | float) and v > 0 for v in (open_, high, low, close)):
            continue
        when = float(ts) / 1000.0 if ts > 10_000_000_000 else float(ts)
        key = f"{feed}|{interval}"
        vol = book.of(feed, interval)
        vol.update(float(close))
        realised = vol.observe_bar(float(open_), float(high), float(low), float(close))
        if not realised or realised <= 0:
            continue

        # Settle the previous bar's forecasts against what just happened.
        held = pending.pop(key, None)
        if held is not None:
            row, unit, was_naive, was_har, was_learned, was_facto = held
            if unit > 0 and realised > 0:
                truth = math.log(realised / unit)
                actual.append(truth)
                said["naive"].append(math.log(max(was_naive, 1e-9) / unit))
                said["har"].append(math.log(max(was_har, 1e-9) / unit))
                said["learned"].append(was_learned)
                said["facto"].append(was_facto)
                if row:
                    fm.learn(row, truth)

        try:
            _, share = clock.volatility(feed, when)
        except Exception:
            share = 1.0
        learned = book.learned
        row = learned.features(
            key,
            ew_bps=vol.bps,
            garch_bps=vol.garch_bps,
            range_bps=vol.range_bps,
            har_bps=vol.forecast_bps,
            stretch=vol.stretch,
            open_=float(open_), high=float(high), low=float(low), close=float(close),
            hour=float(sessions.hour_of(when)), hour_share=share,
            volume=float(volume) if isinstance(volume, int | float) and volume > 0 else 0.0,
            interval_seconds=SECONDS.get(interval, 0.0),
        )
        book.learn(
            feed, interval, realised,
            open_=float(open_), high=float(high), low=float(low), close=float(close),
            hour=float(sessions.hour_of(when)), hour_share=share,
            volume=float(volume) if isinstance(volume, int | float) and volume > 0 else 0.0,
            interval_seconds=SECONDS.get(interval, 0.0),
        )
        got = learned._by_key.get(key)
        tree_said = float(got.said.get("learned") or 0.0) if got else 0.0
        pending[key] = (
            row,
            vol.bps,
            realised,
            (vol.forecast_bps / MAD_TO_SIGMA) if vol.forecast_bps > 0 else realised,
            math.log(max(tree_said, 1e-9) / vol.bps) if tree_said > 0 and vol.bps > 0 else 0.0,
            fm.predict(row) if row else 0.0,
        )

    print(f"{'model':10s} {'n':>9s} {'R2_mean':>9s} {'R2_naive':>9s} {'MAE':>8s} "
          f"{'RMSE':>8s} {'corr':>7s}")
    for name in ("naive", "har", "learned", "facto"):
        got = stats(said[name], actual, said["naive"])
        if not got:
            print(f"{name:10s} too few")
            continue
        print(f"{name:10s} {got['n']:9,.0f} {got['R2_mean']:9.4f} {got['R2_naive']:9.4f} "
              f"{got['MAE']:8.4f} {got['RMSE']:8.4f} {got['corr']:7.4f}")
    print("\nR2_naive > 0 means it beats reusing the last realised value.")


if __name__ == "__main__":
    run()
