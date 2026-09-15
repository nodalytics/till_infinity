# ZMA is a working mean-reversion detector pointed at markets that do not revert

`ZScoreMomentum` - Z-Momentum Attention - is an attention-weighted z-score with
a normalised OLS slope and **dynamic 85th/65th-percentile thresholds**. It fires
`oversold` and `overbought` at extremes of an instrument's own recent z
distribution.

Two things follow from that construction before any data is involved, and both
matter more than they look.

**It can never be quiet.** The thresholds are percentiles of its own history, so
roughly 15% of bars are above the 85th percentile *by definition* - on a trend,
on noise, on a shuffled series. Measured here it fires on 1,716 to 1,773 of
11,749 bars on every symmetric arm including shuffled noise. **A signal count is
not evidence of a signal.**

**And it is a mean-reversion detector.** An extreme z is a claim that price has
gone too far and will come back. That is a statement about the process having a
mean to come back to.

## The positive control, which is the whole design

An Ornstein-Uhlenbeck process is mean-reverting by construction and its speed is
a dial, so a detector that cannot find it there is broken and nothing else it
says means anything. 11,749 scored bars an arm:

| arm | AUC | hit rate | shuffled AUC |
| --- | --- | --- | --- |
| OU, theta = 0.02 | 0.5179 | 0.509 | 0.4988 |
| OU, theta = 0.05 | 0.5492 | 0.583 | 0.4940 |
| **OU, theta = 0.15** | **0.6200** | **0.705** | 0.5080 |

**It works, and it scales with the thing it measures.** That is what makes the
null arms below readable rather than merely disappointing.

## On the synthetics it finds nothing, and on two families it is worse than nothing

| family | AUC | fired | hit rate | shuffled AUC |
| --- | --- | --- | --- | --- |
| volatility 25 | 0.4995 | 1,773 | 0.4867 | 0.4945 |
| volatility 75 | 0.4934 | 1,716 | 0.4790 | 0.4897 |
| volatility 100 | 0.4987 | 1,726 | 0.4994 | 0.5152 |
| step index | 0.5031 | 1,769 | 0.4958 | 0.4953 |
| jump 25 | 0.5006 | 1,727 | 0.5043 | 0.4987 |
| jump 10 | 0.5036 | 1,758 | 0.5017 | 0.4998 |
| boom 500 | 0.4209 | 622 | **0.4357** | 0.5259 |
| boom 1000 | 0.4604 | 287 | **0.3763** | 0.4982 |
| crash 500 | 0.2935 | 529 | **0.4612** | 0.4689 |
| crash 1000 | 0.2300 | 329 | **0.4255** | 0.5354 |

**Volatility, Step and Jump are flat**, sitting on their own shuffles. This is
what `generators.md` predicts rather than a surprise: those feeds are verified
geometric Brownian motion at `H = 0.50`, and **a random walk has no mean to
revert to**, so an extreme z carries no information about the next move.

**Boom and Crash are the finding.** On all four arms the fired signals are wrong
more often than right - 37.6% to 46.1% - while the shuffles sit near 0.5. A
detector that is reliably wrong is not neutral; acting on it costs the spread
*and* takes the losing side.

**Read the hit rate on those four and not the AUC.** With one spike in `rate`
ticks, 499 of 500 bars move the same way, so "the next bar rose" has a base rate
near zero or one and an AUC against it measures the base rate more than the
signal. The AUC column is reported for completeness and is not comparable with
the symmetric families.

## Where it would pay: constructed spreads, measured

A cross-venue spread reverts **by arbitrage** rather than by hope - the same
asset at two venues cannot drift apart without somebody closing it - so it needs
no model, only an inner join on the timestamp. BTC quoted at five venues plus a
sixth source gives six such pairs:

