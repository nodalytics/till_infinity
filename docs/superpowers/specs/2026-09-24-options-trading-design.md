# Options trading: a design

**Status**: **approved 2026-09-24.** A sibling contract beside `Broker` plus a quote recorder as a
collector, in a new top-level `till_infinity/options/` package. Everything below the architecture
section changed after the day's measurements and should be read as the reason the scope is smaller
and the venue list longer than when this was first sketched.

## What this is for

This desk can forecast **size** and cannot forecast **direction**. That is not a hunch, it is the
settled result of the research folder:

* [`crash-timing.md`](../../../research/docs/crash-timing.md) - a big-move score at AUC 0.65-0.81;
* [`news-volatility.md`](../../../research/docs/news-volatility.md) - 2.4x normal volatility on a
  release bar, with a profile out to four hours;
* [`implied.md`](../../../research/docs/implied.md) - VIX beating a trailing estimate by 12-20 points of
  R-squared, the only unambiguous positive in the folder;
* against [`directional-questions.md`](../../../research/docs/directional-questions.md), where a
  92-view ensemble over price, volume, calendar, VIX, the dollar, order flow, gaps and events
  cleared costs at **no** interval, and the best out-of-sample IC was +0.039 inside two standard
  errors.

CFDs and spot require direction. **Options are the instrument class that pays for being right about
size without picking a side.** That is the entire motivation, and it is structural rather than
opportunistic.

**What is not established, and must lead this document**: an option has to beat the market's
*implied* volatility, not a trailing estimate. That is a much harder opponent than the baselines the
research above beats, and `implied.md` is itself evidence for how hard - it is the market's own
volatility index that wins there, not ours. **No measurement in this repository shows our forecasts
beating implied volatility, because until today the repository held no option prices at all.** The
first job of this work is to make that comparison possible. It is not to trade.

## What the day's measurements changed

Before writing execution for any venue, the venues were measured. Two of the three planned phases
turned out to be answerable immediately, and both answers were negative.

| finding | consequence |
| --- | --- |
| Deriv rise/fall margin: **2.41%** on synthetics, **12.0-15.6%** on real ([`deriv-payouts.md`](../../../research/docs/deriv-payouts.md)) | binaries are dead as a directional bet on both families |
| the payout skew is `-0.00054 * sigma * sqrt(T)`, a constant | there is no directional information in the payout |
| accumulators: 0 of 25 cells favourable, **-28.9%** of stake held to cap ([`accumulators.md`](../../../research/docs/accumulators.md)) | the one volatility-shaped Deriv contract is unfavourably priced |
| `ACCU` is offered on **27 of 89 instruments, all synthetic** | the contract exists only where sigma is a published constant |
| Deriv sells **no barrier product on the Jump indices** | `deriving.md`'s 1.71x mispricing has no instrument |

**The pattern matters more than any single number.** A venue writes exotic contracts on processes it
generates itself, where it knows sigma exactly and cannot lose to an informed counterparty. Where
forecasting is possible - real instruments - it sells vanilla directional binaries at a 12-15.6%
margin. Deriv's product range and this desk's edge are close to disjoint, by design rather than
accident.

So **Deriv is demoted**: from the venue this work is built for, to a venue this work *monitors*. It
keeps a recorder and gets no execution path.

## The venues, ranked by whether our edge can be expressed

| venue | instrument | publishes IV? | paper? | gateway needed? | verdict |
| --- | --- | --- | --- | --- | --- |
| **Deribit** | BTC/ETH options | **yes** - `mark_iv`, `bid_iv`, `ask_iv` | **testnet** | no | **primary research target** |
| **IBKR** | equity, index, FX options | via the API | **yes**, paper accounts | **yes** | production target, highest cost |
| **Deriv** | binaries, accumulators, multipliers | no - fixed payouts | n/a | no | **monitor only** |

