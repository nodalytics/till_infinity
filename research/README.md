# Research

Experiments and their results. Each document is a question, what was run to
answer it, and what the answer turned out to be - including when the answer was
"do not build this", which it often is.

Design documents live in [docs/](../docs). This folder is for things that were
*measured*, with the harness that measured them, so a result can be re-run
rather than believed.

| | |
|---|---|
| [models.md](models.md) | **measured** - would trees, forests, cosine similarity or an MLP help; a 1KB logistic regression beats all of them, and five times the data did not change that |
| [features.md](features.md) | **measured** - `side` alone matches all nine features together, generated features make it worse, and the trivial "level holds" rule still beats our directional call everywhere but the top decile |
| [aligning.md](aligning.md) | **measured** - trading against a live higher timeframe costs 2.5 to 4.1 points of held rate at 3m and 5m, nothing at 1m, and reverses at 15m; the pooled figure says the opposite and is Simpson's paradox for the third time |
| [generated.md](generated.md) | **measured, two nulls** - the Deriv synthetics share no driver (325 pairs, the largest correlation is between two unrelated instruments), and FOCuS detections land on origins at *below* chance at every threshold from 1 to 20 nats |
| [twins.md](twins.md) | **measured, null, and one exact positive** - `Volatility 75` and `Volatility 75 (1s)` are not one path seen at two rates: over **916,248 comparisons** on 1.1M ticks and 59 days of bars, no twin correlation, tail coincidence, volatility clock or tick-index alignment stands outside what mismatched pairs of the same instruments produce. What does hold is the stated law - all twelve volatility indices are within **two standard errors** of their advertised annualised volatility and pass every iid-normal test applied, and a twin pair carries identical volatility *per second* with per-tick variance differing by exactly sqrt(2). Also: all sixteen synthetics publish on one clock to within 9ms, which fakes a correlation of +0.19 in |return| on a fixed grid, and `volatility_150_1s_index` is quoted too coarsely to carry any tick statistic |
| [generators.md](generators.md) | **measured** - the Deriv synthetics are exactly the generators the venue publishes: realised volatility equals the name on 12 of 12 indices within **0.49%**, Step Index is a fixed 0.1 step and a fair coin to **p=0.499734 +- 0.000220** over 5.2M flips, Boom/Crash spike at the stated tick rate with a memoryless arrival on all six, and Range Break 100 breaks **2.066x** as often as 200. There is no volatility clustering anywhere (largest |acf| 0.017 against 0.219 on the real feeds), so the published constant beats the rolling estimator on all 24 instrument-halves and the estimator's correlation with the next move sits in **[-0.015, +0.007]** against 0.366-0.493 on the real feeds. Nothing is directional. The one thing that costs money is that a stop on the spike side of Boom or Crash fills **10 to 19R** past where it was placed |
| [deriving.md](deriving.md) | **derived, and the theorem is the result** - the synthetics' parameters are published, so the barrier questions this desk answers with estimators have closed forms. A predictable position on a martingale has zero gross expectancy, so **`E[net] = -(c/2) x turnover`** for every stop, target, trail, grid, entry filter and sizing scheme - verified 23 ways on two paths, max |z| **1.84**, against a look-ahead control earning **+0.5002 per unit of turnover where every honest rule pays -0.5000**. The closed forms need the **0.5826** discrete-monitoring constant and then they are exact: a 1:3 barrier is a **30.7%** shot rather than 25% on 174,501 trades, expected durations land within **0.1-1.9%** where the textbook forms are **12-178%** out, and the same constant derives generators.md's unexplained **0.870 / 0.909** Parkinson ratio to **0.30%**. Boom/Crash's **+13.96R** stop slippage is now a formula reproducing all 24 measured cells to within 5.2%, and the grind side wins **98%** of ten-tick holds at an expectancy of exactly zero. Range Break turns out to have a real range - sub-diffusive by **3.6x** and **8.9x** between breaks - and the break pays for it exactly. The Jump **1.322** is **not** in the spread: `c/sigma` is **1.0103 +- 0.0151** against *realised* volatility on all five, so the venue already knows. And `volatility_250_1s_index` costs **289 seconds** of its own volatility to cross, against 1.0 for the Jump family |
| [cascading.md](cascading.md) | **measured, four tests, two positives** - volatility does cascade coarse-to-fine on all fourteen scale pairs and in both halves of a split, but the effect is +0.01 to +0.03 of correlation and it is a *real-market* property: synthetics score +0.004 against metals' +0.039. The monofractal discriminator is confounded by the marginal - an i.i.d. Student-t with no cascade scores higher than any real instrument - but 13 feeds survive the control and the 12 Volatility indices are **exactly Brownian**, H = 0.50 and kurtosis 3.00. Tails thin, and `MAD_TO_SIGMA` is the Gaussian ratio where FX runs **27% above it at 1m**. The flow/liquidity ratio is null three ways, the sharpest being that 24 of 53 feeds emit one quote a second by construction |
| [starving.md](starving.md) | **measured, and fixed in two halves** - 23 OOM kills in ten days. The *periodic* cause was the save, and streaming it took the transient from 0.394GB to **0.000GB** byte-identically; the plan was right about the fix and wrong about where it was, since 97.1% of a 206MB state is three pickle blobs and streaming the codec's tree was streaming 2.9% of it. The *structural* cause was that the state held **349 feeds for a 53-instrument book**, because `PRICES_CCXT_TOP` bounds what is discovered at one moment and the top-25 by volume rotates. Three earlier diagnoses on this page were wrong and are kept |
| [compounding.md](compounding.md) | **measured, and the answer is a number of trades** - what turning an edge of size X into a large account costs, simulated by resampling the live R distribution rather than assuming one. The book is **-0.1354R over 398 closes, CI [-0.208, -0.060]**, so the growth-optimal fraction is **exactly zero** and the shipping 0.25% ends at 0.711x over 1,000 trades. Given an edge, the safe fraction is **an eighth to a quarter of Kelly**, not a half - quarter Kelly still halves the account before the target one time in five - and a tail-shaped edge sizes at **42%** of a broad one of the same mean while doubling ruin at the same fraction. A broad **+0.05R** compounds 100x in 1.2 years at f=0.0129, which makes the goal arithmetic rather than hope; the binding constraint is that confirming +0.05R takes **1,600 trades** against 398 on the whole record |
| [edge.md](edge.md) | **measured, and it is the question everything waits on** - all 688 closes on record including the 290 the journal was losing, keyed by strategy. `sweep-aware` is **+0.154R, 95% CI [-0.022, +0.346]**: right sign, positive in both halves, survives losing its best trade, and **not yet distinguishable from zero**. `confluence-scalp` is confidently negative and was switched off. 33 more closes settle it |
| [winning.md](winning.md) | **measured, null with one pre-registered survivor** - 43 entry features against a 300-permutation control, and the largest gap on R is *below the median gap the same scan finds in noise*. What survives is `spread / risk`, named in advance by `exiting.md`: **49 trades passed the live gate while expensive against risk, at -0.471R and 53% stopped, for -502.70**, because the gate scales the permitted spread with the *target*. Also catches a fifth Simpson reversal, in which the missing half made a composition look *more* significant |
| [implied.md](implied.md) | **measured, and the first thing here to beat persistence** - VIX does not add to our own volatility estimate, it *replaces* it (`both` is no better than `vix` alone), beating the naive baseline by +0.26 to +0.43 over 15 years walk-forward. The term structure adds 1-2 points; VVIX adds nothing and does not lead. Scope is the equity indices at a day and up |
| [gamma.md](gamma.md) | **measured** - option expiry suppresses index volatility on all four equity indices (0.865, 0.921, 0.909, 0.768 of base) while the placebo second Friday sits flat at 1.004/0.958/1.004/0.981; quarterly triple witching pins harder on all four and the two that pin hardest rebound after. Three of four survive a 2018 split, ^DJI does not. The positioning half - open interest, dealer gamma sign - cannot be tested from free data at all and needs a collector running forward |
| [instruments.md](instruments.md) | **measured** - what each instrument earns; net -746 over 392 closes, the book's best-looking instrument is **one +622.63 trade with no R recorded**, only three instruments with 20+ closes are positive, and Boom 1000 at -0.595R against Crash 1000 at +0.053R is the one asymmetry worth chasing |
| [giveback.md](giveback.md) | **measured twice** - first when `best_r` was a constant zero and the investigation was about why, now that it works: sweep-aware keeps **27%** of its high-water mark and confluence-scalp gave back **1.758R a trade**. The cause is arithmetic - an uncapped wick-widening rule puts the trail 1.33R behind a peak whose median is 0.445R, so on nine trades in ten neither the trail nor the break-even can engage at all |
| [convexity.md](convexity.md) | **measured, and the thesis does not survive** - is this book's money in the tail. In **dollars** yes, 57.3% of gross profit in the top 5% of closes and 30.2% of it in one trade; in **R** no - 35.7%, which is *inside* what a normal distribution with the same moments gives, and the largest R on 325 closes is +2.429. Re-priced at one flat size the top 5% carry 34.9%: the tail is the position sizer. A deliberately convex exit (half stop, no target, 3R trail, a day to run) loses in discovery and wins in verify, and its whole magnitude is the **stop denominator** - divide the stop by three and the mean moves by three, in whichever direction that window already pointed; at a constant stop the shape is worth +0.009R. The tail cannot be selected for (largest of 25 features clears its control by 0.001 and flips sign in verify). And the Boom/Crash spike asymmetry is **manufactured by the stop**: 0.04R with no stop, 0.32R with one, 0.94R with a half-width one, scaling monotonically with the size of the jump the replay is filling through |
| [exiting.md](exiting.md) | **measured, and two look-aheads of my own** - replaying sweep-aware's entries under 18 exit policies; the first version reported a policy at +1.335R against +0.344R, better on 63.5% of the same trades, holding in both halves of a split sample, and it was a look-ahead. Corrected, **none of the eighteen beats what ships by more than noise**, and the replay disagrees with the live exit mix badly enough (98% stop against 81% timeout) to be evidence about the harness. `vol_bps` as a regime turns out to be the spread and nothing else |
| [winning.md](winning.md) | **measured, null** - what separates a winning trade from a losing one on 685 live closes. Against a permutation control run over the whole scan, **nothing the desk knows at order time clears the noise floor on R**: the largest gap across 43 features is 0.433 where shuffled outcomes produce a median of 0.374, and 24 of 43 features survive a split sample where noise survives 22. The one survivor was pre-registered by `exiting.md` - spread as a share of the trade's own **risk**, worth +0.369R cheap-minus-expensive, p<0.001 permuted within feed, 9 of 9 strata - and the gate that ships measures it against the **reward** instead, so 49 trades passed it and lost 0.471R each. Holding time looked like the strongest separator, got *more* significant when the missing half was added, and is entirely the stop rate: remove stops and it reverses at p=0.63 |
| [lagging.md](lagging.md) | **measured, null, and the control is the finding** - is Deriv's crypto quote late enough behind Binance/Bybit/the exchanges to trade. It is late, by +1.3bps of mid on btc against a placebo flat at 0.05 - and so is every exchange: put each venue in the broker's chair against a consensus excluding it and Deriv is **third of six** on btc, beaten by Bitstamp on two feeds of three. What is Deriv-specific is the spread, 2.39bps against Binance's 0.001, so the same catch-up that pays five venues costs Deriv -1.22bps a round trip. The market-made subset does pay at zero delay (+1.54bps) and is negative by **half a second**. Also: every quote timestamp is our own receive clock, 44% of Binance's rows land in one decile of the second, and `prices.db` is not corrupt - only its `quotes_feed_ts` index is |
| [reacting.md](reacting.md) | **measured, null** - no seconds-scale edge after a call: the excursion against a matched control sits between -0.015 and +0.003 volatility units at every horizon, while the median spread is 0.159v |
| [crossing.md](crossing.md) | **measured, three nulls and one candidate** - the cross-venue and cross-rate hunt for a *structural* edge. `dev_bps` reverts **less** than a permutation of itself in 20 of 22 cells, by less than the deviating venue's own spread, and 90.2% of deviations belong to a venue the desk cannot hold. Seven of eight FX triangles are tight to 0.08bps against a 0.85-1.54bps three-leg cost, and their sixty-day "one-signed offsets" are predicted to within 0.045bps by bid-versus-mid arithmetic. No instrument leads another: the second-largest off-zero correlation in 336 is **us30 against btc**, beating six of eight related pairs, and the largest implied move anywhere is 0.089bps against a 2.35bps spread. The twelve Volatility indices realise their own names to within 0.5% in both halves. What survives is **CADJPY**, whose price disagrees with the broker's own USDJPY/USDCAD by +0.41bps and by +1.23bps every Thursday - the T+2 value-date roll, nine Thursdays of nine - a locked three-leg trade worth +0.69bps a week that lives or dies on three swap rates nobody has read. Also: `lp_time` is collected and discarded, so no cross-venue lead-lag is measurable from what is stored |
| [forecasting.md](forecasting.md) | **under revision** - the comparisons were made while two volatility conventions were mixed asymmetrically, so the two headline claims are probably artefacts; what survives is that persistence's edge shrinks monotonically with horizon, and a catalogue of three clean tables that were all defects |
| [volatility.md](volatility.md) | **measured** - the estimate is well calibrated and its half-life is well past the optimum; a flat 20-bar mean beats it at every interval |
| [resolution.md](resolution.md) | **measured on production** - two thirds of outcomes resolved within two seconds; a bar's wick was resolving touches born inside it, and no bars-only replay could see it |
| [states.md](states.md) | **measured** - does a level's behaviour change over its life; it does not, recency predicts worse than pooling, and there is no flip |
| [structure.md](structure.md) | **measured** - the transit graph, confluence and the shape of the level set; the graph is flat and the one strong-looking property is `side` wearing a distance |
| [magnitude.md](magnitude.md) | **measured** - does it know how far, and what being wrong costs; `expected_push` ranks profit 7.5x and the `reward_to_risk` gate inverts the sign of the return |
| [prior.md](prior.md) | **measured** - what `edge` is actually measuring; subtract a side-aware baseline and the level's record plus its neighbours predict at 51.8%, AUC 0.520 |
| [turns.md](turns.md) | **measured** - can a major turn be seen coming; yes, weakly. AUC 0.595 purged over 310 turns, and `vol` alone carries it |
| [cycles.md](cycles.md) | **measured** - does a level's place in the larger move matter; one cell separates by nothing at all, and the AUC gain's interval includes zero |
| [news-models.md](news-models.md) | survey - model families that could turn stored headlines into features, and which of them fit in 640MB beside everything else |
| [reading.md](reading.md) | notes - AlphaGo Zero, Llama 3, InstructGPT and DeepSeek-R1, what transfers and what does not; all four guard against the reward hacking this system did to itself. Plus the microstructure papers behind levels, VWAP, open interest and funding - including Osler's finding that **round numbers predict as well as published levels**, which is the control this desk has not run |
| [localising.md](localising.md) | **measured** - the origin survives its own falsification test, the fine-resolution estimator halves its wander, the body-edge rule adds nothing, and a band re-derived at 1m is 2.6x narrower for 94.8% of the same returns: shifting the 15m bar grid by a minute moves it a median 0.23v, 2.8x steadier than a matched random book and about a seventh of the band it already carries. Includes the corrected harness bug and three discrepancies between the origin-localization specification and the code |
| [locking.md](locking.md) | **measured** - the "resolves in two seconds" figure described a bug that was fixed; only 3.8% do now and the median is 191s. The give-back is real but it is the trap, not the clock: a trap keeps 34% of what it reaches, a break keeps all of it. And the scale-out never fires because the trigger reads the current price while the record keeps the high-water mark |
| [choosing.md](choosing.md) | **measured** - 536 counterfactual returns say the three strategies with real samples are indistinguishable at -0.17 to -0.19R and every strategy is negative at -0.216R pooled, so a selector would choose between options not shown to differ |
| [detecting.md](detecting.md) | **measured** - KSWIN, DDM/EDDM and a hand-written FOCuS added beside ADWIN, all deciding nothing; against their own nulls EDDM alarms up to 11 times per 3,000 on a model that has not changed and FOCuS at most 5 across five such streams |
| [spiking.md](spiking.md) | **measured** - the Boom spike is visible in stored 1m bars, one every 11.9 minutes, and its waiting time has a coefficient of variation of 0.99 against a memoryless process's 1.00. Nothing can call it; what survives is arithmetic on a nearly deterministic grind |
| [trapping.md](trapping.md) | **measured** - traps are 64% of all attempts on a level and 94.6% on 30m; predicting trap from break within a timeframe is AUC 0.567 on the level's own record, and the pooled 0.6187 was the timeframe rather than skill |
| [rounding.md](rounding.md) | **inconclusive, and the reason is the finding** - Osler's round-number control over 16 instruments; drawn, round and random books all hold price within one standard error, but the positive control fails too, so a 5m audit cannot resolve a book whose outcomes resolve in seconds |
| [swinging.md](swinging.md) | **measured** - `swing-level` replayed over 17 instruments and 1.1M bars; the candle gate pays, the 1.5 stop was what lost, and every cell with a 1.0 stop is profitable |
| [bandits.md](bandits.md) | design note - where a bandit fits (attention budgets, not the alert gate) and why gymnasium is not the reason to reach for one |
| [positioning.md](positioning.md) | what supply and demand this system has - six ideas inferred from price, the macro block that is all supply and no demand, and the CFTC positioning that is the one *observed* measure reachable from here |
| [catalogue.md](catalogue.md) | **measured** - which of the broker's 798 symbols are worth carrying; in volatility units the synthetics cost 0.170v to cross against FX's 2.267v, which is the opposite of what the point spreads say |
| [stops.md](stops.md) | **measured on production** - stops are the whole loss; 20 of 27 judgeable stopped trades never reached target and 7 were stopped early, so the answer is a better entry rather than a wider stop |
| [strength.md](strength.md) | **measured, not built** - how strong is a level and does it matter; the strongest single thing a level knows |
| [similarity.md](similarity.md) | **measured** - does `Features.distance` order neighbours; at tradable horizons AUC 0.4921 and 0.5120 against a 0.500 control, and the fast buckets that look decisive are a tautology - `side` fixes direction 100.0% under a minute and 52.8% beyond thirty |
| [handoff.md](handoff.md) | **start here** - what is true, what is broken, what cost time, and the tautology that reframes every model score in this repository |
| [force.md](force.md) | **measured** - does the force arriving at a level decide whether it breaks; it does, AUC 0.560, and depth into the zone separates harder still at 0.599 inverted, while `up_rate` - the best direction feature there is - predicts breaks not at all |
| [paying.md](paying.md) | **measured** - does the five-to-thirty-minute edge pay the spread; the synthetic null scores 47% where real instruments score 70%, and 11 of 26 clear their own cost with gold and spx500 an order of magnitude ahead |
| [barriers.md](barriers.md) | **measured** - the two-level trade as a triple-barrier problem; on 40,803 replayed setups no interval reaches the far barrier more often than the stop, and the +0.66v that survives comes from a 3.5:1 corridor rather than from a hit rate |
| [timeframes.md](timeframes.md) | **measured** - do higher-timeframe levels hold better; a 1m level breaks sixteen times more often than a 1h one, monotonically - but breaking less is not being more tradable, and 1h arrives twenty-seven times slower |
| [horizon.md](horizon.md) | **measured on production** - the level model's edge is +45% on touches resolving inside five minutes and **+0.00%** beyond thirty, which is the horizon `max_hold` trades; and 27% of resolutions carry a negative duration |
| [learning.md](learning.md) | **measured** - is the kNN behind every level call buying anything; at a matched 1,996 touches it beats a one-feature floor by 3.1 points of edge, a learned distance adds nothing over it, and a logistic regression on nine features matches reading one |
| [formations.md](formations.md) | seven ways to find a level and why they run together; 57% of levels now have more than one method behind them, where every one used to be `pip` alone |
| [shelves.md](shelves.md) | **measured** - do high-activity bands get respected; pooled over 849 windows a node is reached 45.8% against a control's 46.3%, and the synthetic null reads -11.6% |
| [origins.md](origins.md) | **measured** - do origins hold when price comes back to them |
| [reachable.md](reachable.md) | **measured** - how often all of `origin-swing`'s conditions hold at once |
| [geometry.md](geometry.md) | **measured** - where reward-to-risk actually comes from, and why a floor on it keeps losers and refuses winners |
| [lateness.md](lateness.md) | **measured** - what entering late costs |
| [macro.md](macro.md) | design note - monetary policy as features on a signal and as a model of its own, and why a rate differential needs both legs from one series family |

