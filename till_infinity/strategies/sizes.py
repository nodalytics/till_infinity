"""What the venue holds, as the numbers `risk/` sizes from.

**Nothing set `Intent.volume`.** `risk/sizing.lots` has been right since the
desk was a service, `Profile.multipliers` returns nine named reductions, and
`scaling.crowding` prices a shared currency leg - and on the Nautilus path none
of the three had a caller. A 5,136-bar replay accepted 25 intents and refused
all 25 at `(desk):zero-volume`, which is what a desk looks like when every gate
works and nobody does the arithmetic.

Three wires were missing, for three different reasons.

**The volume.** `Surprise.decide` reads it off the proposal's features, with a
comment saying the sizer put it there. No sizer ran, and none could: statespace
publishes a reading, not a size, and sizing needs the account's equity - a fact
about the venue that a producer reading bars never sees. So the step belongs
after the decision and before the order, which is `Desk.consider`, and it
belongs there once rather than in each of the three entry mechanisms.

**The spec.** `Desk._spec` built a `SymbolSpec` from the Nautilus instrument
and left `tick_value` on its dataclass default of 1.0. That is the worst
available failure, because 1.0 is *correct* for a standard lot of nearly every
dollar-quoted instrument this desk trades - 100,000 units at a 0.00001 tick, or
100 ounces of gold at 0.01 - and wrong for a yen pair, wrong for a synthetic,
and wrong for anything priced in a currency the account is not held in. A
sizing bug that is right on the majors is a sizing bug that ships. `stops_level`
and `tradable` were left on their defaults for the same reason, so two of the
three gates in `Desk._undealable` could not fire either.

**The book.** `scaling.crowding` wants `(feed, sign)` per open position, and
`Profile.multipliers` dug those out of whatever it was handed with
`getattr(p, "feed", "")`. A Nautilus `Position` carries an `instrument_id` and
a signed quantity and has no `feed` at all, so that expression discarded every
position and the crowding multiplier read 1.0 against a full book. It now takes
the pairs, and this module builds them: the one place that knows both how
Nautilus names an instrument and how this desk names a feed.

## Why this is its own module and not four methods on `Desk`

Because all four are worth testing without a running kernel. A `Strategy`
cannot be instantiated without a `TradingNode` or a `BacktestEngine` around it,
which is how `_spec`'s missing tick value survived: the only assertions anybody
could cheaply write were about the strategy's gates, and the arithmetic
underneath them was reachable only through a node nobody stood up in a test.
These are plain functions over a Nautilus instrument, a sequence of positions
and an intent, so the arithmetic is assertable on its own.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import replace
from typing import Any

from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.position import Position

from ..domain.models import Intent, Refusal, SymbolSpec
from ..risk import scaling, sizing

#: MT5 `trade_mode` values that mean an order cannot be opened:
#: `SYMBOL_TRADE_MODE_DISABLED` and `SYMBOL_TRADE_MODE_CLOSEONLY`.
#:
#: `LONGONLY` and `SHORTONLY` are **not** here, and that is a known gap rather
#: than a decision: they are tradable, so refusing them outright would drop an
#: instrument the desk can trade one way - but nothing below carries the
#: restriction, so a short on a long-only instrument reaches the venue and is
#: rejected there. `SymbolSpec` has no field for a one-sided instrument; adding
#: one belongs with the entry and exit asymmetry rather than here.
UNTRADABLE_MODES = frozenset({0, 3})


def equity_of(account: Any) -> float:
    """The account's total equity, whatever currency shape it declares.

    **`balance_total()` with no argument only works on a single-currency
    account.** Nautilus falls back to `self.base_currency` and raises
    `TypeError("'currency' argument was `None`")` when there is none - and the
    MT5 client declares `base_currency=None`, because an exec client is built
    before it has connected and so before the broker has said what the account
    is held in.

    That combination took the live desk down on 2026-11-05: every statespace
    proposal reached `Desk._sized`, asked for equity, and raised inside
    `Actor.on_bar`, so the actor logged a traceback per bar and **not one
    proposal was ever sized**. Quotes were flowing and the terminal was
    accepting orders; the only symptom was an exception in a handler.

    An MT5 account holds exactly one currency, so the multi-currency reading
    has a single entry and summing it is the same number. Summing rather than
    picking the first keeps it honest if a venue ever reports two: the figure
    would then be a sum of unlike units, which is wrong, so it refuses instead.
    """
    if account is None:
        return 0.0
    base = getattr(account, "base_currency", None)
    if base is not None:
        balance = account.balance_total()
        return float(balance.as_double()) if balance is not None else 0.0
    totals = account.balances_total() or {}
    if len(totals) > 1:
        return 0.0
    return sum(float(money.as_double()) for money in totals.values())


def feed_of(instrument_id: InstrumentId) -> str:
    """The feed name this desk's rules key on, from Nautilus's identifier.

    Lower-cased with the separator dropped: `EUR/USD` and `EURUSD` both become
    `eurusd`.

    **Not `exposure._slug`, which would be the tidier answer and is the wrong
    one.** That function turns `Volatility 75 Index` into
    `volatility_75_index` and its docstring says that is how a feed is keyed,
    but the producer disagrees: `StatespaceActor._payload` keys a feed as
    `feeds.get(symbol, symbol.lower())`, so an unmapped symbol with spaces
    keeps them. Those two derivations disagree on exactly the instruments that
    have a space in the name, and this one matches the producer - which is the
    one that has to match, because `Counterfactual.observe` compares this
    against the feed on a published intent.

    They agree on every key in `exposure.LEGS`, all of which are already
    lower-case and alphanumeric, so the currency decomposition and the crowding
    multiplier read the same either way. The disagreement is real but it is
    only about the naming of instruments the legs table does not carry.
    """
    return instrument_id.symbol.value.lower().replace("/", "")


def book_of(positions: Iterable[Position]) -> tuple[tuple[str, int], ...]:
    """Open positions as the `(feed, sign)` pairs `scaling.crowding` reads.

    `signed_qty` rather than `side`, because it answers the question directly:
    Nautilus's `PositionSide` is an enum with no sign on it, and mapping it
    would be a third place that has to agree about which way `LONG` is.

    A flat position is dropped. The cache can hold one briefly after a close,
    and counting it would crowd a leg nobody is on.
    """
    found = []
    for position in positions:
        quantity = float(getattr(position, "signed_qty", 0.0) or 0.0)
        if quantity == 0.0:
            continue
        found.append((feed_of(position.instrument_id), 1 if quantity > 0 else -1))
    return tuple(found)


def _stated(info: dict[str, Any], *names: str) -> float:
    """The first of `names` the venue gave a positive number for, else 0.0.

    Several names because MT5 states the same quantity under more than one
    key and the right one is not the obvious one - see `spec_of`.
    """
    for name in names:
        try:
            value = float(info.get(name) or 0.0)
        except (TypeError, ValueError):
            continue
        if value > 0.0:
            return value
    return 0.0


def spec_of(instrument: Instrument, *, rate: float = 1.0) -> SymbolSpec:
    """A Nautilus instrument as the spec `risk/sizing.lots` sizes against.

    `rate` converts the instrument's **quote** currency into the one the
    account is held in, and defaults to 1.0 because that is the common case:
    a dollar account trading dollar-quoted instruments. A caller that cannot
    get a rate should pass `0.0` rather than `1.0`, which leaves `tick_value`
    at zero and makes `lots` refuse with a reason instead of sizing against an
    invented conversion.

    **`trade_tick_value_loss` first, and the order matters.** MT5 states three
    tick values: `trade_tick_value_profit`, `trade_tick_value_loss`, and
    `trade_tick_value`, which equals the profit one. A risk budget is the cost
    of being *stopped*, so the loss figure is the one being inverted here. On
    almost every instrument the two agree; where they do not - a venue charging
    an asymmetric conversion on a non-account-currency instrument - taking the
    profit value sizes the position slightly too large, which is the direction
    nobody notices.

    All three are already in the account currency, so `rate` is not applied to
    them. It is applied only to the figure derived from the contract size,
    which is in the quote currency by construction.
    """
    info: dict[str, Any] = dict(instrument.info or {})
    digits = int(instrument.price_precision)
    point = float(instrument.price_increment)
    # The venue's own tick, where it states one. `price_increment` is set to
    # `10**-digits` by the MT5 provider, and an instrument whose real tick is
    # coarser than that would pair a tick value with the wrong tick and be
    # mis-sized by the ratio between them.
    tick = _stated(info, "trade_tick_size") or point
    contract = _stated(info, "trade_contract_size") or float(instrument.multiplier) or 1.0
    stated = _stated(info, "trade_tick_value_loss", "trade_tick_value")
    # Derived only where the venue said nothing: one tick, on one unit of
    # quantity, converted into the account's currency. For spot crypto the
    # multiplier is 1 and quantity is in base units, so this is the tick
    # itself, which is the right answer for that convention too.
    value = stated if stated > 0.0 else tick * contract * max(0.0, rate)

    mode = info.get("trade_mode")
    return SymbolSpec(
        symbol=instrument.id.symbol.value,
        digits=digits,
        point=point,
        tick_size=tick,
        tick_value=value,
        volume_min=float(instrument.min_quantity or 0.0),
        volume_max=float(instrument.max_quantity or 0.0),
        volume_step=float(instrument.size_increment),
        contract_size=contract,
        stops_level=_stated(info, "trade_stops_level"),
        tradable=int(mode) not in UNTRADABLE_MODES if isinstance(mode, int | float) else True,
    )


def size(
    intent: Intent,
    *,
    spec: SymbolSpec,
    settings: Any,
    equity: float,
    profile: Any = None,
    peak: float = 0.0,
    book: Sequence[tuple[str, int]] = (),
) -> Intent | Refusal:
    """An accepted intent with a volume on it, or the reason it cannot have one.

    One sizing step for every entry mechanism, because the alternative is three
    and `Trader` is the record of what three costs: the figure that has to be
    right to the cent was computed in three places and `share_of_risk` was
    folded into two of them.

    The reductions multiply the **risk fraction**, not the lots, and that is
    not a free choice. `lots` rounds down to the broker's volume step and then
    refuses a result below the minimum lot; scaling after it would hand the
    venue a size off the grid, and scaling before it means one rounding, in the
    one direction that cannot breach the budget it was sized for.

    Nothing here applies `lots(slippage=...)`, deliberately. `scaling
    .by_slippage` already prices the measured stop overshoot and the two are
    arithmetically the same reduction - inflating the stop distance by `1 + s`
    divides the volume by exactly what `1 / overshoot` multiplies it by - so
    applying both would charge for the overshoot twice. The multiplier is the
    one that can be switched on per instrument and per side, which is where
    that measurement lives, so it is the one that keeps the job.

    **A volume already on the intent is replaced, not honoured**, and the
    reason is a foot-gun rather than a principle. Both decision rules read
    their volume as `features.get("volume")`, and the bar payload statespace
    publishes carries `volume` as the bar's own traded volume at the top level.
    Those two are one careless move apart: a `features` dict that one day
    includes the bar's volume would put four digits where a lot size goes, and
    `make_qty` would take it. There is one authority for a size and it is this
    function.
    """
    terms: dict[str, float] = {}
    scale = 1.0
    if profile is not None:
        terms = profile.multipliers(
            intent.features,
            intent.feed,
            book=book,
            equity=equity,
            peak=peak,
            interval=intent.interval,
            side=intent.side,
        )
        scale = scaling.combined(*terms.values())

    found = sizing.lots(
        spec,
        equity=equity,
        risk_fraction=settings.risk_fraction * scale,
        stop_distance=intent.risk,
        max_risk_money=settings.max_risk_money,
    )
    if not found.ok:
        return Refusal(
            gate="unsized",
            detail=found.reason or f"{spec.symbol} sized to nothing",
            feed=intent.feed,
        )

    # The reductions that actually reduced, recorded on the intent so the
    # journal can say *which reading* made a trade smaller rather than only
    # that something did. `multipliers` returns nine keys on every call for
    # exactly this - a product discards it - and the ones at 1.0 are dropped
    # because nine columns of 1.0 on every decision is noise, not a record.
    marks = {f"size_{name}": value for name, value in terms.items() if value != 1.0}
    if marks:
        marks["size_scale"] = scale
    if intent.volume > 0.0:
        # What was replaced, kept so the replacement is visible in the record
        # rather than being a number that quietly stopped mattering.
        marks["size_given"] = intent.volume
    return replace(
        intent,
        volume=found.volume,
        risk_money=found.risk_money,
        features={**intent.features, **marks},
    )
