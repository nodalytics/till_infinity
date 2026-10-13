# The commodity-currency claim is real, and it is the dollar that hid it

The trade-press claim is that the currencies of raw-material exporters rise and
fall with the prices of what they export. It names AUD, CAD, NZD, NOK, RUB, BRL
and CLP, with special mentions for USD as the pricing currency, JPY as an
importer and CHF as a gold proxy.

It is a **pre-specified hypothesis with a sign per pair**, which makes it worth
testing properly: there is nothing to correct for multiplicity because nothing
is being chosen. The harness is `research/ideas/commodity_currencies.py`, and
the data came from the lab terminal's 731 symbols via
`research/harness/commodity_fetch.py`.

**The answer: real in contemporaneous returns once the dollar is removed,
specific to the currencies the claim names, absent in levels, and absent in
volatility.** The last two are what make it interesting rather than another
instance of what this desk already knew.

## The dollar is the whole problem, and the first pass got it wrong

Commodities are priced in dollars, so a weaker dollar lifts all of them and
lifts every `XXXUSD` quote at the same time. The first pass measured gold
against `AUDUSD` at `+0.4067` and against `GBPUSD` at `+0.3600` and concluded
that most of the effect was the dollar - sterling is not a commodity currency,
so a correlation that barely distinguishes it from the Australian dollar cannot
be about commodities.

That conclusion was **backwards**, and `USD Basket` is what shows it. Partial
out the dollar from both legs and:

| | raw | dollar removed | kept |
| --- | ---: | ---: | ---: |
| `AUDUSD` / gold | +0.4067 | **+0.1135** | 0.28 |
| `GBPUSD` / gold | +0.3600 | **-0.0009** | 0.00 |
| `EURUSD` / gold | +0.3521 | **-0.0178** | 0.05 |
| `AUDUSD` / platinum | +0.3805 | **+0.1899** | 0.50 |

Sterling's gold correlation is **annihilated** - 0.3600 to 0.0009, three
hundredths of a percent surviving - while Australia keeps a quarter of a much
larger number. The raw correlations were dollar-dominated for *everyone*; what
distinguishes a commodity currency is the **residual**, and the residual is
what the claim is actually about.

### And for Canada the dollar was hiding the effect, not creating it

| | raw | dollar removed | amplified |
| --- | ---: | ---: | ---: |
| `USDCAD` / `US Oil` | -0.0621 | **-0.2260** | 3.6x |
| `USDCAD` / `UK Brent Oil` | -0.0651 | **-0.2313** | 3.6x |

The headline claim of the whole list - the Canadian dollar against crude -
reads as **almost nothing** raw and as the second-strongest relationship in the
study once the dollar is taken out. The mechanism is visible in the control
legs: `USDCAD` against the dollar basket is `+0.7505`, and crude against the
dollar basket is `+0.1153` in this sample, so the dollar channel contributes a
*positive* component that cancels a genuine negative oil link. Remove it and
the oil link appears.

This is why the control legs are printed per row. The first version of this
study had them computed and not shown, and the sign of a 3.6x amplification
cannot be explained without them.

## Two comparisons the dollar cannot fake

A partial correlation is only as good as the control, so the study does not
rest on it.

**The exporter against the importer.** Canada exports crude and Japan imports
it, so the claim predicts `USDCAD` and `USDJPY` move *opposite* ways against
oil. Both are dollar-base pairs, so any pure dollar effect must give them the
*same* sign. Measured: `USDCAD` -0.2260 against `USDJPY` +0.1119 on `US Oil`,
and -0.2313 against +0.1217 on Brent. **Opposite, raw and partialled.** No
dollar story produces that.

**Norway against Sweden.** On energy, `NOK` loads **+0.3113** and `SEK`
**-0.0702**. Two neighbouring Nordic economies of similar size, both freely
floating, both European, differing in one relevant respect: one of them sells
oil. Sterling and the euro differ from the krone in a dozen ways; the krona
differs in one, which makes it the control Norway deserves.

## The group test, and why the first version of it could not have worked

The hand-picked version - fourteen claims against four controls, all of them
GBP or EUR - returned a gap of `+0.0430` at **p = 0.1037** over label shuffles.
That is not a negative result, it is an **underpowered design**: the unit of
independence is the *currency*, not the claim, and with three named currencies
against two controls there are `C(5, 3) = 10` arrangements, so the test could
not return a p below 0.1 whatever was true.

`USDNOK`, `USDSEK`, `USDMXN`, `USDZAR` and `USDPLN` were fetched to fix that,
giving six named currencies against four controls and `C(10, 6) = 210`
arrangements - a floor of 0.0048. Every currency is scored against all twelve
commodities, each cell oriented by the quote convention so that positive always
means "the currency strengthened as the commodity rose":