| spread | n | AUC | fired | hit |
| --- | --- | --- | --- | --- |
| btc 1m BINANCE-YAHOO | 6,607 | 0.7295 | 990 | 0.8313 |
| btc 1m BINANCE-COINBASE | 6,653 | 0.7253 | 1,010 | 0.8317 |
| btc 1m BINANCE-DERIV | 6,530 | 0.7201 | 983 | 0.8250 |
| btc 1m BINANCE-KRAKEN | 6,612 | 0.7048 | 991 | 0.7871 |
| btc 15m BINANCE-BITSTAMP | 5,285 | 0.6968 | 802 | **0.8367** |
| btc 1m BINANCE-BITSTAMP | 6,651 | 0.6730 | 981 | 0.7900 |

**AUC 0.67 to 0.73 and hit rates of 78.7% to 83.7%**, on six independent pairs,
against 0.50 on every outright price in this folder. That is higher than the
strongest OU control - which is what arbitrage enforcement should look like
beside a synthetic dial set to theta = 0.15.

**It is an instrument class, not a trade.** Capturing a cross-venue spread means
executing on two venues at once, and the spread is very likely inside the
combined costs. What this establishes is that the detector is sound and that it
belongs on constructed spreads rather than outright prices.

## The changepoint gate works, once the inequality is the right way round

`Focus` - the production exact-CUSUM changepoint - answers a different question
from ZMA: ZMA fires on **magnitude of displacement**, Focus on **accumulated
evidence that the mean itself moved**. Gating one by the other should raise
precision if the two are independent.

The first version required Focus to be **quiet**, on the reasoning that an
extreme z with no changepoint behind it is the reverting case. That is backwards,
and it made precision worse on every arm where it could be measured. On a
genuinely reverting series **the excursion is the evidence**, so demanding
quiet filters out exactly the displacements worth trading.

| arm | gate | fired | hit | gated | gated hit | kept |
| --- | --- | --- | --- | --- | --- | --- |
| OU theta=0.15 | quiet | 1,777 | 0.6657 | 368 | 0.6277 | 20.7% |
| OU theta=0.15 | **active** | 1,777 | 0.6657 | 1,409 | **0.6757** | 79.3% |
| btc 15m spread | quiet | 802 | 0.8367 | 423 | 0.7707 | 52.7% |
| btc 15m spread | **active** | 802 | 0.8367 | 379 | **0.9103** | 47.3% |
| btc 1m spread | quiet | 981 | 0.7900 | 358 | 0.7570 | 36.5% |
| btc 1m spread | **active** | 981 | 0.7900 | 623 | **0.8090** | 63.5% |

**83.67% to 91.03% on the best spread**, keeping 47% of signals - about five
standard errors on the gated sample. The OU control improves too, which is the
consistency check: the gate helps where reversion is real.

Two things it is not. **The gate is inert on the synthetics**, keeping 99 to 100%
of signals, which means the threshold of 1.0 is badly scaled for those series
rather than that the gate was tested there. And **precision is not profit**: 379
signals at 91% is 345 expected hits against 671 from 802 at 84%, so the gate is
worth its sample only if each trade carries a cost worth avoiding. That is the
same AUC-versus-money gap `research/asking.md` lists as outstanding.

## Where it would pay

Where `theta` is large. The OU arms say the detector is fine and the dial it
responds to is reversion speed, so the instruments to point it at are the ones
that genuinely revert: **a pairs residual, a calendar spread, an index against
its own constituents** - constructed spreads, not outright directional prices.

Nothing in the traded book is such a series today.

## What this is and is not

**Simulated, not measured.** These are each family's documented mechanics -
`grounding.md`'s `p = 0.499734` for Step, `families.md`'s memoryless spike hazard
for Boom and Crash, the 1.322x diffusive multiple for Jump - and the simulators
are faithful to what this folder has verified. A generator that differs from its
documentation in a way nobody has checked would not show up here.
[`zma.py`](harness/zma.py) runs unchanged on cached bars; that is the version to
believe, and it needs the terminal.

**Two of its own errors are recorded in the harness rather than tidied away**:
Boom and Crash were simulated with their spike directions reversed, and the AUC
was initially compared across symmetric and asymmetric arms as though it meant
the same thing in both.
