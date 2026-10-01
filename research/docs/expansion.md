# Volatility expansion can be called from compression and the calendar; a breakout straddle still cannot trade it

Measured 2026-10-01 on the lab with [`expansion_build.py`](../harness/expansion_build.py) and
[`coil_trade.py`](../harness/coil_trade.py). The universe is 48 real instruments (15 FX pairs, gold,
silver, BTC, ETH, SOL, 20 US stock CFDs) at 15m and 1h, plus 8 Deriv markets, scored apart.
Walk-forward: each series' first 60% by time trains and its last 40% scores. The controls are
walks we generate ourselves.

## The question

[`fractal-twins.md`](fractal-twins.md) found that, from a compressed state, an expansion within 16
bars is predictable (gradient boosting AUC 0.728 at 15m, 0.738 at 1h). Two things kept it out of
production:

- it read 288 raw window values, which a live engine cannot keep for every series;
- its control was Deriv's indices, which this program no longer treats as controls.

Both are fixed here. The question is re-asked through the production class itself,
`structures/learning/expansion.py`.

**Definitions** (the research ones):

- **compressed:** the 14-bar smoothed true range sits at or below the 20th percentile of its last
  1,500 bars;
- **expansion:** that percentile reaches the 80th within the next 16 bars.

**The features** are compact running state:

- compression depth and run length;
- fast against slow range, and the range against its own mean;
- volatility of volatility, and the last bar's range;
- how directional the last 16 bars were;
- the clock (hour, hours to the weekly close);
- the next timeframe's percentile;
- tick volume against its norm, overall and for the hour.

## Pre-registered, before the run

1. Real-market held-out AUC ≥ 0.68 in both halves of the held-out period.
2. Real markets beat our iid t walks by ≥ 0.10. Some walk skill is mechanical (a deep compression
   takes longer to climb back), so the walks are not held to 0.5.
3. Top-decile calibration (realised over predicted) within 0.7–1.4.

GARCH walks are reported, not gated, to show how much of the skill is plain volatility clustering.

## Result: it passes every bar, and beats the research model

645,700 compressed bars; 258,293 held out.

| | AUC held out |
|---|---|
| **Real markets** | **0.781** (first half 0.779, second half 0.784) |
| Metals / crypto / FX / stocks | 0.829 / 0.808 / 0.752 / 0.752 |
| 15m / 1h | 0.787 / 0.773 |
| Deriv | 0.556 |
| iid t walks / GARCH walks | 0.548 / 0.564 |
| Compression depth alone (best way round) | 0.598 |

- **Top decile on real markets:** 25.8% of compressed moments expand within 16 bars, against a
  7.4% base rate. That is **3.5x**, with calibration 1.04.
- **It is more than volatility clustering:** real markets beat the GARCH walks by 0.22.
- **Deriv barely registers.** Its generators hold volatility constant by law
  ([`generators.md`](generators.md)), so what little there is to time is the smoothing's own
  mechanics, the same as on walks.
- The dependency-free evaluator reproduces the training library exactly (max difference 0.0).

**Shipped:** `till_infinity/models/expansion.json`, trained on everything but the last 14 days.
It reads only while a series is compressed. Its card line, from 2.5x the normal rate, is:

    🌀 coiled · expansion next 16 bars 31% · 3.0x normal · no side

It joins the fortnightly retrain contest (`models/retrain.py`, `expansion`) with these gates:
real AUC ≥ 0.68, at least 0.10 over the walks, not worse than the champion, and calibration within
0.7–1.4.

**It says nothing about direction.** Among compressed moments that expanded, every model tested
in fractal-twins.md called the side at a coin (AUC 0.47–0.53).

## Can it be traded? B1 and F2 (research/docs/ideas.md)

**The idea:** if a big move is coming and its side is a coin, take both sides. Set resting stop
orders above and below the compression box, cap each side with a stop, and let the move pay. An
*unconditional* straddle had already lost; the question is whether the alert changes that.

**Pre-registered rules:**

- **Box:** the high and low of the 16 bars ending at the arming bar.
- **Orders:** a buy stop at the box high plus the spread, and a sell stop at the box low, resting
  for 16 bars.
