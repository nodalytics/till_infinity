"""`VI_M15_imp_H4sq` as a trade: a 15m impulse out of a 4h squeeze, held 4h.

    ./.secrets/lab.sh run research/harness/vol_impulse.py \
        SEQLAB=$HOME/till_infinity/data/seqlab \
        FAST=$HOME/till_infinity/data/fast \
        OUT=$HOME/till_infinity/out/vol_impulse

## The claim, and the part of it that is already answered

`impulse-vol.md` measured this conditioning as a **conditional mean** over the
same panel and reported that *"the multi-timeframe version adds nothing: a 4h
squeeze plus a 15m impulse reads +0.225 where no condition at all reads
+0.226"*. That sentence is about the **volatility** channel. On the direction
channel the same study read the headline cell of USDCAD at -0.228 of a forecast
unit - a *reversion*, against the continuation this rule takes - with its
interval containing its own round trip, and `trigger-expectancy.md` read the
signed continuation at trigger 3.0 over 12 bars at **-0.069** pooled with 0 of
6 instruments clearing cost.

So the direction reading is not open. What neither study did is the trade, and
both say so in the same words: *"There is no stop, no target and no fill model,
so the `P(>= N R)` against `1/(1+N)` that this desk leads with is not
computed."* This harness is that: a fill at the next bar's **open** paying the
quoted spread, a time exit, one position at a time, and R denominated in the
trigger. Four things change from a conditional mean, and each can move a number
on its own - the fill price, the non-overlap, the cost in R, and a risk unit
that is the *trigger* rather than a forecast unit.

**The detector is the production one.** `till_infinity.strategies.volimpulse`
holds the fold, the frozen HAR and the squeeze, and this file imports them
rather than reimplementing them, including for the null arms: the arm that
decides the rule's central claim - the squeeze removed - is
`Fold(require_squeeze=False)`, the same object. A harness that reimplemented
the rule would be measuring the reimplementation.

## The arms

| arm | what it changes | what it is for |
|---|---|---|
| `real` | nothing | the rule |
| `coin` | the side, drawn at random | does the side carry anything the dates and the cost do not |
| `stale8` | the fill is 8 bars late | is the information specific to the moment |
| `random` | the entry bar, drawn at the same count and the same hour histogram | is it being in the market at those times |
| `nosqueeze` | `require_squeeze=False` | **the rule's central claim**: does the slow leg contribute |
| `expansion` | the impulses the squeeze **refused** | the duty-cycle-free half of that claim: `nosqueeze` trades 4-5x as often as `real`, and on a losing book any rule that trades less looks better, so the comparison that carries information is squeeze against not-squeeze at whatever count each produces |
| `rawrange` | the squeeze ranks the unadjusted range | the specification's own ambiguity |
| `flip` | every return's sign randomised, the magnitude path kept exactly | the calibrated direction null `impulse-vol.md` uses |
| `har_early` | the HAR fitted before 2019 instead of before 2026-02 | the rule freezes the model *after* most of the sample, so the denominator that picks the events has seen the future |

`nosqueeze` fires about five times as often, so its non-overlap binds harder;
the kept-trade count is printed for every arm because a duty cycle that differs
is a confound and not a result.

## What is charged, and what is not

Cost is **one quoted spread** per round trip - a buy enters at the ask and
exits at the bid - taken from the terminal's quote on 2026-11-05 and never from
the per-bar `spread` column, which is zero on 7-35% of bars here and whose
median runs three to eight times below the quote. `impulse-vol.md` records that
every direction cell in that study is profitable at the column's number and
almost none at the quote's. Slippage, commission and swap are **not** charged,
so every net number here is optimistic by those three.

## What a null here would and would not mean

`1R` is the trigger, so a mean of zero before cost is the whole of the null
hypothesis and `1/(1+N)` has no role: there is no stop, so there is no barrier
race. The quantity to beat is `mean R > cost in R`, and that cost is printed
beside every row because on a 15-minute book it is the larger term:
`vol-gate.md`'s own rule is that *"an idea whose edge is smaller than the
difference between"* 0.20R in the quietest volatility quintile and 0.08R in the
busiest *"is an idea about costs"*.
"""

from __future__ import annotations

import os
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

sys.path.insert(0, os.environ.get("REPO", os.path.expanduser("~/till_infinity/repo")))

from till_infinity.strategies.volimpulse import (  # noqa: E402
    HAR_LAGS,
    HOLD_BARS,
    IMPULSE_MULT,
    SQUEEZE_ATR,
    SQUEEZE_BINS,
    SQUEEZE_SHARE,
    SQUEEZE_WINDOW,
    Fold,
    Har,
    VolImpulseProfile,
)

SEQLAB = os.environ.get("SEQLAB", os.path.expanduser("~/till_infinity/data/seqlab"))
FAST = os.environ.get("FAST", os.path.expanduser("~/till_infinity/data/fast"))
OUT = os.environ.get("OUT", "vol_impulse")
WORKERS = int(os.environ.get("WORKERS", "10"))

#: The five markets the rule names.
MARKETS = ("EURUSD", "USDJPY", "GBPUSD", "USDCAD", "XAUUSD")

