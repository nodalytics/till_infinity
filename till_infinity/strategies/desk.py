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

from typing import Any

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType, QuoteTick
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.strategy import Strategy as NautilusStrategy

from ..domain.models import Intent, Refusal, SymbolSpec, Tick
from .config import Settings
from .strategies import strategy as rules


class DeskConfig(StrategyConfig, frozen=True):
    """What one entry strategy trades, and under which decision rule."""

    instrument_id: InstrumentId
    bar_type: BarType
    #: The decision rule this entry asks. A name from `rules.catalogue()`;
    #: `statespace-surprise` is the one registered rule today.
    rule: str = "statespace-surprise"
    #: Detectors from `till_infinity.indicators` to register, as `name` or
    #: `name:source`. Empty by default - an indicator nothing reads still
    #: costs a fold per bar.
    indicators: tuple[str, ...] = ()
    #: Widest spread worth dealing, in volatility units. Above it the round
    #: trip is a bar range and the idea is over before it starts, which is what
    #: costing exotics first established.
    max_spread_vol: float = 0.5
    #: Refuse an entry within this long of the session close, in hours.
    closing_within_hours: float = 0.5


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
        self.rule: rules.Strategy | None = None
        #: Every gate that has fired, by `rule:gate`. Counted, not journalled.
        self.passed_over: dict[str, int] = {}
        self.refused = 0
        self.taken = 0
        self.detectors: dict[str, Any] = {}

    # ----------------------------------------------------------- the lifecycle

    def on_start(self) -> None:
        """Build the rule, register the detectors, then subscribe.

        Registration before subscription, so an indicator cannot miss the first
        bar. The two orders are indistinguishable on a live feed and differ in
        a backtest, which delivers the first bar immediately.
        """
        # `build` raises on an unknown name, listing what it has, so there is
        # no guard here: a second check would either be dead or would disagree
        # with the registry about what exists.
        self.rule = rules.build([self._cfg.rule], self.settings)[0]
        self._register()
        self.subscribe_bars(self._cfg.bar_type)
        self.subscribe_quote_ticks(self._cfg.instrument_id)
        self.log.info(f"{self._cfg.rule} on {self._cfg.bar_type}")

    def on_stop(self) -> None:
        """Say what it did, because a strategy that stops silently leaves no
        way to tell a quiet session from a broken one."""
        self.log.info(
            f"taken {self.taken}, refused {self.refused}, "
            f"gates {dict(sorted(self.passed_over.items()))}"
        )

    def _register(self) -> None:
        """Hand the configured detectors to Nautilus.

        An unknown name raises rather than being skipped: a detector the config
        asked for and the strategy quietly did not build is a sweep reporting a
        null for a question it never asked.
        """
        from ..indicators import build_detector

        for entry in self._cfg.indicators:
            name, _, source = entry.partition(":")
            detector = build_detector(name, source or None)
            self.register_indicator_for_bars(self._cfg.bar_type, detector)
            self.detectors[entry] = detector
            self.log.info(f"registered {entry} for {self._cfg.bar_type}")

    # ------------------------------------------------------------- the gates

    def consider(self, payload: dict[str, Any]) -> Intent | Refusal | None:
        """One signal against this strategy's rule. The gates, in order.

        `None` means *not for us* - no instrument, nothing to record. A
        `Refusal` means *for us and declined*, and carries the gate that
        declined it. An `Intent` means place it.
        """
        if self.rule is None:
            return None
        spec = self._spec()
        if spec is None:
            # Counted, not journalled: an instrument this desk does not trade
            # is not a refusal, but a tally of nothing is a tally that cannot
            # be read.
            self._count("(desk):untraded")
            return None

        self.rule.observe(payload)
        if not self.rule.wants(payload):
            self._count(f"{self.rule.name}:unwanted")
            return None

        tick = self._tick()
        if refusal := self._undealable(spec, tick):
            self._count(f"(desk):{refusal.gate}")
            return refusal

        if refusal := self._already_held():
            self._count(f"(desk):{refusal.gate}")
            return refusal

        verdict = self.rule.consider(
            payload,
            spec=spec,
            tick=tick,
            equity=self._equity(),
            positions=[],
            peak=self._equity(),
        )
        if isinstance(verdict, Refusal):
            self.refused += 1
            self._count(f"{self.rule.name}:{verdict.gate}")
            # Debug and not the journal: this is the normal case, hundreds a
            # day, and recording all of it buries what matters.
            self.log.debug(f"{self.rule.name} declined: {verdict.detail}")
            return verdict
        return verdict

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
        """
        instrument = self.cache.instrument(self._cfg.instrument_id)
        if instrument is None:
            return None
        return SymbolSpec(
            symbol=instrument.id.symbol.value,
            digits=instrument.price_precision,
            point=float(instrument.price_increment),
            tick_size=float(instrument.price_increment),
            volume_min=float(instrument.min_quantity or 0.0),
            volume_max=float(instrument.max_quantity or 0.0),
            volume_step=float(instrument.size_increment),
            tradable=True,
        )

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
        account = self.portfolio.account(self._cfg.instrument_id.venue)
        if account is None:
            return 0.0
        balance = account.balance_total()
        return float(balance.as_double()) if balance is not None else 0.0

    def _count(self, key: str) -> None:
        self.passed_over[key] = self.passed_over.get(key, 0) + 1

    # ----------------------------------------------------------- the handlers

    def on_bar(self, bar: Bar) -> None:
        """Nautilus delivers this after every registered indicator has updated.

        Deliberately empty here. A bar is not a signal on this desk - the
        decision rules read published readings - so an entry that wants a bar
        trigger overrides this, and one that does not pays nothing.
        """

    def on_data(self, data: Any) -> None:
        """A published reading. The gate sequence, then place or record."""
        payload = getattr(data, "value", None) or getattr(data, "payload", None)
        if not isinstance(payload, dict):
            return
        verdict = self.consider(payload)
        if isinstance(verdict, Intent):
            self.taken += 1
            self.place(verdict)