- **Exits:** each leg's stop sits at the opposite edge (box height plus spread), which caps that
  side's loss. **No take-profit.** The exit is the stop or 16 bars, the alert's horizon.
- **Versions:**
  - *straddle:* both legs stay live, so a failed breakout that reverses fills the other side;
  - *oco:* the first fill cancels the other.
- **Skips:** a box under 3 spreads (untradeable); one arming per series per 16 bars.
- **Costs:** MT5's per-bar spread from the broker's own bars, swap from the broker's symbol
  specs. Backtested with [`../mt5bt/`](../mt5bt/README.md) on held-out predictions only.
- **F2's stress:** F_t = 0.98 F_t−1 + max(0, log(TR_t / median TR of the last 500 bars)). F2 arms
  when the series is compressed and F_t is in the top fifth of its own last 1,500 bars.

**Results, R per trade net of spread and swap:**

| Arm | Straddle | OCO |
|---|---|---|
| **B1:** alert ≥ 2.5x | **−0.053** [−0.116, +0.013], n 1,489 | **−0.036** [−0.098, +0.030], n 1,183 |
| Compressed, alert quiet (< 1x) | −0.106 [−0.127, −0.082], n 16,340 | −0.068 [−0.092, −0.044] |
| Compressed, any | −0.097 [−0.118, −0.074], n 19,848 | −0.064 [−0.087, −0.040] |
| **F2:** stress high | **−0.158** [−0.258, −0.063], n 431 | −0.126 [−0.224, −0.027] |
| F2 null: stress low | −0.102 [−0.131, −0.074] | −0.064 [−0.093, −0.036] |
| B1 and F2 together | −0.271 [−0.488, −0.028], n 48 | −0.202 [−0.418, +0.017] |
| B1 on 12 GARCH walks | +0.045 [−0.014, +0.109] (per walk +0.039 ± 0.038) | +0.047 [−0.018, +0.112] |

**Verdict: no, as specified.**

- **B1 loses half as much as the null, but the gain is cost, not move.** Gross of costs, B1 makes
  −0.024R a trade against the quiet null's −0.030. That is the same. The improvement is the spread:
  0.018R against 0.068R, because the boxes the alert picks are wide relative to the spread. The
  alert correctly says the range will expand, but the expansion does not run cleanly away from a
  16-bar box edge often enough to pay. Big ranges can be two-sided, and the time exit catches
  most trades mid-move (about 70% of exits).
- **The halves disagree:** +0.031 then −0.137 (straddle), +0.041 then −0.112 (OCO).
- **By family:** metals are positive in B1 (+0.099 straddle, +0.069 OCO) and crypto and stocks
  clearly negative. One family of four being positive is what chance produces; treat it as a
  hypothesis for fresh data, not a finding.
- **F2 is worse than its own null.** High unrecovered stress in a compressed market made the
  straddle lose more, not less. That is the second time a fatigue-style measure has had the wrong
  sign here ([`susceptibility.md`](susceptibility.md)).
- **The walks show nothing,** as they should: +0.039 ± 0.038 per walk.

**What it would take to trade it:** the alert is a good *risk* reading, not an entry. Untested
trades that fit what it measures better (each a new trial):

- **Options:** buy volatility when the alert fires. Deribit BTC and ETH are reachable; the broker
  has no options.
- **Size and stops for trades taken anyway:** widen the stop or cut the size on a live position
  when its series fires the alert (ideas.md A1.1, A1.3).
- **Exits that follow the expansion** instead of a fixed 16 bars, such as trailing once the range
  percentile passes 0.8. Pre-register before running; the B1 and F2 runs above are counted.

## Magnitude without direction, and the whipsaw (Part G, [`energy.py`](../harness/energy.py))

The sharper question ([`ideas.md`](ideas.md) Part G): does the alert carry information about the
size of the coming move but not its sign? And is the whipsaw what kills the bracket?

**Pre-registered:**

- **Excursion:** the two-sided excursion Y = max(MFE up, MFE down) over 16 bars, in σ (the
  14-bar smoothed true range).
- **Whipsaw:** both edges of the 16-bar box touched within 16 bars.
- **Groups:** not compressed, compressed with the alert quiet, alert 1–2.5x, alert ≥ 2.5x.
- **Sample:** held-out rows only; 391,351 of them.

