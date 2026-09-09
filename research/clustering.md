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

## The open question it points at

If volatility is the predictable part and direction is not, the sharpest
version of what this repository does is: **take the part that is predictable,
and let structure supply the sign.**

That is testable and has not been tested directly. The forecast is already
published on every call as `forecast_ratio`; nothing conditions on it. Whether
a level held more often when the regime forecast was rising, falling or flat is
a question the journal can answer today, and would say whether the two halves
are actually being combined or merely both present.
