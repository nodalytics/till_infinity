"""Turn the fetched candle files into a supervised matrix that cannot leak.

This is the shared dataset for `sk_batch.py` and `tf_batch.py`. It is written
defensively, because every one of the guards below exists for a mistake this
research has already made and paid for:

**A label must look into the future - that is what makes this supervised.** The
label here is deliberately computed from bars the model will not see, `horizon`
bars ahead, and there is no way to learn a forward question without doing that.
So "leakage" never means "the label looked forward". It means exactly two things,
and both are guarded:

1. forward information reached a **feature**, and
2. one row's forward window straddled a train/test boundary, so the test period
   was partly visible while training. That is what the purge and the embargo in
   `splits.py` are for - a plain date cut does not fix it, because the last
   `horizon` training rows are labelled from bars inside the test period.

With that said, the specific guards:

* **The label's own ingredients are never features.** A forward return was once
  left in a feature table and produced an AUC of 1.000. Single-feature AUC did
  not catch it, because a *signed* return against an *absolute-magnitude* target
  is not monotonic, and AUC only sees monotonic relationships. So the fix is
  structural: features are built from bars `<= t`, the label from bars `> t`,
  by separate functions that never see each other's window.

* **Nothing carries a price unit.** A race between volatility estimators once
  put price-unit and dimensionless estimators against a price-unit target, and
  every correlation came back near 0.57 because they were all tracking the drift
  in the price level. Normalising collapsed them to ~0.30 and reordered the
  ranking. Every feature here is a ratio, a count or a z-score.

* **Instruments are a group, not a pooled blur.** Daily-to-monthly momentum
  passed clustered errors, parameter robustness, a synthetic control and a
  shuffled null, and was still just bitcoin. Only leave-one-group-out caught it,
  so `groups` ships with the matrix and both trainers are expected to use it.

* **Bars are not trusted to be bars.** Yahoo reports a close outside the bar's
  own high/low on up to 6% of rows for some instruments. `read` widens the range
  to contain open and close - the minimal repair, since a close outside the range
  means the *range* was misreported - and counts every repair. Anything that
  depends on a bar's extremes must check `repairs` before believing itself.

## The label is chosen, not assumed

`labels.py` holds six families and this module does not prefer any of them:

| family      | the question it asks                                  |
|-------------|-------------------------------------------------------|
| `banded`    | up, flat or down by `band` true ranges, close to close |
| `triple`    | a target, a stop and a clock - what the desk does      |
| `speed`     | how fast a move of that size arrives, unsigned         |
| `expansion` | is volatility about to expand, hold or contract        |
| `regime`    | is the next stretch trending, reverting or neither     |
| `seasonal`  | the move net of what the calendar already explains     |

The band is set in units of the instrument's own EWMA true range rather than in
basis points, so one threshold means the same thing on gold and on the yen. Every
family reports a majority-class share, and that is the number to read first: a
model that cannot beat "always say the majority" has found nothing at all.
"""

from __future__ import annotations

import csv
import gzip
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

#: Wilder's smoothing for true range, the same constant the live desk sizes from
#: (`structures/vol/ranges.py`). Kept identical so research and production are
#: reading the same quantity and a result here means something there.
TR_ALPHA = 1.0 / 14.0

#: Lookbacks for the return features, in bars.
SPANS = (1, 2, 3, 5, 10, 20, 60)

#: Bars of history a row needs before its features are all defined. The longest
#: span plus room for the EWMA to settle.
WARMUP = 120

#: A candle counts as showing intent when its body is this many times the
#: prevailing true range. The operator's rule: a run of same-coloured candles is
#: only volatility-as-direction if at least one of them is long.
INTENT = 1.0

#: Shortest run of same-coloured candles that counts as consistent.
RUN_MIN = 2


