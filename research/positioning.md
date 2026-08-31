# Supply and demand: what is inferred, what is observed, and what is missing

Almost everything this system knows about supply and demand is **inferred from
price**, because the broker feed gives a spread and nothing behind it. There is
no order book, no depth, no resting size. That is a hard limit of the data
source rather than a gap in the code, and it is worth stating plainly before
the list below reads as more than it is.

## What exists, under other names

The desk vocabulary maps onto modules built from the mechanism rather than the
label:

| the trading term | what it is here | status |
| --- | --- | --- |
| supply/demand zone, order block | `origins.py` - where a violent move *started*, whose impulse broke structure | live, in the default formation |
| volume at price, cost basis | `profile.py` - modes of the distribution of activity over price | live; refuted as a *source* of levels, kept as a vote ([shelves.md](shelves.md)) |
| liquidity pool, equal highs | `equals.py` - price stopped at the *same* price twice | live |
| imbalance, fair value gap | `gaps.py` - defined by trade that did **not** happen | live |
| stop hunt, liquidity grab | `sweeps.py` - being wrong and being swept look identical and are not | live |
| absorption, compression | `absorption.md` | measured; **neither separates** |

Six of the standard supply-and-demand ideas are represented, two of them
already refuted. That is a healthier state than having all six untested.

## The macro side is supply, and only supply

The FRED block is the *supply of money*, and rather thoroughly: `WALCL`,
`ECBASSETSW` and `JPNASSETS` (central bank balance sheets), `M2SL` (money
stock), `RRPONTSYD` (liquidity drained overnight), `WRESBAL` (reserves),
`TOTBKCR` (credit supply).

**The demand side is one series - `UNRATE`.** That asymmetry was not deliberate
and is worth naming: the model can see how much money exists and almost nothing
about who wants it.

## What was missing, and is now collected

The CFTC's **Commitments of Traders** report is the one piece of *observed*
rather than inferred supply and demand reachable from here. Every Friday it
publishes how many contracts each category of trader held on the previous
Tuesday, for every US futures market. Reported, not modelled, and free.

`news/cot.py`. What it takes:

* **leveraged funds' net**, long minus short - the speculative money, whose
  positioning is a bet rather than a hedge. A dealer's book is the other side
  of somebody else's hedge and says more about flow than about opinion.
* **asset managers' net**, the slower money, for the same markets.
* **open interest**, because the nets are meaningless without it.

Normalised by open interest. A net of −72,092 contracts is not comparable
between a market with two million outstanding and one with twenty-two thousand,
nor with itself a year later.

### The sign is the part that could have been silently wrong

**CME currency futures are quoted as the foreign currency in dollars.** A long
JAPANESE YEN future is long yen, which is *short* USDJPY. So the mapping
inverts for every pair with the dollar first - `usdjpy`, `usdcad`, `usdchf` -
and does not for `eurusd`, `gbpusd`, `audusd`, `nzdusd`.

Getting that backwards would not fail. It would produce a signal of exactly the
right magnitude pointing exactly the wrong way, on the instruments that matter
most, and it would look like a working feature.

The first live read is its own check on that:

| feed | leveraged net, as share of open interest |
| --- | --- |
| usdcad | **+21.9%** |
| usdjpy | **+20.1%** |
| dxy | **+19.2%** |
| audusd | +16.2% |
| gbpusd | +15.0% |
| usdchf | +8.1% |
| eurusd | −4.7% |
| us100 | −13.7% |
| spx500 | −15.4% |
| nzdusd | −36.0% |
| btc | −36.4% |

Funds are net *short* Canadian dollar and yen futures, which this reports as
long USDCAD and long USDJPY. Independently, they are long the **dollar index**
at +19.2% and short EURUSD. Those two facts agree with each other, and they
were derived down different paths - the inverted pairs through `INVERTED` and
the dollar index straight through. That coherence is the evidence the table is
right, and it is why it is recorded here rather than asserted in a docstring.

## What it is worth, which is unmeasured

Tuesday's positions, published Friday. **The freshest reading is always three
days old and it changes once a week.**

Whether that is worth anything here is exactly the sort of question this
repository answers by measuring. Two reasons to expect little and one to expect
something:

* against it - [horizon.md](horizon.md) found no demonstrated directional edge
  beyond thirty minutes, and a weekly signal cannot act faster than that;
* against it - 94 markets, of which twelve map to instruments we trade, and one
  observation each per week is 12 rows a week. Establishing anything will take
  months.
* for it - the same finding says the *fast* horizons are a tautology, so a slow
  signal is the only kind that could be measuring something real. A weekly
  number is badly matched to a thirty-minute hold and well matched to the
  timescale at which this system has never had any evidence at all.

Collected now because collection is nearly free and cannot be done
retroactively. Nothing consumes it yet, and it should not until there is enough
of it to say something - which is the mistake `news/fred.py` made in the other
direction, collecting 2,174 rows that nothing read for a month.
