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
  estimate, range-based estimators, and an ensemble over them. Every published
  call carries `vol_bps` as the unit, plus `garch_bps`, `ensemble_bps`,
  `forecast_bps` and `forecast_ratio` - the last being how far the current
  scale sits above its own long-run level, which is the regime reading.
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

## Run: the regime does predict whether a level holds

24,611 decisive touches over 7 days, each joined to the decision that carried
`forecast_ratio` - how far the current volatility scale sits above its own
long-run level.

| forecast_ratio | touches | level held |
| --- | --- | --- |
| below 0.73 | 4,922 | **78.9%** |
| 0.73 - 1.00 | 4,689 | 83.1% |
| **1.00 - 1.20** | 5,156 | **85.7%** |
| 1.20 - 2.06 | 4,922 | 83.5% |
| above 2.06 | 4,922 | **78.8%** |

**Levels hold best when volatility is near its own long-run level, and worst at
both extremes** - 6.9 points between the peak and either tail, on about five
thousand touches per bucket. It is an inverted U, not a slope, which is why
nobody would have found it by fitting a coefficient.

Both ends make sense on inspection. In a compressed regime a level is what
price is coiled against, and the move that ends the compression goes through
it. In a violent one, levels are simply run over. The middle is where a level
is a level.

**And the touch's own `regime` field carries none of this:** 82.4%, 81.6%,
82.0%, 82.4%, 81.8% across its five buckets - flat to within a point. Two
fields that sound like the same quantity, and only one of them knows anything.
Anything reaching for "the regime" should reach for `forecast_ratio`.

So the two halves are **not** currently combined. The forecast is computed,
published on every call, and read by nothing. This is the first measurement
saying it should be read.

**What it is not yet.** Held rate is not profit: `research/reachable.md` is the
standing reminder that a level holding and a trade paying are different events.
And 7 days of one regime is exactly the sample in which a volatility conditional
is most likely to be a period effect. The next step is the same one
`agreeing.md` needed - more days, and a block bootstrap over autocorrelated
touches.

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
