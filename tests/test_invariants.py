"""The trading service's risk invariants, checked by property, by state machine and exhaustively.

A backtest says a rule made money on one path. These say what the risk layer *guarantees* on every
path hypothesis can construct: that the account-level limits bind, that the clock-based vetoes are
exactly the windows they claim, that sizing never breaches its budget, and that the day's halt
lasts the day. See `research/docs/verification.md` for the invariant list and its sources.

Bounded for CI: set HYPOTHESIS_PROFILE=deep for a long run.
"""

from __future__ import annotations

import datetime as dt
import math
import os

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

from till_infinity.structures import rollover as ro
from till_infinity.trading import Settings, scaling, swap
from till_infinity.trading.models import Intent, Position, Side, SymbolSpec
from till_infinity.trading.risk import Guard, fx_window
from till_infinity.trading.sizing import lots

settings.register_profile("ci", max_examples=150, deadline=None)
settings.register_profile(
    "deep", max_examples=3000, deadline=None, suppress_health_check=[HealthCheck.too_slow]
)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "ci"))

UTC = dt.UTC


def at(text: str) -> float:
    return dt.datetime.fromisoformat(text).replace(tzinfo=UTC).timestamp()


# ------------------------------------------------------------------ an independent New York clock

#: 2026's US daylight-saving boundaries, written out rather than asked of zoneinfo, so the
#: exhaustive checks below do not share the implementation's source of truth.
DST_START = at("2026-03-08 07:00")  # 02:00 EST -> 03:00 EDT
DST_END = at("2026-11-01 06:00")  # 02:00 EDT -> 01:00 EST


def new_york(t: float) -> dt.datetime:
    offset = -4 if DST_START <= t < DST_END else -5
    return dt.datetime.fromtimestamp(t + offset * 3600, UTC).replace(tzinfo=None)


def weeks() -> list[float]:
    """Every minute of the two weeks that hold a DST change, and one ordinary week."""
    out = []
    for start in ("2026-03-05 00:00", "2026-10-29 00:00", "2026-07-13 00:00"):
        t0 = at(start)
        out += [t0 + 60 * m for m in range(8 * 24 * 60)]
    return out


# ------------------------------------------------------------------ exhaustive: clock vetoes


def test_fx_window_is_exactly_new_york_16_to_19_and_the_sunday_open_every_minute():
    s = Settings()
    for t in weeks():
        local = new_york(t)
        minute = local.hour * 60 + local.minute
        quiet = 16 * 60 <= minute < 19 * 60
        sunday_open = local.weekday() == 6 and 17 * 60 <= minute < 18 * 60
        got = fx_window(s, "eurusd", t)
        want = "fx_quiet_hour" if quiet else "fx_sunday_open" if sunday_open else None
        assert (got[0] if got else None) == want, (dt.datetime.fromtimestamp(t, UTC), local)
        assert fx_window(s, "xauusd", t) is None
        assert fx_window(s, "volatility_75_index", t) is None


def test_rollover_mask_is_exactly_16_55_to_17_10_new_york_every_minute():
    for t in weeks():
        local = new_york(t)
        minute = local.hour * 60 + local.minute
        want = 16 * 60 + 55 <= minute <= 17 * 60 + 10
        assert ro.masked("eurusd", t) == want, (dt.datetime.fromtimestamp(t, UTC), local)
        assert not ro.masked("xauusd", t)


def test_the_halt_lasts_exactly_the_utc_day_it_was_set_every_minute():
    s = Settings()
    s.daily_loss_fraction = 0.02
    s.quiet_hours = ()
    s.fx_quiet_ny = ()
    s.fx_sunday_open_min = 0.0
    loss_at = at("2026-07-15 13:37")
    for minute in range(0, 3 * 24 * 60, 7):
        t = loss_at + 60 * minute
        guard = Guard(s)
        guard.roll(10_000.0, now=loss_at - 3600)
        guard.record("eurusd", -300.0, 9_700.0, now=loss_at)
        assert guard.halted
        guard.roll(9_700.0, now=t)
        refused = guard.allows(_intent("xauusd", "XAUUSD"), positions=[], now=t)
        same_day = (
            dt.datetime.fromtimestamp(t, UTC).date()
            == dt.datetime.fromtimestamp(loss_at, UTC).date()
        )
        assert (refused is not None and refused.gate == "halted") == same_day, minute


