"""Moving bands: eight moving averages, a centroid, a rolling min and a max.

One rule over eleven estimators of "where price has been lately", so the
estimator is a swept parameter rather than eleven near-identical strategies.
Nautilus supplies the eight averages through `MovingAverageFactory`; the
centroid, min and max are here because it has no equivalent.

**This exists to make the exit measurable, and that is the honest reason.**
`exits.ManagedExit` says break-even and trailing are "an empirical question
about this strategy on these instruments and nothing in this repository
answers it". The rules that could have answered it place 4 to 18 positions over
the catalogue's 76 days - far too few - and a band crossover on the same 5,135
bars fires often enough to say something. A direction claim is *not* what this
is for: `direction-is-closed-not-just-null` records the gate finding a planted
drift at z +2.90 while earning 2% of a spread, and a moving-average crossover
is the most-tested direction idea in the subject's history.

## The two signal forms, and why both

`cross` is the conventional pair: the fast estimator through the slow one. It
is the form every average here is usually traded in.

`break` is price through a single estimator. **The rolling min and max only
exist in this form** - a fast/slow pair of rolling maxima is two lagging copies
of the same extreme and crosses almost never, while `close > max(N)` is a
Donchian breakout, which is what a rolling extreme is for. Running the averages
in both forms costs one flag and makes the comparison a comparison of
estimators rather than of estimators-and-forms.

## Asymmetry

Every number a side could want differs by side, through the `*_for(sign)`
methods `StructureProfile` established: spans, the stop multiple and the
target. Markets are not symmetric - `fear-greed.md` measured down swings 33%
faster and up swings 21% longer, stable in 6 of 6 eras - so a rule with one
number for both sides is asserting something the data refuses.

The tilt convention is `indicators.levels.Sided`: a shared value and a ratio,
so the **geometric mean is the shared value whatever the tilt** and a tilt of 1
is exactly neutral. That matters because `refit-the-parameter-a-lever-
multiplies` records a multiplier whose mean was not 1 reversing a +1192 result
to -24 by moving the average rather than the asymmetry.

## The volatility it publishes

`ma_atr` and `ma_close`, not `vol_bps`. `structure.py` gives the reason in
place: `vol_bps` is a folded log variance elsewhere on this desk and an ATR
written into it would put one journal column in two estimators.
`exits._trail_vol_bps` converts an `*_atr` with its `*_close` anchor, so the
trail works without the column being polluted - which is the whole point of
publishing it, since a rule carrying no volatility gets no trail and does so
silently.
"""

from __future__ import annotations

import os
from collections import deque
from dataclasses import dataclass
from typing import Any, ClassVar

from nautilus_trader.model.data import Bar

from ..domain.models import Intent, Refusal, Side
from .entries import ArrivalEntry, EdgeEntry, RestingEntry
from .exits import ManagedExit
from .profile import Profile

#: The eight Nautilus averages, by the name an operator writes, mapped to the
#: `MovingAverageType` member. `VARIABLE_INDEX_DYNAMIC` and `ADAPTIVE` both
#: take an extra argument in Nautilus and are built through the factory the
#: same way, so nothing here special-cases them.
AVERAGES: dict[str, str] = {
    "sma": "SIMPLE",
    "ema": "EXPONENTIAL",
    "dema": "DOUBLE_EXPONENTIAL",
    "wilder": "WILDER",
    "hull": "HULL",
    "adaptive": "ADAPTIVE",
    "wma": "WEIGHTED",
    "vidya": "VARIABLE_INDEX_DYNAMIC",
}

#: The three this module implements, because Nautilus has no equivalent.
#:
#: `centroid` is the rolling mean of the **typical price** `(h + l + c) / 3`
#: rather than of the close, which is what makes it a different estimator from
#: `sma` rather than a slower copy of it: it reads where the bar's mass sat,
#: not where it finished. `drive-q-from-the-range` is the standing reason to
#: prefer a range-aware estimator - the range-vs-close ratio runs 0.648 on FX
#: and 0.667 on 371 of 392 equities.
OURS: tuple[str, ...] = ("centroid", "rmin", "rmax", "sigma")

#: Every estimator this rule can run.
KINDS: tuple[str, ...] = (*AVERAGES, *OURS)

