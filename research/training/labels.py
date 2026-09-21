"""The label families. One question each, all over the same features and splits.

A supervised label has to look into the future - that is the whole point of it -
so none of these is shy about it. What they are careful about is the *other* two
things people mean by leakage: forward information reaching a feature, and a
row's forward window straddling a train/test boundary. The first is handled by
`candles.features`, which only ever indexes `<= t`; the second by `splits.py`,
which purges and embargoes by exactly the horizon each family uses.

Every family answers `(y, ret, valid, names)`:

* `y`     the class per bar, as an integer index into `names`
* `ret`   **what a decision at that bar would actually have realised**, under
          that family's own exit rule - not always the close-to-close return,
          because a triple-barrier decision exits at a barrier and a speed
          decision exits on a clock
* `valid` False where there is not enough forward data, or the question is not
          defined for that bar
* `names` the class names, so a confusion matrix can be read

## Which of these can be trusted on which source

`triple` and `speed` read a bar's **high and low**. Every public daily series
checked here misreports those on a few percent of rows - a close outside the
bar's own range - and `candles.read` repairs them by widening, which is the
minimal honest fix but is still a repair. So a first-passage answer on a public
daily file is softer than it looks, and `candles.build` carries the repair count
per instrument so a caller can refuse. On broker bars the extremes are the
terminal's own and the question is clean.

`banded`, `expansion`, `regime` and `seasonal` use closes only and are safe
anywhere.
"""

from __future__ import annotations

import datetime as dt

import numpy as np

#: How much of the horizon a move must arrive inside to count as fast. A third
#: is not tuned - it is the natural split of "early, late, never" into thirds,
#: and tuning it against the answer is how a threshold becomes a result.
FAST_SHARE = 1.0 / 3.0

#: Dead band for the volatility and regime families, as a fraction. Below this
#: the forward window is called unchanged rather than forced into a direction.
STEADY = 0.15

#: Minimum forward bars a variance ratio needs before it means anything.
RATIO_MIN = 8


def _forward_return(close: np.ndarray, horizon: int) -> tuple[np.ndarray, np.ndarray]:
    """Close-to-close return `horizon` bars ahead, and where it is defined."""
    n = len(close)
    out = np.full(n, np.nan)
    valid = np.zeros(n, dtype=bool)
    if n > horizon:
        ahead = close[horizon:]
        here = close[:-horizon]
        good = (here > 0) & (ahead > 0)
        out[: n - horizon] = np.where(good, ahead / np.where(here > 0, here, 1.0) - 1.0, np.nan)
        valid[: n - horizon] = good
    return out, valid


def banded(bars, tr, horizon, band):
    """Up, flat or down by `band` true ranges, measured close to close.

    The plainest question, and the baseline the others have to beat. `flat` is
    the majority class by construction, which is deliberate: a model that cannot
    beat "say flat" has found nothing, and a two-class label would hide that.
    """
    close = bars[:, 4]
    forward, valid = _forward_return(close, horizon)
    edge = band * tr
    y = np.ones(len(close), dtype=np.int64)  # flat
    y[forward > edge] = 2
    y[forward < -edge] = 0
    return y, forward, valid, ["down", "flat", "up"]


def _first_passage(bars, tr, horizon, band):
    """For each bar: which barrier was hit first, and after how many bars.

    Returns `(side, bars_taken)` with side +1 up, -1 down, 0 neither. **When both
    barriers fall inside the same bar the adverse one wins**, because a bar does
    not record the order its extremes arrived in. That biases every number this
    produces downward, which is the direction an honest bias points when the
    alternative is flattering a rule you are about to trade.
    """
    close, high, low = bars[:, 4], bars[:, 2], bars[:, 3]
    n = len(close)
    side = np.zeros(n, dtype=np.int64)
    took = np.zeros(n, dtype=np.int64)
    for at in range(n - horizon):
        here = close[at]
        if here <= 0:
            continue
        reach = band * tr[at] * here
        up, down = here + reach, here - reach
        for step in range(1, horizon + 1):
            hit_up = high[at + step] >= up
            hit_down = low[at + step] <= down
            if hit_up and hit_down:
                side[at], took[at] = -1, step  # the adverse one, by convention
                break
            if hit_up:
                side[at], took[at] = 1, step
                break
            if hit_down:
                side[at], took[at] = -1, step
                break
    return side, took


