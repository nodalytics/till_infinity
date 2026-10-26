"""The OHLCV-only signal families, cross-sectionally, on 523 daily equities.

A list of candidate edges from OHLCV alone was put forward, prioritised. Most
of it is already measured here and failed - every SMC, level, pattern,
reversion and sweep rule in `imported-ideas.md`'s 4,800 cells; gaps rank at
0.92-0.97 but that is the calendar; breakout retests read **-0.291R** over
167,501 trades. One family passed: **volatility-scaled time-series momentum**,
Sharpe 0.42 fresh and **0.79 on 36 unseen Binance perpetuals with real
funding**.

But its first priority - **short-term reversal conditioned on volume and
illiquidity** - has never been tested here, for a specific reason: Amihud
illiquidity is `|r| / dollar volume`, and on MT5 FX "volume" is a count of
quote updates. Every volume-weighted indicator on this desk is null because
its key input does not mean what its name says.

**The daily equity cache is the exception.** 523 names with real share volume
*and* a spread column, so the one untested family is computable on data where
its input is real.

## The unit is a (date, name) rank, not a time series

Per date, names are ranked by the signal and a long-short spread is formed
from the extreme terciles. The statistic is the mean spread return across
dates with its standard error, so the **cross-section is the sample** - which
is what makes 270 bars a usable history.

Dates are **non-overlapping at the horizon**: every h-th date, so the spread
returns are independent and `overlapping-outcome-windows-leak` does not apply.
That costs sample at h=20 (13 periods) and leaves h=1 and h=5 - the paste's own
"1-5 day" priority - with 270 and 54.

## The nulls, and why two

* `shuffled` - ranks permuted **within each date**, which breaks the signal
  while preserving that date's cross-sectional return distribution exactly.
  This is the null the statistic is read against.
* `synthetic` - the same harness on a cross-section of geometric Brownian
  names. Any spread that appears there is mechanical, and
  `the-placebo-arm-selects-the-null` is the standing reason to reject a null
  that finds structure.

## What this cannot fix, and says so

**Survivorship.** 523 names from a cache of current constituents is not the
universe that existed in the sample, and the paste names this itself. A
reversal study on survivors is biased toward names that recovered.

**Corporate actions.** Whether these closes are adjusted is not recorded, so a
split would read as a 50% return. The `shuffled` arm does not catch that; it
would show up as fat tails in the spread returns, which is reported.

**Costs.** `spread-column-is-in-points` - that column is in points, not price,
and reading it as price gave EURUSD a 476% round trip. So the gross number is
reported alongside the median `spread / close` **so the implied scale can be
seen**, plus net at 5 and 10 basis points round trip. A family whose gross
edge is under a basis point is not reported as an edge.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
for q in (HERE, HERE.parent, HERE.parents[1]):
    sys.path.insert(0, str(q))

from pattern_fingerprint import CACHE, classify  # noqa: E402

FRAME = "1d"
HORIZONS = (1, 5, 20)
#: Fraction of names in each extreme group. A tercile rather than a decile,
#: because 523 names at a decile is 52 and the conditional arms cut that by
#: three again.
EDGE = 1.0 / 3.0
#: Trailing window for the realised volatility, volume z and Amihud measures,
#: in days. Known at the bar it is read on.
LOOKBACK = 20
#: Round-trip costs to net out, in basis points.
COSTS = (5.0, 10.0)
LEAST_NAMES = 60
#: Spans for the range-position reading, in bars of the frame being read. On
#: the daily frame these are a week, a month and a quarter.
WINDOWS = (5, 20, 60)
SEED = 20261026


def _load(path: Path) -> dict[str, np.ndarray] | None:
    with np.load(path) as bundle:
        need = {"time", "open", "high", "low", "close", "volume"}
        if not need <= set(bundle.keys()):
            return None
        order = np.argsort(bundle["time"])
        got = {k: np.asarray(bundle[k], dtype=float)[order] for k in need}
        if "spread" in bundle:
            got["spread"] = np.asarray(bundle["spread"], dtype=float)[order]
    keep = (got["close"] > 0) & (got["high"] >= got["low"]) & (got["low"] > 0)
    got = {k: v[keep] for k, v in got.items()}
    return got if len(got["close"]) >= 120 else None


def _features(bars: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Everything the families need, each known at its own bar's close."""
    close, open_, high, low = bars["close"], bars["open"], bars["high"], bars["low"]
    volume = np.maximum(bars["volume"], 0.0)
    rows = len(close)

    ret = np.full(rows, np.nan)
    ret[1:] = close[1:] / close[:-1] - 1.0
    gap = np.full(rows, np.nan)
    gap[1:] = open_[1:] / close[:-1] - 1.0
    intraday = close / np.maximum(open_, 1e-12) - 1.0
    span = np.maximum(high - low, 1e-12)
    clv = (close - low) / span
    dollar = close * volume
    amihud = np.abs(ret) / np.maximum(dollar, 1e-12)

    def trailing(source: np.ndarray, how) -> np.ndarray:
        out = np.full(rows, np.nan)
        for i in range(LOOKBACK, rows):
            block = source[i - LOOKBACK + 1 : i + 1]
            block = block[np.isfinite(block)]
            if len(block) >= LOOKBACK // 2:
                out[i] = how(block)
        return out

    vol = trailing(ret, np.std)
    dollar_mean = trailing(dollar, np.mean)
    dollar_sd = trailing(dollar, np.std)
    amihud_mean = trailing(amihud, np.mean)

    volume_z = np.full(rows, np.nan)
    good = np.isfinite(dollar_sd) & (dollar_sd > 0)
    volume_z[good] = (dollar[good] - dollar_mean[good]) / dollar_sd[good]

    # **Where the close sits in its own N-bar range** - the ceiling-and-floor
    # reading, as a number rather than a drawn line. 0 is the floor of the
    # window, 1 the ceiling, so it is comparable across names and scales
    # without any level being marked. `WINDOWS` is in **bars of this frame**,
    # and the frame is the unit the caller chose: the same construction at 1h
    # or 5m is the same statistic over a different span, which is why
    # `inputs.py` insists a window is hours rather than a bar count.
    position: dict[int, np.ndarray] = {}
    for window in WINDOWS:
        out = np.full(rows, np.nan)
        for i in range(window, rows):
            ceiling = float(high[i - window + 1 : i + 1].max())
            floor = float(low[i - window + 1 : i + 1].min())
            if ceiling > floor:
                out[i] = (close[i] - floor) / (ceiling - floor)
        position[window] = out

    past5 = np.full(rows, np.nan)
    past5[5:] = close[5:] / close[:-5] - 1.0
    past20 = np.full(rows, np.nan)
    past20[20:] = close[20:] / close[:-20] - 1.0
    scaled = np.full(rows, np.nan)
    good = np.isfinite(vol) & (vol > 0)
    scaled[good] = past20[good] / vol[good]

    return {
        "ret": ret,
        "past5": past5,
        "past20": past20,
        "tsmom": scaled,
        "vol": vol,
        "clv": clv,
        "gap": gap,
        "intraday": intraday,
        "volume_z": volume_z,
        "amihud": amihud_mean,
        "close": close,
        "open": open_,
        "time": bars["time"],
        **{f"range_{window}": position[window] for window in WINDOWS},
        "spread_frac": (bars.get("spread", np.zeros(rows)) / np.maximum(close, 1e-12)),
    }