#: The estimators that make no sense as a fast/slow pair. A pair of rolling
#: maxima is two lagging copies of one extreme and crosses almost never.
BREAK_ONLY: frozenset[str] = frozenset({"rmin", "rmax", "sigma"})

DEFAULT_KIND = "ema"
DEFAULT_FAST = 20
DEFAULT_SLOW = 50
#: Volatility units from the entry to the stop. 3.0 is `Intent.stop_vol`'s own
#: median on this desk, so it is the incumbent rather than a guess.
DEFAULT_STOP_VOL = 3.0
#: Zero target. `EdgeEntry` submits the entry alone on a zero and attaches the
#: stop from `on_order_filled`; a target invented here would make this a
#: different rule with better arithmetic, which is the error
#: `a-martingale-cannot-pay` is about.
DEFAULT_TARGET_R = 0.0
DEFAULT_MODE = "cross"
DEFAULT_ATR_PERIOD = 14


def _float(name: str, fallback: float) -> float:
    try:
        return float(os.environ.get(name) or fallback)
    except ValueError:
        return fallback


def _int(name: str, fallback: int) -> int:
    try:
        return int(float(os.environ.get(name) or fallback))
    except ValueError:
        return fallback


@dataclass(frozen=True, slots=True)
class Tuning:
    """What a sweep varies, read from the environment on every call.

    **Read per call and not at import.** `research/ideas/leaf_sweep.py` sets
    the environment per cell inside one process, so a value captured at import
    would run all 528 cells as the first one - which is the defect that made a
    sweep report one leaf's result for four rules.
    """

    kind: str = DEFAULT_KIND
    fast: int = DEFAULT_FAST
    slow: int = DEFAULT_SLOW
    mode: str = DEFAULT_MODE
    stop_vol: float = DEFAULT_STOP_VOL
    target_r: float = DEFAULT_TARGET_R
    #: Resistance-side to support-side ratio, in `Sided`'s sense: the two sides
    #: are `shared * sqrt(tilt)` and `shared / sqrt(tilt)`, so the geometric
    #: mean is `shared` whatever the tilt and 1.0 is exactly neutral.
    span_tilt: float = 1.0
    stop_tilt: float = 1.0
    #: Standard deviations either side of the mean for the `sigma` kind. Two
    #: is the conventional choice and is not measured here.
    sigma_k: float = 2.0
    #: Close the position when the pair turns against it. **Without this the
    #: win rate is 0.00 by construction**: with no target and no hold clock
    #: the only exit is the stop, which is what the first run of this rule
    #: measured on all 57 positions across five estimators. An average
    #: crossover rule exits on the opposite cross; that is the rule, not an
    #: addition to it.
    exit_on_turn: bool = True

    @classmethod
    def read(cls) -> Tuning:
        kind = (os.environ.get("TRADING_BAND_KIND") or DEFAULT_KIND).strip().lower()
        if kind not in KINDS:
            raise ValueError(
                f"{kind!r} is not a band this rule can build. Known: {', '.join(KINDS)}."
            )
        mode = (os.environ.get("TRADING_BAND_MODE") or DEFAULT_MODE).strip().lower()
        if mode not in ("cross", "break"):
            raise ValueError(f"{mode!r} is not a mode: 'cross' or 'break'.")
        if kind in BREAK_ONLY:
            # Not a refusal: a sweep that asked for every estimator in both
            # modes would otherwise lose a third of its cells to an argument
            # about a form that does not apply, and the cell is still a cell.
            mode = "break"
        return cls(
            kind=kind,
            fast=max(2, _int("TRADING_BAND_FAST", DEFAULT_FAST)),
            slow=max(3, _int("TRADING_BAND_SLOW", DEFAULT_SLOW)),
            mode=mode,
            stop_vol=max(0.0, _float("TRADING_BAND_STOP_VOL", DEFAULT_STOP_VOL)),
            target_r=max(0.0, _float("TRADING_BAND_TARGET_R", DEFAULT_TARGET_R)),
            span_tilt=max(1e-6, _float("TRADING_BAND_SPAN_TILT", 1.0)),
            stop_tilt=max(1e-6, _float("TRADING_BAND_STOP_TILT", 1.0)),
            sigma_k=max(0.0, _float("TRADING_BAND_SIGMA_K", 2.0)),
            exit_on_turn=(os.environ.get("TRADING_BAND_EXIT_ON_TURN", "1") or "1")
            not in ("0", "false", "False", "no"),
        )

    def _sided(self, shared: float, tilt: float, sign: int) -> float:
        """`shared` tilted onto one side, geometric mean preserved."""
        root = tilt**0.5
        return shared * root if sign > 0 else shared / root

    def span_for(self, shared: int, sign: int) -> int:
        return max(2, round(self._sided(float(shared), self.span_tilt, sign)))

    def stop_for(self, sign: int) -> float:
        return self._sided(self.stop_vol, self.stop_tilt, sign)