def test_the_cooldown_is_exactly_its_length_every_second_near_the_edge():
    s = Settings()
    s.loss_cooldown = 900.0
    s.quiet_hours = ()
    s.fx_quiet_ny = ()
    s.fx_sunday_open_min = 0.0
    lost = at("2026-07-15 10:00")
    for dtime in range(880, 921):
        guard = Guard(s)
        guard.roll(10_000.0, now=lost - 60)
        guard.record("xauusd", -5.0, 9_995.0, now=lost)
        got = guard.allows(_intent("xauusd", "XAUUSD"), positions=[], now=lost + dtime)
        assert (got is not None and got.gate == "cooldown") == (dtime < 900), dtime


# ------------------------------------------------------------------ properties: sizing

specs = st.builds(
    SymbolSpec,
    symbol=st.just("X"),
    tick_size=st.sampled_from([0.00001, 0.001, 0.01, 0.1, 1.0]),
    tick_value=st.floats(0.01, 100.0),
    volume_min=st.sampled_from([0.01, 0.1, 1.0]),
    volume_max=st.sampled_from([10.0, 100.0, 1000.0]),
    volume_step=st.sampled_from([0.01, 0.1, 1.0]),
)


@given(
    spec=specs,
    equity=st.floats(1.0, 1e7),
    risk=st.floats(1e-5, 0.05),
    stop=st.floats(1e-5, 1e4),
    cap=st.one_of(st.just(0.0), st.floats(1.0, 1e5)),
    slip=st.floats(0.0, 1.0),
)
def test_a_sized_trade_never_risks_more_than_its_budget(spec, equity, risk, stop, cap, slip):
    assume(spec.volume_step <= spec.volume_min)
    got = lots(
        spec,
        equity=equity,
        risk_fraction=risk,
        stop_distance=stop,
        max_risk_money=cap,
        slippage=slip,
    )
    budget = equity * risk if cap <= 0 else min(equity * risk, cap)
    if got.ok:
        assert got.risk_money <= budget * (1 + 1e-6) + 1e-9
        assert spec.volume_min <= got.volume <= spec.volume_max
        steps = got.volume / spec.volume_step
        assert abs(steps - round(steps)) < 1e-6
    else:
        assert got.volume == 0


@given(
    spec=specs,
    equity=st.floats(100.0, 1e6),
    risk=st.floats(1e-4, 0.02),
    near=st.floats(1e-4, 100.0),
    factor=st.floats(1.0, 10.0),
)
def test_a_wider_stop_never_buys_more_lots(spec, equity, risk, near, factor):
    tight = lots(spec, equity=equity, risk_fraction=risk, stop_distance=near)
    wide = lots(spec, equity=equity, risk_fraction=risk, stop_distance=near * factor)
    assert wide.volume <= tight.volume + 1e-12


@given(
    spec=specs,
    equity=st.floats(100.0, 1e6),
    risk=st.floats(1e-4, 0.02),
    stop=st.floats(1e-4, 100.0),
    more=st.floats(1.0, 10.0),
)
def test_more_budget_never_buys_fewer_lots(spec, equity, risk, stop, more):
    small = lots(spec, equity=equity, risk_fraction=risk, stop_distance=stop)
    large = lots(spec, equity=equity * more, risk_fraction=risk, stop_distance=stop)
    assert large.volume + 1e-12 >= small.volume


@given(spec=specs, volume=st.floats(0.0, 2000.0))
def test_rounding_a_volume_is_downward_on_the_grid_and_idempotent(spec, volume):
    once = spec.round_volume(volume)
    assert once <= min(volume, spec.volume_max) + 1e-9
    assert spec.round_volume(once) == once
    steps = once / spec.volume_step
    assert abs(steps - round(steps)) < 1e-6


@given(st.lists(st.floats(-5.0, 5.0), min_size=0, max_size=8))
def test_combined_scaling_stays_in_its_band(values):
    got = scaling.combined(*values)
    assert scaling.FLOOR <= got <= 1.0


