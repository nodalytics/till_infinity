# Focal points: crossing a big figure accelerates a little more than chance, and nothing about it pays

Measured 2026-09-29 on the lab with [`focalpoints.py`](../harness/focalpoints.py): the lab's broker
15m bars for 15 FX pairs, XAU, XAG, BTC, ETH and SOL, with five Deriv random walks as the control.
Reported on each series' last 40% by time, with halves.

## The question: game theory at the chart

A price that many traders watch is a Schelling focal point: orders collect there because everyone
expects everyone else's to. Two published forms are testable:
- **Osler (2003):** take-profit orders cluster *at* round numbers, so trends tend to reverse
  there. Stop-losses cluster just *beyond* them, so once a round number is crossed the move tends
  to accelerate (a stop cascade).
- **The stop hunt:** price pokes just beyond a widely watched extreme (yesterday's high or low),
  takes the stops resting there, and comes back (a "liquidity sweep").

**Levels:**
- **round:** the big figure, a step of 10^(floor(log10 price) - 2), so 1.1000 on EURUSD, 150.00 on
  USDJPY, $10 on gold and $100 on BTC;
- **half:** the half figure between them;
- **round placebo:** the same grid shifted by a random 20-80% of a step;
- **prior day:** yesterday's UTC high and low;
- **prior day placebo:** those levels shifted by 0.5-1.5 baseline moves.

**The races** start at each level's first touch of the day, all within an hour and in units of the
trailing baseline move (sigma):
- **bounce:** does price go one sigma back before one sigma through?
- **cascade:** after a close half a sigma through, does it go one more sigma onward before it
  returns to the level?
- **sweep reverses:** after a poke of up to one sigma through that closes back, does price go one
  sigma back before making a new extreme?

The random walks have round numbers too, and nobody places orders at them, so they are the control
for the arithmetic.

## Results

| | bounce: round / placebo | **accelerates after crossing: round / placebo** | sweep reverses: prior day / placebo |
| --- | --- | --- | --- |
| FX (23,677 touches) | 51.9% / 53.1% | **56.7% / 54.1%** (halves 57.0 / 56.3 against 53.4 / 54.9) | 66.2% / 67.7% |
| metals (7,352) | 47.9% / 48.5% | 60.0% / 58.8% | 71.2% / 69.0% |
| crypto (8,406) | 52.0% / 52.8% | 57.0% / 55.7% | 78.1% / 71.1% |
| **random walks** (13,144) | 48.9% / 48.5% | **53.7% / 52.5%** | 62.5% / 57.7% |

(standard errors: about 0.7-1.2 points for bounce and cascade, 1.3-3.8 for sweeps)

- **Round numbers do not make price turn.** The bounce rate at a big figure equals the placebo's
  everywhere, and in FX it is slightly lower (51.9% against 53.1%). The take-profit half of Osler's
  story does not show at this resolution.
- **Crossing a big figure in FX accelerates, as Osler's stop-loss half says.** It goes onward 56.7%
  of the time against 54.1% at the placebo, about 2.6 standard errors, and the same in both halves.
  The random walks show +1.2 points at the same test, so the market's own share is about 1.4 points.
  Metals and crypto show +1.2 and +1.3, the same as the control.
- **No stop hunt in FX.** A poke through yesterday's high or low that closes back reverses no more
  often than a poke through a placebo level (66.2% against 67.7%). Crypto shows +7 points (78.1%
  against 71.1%, about 1.5 standard errors), and the random walks show +4.8 at the same test, so it
  does not clear its own control.

## What it is worth

The one effect beyond the control is the FX cascade: 1.4 points on a race worth about a sigma and a
half. A breakout trade taken on it earns roughly 0.02-0.04 of a baseline move before costs, against
a 15m FX spread of about 0.46. It is real, in the direction the literature says, and far too small to
trade.

It does say one thing about **where not to put a stop**. A stop placed just beyond a big figure sits
where crossings accelerate, which is where fills are fastest and slippage worst. That was not
measured here; it would need live fills around big figures, and the journal's `stop_overshoot`
record is the place to check it.

## What this settles

- **Round numbers and yesterday's extremes are not self-fulfilling reversal levels** on this desk's
  instruments. They behave like placebo levels, as volume-profile levels did
  ([`orderflow.md`](orderflow.md)) and as `structures`' levels do against a random walk
  ([`skill.md`](skill.md)).
- **The stop-cascade effect at big figures exists in FX** at about 1.4 points beyond chance. It is too
  small to trade, and possibly worth knowing for stop placement.
