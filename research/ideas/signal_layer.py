"""Signal = w1*Trend + w2*Momentum + w3*Volatility + w_regime*Regime, as statespace's last layer.

Asked for across several messages on 2026-10-15: the final layer of statespace
should be this weighted signal; most of its terms are already measured here;
Trend should be tested as slopes and EMAs of slopes; and level return rates and
tick-volume velocity should go in beside them. Then: *it looks like the basic
formula for a perceptron?*

**It is one**, and that is the most useful thing about it. `sum(w_i * x_i)` is a
perceptron's pre-activation, missing only a bias and an activation - so three
things follow and all three are tested here rather than assumed:

1. The weights do not have to be hand-tuned. Logistic regression **is** this
   perceptron with a sigmoid and a proper loss, so the fitted weights are the
   ceiling of any hand-tuned set and the comparison is free.
2. Its decision boundary is a hyperplane, so if the terms **interact** no choice
   of weights can express it. A gradient-boosted arm measures how much is left
   on the table by the linear form itself.
3. `w_regime * Regime` is almost certainly the **wrong shape**. A regime is not
   another piece of evidence to add - it says *which other terms to believe*.
   Added, it shifts the score by a constant per regime; what it should do is
   multiply. So the gated form `Regime * (w1*Trend + w2*Momentum) + ...` is run
   beside the additive one, and the difference is the cost of the formula.

## What this is being asked to predict, and the prior

**Direction is closed on this desk and that is measured, not assumed.**
`direction-is-closed-not-just-null` records a gate that finds a planted drift at
z +2.90 and earns 2% of a spread; `statespace-signals.md` records speed as 8.1x
as persistent as signed velocity, with consecutive directions agreeing 49.499%
against 50% +/- 3.102%. So a *directional* reading of this formula is expected
to be a coin, and the only honest way to report that is with a planted drift
beside it showing the test would have seen a real one.

What is **not** closed is magnitude: volatility is forecastable, and every
effect this desk has found has been about size. Both targets are therefore
scored, and the interesting result would be the formula working on one and not
the other.

## Terms, each from a quantity already measured here

* **Trend** - `slope t` (rolling OLS slope over its own standard error), `ema
  gap`, `ema cross`, `ema slope`. The four from `slope_auc.py`, where they were
  measured as a powered null for direction with metals the one coherent thread.
* **Momentum** - the change in that slope over its own error, which is the
  acceleration `linear.py` and `landau.py` carry as a state.
* **Volatility** - the range-to-close estimator ratio, which
  `drive-q-from-the-range` measures at 0.648 within strata on FX, and the
  short-to-long realised ratio.
* **Regime** - the same short-to-long ratio as a regime indicator, used both
  additively and as the gate.
* **Level return** - `recency` to the nearest swing extreme, which
  `weight-return-rate.md` measured as the only one of `strength`'s four terms
  that orders anything (+0.064 of AUC at z 4.44 on swings).
* **Tick velocity** - tick volume against its own trailing mean, and its rate of
  change.

Controls: a block-shuffled twin of the whole feature matrix, the generated
feeds, an out-of-sample split for every fitted arm, and the planted drift.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

CACHE = Path.home() / "till_infinity/data/seqlab"
FRAMES = ("15m", "1h")
LIMIT = 40000
#: Trailing window for every causal feature, in bars.
BACK = 48
#: Forward horizons, in bars.
HORIZONS = (3, 12)
#: Planted **momentum**, as the AR(1) coefficient added to the returns. The
#: power curve for the direction target.
#:
#: The first version added `choice(-1, 1) * drift` and cumulated it, which is a
#: random **walk** rather than a drift - it adds noise, nothing can predict it,
#: and the curve read 0.5135, 0.5135, 0.5132, 0.5131 across planted strengths
#: of 0 to 0.10. A test with a flat power curve has not shown a null, it has
#: shown nothing. Positive autocorrelation in the returns is a directional
#: effect the trend terms can actually find, which is what a power arm has to
#: plant.
PLANTS = (0.0, 0.05, 0.15, 0.30)
#: How a series is nulled. `blocks` keeps 96-bar runs, so volatility clustering
#: **survives** inside a block - which makes it the right null for the volume
#: terms, whose link to price it destroys, and the wrong one for the price-only
#: volatility terms, whose skill it reproduces. `iid` shuffles single returns
#: and destroys clustering too, so it is the null those terms need.
NULLS = ("blocks", "iid")
SEED = 20261015
TRADED = ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "AUDUSD", "USDCAD", "EURJPY", "XAGUSD")
GENERATED = ("Volatility_75_Index", "Volatility_100_Index", "Step_Index_200")
#: The canonical four, plus the two that were asked for.
GROUPS = {
    "trend": ("slope t", "ema gap", "ema cross", "ema slope"),
    "momentum": ("accel t",),
    "volatility": ("range ratio", "vol ratio"),
    "regime": ("regime",),
    "level": ("level recency",),
    "tick": ("tick z", "tick velocity"),
}
FEATURES = tuple(name for names in GROUPS.values() for name in names)


def load(name: str, frame: str):
    path = CACHE / f"{name}.{frame}.npz"
    if not path.exists():
        return None
    with np.load(path) as bundle:
        need = {"time", "high", "low", "close", "open"}
        if not need <= set(bundle.keys()):
            return None
        order = np.argsort(bundle["time"])
        got = {k: np.asarray(bundle[k], dtype=float)[order] for k in need}
        # The cache calls it `volume` and it is a **tick count** - median 827 at
        # 15m and 2,544 at 1h on EURUSD. The first version of this read
        # `tick_volume`, which does not exist, and fell back to `ones` - which
        # makes a volume profile a plain mid-price histogram and a tick z-score
        # all-NaN, since a constant has no spread. Raise rather than fall back.
        if "volume" not in bundle:
            raise KeyError(f"no volume in {path.name}")
        got["volume"] = np.asarray(bundle["volume"], dtype=float)[order]
    keep = (got["high"] >= got["low"]) & (got["low"] > 0)
    got = {k: v[keep] for k, v in got.items()}
    if len(got["close"]) < 8000:
        return None
    if len(got["close"]) > LIMIT:
        got = {k: v[-LIMIT:] for k, v in got.items()}
    return got


def rolling_sum(got: np.ndarray, back: int) -> np.ndarray:
    """Trailing sum over `back`, NaN until the window is full."""
    out = np.full(len(got), np.nan)
    if len(got) < back:
        return out
    csum = np.cumsum(np.nan_to_num(got))
    out[back - 1 :] = csum[back - 1 :] - np.concatenate(([0.0], csum[:-back]))
    return out


def ema(got: np.ndarray, span: float) -> np.ndarray:
    from scipy.signal import lfilter

    alpha = 2.0 / (span + 1.0)
    return lfilter([alpha], [1.0, -(1.0 - alpha)], np.nan_to_num(got))


def slope_parts(price: np.ndarray, back: int):
    """Rolling OLS slope and its own standard error, in O(n) from cumulative sums."""
    spot = np.arange(len(price), dtype=float)
    sum_y = rolling_sum(price, back)
    sum_yy = rolling_sum(price**2, back)
    sum_iy = rolling_sum(spot * price, back)
    start = spot - (back - 1)
    sum_x = back * (back - 1) / 2.0
    sum_xx = (back - 1) * back * (2 * back - 1) / 6.0
    sum_xy = sum_iy - start * sum_y
    spread_x = back * sum_xx - sum_x**2
    slope = (back * sum_xy - sum_x * sum_y) / spread_x
    intercept = (sum_y - slope * sum_x) / back
    sse = np.maximum(sum_yy - intercept * sum_y - slope * sum_xy, 0.0)
    centred_x = sum_xx - sum_x**2 / back
    with np.errstate(invalid="ignore", divide="ignore"):
        error = np.sqrt(sse / max(back - 2, 1) / centred_x)
    return slope, error


def features(bars, back: int) -> dict[str, np.ndarray]:
    """Every term, causal, on a trailing `back`-bar window.

    Each is scale-free by construction - a `t`, a ratio or a standardised gap -
    so the same weights mean the same thing on EURUSD and on gold, which is a
    requirement for a single weighted sum and not a nicety.
    """
    highs, lows, closes = bars["high"], bars["low"], bars["close"]
    price = np.log(np.maximum((highs + lows + closes) / 3.0, 1e-12))
    volume = bars["volume"]
    out: dict[str, np.ndarray] = {}

    slope, error = slope_parts(price, back)
    with np.errstate(invalid="ignore", divide="ignore"):
        out["slope t"] = np.where(error > 0, slope / error, np.nan)
    quick, slow = ema(price, back / 4.0), ema(price, float(back))
    gap = price - slow
    unit = np.sqrt(rolling_sum(np.nan_to_num(gap) ** 2, back) / back)
    step = max(int(back / 10), 2)
    moved = np.concatenate((np.full(step, np.nan), slow[step:] - slow[:-step]))
    with np.errstate(invalid="ignore", divide="ignore"):
        out["ema gap"] = np.where(unit > 0, gap / unit, np.nan)
        out["ema cross"] = np.where(unit > 0, (quick - slow) / unit, np.nan)
        out["ema slope"] = np.where(unit > 0, moved / unit, np.nan)

    # Momentum: how much the slope itself has changed, over its own error. The
    # acceleration `linear` and `landau` carry as a state, in a scale-free form.
    lag = max(int(back / 4), 2)
    changed = np.concatenate((np.full(lag, np.nan), slope[lag:] - slope[:-lag]))
    with np.errstate(invalid="ignore", divide="ignore"):
        out["accel t"] = np.where(error > 0, changed / (error * math.sqrt(2.0)), np.nan)

    # Volatility: the range estimator against the close estimator, which
    # `drive-q-from-the-range` measures as the better driver, and short against
    # long realised.
    steps = np.concatenate(([np.nan], np.diff(price)))
    close_var = rolling_sum(np.nan_to_num(steps) ** 2, back) / back
    span = np.log(np.maximum(highs, 1e-12)) - np.log(np.maximum(lows, 1e-12))
    range_var = rolling_sum(span**2, back) / (back * 4.0 * math.log(2.0))
    short_var = rolling_sum(np.nan_to_num(steps) ** 2, max(back // 4, 4)) / max(back // 4, 4)
    with np.errstate(invalid="ignore", divide="ignore"):
        out["range ratio"] = np.where(close_var > 0, np.sqrt(range_var / close_var), np.nan)
        ratio = np.where(close_var > 0, np.sqrt(short_var / close_var), np.nan)
    out["vol ratio"] = ratio
    # Regime: the same ratio, centred so that one means "no regime".
    out["regime"] = ratio - 1.0

    # Level return: recency to the nearest swing extreme, which is the only one
    # of `strength`'s four terms that orders a return rate.
    reach = back * 4
    top = np.full(len(price), np.nan)
    bottom = np.full(len(price), np.nan)
    for i in range(reach, len(price)):
        window = slice(i - reach, i)
        top[i] = float(highs[window].max())
        bottom[i] = float(lows[window].min())
    near_top = np.abs(closes - top)
    near_bottom = np.abs(closes - bottom)
    nearest = np.where(near_top <= near_bottom, top, bottom)
    with np.errstate(invalid="ignore", divide="ignore"):
        unit_price = np.sqrt(close_var) * closes
        out["level recency"] = np.where(
            unit_price > 0, -np.abs(closes - nearest) / unit_price, np.nan
        )

    # Tick velocity: volume against its own trailing mean, and its rate of change.
    mean_volume = rolling_sum(volume, back) / back
    with np.errstate(invalid="ignore", divide="ignore"):
        spread_volume = np.sqrt(
            np.maximum(rolling_sum(volume**2, back) / back - mean_volume**2, 0.0)
        )
        zed = np.where(spread_volume > 0, (volume - mean_volume) / spread_volume, np.nan)
    out["tick z"] = zed
    out["tick velocity"] = np.concatenate((np.full(step, np.nan), zed[step:] - zed[:-step]))
    return out


def auc(score: np.ndarray, truth: np.ndarray) -> float:
    """Tie-aware `P(score | yes > score | no) + 0.5 P(equal)`."""
    keep = np.isfinite(score) & np.isfinite(truth)
    score, truth = score[keep], truth[keep].astype(bool)
    yes = np.sort(score[truth])
    no = np.sort(score[~truth])
    if not len(yes) or not len(no):
        return float("nan")
    left = np.searchsorted(no, yes, side="left")
    right = np.searchsorted(no, yes, side="right")
    return (float(left.sum()) + 0.5 * float((right - left).sum())) / (len(yes) * len(no))


def standardise(table: np.ndarray) -> np.ndarray:
    """Zero mean, unit spread per column, so one weight set is portable."""
    middle = np.nanmedian(table, axis=0)
    spread = np.nanstd(table, axis=0)
    spread = np.where(spread > 0, spread, 1.0)
    return (table - middle) / spread


def momentum(price: np.ndarray, rho: float, rng) -> np.ndarray:
    """Give the returns positive autocorrelation `rho`, keeping their spread.

    A directional effect the trend terms can find, unlike a random walk added
    to the level. The spread is restored afterwards so the plant changes the
    *predictability* of the series and not its volatility, which the magnitude
    target would otherwise pick up as the planted effect.
    """
    steps = np.diff(price)
    if rho <= 0.0 or len(steps) < 4:
        return price
    out = np.empty_like(steps)
    out[0] = steps[0]
    for i in range(1, len(steps)):
        out[i] = steps[i] + rho * out[i - 1]
    spread = np.std(out)
    if spread > 0:
        out = out * (np.std(steps) / spread)
    _ = rng
    return np.concatenate(([price[0]], price[0] + np.cumsum(out)))


def gather(
    names: tuple[str, ...],
    frame: str,
    horizon: int,
    rho: float = 0.0,
    shuffle: str = "none",
):
    """The feature table, both targets, and a feed label per row."""
    rng = np.random.default_rng(SEED)
    rows: list[np.ndarray] = []
    direction: list[np.ndarray] = []
    magnitude: list[np.ndarray] = []
    for name in names:
        bars = load(name, frame)
        if bars is None:
            continue
        if shuffle != "none":
            # Reorder the returns and rebuild, so every feature is computed on a
            # series with the same bar geometry and no memory. `volume` is left
            # in place rather than reordered, which is deliberate: it makes this
            # the null for "does volume predict what price does", by breaking
            # exactly that link and nothing else.
            closes = bars["close"]
            steps = np.diff(np.log(closes))
            count = max(len(steps) // 96, 2) if shuffle == "blocks" else len(steps)
            blocks = np.array_split(steps, count)
            rng.shuffle(blocks)
            rebuilt = float(closes[0]) * np.exp(np.cumsum(np.concatenate(blocks)))
            span = slice(1, len(rebuilt) + 1)
            scale = rebuilt / np.maximum(closes[span], 1e-12)
            prices = {"high", "low", "close", "open"}
            bars = {
                k: (v[span] * scale if k in prices else v[span]) for k, v in bars.items()
            }
        price = np.log(np.maximum(bars["close"], 1e-12))
        if rho > 0.0:
            price = momentum(price, rho, rng)
            moved = price - np.log(np.maximum(bars["close"], 1e-12))
            bars = dict(bars)
            for key in ("high", "low", "close", "open"):
                bars[key] = bars[key] * np.exp(moved)
        got = features(bars, BACK)
        ahead = np.concatenate((price[horizon:] - price[:-horizon], np.full(horizon, np.nan)))
        table = np.column_stack([got[name] for name in FEATURES])
        keep = np.isfinite(table).all(axis=1) & np.isfinite(ahead)
        if keep.sum() < 2000:
            continue
        rows.append(table[keep])
        direction.append((ahead[keep] > 0).astype(float))
        size = np.abs(ahead[keep])
        magnitude.append((size > np.median(size)).astype(float))
    if not rows:
        return None
    return (
        standardise(np.vstack(rows)),
        np.concatenate(direction),
        np.concatenate(magnitude),
    )


def fitted(table: np.ndarray, truth: np.ndarray, interactions: bool = False) -> float:
    """Out-of-sample AUC of the fitted perceptron: logistic regression.

    Fitted on the first half and scored on the second, which is the only way a
    fitted arm is comparable with a hand-tuned one. With `interactions`, every
    term is also multiplied by the regime, which is the gated form the additive
    `w_regime * Regime` cannot express.
    """
    from sklearn.linear_model import LogisticRegression

    design = table
    if interactions:
        regime = table[:, FEATURES.index("regime")][:, None]
        design = np.hstack([table, table * regime])
    cut = len(design) // 2
    model = LogisticRegression(max_iter=2000, C=1.0)
    model.fit(design[:cut], truth[:cut])
    return auc(model.decision_function(design[cut:]), truth[cut:])


def boosted(table: np.ndarray, truth: np.ndarray) -> float:
    """The nonlinear ceiling, so the linear form's cost is a number."""
    from sklearn.ensemble import HistGradientBoostingClassifier

    cut = len(table) // 2
    model = HistGradientBoostingClassifier(max_iter=150, max_depth=4, random_state=0)
    model.fit(table[:cut], truth[:cut])
    return auc(model.predict_proba(table[cut:])[:, 1], truth[cut:])