@given(
    st.lists(st.floats(0.0, 1.0), min_size=1, max_size=6), st.integers(0, 5), st.floats(0.0, 1.0)
)
def test_combined_scaling_is_monotone_in_every_reduction(values, which, lower):
    i = which % len(values)
    reduced = list(values)
    reduced[i] = min(values[i], lower)
    assert scaling.combined(*reduced) <= scaling.combined(*values) + 1e-12


@given(
    st.sampled_from(["1m", "3m", "5m", "15m", "1h", "4h", ""]),
    st.lists(
        st.tuples(st.sampled_from(["1m", "5m", "15m", "1h"]), st.floats(-2.0, 3.0)), max_size=4
    ),
)
def test_an_interval_weight_never_enlarges_a_trade(interval, weights):
    got = scaling.by_interval(interval, weights)
    assert scaling.FLOOR <= got <= 1.0 or got == 1.0


# ------------------------------------------------------------------ properties: the ZMA e-process


@given(calls=st.integers(0, 20_000), rate=st.floats(0.0, 1.0))
def test_a_record_at_or_under_a_coin_never_earns(calls, rate):
    right = math.floor(calls * min(rate, 0.5))
    assert not Settings().zma_earned(calls, right)


@given(calls=st.integers(200, 20_000), a=st.floats(0.0, 1.0), b=st.floats(0.0, 1.0))
def test_more_right_calls_never_unearn_a_record(calls, a, b):
    s = Settings()
    lo, hi = sorted((math.floor(calls * a), math.floor(calls * b)))
    if s.zma_earned(calls, lo):
        assert s.zma_earned(calls, hi)


# ------------------------------------------------------------------ properties: swap


@given(
    start=st.floats(at("2026-01-01 00:00"), at("2026-12-01 00:00")),
    hold=st.floats(0.0, 10 * 86_400.0),
    more=st.floats(0.0, 5 * 86_400.0),
    triple=st.sampled_from([3, 1, 7]),
)
def test_swap_nights_never_fall_as_a_hold_lengthens(start, hold, more, triple):
    assert swap.nights(start, hold + more, triple) >= swap.nights(start, hold, triple)


def next_roll(t: float) -> float:
    """The next 17:00 New York strictly after `t`, as a UTC instant, from the independent clock.

    Real elapsed time, not "24 hours later": the daylight-saving days are 23 and 25 hours long,
    which is exactly the case the first version of the property below got wrong."""
    local = new_york(t)
    day = (
        local.date()
        if (local.hour, local.minute, local.second) < (17, 0, 0)
        else (local.date() + dt.timedelta(days=1))
    )
    wall = dt.datetime.combine(day, dt.time(17, 0)).replace(tzinfo=UTC).timestamp()
    for offset in (-4, -5):  # the one whose UTC instant agrees with the offset it implies
        instant = wall - offset * 3600
        if (-4 if DST_START <= instant < DST_END else -5) == offset:
            return instant
    raise AssertionError("no consistent offset")


@given(
    start=st.floats(at("2026-01-01 00:00"), at("2026-12-01 00:00")),
    triple=st.sampled_from([3, 1, 7]),
)
def test_a_hold_that_ends_before_the_next_17_00_new_york_pays_no_swap(start, triple):
    hold = max(0.0, next_roll(start) - start - 120.0)
    assert swap.nights(start, hold, triple) == 0.0


def test_a_hold_across_the_23_hour_spring_forward_day_crosses_its_rollover():
    """The counterexample hypothesis found: Saturday 2026-03-07 17:00 New York, held 23h58m. The
    next day is 23 hours long, so the hold does cross Sunday's 17:00 - and a 24/7 symbol pays it."""
    start = at("2026-03-07 22:00")
    assert swap.nights(start, 86_280.0, 7) == 1.0
    assert swap.nights(start, next_roll(start) - start - 60.0, 7) == 0.0