@dataclass
class Panel:
    """A supervised matrix plus everything needed to split it honestly."""

    x: np.ndarray
    y: np.ndarray
    #: Forward return of each row, for scoring what a decision would have made.
    ret: np.ndarray
    #: Instrument name per row, for leave-one-group-out.
    groups: np.ndarray
    #: Bar timestamp per row, for walk-forward ordering and embargo.
    when: np.ndarray
    names: list[str] = field(default_factory=list)
    #: Repaired-bar count per instrument, so extremes-based work can refuse.
    repairs: dict[str, int] = field(default_factory=dict)
    #: Class names in label order, so a confusion matrix can be read.
    classes: list[str] = field(default_factory=list)
    #: Which family produced `y`, and the horizon it looked ahead.
    family: str = ""
    horizon: int = 0

    def __len__(self) -> int:
        return len(self.y)

    @property
    def majority(self) -> float:
        """The share of the biggest class - the score any model has to beat."""
        if not len(self.y):
            return 0.0
        return float(np.bincount(self.y).max()) / len(self.y)

    @property
    def order(self) -> np.ndarray:
        """Row indices in time order, which is the only order allowed to train."""
        return np.argsort(self.when, kind="stable")


def read(path: Path) -> tuple[np.ndarray, int]:
    """Bars as an (n, 5) array of ts/o/h/l/c, and how many needed repair."""
    rows: list[tuple[float, ...]] = []
    repaired = 0
    with gzip.open(path, "rt", newline="") as fh:
        for row in csv.DictReader(fh):
            try:
                ts = float(row["ts"])
                o, h, low, c = (
                    float(row["open"]),
                    float(row["high"]),
                    float(row["low"]),
                    float(row["close"]),
                )
            except (KeyError, ValueError, TypeError):
                continue
            if min(o, h, low, c) <= 0 or not all(math.isfinite(v) for v in (o, h, low, c)):
                continue
            wide_h, wide_l = max(h, o, c), min(low, o, c)
            if wide_h != h or wide_l != low:
                repaired += 1
                h, low = wide_h, wide_l
            rows.append((ts, o, h, low, c))
    rows.sort()
    return np.array(rows, dtype=float), repaired


def true_range(bars: np.ndarray) -> np.ndarray:
    """EWMA of true range as a fraction of close - dimensionless, causal.

    `tr[i]` uses bars up to and including `i`, which is what a decision at the
    close of bar `i` is allowed to know.
    """
    high, low, close = bars[:, 2], bars[:, 3], bars[:, 4]
    prev = np.concatenate(([close[0]], close[:-1]))
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev), np.abs(low - prev)))
    out = np.empty(len(tr))
    running = tr[0]
    for i, value in enumerate(tr):
        running += TR_ALPHA * (value - running)
        out[i] = running
    return out / np.maximum(close, 1e-12)