Designs nobody has built and measurements nobody has taken live in
[planned/](planned/) - the one thing that must not sit beside documentation of
things that exist, because that is where a reader cannot tell the difference.

Findings that changed the code, or that belong next to it, are written up in
`docs/` instead - [edge.md](../docs/edge.md), [strength.md](strength.md),
[absorption.md](../docs/absorption.md), [magnet.md](../docs/magnet.md),
[news-dedup.md](../docs/news-dedup.md).

## Running the harness

From the repository root, with the stored prices database in place:

```bash
python research/harness/touches.py    # replay once, cache resolved touches
python research/harness/models.py     # model and similarity comparison
python research/harness/edge_gate.py  # the |edge| gate, thresholds and quantiles
python research/harness/similarity.py # does feature distance predict agreement
python research/harness/features.py   # feature importance, and generated features
python research/harness/holds.py      # the edge against "assume the level holds"
python research/harness/vol.py        # does the volatility estimate predict the next move
python research/harness/cycles.py     # does cyclical context change what a touch means
python research/harness/turns.py      # can a major turn be seen before it happens
python research/harness/prior.py      # what edge measures, and whether the kNN earns its place
python research/harness/magnitude.py  # expected_push, risk_vol and the reward-to-risk gate
python research/harness/topology.py   # the transit graph over levels
python research/harness/structure.py  # confluence, the level set's shape, and volatility
python research/harness/crossing.py   # cross-venue deviation, FX triangles, cross-instrument lead-lag
python research/harness/states.py     # does a level's behaviour change over its life
```

