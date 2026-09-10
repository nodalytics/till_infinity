# Direction is noise; volatility is the part that repeats

The most useful thing anyone proved about markets is not about direction.

**Price direction is close to unforecastable.** Across liquid markets, the sign
of the next move is dominated by noise, and every honest attempt to predict it
runs into the same wall: whatever edge exists is small, unstable, and mostly
gone once costs are paid.

**Volatility is not.** It clusters - a large move is followed by large moves,
a quiet session by quiet sessions - and it does so reliably enough to be
modelled, across every liquid market anyone has looked at. The econometrics
that formalised this is standard textbook material and about sixty lines of
code, and it earned a Nobel prize because it is a structural property rather
than a pattern somebody noticed.

The practical consequence is the part worth stating plainly:

> A desk does not ask "will it go up?". It asks **"will the next move be large
> or small?"** - because sizing correctly inside a volatility regime is worth
> more than being right about direction.

A trader right 48% of the time who sizes with the regime beats one right 62% of
the time who sizes blindly, over any sample long enough to matter. That is not
a claim about skill. It is arithmetic about position size.

## Why this document is here rather than in a list of ideas

Because it is the assumption the whole repository is built on, and it is worth
having written down where it can be argued with.

**Nothing here forecasts direction.** The valuation says where price is
mispriced relative to structure; the side is then arithmetic, not a prediction.
[idea.md](../docs/idea.md) makes that argument at length and it is the same
argument as this one arrived at from the other end.

**Everything here is measured in volatility units.** A stop 1.4v away is 1.4
times the typical recent move, not 1.4 dollars. That is not a convenience - a
fixed distance encodes one regime and stops describing the next, which is the
same fact as volatility clustering, applied.

## What is already built

The two halves of the idea are both in production, which is worth recording
because "we should do this" is cheaper than checking whether it is done:

* **The volatility model.** `structures/vol/` carries a GARCH estimate, a HAR
  estimate, range-based estimators, a learned model, and an ensemble over them.
  [forecasting.md](forecasting.md) is the head-to-head between them, and its
  standing result is that **none of them beats reusing the last realised
  value** - which bears on where `forecast_ratio` comes from, though not on the
  measured relationship between `forecast_ratio` and level-holding below. Every published
  call carries `vol_bps` as the unit, plus `garch_bps`, `range_bps`,
  `ensemble_bps`, `forecast_bps`, and **two ratios that are easy to confuse and
  are not the same question**:

  | field | is | says |
  | --- | --- | --- |
  | `vol_stretch` | `garch.stretch` | **where we are** - current scale over its own long-run level |
  | `forecast_ratio` | `har.ratio` | **where we are going** - next bar over the last one |

  An instrument can sit at twice its usual volatility (`vol_stretch` 2.0) and
  be expected to stay exactly there (`forecast_ratio` 1.0). Measured over
  32,362 touches the two correlate at **+0.033** - they are close to
  independent, and the run below finds that only one of them predicts anything.
* **Volatility-derived sizing.** `trading/sizing.py` converts a stop expressed
  in volatility units to a price distance as `price * vol_bps * multiple /
  10_000`, then inverts the broker's tick value against the risk budget to get
  lots. A wider regime therefore produces a wider stop and **fewer lots, with
  no separate rule** - the size falls out of the unit rather than being
  adjusted afterwards.

So the answer to "do we size according to volatility" is yes, structurally
rather than as a setting: there is no path through this code that sizes a trade
without dividing by a volatility estimate.

## What this framing does not license

* **It is not a reason to trade more.** Knowing the regime tells you how big to
  be, not whether there is anything worth being big about. The measured problem
  on this book is the reward-to-risk geometry, not the sizing.
* **It is not a substitute for a directional edge.** "Sizing beats direction"
  compares two traders who both have one. A correct size on a coin flip is
  still a coin flip; what it buys is surviving long enough for a real edge to
  show, and not being ruined by a regime change.
* **Clustering is about magnitude, not sign.** A model that predicts the next
  move is large says nothing about which way, which is exactly why the
  structure half of this system exists.

## Run: the *change* in the regime predicts whether a level holds. The regime does not.

32,362 decisive touches over 14 days, each joined to the decision that carried
both ratios. Quintiles of each, held rate in each bucket, ~6,500 touches per
cell.

| quintile | `forecast_ratio` — where we are going | `vol_stretch` — where we are |
| --- | --- | --- |
| lowest | 81.3% | 84.6% |
| 2nd | 84.8% | 83.4% |
| **middle** | **86.4%** | 83.6% |
| 4th | 85.1% | 83.4% |
| highest | 81.4% | 84.0% |
| **peak − tail** | **5.1 points** | **1.2 points, no shape** |