def triple(bars, tr, horizon, band):
    """Triple barrier: a profit target, a stop, and a clock.

    This is the label that matches what the desk actually does - every strategy
    it runs is an entry plus a stop plus a target - which is why it is worth the
    extra care its inputs need. `ret` is the return the barrier would have paid,
    not the close-to-close return, since a barrier trade does not sit to the end
    of the horizon.
    """
    close = bars[:, 4]
    side, _took = _first_passage(bars, tr, horizon, band)
    forward, valid = _forward_return(close, horizon)
    y = np.where(side > 0, 2, np.where(side < 0, 0, 1)).astype(np.int64)
    # Realised: the barrier when one was touched, otherwise wherever the clock
    # left it.
    reach = band * tr
    ret = np.where(side != 0, side * reach, np.nan_to_num(forward))
    return y, ret, valid, ["stopped", "timeout", "target"]


def speed(bars, tr, horizon, band):
    """How quickly a move of `band` true ranges arrives, in either direction.

    The "fast movement" question, as a label rather than a hunch. It is
    deliberately **unsigned**: it asks whether the next `horizon` bars contain a
    move worth taking at all, which is the trade-or-not-trade decision, and
    leaves the direction to a directional model. Six independent tests here have
    found no directional edge at any horizon, so a magnitude question is the one
    with somewhere to go.
    """
    side, took = _first_passage(bars, tr, horizon, band)
    _forward, valid = _forward_return(bars[:, 4], horizon)
    quick = max(1, round(horizon * FAST_SHARE))
    y = np.full(len(side), 2, dtype=np.int64)  # never
    y[(side != 0) & (took > quick)] = 1  # slow
    y[(side != 0) & (took <= quick)] = 0  # fast
    # What the move was worth in true ranges, unsigned: the magnitude available.
    ret = np.where(side != 0, band * tr, 0.0)
    return y, ret, valid, ["fast", "slow", "never"]


def expansion(bars, tr, horizon, band):  # noqa: ARG001 - a volatility question sizes no barrier
    """Is volatility about to expand, hold, or contract?

    Realised close-to-close volatility over the next `horizon` bars against the
    trailing true range, as a ratio. `band` is unused - the family's own dead
    band decides - and that is on purpose rather than an oversight: a volatility
    question has no barrier to size.

    This is the one family with a known use already waiting for it. The desk
    sizes every position off an EWMA of true range, which is a *backward* reading;
    a forward one would let it size for the volatility it is about to meet.
    """
    close = bars[:, 4]
    n = len(close)
    logs = np.zeros(n)
    good = (close[1:] > 0) & (close[:-1] > 0)
    safe_now = np.where(close[1:] > 0, close[1:], 1.0)
    safe_was = np.where(close[:-1] > 0, close[:-1], 1.0)
    logs[1:] = np.where(good, np.log(safe_now / safe_was), 0.0)

    ahead = np.full(n, np.nan)
    valid = np.zeros(n, dtype=bool)
    for at in range(n - horizon):
        window = logs[at + 1 : at + horizon + 1]
        if len(window) >= 2:
            ahead[at] = window.std(ddof=1)
            valid[at] = True

    ratio = ahead / np.maximum(tr, 1e-12)
    # The ratio's own median is the neutral point, because true range and a
    # close-to-close standard deviation are not on the same scale and a ratio of
    # 1.0 would call almost everything a contraction.
    middle = np.nanmedian(ratio[valid]) if valid.any() else 1.0
    y = np.ones(n, dtype=np.int64)  # steady
    y[ratio > middle * (1.0 + STEADY)] = 2
    y[ratio < middle * (1.0 - STEADY)] = 0
    return y, np.nan_to_num(ratio - middle), valid, ["contract", "steady", "expand"]