#: `point` per symbol, from the bridge's `symbols/info` on 2026-11-05, as
#: `impulse_vol.py` recorded them. The spread column is in **points**, not
#: price: `price = points * point`, and reading it as price once put a 476%
#: round trip on EURUSD.
POINT = {"EURUSD": 1e-05, "GBPUSD": 1e-05, "USDJPY": 0.001, "USDCAD": 1e-05, "XAUUSD": 0.01}
#: The spread the terminal **quoted** on 2026-11-05, in points.
SPREAD_POINTS = {"EURUSD": 9, "GBPUSD": 11, "USDJPY": 9, "USDCAD": 10, "XAUUSD": 16}

#: The rule's own freeze: the HAR sees nothing at or after this.
FREEZE = pd.Timestamp("2026-02-01", tz="UTC").value // 10**9
#: The freeze the causality arm uses instead, so that 7 of the 11.8 years are
#: scored by a model that could not have seen them.
EARLY = pd.Timestamp("2019-01-01", tz="UTC").value // 10**9
#: The discovery / confirmation boundary, fixed before the grid was read.
SPLIT = pd.Timestamp("2021-01-01", tz="UTC").value // 10**9

#: The cost gate, which is the desk's one measured limit: a round trip may not
#: exceed this share of the risk, and here the risk is the trigger.
COST_SHARE = VolImpulseProfile.cost_share
CUT_HOURS = set(VolImpulseProfile.no_fill_hours)

#: Draws for the surrogate arms, resamples for the day-block bootstrap, and the
#: interval. A day block because impulses cluster in days and the hold is 16
#: bars - a block has to be at least the hold or the resample breaks a trade in
#: half, and 96 bars of 15 minutes is a day.
NDRAW = 200
BOOT = 2_000
ALPHA = 0.10
SEED = 20261108

#: Planted drift sizes for the power sweep, in units of 1R.
PLANTED = (0.0, 0.02, 0.05, 0.10, 0.20)

ARMS = (
    "real",
    "coin",
    "stale8",
    "random",
    "nosqueeze",
    "expansion",
    "rawrange",
    "flip",
    "har_early",
)
#: How late the stale arm fills. The signal is unchanged and the entry is this
#: many bars after the one the rule names, so the arm asks whether the
#: information belongs to the moment or to the day.
STALE = 8


def bars(symbol: str, root: str = SEQLAB, interval: str = "15m") -> pd.DataFrame:
    """One instrument's bars, oldest first, de-duplicated on the stamp.

    `high` and `low` are widened to contain the open and the close, which is
    the contract this venue's stored bars are known to break on a handful of
    rows.
    """
    z = np.load(f"{root}/{symbol}.{interval}.npz")
    df = pd.DataFrame(
        {
            "ts": z["time"].astype(np.int64),
            "open": z["open"].astype(float),
            "high": z["high"].astype(float),
            "low": z["low"].astype(float),
            "close": z["close"].astype(float),
        }
    )
    df = df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    df["high"] = df[["open", "high", "close"]].max(axis=1)
    df["low"] = df[["open", "low", "close"]].min(axis=1)
    return df


def fifteens(symbol: str) -> pd.DataFrame | None:
    """M1 bars from `data/fast` folded onto 15-minute calendar bins.

    Only for the live-trade check: the fast cache is 20,000 minutes, about two
    weeks, which is a fiftieth of what the squeeze window alone needs - so this
    is spliced onto the end of the seqlab series rather than used on its own.
    """
    try:
        z = np.load(f"{FAST}/{symbol}.1m.npz")
    except FileNotFoundError:
        return None
    df = pd.DataFrame(
        {
            "ts": z["time"].astype(np.int64),
            "open": z["open"].astype(float),
            "high": z["high"].astype(float),
            "low": z["low"].astype(float),
            "close": z["close"].astype(float),
            # Points, not price, and kept because the **minute** cache's column
            # is informative where the 15-minute one is not: on USDCAD it reads
            # a median of 3 points and a maximum of 151, against 35% exact
            # zeros on the 15-minute series.
            "spread": z["spread"].astype(float) if "spread" in z.files else 0.0,
        }
    ).drop_duplicates("ts")
    df["bin"] = df.ts // 900 * 900
    out = df.groupby("bin").agg(
        ts=("bin", "first"),
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        spread=("spread", "max"),
        rows=("close", "size"),
    )
    # **A bin with fewer than fifteen minutes is still a bar, and dropping one
    # loses exactly the bar that matters.** The first version of this required
    # all fifteen, and the one bin it removed on USDCAD was
    # 2026-11-06 03:00 UTC - the bar the live trade was taken on, which is
    # short *because* 03:00-03:04 are missing from the broker's own minute
    # history and the spread at 03:05 is 151 points against a 10-point quote.
    # A minute with no tick produces no M1 bar, so a short bin is an absence of
    # trading and not an absence of data. 14 of 1,339 bins are short here.
    #
    # The final bin is dropped whatever its length: the cache ends mid-bin and
    # that one is incomplete by the clock rather than by the market.
    return out[out.index < out.index.max()].drop(columns="rows").reset_index(drop=True)


# ----------------------------------------------------------------- the HAR fit