def handtuned(table: np.ndarray, gated: bool) -> np.ndarray:
    """The formula as written, with equal weight on each named group.

    Hand-tuned means chosen, and the only defensible choice without a fit is
    equal: each group contributes the mean of its standardised members, and the
    four canonical groups carry the weight the formula gives them. `gated`
    multiplies trend and momentum by the regime instead of adding it.
    """
    column = {name: table[:, i] for i, name in enumerate(FEATURES)}
    parts = {
        group: np.mean([column[name] for name in names], axis=0)
        for group, names in GROUPS.items()
    }
    if gated:
        return (
            (1.0 + parts["regime"]) * (parts["trend"] + parts["momentum"])
            + parts["volatility"]
            + parts["level"]
            + parts["tick"]
        )
    return (
        parts["trend"]
        + parts["momentum"]
        + parts["volatility"]
        + parts["regime"]
        + parts["level"]
        + parts["tick"]
    )


def row(label, pick, table, way, size, twins) -> None:
    """One table line: the arm on the real series against both nulls.

    `pick` takes a feature table and a truth vector and returns an AUC, so one
    function serves a single column, a hand-tuned sum and a fitted model.
    """
    out = []
    for truth, index in ((way, 1), (size, 2)):
        value = pick(table, truth)
        nulls = []
        for kind in NULLS:
            other = twins.get(kind)
            nulls.append(float("nan") if other is None else pick(other[0], other[index]))
        # The floor is whichever null scores highest: a term has to beat the
        # best explanation available, not the most flattering one.
        floor = float(np.nanmax(nulls)) if np.any(np.isfinite(nulls)) else float("nan")
        out.append((value, nulls[0], nulls[1], value - floor))
    print(
        f"  {label:<24}"
        + "".join(f"{v:>8.4f}" for v in out[0])
        + "  |"
        + "".join(f"{v:>8.4f}" for v in out[1])
    )


