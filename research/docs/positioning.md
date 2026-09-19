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

## Does it lag price? Measured, and the answer splits

The worry that decides whether this is worth carrying: speculative positioning
is famously trend-following, so a fund's net might be a *description* of the
move that already happened rather than a claim about the next one.

Harness: [`harness/cotlag.py`](harness/cotlag.py), over 84 weekly reports from
the CFTC's own history files, against the broker's daily closes - so the price
series correlated is the one the desk would trade, not the futures contract.

| feed | weeks | lag corr | lead corr |
| --- | --- | --- | --- |
| eurusd | 84 | +0.026 | −0.046 |
| gbpusd | 84 | −0.144 | −0.046 |
| **usdjpy** | 84 | **+0.397** | +0.033 |
| audusd | 84 | −0.009 | +0.042 |
| usdcad | 84 | +0.176 | −0.195 |
| usdchf | 84 | −0.045 | +0.117 |
| nzdusd | 84 | −0.043 | +0.075 |
| **spx500** | 84 | **−0.433** | +0.177 |
| **us100** | 84 | **−0.508** | +0.155 |
| **btc** | 84 | **−0.464** | +0.083 |
| | | mean **−0.105** | mean **+0.040** |

At 84 observations the standard error of a correlation is about 0.11, so ±0.22
is the two-sigma line. Three findings, and only one of them is the expected
one.

**FX positioning does not clearly follow price.** Six of the seven pairs sit
inside the noise band and the signs are mixed. That contradicts the standard
"funds chase trends" story at weekly frequency, and it is mildly good news: the
number is not merely a restatement of the last week's return. `usdjpy` at +0.397
is the exception and is significant.

**The indices and bitcoin move hard *against* the prior week - −0.43 to −0.51,
all significant.** When price rose, leveraged funds cut their net long or added
to a short. The natural reading is not contrarian conviction but **hedging**:
leveraged funds short index futures against long cash equity, so a rally
mechanically enlarges the hedge.

That has a direct consequence for anything that reads this. **`spx500` at −15.4%
net short is not a bearish opinion**, and a consumer treating the *level* of
index positioning as directional would be reading a hedge book as a view. FX is
the part of this data where the net plausibly means what it looks like.

**Nothing leads.** Every lead correlation is inside the noise band, the largest
is −0.195, and the mean is +0.040. On 84 weeks there is no predictive content
at the weekly horizon.

## The Socrata API, and why it is not used

The CFTC serves the same data as JSON at
`publicreporting.cftc.gov/resource/gpe5-46if.json`, and it is better in every
respect but one.

**It answers 403 from some networks and 200 from others.** It serves the
production host in Mumbai and refuses the development machine, which is the
worst shape a dependency can have: it works until somebody tries to reproduce a
result, and then it fails for reasons unrelated to the result.

What it would buy, recorded so the decision does not have to be made again:

* **named fields.** `news/cot.py` reads `row[14]`. A column reshuffle in a
  fixed-layout government text dump would not raise - it would return a
  different category of trader, silently, which is the same class of failure
  the sign mapping is written to avoid. `lev_money_positions_long` cannot do
  that.
* **server-side filtering** to the twelve markets that matter, rather than
  parsing 94 and discarding 82.
* **incremental fetching** by report date, instead of pulling the whole file
  weekly to find one new row per market.
* **the whole history behind one endpoint**, rather than the per-year zips
  `harness/cotlag.py` downloads.

Not adopted. The lead correlations above are all inside the noise band, so this
data has no measured predictive content, and hardening the pipeline of
something nothing consumes is work at the wrong end. The named-field argument
is real and becomes the right answer the moment anything depends on this.

## What it is worth, which is now partly measured

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

Collected now because collection is nearly free. Nothing consumes it yet and
nothing should: the lead correlations above say there is no weekly predictive
content to consume, so wiring it into a signal would be adding a feature that
has already been measured to nothing.

What it is good for, on this evidence, is **interpretation rather than
prediction** - and one interpretive fact is worth having: index positioning is
a hedge book and must not be read as a view. That is a caution against a
mistake somebody would otherwise make, which is a smaller thing than a signal
and is not nothing.

The history is the useful part and it is already public: 84 weeks were
downloaded and analysed in one go from the CFTC's own archive, so the case for
collecting weekly is only to have it for whatever is asked later, not to
accumulate towards a threshold.
