"""Do turns work on a clock this desk can trade, or only on the daily?

Run from the repository root:  python research/harness/turns_fast.py

`turns.md` holds the strongest **unbuilt** result in this folder: on fourteen instruments a purged
walk-forward gives **AUC 0.595, 95% interval 0.540-0.654**, which excludes 0.5 over 310 turns. The
effect is the conventional one - old, extended, volatile trends turn - and it is measured rather
than plausible.

It has never been built, and the reason is the clock. The question it asks is

> on a day when the instrument is in an established uptrend near its highs, will it fall by 20 of
> its own daily move units within **60 trading days**?

Three months is not a horizon this desk has. Entries now run 1m to 30m and holds run minutes to
hours, so a signal with a quarter-long horizon cannot be acted on however good it is.

## The question this file asks instead

**Is the effect scale-free?** Keep every clause of the original and change only the bar clock: on an
*hourly* series, in an established uptrend near its highs, will it fall by 20 of its own **hourly**
move units within 60 **hourly** bars?

Sixty hours is two and a half days. That is a horizon the desk has.

The repository has found scale-invariance twice, which is why this is worth asking rather than
assuming. `break-trade.md` measured the break hazard crossing even money at four to seven bars of
the level's own timeframe across a thirtyfold span; `breakout-runs.md` measured breakout excursion
matching the driftless law at every quantile, so the captured fraction is scale-invariant and the
trail width has no optimum. If turns are the same kind of object, the daily result reproduces here.

If it does not reproduce, that is also an answer: it says trend exhaustion is a slow, macro
phenomenon rather than a fractal one, and `turns.md` should stay unbuilt rather than be ported to a
clock it does not live on.

## Every one of the original's refusals is kept

`turns.md` designed its controls before its model and they are the reason its number is worth
porting. All three carry over.

**Overlapping windows.** Two bars an hour apart share 59 of their 60 forward bars, so rows are
nowhere near independent and a plain interval is meaningless. The interval here is an **episode
bootstrap** - contiguous blocks at least as long as the horizon - which is the original's control.

**The universe is the comparison.** The label is only interesting against *moments that looked the
same and continued*, so the sample is restricted to bars already in an established uptrend near
their highs. A model that learns to tell an uptrend from a downtrend has answered an easier
question and would score well doing it.

**Units, not percent.** One threshold in percent would mean a routine fortnight for btc and a
generational move for eurusd. Twenty move units is twenty times the instrument's own median
absolute bar return, so the question means the same thing everywhere.

**And a forward drawdown, not a pivot.** A zigzag pivot is confirmed days after the extreme, so a
model trained on pivot labels is asked when a pivot will be *confirmed* rather than when the turn
happened.

## Three features, pre-registered

`auditing.md`'s verdict on the original is the reason this list is short: *"`vol` alone at 0.604 is
the top of a ten-signal scan"*. A ten-signal scan reporting its best is a multiple-comparisons
problem, so the features here are named in advance and there are three - the three the original's
mechanism actually names.

* **age** - how long the trend has run, in bars since the trailing low;
* **extension** - how far price sits above its own trailing mean, in move units;
* **volatility** - the trailing dispersion, in its own recent range.

Old, extended, volatile. Nothing else is tried, so nothing has to be corrected for.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "training"))

import candles  # noqa: E402

#: The fourteen-instrument universe of `turns.md`, of what this desk holds hourly.
UNIVERSE = ("btcusd", "xauusd", "xagusd", "eurusd", "gbpusd", "usdjpy", "usdcad")

#: Bars forward the drawdown is measured over, and the size of it in move units. Both taken from
#: `turns.md` unchanged - only the meaning of "bar" differs.
HORIZON = 60
DROP_UNITS = 20.0

#: The universe gate: price within this fraction of its trailing high, a trailing window long
#: enough for "established" to mean something, and a minimum age so the leg has actually run.
#:
#: **Tightened after a first run.** At 3% and no age floor the gate kept **94.1%** of eurusd bars,
#: which is not a comparison set - it is the series. The original is explicit that the label is
#: only interesting against *moments that looked the same and continued*, and warns that a model
#: which learns to tell a bull market from a bear market "has answered an easier question and would
#: score well doing it". A gate that admits everything guarantees exactly that.
NEAR_HIGH = 0.01
TREND_WINDOW = 240
MIN_AGE = 60

#: Trailing window for the volatility and extension readings.
LOOK = 120

#: Held back chronologically and never fitted on, with a purge of `HORIZON` bars between.
TEST_SHARE = 0.3


def rolling(values: np.ndarray, window: int, how: str) -> np.ndarray:
    """Backward-looking rolling max, min or mean - bar `i` sees `[i-window+1, i]`."""
    out = np.full(len(values), np.nan)
    if len(values) < window:
        return out
    panes = np.lib.stride_tricks.sliding_window_view(values, window)
    got = {"max": panes.max, "min": panes.min, "mean": panes.mean}[how](axis=1)
    out[window - 1 :] = got
    return out


def state(close: np.ndarray, rets: np.ndarray) -> dict[str, np.ndarray]:
    """The three pre-registered features, plus the universe gate. All backward-looking."""
    unit = float(np.median(np.abs(rets[np.isfinite(rets)]))) or 1e-9
    high = rolling(close, TREND_WINDOW, "max")
    low = rolling(close, TREND_WINDOW, "min")
    mean = rolling(close, LOOK, "mean")

    # Age: bars since the trailing low, which is how long this leg has been running.
    age = np.full(len(close), np.nan)
    for i in range(TREND_WINDOW - 1, len(close)):
        window = close[i - TREND_WINDOW + 1 : i + 1]
        age[i] = float(TREND_WINDOW - 1 - int(np.argmin(window)))

    # Extension: how far above its own mean, in move units.
    extension = np.log(np.maximum(close, 1e-12) / np.maximum(mean, 1e-12)) / unit

    # Volatility: trailing dispersion against its own recent range, so it is comparable across
    # instruments without being the same number as `extension`.
    sd = np.full(len(close), np.nan)
    csq = np.concatenate([[0.0], np.cumsum(np.nan_to_num(rets) ** 2)])
    sd[LOOK - 1 :] = np.sqrt((csq[LOOK:] - csq[:-LOOK]) / LOOK)
    vol = sd / unit

    near = (close >= high * (1.0 - NEAR_HIGH)) & (high > low) & (age >= MIN_AGE)
    return {
        "age": age,
        "extension": extension,
        "vol": vol,
        "near": near.astype(float),
        "unit": unit,
        "sd": sd,
    }


def label(close: np.ndarray, scale: np.ndarray) -> np.ndarray:
    """Did price fall `DROP_UNITS` of `scale` below this bar within `HORIZON` bars?

    A forward **drawdown** from the bar itself, not a pivot: no confirmation lag and no ambiguity
    about which bar the turn happened on.

    **`scale` is the argument that decides whether this measures anything.** Passed a single
    number - the instrument's median absolute return over the whole sample, which is what
    `turns.md` uses - the threshold is a *fixed* distance, and then current volatility predicts
    reaching it almost by construction: a 20-unit fall is easy in a loud stretch and hard in a
    quiet one whatever the trend is doing. Measured here, `vol` alone scored **0.660** on that
    specification, and `auditing.md` records `vol` alone at 0.604 on the daily original - the same
    artefact, in the same place.

    Passed the **trailing** volatility per bar, the threshold is "twenty sigma as sigma stands
    now", and volatility can no longer answer the question by knowing its own size.
    """
    out = np.full(len(close), np.nan)
    floor = np.full(len(close), np.nan)
    usable = len(close) - HORIZON
    if usable <= 0:
        return out
    panes = np.lib.stride_tricks.sliding_window_view(close[1:], HORIZON)
    floor[:usable] = panes.min(axis=1)[:usable]
    fell = np.log(np.maximum(floor, 1e-12) / np.maximum(close, 1e-12))
    unit = np.where(np.isfinite(scale) & (scale > 0), scale, np.nan)
    out[:usable] = (fell[:usable] / unit[:usable] <= -DROP_UNITS).astype(float)
    return out


def auc(score: np.ndarray, flag: np.ndarray) -> float:
    ok = np.isfinite(score) & np.isfinite(flag)
    score, flag = score[ok], flag[ok].astype(bool)
    if len(score) < 200 or flag.sum() == 0 or flag.all():
        return float("nan")
    order = np.argsort(score)
    ranks = np.empty(len(score), dtype=float)
    ranks[order] = np.arange(1, len(score) + 1)
    pos = float(flag.sum())
    return float((ranks[flag].sum() - pos * (pos + 1) / 2.0) / (pos * (len(flag) - pos)))


def episode_interval(
    score: np.ndarray, flag: np.ndarray, block: int, draws: int = 300
) -> tuple[float, float]:
    """`turns.md`'s control: resample contiguous **episodes**, not rows.

    Two bars an hour apart share 59 of their 60 forward bars. Resampling rows would treat those as
    independent evidence and return an interval several times too narrow, which is exactly how an
    overlapping-window study manufactures significance.
    """
    n = len(score)
    if n < block * 8:
        return (float("nan"), float("nan"))
    starts = np.arange(0, n - block)
    count = max(n // block, 1)
    rng = np.random.default_rng(0)
    got = []
    for _ in range(draws):
        picks = rng.choice(starts, size=count)
        idx = np.concatenate([np.arange(p, p + block) for p in picks])
        value = auc(score[idx], flag[idx])
        if np.isfinite(value):
            got.append(value)
    if len(got) < 50:
        return (float("nan"), float("nan"))
    return (float(np.quantile(got, 0.025)), float(np.quantile(got, 0.975)))


def fit(design: np.ndarray, target: np.ndarray) -> np.ndarray:
    """Ridge on standardised columns, which is all three features need."""
    beta, *_ = np.linalg.lstsq(
        design.T @ design + 1e-3 * np.eye(design.shape[1]), design.T @ target, rcond=None
    )
    return beta


def study(bars: np.ndarray) -> dict | None:
    close = bars[:, 4]
    keep = close > 0
    close = close[keep]
    if len(close) < 20_000:
        return None
    rets = np.concatenate([[np.nan], np.diff(np.log(close))])
    built = state(close, rets)
    # Primary specification: the threshold scales with **trailing** volatility, so volatility
    # cannot predict the label by knowing its own size. The global-unit version is reported
    # beside it so the artefact is visible rather than argued about.
    flags = label(close, built["sd"])
    fixed = label(close, np.full(len(close), built["unit"]))

    ok = np.isfinite(flags) & (built["near"] > 0)
    for name in ("age", "extension", "vol"):
        ok &= np.isfinite(built[name])
    rows = np.where(ok)[0]
    if len(rows) < 2_000:
        return None

    cut = int(len(rows) * (1.0 - TEST_SHARE))
    # Purged: no training row's forward window reaches into the test block.
    train, test = rows[: max(cut - HORIZON, 0)], rows[cut:]
    if len(train) < 1_000 or len(test) < 500:
        return None

    columns = ("age", "extension", "vol")
    raw = np.column_stack([built[c] for c in columns])
    mean, sd = raw[train].mean(axis=0), raw[train].std(axis=0)
    sd[sd <= 0] = 1.0
    design = np.column_stack([(raw - mean) / sd, np.ones(len(close))])

    beta = fit(design[train], flags[train])
    called = design[test] @ beta
    lo, hi = episode_interval(called, flags[test], HORIZON)
    singles = {c: auc(built[c][test], flags[test]) for c in columns}
    # The same model against the fixed-threshold label, which is the specification the original
    # used. Reported so the artefact it carries is visible side by side rather than argued about.
    fixed_ok = np.isfinite(fixed[test])
    fixed_auc = (
        auc(called[fixed_ok], fixed[test][fixed_ok]) if fixed_ok.sum() > 500 else float("nan")
    )
    fixed_vol = (
        auc(built["vol"][test][fixed_ok], fixed[test][fixed_ok])
        if fixed_ok.sum() > 500
        else float("nan")
    )
    return {
        "n": len(test),
        "base": float(flags[test].mean()),
        "auc": auc(called, flags[test]),
        "lo": lo,
        "hi": hi,
        "singles": singles,
        "universe": float(len(rows)) / float(len(close)),
        "fixed_auc": fixed_auc,
        "fixed_vol": fixed_vol,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("symbols", nargs="*", default=list(UNIVERSE))
    ap.add_argument("--where", default=os.environ.get("WHERE", ".secrets/broker-deep"))
    ap.add_argument("--interval", default="1h")
    args = ap.parse_args()

    print(
        f"turns.md's question on a {args.interval} clock: in an established uptrend near its "
        f"highs,\nwill price fall {DROP_UNITS:.0f} of its own move units within {HORIZON} bars?\n"
        f"\nthe daily original: AUC 0.595, 95% interval 0.540-0.654, over 310 turns\n"
        "the interval here is an **episode** bootstrap - rows share 59 of 60 forward bars\n"
        "three features, named in advance: age, extension, volatility\n"
    )

    print(
        f"  {'symbol':<10}{'n test':>8}{'base':>8}{'univ':>7}{'AUC':>8}"
        f"{'95% episode':>19}{'age':>7}{'ext':>7}{'vol':>7}"
        f"{'| fixed':>9}{'vol':>7}"
    )
    rows = []
    for symbol in args.symbols:
        found = sorted(Path(args.where).expanduser().glob(f"{symbol}_{args.interval}_*.csv.gz"))
        if not found:
            continue
        bars, _repaired = candles.read(found[0])
        got = study(bars)
        if got is None:
            print(f"  {symbol:<10}{'too few usable bars':>40}")
            continue
        rows.append((symbol, got))
        mark = "  <-" if got["lo"] > 0.5 else ""
        print(
            f"  {symbol:<10}{got['n']:>8,}{got['base']:>8.1%}{got['universe']:>7.1%}"
            f"{got['auc']:>8.4f}  [{got['lo']:.3f}, {got['hi']:.3f}]"
            f"{got['singles']['age']:>7.3f}{got['singles']['extension']:>7.3f}"
            f"{got['singles']['vol']:>7.3f}"
            f"{got['fixed_auc']:>9.3f}{got['fixed_vol']:>7.3f}{mark}"
        )

    if rows:
        clears = sum(1 for _s, g in rows if g["lo"] > 0.5)
        pooled = float(np.mean([g["auc"] for _s, g in rows]))
        print(
            f"\n  mean AUC {pooled:.4f} across {len(rows)} instruments; "
            f"**{clears} of {len(rows)}** have an episode interval excluding 0.5"
        )

    print(
        "\n  **Compare with 0.595 [0.540, 0.654] on the daily**, not with 0.5. The question is\n"
        "  whether the effect is scale-free; the repository has measured that twice, for the\n"
        "  break hazard across a thirtyfold span of timeframes and for breakout excursion at\n"
        "  every quantile. Reproducing here would make the daily result portable to a clock\n"
        "  this desk can trade; failing to says trend exhaustion is macro rather than fractal.\n"
        "\n  **`| fixed` is the artefact, shown deliberately.** It is the same model against the\n"
        "  original's fixed-threshold label, where the drop is measured in a *global* median move\n"
        "  unit. On that specification current volatility predicts the label almost by\n"
        "  construction - a 20-unit fall is easy in a loud stretch and hard in a quiet one,\n"
        "  whatever the trend is doing - so the `vol` column beside it is what is scored.\n"
        "  the trend is doing - so the `vol` column beside it is what is really being scored.\n"
        "  `auditing.md` records `vol` alone at 0.604 on the daily original, which is the same\n"
        "  number in the same place.\n"
        "\n  `univ` is the share of bars passing the gate. One that keeps almost everything\n"
        "  is not the comparison set the question needs; one that keeps nothing has no sample."
        "  the comparison set the question needs; one that keeps almost nothing has no sample."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