def regime(bars, tr, horizon, band):  # noqa: ARG001 - a regime question sizes no barrier
    """Is the next stretch trending, choppy, or neither?

    A variance ratio over the forward window: the variance of the whole move
    against `horizon` times the variance of one bar. Above one the move is
    persistent, below one it reverts. This is the "seasons of momentum and mean
    reversion" question, asked bar by bar rather than by hour of the day.

    **What it cannot tell you** is whether either state is tradeable. Intraday
    regime has already been measured here as mean-reverting almost everywhere and
    by less than the spread, so a correct forecast of the state is not yet a
    trade. This labels the state; whether it pays is a separate question and the
    scoring in the trainers is what answers it.
    """
    close = bars[:, 4]
    n = len(close)
    logs = np.zeros(n)
    logs[1:] = np.log(np.maximum(close[1:], 1e-12) / np.maximum(close[:-1], 1e-12))

    ratio = np.full(n, np.nan)
    valid = np.zeros(n, dtype=bool)
    if horizon >= RATIO_MIN:
        for at in range(n - horizon):
            window = logs[at + 1 : at + horizon + 1]
            one = window.var(ddof=1)
            if one <= 0:
                continue
            whole = window.sum() ** 2
            ratio[at] = whole / (horizon * one)
            valid[at] = True

    y = np.ones(n, dtype=np.int64)  # neither
    y[ratio > 1.0 + STEADY] = 2
    y[ratio < 1.0 - STEADY] = 0
    return y, np.nan_to_num(ratio - 1.0), valid, ["revert", "neither", "trend"]


def seasonal(bars, tr, horizon, band):
    """The forward move, *net of whatever the calendar already explains*.

    Intraday seasonality here turned out to be a rollover quoting artifact, and a
    daily seasonal that is really "Mondays are different at this broker" is the
    same trap one timeframe up. So this subtracts the instrument's own running
    mean forward return for that calendar slot and bands what is left: it asks
    whether there is anything beyond the season, which is the only version of the
    question worth trading.

    **The calendar mean is expanding, not full-sample.** A full-sample mean would
    be computed partly from the future of every row it is subtracted from - real
    leakage, and the subtle kind, because the label would still look plausible.
    """
    close = bars[:, 4]
    forward, valid = _forward_return(close, horizon)
    slot = np.array(
        [dt.datetime.fromtimestamp(t, dt.UTC).weekday() for t in bars[:, 0]], dtype=np.int64
    )
    # Intraday files need the hour, not the weekday, and the bar spacing says
    # which this is without being told.
    spacing = np.median(np.diff(bars[:, 0])) if len(bars) > 2 else 86_400.0
    if spacing < 86_000.0:
        slot = np.array(
            [dt.datetime.fromtimestamp(t, dt.UTC).hour for t in bars[:, 0]], dtype=np.int64
        )

    excess = np.full(len(close), np.nan)
    seen: dict[int, list[float]] = {}
    for at in range(len(close)):
        if not valid[at]:
            continue
        past = seen.get(slot[at], [])
        # Only slots seen enough times to have a mean worth subtracting.
        excess[at] = forward[at] - (sum(past) / len(past) if len(past) >= RATIO_MIN else 0.0)
        # The value is banked only after it is used, so it never informs itself.
        seen.setdefault(slot[at], []).append(forward[at])

    edge = band * tr
    y = np.ones(len(close), dtype=np.int64)
    y[excess > edge] = 2
    y[excess < -edge] = 0
    valid = valid & np.isfinite(excess)
    return y, np.nan_to_num(excess), valid, ["under", "as-usual", "over"]


#: Every family, by the name the trainers take on the command line.
FAMILIES = {
    "banded": banded,
    "triple": triple,
    "speed": speed,
    "expansion": expansion,
    "regime": regime,
    "seasonal": seasonal,
}

#: Families that read a bar's high and low, and are therefore only as good as the
#: source's extremes. `candles.build` reports repairs per instrument; a caller
#: working on public dailies should think twice about these two.
NEEDS_EXTREMES = frozenset({"triple", "speed"})
