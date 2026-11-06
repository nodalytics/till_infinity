# What this broker actually does

Measured facts about the MT5 account the desk trades, as distinct from what
MT5 documents or what the bridge accepts. Every number here was read off the
live account on the date given, and most of them were found the expensive way.

The short version: **a retcode means the deal happened. It has never meant the
protection exists.**

| | |
|---|---|
| [A deal discards the stop](#a-deal-discards-the-stop) | `trade_exemode: 2`, so `sl`/`tp` sent with an order are silently dropped |
| [Tick values are in the account currency](#tick-values-are-in-the-account-currency) | `base_currency=None` is not a sizing bug |
| [Order ids namespace on the last hyphen](#order-ids-namespace-on-the-last-hyphen) | eighteen desks once shared two namespaces |
| [The comment is 31 characters](#the-comment-is-31-characters) | and the useful half is the tail |
| [The book is 725 names and 240 quotes](#the-book-is-725-names-and-240-quotes) | naming is inconsistent; most of it is untradeable |

## A deal discards the stop

EURUSD reports `trade_exemode: 2` - **Market execution**. The broker fills a
`TRADE_ACTION_DEAL` and *ignores the `sl` and `tp` sent in the same request*.
They have to be applied afterwards, as a separate action, which is
`POST /positions/modify` addressed by ticket.

What that cost, on 2026-11-06:

```
ticket 5828118661  EURUSD  SELL 0.43  open 1.11532
sl 0.0   tp 0.0   magic 777701   profit -25.8
comment 'O-20261106-135228-001-E270-37'
```

Ours, by the magic and the comment. Open and unprotected for ninety minutes
across two restarts, and nothing said so - because `_place` sent `sl`/`tp`
with the deal, read `retcode 10009`, and then generated `OrderAccepted` for
the stop and target legs against the entry's ticket. The engine held a bracket
the venue knew nothing about. **This was true of every position opened on a
Market-execution symbol**, so the in-process exit was the only protection, and
that dies with the process.

`_protect` now puts them on the position after the deal and reads the position
back. Three judgements in it worth keeping:

- **A missing position row is not evidence of failure.** A position can lag
  the deal that opened it, and rejecting a stop because the book has not
  caught up would refuse protection that exists. It fails on what it can see -
  a listed position whose `sl` is not the one asked for.
- **Only the leg that failed is rejected.** Reporting a stop as dead while the
  venue holds it is the same lie inverted.
- **Accepted after the check, never before.** An accepted order cannot then be
  rejected, so the verification has to precede `generate_order_accepted`.

Gated on `MARKET` **and** `retcode == DONE`: 10008 is PLACED, a position
exists only once the deal is done, and sending a resting order to
`/positions/modify` once posted its limit price as a target.

`trade_stops_level` is 20 points on EURUSD and 3 for `trade_freeze_level`. A
stop inside that is refused, which `risk/sizing.respects_stops_level` catches
before the order rather than discovering it from a retcode - so the refusal
names the number that was breached.

## Tick values are in the account currency

**A measured null, recorded because it looks exactly like a live money bug.**

The account reports `base_currency=None` with a single balance:

```
AccountState(account_id=MT5-6258778, account_type=MARGIN, base_currency=None,
  balances=[AccountBalance(total=5_971.43 USD, locked=0.00 USD, free=5_971.43 USD)])
```

So it is *not* the multi-currency account `Desk._rate` assumes when it returns
`1.0`, and that looks like non-USD-quoted instruments being sized against a
budget in the wrong currency - a ~150x error on USDJPY. It is not.
`sizes.spec_of` sizes from `trade_tick_value_loss` and **does not apply `rate`
to it**, because MT5 states all three tick values in the account currency:

| symbol | `trade_tick_value_loss` | check |
|---|---|---|
| USDJPY | 0.6315 | 100 JPY / ~158 = 0.633 USD |
| USDCHF | 1.2202 | 1 CHF / ~0.82 = 1.22 USD |
| USDCAD | 0.7092 | 1 CAD / ~1.41 = 0.709 USD |
| EURUSD | 1.0 | 1 USD |

Each is the USD figure. `rate` reaches only the contract-size fallback, which
these instruments never use. Do not "fix" `_rate` on the strength of
`base_currency=None`; `currency_profit` being JPY is not evidence either -
that is the quote currency, not the unit the tick value is quoted in.

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