**Deribit is first**, and the reason is narrow: it publishes an implied volatility per instrument, so
the comparison this whole design exists to make - *do our volatility forecasts beat the market's* -
becomes a measurement against recorded data with **no execution, no credentials and no capital**.
Measured 2026-09-24: `test.deribit.com` and `www.deribit.com` both answer, **1,050 live BTC options
on testnet quoting a `mark_iv`**, public market data unauthenticated, tick size 0.0001.

Example rows, which is what a recorder would be storing:

    BTC-25SEP26-84000-P   mark_iv 40.6%   volume 958.2
    BTC-24SEP26-86000-P   mark_iv 41.8%   volume 581.0

**IBKR is second and is the production venue**, because it reaches the instruments this desk actually
has history and signals for - indices, gold, the majors - with real options rather than fixed
payouts. Its cost is architectural, and we have paid it before: **both** API surfaces require a
vendor process running somewhere. The Client Portal Web API needs a lightweight gateway; the TWS API
needs TWS or IB Gateway installed. That is the **same shape as the MT5 bridge**, which is an argument
for IBKR rather than against it - we know this shape, and we know its failure modes, all of which
were live this week:

* a health route that reports the service rather than the broker, so a detached gateway reads as
  healthy (fixed in the bridge on 2026-09-24);
* an unsupervised tunnel that dies with its shell, with no systemd unit;
* a vendor-side toggle with no programmatic setter (`AutoTrading`), needing a GUI keystroke.

IBKR will have its own versions of all three, and the design should assume so rather than discover
it.

## Architecture

### A sibling contract, not a fifth `Broker` backend

`trading/venues/` is already the right shape: a `Broker` ABC with `mt5_native`, `mt5_rpyc`,
`mt5_http` and `paper`, resolved by `broker.choose` with mandatory logging of which backend won and
why the earlier ones were skipped.

It cannot carry options. The contract is CFD-shaped all the way down:

    Order(symbol, side, volume, stop, target, deviation)
    Position(ticket, symbol, side, volume, price_open, stop, target, profit)
    close_position(ticket, volume)

An option has **strike, expiry, premium and a payoff rule**; a binary has **stake, duration, barrier
and payout**; an accumulator has **growth rate and a per-tick barrier**. None has `volume` or
`stop` in the sense `risk.py` reads them, and every sizing path in `risk.py` and `sizing.py` reads
exactly those fields. Forcing options through `Order` puts a lie in the type that sizing then acts
on.

So: a **new package** `till_infinity/options/`, with its own contract, its own venues and its own
paper book, sharing the bus, the journal, the `Guard`'s day state and `shared/effects.py`.

**This differed from the first sketch and was agreed on 2026-09-24.** That sketch put the sibling
contract inside `trading/`. A top-level package won because the recorder needs its own store and its
own loop, and because an options position's lifecycle - it expires - has no counterpart in
`trading/`, where every exit is a decision. Keeping it under `trading/` would have worked; it would
have meant one package holding two unrelated position models.

### The contract model

One model across all venues and product classes, because the alternative - a type per product - has
to be re-plumbed for each new one. Deriv's own API already demonstrates the unified shape works: one
`proposal` verb covers binaries, accumulators, multipliers, turbos and vanillas.

```python
@dataclass(frozen=True, slots=True)
class Contract:
    """What we want to buy, in terms every venue can express."""
    venue: str            # "deribit" | "ibkr" | "deriv"
    underlying: str       # our feed name, not the venue's symbol
    kind: ContractKind    # CALL | PUT | BINARY_UP | BINARY_DOWN | ACCUMULATOR | ...
    stake: float          # what we risk, in account currency
    #: None where the product has no expiry - accumulators and multipliers.
    expiry: float | None
    #: None for a binary priced at the money; a price for a vanilla or barrier.
    strike: float | None
    #: Per-product extras, kept out of the core so a new product needs no new field.
    terms: Mapping[str, float] = field(default_factory=dict)
```

