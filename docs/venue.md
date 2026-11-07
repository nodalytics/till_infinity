# What this broker actually does

Measured facts about the MT5 account the desk trades, as distinct from what
MT5 documents or what the bridge accepts. Every number here was read off the
live account on the date given, and most of them were found the expensive way.

The short version: **a retcode means the deal happened. It has never meant the
protection exists.** The corollary, learned later and more expensively: a
*refusal* does not mean the protection is absent either. Read the position.

| | |
|---|---|
| [A deal does carry the stop](#a-deal-does-carry-the-stop) | and assuming otherwise cost a live regression |
| [A no-op modify is a 400](#a-no-op-modify-is-a-400) | asking for prices already held is an error, not a confirmation |
| [Tick values convert for FX and not for CFDs](#tick-values-convert-for-fx-and-not-for-cfds) | seven live instruments are sized in the wrong currency |
| [NGAS contradicts its own contract size](#ngas-contradicts-its-own-contract-size) | by a factor of 10,000, in the dangerous direction |
| [What is quoting when](#what-is-quoting-when) | the book closes in four waves, not one |
| [What the unconverted tick value costs](#what-the-unconverted-tick-value-costs-by-currency) | 158x on JPY, and the direction decides what is safe to add |
| [Every cross costs little, and one is untradeable](#every-cross-costs-little-and-one-is-untradeable) | EURNZD round-trips a whole bar range |
| [Order ids namespace on the last hyphen](#order-ids-namespace-on-the-last-hyphen) | eighteen desks once shared two namespaces |
| [The comment is 31 characters](#the-comment-is-31-characters) | and the useful half is the tail |
| [The book is 725 names and 240 quotes](#the-book-is-725-names-and-240-quotes) | naming is inconsistent; most of it is untradeable |
| [Specs worth having to hand](#specs-worth-having-to-hand) | all 23 live instruments, and `stops_level` spans 5 to 2000 |
| [Proving any of this](#proving-any-of-this) | the per-instrument test, and how it stays safe |

## A deal does carry the stop

**This section said the opposite until 2026-11-06, and the desk was changed on
the strength of it. The premise was wrong.**

EURUSD reports `trade_exemode: 2` - Market execution - which MT5's own
documentation describes as filling a `TRADE_ACTION_DEAL` and applying
protection separately. Read against the live account, it does no such thing:

```
0.01 BUY EURUSD at ask 1.11382, sl 1.10882 and tp 1.11882 in the deal body
-> retcode 10009, ticket 5828521206
-> position reads sl 1.10882  tp 1.11882
```

The broker kept both. And `trade_exemode` carries no information here anyway:
**all 23 live instruments report mode 2**, including every one whose deal has
never dropped anything. So does `trade_mode`: all 23 report 4, shut markets
included.

### What the wrong premise cost

`_place` puts `sl`/`tp` in the deal body. Believing they were discarded,
`_protect` was added to set them afterwards with `/positions/modify` - which
meant asking the venue for the prices it already held. MT5 has nothing to
change, refuses, and this bridge answers `400`. So:

1. `_bridge.modify` raises
2. `_protect` catches it and reports **both legs naked**
3. `_report_legs` **rejects the stop and target of a protected position**

The broker held a bracket while the engine believed two legs were rejected -
the same disagreement the change was written to prevent, inverted. It never
fired: it needs a market bracket, and the desk was inside
`TRADING_QUIET_HOURS` for the whole time it was deployed.

`_protect` now reads the position **before** it writes, leaves a position that
is already right alone, and takes its verdict from reading the position again
afterwards rather than from what the modify said. A refusal over a position
that holds the stop is noise; a confirmation over one that does not is a lie.
An unreadable position is still not a naked one - a position can lag the deal
that opened it - so only a refusal with nothing to look at is reported as
unprotected.

### What is still unexplained

The naked position that started all of this is **not** accounted for:

```
ticket 5828118661  EURUSD  SELL 0.43  open 1.11532
sl 0.0   tp 0.0   magic 777701   profit -25.8
comment 'O-20261106-135228-001-E270-37'
```

Ours by the magic and the comment, open and unprotected for ninety minutes
across two restarts. A valid stop *is* kept, so something else dropped this
one. The live hypothesis is that its stop sat inside `trade_stops_level` - 20
points on EURUSD, `trade_freeze_level` 3 - and the broker filled the deal
while discarding a level it would not accept.
`risk/sizing.respects_stops_level` is supposed to catch that before the order,
so either it uses a different distance basis than the broker does or the stop
was moved after placement. **Unproven.** The test is a deal with a
deliberately too-close stop; until that is run, do not assume either the
discard or the guard.

Gated on `MARKET` **and** `retcode == DONE`: 10008 is PLACED, a position
exists only once the deal is done, and sending a resting order to
`/positions/modify` once posted its limit price as a target.

## A no-op modify is a 400

`POST /positions/modify` with the `sl` and `tp` the position already carries
comes back **HTTP 400**, not a 200 with a retcode. The body was not captured
on the run that found it; the reading that fits is MT5 retcode 10025,
`No changes`, surfaced as a status code.

Two consequences:

- **A refusal from this route is not evidence about the position.** Decide on
  what a position read says, not on what the route answered.
- **Check before writing.** A modify is only worth sending when something it
  would change actually differs.

`ModifySLTPRequest` requires `ticket` and `sl`, with `tp` optional - so a
schema problem would be FastAPI's `422`, and a `400` is the broker talking.

## Tick values convert for FX and not for CFDs

**The blanket claim this section used to make - that MT5 states all tick
values in the account currency - holds for FX and fails for every CFD whose
profit currency is not USD.** Measured across all 23 live instruments by
comparing `trade_tick_value_loss` against `trade_tick_size x
trade_contract_size`, which is the same quantity in the *quote* currency:

| instrument | profit ccy | stated | quote-ccy | ratio | reading |
|---|---|---|---|---|---|
| USDJPY | JPY | 0.6308 | 100.0 | **158.53** | converted - the ratio *is* USDJPY |
| USDCAD | CAD | 0.7077 | 1.0 | 1.4130 | converted |
| USDCHF | CHF | 1.2184 | 1.0 | 0.8207 | converted |
| EURUSD, GBPUSD, AUDUSD | USD | 1.0 | 1.0 | 1.0 | nothing to convert |
| XAUUSD, XPTUSD | USD | 1.0 | 1.0 | 1.0 | correct |
| XAGUSD | USD | 5.0 | 5.0 | 1.0 | correct, and proves the contract size is applied |
| Germany 40, France 40, Europe 50 | **EUR** | 0.01 | 0.01 | 1.0 | **not converted** |
| UK 100 | **GBP** | 0.01 | 0.01 | 1.0 | **not converted** |
| Japan 225 | **JPY** | 0.01 | 0.01 | 1.0 | **not converted** |
| Australia 200 | **AUD** | 0.01 | 0.01 | 1.0 | **not converted** |
| Hong Kong 50 | **HKD** | 0.01 | 0.01 | 1.0 | **not converted** |

The FX rows settle that conversion does happen: USDJPY's ratio is the USDJPY
rate to four figures. The CFD rows have ratio exactly 1.0 while their profit
currency is not USD, so their figure is the quote-currency one.

`strategies/sizes.spec_of` takes `trade_tick_value_loss` whenever it is
positive and never applies `rate` to it, on the documented assumption that it
is already in the account currency. For seven live instruments it is not, and
position size is inversely proportional to the tick value, so each is
mis-sized by its own rate (quotes of 2026-11-06 22:50 UTC):

| instrument | factor | effect on size |
|---|---|---|
| Japan 225 | JPY, 1/158.53 | **158x too small** |
| Hong Kong 50 | HKD | much too small; this terminal quotes no HKD pair, so unmeasured here |
| Australia 200 | AUD 0.6863 | 31% too small |
| Germany 40, France 40, Europe 50 | EUR 1.1136 | 11% too large |
| UK 100 | GBP 1.3347 | 33% too large |

**Not yet confirmed against realised P&L**, which is the check that would
settle it: compare the money lost on a stop against the risk the intent asked
for, per instrument. `r_multiple` cannot show this - it is computed from price
distance, so a currency scaling error is invisible to it. Japan 225's
`volume_min` of 10 lots is consistent with a lot being small in JPY, which is
weak supporting evidence and not proof.

Do not "fix" `Desk._rate` on the strength of `base_currency=None`. The account
reports `base_currency=None` with a **single** `AccountBalance` in USD, so it
is not the multi-currency account `_rate`'s `1.0` assumes, and `currency_profit`
being JPY is not evidence either - that is the quote currency, not necessarily
the unit the tick value is quoted in. The error above is in `spec_of` trusting
a stated value, not in `rate` itself. (The balance and the account id stay out
of this file: the repository is public, which is also why `.secrets/` holds
anything that names the account.)

## NGAS contradicts its own contract size

Every other instrument satisfies `trade_tick_value == trade_tick_size x
trade_contract_size` in the quote currency. XAGUSD is the clean demonstration:
tick `0.001`, contract `5000`, tick value `5.0`. NGAS does not:

| field | value |
|---|---|
| `trade_tick_size` | 0.001 |
| `trade_contract_size` | 10000 |
| `trade_tick_value_loss` | **0.001**, where the pattern gives **10.0** |
| `volume_min` / `volume_max` | 0.1 / 5.0 |
| `currency_profit` | USD, so no conversion explains it |

One of the two fields is wrong by a factor of 10,000, and because `spec_of`
prefers the stated tick value, the desk sizes NGAS as though a 0.001 move were
worth a tenth of a cent a lot rather than ten dollars. That is the **dangerous
direction** - too large - and it is bounded only by `volume_max` of 5.0 lots,
which at 10,000 MMBtu a lot is 50,000 MMBtu, about 164,000 USD of notional at
3.28. A margin refusal (`retcode 10019`) is the likely practical outcome on a
small account, but nothing in the desk refuses it first.

NGAS is in `TRADING_SYMBOLS` and live. It is also the most expensive thing on
the book to trade - a 0.261 bar-range round trip, see
`.secrets/instruments.md` - so dropping it costs little.

## What is quoting when

The book does not close at one time. Quote ages read at **21:50 UTC on Friday
2026-11-06**, where age is now minus the last tick:

| group | age | state |
|---|---|---|
| NGAS, US Oil, UK Brent Oil | 0-1 min | still trading |
| Germany 40, UK 100, France 40, Europe 50 | 0 min | still trading |
| Australia 200, Hong Kong 50 | 0 min | still trading |
| XAUUSD, XAGUSD, XPTUSD | 8 min | shut ~21:41 |
| Wall Street 30, US SP 500, US Tech 100 | 8-9 min | shut ~21:41 |
| XCUUSD | 54 min | shut ~20:55 |
| FX (all six) | fresh at 21:50, 36 min by 22:50 | shut ~22:15 |

**Quote age is the usable session signal.** `/symbols/info` returns
`session_open` and `session_close` as *prices*, not times - Wall Street 30
reports `session_close: 53556.35` - so there is no schedule to read off the
venue. `strategies/sessions.py` learns schedules from data and **nothing
consumes it**: `trading_at` and `closes_in` have no callers.

A stale quote is not the same as a refusal. Every instrument above kept
`trade_mode: 4` while shut, so trade mode cannot be used to detect a closed
market either.

## What the unconverted tick value costs, by currency

The section above establishes that `trade_tick_value` is the **quote-currency**
figure on every CFD whose profit currency is not USD, and that `sizes.spec_of`
trusts it without applying a rate. This is what that is worth per currency,
measured 2026-11-07 against quotes of that date. Position size is inversely
proportional to the tick value, so a **stated value below the truth oversizes**:

| profit ccy | rate to USD | stated vs true | size error | direction |
| --- | --- | --- | --- | --- |
| **JPY** | 1/158.53 | 0.01 vs 0.0000631 | **158x** | undersized |
| NZD | ~0.58 | 0.01 vs 0.0058 | 1.7x | undersized |
| AUD | 0.6863 | 0.01 vs 0.00686 | 1.46x | undersized |
| CAD | 1/1.4130 | 0.01 vs 0.00708 | 1.41x | undersized |
| CHF | 1/0.8207 | 0.01 vs 0.0122 | 1.22x | **oversized** |
| GBP | 1.3347 | 0.01 vs 0.0133 | 1.33x | **oversized** |
| EUR | 1.1136 | 0.01 vs 0.01114 | 1.11x | **oversized** |
| USD | 1.0 | agrees | - | correct |

**The direction decides what is safe to add.** An undersized instrument trades
too little and reads as a dead rule; an oversized one risks more than the
budget said. So a JPY cross is not dangerous, it is *pointless* - it would
trade about 1/158 of intent - while a GBP or CHF cross risks a quarter more
than intended.

This is why the four crosses chosen for `identity-arb` on 2026-11-07 are
AUDCAD, EURAUD, AUDNZD and EURCAD rather than the two cheapest: EURJPY (0.036)
and AUDJPY (0.037) are the cheapest crosses on the book **and** the worst
choices, being JPY-quoted.

### Fixed by asking the broker, 2026-11-07

The paragraph that stood here said this waited on a realised-P&L observation -
open a minimum position, note the move, read back the `profit`. It does not,
because the terminal will do that arithmetic without the position:
`order_calc_profit` is the function it *settles* P&L with, and it answers in
the account's currency. The bridge has served it at
`GET /api/v1/orders/calc/profit` all along and nothing called it.

So `providers.py` asks once per instrument at load - one lot, a `CALC_SPAN` of
1000 ticks, divided back down - and puts the answer on `info` as
`calc_tick_value`. `spec_of` then prefers it to the stated figure. This is not
"another read": nothing is inferred from a field whose unit is in question.

**It corrects a value and never multiplies one.** A calculated figure the
stated one contradicts by more than `CONTRADICTION` refuses the instrument
rather than adopting it, which is the same answer `_contradicts` gives NGAS.
That splits the table above exactly: EUR, GBP, CHF, CAD, AUD and NZD are
1.11x to 1.7x and get corrected - the three oversized ones being the whole
point - while JPY at 158x is refused. Refusing Japan 225 loses nothing real,
because at 1/158 of intent it was never trading; and a 158x gap means one of
the two numbers means something nobody has confirmed, so sizing a position on
it would be the one mistake that can empty an account.

Nor does it overturn a refusal `tick x contract` already made: NGAS stays
refused whatever the calculation says, because that gap is between two of the
venue's own fields and is not this reading's to settle.

**What to read in the startup log.** Every instrument where the two differ by
more than 1% logs a warning naming both and the ratio. A ratio near 1.0 says
the stated figure was already in the deposit currency; a ratio that *is* the
instrument's FX rate says it was not - which is the table above, confirmed or
refuted per instrument, on every start.

## Every cross costs little, and one is untradeable

Spread over bar range, 96 M15 bars, 2026-11-07. The same measurement
`.secrets/instruments.md` records for the live book, and the screen that has
now twice stopped a bad instrument being added.

| cross | median | | cross | median |
| --- | --- | --- | --- | --- |
| EURJPY | 0.036 | | EURCAD | 0.072 |
| AUDJPY | 0.037 | | GBPCHF | 0.082 |
| AUDCAD | 0.038 | | AUDCHF | 0.084 |
| NZDJPY | 0.049 | | EURCHF | 0.086 |
| GBPJPY | 0.051 | | GBPCAD | 0.091 |
| EURAUD | 0.055 | | EURGBP | 0.100 |
| CADJPY | 0.058 | | CADCHF | 0.120 |
| AUDNZD | 0.058 | | CHFJPY | 0.122 |
| GBPAUD | 0.060 | | NZDCAD | 0.143 |
| | | | NZDCHF | 0.164 |
| | | | GBPNZD | 0.175 |
| | | | **EURNZD** | **1.071** |

**EURNZD round-trips for more than a whole bar range** - 1.071 median, 1.415 at
p75 - and is the only cross outside the 0.036-0.175 band. It also carries
`trade_stops_level` 40 where every other cross carries 20, and a 150-point
median spread at M1. Excluded.

All 21 crosses are `volume_min` 0.01, `trade_mode` 4 and `trade_exemode` 2, and
all pass the contract-size guard.

### And the crypto, screened the same day

| symbol | median | verdict |
| --- | --- | --- |
| **BTCUSD** | **0.010** | cheapest on the book after US Tech 100 (0.008) |
| XRPUSD | 0.037 | cheap, but `volume_min` is **500 lots** |
| BNBUSD | 0.042 | added |
| ETHUSD | 0.065 | added |
| SOLUSD | 0.143 | dear - worse than Hong Kong 50 |
| **LTCUSD** | **1.154** | **untradeable** |
| **ADAUSD** | **1.055** | **untradeable** |

LTCUSD and ADAUSD cost **more than a full bar range** to round trip, three
times beyond the 0.40 the cost file calls untradeable. And the `.conv`
variants - `BTCUSD.conv`, `ETHUSD.conv`, `LTCUSD.conv` - report
`trade_mode` **absent**, so they are currency-*conversion* symbols and not
tradeable instruments, however identical their spread figures look.

Crypto quotes through the weekend: all ten read a fresh tick at 08:30 UTC on a
Saturday, which is what makes BTCUSD, ETHUSD and BNBUSD worth holding beside
the Deriv synthetics.

## Specs worth having to hand

All 23 live instruments, read 2026-11-06. `stops` is `trade_stops_level` in
points; every one of them is `trade_exemode: 2` and `trade_mode: 4`, and all
six FX pairs carry `trade_freeze_level: 3`.

| instrument | vol min | vol max | stops | tick | contract |
|---|---|---|---|---|---|
| EURUSD, GBPUSD, AUDUSD, USDCAD, USDCHF | 0.01 | 50 | 20 | 1e-05 | 100000 |
| USDJPY | 0.01 | 50 | 20 | 0.001 | 100000 |
| XAUUSD | 0.01 | 10 | 20 | 0.01 | 100 |
| XAGUSD | 0.01 | 15 | 20 | 0.001 | 5000 |
| XPTUSD | 0.01 | 10 | 400 | 0.01 | 100 |
| XCUUSD | 1.0 | 1000 | 600 | 0.01 | 1 |
| NGAS | 0.1 | 5 | 5 | 0.001 | 10000 |
| US Oil, UK Brent Oil | 1.0 | 1000 | 50 | 0.001 | 1 |
| US SP 500 | 0.1 | 150 | 50 | 0.01 | 1 |
| UK 100, France 40 | 0.1 | 100 | 100 | 0.01 | 1 |
| US Tech 100, Germany 40 | 0.1 | 100 | 150 | 0.01 | 1 |
| Europe 50 | 0.1 | 150 | 200 | 0.01 | 1 |
| Wall Street 30 | 0.1 | 100 | 300 | 0.01 | 1 |
| Australia 200 | 0.1 | 100 | 500 | 0.01 | 1 |
| Japan 225 | **10.0** | 1500 | 1000 | 0.01 | 1 |
| Hong Kong 50 | 0.1 | 100 | **2000** | 0.01 | 1 |

`stops_level` spans 5 points on NGAS to 2000 on Hong Kong 50, so a stop
distance that is legal on one instrument is refused on another. Japan 225's
`volume_min` of 10 lots makes it the one instrument no small test can touch:
the tightest legal stop at the minimum size is several hundred dollars.

## Proving any of this

`/tmp/protect_all.py` on the instance tests the protection path per
instrument. `survey` reads only - it sends no order - and reports which
instruments are tradeable now, with the worst case priced two ways. `prove`
then trades only what the survey passed, asking three separate questions per
instrument: does the deal keep the stop, does a no-op modify fail, does a real
modify work.

It trades at `volume_min` under **magic 990001**, deliberately not the desk's
`777701`, so `_ours` ignores it and reconciliation cannot adopt one. Each
instrument closes in its own `finally`, with a final sweep for anything
carrying that magic, and any instrument whose worst case cannot be priced -
or exceeds `PROOF_RISK_CAP`, default 20 - is skipped rather than traded.

Two lessons already paid for:

- **Price the risk both ways.** The cap read `0.00` for NGAS on the tick-value
  basis and `15.00` on the contract basis. A cap computed from a single
  unverified field is not a cap.
- **One snapshot is not a measurement.** A single read at 16:00 UTC gave NGAS
  a 0.788 bar-range round trip against a 96-bar median of 0.261, and nearly
  cost four live feeds.

## Order ids namespace on the last hyphen

`StrategyId.get_tag()` returns only the text after the **last** hyphen, and
Nautilus's order-id generators namespace on that alone - it is read in four
places and all four are in `generators.pyx`. `_tag` put the symbol first and
the rule hash last, so these were two desks with **one** id namespace:

```
EdgeEntry-EURUSD-E270   get_tag() -> E270
EdgeEntry-GBPUSD-E270   get_tag() -> E270
```

Each desk holds its own `OrderFactory` whose counter `Strategy._start`
initialises to `len(its own cached order lists)`, so every desk calls its first
bracket `-1`, and the datetime tag resolves only to the second. Two desks
proposing on the same bar close emit byte-identical ids; the second is denied
`duplicate OrderListId`, and `_deny_order_list` denies every leg. Measured
over a nine-symbol, two-entry deploy:

```
before  qualify=False:  2 namespaces for 18 desks  ['E287', 'R287']
before  qualify=True :  1 namespaces for 18 desks  ['MT5']
after:                 18 namespaces for 18 desks
```

Venue-qualified was worst - the venue went last, so every desk on it shared
`MT5`. **A duplicate denial is not a retry**; nothing in this repository
re-sends a refused order. Divide the denial count by the legs to get
collisions: the "3 refused, 9 denied" night of 2026-11-05 was three collided
brackets alongside three unrelated retcode 10018 refusals, sharing only the
trigger - several desks proposing at a session boundary.

So the tag is joined with `_`, and must stay free of internal hyphens. The
cost of changing it is a one-time rename that orphans whatever is open:
`test_a_single_venue_tag_is_unchanged` is the tripwire and has fired twice.
Drain first, and check with a position read rather than a recollection - on
2026-11-06 the desk was believed flat and was not.

## The comment is 31 characters

MT5 truncates an order comment at 31 characters, and the adapter sends the
client order id as the comment. It keeps the **last** 31, not the first: the
head is a timestamp the terminal already records against the deal, and only
the tail names the trader, the desk and the counter.

Taking the first 31 was harmless while a desk tag was four characters. Once
the tag carries the symbol, `O-20261106-230145-001-EURUSD_E270-3` truncates to
`O-20261106-230145-001-EURUSD_E2`, which is the same string for every order
that desk sends and for its neighbours on other symbols.

Informational only - orders are found by `magic` and fills correlated by
ticket, never by comment. But a comment that cannot tell two desks apart is no
use to the person reading the terminal, which is the only reason it is sent.

## The book is 725 names and 240 quotes

The terminal lists **725** symbols. On 2026-11-06 at 16:00 UTC only **240**
carried a two-sided quote; the rest are listed without being quotable at that
moment. Naming is inconsistent and cannot be guessed:

| kind | how it is spelled |
|---|---|
| FX, metals | `EURUSD`, `XAUUSD`, `XAGUSD`, `XPTUSD`, `XCUUSD` |
| energy | `NGAS`, but `US Oil` and `UK Brent Oil` |
| indices | `US SP 500`, `Wall Street 30`, `Germany 40`, `Hong Kong 50` |
| synthetics | `Step Index 300`, `Crash 150 Index`, `Volatility 75 Index` |
| equities | `VYLR.N`, `SPXS.US`, `UNG.US` |

`USOil`/`UKOil` is FXCM's spelling and is **wrong here** - the data client
says so directly, `TRADING_SYMBOLS has 'USOil' and this terminal does not list
it at all, under any case`, which is the cheapest way to find out. Spreads run
from 0.14bps (`Step Index`) to 598bps (`SPXS.US`, a 6% round trip). See
[deployment.md](deployment.md#sizing-it) for what the box can carry and
`.secrets/instruments.md` for per-instrument cost.

## Routes worth knowing

- `/api/v1` is the prefix; the adapter adds it.
- The account is under `/terminal/`, not `/account/` - that 404s.
- `POST /orders/` is 405. Orders go through `/trading/order`.
- `POST /positions/close` and `/close_all` take **query parameters**, not a
  body; sending JSON gives `422 field required for query.ticket`.
- `/symbols/ticks` caps at **40 symbols** a call and says so: `asked for 60
  symbols; the limit is 40`.
- `/symbols/info` returns `session_open` and `session_close` as *prices*, not
  times. Wall Street 30 reports `session_close: 53556.35`.
- Two `trade_allowed` flags exist and only `terminal_info`'s decides whether an
  order fills.