class Rolling:
    """A rolling window with a mean, a min and a max over the same buffer.

    Three statistics off one deque rather than three indicators, because they
    share the window and a reader comparing them must be sure the windows are
    identical - `restore-drops-deque-maxlen` is the standing reminder that a
    window's bound is worth asserting rather than assuming.
    """

    __slots__ = ("_seen", "span")

    def __init__(self, span: int) -> None:
        if span < 1:
            raise ValueError(f"span={span} is not a window")
        self.span = int(span)
        self._seen: deque[float] = deque(maxlen=self.span)

    def update(self, value: float) -> None:
        self._seen.append(float(value))

    @property
    def initialized(self) -> bool:
        return len(self._seen) >= self.span

    @property
    def mean(self) -> float:
        return sum(self._seen) / len(self._seen) if self._seen else 0.0

    @property
    def lowest(self) -> float:
        return min(self._seen) if self._seen else 0.0

    @property
    def highest(self) -> float:
        return max(self._seen) if self._seen else 0.0

    @property
    def stdev(self) -> float:
        """The window's population standard deviation.

        Population and not sample: the window **is** the data the band is
        drawn from rather than a draw from something larger, and at span 20
        the two differ by 2.6% - enough to move a `k` of 2 by 0.05 sigma and
        not enough for anyone to notice it was the wrong one.
        """
        n = len(self._seen)
        if n < 2:
            return 0.0
        mean = sum(self._seen) / n
        return (sum((v - mean) ** 2 for v in self._seen) / n) ** 0.5