`terms` is deliberate. A `growth_rate`, a `barrier2`, a `duration_unit` are venue- and
product-specific, and promoting each to a top-level field means the dataclass grows without bound and
every venue has to ignore most of it. The rule: **anything two venues express differently goes in
`terms`.**

Quotes carry what a decision needs and, critically, **what a fair-value comparison needs**:

```python
@dataclass(frozen=True, slots=True)
class Quote:
    contract: Contract
    ask: float            # what it costs
    #: The venue's own implied volatility where it publishes one - Deribit does,
    #: Deriv does not. None is not zero, and the difference is the whole study.
    implied_vol: float | None
    #: A fixed-payout product's payout, from which `stake / payout` is the
    #: venue's implied probability. None for a vanilla.
    payout: float | None
    spot: float
    at: float
```

### `OptionsVenue`, beside `Broker`

```python
class OptionsVenue(ABC):
    async def connect(self) -> None: ...
    async def healthy(self) -> bool: ...
    #: Which contracts this venue will actually quote. Measured, not declared -
    #: see below on why this method exists at all.
    async def catalogue(self) -> list[Contract]: ...
    async def quote(self, contract: Contract) -> Quote | None: ...
    async def buy(self, contract: Contract, quote: Quote) -> Fill | None: ...
    async def positions(self) -> list[OpenContract]: ...
    async def close(self, ref: str) -> Fill | None: ...

# `Fill` and `OpenContract` are not sketched here on purpose: their fields follow from the
# settlement work in phase 2, and guessing them now would fix a shape before the thing that
# needs it exists. `Fill` carries what was paid and the venue's reference; `OpenContract`
# carries a `Contract`, that reference, and whatever the venue reports about its current worth.
```

**`catalogue()` is not decoration.** Today's measurements produced three separate surprises that a
declared symbol list would have hidden: Boom and Crash are listed tradable and quote no option at
all; Jumps carry no barrier products; and forex options quote at 15m even though `contracts_for`
advertised `1d..365d`. A venue adapter must be able to say what it *actually* quotes, and the
recorder must ask rather than assume. The corollary is a rule for the whole package: **never write a
symbol-and-duration grid by hand.**

### The recorder is a collector, not part of `trading`

It behaves like `prices`: a long-running subscription writing to its own store. It gets its own
module and its own SQLite file (`options.db`), with `shared/db.py`'s pragmas - including the
`journal_size_limit` cap, whose absence cost a day of trading this week.

Two constraints from the box rather than from taste. tis has **two cores and 3 GB** and has been
OOM-killed 63 times, so:

* **a bounded subscription budget** - a fixed number of live subscriptions with a rotating schedule,
  so coverage is broad over a day rather than deep every second. Deribit alone has 1,050 live BTC
  options; subscribing to all of them is not an option and is not necessary;
* **write batching**, because the WAL lesson from 2026-09-24 is that a checkpoint cannot drain while
  a reader holds a snapshot, and a collector that writes per-message on a shared disk is how that
  happens.

## Phasing

The order is set by what each phase can *establish*, and it is deliberately front-loaded with the
things that need no credentials, because two of three Deriv phases turned out to be answerable from
quotes alone and both answers were no.

### Phase 0 - Deribit recorder. No credentials, no execution.

Record the BTC and ETH option surface: `mark_iv`, `bid_iv`, `ask_iv`, mark price, spot, open
interest. Then answer the question this design exists for:

**Do our volatility forecasts beat Deribit's implied volatility, out of sample?**

Scored as `implied.md` scores members - QLIKE against realised, walk-forward, refit at every step -
with the venue's IV as just another member of `consensus_vol.Ensemble`. If our forecast cannot beat
`mark_iv`, there is no options edge and phases 1-3 should not be built. **This is the gate for the
whole programme**, and it costs a recorder.