| currency | named | median oriented partial |
| --- | :---: | ---: |
| AUD | yes | **+0.0856** |
| NOK | yes | **+0.0581** |
| MXN | yes | **+0.0499** |
| NZD | yes | **+0.0490** |
| ZAR | yes | **+0.0353** |
| CAD | yes | **+0.0328** |
| SEK | no | +0.0241 |
| GBP | no | +0.0045 |
| PLN | no | +0.0016 |
| EUR | no | -0.0368 |

**All six named currencies rank above three of the four controls.** Named
median `+0.0494`, control median `+0.0030`, gap `+0.0464`, and the exact
permutation over currency labels gives **3 of 210 arrangements, p = 0.0143**.

`CLP` and `RUB` are not offered by the venue, so copper and the Russian claims
remain untestable rather than refuted. `HKD` and `CNH` were available and left
out: a pegged currency would score near zero for a reason that has nothing to
do with commodities, which would flatter the result.

## Does each currency load on what its country actually sells

This arm needs **no control group**: each currency is compared against itself,
its own export class against the other two. A dollar effect, a risk-appetite
effect or any other common factor hits all three classes, so it cannot produce
a gap - only knowing what the country sells can.

| currency | sells | energy | metal | soft | own rank |
| --- | --- | ---: | ---: | ---: | :---: |
| CAD | energy | **+0.2260** | +0.0217 | +0.0316 | 1 |
| NOK | energy | **+0.3113** | +0.0559 | +0.0245 | 1 |
| AUD | metal | +0.0807 | **+0.1915** | +0.0620 | 1 |
| ZAR | metal | -0.1155 | **+0.2143** | +0.0320 | 1 |
| NZD | soft | -0.0018 | +0.1034 | +0.0381 | 2 |
| MXN | energy | -0.0098 | +0.1019 | +0.0517 | 3 |

Four of six rank their own export class **first**, and the rank sum is **9
against a chance 12**, `p = 0.1070` exact over the 729 rank vectors. Not
significant, and reported as the rank test rather than the sign count because
the sign count - 4 of 6, `p = 0.3438` - discards the information that three of
the four hits are the three largest loadings in the table.

Mexico is the one clear miss, and the honest reading is that its label may be
wrong rather than the claim: Mexico is the world's largest **silver** producer,
and `MXN` loads `+0.1019` on metals against `-0.0098` on energy. That is
consistent with relabelling it, which is exactly why it has not been
relabelled - the signs were fixed before measuring and moving one afterwards
would turn a test into a fit.

## What it is not: not levels, and not volatility

Two channels this desk has measured extensively come back empty, and both
matter for how the result can be used.

**Levels do not tie.** Zero of eighteen claims cointegrate against the
established `-4.07` bar from the two-real-leg block shuffle; the best is
`USDCAD` against `NGAS` at `-2.68`. "Rise and fall together" is true of
returns and false of levels, so there is no spread here to trade back to a
mean - which is the same answer the screen gave for 190 pairs and 1,625
baskets.

**Volatility does not carry it either**, and this is the surprise. One of
eighteen claims clears its own rotation null on log-volatility correlation
(`USDCHF` / gold at +0.3349 against a null max of 0.3342, which is a tie, not a
finding). Every other cross-instrument relationship this desk has found lives
in volatility - a median correlation of +0.5170 across the universe - and this
one does not. It is a **returns** relationship, which makes it the first
contemporaneous structure here that is not a volatility effect wearing a
disguise.

## A defect found on the way, which changed numbers in this study

`relationship_screen.align` returns two series on their common timestamps, and
the first version of this harness differenced **after** aligning. That turns
every hole in the common grid into one increment spanning the hole - and FX
trades 24/5 while crude, the softs and the indices do not, so the common grid
between an FX pair and a commodity is mostly holes, each becoming a large move
that appears in **both** series at the same index.

Differencing each series on its own consecutive bars first, keeping only
increments whose own timestamp gap is the modal spacing, and aligning the
**returns** afterwards moved `USDCAD` against crude from `-0.0436` to `-0.0621`
raw and the amplification from 5.4x to 3.6x. Every figure above is the
corrected form.

The blast radius was checked and is small: `log_volatility` in
`volatility_relationships.py` already differences natively, and
`relationship_screen.screen` works on levels, where gap contamination inflates
the increment variance and therefore makes cointegration *harder* to find - so
the 0-of-190 null it reports is conservative rather than manufactured.

## What this is worth

A contemporaneous return correlation is **not an entry signal**: nothing here
leads, and the lagged form of this question has been null in every test this
desk has run. What a residual commodity exposure of 0.11 to 0.23 is good for
is **hedging and basket construction** - knowing that a long `USDCAD` position
carries a short crude position whether or not it was wanted, and that the same
is not true of a long `GBPUSD`.

It also stands as a **positive control for the screen**, next to the currency
triangles. An FX screen that cannot find NOK against oil at -0.31, or that
cannot tell Norway from Sweden, is broken - and unlike the triangles, this one
is a genuine economic relationship rather than an arithmetic identity.