The generator study runs on the lab rather than here - it reads `research.db`,
which is 60 days of bars and 24 hours of ticks across 53 feeds:

```bash
./.secrets/lab.sh run research/harness/genvol.py    # realised vs nominal volatility, clustering
./.secrets/lab.sh run research/harness/genstep.py   # Step Index: fixed step, fair coin, barriers
./.secrets/lab.sh run research/harness/genspike.py  # Boom/Crash: spike rate, grind, the arithmetic
./.secrets/lab.sh run research/harness/genrange.py  # Range Break: break rate, fade, follow-through
./.secrets/lab.sh run research/harness/genstop.py   # what a stop is worth when the adverse tick jumps
```

`touches.py` writes `touches.pkl` beside itself and the others read it, so the
replay runs once rather than four times.

## Which data these were measured on

Everything dated **2026-08-16** was re-run on 10,484 touches across fourteen
instruments, after the backfill in [todo.md](../docs/todo.md) §0d took the
store from 455k bars to 1.56M. The earlier readings used 1,995 touches across
six instruments over days rather than months, and are in git.

Two of the six documents changed their answer. [turns.md](turns.md) went from
"does not separate from chance" to AUC 0.595; [cycles.md](cycles.md) went from
"nothing separates anywhere" to one marginal cell. The other four reproduced,
with absolute accuracies about five points lower on the harder sample and the
rankings intact.

**Re-run the harness after any backfill.** Every document here reads
`touches.pkl`, which regenerates from whatever is in the store, so a collection
run silently invalidates all of them.

## What every result here shares, and its limits

**Walk-forward.** Nothing is predicted from its own outcome or from anything
that resolved after it.

**Bars only.** Production drives touches from quotes as well, and on
2026-08-14 that difference twice overturned a replay result: the
instant-resolution fix looked complete on a replay and was still 42.9% wrong
live. Treat every number here as the level machinery rather than the system.

**One replay, six instruments, ~2,000 touches.** Enough to rank things, not
enough to pin a constant. Where a number is quoted as transportable, the
document says so and shows the split that establishes it.

**Measured after 2026-08-14.** Everything before that date was counted on data
where roughly half of all outcomes were artefacts - touches resolving at the
instant they opened - so earlier measurements in this project are not
comparable, and several were withdrawn.