Detection floor, stated now: the spread between `bid_iv` and `ask_iv` is the cost. A forecast must
beat `mark_iv` by more than half that spread to be worth anything, and the floor is computed from
recorded data before the comparison is run.

### Phase 1 - Deriv recorder, reduced to monitoring

`payout_logger.py` already does this and now collects (54/54 on its first sweep). Extend it to carry
accumulator terms, and keep it running for exactly two triggers:

* **`ACCU` listed on a real instrument** - the break-even bar is a 2.51% fall in per-tick volatility,
  the signal exists on real markets at +5 to +9 points, and `accumulators.py` re-runs in a minute;
* **the barrier widening past 2.18 sigmas** at `g=0.03`, which would flip the arithmetic with no
  signal required.

No execution path. If neither trigger fires, this is the whole of Deriv's involvement.

### Phase 2 - the paper book

Only if phase 0 clears its floor. `options/paper.py`, following `venues/paper.py`'s two properties
that make it trustworthy: **fill against the live quote rather than the mid**, and **settle on the
tick stream rather than a timer**. For options, settlement is the new work - an expiry has to be
evaluated at expiry, which a CFD book never had to do, so the paper book acquires state that
`venues/paper.py` deliberately has none of.

### Phase 3 - IBKR, and only for what phase 0 justified

Gateway, tunnel, supervision - and a health route that reports the *gateway's* state, not the
service's, because that specific mistake cost a day on the MT5 bridge and the fix is already written
down. Paper account first; live is a separate decision with its own approval.

## Out of scope, explicitly

* **Trading anything on Deriv.** Measured and negative, twice.
* **Selling premium.** The variance risk premium is real and `implied.md` finds it in VIX, so short
  volatility with the spike score and the calendar as a filter is a coherent idea - and it is an
  *unbounded loss* strategy on a desk whose risk framework is built around a stop price. It needs its
  own design.
* **Multi-leg structures.** Spreads, straddles, condors. Everything here is single-leg until a
  single leg has been shown to work.
* **Greeks-based hedging.** Delta-hedging an option with the CFD book couples two venues' state and
  needs the single-leg case settled first.
* **Crypto options anywhere but Deribit.** Binance and OKX also list them; one venue is enough to
  answer the phase 0 question, and a second adapter before then is work with no information in it.

## Testing

Following the repository's existing shape rather than inventing one:

* **a fake venue** in the style of `metatrader-terminal`'s `fake_mt5.py` - returns what it is told,
  records what it was asked, so a route passing an argument a venue rejects is caught without a
  network;
* **contract round-trip tests** per venue: our `Contract` to the venue's wire format and back, which
  is where `symbol` versus `underlying_symbol` would have been caught;
* **the recorder's budget** under test, because an unbounded subscription on a 3 GB box is a
  production incident and not a test failure;
* **`shared/effects.py` declarations** for every switch, because a feature that is enabled and
  reached by nothing has happened nine times in this codebase and is invisible to ordinary tests;
* **a published-field check** in the style of `test_published.py` - a recorder writing a column that
  never varies is not recording.

## Open questions

1. **Does the account exist?** Deribit testnet needs registration; IBKR paper needs an opened
   account. Phase 0 needs neither - public market data is unauthenticated - but phase 2 onward does.
2. **Which underlyings overlap?** Deribit is BTC and ETH. This desk has deep history on both, but its
   *best-validated* volatility work is on indices and gold via VIX. The phase 0 comparison is
   therefore on the underlyings where our forecasts are least proven, which weakens what a positive
   result would mean and should be said out loud when one arrives.
3. **Is `mark_iv` the right opponent?** It is Deribit's mark, not a tradable price. The honest
   comparison is against `ask_iv` for buying and `bid_iv` for selling, and the recorder must capture
   all three - two of the four rows sampled today had `bid_iv`/`ask_iv` null, so how often they are
   present is itself a phase 0 measurement.