@given(
    price=st.floats(1.0, 1e5),
    hold=st.floats(0.0, 10 * 86_400.0),
    side=st.sampled_from([Side.BUY, Side.SELL]),
    feed=st.sampled_from(sorted(swap.DERIV_FALLBACK)),
)
def test_swap_cost_is_never_negative(price, hold, side, feed):
    assert swap.expected(None, feed, side, price, at("2026-07-15 12:00"), hold) >= 0.0


# ------------------------------------------------------------------ properties: stops


@given(
    side=st.sampled_from([Side.BUY, Side.SELL]),
    risk=st.floats(0.1, 5.0),
    current_off=st.floats(-6.0, 3.0),
    run=st.floats(-3.0, 10.0),
    even_at=st.sampled_from([0.0, 0.5, 1.0]),
    trail=st.sampled_from([0.0, 1.0, 2.0]),
    vol=st.floats(0.0, 300.0),
    ticks=st.integers(0, 5),
)
def test_a_managed_stop_only_ever_tightens(
    side, risk, current_off, run, even_at, trail, vol, ticks
):
    from till_infinity.trading.manage import advance, better

    sign = side.sign
    entry = 100.0
    stop0 = entry - sign * risk
    current = stop0 + sign * current_off  # wherever an earlier move left it, maybe none tighter
    position = Position(1, "X", side, 0.1, entry, stop=current)
    intent = Intent(
        feed="x",
        symbol="X",
        side=side,
        volume=0.1,
        entry=entry,
        stop=stop0,
        target=entry + sign * 2 * risk,
    )
    s = Settings()
    s.break_even_at, s.trail_vol, s.break_even_ticks = even_at, trail, ticks
    spec = SymbolSpec(symbol="X", digits=3, tick_size=0.001)
    got = advance(position, intent, spec, s, best=entry + sign * run, vol_bps=vol)
    if got is not None:
        assert better(got.stop, current, side)  # never loosened, not even by rounding
    if run <= 0:
        assert got is None  # nothing moves a stop on a trade that has not gone our way


# ------------------------------------------------------------------ properties: the z-score's say


@given(
    calls=st.floats(0.0, 5000.0),
    rate=st.floats(0.0, 1.0),
    z=st.floats(-4.0, 4.0),
    side=st.sampled_from(["up", "down"]),
)
def test_the_z_score_veto_can_only_remove_a_trade_and_only_when_earned(calls, rate, z, side):
    from till_infinity.trading.strategies.scalper import CycleScalp, zma_gate

    s = Settings()
    right = calls * rate
    features = {"zma_z": z, "zma_strong": 1.0, "zma_edge_calls": calls, "zma_edge_right": right}
    got = zma_gate(CycleScalp(settings=s), {"direction": side, "feed": "v75"}, features)
    assert got is None or got.gate == "zma_against"
    if not s.zma_earned(calls, right):
        assert got is None


# ------------------------------------------------------------------ the state machine

FEEDS = [
    ("eurusd", "EURUSD"),
    ("gbpusd", "GBPUSD"),
    ("xauusd", "XAUUSD"),
    ("volatility_75_index", "Volatility 75 Index"),
    ("boom_1000_index", "Boom 1000 Index"),
]


def _intent(
    feed: str, symbol: str, side: Side = Side.BUY, risk: float = 1.0, reward: float = 2.0
) -> Intent:
    sign = side.sign
    return Intent(
        feed=feed,
        symbol=symbol,
        side=side,
        volume=0.1,
        entry=100.0,
        stop=100.0 - sign * risk,
        target=100.0 + sign * reward,
        interval="15m",
    )