| Group | P(Y > 2σ) | P(Y > 4σ) | P(Y > 6σ) | Whipsaw | P(up) | 3σ reached by bar 16 |
|---|---|---|---|---|---|---|
| Not compressed | 0.74 | 0.25 | 0.09 | **0.10** | 0.51 | 44% |
| Compressed, alert quiet | 0.86 | 0.41 | 0.17 | 0.21 | 0.51 | 61% |
| Alert 1–2.5x | 0.91 | 0.46 | 0.19 | 0.24 | 0.50 | 69% |
| **Alert ≥ 2.5x** | 0.95 | **0.60** | 0.29 | **0.30** | 0.49 | **79%** (median bar 7) |

- **Energy, not direction.** Alert strength carries 0.0026 bits about |R| against 0.00026 about
  sign(R), each far above its shuffled null. Ten times more about size than about sign, though
  the sign share is not quite zero: P(up) drifts from 0.53 in the weakest decile to 0.50 in the
  strongest.
- **The alert moves the whipsaw the wrong way.** By alert decile, P(Y > 4σ) rises from 0.39 to
  0.52, and the whipsaw rate rises with it, from 0.18 to 0.28. The energy it predicts is in good
  part two-sided. That is why the box bracket cannot harvest it.
- **Both halves agree:** P(Y > 4σ) is 0.59 and 0.60 for the alert.

**SL-only trades with a trailing stop.** Initial stop at the opposite box edge, then a trail
k·σ behind the best completed-bar price, no take-profit, 96 bars at most.

- **A:** any compressed bar; **B:** the alert. Both use a two-sided OCO bracket.
- **C, D:** the same gates, with one order in the box's drift.
- 20 configurations, so the best is a best-of-20.

| | Primary (d = 0, k = 2) | Buffer 0.5σ | Buffer 1σ | Close-confirmed | Trail 3σ |
|---|---|---|---|---|---|
| A: any, bracket | −0.071 | −0.056 | −0.049 | −0.064 | −0.081 |
| **B: alert, bracket** | **−0.013** [−0.055, +0.032] | −0.013 | **−0.010** [−0.043, +0.024] | −0.051 | −0.043 |
| C: any, drift side | −0.080 | −0.062 | −0.050 | – | −0.087 |
| D: alert, drift side | −0.026 | −0.029 | −0.018 | – | −0.039 |

- **The trail is worth +0.04R on B** (−0.053 static → −0.013). B beats A in every column, so the
  gate does change the economics.
- **Nothing clears zero.** The best cell, B with a 1σ buffer, is −0.010R and gross +0.003.
  Closing beyond the edge before entering makes it worse, not better.
- **The bracket's EV improves with alert strength** at the top: −0.08 to −0.10R in deciles 1–7,
  −0.031 in decile 8, −0.006 in decile 9 (gross +0.013). The bottom decile breaks the pattern
  (−0.051).
- **The walks** give +0.008 ± 0.029 per walk.

**Where that leaves it:** the alert is a real, well-calibrated forecast of *energy*. The obstacle
to trading it is the whipsaw, which the alert makes more likely, not less. The next question is
the one the trade needs answered directly: once price leaves the box, does it commit? That is
measured on post-breakout paths against a martingale's own odds, in
[`escape.py`](../harness/escape.py).

## Once price leaves the box, does it commit? ([`escape.py`](../harness/escape.py))

The whipsaw is B1's central failure mode, so this asks the question the trade needs: **does
compression change the distribution of post-breakout paths?**

**Pre-registered:**

- **Box:** the 16 bars ending at the arming bar; W is its height.
- **Breakout:** the first bar within the next 16 that leaves the box. Follow it 48 bars from its
  close.
- **Outcomes:**
  - *clean:* reaches the edge + 1W before the opposite edge;
  - *whipsaw:* reaches the opposite edge first;
  - *stall:* neither.
- **The martingale null, event by event:** P(clean) = distance to the opposite edge / (that +
  distance to +1W).
- **The verdict compares real markets with GARCH walks**, because stalls count as not-clean, which
  puts the raw excess below zero on any process.