@dataclass(frozen=True, slots=True)
class Fit:
    """A frozen HAR and the sample it was frozen on."""

    har: Har
    rows: int
    r2: float
    until: int


def components(r: np.ndarray, lags: tuple[int, ...] = HAR_LAGS) -> np.ndarray:
    """Mean `|r|` over each lag, **ending at the bar before** each row.

    Shifted, so a forecast never sees its own bar. `impulse-vol.md`'s own
    forecast is shifted for the same reason and the repo's HAR arm in
    `vol_gate.py` is not - because there the target is forward volatility and
    here it is the bar itself.
    """
    absolute = pd.Series(np.abs(r))
    return np.column_stack(
        [absolute.rolling(lag).mean().shift(1).to_numpy() for lag in lags]
    )


def forecast(r: np.ndarray, har: Har) -> np.ndarray:
    """The frozen HAR's forecast for every bar, from the bars before it.

    The same arithmetic `Har.forecast` does one bar at a time, vectorised, so
    an arm that needs a risk unit on a bar the rule did not pick gets the
    rule's unit rather than a constant. A constant was the first version and it
    made the random arm's cost gate refuse nothing, which is a duty-cycle
    difference wearing a result's clothes.
    """
    eps = 1e-12
    x = np.log(components(r, har.lags) + eps)
    total = har.const + x @ np.array(har.weights)
    return har.scale * np.exp(total)


def fit_har(ts: np.ndarray, r: np.ndarray, until: int) -> Fit:
    """OLS of `log|r|` on the log components, on bars before `until`.

    The **smearing** factor is part of the model and not a cosmetic: a fit on
    `log|r|` exponentiates to a forecast of the geometric mean, which runs low,
    and a trigger divided by a low forecast fires too often. `vol_gate.py` uses
    `mean(exp(y - pred))` on its own fitting rows and this is the same
    correction, applied so that `mean(|r|) / mean(sigma)` is 1 on the fit.
    """
    eps = 1e-12
    x = np.log(components(r) + eps)
    y = np.log(np.abs(r) + eps)
    rows = np.isfinite(y) & np.isfinite(x).all(axis=1) & (ts < until) & (np.abs(r) > 0)
    design = np.column_stack([np.ones(rows.sum()), x[rows]])
    beta, *_ = np.linalg.lstsq(design, y[rows], rcond=None)
    pred = design @ beta
    scale = float(np.mean(np.exp(y[rows] - pred)))
    resid = y[rows] - pred
    r2 = 1.0 - float(np.var(resid) / np.var(y[rows]))
    return Fit(
        har=Har(
            const=float(beta[0]),
            weights=tuple(float(b) for b in beta[1:]),
            scale=scale,
            lags=HAR_LAGS,
            until=str(pd.Timestamp(until, unit="s", tz="UTC").date()),
        ),
        rows=int(rows.sum()),
        r2=r2,
        until=until,
    )


# ------------------------------------------------------------------ the events


@dataclass(slots=True)
class Events:
    """Every impulse one fold produced, with the fold's own branch counts."""

    at: np.ndarray
    side: np.ndarray
    sigma: np.ndarray
    rank: np.ndarray
    impulse: np.ndarray
    hour: np.ndarray
    counts: dict[str, int]


def detect(df: pd.DataFrame, har: Har, **kwargs: object) -> Events:
    """The production fold over one instrument's bars.

    `kwargs` reach `Fold` untouched, which is how every arm that changes the
    *detector* - the squeeze removed, the raw range - is the same object as the
    rule rather than a copy of it.
    """
    fold = Fold(har=har, **kwargs)  # type: ignore[arg-type]
    rows = df[["ts", "high", "low", "close"]].to_numpy()
    at, side, sigma, rank, impulse, hour = [], [], [], [], [], []
    for index, (ts, high, low, close) in enumerate(rows):
        found = fold.update(int(ts), high, low, close)
        if found is None:
            continue
        at.append(index)
        side.append(found.side.sign)
        sigma.append(found.sigma)
        rank.append(found.rank)
        impulse.append(found.impulse)
        hour.append(found.hour)
    return Events(
        at=np.array(at, dtype=int),
        side=np.array(side, dtype=float),
        sigma=np.array(sigma, dtype=float),
        rank=np.array(rank, dtype=float),
        impulse=np.array(impulse, dtype=float),
        hour=np.array(hour, dtype=int),
        counts=dict(fold.counts),
    )


# ------------------------------------------------------------------ the trades


@dataclass(slots=True)
class Book:
    """One arm's trades, sequential and non-overlapping."""

    at: np.ndarray
    side: np.ndarray
    gross: np.ndarray
    cost: np.ndarray
    day: np.ndarray
    ts: np.ndarray
    hour: np.ndarray
    #: How many events each gate removed, before the book was built.
    gates: dict[str, int]

    @property
    def net(self) -> np.ndarray:
        return self.gross - self.cost


