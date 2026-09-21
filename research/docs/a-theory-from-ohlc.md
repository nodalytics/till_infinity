# What OHLC alone can tell us about this market — a theory, 2026-09-21

The brief: derive our own account of how the market works, from the only data available, which is
open, high, low, close and one spread figure per bar. This is that account. Every number in it was
measured or derived here, and the parts that are derived were verified by simulation.

It is a theory in the useful sense: it makes claims that constrain what is possible, several of
which are strong enough to rule out whole classes of strategy without testing them.

## 1. The law: barrier geometry cannot produce expectancy

Let `X` be the log-price with drift `mu`, barriers at `+a` and `-b`, `tau` the first exit, and let
`u` and `d` be the overshoots past the target and the stop. Optional stopping on the martingale
`X_t - mu t` gives, with `m = mu E[tau]`:

    p = (b + d + m) / (a + u + b + d)

and for market orders on both sides the expectancy collapses to

    **E[P&L] = m = mu E[tau]**

Verified across 21 jump-diffusion configurations at 40,000 paths each; see
[barrier-geometry-is-irrelevant.md](barrier-geometry-is-irrelevant.md). The barrier distances, the
reward-to-risk ratio, the jump structure and both overshoots all cancel.

**This is the central result and it is a law, not an observation.** It holds for any process with
the martingale property, so it cannot be escaped by choosing a different instrument or timeframe.
Its consequence: every strategy defined by *where to put the stop and target* has expectancy equal
to the drift over its holding period and nothing else. That is why a dozen studies here — range
position across 314,794 rows, measured moves, reward-to-risk sweeps, 1536 stretch cells, four PIP
window lengths, sweeps, order blocks, channels, gap edges — all landed on the fair-odds line. They
were varying an irrelevant parameter.

## 2. The correction: `b / (a + b)` is the wrong yardstick, and how wrong is measurable

Scoring against the continuous-path `b / (a + b)` invented the one positive result this research
ever had: Boom shorts at +4.1 points. Against the corrected benchmark with Boom's own overshoots
(`u = 0.515`, `d = 0.287`) the excess is **+0.24 points**.

Measured across 34 instruments, the correction closes the gap on the synthetics to 0.11–0.32% and
**widens** it on FX, indices and metals. That is the theory working: the synthetics compensate
jumps with drift and are martingales, so `m = 0` there. Everything else has genuine drift, and the
residual from the martingale formula **is a measurement of that drift**. USDCHF's 5.24% is the
largest in the book.

## 3. What the price path does, independent of any strategy

**Excursion is exponential with mean equal to the giveback.** A run measured to a trailing stop of
`g` has expected extent exactly `g`, matching the driftless law on Volatility 75 to within 0.05 at
every quantile ([breakout-runs.md](breakout-runs.md)). So a run has no scale of its own — it
inherits the one you impose. Widening a trailing stop widens the run proportionally and the
captured *fraction* is invariant, which means that parameter has no optimum.

**The reversal hazard is flat after two bars** — 0.243, then 0.362, 0.365, 0.323. Momentum
persists for about two bars and then never exhausts. There is no "due a reversal" state, so no
turning point can be timed.

**Levels are not special in the way level-based trading requires.** Gap edges beat a matched
placebo by +0.6% and lost to cost; premium/discount tracked `a / (a + b)` across ten deciles;
cross-window PIP agreement was flat across 130,000 touches at a detection floor *below* the
hurdle, which makes that one a real negative rather than an underpowered one.

## 4. What it costs, which is where most of the answer lives

| cost | measured value | how it scales |
|---|---|---|
| spread | 0.004 TR synthetics, 0.020 TR FX | per trade, flat |
| stop slippage | **0.063 TR** from 305 live fills | per stop-out |
| carry | 0.161–0.321 TR/day on synthetics | **linear in holding time** |

The scaling is the important part. **Carry is linear in time while any edge is at best its square
root**, so cost catches up precisely at the horizons a signal needs to work. And carry is charged
at a discrete rollover instant, not by the hour, so **being flat at rollover makes it exactly
zero** — a 0.013 TR saving for a 4% loss of opportunity, the one unambiguously free improvement
found.

Two further structural costs, both derived:

**A limit target is a mistake on a jump process.** It forfeits the favourable overshoot `u`, and
expectancy becomes `[m(a+b+d) - u(b+d)] / (a+u+b+d)` — needing 0.30 TR of drift per trade just to
break even at measured overshoots. The measurement agreed independently: Boom long went from
+0.002 to −0.084 when a 1 TR limit target was added.