class Band:
    """One estimator over one span, whichever of the eleven it is.

    The Nautilus averages are driven with the close; `centroid` with the
    typical price; `rmin` and `rmax` read the window's extremes of the low and
    the high respectively, which is what a Donchian edge is - a rolling max of
    closes is not the level anybody is watching.
    """

    __slots__ = ("_inner", "_roll", "kind", "side", "sigma_k", "span")

    def __init__(self, kind: str, span: int, *, side: int = 0, sigma_k: float = 2.0) -> None:
        self.kind = kind
        self.span = int(span)
        #: Which edge this band is, for a kind that has two. `sigma` is the
        #: only one so far: the upper edge for a long, the lower for a short,
        #: which falls out of `Bands` keeping one pair per side anyway.
        self.side = int(side)
        self.sigma_k = float(sigma_k)
        self._inner: Any = None
        self._roll: Rolling | None = None
        if kind in AVERAGES:
            from nautilus_trader.indicators.averages import (
                MovingAverageFactory,
                MovingAverageType,
            )

            if kind == "adaptive":
                # **The factory returns `None` for `ADAPTIVE`.** Kaufman's AMA
                # takes a fast and a slow period on top of the efficiency
                # window, and `MovingAverageFactory.create(span, ADAPTIVE)`
                # returns nothing rather than raising - so `_inner` was None
                # and every read of it asserted. Built directly, with the
                # conventional 2 and 30.
                from nautilus_trader.indicators.averages import AdaptiveMovingAverage

                self._inner = AdaptiveMovingAverage(self.span, 2, 30)
            elif kind == "wma":
                # **The factory's `WEIGHTED` is an SMA.**
                # `WeightedMovingAverage(span, weights=None)` averages with
                # equal weights, so `wma` and `sma` returned byte-identical
                # results - 76 positions and -470.16 on both - and a sweep
                # would have counted one estimator as two cells, inflating its
                # own trial count and able to report the same winner twice.
                #
                # Linear weights `1..n`, which is what a weighted moving
                # average conventionally means.
                from nautilus_trader.indicators.averages import WeightedMovingAverage

                self._inner = WeightedMovingAverage(
                    self.span, [float(i + 1) for i in range(self.span)]
                )
            else:
                self._inner = MovingAverageFactory.create(
                    self.span, MovingAverageType[AVERAGES[kind]]
                )
            if self._inner is None:
                raise ValueError(
                    f"nautilus built no {kind!r} average at span {self.span}; a band that "
                    f"cannot be built must not become a cell that reads zero"
                )
        else:
            self._roll = Rolling(self.span)

    def update(self, bar: Bar) -> None:
        if self._inner is not None:
            self._inner.update_raw(float(bar.close))
            return
        assert self._roll is not None
        if self.kind == "centroid":
            self._roll.update((float(bar.high) + float(bar.low) + float(bar.close)) / 3.0)
        elif self.kind == "sigma":
            self._roll.update(float(bar.close))
        elif self.kind == "rmin":
            self._roll.update(float(bar.low))
        else:
            self._roll.update(float(bar.high))

    def plausible(self, close: float) -> bool:
        """Whether this band is a price at all, rather than a warm-up artefact.

        **`initialized` is not enough.** `VariableIndexDynamicAverage` reports
        `initialized=True` after its span while reading **0.7745 on data
        around 1.1000** - its recursion starts from zero and converges over
        far more bars than its period. A band at 70% of the price is not a
        level anybody is watching, and trading a cross against it would be
        trading the warm-up.

        A factor of two either way, which no real estimator of recent price
        approaches and which catches an unconverged recursion on any feed
        whatever its scale - `a-synthetic-at-price-one-hides-scale-bugs` is
        why this is a ratio rather than a distance.
        """
        value = self.value
        return close > 0.0 and 0.5 * close <= value <= 2.0 * close

    @property
    def initialized(self) -> bool:
        if self._inner is not None:
            return bool(self._inner.initialized)
        assert self._roll is not None
        return self._roll.initialized

    @property
    def value(self) -> float:
        if self._inner is not None:
            return float(self._inner.value)
        assert self._roll is not None
        if self.kind == "centroid":
            return self._roll.mean
        if self.kind == "sigma":
            # **A level, not a volatility reading.** `k` sigma either side of
            # the window's own mean, which is the only form of this that is a
            # price a participant could be watching. The side is the band's,
            # so a long tests the upper edge and a short the lower.
            spread = self.sigma_k * self._roll.stdev
            return self._roll.mean + (spread if self.side >= 0 else -spread)
        return self._roll.lowest if self.kind == "rmin" else self._roll.highest


class BandProfile(Profile):
    """The rule's identity and its per-side numbers.

    Built with `__new__` and no `__init__`, as `Surprise` and the statespace
    profiles are: a profile is configuration and two instances of one strategy
    on two instruments share it.
    """

    name: ClassVar[str] = "bands"
    description: ClassVar[str] = "moving bands: 8 averages, centroid, rolling min and max"
    #: Its own shape, so a statespace proposal on the same bus is skipped
    #: rather than counted as unwanted - the reason `StructureProfile` has one.
    shape: ClassVar[str] = "bands"
    style: ClassVar[str] = "swing"
    interval: ClassVar[str] = "15m"
    atr_period: ClassVar[int] = DEFAULT_ATR_PERIOD
    hold_bars: ClassVar[float] = 0.0
    hold_seconds: ClassVar[float] = 0.0


