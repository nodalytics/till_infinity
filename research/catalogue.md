# Which of the broker's 798 symbols are worth carrying

The machinery to add one has existed since the instrument tables were
generated: `PRICES_BROKER_SYMBOLS` wires the four tables that have to agree -
instruments, exposure legs, price feeds, symbol list - from one name. Adding an
instrument is a config change.

What it is not is free. Level building scales with feeds times timeframes, and
the warm-up already replays about 987k bars at 42 feeds. So the question was
never "can we carry more", it is **which ones**.

## The screen is spread in volatility units, not points

`charge_spread` deducts the quoted spread from every level call before it is
judged, and the cost is wildly uneven - 0.003v on btc against 2.5v on gbpusd
intraday. A spread in *points* cannot be compared across instruments at all:
the synthetics quote a median spread of 230 points against FX's 12, which looks
decisive and means nothing.

In volatility units - what a strategy actually pays - the ordering inverts.

Harness: [`harness/screen.py`](harness/screen.py). Fetch 400 M5 bars, warm a
volatility estimate, take the live tick, express the spread in units of a
typical move.

## What it says

Median cost to cross, 64 symbols sampled:

| family | median spread | sampled |
| --- | --- | --- |
| synthetic | **0.170v** | 23 |
| metal | 0.547v | 8 |
| other (mostly crypto) | 1.869v | 14 |
| fx | 2.267v | 14 |
| basket | 4.036v | 5 |

**The synthetics are the cheapest thing the broker offers**, by more than a
factor of ten against FX. That is the opposite of what the raw point spreads
suggest and it is the number that decides: a scalp whose whole expected push is
one or two volatility units cannot pay two units to get in and out.

The cheapest end, with what is already carried marked:

    Step Index                     0.075v  carried
    Range Break 200 Index          0.116v
    Jump 10 Index                  0.121v
    Jump 25 Index                  0.122v
    Volatility 25 (1s) Index       0.130v
    Boom 500 Index                 0.130v  carried
    Crash 500 Index                0.149v
    Volatility 10 (1s) Index       0.157v
    Volatility 50 (1s) Index       0.157v
    XAUUSD                         0.159v  carried
    Volatility 25 Index            0.164v  carried
    Volatility 10 Index            0.164v  carried
    Range Break 100 Index          0.170v
    XAUEUR                         0.171v
    Volatility 100 (1s) Index      0.172v
    Volatility 75 (1s) Index       0.179v
    Volatility 50 Index            0.185v  carried
    Crash 1000 Index               0.186v  carried
    Crash 300 Index                0.199v

Eleven uncarried synthetics are as cheap as or cheaper than the nine already
being traded.

## The caveat that could invert half of this

**Measured at 21:00 UTC**, which is the worst hour of the day for FX: New York
has closed and Tokyo has not opened, and spreads are at their widest. The FX
numbers here are a worst case rather than a typical one, and EURUSD at 0.825v
would look very different at 13:00.

The synthetics are unaffected - they run 24/7 on a generated process and their
spreads do not move with a session - so the comparison *between synthetics* is
sound and the comparison *against FX* is not yet. Re-running this during the
London/New York overlap is what would settle it, and until then nothing here
argues for dropping an FX pair.

## What not to add

The 643 symbols this classifier calls "other" are mostly crypto and cross-rate
variants, at a median 1.869v. Two of the crypto symbols sampled were not fully
tradable at all. Baskets are worse again at 4.036v - they are a spread product
whose whole construction is a basket of pairs, so paying four units to cross
one is unsurprising.

## What is unmeasured

Whether a cheap instrument is a *tradable* one. Spread is the cost floor and
says nothing about whether there is anything to trade above it: a generated
process with a tiny spread and no structure is cheap and worthless. The
synthetics already carried are the evidence available, and they have been
running long enough to say - see the ledger.

## Adding them found a third list

The eleven were added and collected nothing: **zero quotes and zero bars on
every one**, which is the same silence as a feed that does not exist - and is
exactly the failure the original nine hit, where 1,271 quotes each and no
candles read as a slow warm-up and was not one.

There were three lists, not the two this note assumed:

| list | where | decides |
| --- | --- | --- |
| `SYNTHETICS` | code | what is **tradable** |
| `PRICES_BROKER_SYMBOLS` | env | what the broker source knows the **name** of |
| `SYMBOLS` | env | what is actually **collected** |

Naming an instrument in the first two registered it, made it tradable, gave it
an exposure leg - and left it polled by nothing, because `resolve_symbols`
returns what `SYMBOLS` names and nothing else.

The fix is not to write the list a third time. `PRICES_BROKER_SYMBOLS` is
already an explicit opt-in and it is the *only* way to reach an instrument
nothing else quotes, so naming one there and having it collected by nothing is
never what anybody wanted. The running deployment now carries every broker-only
feed whatever `SYMBOLS` says.

`resolve_symbols` itself stays narrow: a one-off `prices bars --symbols gold`
should get gold, not the whole synthetic book. The union belongs to the stack,
where the lists are meant to describe one intent.