def main() -> None:
    print(
        f"Signal as a perceptron: {len(FEATURES)} terms in {len(GROUPS)} groups, "
        f"{BACK}-bar window.\n"
        "Every fitted arm is trained on the first half and scored on the second.\n"
    )
    for frame in FRAMES:
        for horizon in HORIZONS:
            for group, names in (("traded", TRADED), ("generated", GENERATED)):
                real = gather(names, frame, horizon)
                if real is None:
                    continue
                table, way, size = real
                twins = {}
                for kind in NULLS:
                    twins[kind] = gather(names, frame, horizon, shuffle=kind)
                print("=" * 104)
                print(f"{frame}  h={horizon}  {group}   {len(table):,} rows")
                print("=" * 104)
                head = f"  {'arm':<24}{'dir':>8}{'blocks':>8}{'iid':>8}{'edge':>8}"
                print(head + f"  |{'mag':>8}{'blocks':>8}{'iid':>8}{'edge':>8}")

                for index, name in enumerate(FEATURES):
                    def one(t, truth, i=index):
                        return auc(t[:, i], truth)

                    row(name, one, table, way, size, twins)
                for label, gated in (("hand-tuned, additive", False), ("hand-tuned, gated", True)):
                    row(
                        label,
                        lambda t, truth, g=gated: auc(handtuned(t, g), truth),
                        table,
                        way,
                        size,
                        twins,
                    )
                row("fitted linear", lambda t, truth: fitted(t, truth), table, way, size, twins)
                row(
                    "fitted + regime gates",
                    lambda t, truth: fitted(t, truth, interactions=True),
                    table,
                    way,
                    size,
                    twins,
                )
                row("boosted ceiling", lambda t, truth: boosted(t, truth), table, way, size, twins)
                print(
                    "  `blocks` keeps 96-bar runs so volatility clustering survives inside\n"
                    "  one - the right null for the volume terms, whose link to price it\n"
                    "  breaks, and the wrong one for the price-only volatility terms, whose\n"
                    "  skill it reproduces. `iid` reorders single returns and destroys the\n"
                    "  clustering as well. `edge` is real minus the **higher** of the two,\n"
                    "  so a term has to beat the best available explanation.\n"
                )
            # Power on direction, which is the target expected to be a coin.
            print(f"  power on direction, {frame} h={horizon}: planted return momentum")
            print(f"  {'rho':>7}{'best single':>13}{'hand-tuned':>12}{'fitted':>9}{'boosted':>9}")
            for rho in PLANTS:
                got = gather(TRADED, frame, horizon, rho=rho)
                if got is None:
                    continue
                table, way, _size = got
                best = max(abs(auc(table[:, i], way) - 0.5) for i in range(len(FEATURES)))
                print(
                    f"  {rho:>7.2f}{0.5 + best:>13.4f}"
                    f"{auc(handtuned(table, False), way):>12.4f}"
                    f"{fitted(table, way):>9.4f}{boosted(table, way):>9.4f}"
                )
            print(
                "  `rho` of 0 is the measured figure; the rows above it say what size of\n"
                "  real directional structure this test would have found. A curve that\n"
                "  does not rise means the null above is not a null.\n"
            )


if __name__ == "__main__":
    main()
