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
| [cascading.md](cascading.md) | **not run** - four falsifiable tests borrowed from turbulence, with the harness each needs: whether volatility cascades from coarse timeframes to fine and only that way, whether the synthetics are monofractal where real markets are not (which would undermine the pooled learner), whether tails thin with the interval, and a speculative flow/liquidity ratio |
| [starving.md](starving.md) | **measured** - 24 OOM kills in nine days, and the cause is the save, not a leak: holding a 206MB state costs 1.33GB resident and a save adds 0.58GB on top, every 300s, against a 2.61GB limit. Two earlier diagnoses on this page were wrong and are kept |
| [implied.md](implied.md) | **not run** - whether VIX and VVIX say anything our own volatility estimate does not, on the four equity indices that are 8% of the book; four tests, ordered so the cheapest kills it fastest |
| [reacting.md](reacting.md) | **measured, null** - no seconds-scale edge after a call: the excursion against a matched control sits between -0.015 and +0.003 volatility units at every horizon, while the median spread is 0.159v |
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
python research/harness/states.py     # does a level's behaviour change over its life
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