**Levels hold when the volatility scale is about to stay put, and break when it
is about to change - in either direction.** That is an inverted U, not a slope,
which is why nobody would have found it by fitting a coefficient.

Both ends make sense on inspection, and neither is about being calm or violent.
A forecast far *above* one says the next bar is several times the last: an
expansion of that size runs a level over regardless of what the level is. A
forecast far *below* one says the scale is collapsing, and a level holding
price against a move is exactly what stops mattering when the move stops. The
middle - next bar the size of the last - is where a level is a level.

**The regime level itself carries none of this.** `vol_stretch` is flat to
within 1.2 points with no monotone or U shape, and the touch's own `regime`
field is flat too (84.4 / 83.4 / 83.8 / 84.0 / 83.5). Three fields that sound
like the same quantity, and one of them knows something.

### The correction, and why it is not cosmetic

An earlier version of this section reported the `forecast_ratio` numbers under
`vol_stretch`'s definition - "how far the current scale sits above its own
long-run level". The same wrong gloss had reached `scaling.by_regime`,
`config.regime_band`, `docs/todo.md` and the harness itself.

It reads like a naming slip and it isn't, because the two fields correlate at
**+0.033**. A reader acting on the prose would have reached for the field named
in it, gated on `vol_stretch`, and gated on the one with nothing in it. The
live code escaped only because `scaling.by_regime` was wired to
`forecast_ratio` - right for the wrong reason.

The general lesson is the one this repository keeps re-learning in different
clothes: **a field's name and a field's definition are different objects**, and
a measurement is a statement about the definition. `run_vol` returning exactly
0.000 on every touch and `articles.symbols` being `[]` on all 24,214 rows are
the same failure with the volume turned up - a number that arrives, looks like
a reading, and means nothing.

### Against the earlier read

7 days and 24,611 touches gave 85.7% at the peak against 78.9 / 78.8 at the
tails. 14 days and 32,362 gives 86.4% against 81.3 / 81.4. **The peak is stable
and the tails have come in by about 2.5 points** on twice the data, which is
the direction a period effect usually moves when the period lengthens. The
shape survived; the size of the claim shrank by a quarter.

### What it is not yet

Held rate is not profit. `research/reachable.md` is the standing reminder that
a level holding and a trade paying are different events, and nothing here has
been joined to money. A block bootstrap over autocorrelated touches is still
owed - the same one `agreeing.md` needs. `regime_band` stays at 0.0 until then.

## Sizing: half of it is automatic and the other half is switched off

An earlier version of this document said sizing was volatility-aware, full
stop. That is too strong and the distinction matters.

**What is automatic.** A stop is expressed in volatility units and converted
through `vol_bps`, so a wider regime gives a wider stop and the lot count falls
to keep the *money at risk* constant. Nothing has to be configured for that and
nothing can turn it off.

**What is not.** Constant money at risk is **not** constant risk when an
instrument's own volatility is many times another's. `scaling.by_volatility`
exists for exactly that - it scales a position down by `target / vol_bps` when
an instrument runs hotter than the book is sized for - and it is **off**:
`TRADING_VOLATILITY_TARGET_BPS` is unset, so it returns 1.0 on every trade.

The spread it would be correcting, measured over 7 days of published calls:

| feed | median vol_bps | p90 |
| --- | --- | --- |
| eurusd | 0.72 | 2.33 |
| gbpusd | 0.95 | 2.47 |
| spx500 | 1.62 | 5.90 |
| us100 | 2.12 | 8.25 |
| usdjpy | 2.20 | 4.66 |
| btc | 3.77 | 10.32 |
| gold | 3.78 | 9.91 |
| silver | 7.60 | 32.38 |
| boom_500_index | 8.65 | 24.26 |
| **volatility_75_index** | **17.75** | **45.38** |

**A 25x spread, all carrying the same risk fraction.** A volatility index gets
the same fraction of equity at risk as EURUSD, on an instrument that moves
twenty-five times as far in the same minute. The stop widens and the lots fall,
so the *arithmetic* loss on a stop is equal - but the portfolio's exposure to a
violent instrument having a violent day is not, and that is what the scaler is
for.

This is not a small dial. It bears directly on where the money has actually
gone: the synthetics are the loss centre in every breakdown of this book.

**A target near 3.0bps** would leave the majors and the indices at full size and
cut silver, boom and the volatility indices by two-thirds or more. It only ever
reduces - a sizing model that can size *up* turns an estimation error into a
margin call - so the risk of setting it is under-sizing, not over.