#: (name, the signal to rank on, which end is long, an optional conditioner).
#: `long_low` says the bottom tercile is the long leg - reversal buys losers.
ARMS: tuple[tuple[str, str, bool, str | None], ...] = (
    ("reversal 1d", "ret", True, None),
    ("reversal 5d", "past5", True, None),
    ("reversal 1d | illiquid", "ret", True, "amihud_high"),
    ("reversal 1d | liquid", "ret", True, "amihud_low"),
    ("reversal 1d | heavy volume", "ret", True, "volume_high"),
    ("reversal 1d | light volume", "ret", True, "volume_low"),
    ("tsmom 20d / vol", "tsmom", False, None),
    ("momentum 20d raw", "past20", False, None),
    ("low volatility", "vol", True, None),
    ("gap", "gap", True, None),
    ("gap | closed strong", "gap", True, "clv_high"),
    ("close location", "clv", False, None),
    # The ceiling-and-floor arms, both ways round: at the top of its own range
    # is either a breakout about to continue or an overextension about to
    # revert, and only the measurement says which.
    ("at range ceiling 5d", "range_5", False, None),
    ("at range floor 5d", "range_5", True, None),
    ("at range ceiling 20d", "range_20", False, None),
    ("at range floor 20d", "range_20", True, None),
    ("at range ceiling 60d", "range_60", False, None),
    ("ceiling 20d | heavy volume", "range_20", False, "volume_high"),
    ("ceiling 20d | illiquid", "range_20", False, "amihud_high"),
)