def book(
    df: pd.DataFrame,
    events: Events,
    spread_px: float,
    *,
    late: int = 0,
    sides: np.ndarray | None = None,
    hold: int = HOLD_BARS,
    gate_cost: bool = True,
    gate_hours: bool = True,
) -> Book:
    """Events turned into a sequential book, with every gate counted.

    **One position at a time.** A four-hour hold on a 15-minute trigger
    otherwise counts one outcome up to sixteen times, and the desk itself
    cannot hold two: `Desk._already_held` refuses the instrument across every
    strategy. The slot frees on the bar the clock closes the trade, which is
    what the production `_clock` does before it judges that bar's own event.

    `late` fills `late` bars after the bar the rule names, which is the stale
    arm; `sides` replaces the side, which is the coin arm. Both keep the dates,
    the risk unit and the cost, so what changes is one thing at a time.
    """
    logopen = np.log(df.open.to_numpy(float))
    stamps = df.ts.to_numpy(np.int64)
    n = len(logopen)
    side = events.side if sides is None else sides
    gates = {"events": len(events.at), "cut": 0, "costly": 0, "overlap": 0, "short": 0}
    free = -1
    keep_at, keep_side, keep_gross, keep_cost = [], [], [], []
    for row, index in enumerate(events.at):
        enter, leave = index + 1 + late, index + 1 + late + hold
        if leave >= n:
            gates["short"] += 1
            continue
        if gate_hours and events.hour[row] in CUT_HOURS:
            gates["cut"] += 1
            continue
        risk = IMPULSE_MULT * events.sigma[row]
        cost = spread_px / np.exp(logopen[enter]) / risk
        if gate_cost and cost > COST_SHARE:
            gates["costly"] += 1
            continue
        if index < free:
            gates["overlap"] += 1
            continue
        free = index + 1 + late + hold
        keep_at.append(index)
        keep_side.append(side[row])
        keep_gross.append(side[row] * (logopen[leave] - logopen[enter]) / risk)
        keep_cost.append(cost)
    at = np.array(keep_at, dtype=int)
    ts = stamps[at] if len(at) else np.array([], dtype=np.int64)
    return Book(
        at=at,
        side=np.array(keep_side, dtype=float),
        gross=np.array(keep_gross, dtype=float),
        cost=np.array(keep_cost, dtype=float),
        day=ts // 86_400,
        ts=ts,
        hour=(ts // 3_600 % 24).astype(int) if len(at) else np.array([], dtype=int),
        gates=gates,
    )


# -------------------------------------------------------------- the statistics


def day_block(values: np.ndarray, days: np.ndarray, rng: np.random.Generator) -> tuple[float, float]:
    """A day-block bootstrap interval for the mean.

    Whole days, because impulses cluster in days and a hold of 16 bars sits
    inside one - so a block shorter than the hold would split a trade across
    two resampled blocks and narrow the interval for a reason that is not the
    data. An ordinary standard error on these rows is too narrow.
    """
    if len(values) == 0:
        return float("nan"), float("nan")
    keys, inverse = np.unique(days, return_inverse=True)
    groups = [values[inverse == k] for k in range(len(keys))]
    totals = np.array([g.sum() for g in groups])
    sizes = np.array([len(g) for g in groups])
    draws = rng.integers(0, len(keys), size=(BOOT, len(keys)))
    means = totals[draws].sum(axis=1) / np.maximum(sizes[draws].sum(axis=1), 1)
    return (
        float(np.quantile(means, ALPHA / 2.0)),
        float(np.quantile(means, 1.0 - ALPHA / 2.0)),
    )


def summary(name: str, symbol: str, arm: str, got: Book, rng: np.random.Generator) -> dict:
    """One row: the sample, the mean, its interval, and the cost beside it."""
    net, gross = got.net, got.gross
    lo, hi = day_block(net, got.day, rng)
    first = got.ts < SPLIT
    row = {
        "symbol": symbol,
        "arm": arm,
        "cell": name,
        "n": len(net),
        "mean_net": float(net.mean()) if len(net) else float("nan"),
        "se": float(net.std(ddof=1) / np.sqrt(len(net))) if len(net) > 1 else float("nan"),
        "lo": lo,
        "hi": hi,
        "mean_gross": float(gross.mean()) if len(gross) else float("nan"),
        "cost_r": float(got.cost.mean()) if len(got.cost) else float("nan"),
        "sd": float(net.std(ddof=1)) if len(net) > 1 else float("nan"),
        "win": float((net > 0).mean()) if len(net) else float("nan"),
        # **Lead with the tail.** There is no stop here, so `1/(1+N)` has no
        # role, but the share of trades that reach a further impulse-sized step
        # is still the shape of the distribution rather than its centre, and a
        # mean can be flat while a tail is not.
        "p_ge1": float((net >= 1.0).mean()) if len(net) else float("nan"),
        "p_ge2": float((net >= 2.0).mean()) if len(net) else float("nan"),
        "p_le1": float((net <= -1.0).mean()) if len(net) else float("nan"),
        "n_first": int(first.sum()),
        "mean_first": float(net[first].mean()) if first.any() else float("nan"),
        "n_second": int((~first).sum()),
        "mean_second": float(net[~first].mean()) if (~first).any() else float("nan"),
    }
    row |= {f"gate_{k}": v for k, v in got.gates.items()}
    return row


def one(symbol: str) -> tuple[list[dict], dict, pd.DataFrame]:
    """Every arm on one instrument, its diagnostics, and its trades.

    The trades come back as well as the summaries because **a pooled
    interval is not the average of five intervals**: trades on one day are
    correlated across instruments, so the pooled day-block bootstrap has to
    resample days across the whole panel at once.
    """
    rng = np.random.default_rng(SEED + abs(hash(symbol)) % 10_000)
    df = bars(symbol)
    ts = df.ts.to_numpy(np.int64)
    close = df.close.to_numpy(float)
    r = np.concatenate([[np.nan], np.diff(np.log(close))])
    spread_px = SPREAD_POINTS[symbol] * POINT[symbol]

    frozen = fit_har(ts, r, FREEZE)
    early = fit_har(ts, r, EARLY)
    detector = {
        "bins": SQUEEZE_BINS,
        "window": SQUEEZE_WINDOW,
        "share": SQUEEZE_SHARE,
        "atr_bins": SQUEEZE_ATR,
        "mult": IMPULSE_MULT,
    }
    events = detect(df, frozen.har, **detector)
    rows: list[dict] = []
    note = {
        "symbol": symbol,
        "bars": len(df),
        "from": str(pd.Timestamp(ts[0], unit="s", tz="UTC")),
        "to": str(pd.Timestamp(ts[-1], unit="s", tz="UTC")),
        "spread_px": spread_px,
        "har": frozen.har,
        "har_rows": frozen.rows,
        "har_r2": frozen.r2,
        "har_early": early.har,
        "counts": events.counts,
        "events": len(events.at),
        "hours": np.bincount(events.hour, minlength=24).tolist() if len(events.at) else [],
    }
    if len(events.at) == 0:
        # A zero is a reading and this one would be of nothing: the fold's own
        # branch counts say which stage it died at.
        return rows, note, pd.DataFrame()

    trades: list[pd.DataFrame] = []

    def keep(arm: str, got: Book, cell: str = "headline") -> Book:
        """Summarise one arm and keep its trades for the pooled bootstrap."""
        rows.append(summary(cell, symbol, arm, got, rng))
        if cell == "headline" and len(got.net):
            trades.append(
                pd.DataFrame(
                    {
                        "symbol": symbol,
                        "arm": arm,
                        "ts": got.ts,
                        "day": got.day,
                        "gross": got.gross,
                        "cost": got.cost,
                        "net": got.net,
                    }
                )
            )
        return got

    real = keep("real", book(df, events, spread_px))
    # The ungated books, so the cost gate's and the hour cut's own effects are
    # numbers rather than differences nobody printed.
    keep("real", book(df, events, spread_px, gate_cost=False), cell="uncosted")
    keep("real", book(df, events, spread_px, gate_hours=False), cell="unhoured")

    # `coin`: the same dates, the same risk unit, the same cost, a random side.
    draws = []
    for _ in range(NDRAW):
        sides = rng.choice([-1.0, 1.0], size=len(events.at))
        draws.append(book(df, events, spread_px, sides=sides))
    keep("coin", draws[0])
    note["coin_draws"] = [(len(d.net), float(d.net.mean())) for d in draws if len(d.net)]
    note["coin_mean"] = float(np.mean([m for _, m in note["coin_draws"]]))
    note["coin_sd"] = float(np.std([m for _, m in note["coin_draws"]]))

    keep("stale8", book(df, events, spread_px, late=STALE))

    # `random`: the same number of entries, drawn from the same hour histogram
    # and given the side of their own bar. Hour-matched because the HAR carries
    # no intraday seasonal, so the rule fires where the daily cycle puts the
    # most volatility and an unmatched draw would differ in that as well.
    keep("random", _random_arm(df, events, spread_px, forecast(r, frozen.har), rng))

    opened = detect(df, frozen.har, **(detector | {"require_squeeze": False}))
    keep("nosqueeze", book(df, opened, spread_px))
    note["nosqueeze_counts"] = dict(opened.counts)
    # The complement, which is the comparison with no duty-cycle difference in
    # it: the same detector, the same fills, the impulses the squeeze refused.
    wide = opened.rank > SQUEEZE_SHARE
    keep(
        "expansion",
        book(
            df,
            Events(
                at=opened.at[wide],
                side=opened.side[wide],
                sigma=opened.sigma[wide],
                rank=opened.rank[wide],
                impulse=opened.impulse[wide],
                hour=opened.hour[wide],
                counts=opened.counts,
            ),
            spread_px,
        ),
    )

    raw = detect(df, frozen.har, **(detector | {"raw_range": True}))
    keep("rawrange", book(df, raw, spread_px))

    keep("flip", _flip_arm(df, events, spread_px, rng))
    note["flip_draws"] = [
        (len(b.net), float(b.net.mean()))
        for b in _flip_books(df, events, spread_px, rng, NDRAW)
        if len(b.net)
    ]
    note["flip_mean"] = float(np.mean([m for _, m in note["flip_draws"]]))
    note["flip_sd"] = float(np.std([m for _, m in note["flip_draws"]]))

    late = detect(df, early.har, **detector)
    after = late.at[df.ts.to_numpy(np.int64)[late.at] >= EARLY] if len(late.at) else late.at
    kept = np.isin(late.at, after)
    trimmed = Events(
        at=late.at[kept],
        side=late.side[kept],
        sigma=late.sigma[kept],
        rank=late.rank[kept],
        impulse=late.impulse[kept],
        hour=late.hour[kept],
        counts=late.counts,
    )
    keep("har_early", book(df, trimmed, spread_px))

    # Power, on the real book: a drift of known size in units of 1R, added in
    # the direction the trade took, so the sweep says where the test goes blind.
    note["power"] = {}
    for drift in PLANTED:
        planted = replace(real, gross=real.gross + drift)
        lo, _ = day_block(planted.net, planted.day, rng)
        note["power"][drift] = {"mean": float(planted.net.mean()), "lo": lo, "seen": bool(lo > 0)}
    return rows, note, pd.concat(trades, ignore_index=True)


def _random_arm(
    df: pd.DataFrame,
    events: Events,
    spread_px: float,
    sigmas: np.ndarray,
    rng: np.random.Generator,
) -> Book:
    """The rule's count and hour histogram, at bars the rule did not pick.

    Its side is its own bar's direction, so the arm is "trade the last bar's
    way" at a matched time rather than a coin at a matched time - the coin arm
    is the one that removes the side.
    """
    ts = df.ts.to_numpy(np.int64)
    close = df.close.to_numpy(float)
    r = np.concatenate([[np.nan], np.diff(np.log(close))])
    hour = (ts // 3_600 % 24).astype(int)
    warm = int(events.at.min()) if len(events.at) else 0
    pool = np.arange(warm, len(ts) - HOLD_BARS - 2)
    wanted = np.bincount(events.hour, minlength=24)
    picked: list[int] = []
    for h in range(24):
        if wanted[h] == 0:
            continue
        candidates = pool[hour[pool] == h]
        if len(candidates) == 0:
            continue
        picked.extend(rng.choice(candidates, size=min(wanted[h], len(candidates)), replace=False))
    at = np.sort(np.array(picked, dtype=int))
    sign = np.sign(np.nan_to_num(r[at]))
    sign[sign == 0] = 1.0
    sigma = sigmas[at]
    live = np.isfinite(sigma) & (sigma > 0.0)
    at, sign, sigma = at[live], sign[live], sigma[live]
    arm = Events(
        at=at,
        side=sign,
        sigma=sigma,
        rank=np.zeros(len(at)),
        impulse=np.zeros(len(at)),
        hour=hour[at],
        counts={},
    )
    return book(df, arm, spread_px)


def _flip_arm(df: pd.DataFrame, events: Events, spread_px: float, rng: np.random.Generator) -> Book:
    """One sign-flip draw, as a book, so it prints beside the others."""
    return _flip_books(df, events, spread_px, rng, draws=1)[0]


def _flip_books(
    df: pd.DataFrame, events: Events, spread_px: float, rng: np.random.Generator, draws: int
) -> list[Book]:
    """The sign-flip surrogate: `|q|` in its original order, signs randomised.

    The magnitude path survives exactly - the clustering, the squeeze, the
    expansion - and direction does not, so anything that appears here is
    volatility rather than skill. Applied to the open-to-open series the trade
    is scored on, with the event set and the risk unit held at the real ones,
    which is what makes it one change rather than three.
    """
    logopen = np.log(df.open.to_numpy(float))
    q = np.concatenate([[0.0], np.diff(logopen)])
    out: list[Book] = []
    for _ in range(draws):
        signs = rng.choice([-1.0, 1.0], size=len(q))
        flipped = np.abs(q) * signs
        rebuilt = df.copy()
        rebuilt["open"] = np.exp(logopen[0] + np.cumsum(flipped))
        sides = signs[np.minimum(events.at + 1, len(signs) - 1)]
        out.append(book(rebuilt, events, spread_px, sides=sides))
    return out


# ----------------------------------------------------------------------- print


def live_trade(symbol: str = "USDCAD") -> str:
    """Does the rule fire on the one trade the live desk took?

    Bought USDCAD at 03:00 UTC on 2026-11-06 and exited at 07:00 for +1.87R.
    The seqlab cache ends 2026-11-05 15:30, so the fast M1 cache is folded to
    15 minutes and spliced on: the squeeze needs 125 days of history and the
    fast cache holds two weeks, so neither half can answer this alone.
    """
    base = bars(symbol)
    tail = fifteens(symbol)
    if tail is None or len(tail) == 0:
        return f"{symbol}: no fast cache, so the live trade cannot be checked"
    joined = (
        pd.concat([base, tail[tail.ts > base.ts.max()].drop(columns="spread")], ignore_index=True)
        .drop_duplicates("ts")
        .sort_values("ts")
        .reset_index(drop=True)
    )
    ts = joined.ts.to_numpy(np.int64)
    r = np.concatenate([[np.nan], np.diff(np.log(joined.close.to_numpy(float)))])
    frozen = fit_har(ts, r, FREEZE)
    events = detect(
        joined,
        frozen.har,
        bins=SQUEEZE_BINS,
        window=SQUEEZE_WINDOW,
        share=SQUEEZE_SHARE,
        atr_bins=SQUEEZE_ATR,
        mult=IMPULSE_MULT,
    )
    lines = [
        f"{symbol}: spliced to {pd.Timestamp(ts[-1], unit='s', tz='UTC')}, "
        f"{len(joined)} bars, {len(events.at)} events"
    ]
    want = pd.Timestamp("2026-11-06", tz="UTC").value // 10**9
    near = [
        (i, row)
        for row, i in enumerate(events.at)
        if want - 86_400 <= ts[i] <= want + 2 * 86_400
    ]
    if not near:
        lines.append("  no impulse within a day of the live trade")
    got = book(joined, events, SPREAD_POINTS[symbol] * POINT[symbol])
    for i, row in near:
        lines.append(
            f"  {pd.Timestamp(ts[i], unit='s', tz='UTC')} side {events.side[row]:+.0f} "
            f"impulse {events.impulse[row]:.2f} rank {events.rank[row]:.3f} "
            f"hour {events.hour[row]:02d} "
            f"{'taken' if i in got.at else 'not taken'}"
        )
        if i in got.at:
            k = int(np.where(got.at == i)[0][0])
            lines.append(
                f"    gross {got.gross[k]:+.3f}R cost {got.cost[k]:.3f}R "
                f"net {got.net[k]:+.3f}R"
            )
    return "\n".join(lines)


def pooled(trades: pd.DataFrame, rng: np.random.Generator) -> list[dict]:
    """One row per arm over the whole panel, bootstrapped on shared days.

    The block is a **calendar day across all five instruments**, not a day per
    instrument: a squeeze on the dollar legs is one condition seen five times,
    and resampling instruments independently would treat that as five
    observations. The hold is 16 bars and a day is 96, so no block is shorter
    than a trade.
    """
    out = []
    for arm in ARMS:
        part = trades[trades.arm == arm]
        if part.empty:
            continue
        net = part.net.to_numpy(float)
        lo, hi = day_block(net, part.day.to_numpy(np.int64), rng)
        first = part.ts.to_numpy(np.int64) < SPLIT
        out.append(
            {
                "arm": arm,
                "n": len(net),
                "mean_net": float(net.mean()),
                "se": float(net.std(ddof=1) / np.sqrt(len(net))),
                "lo": lo,
                "hi": hi,
                "mean_gross": float(part.gross.mean()),
                "cost_r": float(part.cost.mean()),
                "sd": float(net.std(ddof=1)),
                "win": float((net > 0).mean()),
                "p_ge1": float((net >= 1.0).mean()),
                "p_ge2": float((net >= 2.0).mean()),
                "mean_first": float(net[first].mean()) if first.any() else float("nan"),
                "mean_second": float(net[~first].mean()) if (~first).any() else float("nan"),
                "n_first": int(first.sum()),
                "n_second": int((~first).sum()),
                "days": int(part.day.nunique()),
            }
        )
    return out


def main() -> None:
    print(f"vol_impulse: {len(MARKETS)} markets, arms {', '.join(ARMS)}", flush=True)
    rows: list[dict] = []
    notes: list[dict] = []
    books: list[pd.DataFrame] = []
    with ProcessPoolExecutor(max_workers=min(WORKERS, len(MARKETS))) as pool:
        for got, note, trades in pool.map(one, MARKETS):
            rows.extend(got)
            notes.append(note)
            if len(trades):
                books.append(trades)
            print(f"  {note['symbol']}: {note['events']} events, {len(got)} rows", flush=True)
    if not rows or not books:
        # The harness that wrote zero cells and exited zero is a defect this
        # repository has already paid for.
        raise SystemExit("no cells: every instrument produced zero events")

    frame = pd.DataFrame(rows)
    frame.to_csv(f"{OUT}.csv", index=False)
    trades = pd.concat(books, ignore_index=True)
    trades.to_csv(f"{OUT}-trades.csv", index=False)

    print("\n== the frozen HAR, for pasting into strategies/volimpulse.py ==")
    for note in notes:
        har = note["har"]
        print(
            f'    "{note["symbol"].lower()}": Har(const={har.const:.6f}, weights=('
            + ", ".join(f"{w:.6f}" for w in har.weights)
            + f'), scale={har.scale:.6f}, until="{har.until}"),'
        )
    print("\n== fit and firing ==")
    for note in notes:
        counts = note["counts"]
        judged = counts["bars"] - counts["cold-return"] - counts["cold-har"] - counts["cold-squeeze"]
        impulses = counts["no-squeeze"] + counts["fired"]
        print(
            f"  {note['symbol']:7s} {note['bars']:7d} bars {note['from'][:10]}..{note['to'][:10]}"
            f"  har rows {note['har_rows']:7d} r2 {note['har_r2']:.3f}"
            f" scale {note['har'].scale:.3f}"
        )
        print(
            f"          judged {judged:7d}  impulses {impulses:6d}"
            f" ({impulses / max(judged, 1) * 100:.3f}% of judged)"
            f"  in a squeeze {counts['fired']:5d}"
            f" ({counts['fired'] / max(impulses, 1) * 100:.1f}% of impulses,"
            f" {counts['fired'] / max(judged, 1) * 100:.3f}% of bars)"
            f"  spread {note['spread_px']:.6g} px"
        )
        print(f"          firings by UTC hour: {note['hours']}")

    print("\n== per instrument, headline cell: mean R net of one quoted spread ==")
    head = frame[frame.cell == "headline"]
    for arm in ARMS:
        part = head[head.arm == arm]
        if part.empty:
            continue
        print(f"\n  -- {arm} --")
        for _, row in part.iterrows():
            print(
                f"  {row.symbol:7s} n {int(row.n):5d}  net {row.mean_net:+.4f}"
                f"  se {row.se:.4f}  [{row.lo:+.4f}, {row.hi:+.4f}]"
                f"  gross {row.mean_gross:+.4f}  cost {row.cost_r:.4f}"
                f"  sd {row.sd:.2f}  win {row.win:.3f}"
                f"  P(>=1R) {row.p_ge1:.3f}  halves {row.mean_first:+.4f} / {row.mean_second:+.4f}"
                f"  ({int(row.n_first)}/{int(row.n_second)})"
            )

    print("\n== pooled over the five markets, day blocks shared across them ==")
    rng = np.random.default_rng(SEED)
    for row in pooled(trades, rng):
        print(
            f"  {row['arm']:10s} n {row['n']:5d} over {row['days']:4d} days"
            f"  net {row['mean_net']:+.4f}  se {row['se']:.4f}"
            f"  [{row['lo']:+.4f}, {row['hi']:+.4f}]"
            f"  gross {row['mean_gross']:+.4f}  cost {row['cost_r']:.4f}"
            f"  sd {row['sd']:.2f}  win {row['win']:.3f}"
            f"  P(>=1R) {row['p_ge1']:.3f} P(>=2R) {row['p_ge2']:.3f}"
            f"  halves {row['mean_first']:+.4f}/{row['mean_second']:+.4f}"
            f" ({row['n_first']}/{row['n_second']})"
        )
    pd.DataFrame(pooled(trades, rng)).to_csv(f"{OUT}-pooled.csv", index=False)

    print("\n== what each gate refused, real arm ==")
    for _, row in head[head.arm == "real"].iterrows():
        total = row.gate_events
        print(
            f"  {row.symbol:7s} events {int(total):5d}"
            f"  cut {int(row.gate_cut):4d} ({row.gate_cut / max(total, 1):.1%})"
            f"  costly {int(row.gate_costly):4d} ({row.gate_costly / max(total, 1):.1%})"
            f"  overlap {int(row.gate_overlap):4d} ({row.gate_overlap / max(total, 1):.1%})"
            f"  short {int(row.gate_short):3d}  taken {int(row.n):4d}"
        )
    print("\n  the same, with the cost gate off and with the hour cut off:")
    for cell in ("uncosted", "unhoured"):
        part = frame[frame.cell == cell]
        for _, row in part.iterrows():
            print(
                f"  {cell:9s} {row.symbol:7s} n {int(row.n):5d}  net {row.mean_net:+.4f}"
                f"  [{row.lo:+.4f}, {row.hi:+.4f}]  cost {row.cost_r:.4f}"
            )

    print("\n== the surrogate spreads, over the draws ==")
    print("  A single surrogate draw is one realisation; these are its own null.")
    for note in notes:
        if "coin_mean" in note:
            print(
                f"  {note['symbol']:7s} coin {note['coin_mean']:+.4f} +- {note['coin_sd']:.4f}"
                f"   flip {note['flip_mean']:+.4f} +- {note['flip_sd']:.4f}"
            )
    for name in ("coin", "flip"):
        per = [note[f"{name}_draws"] for note in notes if f"{name}_draws" in note]
        if not per:
            continue
        width = min(len(rows) for rows in per)
        means = [
            float(np.average([rows[d][1] for rows in per], weights=[rows[d][0] for rows in per]))
            for d in range(width)
        ]
        real_mean = float(trades[trades.arm == "real"].net.mean())
        beat = float(np.mean([m >= real_mean for m in means]))
        print(
            f"  pooled {name:5s} {np.mean(means):+.4f} +- {np.std(means):.4f}"
            f"   the real arm sits at {real_mean:+.4f},"
            f" beaten by {beat:.1%} of {width} draws"
        )

    print("\n== power: a drift planted in units of 1R, on the real book ==")
    print("  Y means the day-block lower bound cleared zero at that plant.")
    for note in notes:
        if "power" not in note:
            continue
        seen = "  ".join(
            f"{d}:{'Y' if note['power'][d]['seen'] else 'n'}({note['power'][d]['lo']:+.3f})"
            for d in PLANTED
        )
        print(f"  {note['symbol']:7s} {seen}")
    print("  pooled:")
    real = trades[trades.arm == "real"]
    for drift in PLANTED:
        lo, hi = day_block(
            real.net.to_numpy(float) + drift, real.day.to_numpy(np.int64), rng
        )
        print(
            f"    {drift}: mean {real.net.mean() + drift:+.4f}  [{lo:+.4f}, {hi:+.4f}]"
            f"  {'seen' if lo > 0 else 'blind'}"
        )

    print("\n== the one live trade ==")
    print(live_trade())
    print(f"\nwrote {OUT}.csv, {OUT}-trades.csv, {OUT}-pooled.csv ({len(frame)} rows)")


if __name__ == "__main__":
    main()
