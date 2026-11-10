"""The gate sequence and the journal reasons, shared by every entry.

A Nautilus `Strategy` per entry mechanism, over one shared base. The design is
`docs/specs/2026-10-31-service-becomes-nautilus-strategies.md`. Subclasses
differ in exactly one thing: `place`, how an accepted intent reaches
the venue. Everything before that is identical and lives here, because the
gates are the part the journal reads.

## Why one strategy per entry, and not one `Trader`

`service.Trader` runs every rule inside one object and tells them apart by a
broker magic number. `DEFAULT_MAGIC` is `777_701`, and the desk has recorded
what that costs: **off by one relabels every strategy as its neighbour**, which
is why the standing instruction is to judge the desk on the broker rather than
on the journal.

Nautilus puts a `strategy_id` on every order, fill and position, assigned by
the framework and carried through the lifecycle. One strategy per rule makes
that bug class **impossible** rather than guarded against.

It also deletes `_take_all`, `_agree` and `_also_wanted` - about 200 lines
whose job was to let several rules consider one signal and reconcile what each
wanted. Nautilus runs strategies side by side; each sees the data and acts or
does not.

## The order of the gates is the design

`Trader.on_signal` carries a note worth repeating rather than paraphrasing:
*the order is the design, and splitting it across helpers would hide it. Each
return is a distinct way a signal stops being a trade, and each one is recorded
differently.* So `consider` below is one sequence, read top to bottom, and the
gates are not factored into helpers that would let the order drift.

## Counted is not journalled, and the difference is deliberate

Two tallies, because a refusal rate and a refusal record answer different
questions.

* `passed_over` counts **every** gate, including the ones that fire hundreds of
  times a day. A strategy declining on probability or interval is the filter
  working, and journalling all of it would bury the refusals that matter.
* The journal records the ones a person would want to read back: an instrument
  the desk *does* trade, refused for a reason nothing else recorded.

Getting this backwards in either direction is a real cost. Journal everything
and the record is noise; count everything and nothing is explicable.

## What this does not do

**It does not size, and it does not decide the day's limits.** `plans` bounds
the loss, `risk` decides whether this account may take another trade, and
Nautilus's `RiskEngine` is the last-line notional and rate cap. Risk is *not*
pluggable - checked on 1.221.0, `RiskEngine`'s whole public surface is
`set_max_notional_per_order`, `set_trading_state` and `reset` - so ours sits
above it and not inside.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import Any

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType, QuoteTick
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.strategy import Strategy as NautilusStrategy

from ..domain.models import Intent, Refusal, Side, SymbolSpec, Tick
from ..risk import forecast, sizing
from ..utils.topics import PROPOSALS, VOLATILE, subscribe
from . import sizes
from .config import Settings
from .counterfactual import Counterfactual, Resolved
from .timeframes import Frames, seconds_of


class DeskConfig(StrategyConfig, frozen=True):
    """What one entry strategy trades, and under which decision rule."""

    instrument_id: InstrumentId
    bar_type: BarType
    #: Kept for configs that name a rule. **Read by nothing**: the decision
    #: is the class, composed from a mixin in `surprise.py`, so which rule runs
    #: is which class `node/desks.py` built rather than a string looked up in
    #: a registry. Left in place so an existing config still loads.
    rule: str = "statespace-surprise"
    #: Coarser frames to read for state, never to fire on. Empty by default,
    #: so nothing changes for a strategy that does not ask.
    #:
    #: **A trigger on a coarse frame is a different strategy on that frame**,
    #: not this one with context, so `timeframes.Frames` refuses a context
    #: frame finer than or equal to the signal frame. The look-ahead this
    #: exists to prevent - reading the H1 bar that *contains* the M15 signal,
    #: three quarters of which is in the future - is enforced by
    #: `Frames.ready` rather than left to a caller.
    context_bar_types: tuple[BarType, ...] = ()
    #: Detectors from `till_infinity.indicators` to register, as `name` or
    #: `name:source`. Empty by default - an indicator nothing reads still
    #: costs a fold per bar.
    indicators: tuple[str, ...] = ()
    #: Follow the trades this strategy wanted and did not get.
    #:
    #: **On by default, and it should stay on.** The deflated Sharpe's
    #: `Var(SR_trials)` is a variance over the whole search, so a record that
    #: drops what was declined makes every DSR optimistic - and the failure is
    #: silent, because the number still prints. See `counterfactual.py`.
    follow_untaken: bool = True
    #: How long a declined trade is followed, in hours.
    follow_hours: float = 1.0
    #: Widest spread worth dealing, in volatility units. Above it the round
    #: trip is a bar range and the idea is over before it starts, which is what
    #: costing exotics first established.
    max_spread_vol: float = 0.5
    #: Refuse an entry within this long of the session close, in hours.
    closing_within_hours: float = 0.5


#: Seconds between tally lines, matching `StatespaceActor`'s cadence so a
#: reader comparing the two is comparing like with like.
TALLY_EVERY = 300.0


class Desk(NautilusStrategy):
    """One entry mechanism, over the shared gates.

    Subclasses implement `place`. They may also override `on_bar` to add their
    own trigger - a resting entry watches for price turning against it, an
    arrival entry watches for a bar that confirms - but they call `consider`
    for the decision rather than re-deriving it.
    """

    def __init__(self, config: DeskConfig) -> None:
        super().__init__(config)
        self._cfg = config
        self.settings = Settings.from_env()
        #: Every gate that has fired, by `rule:gate`. Counted, not journalled.
        self.passed_over: dict[str, int] = {}
        self.refused = 0
        self.taken = 0
        self.detectors: dict[str, Any] = {}
        #: The clocks this desk reads. Built here so a strategy can ask what
        #: was knowable at a bar's close without each one keeping its own
        #: book of which frame last closed when.
        self.frames = Frames(
            signal=str(config.bar_type),
            context=tuple(str(frame) for frame in config.context_bar_types),
        )
        #: The highest account equity this strategy has seen, which is what
        #: `scaling.by_drawdown` tapers against. Equity is account-wide, so
        #: every strategy on one account converges on the same figure.
        #:
        #: **It is a high-water mark since start-up, not since the account's
        #: peak**, so a restart after a drawdown forgets the peak and sizes
        #: full. Said here rather than hidden: the alternative is persisting a
        #: peak, and a stale persisted peak would taper a recovered account
        #: for ever. The multiplier is off by default either way.
        self._peak = 0.0
        self.counterfactual = Counterfactual()
        #: What the counterfactual has resolved, newest last. Kept rather than
        #: only logged so a run can be asked what its declined trades were
        #: worth - which is the number the trial count depends on.
        self.resolved: list[Resolved] = []
        #: Bar types the volatility screen currently admits. Empty until one
        #: is published, which `_volatile_enough` treats as "refuse" rather
        #: than "admit everything" - see there for why.
        self._admitted: list[str] = []
        #: The volatility forecast a stop can be floored at. Fed in `on_bar`
        #: from this desk's own bars, so it is on the clock the desk trades
        #: rather than on whatever a producer happened to publish.
        self._forecast = forecast.RangeForecast()

    # ----------------------------------------------------------- the lifecycle

    @property
    def interval(self) -> str:
        """The clock this desk actually trades, read off its own `bar_type`.

        **Not `profile.interval`, which is the clock the rule was *measured*
        on.** Those were the same thing for as long as the node built every
        desk on `intervals()[0]`; once a rule fans out over `15m,1h,4h` the
        ClassVar is right for one of the four desks and wrong for three, and it
        is not a label - `Intent.interval` drives `scaling.by_interval`, and
        `domain/models.py` converts a hold through `SECONDS` with it. A 4h desk
        reporting `15m` would be sized by the wrong weight and would compute a
        span sixteen times too short, with every number still printing.

        Empty when the bar type is not a time clock, which is what `SECONDS`
        and `by_interval` already treat as "no interval" rather than guessing.
        """
        from ..utils.intervals import SECONDS

        span = seconds_of(self._cfg.bar_type)
        if span <= 0.0:
            return ""
        return next((name for name, secs in SECONDS.items() if secs == span), "")

    def _say_clock(self) -> None:
        """Say so when this desk trades a clock its rule was not measured on.

        **The one thing this repository's CLAUDE.md puts above everything
        else** is that the thing that measured an idea and the thing that
        trades it are the same thing. Fanning a rule over `15m,1h,4h` breaks
        that by construction for three desks of four, and the break is
        otherwise invisible: the desk starts, subscribes, warms and proposes,
        and nothing it logs mentions a clock at all.

        So it reports and never refuses. A slower clock is a legitimate thing
        to run - `bjorgum.md` measured this desk's zone findings at 15m, 1h and
        4h and the strongest cell on the book is at 4h - but it is a different
        experiment from the one the rule's own numbers came from, and a reader
        of the log should not have to infer that from the bar type.
        """
        # `getattr` on `self` and not on `self.profile`: `profile` is declared
        # by each rule's mixin rather than by this base, so a desk composed
        # without one - every entry-mechanism test double - has no attribute
        # to read and this ran before the first bar of all of them.
        measured = str(getattr(getattr(self, "profile", None), "interval", "") or "")
        traded = self.interval
        if measured and traded and traded != measured:
            self.log.warning(
                f"{self._cfg.rule} is specified and measured on {measured} and this "
                f"desk trades {traded}: a different experiment, not a slower view of "
                f"the same one. Sizing and holds follow {traded}."
            )

    def on_start(self) -> None:
        """Build the rule, register the detectors, then subscribe.

        Registration before subscription, so an indicator cannot miss the first
        bar. The two orders are indistinguishable on a live feed and differ in
        a backtest, which delivers the first bar immediately.
        """
        self._say_clock()
        self._register()
        self.subscribe_bars(self._cfg.bar_type)
        for frame in self._cfg.context_bar_types:
            self.subscribe_bars(frame)
        if self._cfg.context_bar_types:
            self.log.info(f"context frames: {', '.join(str(f) for f in self.frames.context)}")
        self.subscribe_quote_ticks(self._cfg.instrument_id)
        # **The readings this desk decides on.** Nothing subscribed to
        # `statespace.proposals` after the port: `service.py` consumed it and
        # `StatespaceActor` publishes it, so for weeks there was a producer
        # with no consumer - and a producer whose own tally counts what it
        # sent looks healthy from either side. That shape has now hidden this
        # one topic twice, which is why the subscribe sits next to the bars
        # rather than somewhere a reader has to go looking for it.
        subscribe(self, PROPOSALS, self.on_data)
        # **The volatility ranking, if one is being published.** Subscribed
        # unconditionally and acted on only when `TRADING_VOLATILE_ONLY` is
        # set: a desk that subscribes to a topic nobody publishes costs one
        # handler, and a desk that gates on a ranking that never arrives would
        # refuse every trade for ever - which is the failure mode this desk has
        # on record three times under the name "consumer with no producer".
        subscribe(self, VOLATILE, self._on_ranking)
        self.log.info(f"{self._cfg.rule} on {self._cfg.bar_type}, proposals on {PROPOSALS}")
        # **Say what this desk is doing while it runs, not only when it stops.**
        # `taken`, `refused` and `passed_over` were logged in `on_stop` alone,
        # so on 2026-11-07 sixty-four desks ran nine hours and the only way to
        # learn whether a single swing had been confirmed was to stop the node.
        # The diagnosis that followed needed exactly this line. It reports and
        # never acts - a quiet desk is a legitimate state, not a fault.
        self.clock.set_timer(
            name=f"desk-tally-{self._cfg.rule}-{self._cfg.instrument_id}",
            interval=timedelta(seconds=TALLY_EVERY),
            callback=lambda _event: self._say_tally(),
        )

    def _tally_line(self) -> str:
        """The tally as a string, so a test can read it.

        Separated from the logging because Nautilus's `Logger` is a Cython
        object whose `info` is read-only and cannot be stubbed, so a test of
        the *content* has to be given something that returns it.
        """
        gates = dict(sorted(self.passed_over.items()))
        return (
            f"desk {self._feed_name()}: taken={self.taken} refused={self.refused} "
            f"gates={gates or {}}{self._tally_extra()}"
        )

    def _say_tally(self) -> None:
        """One line: which desk, what was taken, what was refused, and what ate
        the rest.

        **The feed is on it because two diagnoses this weekend turned on not
        having it.** One class serves thirty instruments, so
        `gates={'statespace-surprise:cost': 1}` named no instrument: the cost
        readings of 2026-11-08 had to be attributed by re-running the rule
        offline on every crypto and matching the numbers, and a later one could
        not be attributed at all.
        """
        self.log.info(self._tally_line())

    def _tally_extra(self) -> str:
        """What a rule adds to the tally beyond the desk's own counters.

        Empty here. `Structure` overrides it with the fold's state, which is
        what distinguishes "no setups" from "no swings yet" - different
        failures that a trade count of zero cannot tell apart.
        """
        return ""

    def on_stop(self) -> None:
        """Say what it did, because a strategy that stops silently leaves no
        way to tell a quiet session from a broken one.

        The counterfactual is reported alongside the trades. A run that took
        three and declined four hundred is a different claim from one that took
        three and declined three, and the trial count is the difference.
        """
        self.log.info(
            f"taken {self.taken}, refused {self.refused}, "
            f"gates {dict(sorted(self.passed_over.items()))}"
        )
        self.log.info(
            f"counterfactual: {len(self.resolved)} resolved, "
            f"{self.counterfactual.following} still following"
        )

    def _register(self) -> None:
        """Hand the configured detectors to Nautilus.

        An unknown name raises rather than being skipped: a detector the config
        asked for and the strategy quietly did not build is a sweep reporting a
        null for a question it never asked.
        """
        from ..indicators import FRAMEWORK, build_detector

        for entry in self._cfg.indicators:
            name, _, rest = entry.partition(":")
            # **Ours and Nautilus's, named the same way.** `cusum:typical`
            # picks one of our detectors and the float it reads; `rsi:7` picks
            # one of the framework's and its period. One syntax, because a
            # strategy using both should not have to say which is which.
            if name in FRAMEWORK:
                detector = build_detector(name, period=int(rest) if rest else None)
            else:
                detector = build_detector(name, rest or None)
            self.register_indicator_for_bars(self._cfg.bar_type, detector)
            self.detectors[entry] = detector
            self.log.info(f"registered {entry} for {self._cfg.bar_type}")

    # ------------------------------------------------------------- the gates

    def wants(self, payload: dict[str, Any]) -> bool:  # noqa: ARG002
        """Is this signal this strategy's to judge at all?

        Default yes. A decision mixin overrides it so a signal on a shape or
        feed it does not cover costs nothing and is not counted as a refusal -
        it was never this strategy's to decline.
        """
        return True

    def decide(self, payload: dict[str, Any]) -> Intent | Refusal | None:
        """The decision. Supplied by a mixin - see `surprise.Surprise`.

        **Not an abstract method on a base class, which is what this
        replaced.** A `Strategy` ABC with an abstract `consider` made the
        decision a hierarchy, and the mechanism that placed it a separate one;
        a mixin with no base lets any decision compose with any entry, which
        is what "entries and exits are asymmetric" means in code.
        """
        raise NotImplementedError(
            f"{type(self).__name__} has no decision: compose it with a mixin "
            f"that supplies `decide`, as `surprise.SurpriseEdge` does."
        )

    def consider(self, payload: dict[str, Any]) -> Intent | Refusal | None:
        """One signal, through the gates in order, then the decision.

        `None` means *not for us* - no instrument, not our shape, nothing to
        record. A `Refusal` means *for us and declined*, and carries the gate
        that declined it. An `Intent` means place it.
        """
        spec = self._spec()
        if spec is None:
            # Counted, not journalled: an instrument this desk does not trade
            # is not a refusal, but a tally of nothing is a tally that cannot
            # be read.
            self._count("(desk):untraded")
            return None

        # ──── the feed, before the rule's own gates ────
        #
        # **`PROPOSALS` is one topic and every desk subscribes to it**, so a
        # proposal reaches all of them and not only the one whose instrument
        # it is about. `Surprise.wants` checked the payload's feed against its
        # *allowlist* - whether anybody may trade that feed - and nothing
        # checked it was **this** desk's feed, while `place` always sizes
        # `self._cfg.instrument_id`.
        #
        # On 2026-11-07 at 12:30:38 that turned one proposal, `surprise 5.66
        # on btcusd`, into BUY brackets on USDCAD, EURUSD, USDJPY, USDCHF,
        # Wall Street 30, US SP 500 and US Tech 100 - seven desks, 21 orders,
        # 119ms, each logging `btcusd` beside its own prices. EURUSD and
        # USDCHF were both bought, which is one exposure taken twice in
        # opposite directions. Only the closed weekend market saved it.
        #
        # Here rather than in `wants` because it is not a rule's judgement:
        # `place` can only size this desk's instrument, so a payload about
        # another feed is a category error for every rule, and a rule that
        # forgot the check would reintroduce it. `None` rather than a
        # `Refusal` because it was never this desk's to decline.
        feed = str(payload.get("feed") or "")
        if feed != self._feed_name():
            self._count("(desk):other-feed")
            return None

        if not self.wants(payload):
            self._count(f"{self.label}:unwanted")
            return None

        if refusal := self._barred(spec, payload):
            return refusal

        verdict = self.decide(payload)
        if isinstance(verdict, Refusal):
            self.refused += 1
            self._count(f"{self.label}:{verdict.gate}")
            # Debug and not the journal: this is the normal case, hundreds a
            # day, and recording all of it buries what matters.
            self.log.debug(f"{self.label} declined: {verdict.detail}")
            return verdict
        if not isinstance(verdict, Intent):
            return verdict
        return self._sized(verdict, spec, payload)

    def _sized(self, intent: Intent, spec: SymbolSpec, payload: dict[str, Any]) -> Intent | Refusal:
        """The accepted intent with a volume on it, or why it cannot have one.

        **Here and not in the three `place` methods.** Every entry mechanism
        needs a size, `consider` is the one thing all three run, and `Trader`
        is the record of what the alternative costs: the figure that has to be
        right to the cent was computed at three call sites and `share_of_risk`
        was folded into two of them.

        Here rather than in `decide` for a different reason. A decision is
        about the market and a size is about the account, and the producer that
        publishes the reading cannot see the account at all - which is why
        `Surprise.decide` reading `features["volume"]` was never going to
        return anything. See `sizes.py`.
        """
        equity = self._equity()
        self._peak = max(self._peak, equity)
        found = sizes.size(
            intent,
            spec=spec,
            settings=self.settings,
            equity=equity,
            profile=getattr(self, "profile", None),
            peak=self._peak,
            # The whole book, not this strategy's: a shared currency leg is
            # crowded by whoever is on it. `_already_held` has already refused
            # this instrument, so this is every *other* position.
            book=sizes.book_of(self.cache.positions_open()),
            rule=self._cfg.rule,
            # **The same positions, grouped by who opened them.** `crowding`
            # wants every position on a leg regardless of rule; `by_agreement`
            # wants them per rule, because a book of five rules that all point
            # one way is closer to one rule's risk than to five.
            by_rule=sizes.books_by_rule(self.cache.positions_open()),
        )
        if isinstance(found, Refusal):
            return self._refuse(found, payload)

        found = self._floor_target(self._floor_stop(found))

        # The broker's own minimum stop distance, checked before the order
        # rather than discovered by its retcode. This fires only where the
        # venue stated a `stops_level` and the geometry is inside it, in which
        # case the order would be rejected anyway - so it changes a venue
        # rejection into a record that says which number was breached.
        breach = sizing.respects_stops_level(spec, found.entry, found.stop, found.target)
        if breach:
            refusal = Refusal(gate="stops-level", detail=breach, feed=found.feed)
            return self._refuse(refusal, payload)
        return found

    def _floor_stop(self, intent: Intent) -> Intent:
        """Widen a stop the volatility forecast says is too tight.

        **A floor and never a replacement**, because a rule's stop distance is
        part of what was measured about that rule and
        `reproduce-the-baseline-before-an-increment` is the standing warning
        about swapping a model under a result - HAR read +0.036 against the
        shelf's +0.110 and the cause was the data window, not the model.

        Ordered **before** `_floor_target`, so `target_r` measures R against
        the floored stop. The two on different bases would be worse than
        either alone: a target in units of a stop the desk then widened is a
        reward-to-risk ratio that describes no trade that happened.

        Off unless `TRADING_FORECAST_BAND` is set, and an unwarmed forecast is
        a no-op - `risk/forecast.floored` returns the distance unchanged when
        it has no opinion, so a desk in its first fourteen bars behaves exactly
        as it did before.
        """
        if not self.settings.forecast_band or not self._forecast.ready:
            return intent
        risk = intent.risk
        if risk <= 0.0:
            return intent
        wanted = forecast.floored(risk, self._forecast.value)
        if wanted <= risk:
            return intent
        sign = 1 if intent.side is Side.BUY else -1
        return replace(
            intent,
            stop=intent.entry - sign * wanted,
            features={
                **intent.features,
                # Both numbers, because the journal has to show what the floor
                # changed and not only that it fired.
                "stop_floored_from": float(risk),
                "stop_forecast": float(self._forecast.value),
            },
        )

    def _floor_target(self, intent: Intent) -> Intent:
        """Give an intent a target where its rule shipped none.

        **Here, and not in any rule's `decide`.** Three live rules set
        `target=0.0` deliberately and say why in the same words - "a target
        invented here would be a different rule with better arithmetic" - and
        `smc-bos-causal` names its exit in the rule itself, where the `time` in
        `smc_bos_c_L50|M15|N20|time` is a 16-bar clock. Rewriting those would
        change the thing that was measured. Applying a floor **after** the
        decision leaves every rule's own code path identical, so the measured
        baseline is still what runs when the floor is off.

        Ordered before `respects_stops_level` on purpose: a target this
        supplies is checked against the broker's own minimum distance like any
        other, rather than being discovered by a retcode.

        `target_floored` goes on the features because the exit has changed. A
        later study that pooled floored trades with the rule's own stop-or-
        clock exits would be averaging two different rules, and
        `pooled-medians-invert-subgroups` is what that costs.
        """
        wanted = self.settings.target_r
        if wanted <= 0 or intent.target:
            return intent
        risk = intent.risk
        if risk <= 0:
            # No stop to measure against. `sizes.size` has already sized this
            # from the same distance, so a zero here means the rule gave an
            # entry equal to its stop and the trade is refused downstream -
            # inventing a target off a zero risk would put a price on nothing.
            return intent
        sign = 1 if intent.side is Side.BUY else -1
        return replace(
            intent,
            target=intent.entry + sign * wanted * risk,
            features={**intent.features, "target_floored": float(wanted)},
        )

    def _refuse(self, refusal: Refusal, payload: dict[str, Any]) -> Refusal:
        """Count, record and return a desk-level refusal of a wanted trade.

        Journalled rather than only counted, because these are exactly the
        case `_journal` was written for: an instrument the desk *does* trade,
        on a signal its rule *accepted*, refused for a reason nothing else
        holds. A rule declining on probability is the filter working; a trade
        the rule wanted and the account could not afford is a different fact
        and a rarer one.
        """
        self.refused += 1
        self._count(f"(desk):{refusal.gate}")
        self._journal(refusal, payload)
        return refusal

    def _journal(self, refusal: Refusal, payload: dict[str, Any]) -> None:
        """Record one refusal, for the half of it nothing else holds.

        **Exactly the split the module docstring describes**, implemented at
        last: these two gates refuse an instrument the desk *does* trade, for
        a reason no other record carries - the terminal called it untradable,
        the quote was missing, a sibling strategy already held it. Nautilus
        persists orders, fills and positions; it does not persist why there
        was no order - see
        [ADR 0005](../../docs/adr/0005-the-journal-is-the-record-not-the-hot-path.md).

        The per-decision refusals are deliberately **not** here. They are
        hundreds a day - a strategy declining on probability or interval is
        the filter working - and journalling them would bury these.

        **Nothing published here before.** `JournalActor` subscribed to a
        topic with no producer and every reason went to a debug log, which is
        the mirror of the failure the desk has already paid for twice: a
        subscriber with no publisher and a publisher with no subscriber look
        identical from either side, and both look like a quiet market.

        Failures are swallowed on purpose. This runs on the stack of a live
        decision - Nautilus's bus calls handlers inline - so a journal that
        cannot write must not stop a trade. The actor counts its own failures
        and degrades; that is where a write problem becomes visible.
        """
        from ..journal.actor import publish
        from ..journal.models import Entry, Kind

        try:
            publish(
                self,
                Entry(
                    title=f"{refusal.gate} on {refusal.feed or self.label}",
                    kind=Kind.DECISION,
                    actor=str(self.id),
                    rationale=refusal.detail,
                    context={
                        "gate": refusal.gate,
                        "feed": refusal.feed,
                        "rule": self.label,
                        "interval": str(payload.get("interval") or ""),
                    },
                    tags=("refusal", refusal.gate),
                ),
            )
        except Exception as exc:  # a record that cannot be written is not a halt
            self.log.debug(f"journal refused {refusal.gate}: {exc}")

    @property
    def label(self) -> str:
        """What this strategy is called in a gate tally.

        The profile's name where a decision mixin supplies one, and the class
        name otherwise - so a tally is readable either way rather than keyed on
        `None`.
        """
        profile = getattr(self, "profile", None)
        return getattr(profile, "name", "") or type(self).__name__

    def _undealable(self, spec: SymbolSpec, tick: Tick | None) -> Refusal | None:
        """Is the instrument dealable at all, right now?

        Three ways it is not, and each is about the venue rather than the idea:
        no quote, a quote too wide to pay, or a session about to close under a
        position that would then be held through a gap.
        """
        if not spec.tradable:
            return Refusal(gate="untradable", detail=f"{spec.symbol} is not tradable")
        if tick is None:
            return Refusal(gate="no-quote", detail=f"no quote for {spec.symbol}")
        if tick.ask <= 0.0 or tick.bid <= 0.0:
            return Refusal(gate="bad-quote", detail=f"{spec.symbol} quoted {tick.bid}/{tick.ask}")
        if tick.ask < tick.bid:
            # A crossed quote is a bad tick, not a tight spread. Folding it in
            # would make the cost read *better* than the truth, which is the
            # one direction of error that lets an idea through.
            return Refusal(
                gate="crossed", detail=f"{spec.symbol} bid {tick.bid} above ask {tick.ask}"
            )
        return None

    def _on_ranking(self, payload: Any) -> None:
        """Keep the latest volatility ranking. Published by `VolatileScreen`."""
        from .screening import ranked_bar_types

        self._admitted = ranked_bar_types(payload)

    def _barred(self, spec: SymbolSpec, payload: dict[str, Any]) -> Refusal | None:
        """Every desk-level refusal, in order, counted and recorded.

        Extracted because `consider` reached nine return statements and the
        ninth was a lint error rather than a reader's complaint - but the
        reader's version is the better reason: these three are the gates that
        are *not* a rule's judgement, and keeping them together says so.

        **The order is the cheap check first.** `_undealable` reads a cached
        quote, `_volatile_enough` reads a published list, `_already_held` walks
        the cache's positions. None of them is expensive and the order is not
        about speed: it is that an untradable instrument should be refused as
        untradable rather than as insufficiently volatile, because the gate
        name is what an operator reads off the tally.

        `_volatile_enough` is counted and **not journalled**, unlike the two
        either side of it. With the screen on, every desk outside the top share
        is refused on every signal - that is the gate working, not a wanted
        trade declined - and journalling it would write the quiet book's whole
        signal stream to disk. `_journal`'s own docstring draws that line.
        """
        if refusal := self._undealable(spec, self._tick()):
            self._count(f"(desk):{refusal.gate}")
            self._journal(refusal, payload)
            return refusal
        if refusal := self._volatile_enough():
            self._count(f"(desk):{refusal.gate}")
            return refusal
        if refusal := self._already_held():
            self._count(f"(desk):{refusal.gate}")
            self._journal(refusal, payload)
            return refusal
        return None

    def _volatile_enough(self) -> Refusal | None:
        """Refuse an instrument outside the current top share, when asked to.

        **Off unless `TRADING_VOLATILE_ONLY` is set**, and off is a no-op
        rather than a permissive default: a gate that silently admits
        everything reads the same as one that is working, and
        `venue-faults-hide-below-the-strategy` is what that costs.

        Refuses when the gate is on and **no ranking has arrived**, which is
        the opposite of the usual choice here and deliberate. A scalp whose
        whole premise is "only the volatile ones" has no fallback instrument
        set: admitting everything until the screener warms would trade the
        quiet book under a rule written for the loud one. `VolatileScreen`
        says so on its own tally, so the quiet period is visible rather than
        inferred.
        """
        if not self.settings.volatile_only:
            return None
        if not self._admitted:
            return Refusal(
                gate="no-ranking",
                detail="no volatility ranking has been published yet",
                feed=self._feed_name(),
            )
        if str(self._cfg.bar_type) in self._admitted:
            return None
        return Refusal(
            gate="not-volatile",
            detail=(
                f"{self._cfg.instrument_id.symbol} is outside the top "
                f"{len(self._admitted)} by range"
            ),
            feed=self._feed_name(),
        )

    def _already_held(self) -> Refusal | None:
        """Does anything already hold this instrument?

        **Across every strategy, not just this one.** `Trader` called this
        "first taker wins - two strategies wanting the same instrument is one
        idea found twice", and enforced it by running them in one object. The
        cache is shared, so the same guard is a query: `positions_open` is not
        filtered by `strategy_id` unless asked, so this sees the whole book.
        """
        held = self.cache.positions_open(instrument_id=self._cfg.instrument_id)
        if held:
            owners = sorted({str(p.strategy_id) for p in held})
            return Refusal(
                gate="held",
                detail=f"{self._cfg.instrument_id} already held by {', '.join(owners)}",
            )
        return None

    # ------------------------------------------------------------ the placing

    def place(self, intent: Intent) -> None:
        """Send an accepted intent. The one thing an entry decides."""
        raise NotImplementedError

    # ------------------------------------------------------------- the pieces

    def _spec(self) -> SymbolSpec | None:
        """This instrument's trading rules, from Nautilus's own instrument.

        Built from the cache rather than carried in config, so the venue is the
        authority on its own tick size and volume step - which is the thing
        `Trader` kept a parallel copy of and had to refresh.

        **Three fields used to be left on their dataclass defaults** - the tick
        value at 1.0, `stops_level` at zero and `tradable` at `True` - so the
        money conversion was a coincidence that happens to hold on the majors
        and two of `_undealable`'s gates could not fire. See `sizes.spec_of`.
        """
        instrument = self.cache.instrument(self._cfg.instrument_id)
        if instrument is None:
            return None
        return sizes.spec_of(
            instrument,
            rate=self._rate(instrument),
            account_currency=self._account_currency(),
        )

    def _account_currency(self) -> Any:
        """The currency the account is actually denominated in, or `None`.

        `base_currency` where the account states one. **This broker's does
        not** - it reports `base_currency=None` while holding a single
        `AccountBalance` in USD - and a single balance is the account's
        currency, because there is nothing else it could be. More than one and
        the account really is multi-currency, where there is no single answer.

        Only `sizes.spec_of` wants this, to know whether a stated tick value is
        comparable to `tick x contract` without a conversion. `None` is the
        safe answer: it skips that check rather than guessing.
        """
        account = self.portfolio.account(self._cfg.instrument_id.venue)
        if account is None:
            return None
        stated = getattr(account, "base_currency", None)
        if stated is not None:
            return stated
        try:
            held = list(account.currencies())
        except Exception:  # pragma: no cover - a venue account without the call
            return None
        return held[0] if len(held) == 1 else None

    def _rate(self, instrument: Any) -> float:
        """The instrument's quote currency in the account's, for sizing.

        1.0 where they are the same, which is the common case and the only one
        that needs no data: a dollar account trading dollar-quoted instruments.

        **0.0 where a conversion is needed and none is available**, which makes
        `lots` refuse with a reason rather than size against an invented rate.
        A yen pair mis-converted is wrong by a factor of 150, and the direction
        of the error depends on which way the mistake went - so there is no
        safe guess, only a refusal or a number the venue supplied.

        A multi-currency account reports no base currency. There is nothing to
        convert *to* in that case, so this returns 1.0 and the figures stay in
        the quote currency, which is what the balances are held in too.
        """
        account = self.portfolio.account(self._cfg.instrument_id.venue)
        wanted = getattr(account, "base_currency", None) if account is not None else None
        quote = instrument.quote_currency
        if wanted is None or wanted == quote:
            return 1.0
        found = self.cache.get_xrate(self._cfg.instrument_id.venue, quote, wanted)
        if not found:
            self.log.warning(
                f"no {quote}/{wanted} rate for {self._cfg.instrument_id}: "
                f"it cannot be sized until one is cached"
            )
            return 0.0
        return float(found)

    def _tick(self) -> Tick | None:
        """The last quote, in this desk's shape."""
        quote: QuoteTick | None = self.cache.quote_tick(self._cfg.instrument_id)
        if quote is None:
            return None
        return Tick(
            symbol=self._cfg.instrument_id.symbol.value,
            bid=float(quote.bid_price),
            ask=float(quote.ask_price),
            time=quote.ts_event / 1_000_000_000,
        )

    def _equity(self) -> float:
        """Account equity, or 0.0 when there is no account yet.

        Zero rather than a guess: a size computed from an invented equity is
        the one number nobody would catch.
        """
        return sizes.equity_of(self.portfolio.account(self._cfg.instrument_id.venue))

    def _feed_name(self) -> str:
        """The feed name the rules key on, from the instrument.

        One derivation, shared with the book `crowding` reads - see
        `sizes.feed_of`. It used to be a lower-case with the slash dropped,
        which is right for `EUR/USD` and leaves `Volatility 75 Index` with its
        spaces, so the counterfactual never resolved a synthetic: it compares
        this against the feed the producer published, and that one is slugged.
        """
        return sizes.feed_of(self._cfg.instrument_id)

    def _count(self, key: str) -> None:
        self.passed_over[key] = self.passed_over.get(key, 0) + 1

    def _protects(self) -> bool:
        """Whether this desk's rule wants a stop order at `Intent.stop` at all.

        **A rule that exits on a clock alone still has to be sized**, and a
        size is a budget divided by a distance, so `Intent.stop` on such a rule
        is a sizing distance with nothing defending it - see
        `Profile.protective_stop`, where the reason is written.

        Here on `Desk` and not on the entry, because two paths put a stop at
        the venue - `EdgeEntry` brackets or attaches one after the fill, and
        `ExitMechanism._attach` covers a position that reached one unbracketed
        - and a flag honoured by one of them is a rule that trades differently
        depending on which path ran first. True for every rule that does not
        say otherwise, and True where a desk carries no profile at all.
        """
        return bool(getattr(getattr(self, "profile", None), "protective_stop", True))

    # ----------------------------------------------------------- the handlers

    def on_bar(self, bar: Bar) -> None:
        """Nautilus delivers this after every registered indicator has updated.

        **Records which frame just closed, and decides nothing.** A bar is not
        a signal on this desk - the decision rules read published readings - so
        an entry that wants a bar trigger overrides this, and one that does not
        pays only the frame bookkeeping.

        An override that wants the context must call `super().on_bar(bar)` or
        `self.frames.ready` will never see a close. Nautilus delivers a bar at
        its close, so what is recorded here is always final.
        """
        self.frames.observe(bar.bar_type, bar.ts_event / 1e9, self.readings())
        self.observe_forecast(bar)

    def observe_forecast(self, bar: Bar) -> None:
        """Fold one bar into the stop-floor forecast. Live or replayed.

        **Only this desk's own signal frame.** A desk may be handed a context
        frame or, on `identity-arb`, a partner leg's bars - folding either
        would average two instruments' ranges and set a stop from neither,
        which is the shape that took a warmed ATR from 0.00132 to 0.62083 one
        level down.

        Called from the warm replay as well as from `on_bar`, because a desk
        that has to wait fourteen live bars for its stop floor is a desk whose
        first trades after every deploy are the ones the floor exists for -
        three and a half hours of them on a 15m clock.
        """
        if str(bar.bar_type) == str(self._cfg.bar_type):
            self._forecast.update(float(bar.high), float(bar.low), float(bar.close))

    def readings(self) -> dict[str, Any]:
        """What a frame's state is worth recording, per registered detector.

        Default is the detector values, which is what a context frame is for:
        a trend or a volatility reading from a slower clock. Overridden by a
        strategy that wants something else, and deliberately not the bar - a
        frame's bar is already in the cache and recording it here would
        duplicate it per frame.
        """
        return {name: getattr(detector, "value", None) for name, detector in self.detectors.items()}

    def on_data(self, data: Any) -> None:
        """A published reading. The gate sequence, then place or record.

        **Takes a bare dict as well as a wrapped one**, because the two ways a
        reading arrives here deliver different things. `subscribe_data` hands
        over a `Data` subclass with the payload on an attribute;
        `msgbus.subscribe` hands over the message itself, and
        `utils/topics.subscribe` says so - the bus does not pass the topic
        either.

        Unwrapping only would have made this silently return on every
        proposal: `getattr({}, "value", None)` is `None`, so the handler would
        run, find nothing and do nothing, for every reading statespace
        published. A consumer that is subscribed and inert looks exactly like
        a producer that is quiet.
        """
        payload = data if isinstance(data, dict) else None
        if payload is None:
            payload = getattr(data, "value", None) or getattr(data, "payload", None)
        if not isinstance(payload, dict):
            return
        verdict = self.consider(payload)
        if isinstance(verdict, Intent):
            self.taken += 1
            self.place(verdict)
        elif isinstance(verdict, Refusal):
            self._follow(verdict, payload)

    def _follow(self, refusal: Refusal, payload: dict[str, Any]) -> None:
        """Follow a trade a gate refused, where the rule said where it would go.

        A refusal carries the gate but not the geometry, so this asks the rule
        for the intent it would have built. Where it cannot - most gates refuse
        before there is an intent to build - there is nothing to follow and
        nothing is recorded: **a counterfactual invented from a refusal with no
        entry would be following a trade nobody specified.**
        """
        if not self._cfg.follow_untaken:
            return
        intent = payload.get("intent")
        if not isinstance(intent, Intent):
            return
        self.counterfactual.wanted(
            intent,
            by=self.label,
            now=self.clock.timestamp(),
            hold=self._cfg.follow_hours * 3_600.0,
            regime=float(payload.get("regime") or 0.0),
            market=str(payload.get("market") or ""),
        )
        self._count(f"(desk):following-{refusal.gate}")

    def on_quote_tick(self, tick: QuoteTick) -> None:
        """Walk the counterfactual forward. Subclasses that override this must
        call `super().on_quote_tick(tick)`, or the record stops resolving and
        `following` climbs forever."""
        done = self.counterfactual.observe(
            self._feed_name(),
            float(tick.bid_price),
            float(tick.ask_price),
            # **The tick's own time, not the clock's.** They agree in a
            # backtest, where the clock follows the data, and they do not when
            # a handler is driven directly - and `ts_event` is unambiguous
            # either way: it is when this quote happened.
            tick.ts_event / 1_000_000_000,
        )
        for row in done:
            self.resolved.append(row)
            self.log.info(f"{row.shape} {row.feed} {row.how} at {row.reward:+.2f}R")