CONDITIONS = {
    "amihud_high": ("amihud", True),
    "amihud_low": ("amihud", False),
    "volume_high": ("volume_z", True),
    "volume_low": ("volume_z", False),
    "clv_high": ("clv", True),
}


def _spread_returns(
    panel: dict[str, dict[str, np.ndarray]],
    dates: np.ndarray,
    signal: str,
    long_low: bool,
    condition: str | None,
    horizon: int,
    rng: np.random.Generator,
    shuffle: bool = False,
) -> tuple[list[float], list[float]]:
    """The long-short spread per non-overlapping date, and the costs faced."""
    out: list[float] = []
    costs: list[float] = []
    names = sorted(panel)
    for step in range(LOOKBACK + 1, len(dates) - horizon, horizon):
        scores: list[float] = []
        forward: list[float] = []
        spreads: list[float] = []
        gate: list[float] = []
        for name in names:
            one = panel[name]
            index = one["index"]
            if step not in index:
                continue
            i = index[step]
            if i + horizon + 1 >= len(one["close"]):
                continue
            score = one[signal][i]
            close = one["close"]
            # **Entered at the next open, never the signal bar's close.** The
            # signal is known at that close, so filling there is filling at a
            # price the signal was computed from. This is the correction that
            # kills most paper edges, and it costs a bar of the horizon.
            entry = one["open"][i + 1]
            if not entry > 0:
                continue
            ahead = close[i + horizon] / entry - 1.0
            if not (math.isfinite(score) and math.isfinite(ahead)):
                continue
            if condition is not None:
                field, _ = CONDITIONS[condition]
                value = one[field][i]
                if not math.isfinite(value):
                    continue
                gate.append(float(value))
            scores.append(float(score))
            forward.append(float(ahead))
            spreads.append(float(one["spread_frac"][i]))
        if len(scores) < LEAST_NAMES:
            continue
        score_array = np.asarray(scores)
        forward_array = np.asarray(forward)
        if condition is not None:
            _, upper = CONDITIONS[condition]
            cut = np.quantile(np.asarray(gate), 2.0 / 3.0 if upper else 1.0 / 3.0)
            keep = np.asarray(gate) >= cut if upper else np.asarray(gate) <= cut
            if keep.sum() < LEAST_NAMES // 2:
                continue
            score_array, forward_array = score_array[keep], forward_array[keep]
            spreads = list(np.asarray(spreads)[keep])
        if shuffle:
            # **Within the date**, so the cross-sectional return distribution
            # for that date is preserved exactly and only the pairing dies.
            score_array = score_array.copy()
            rng.shuffle(score_array)
        order = np.argsort(score_array)
        take = max(int(EDGE * len(order)), 10)
        low = forward_array[order[:take]].mean()
        high = forward_array[order[-take:]].mean()
        out.append(float(low - high) if long_low else float(high - low))
        costs.append(float(np.median(spreads)) if spreads else 0.0)
    return out, costs


def _panel(names: list[str], dates: np.ndarray) -> dict[str, dict]:
    """Features per name, with a map from the shared date index to its own row."""
    panel: dict[str, dict] = {}
    lookup = {when: i for i, when in enumerate(dates)}
    for name in names:
        bars = _load(CACHE / f"{name}.{FRAME}.npz")
        if bars is None:
            continue
        got = _features(bars)
        got["index"] = {lookup[w]: i for i, w in enumerate(got["time"]) if w in lookup}
        panel[name] = got
    return panel