| First breakouts | n | Clean | Whipsaw | Stall | Excess over martingale odds | Median BQ | Median MAE/MFE |
|---|---|---|---|---|---|---|---|
| Alert ≥ 2.5x | 2,153 | 0.430 | 0.385 | 0.186 | −0.098 [−0.120, −0.076] | 0.97 W | 0.92 |
| Compressed, alert quiet | 13,377 | 0.428 | 0.438 | 0.134 | −0.076 [−0.087, −0.065] | 1.04 W | 1.01 |
| All compressed | 17,667 | 0.426 | 0.423 | 0.151 | −0.082 [−0.091, −0.073] | 1.01 W | 0.99 |
| **GARCH walks** | 2,372 | 0.420 | 0.411 | 0.169 | **−0.083** [−0.105, −0.061] | 0.91 W | 0.96 |

**No.** Breakouts from compressed boxes on real markets commit exactly as often as breakouts on
GARCH walks: −0.082 against −0.083. Every half and every family is negative, from −0.03 (crypto)
to −0.14 (stocks under the alert).

- **The alert's breakouts commit slightly *less*:** −0.098, within noise of the walks. The alert
  predicts energy, not commitment.
- **Refractory:** a second breakout after a whipsaw does better than a first (−0.054 against
  −0.082). The walks show the same lift (−0.048 against −0.083), so it is the geometry of the
  second box position, not a market's tendency to oscillate after a failure.
- **Precursors at the breakout bar are geometry, not information:**

  | Feature | AUC on markets | AUC on walks |
  |---|---|---|
  | Closed outside the box | 0.581 | 0.580 |
  | The bar's range | 0.526 | 0.531 |
  | Tick-volume z | 0.536 | – |
  | Wait, box width, alert strength | 0.49–0.51 | 0.50–0.51 |
  | Gradient boosting, all features (second half) | 0.612 | 0.585 |
  | The martingale geometry alone | 0.606 | 0.618 |

  Everything together adds 0.006 over the geometry.

**So:** the hoped-for state, where direction is uncertain but continuation is not, is not what
compression produces on these markets and bars. Compression reliably predicts that the market
will move more (energy). It does not predict that a move out of the box will keep going. A
two-sided bracket therefore pays for the whipsaw at the rate a random walk does, and its costs
make it lose. The alert stays in production as a risk reading: sizing, stops, and not being
surprised. It is not an entry.

**What is left untested, each a new trial:**

- **Options**, which monetise energy without needing commitment: buy volatility on the alert.
  Deribit BTC and ETH are reachable.
- **Other direction-free precursors** of energy (the shock forecaster, release timing, open
  interest), measured with this same harness against the same walks.
- **Tick-level breakouts** (`mt5bt --ticks`), in case bars hide a commitment signature at the
  moment of the break.

## What else foretells an expansion? ([`precursors.py`](../harness/precursors.py), [`signature.py`](../harness/signature.py))

**The question:** is compression one sensor of a broader "pre-expansion state"? Fifteen candidate
sensors, each pre-registered, were added one at a time to the alert. A sensor counts if it adds
≥ 0.005 held-out AUC in *both* halves.

| Sensor | Held-out AUC (first / second half) | Counts |
|---|---|---|
| The alert's 15 features | 0.786 (0.784 / 0.788) | baseline |
| **+ the calendar ahead:** the series' weekday × hour range profile over the next 16 bars against the last 16 | **0.803 (0.805 / 0.800)** | **yes, +0.017** |
| + cross-asset breadth (share of the family already expanding) / family mean percentile | 0.785 / 0.786 | no |
| + spread state (spread against its 500-bar median) | 0.787 | no |
| + volume build-up (slope of tick volume over 16 bars) | 0.786 | no |
| *Over alert + calendar (0.803):* | | |
| + boundary exhaustion (tests of the edge; slope of their penetration) | 0.803 / 0.803 | no |
| + vol term structure (RV 4/16, RV 16/64) | 0.803 / 0.803 | no |
| + directional entropy (up-close share, 32 bars) | 0.803 | no |
| + return-sequence entropy (sign 3-grams, 64 bars), and its change | 0.802 / 0.802 | no |
| + cross-asset dispersion; family mean correlation, and its change | 0.802 / 0.801 / 0.801 | no |
| + all ten | 0.800 | no (overfits) |