def consistency(bars: np.ndarray, tr: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The operator's reading of volatility: clean movement in one direction.

    Returns the signed run length of same-coloured candles ending at each bar,
    and whether that run contains a candle whose body is at least `INTENT` true
    ranges - the "long candle that signifies strong intent". A run without one is
    drift, not intent, which is the distinction the rule is making.

    Measured on real instruments at 1.17x forward movement, and at nothing on
    synthetics, which is the pattern a real effect leaves.
    """
    opens, closes = bars[:, 1], bars[:, 4]
    body = closes - opens
    colour = np.sign(body)
    run = np.zeros(len(bars))
    strong = np.zeros(len(bars))
    length = 0
    seen = False
    for i in range(len(bars)):
        long_enough = abs(body[i]) >= INTENT * tr[i] * max(closes[i], 1e-12)
        if i and colour[i] != 0 and colour[i] == colour[i - 1]:
            length += 1
            seen = seen or long_enough
        else:
            length = 1
            seen = long_enough
        run[i] = length * colour[i]
        strong[i] = 1.0 if (seen and length >= RUN_MIN) else 0.0
    return run, strong


def features(bars: np.ndarray, tr: np.ndarray, at: int) -> list[float]:
    """Everything knowable at the close of bar `at`, and nothing else.

    Indexing is the whole discipline here: every slice ends at `at` inclusive.
    """
    close = bars[:, 4]
    here = close[at]
    out: list[float] = []

    # Returns over several lookbacks, in true-range units so a move means the
    # same thing across instruments and across decades of changing price level.
    scale = max(tr[at], 1e-9)
    for span in SPANS:
        was = close[at - span]
        out.append(math.log(here / was) / scale if was > 0 else 0.0)

    # Where volatility sits against its own recent history - the desk's "regime".
    recent, older = tr[at - 20 : at + 1].mean(), tr[at - 60 : at + 1].mean()
    out.append(recent / older if older > 0 else 1.0)
    out.append(math.log(max(tr[at], 1e-9) / max(older, 1e-9)))

    # Where the close sits inside its own recent range, 0 at the low, 1 at the high.
    for span in (10, 20, 60):
        window = bars[at - span : at + 1]
        top, bottom = window[:, 2].max(), window[:, 3].min()
        out.append((here - bottom) / (top - bottom) if top > bottom else 0.5)

    # Body and wicks as fractions of the bar, which is the candle's shape without
    # its size - the part a shape model is supposed to read.
    o, h, low = bars[at, 1], bars[at, 2], bars[at, 3]
    reach = max(h - low, 1e-12)
    out.append((here - o) / reach)
    out.append((h - max(o, here)) / reach)
    out.append((min(o, here) - low) / reach)
    out.append((h - low) / max(here * max(tr[at], 1e-9), 1e-12))

    return out


FEATURE_NAMES = (
    [f"ret_{s}_tr" for s in SPANS]
    + ["vol_ratio_20_60", "vol_log_gap"]
    + [f"range_pos_{s}" for s in (10, 20, 60)]
    + ["body_frac", "upper_wick", "lower_wick", "range_over_tr"]
    + ["run_signed", "run_has_intent", "dow", "month"]
)


def build(
    paths: list[Path],
    family: str = "banded",
    horizon: int = 5,
    band: float = 1.0,
    *,
    verbose: bool = True,
) -> Panel:
    """Assemble the panel from candle files, one group per file.

    The features and the label are produced by separate calls that never share a
    window: `features` indexes `<= at`, the family indexes `> at`. That is the
    structural guard, and it is worth more than any amount of checking afterwards.
    """
    import datetime as dt

    from labels import FAMILIES, NEEDS_EXTREMES

    make = FAMILIES.get(family)
    if make is None:
        raise SystemExit(f"no such label family: {family}. Have {', '.join(sorted(FAMILIES))}")

    xs: list[list[float]] = []
    ys: list[int] = []
    rets: list[float] = []
    groups: list[str] = []
    whens: list[float] = []
    repairs: dict[str, int] = {}
    classes: list[str] = []

    for path in sorted(paths):
        name = path.name.split("_")[0]
        bars, repaired = read(path)
        if len(bars) < WARMUP + horizon + 1:
            if verbose:
                print(f"  {name:<10} only {len(bars)} bars, skipped")
            continue
        repairs[name] = repaired
        tr = true_range(bars)
        run, strong = consistency(bars, tr)
        y, ret, valid, names = make(bars, tr, horizon, band)
        classes = classes or list(names)

        kept = 0
        for at in range(WARMUP, len(bars) - horizon):
            if not valid[at]:
                continue
            row = features(bars, tr, at)
            stamp = dt.datetime.fromtimestamp(bars[at, 0], dt.UTC)
            row += [run[at], strong[at], float(stamp.weekday()), float(stamp.month)]
            if not all(math.isfinite(v) for v in row):
                continue
            xs.append(row)
            ys.append(int(y[at]))
            rets.append(float(ret[at]))
            groups.append(name)
            whens.append(bars[at, 0])
            kept += 1
        if verbose:
            share = 100.0 * repaired / max(len(bars), 1)
            flag = (
                "  <- extremes repaired, and this family reads them"
                if (repaired and family in NEEDS_EXTREMES)
                else ""
            )
            print(f"  {name:<12} {kept:>7} rows  {repaired:>5} repaired ({share:.1f}%){flag}")

    if not xs:
        # An empty panel is nearly always a family whose question is not defined
        # at this horizon - `regime` needs enough forward bars for a variance
        # ratio to mean anything - and the old failure was an IndexError three
        # frames away from the reason.
        print(
            f"  no usable rows for family={family} at horizon={horizon}. "
            "Some families need a longer horizon than others; `regime` needs at "
            "least 8 bars ahead."
        )
        return Panel(
            x=np.zeros((0, len(FEATURE_NAMES)), dtype=np.float32),
            y=np.zeros(0, dtype=np.int64),
            ret=np.zeros(0),
            groups=np.array([], dtype=object),
            when=np.zeros(0),
            names=list(FEATURE_NAMES),
            repairs=repairs,
            classes=classes,
            family=family,
            horizon=horizon,
        )

    panel = Panel(
        x=np.array(xs, dtype=np.float32),
        y=np.array(ys, dtype=np.int64),
        ret=np.array(rets, dtype=np.float64),
        groups=np.array(groups),
        when=np.array(whens, dtype=np.float64),
        names=list(FEATURE_NAMES),
        repairs=repairs,
        classes=classes,
        family=family,
        horizon=horizon,
    )
    if panel.x.shape[1] != len(FEATURE_NAMES):
        raise AssertionError(
            f"{panel.x.shape[1]} columns against {len(FEATURE_NAMES)} names - "
            "a feature was added without naming it"
        )
    return panel


#: Bars in a sequence window for the convolutional model.
WINDOW = 32


def sequences(
    paths: list[Path], family: str = "banded", horizon: int = 5, band: float = 1.0
) -> tuple[np.ndarray, Panel]:
    """Windows of raw candle shape, aligned row-for-row with `build`'s panel.

    Shape `(rows, WINDOW, 4)`: open, high, low and close for the last `WINDOW`
    bars, each expressed as a multiple of the window's own last close and then
    divided by the prevailing true range. That double normalisation is the point.

    **A convolution over raw prices learns the price level, not the shape.** Gold
    at 400 and gold at 4,300 are the same instrument and the same patterns, and a
    network fed absolute prices spends its capacity discovering which decade it is
    looking at - the same units artifact that once made every volatility estimator
    here correlate at 0.57 because they were all tracking drift. Dividing by the
    last close removes the level; dividing by true range removes the scale, so a
    quiet week and a violent one with the same geometry look alike.

    This is the honest version of the candlestick-image idea: the shape, without
    the axes.
    """
    panel = build(paths, family=family, horizon=horizon, band=band, verbose=False)
    by_name: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for path in sorted(paths):
        name = path.name.split("_")[0]
        bars, _repaired = read(path)
        if len(bars) >= WARMUP + horizon + 1:
            by_name[name] = (bars, true_range(bars))

    out = np.zeros((len(panel), WINDOW, 4), dtype=np.float32)
    for row, (name, stamp) in enumerate(zip(panel.groups, panel.when, strict=True)):
        found = by_name.get(str(name))
        if found is None:
            continue
        bars, tr = found
        at = int(np.searchsorted(bars[:, 0], stamp))
        if at < WINDOW or at >= len(bars):
            continue
        window = bars[at - WINDOW + 1 : at + 1, 1:5]
        last = bars[at, 4]
        scale = max(tr[at] * last, 1e-9)
        out[row] = ((window - last) / scale).astype(np.float32)
    return out, panel


def find(where: str = ".secrets", interval: str = "1d") -> list[Path]:
    """Candle files for one interval. `_derived` files are included as-is."""
    return sorted(Path(where).glob(f"*_{interval}*.csv.gz"))