**Maker entry is catastrophic on the side an instrument jumps towards.** A resting Boom short fills
only as a spike begins: −0.255 against a taker's −0.011, twenty times the spread it saved.

## 5. Capacity: profit is cubic in the edge

Composing the square-root impact law `I(Q) ~ k Q^(1/2)` with `E = m` gives optimal size
`Q* = (2m/3k)^2` and maximum net `4 m^3 / 27 k^2`. **Halving the edge divides the money by eight.**

This does not bind on a retail account against broker-quoted synthetics, where `k` is effectively
zero. It is a reason a found edge could not be *scaled*, and it composes badly with the two bounds
below.

## 6. The two bounds that close the box

**From below, a detection floor.** At measured costs, break-even is a 52.0% hit rate on FX and
51.6% on synthetics, so a rule needs about two points over fair odds, which needs about **5,000
resolved trades** as a single hypothesis. Seven of fifteen studies here had floors of 4 to 15
points and therefore could not have seen a tradable effect either way
([power-and-sizing.md](power-and-sizing.md)).

**From above, the information content of the input.** Thirty-four features of one price series
compress to about **five independent factors**. A new transform re-expresses fixed information; it
cannot add any. That is the structural reason dozens of different-looking studies produced the same
answer, and it applies equally to every formalism tried alongside them — persistent homology,
gauge analogies, Catalan combinatorics, quantum superposition. A conservation law constrains what
is possible; an analogy does not.

## 7. The one thing left, and what it looks like

`m = mu E[tau]` is the only surviving term, so the only shape of strategy available from OHLC is a
**signed forecast of return over a stated horizon** — not a level, a pattern or a structure.

Tested with the best OHLC estimator of it. **Directional efficiency** — net displacement over total
path travelled, dimensionless, scaling as `1/sqrt(n)` for a random walk and `1` for a directed one
— is a normalised drift estimate, `DE ~ (mu/sigma) sqrt(pi/2)`. Market exits, no stop, so `E = m`
exactly:

| DE window | hold | top decile | top − bottom | bootstrap ± | net of cost |
|---|---|---|---|---|---|
| 20 | 6 | +0.0251 | +0.0168 | 0.0383 | +0.0044 |
| 20 | 12 | +0.0389 | +0.0206 | 0.0622 | +0.0142 |
| 20 | 24 | +0.0501 | +0.0326 | 0.0941 | +0.0171 |
| 50 | 24 | −0.0411 | **−0.0725** | 0.1270 | −0.0741 |

**A momentum/reversal crossover: efficiency over 20 bars predicts continuation, over 50 bars it
predicts reversal, and both grow monotonically with holding period.** This is the first non-flat
structure found here and it is in the right variable.

**And none of it clears its bootstrap bar.** +0.0326 against ±0.0941. The windows overlap heavily,
so the block bootstrap cuts the effective sample far below the 37,905 rows; a naive standard error
would have called this significant, which is what it is there to prevent.

## 8. The theory, in one paragraph

From OHLC alone on these instruments: expectancy equals drift over the holding period, and nothing
about where barriers are placed can change that. Drift is small, its best available estimator shows
a coherent continuation-then-reversal shape that does not clear its own error bar, and the input
series carries only about five independent factors so no further transform of it will add
information. Costs are linear in holding time while any edge is at best its square root, and
capacity-limited profit is cubic in the edge. **The strategy space reachable from OHLC is therefore
close to empty — not because the methods were bad, but because the data is thin and the costs are
structural.** The one positive directional result this codebase ever produced reads *relative*
pricing between venues at AUC 0.70 against 0.50 for outright prices, which is information a single
series cannot contain, and it is an arbitrage residual the account cannot hold.

**So the binding constraint is data, not method.** That is an unwelcome conclusion, and it is the
one the measurements support.

## 9. What would change it, in order

1. **Tick data** — closes the slippage bracket, and is the same acquisition that would resolve
   whether Boom's overshoot is 0.063 or 0.24.
2. **Cross-venue quotes** — the only thing that ever worked here; the constraint is holdability,
   not signal.
3. **The event and news store this codebase already has**, which no study has touched. It is a
   second sensor sitting unused.
4. **Non-overlapping samples for the DE ladder** — the cheapest way to find out whether §7 is real,
   and the only open question in this document.