class Bands:
    """The band rule: fold two estimators, signal on a turn, size off an ATR.

    A mixin rather than a `Desk` subclass, matching `Structure`: the leaf
    classes at the foot of this module compose it with an entry and an exit.
    """

    profile: ClassVar[BandProfile] = BandProfile.__new__(BandProfile)

    def on_start(self) -> None:
        """Build the bands and the ATR, register the ATR, then start the desk.

        Registration before `super()`, which subscribes: the two orders are
        indistinguishable on a live feed and differ in a backtest, which
        delivers the first bar immediately.

        The ATR is built here rather than named in the config because
        `node/desks.build` writes the config and sets no indicators - a rule
        whose stop needs one would otherwise be deployable with it missing.
        """
        from nautilus_trader.indicators.volatility import AverageTrueRange

        tuning = Tuning.read()
        self.tuning = tuning
        self.atr = AverageTrueRange(self.profile.atr_period)
        self.register_indicator_for_bars(self._cfg.bar_type, self.atr)
        #: One pair per side, because the spans are tilted per side and a
        #: shared pair would make the asymmetry unreadable.
        self.bands: dict[int, tuple[Band, Band]] = {
            sign: (
                Band(
                    tuning.kind,
                    tuning.span_for(tuning.fast, sign),
                    side=sign,
                    sigma_k=tuning.sigma_k,
                ),
                Band(
                    tuning.kind,
                    tuning.span_for(tuning.slow, sign),
                    side=sign,
                    sigma_k=tuning.sigma_k,
                ),
            )
            for sign in (1, -1)
        }
        #: The last side each pair said, so a signal is a *turn* and not a
        #: state. A rule that fires on every bar the fast band sits above the
        #: slow one is a rule that re-enters a held position on every bar, and
        #: the desk refuses it as already held - which reads as a gate count
        #: rather than as the design error it is.
        self.standing: dict[int, int] = {1: 0, -1: 0}
        self.counts: dict[str, int] = {"bars": 0, "turns": 0, "unwarmed": 0}
        super().on_start()

    def on_bar(self, bar: Bar) -> None:
        """One closed bar into both pairs, and any turn it produced.

        Nautilus delivers an aggregated bar when its interval ends, so this
        close is final.
        """
        super().on_bar(bar)
        self.counts["bars"] += 1
        for sign, (fast, slow) in self.bands.items():
            # **Read the band before folding this bar into it.**
            #
            # A level price is compared against must not contain that price.
            # In `break` mode `rmax` is the window's highest *high*, so a
            # window including the current bar makes `close > rmax` need
            # `close == high` exactly - the rule placed **one position over
            # 5,135 bars** before this, which reads as a rare signal rather
            # than as an impossible one. `rmin` had the mirror of it.
            #
            # Applied to every kind and not only the extremes. A moving
            # average conventionally includes the current close, but a rule
            # that crosses a band containing its own trigger is reading the
            # trigger twice, and `open-gap-filters-are-lookahead` is the
            # standing cost of deciding that case by convention.
            warm = fast.initialized and slow.initialized
            close = float(bar.close)
            plausible = warm and fast.plausible(close) and slow.plausible(close)
            side = self._side(fast, slow, bar) if plausible else 0
            fast.update(bar)
            slow.update(bar)
            if not warm:
                self.counts["unwarmed"] += 1
                continue
            if not plausible:
                # Counted and not logged: on `vidya` this is most of the early
                # run, and a line per bar would be the whole log.
                self.counts["implausible"] = self.counts.get("implausible", 0) + 1
                continue
            if side == 0 or side == self.standing[sign]:
                self.standing[sign] = side or self.standing[sign]
                continue
            self.standing[sign] = side
            if side == -sign and self.tuning.exit_on_turn:
                self._leave(sign)
            if side != sign:
                # Each pair trades its own side only, so the asymmetric spans
                # are attributable: a long taken on the short pair's spans
                # would make the tilt unreadable in the result.
                continue
            self.counts["turns"] += 1
            # Through `on_data` rather than `consider`, because that is where
            # the desk counts what it took and follows what it declined.
            self.on_data(self._payload(side, fast, slow, bar))

    def _leave(self, sign: int) -> None:
        """Close anything this pair opened, because its own signal reversed.

        Through `close_all_positions` on the desk's instrument rather than by
        position id: this rule holds at most one position per side and the
        desk refuses a second, so there is nothing to disambiguate, and a
        lookup that returned nothing would be indistinguishable from a close
        that failed.
        """
        self.counts["turns_out"] = self.counts.get("turns_out", 0) + 1
        try:
            self.close_all_positions(self._cfg.instrument_id)
        except Exception as exc:  # a failed close is counted, not fatal
            self.counts["close_failed"] = self.counts.get("close_failed", 0) + 1
            self.log.warning(f"the {sign:+d} pair turned and the close failed: {exc}")

    def _side(self, fast: Band, slow: Band, bar: Bar) -> int:
        """Which way this pair reads now: +1, -1, or 0 for neither."""
        if self.tuning.mode == "break":
            # Price through the slow band. The fast one is not consulted, so a
            # `break` cell is a one-estimator rule and its `fast` column is
            # there for the record rather than for the signal.
            close, level = float(bar.close), slow.value
            if level <= 0.0:
                return 0
            return 1 if close > level else (-1 if close < level else 0)
        if fast.value <= 0.0 or slow.value <= 0.0:
            return 0
        return 1 if fast.value > slow.value else (-1 if fast.value < slow.value else 0)

    def _payload(self, side: int, fast: Band, slow: Band, bar: Bar) -> dict[str, Any]:
        """The turn as the payload `Desk.consider` reads.

        Handed to `on_data` rather than published: the reading is this
        strategy's own and a bus delivery would have every other desk count it
        as unwanted.
        """
        return {
            "feed": self._feed_name(),
            "shape": self.profile.shape,
            "interval": self.profile.interval,
            "direction": side,
            "features": {
                # `ma_atr` with `ma_close` as its anchor, **not** `vol_bps`:
                # that column is a folded log variance elsewhere on this desk
                # and an ATR in it would put one journal column in two
                # estimators. `exits._trail_vol_bps` does the conversion.
                "ma_atr": float(self.atr.value) if self.atr.initialized else 0.0,
                "ma_close": float(bar.close),
                "ma_fast": float(fast.value),
                "ma_slow": float(slow.value),
                "ma_fast_span": float(fast.span),
                "ma_slow_span": float(slow.span),
                "ma_stop_vol": self.tuning.stop_for(side),
                "ma_target_r": self.tuning.target_r,
            },
        }

    def wants(self, payload: dict[str, Any]) -> bool:
        """Only this rule's own shape."""
        return str(payload.get("shape") or "") == self.profile.shape

    def decide(self, payload: dict[str, Any]) -> Intent | Refusal | None:
        """The turn as an order, or a refusal naming the gate that stopped it."""
        feed = str(payload.get("feed") or "")
        sign = int(payload.get("direction") or 0)
        if sign == 0:
            return Refusal(gate="direction", detail="the turn took no side", feed=feed)
        side = Side.BUY if sign > 0 else Side.SELL

        features = payload.get("features") or {}
        if not isinstance(features, dict):
            return Refusal(gate="features", detail="no features on the turn", feed=feed)

        atr = float(features.get("ma_atr") or 0.0)
        if atr <= 0.0:
            # The ATR warms in 14 bars and the slow band needs at least 3, so
            # on the default spans this is a guard rather than a traded path.
            return Refusal(gate="atr", detail=f"the ATR reads {atr:.6g}", feed=feed)

        tick = self._tick()
        if tick is None:
            return Refusal(gate="no-quote", detail=f"{feed} has no cached quote", feed=feed)
        entry = tick.ask if side is Side.BUY else tick.bid
        if entry <= 0.0:
            return Refusal(gate="bad-quote", detail=f"{feed} quoted {entry}", feed=feed)

        # The stop is volatility units of ATR, per side. The ATR is a price
        # distance already, so no conversion: `stop_vol` multiplies it.
        reach = float(features.get("ma_stop_vol") or DEFAULT_STOP_VOL) * atr
        if reach <= 0.0:
            return Refusal(gate="stop", detail="a zero stop distance", feed=feed)
        stop = entry - sign * reach
        target_r = float(features.get("ma_target_r") or 0.0)

        return Intent(
            feed=feed,
            symbol=self._cfg.instrument_id.symbol.value,
            # Zero: `Desk.consider` sizes it. Two places computing a size is
            # how they come to disagree.
            volume=0.0,
            side=side,
            entry=entry,
            stop=stop,
            target=entry + sign * reach * target_r if target_r > 0.0 else 0.0,
            reason=(
                f"{self.tuning.kind} {self.tuning.mode} "
                f"{'up' if side is Side.BUY else 'down'} on {feed}"
            ),
            interval=self.profile.interval,
            features={str(k): float(v) for k, v in features.items()},
            hold=0.0,
        )


class BandsEdge(Bands, ManagedExit, EdgeEntry):
    """A band turn taken at market."""


class BandsResting(Bands, ManagedExit, RestingEntry):
    """A band turn left as a limit at the price it named."""


class BandsArrival(Bands, ManagedExit, ArrivalEntry):
    """A band turn parked until price comes back to it and a bar confirms."""