class GuardMachine(RuleBasedStateMachine):
    """Drives one `Guard` through random days of signals, fills, closes and clock jumps, keeping an
    independent model of what it must have done, and checks every invariant after every step."""

    @initialize(
        max_positions=st.integers(1, 6),
        max_per_symbol=st.integers(1, 3),
        daily_loss=st.sampled_from([0.0, 0.01, 0.03]),
        cooldown=st.sampled_from([0.0, 300.0, 900.0]),
        quiet=st.sampled_from([(), (20, 21, 22, 23)]),
        fx_quiet=st.sampled_from([(), (16, 19)]),
        sunday=st.sampled_from([0.0, 60.0]),
        start=st.floats(at("2026-01-01 00:00"), at("2026-12-01 00:00")),
    )
    def setup(
        self, max_positions, max_per_symbol, daily_loss, cooldown, quiet, fx_quiet, sunday, start
    ):
        s = Settings()
        s.max_positions, s.max_per_symbol = max_positions, max_per_symbol
        s.daily_loss_fraction, s.loss_cooldown = daily_loss, cooldown
        s.quiet_hours, s.fx_quiet_ny, s.fx_sunday_open_min = quiet, fx_quiet, sunday
        s.min_reward_to_risk = 0.0
        s.max_currency_exposure = 0.0
        self.s = s
        self.now = start
        self.equity = 10_000.0
        self.guard = Guard(s)
        self.guard.roll(self.equity, now=self.now)
        self.positions: list[Position] = []
        self.ticket = 0
        self.model_day = self.guard.day
        self.model_open = self.equity
        self.model_realised = 0.0
        self.model_halted = False
        self.model_losses: dict[str, float] = {}

    def _day(self, t: float) -> str:
        return dt.datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%d")

    def _model_roll(self, t: float) -> None:
        if self._day(t) != self.model_day:
            self.model_day = self._day(t)
            self.model_open = self.equity
            self.model_realised = 0.0
            self.model_halted = False

    @rule(minutes=st.integers(1, 36 * 60))
    def wait(self, minutes):
        self.now += 60 * minutes
        self.guard.roll(self.equity, now=self.now)  # the service rolls on every cycle
        self._model_roll(self.now)

    @rule(which=st.integers(0, len(FEEDS) - 1), side=st.sampled_from([Side.BUY, Side.SELL]))
    def signal(self, which, side):
        feed, symbol = FEEDS[which]
        before = sum(self.guard.refusals.values())
        got = self.guard.allows(
            _intent(feed, symbol, side), positions=list(self.positions), now=self.now
        )
        after = sum(self.guard.refusals.values())
        if got is None:
            assert after == before  # an allowed trade counts no refusal
            # Everything that must be true of any trade the guard lets through:
            assert not self.guard.halted
            assert not self.model_halted
            assert fx_window(self.s, feed, self.now) is None
            assert dt.datetime.fromtimestamp(self.now, UTC).hour not in self.s.quiet_hours
            lost = self.model_losses.get(feed)
            assert not lost or self.now - lost >= self.s.loss_cooldown
            assert len(self.positions) < self.s.max_positions
            assert sum(p.symbol == symbol for p in self.positions) < self.s.max_per_symbol
            self.ticket += 1
            self.positions.append(Position(self.ticket, symbol, side, 0.1, 100.0))
        else:
            assert got.gate  # one refusal names exactly one gate
            assert after == before + 1  # and counts once
            if self.model_halted:
                assert got.gate == "halted"

    @rule(pick=st.integers(0, 50), profit=st.floats(-400.0, 300.0))
    def close(self, pick, profit):
        if not self.positions:
            return
        position = self.positions.pop(pick % len(self.positions))
        feed = next(f for f, sym in FEEDS if sym == position.symbol)
        self.equity += profit
        self._model_roll(self.now)
        self.guard.record(feed, profit, self.equity, now=self.now)
        self.model_realised += profit
        if profit <= 0:
            self.model_losses[feed] = self.now
        limit = self.model_open * self.s.daily_loss_fraction
        if limit > 0 and self.model_realised <= -limit:
            self.model_halted = True

    @invariant()
    def account_limits_bind(self):
        assert len(self.positions) <= self.s.max_positions
        for _, symbol in FEEDS:
            assert sum(p.symbol == symbol for p in self.positions) <= self.s.max_per_symbol

    @invariant()
    def the_guard_agrees_with_the_model(self):
        assert bool(self.guard.halted) == self.model_halted
        assert math.isclose(self.guard.realised, self.model_realised, abs_tol=1e-6)
        assert self.guard.day == self.model_day


TestGuardMachine = GuardMachine.TestCase
TestGuardMachine.settings = settings(
    max_examples=int(os.environ.get("HYPOTHESIS_STATEFUL_EXAMPLES", "60")),
    stateful_step_count=40,
    deadline=None,
)