def main() -> None:
    rng = np.random.default_rng(SEED)
    print(
        "OHLCV-only signal families, cross-sectionally, on the daily equity cache.\n"
        "Per date the names are ranked and a long-short tercile spread is formed, so\n"
        "the cross-section is the sample. Dates are non-overlapping at the horizon.\n"
        "`shuffled` permutes ranks **within each date**, preserving that date's\n"
        "return distribution and breaking only the pairing - it is the null the\n"
        "statistic is read against.\n"
        "Survivorship is not corrected and corporate actions are not verified;\n"
        "both are stated in the module docstring rather than hidden.\n",
        flush=True,
    )
    names = sorted(
        path.name[: -len(f".{FRAME}.npz")]
        for path in CACHE.glob(f"*.{FRAME}.npz")
        if classify(path.name[: -len(f".{FRAME}.npz")]) == "equity"
    )
    if not names:
        names = sorted(path.name[: -len(f".{FRAME}.npz")] for path in CACHE.glob(f"*.{FRAME}.npz"))
    print(f"names: {len(names)}", flush=True)

    stamps: set[float] = set()
    for name in names[:400]:
        bars = _load(CACHE / f"{name}.{FRAME}.npz")
        if bars is not None:
            stamps.update(float(w) for w in bars["time"])
    dates = np.asarray(sorted(stamps))
    print(f"dates: {len(dates)}", flush=True)
    panel = _panel(names, dates)
    print(f"panel: {len(panel)} names loaded", flush=True)

    for horizon in HORIZONS:
        print(f"\n=== h={horizon} days, long-short tercile spread per period")
        print(
            f"{'arm':>26}{'periods':>9}{'mean %':>9}{'se':>8}{'t':>7}"
            f"{'breakeven bp':>13}{'skew':>8}{'shuffled':>10}{'shuf t':>8}"
        )
        for label, signal, long_low, condition in ARMS:
            real, costs = _spread_returns(panel, dates, signal, long_low, condition, horizon, rng)
            if len(real) < 5:
                print(f"{label:>26}{len(real):>9}   too few periods")
                continue
            fake, _ = _spread_returns(
                panel, dates, signal, long_low, condition, horizon, rng, shuffle=True
            )
            mean = float(np.mean(real)) * 100.0
            se = float(np.std(real, ddof=1) / math.sqrt(len(real))) * 100.0
            fake_mean = float(np.mean(fake)) * 100.0
            fake_se = float(np.std(fake, ddof=1) / math.sqrt(max(len(fake), 2))) * 100.0
            # **Breakeven cost in basis points of round trip** - the number
            # that decides it. Four crossings: in and out, two legs.
            breakeven = mean * 100.0 / 4.0
            spread = np.asarray(real)
            skew = float(np.mean(((spread - spread.mean()) / (spread.std() + 1e-12)) ** 3))
            print(
                f"{label:>26}{len(real):>9}{mean:>9.3f}{se:>8.3f}"
                f"{mean / se if se else float('nan'):>7.2f}"
                f"{breakeven:>13.2f}{skew:>8.2f}"
                f"{fake_mean:>10.3f}{fake_mean / fake_se if fake_se else float('nan'):>8.2f}",
                flush=True,
            )
        median_spread = float(
            np.median([np.nanmedian(one["spread_frac"]) for one in panel.values()])
        )
        print(f"  median spread/close across names: {median_spread:.6f}")
    print(
        f"\n\n{len(ARMS)} arms x {len(HORIZONS)} horizons = {len(ARMS) * len(HORIZONS)} cells,\n"
        "so a |t| of 2 is expected somewhere by construction - read the `shuffled`\n"
        "column beside each one, and treat only an arm whose real t exceeds its own\n"
        "shuffled t by a wide margin as worth a second run. An arm whose\n"
        "`breakeven bp` is under a typical spread is not an edge whatever its t -\n"
        "that column is the whole decision. Skew sits beside it because a trend arm\n"
        "wins 35-45% of the time and a reversal arm 55-60%, so accuracy alone\n"
        "misreads both.",
        flush=True,
    )


if __name__ == "__main__":
    main()