- **The calendar is the one other precursor.** A quiet market with a busier session ahead expands
  by the clock alone, and the alert did not know the calendar.
- **Everything else the bars can say, the alert's own state already says.** Each sensor alone
  carries some signal (breadth 0.56 alone, sequence entropy and correlation correlate with the
  label), but none adds to compression plus the calendar.
- **No common latent state:** the ten sensors' first principal component explains 19% of their
  variance at compressed bars. They are not one pre-expansion state seen ten ways.
- **Sensors these markets cannot answer from bars:**
  - liquidity (depth, cancel rates);
  - volume composition (trade count against trade size);
  - order flow against price.

  They need order-book and trade data. On crypto that is the Binance archive (`bookDepth`,
  `aggTrades`, `metrics`) or Bybit; see [`../freqtrade/README.md`](../freqtrade/README.md).

**Shipped:** the calendar is now the alert's 16th feature (`clock_ahead`), learned online per
series. Re-validated with the same pre-registered gates:

- **Real AUC 0.798**, up from 0.781; both halves 0.798 and 0.797.
- **By family:** crypto 0.848 (from 0.808), FX 0.773 (from 0.752), metals 0.837, stocks 0.750.
- **15m:** 0.812.
- **Top decile:** 3.7x the base rate, calibration 1.03.
- **Walks:** iid 0.550, GARCH 0.582.

## How long does an expansion last, and how far does it go?

**Definitions:**

- **Onset:** the bar where the range percentile crosses into the top fifth.
- **Duration D:** bars until it falls below the median.
- **Magnitude M:** the largest move from the pre-onset close during the episode, in pre-onset σ.
- **Velocity:** V = M / D.

60,250 episodes, 24,178 of them held out.

| | Median D (bars) | Middle half | 90th pct | Median excess range |
|---|---|---|---|---|
| All | 19 | 10–38 | 69 | +0.05 |
| Out of compression | **15** | 9–31 | 53 | **+0.25** |
| Not out of compression | 20 | 11–40 | 79 | −0.02 |
| Crypto / metals / FX / stocks / Deriv | 45 / 29 / 28 / 20 / 13 | | | |

- **Out of compression, expansions are shorter but stronger.**
- **Size:** median magnitude 3.3σ (middle half 2.0–5.6σ). Duration and magnitude move together
  (rank correlation 0.75).
- **All three are predictable at the onset,** by rank correlation with the held-out outcome:

  | Target | Gradient boosting | Persistence baseline (last episode's duration) |
  |---|---|---|
  | Duration | 0.70 | 0.53 |
  | Duration, without the last episode | 0.51 | – |
  | Magnitude | 0.48 | – |
  | Velocity | 0.53 | – |

  The strongest single predictors are the onset bar's size (0.24 for D, 0.38 for M), its
  tick-volume surge (0.22), the depth of the compression before it (0.20), and the calendar
  (0.18). Deeper compression gives slower expansions (−0.24 with velocity).

- **Caveat:** some of this is mechanical. A larger onset bar takes longer to decay out of the
  percentile on any process. GARCH walks here (persistence 0.98) run longer than markets (median
  48 bars), so they are not yet a matched control. Before a duration forecast ships, it must beat
  walks fitted to each market's own persistence.

## Did it, or the shock forecaster, see the AUS 200 move? (2026-09-30 and 10-01)

The ASX 200 cash index (Yahoo 15m bars; the broker's Australia 200 CFD is not on the lab), replayed
bar by bar through the production shock forecaster:

- **Sep 30, +0.69% in one 15m bar at 11:30 Sydney:** not seen. The reading on the bar before was
  1.3x normal, against the card's 3x line. 11:30 is the ABS's release slot. Scheduled events are
  the job of the release-volatility profile ([`news-volatility.md`](news-volatility.md)).
- **Oct 1, a −0.6% gap and a −1.9% day:** raised but under the line all the previous afternoon
  (1.8–2.5x), then 3.1–4.4x after the open while the move continued.
- **The expansion alert would not have fired:** before both events the series was not compressed
  (range percentile 0.82 and 0.50).

The cash index has session hours only and no tick volume, so this is indicative. The CFD trades
overnight, where the Oct 1 move may have built more gradually.
