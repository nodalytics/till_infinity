# Ideas to backtest: trading and risk management

A backlog, set 2026-10-01. It gathers ideas from two sources:

- **past studies:** untested proposals, near-misses, and open variants of nulls. The numbers are
  quoted from the docs linked;
- **the seven agendas** in [`agenda.md`](agenda.md), turned into things that trade or manage risk.

Nothing here has been backtested as written. **Every idea is a registered trial when it is run.**
Pre-register its bar and run it walk-forward with both halves. Beat random selection of its own
signals and walks we generate ourselves; Deriv is a market, not a control. Charge costs, and deflate
across the program ([`lopez-de-prado.md`](lopez-de-prado.md)).

**Where the odds are:** the desk forecasts **risk**, not direction ([`findings.md`](findings.md)).
So the risk-management ideas (Part A) and the trades that need no direction (Part B) come first.
Directional near-misses (Part C) are listed so they are not lost, not because they are likely.

**Venue key:** **MT5** = broker FX, metals and indices; **Deriv** = Deriv's own markets;
**FT** = crypto perpetuals with exchange data, backtested in [`../freqtrade/`](../freqtrade/README.md).
MT5 and Deriv ideas are backtested with [`../mt5bt/`](../mt5bt/README.md): bid/ask fills, ticks, swap and the broker's lot grid.

**Where the data comes from:**

| Need | Source |
|---|---|
| **Bid/ask, ticks, spreads, bars** for anything the broker lists (FX, metals, indices, stocks, the Deriv markets) | **MT5**, through the broker bridge: `copy_ticks_range` for every bid/ask tick, `copy_rates_range` for bars, and market depth where the symbol has a book. History goes as deep as the broker's server keeps it. [`../harness/mt5fill.py`](../harness/mt5fill.py) already pulls ticks into a research database |
| Funding, open interest, long/short ratios, taker flow, mark/index basis, liquidation tiers | Crypto exchanges: Bybit via `bytick.com`, the Binance archive (see [`../freqtrade/README.md`](../freqtrade/README.md)) |
| Options | Deribit (BTC, ETH) |

So tick-level research (A2.13 wick stops on real ticks, A3.4 spread percentiles, C1 Sunday-open
fills, C4 first-minute releases, D7 latency) starts from MT5 ticks, not bars.

## Part A: risk management

### A1. Sizing and exposure from what we already forecast

| # | Idea | Source | Status and what to test | Venue |
|---|---|---|---|---|
| A1.1 | Shock probability in sizing: shrink, widen or skip on P(shock) | [`anomalies.md`](anomalies.md), [`shockvolume.md`](shockvolume.md), [`session-switch.md`](session-switch.md) | On the cards, not in sizing. A plain on/off switch tested null (0 of 18 stopped cells). Test **continuous** sizing, size ∝ 1/E[\|move\|], against a uniform cut | MT5, FT |
| A1.2 | A uniform cut in risk per trade instead of state switches | [`session-switch.md`](session-switch.md), [`power-and-sizing.md`](power-and-sizing.md) | Measured: beats every switch in all real cells but one. **Not applied.** A configuration decision, not a backtest | All |
| A1.3 | Size by the envelope's width (P10-P90), not the live volatility unit | [`gbm-envelope.md`](gbm-envelope.md), [`conformal.md`](conformal.md) | Untested. The boosted band corrects a noisy volatility unit, so size from the band | MT5 |
| A1.4 | Hour-of-week volatility multiplier in sizing | [`calendar-returns.md`](calendar-returns.md) | Vol clock built (next-hour error 0.937/0.948). Its use in **sizing** is untested | MT5, FT |
| A1.5 | Release-volatility profile in sizing: 0.789x before, 2.424x on the print's bar, 1.762x at +30m | [`news-volatility.md`](news-volatility.md) | Published, decides nothing. A sizing A/B is untested | MT5 |
| A1.6 | chi "volatility will fall" as an up-size input | [`susceptibility.md`](susceptibility.md) | +5.3-9.1 pts within volatility deciles on real markets. Untested as sizing | MT5 |
| A1.7 | Impulse consistency, entropy, manifold region as magnitude inputs | [`impulse-consistency.md`](impulse-consistency.md), [`state-and-memory.md`](state-and-memory.md), [`manifold.md`](manifold.md) | Move 1.17x (30 of 37 instruments), entropy +0.222, region +0.150. No sizing rule built | MT5 |
| A1.8 | `by_regime` scaler (forecast-ratio inverted U: hold 86.4% mid, 81.3/81.4% tails) | [`trading-scaling.md`](trading-scaling.md), [`clustering.md`](clustering.md) | Built with `regime_band = 0.0`. Block bootstrap owed | MT5 |
| A1.9 | `by_volatility` portfolio cap (target about 3.0 bps) | `docs/todo.md` 7j | Built, off, "needs a decision" | All |
| A1.10 | VIX-scaled member vs HAR; VXN/VXD/RVX for the other indices | [`implied.md`](implied.md) | Ships off; the comparison is untested | MT5 |
| A1.11 | Opex-day size input (expiry day 0.768-0.921 of base volatility) | [`gamma.md`](gamma.md) | Not joined to P&L | MT5 |
| A1.12 | Concurrency check: 34 positions × 0.5% = 17% on correlated dollar legs | [`power-and-sizing.md`](power-and-sizing.md) | Never checked. Measure the worst simultaneous exposure by currency leg | MT5 |
| A1.13 | Kelly table: safe f = 1/8-1/4 Kelly, and freeze config for 1,600 closes | [`compounding.md`](compounding.md) | Contingent on an edge. Today f = 0 (−0.1354R) | All |
| A1.14 | Touch probabilities for size: shrink when both bands are likely to be touched | [`bandrace.md`](bandrace.md), [`gbm-envelope.md`](gbm-envelope.md) | Untested. Skill shrank to +0.011/+0.017 over the boosted bands | MT5 |

### A2. Stops and exits

| # | Idea | Source | Status and what to test | Venue |
|---|---|---|---|---|
| A2.1 | Spike-side sizing on Boom/Crash/DEX: stops fill 10-19R past the level | [`stop-width.md`](stop-width.md), [`generators.md`](generators.md), [`deriving.md`](deriving.md) | Untested in production. Size by the slippage multiple, or refuse the spike side | Deriv |
| A2.2 | Boom/Crash as a group: 20% of trades, 42% of the loss | `docs/todo.md` | Untested. Size down or refuse | Deriv |
| A2.3 | Partial bank: 50% at 1R | [`locking.md`](locking.md), [`losing.md`](losing.md), [`breakeven.md`](breakeven.md) | Near-miss: +0.047R (z ≈ 3.8, replay). Inert live, because 0.31 lots cannot split above the 0.2-lot minimum (needs ≥ 0.4) | MT5 |
| A2.4 | Break-even trigger nearer the 0.445R median peak | [`breakeven.md`](breakeven.md), [`giveback.md`](giveback.md) | Null so far (the interval spans zero). The prize: 66 trades reached ≥1R and ended ≤0, −51.3R of −84.9R. Re-run as `best_after` and `worst_after` accrue | MT5 |
| A2.5 | Cap the trail's wick widening (`room` reaches 2,239v; a 2v trail engages only at 1.33R) | [`giveback.md`](giveback.md) | Untested | MT5 |
| A2.6 | A stop set from winners' MAE (winners' p90 adverse excursion is 0.333R) | [`excursion.md`](excursion.md) | Untested. Shadow both. [`convexity.md`](convexity.md) warns a tighter stop magnifies the existing sign | MT5 |
| A2.7 | Ride's trail (0.5v) on sweep-aware entries | [`exiting.md`](exiting.md) | Near-miss: +0.046R after the look-ahead fix. The live side-by-side was never read | MT5 |
| A2.8 | Break clock: P(break \| still open at t) crosses even money at 4-7 bars | [`break-trade.md`](break-trade.md) | Untested. Shadow a time-based exit | MT5 |
| A2.9 | Regime change tightens the trail rather than exiting | [`hold-clock.md`](hold-clock.md) | Untested. Exiting on a regime change itself was null | MT5 |
| A2.10 | Hold in bars of the entry interval, stop scaled by √(hold bars) | [`paying.md`](paying.md) | Not cleanly tested | MT5 |
| A2.11 | Stop beyond the band that is unlikely to be touched (the boosted P10/P90 at a 20% touch rate) | [`gbm-envelope.md`](gbm-envelope.md) | Untested as stop placement | MT5 |
| A2.12 | Flatten before high-importance releases: held trades did worse in 32 of 36 rows (median 0.19R) | [`directional-questions.md`](directional-questions.md), [`vetoes.md`](vetoes.md) | Untested as an exit. The entry blackout does nothing | MT5 |
| A2.13 | Backtest stops on wicks (wicks take stops 1.4x as often as closes) | [`crash-timing.md`](crash-timing.md) | A research rule. Port the old close-based harnesses | All |

### A3. When to stand aside

| # | Idea | Source | Status and what to test | Venue |
|---|---|---|---|---|
| A3.1 | Time-to-weekend flag for FX (flattening cut weekend sd from 2.51 to 2.07) | [`stop-width.md`](stop-width.md), [`fridayflag.md`](fridayflag.md) | Untested as a rule. Gap AUC 0.601 | MT5 |
| A3.2 | Gap-risk card line (top-quartile weekend gap) | [`fridayflag.md`](fridayflag.md) | Proposed, not built | MT5 |
| A3.3 | Flat at rollover to save swap (saves 0.013 TR, keeps 96%) | [`stop-free.md`](stop-free.md), [`carrying-cost.md`](carrying-cost.md) | Untested live | MT5 |
| A3.4 | Spread-percentile gate by symbol and hour; slippage in minimum RR | `docs/todo.md` 6k/6f, [`vetoes.md`](vetoes.md) | Untested. Revisit at 500+ closes | All |
| A3.5 | Spread as a share of **risk**, not reward (49 trades passed the shipped gate and lost 0.471R each) | [`winning.md`](winning.md), [`auditing.md`](auditing.md) | Open | All |
| A3.6 | Stop-side gate: refuse a stop on the wrong side of entry | [`verification.md`](verification.md) | One line, undecided | All |
| A3.7 | Funding-stamp avoidance: no new perp entries just before a stamp at an extreme rate | `till_infinity/prices/funding.py` | Untested | FT |

### A4. New risk ideas from the agendas

| # | Idea | Agenda | What to test | Venue |
|---|---|---|---|---|
| A4.1 | **Damage integral sizing.** D_t = Σ decayed stress (realised range, volume z, shock score) in place of instantaneous volatility | 4 (failure mechanics), 5 (avalanche) | Does D_t add to the shock forecaster's held-out AUC, on markets but not GARCH walks? Test question 2 first: does stress build while volatility falls? Note [`susceptibility.md`](susceptibility.md)'s fatigue proxy had the wrong sign | MT5, FT |
| A4.2 | **Metastability flag.** Same volatility, different fragility: the response to small shocks (impulse response of range to a 1-sd bar) | 5 item 7 | Do states with a large response to small shocks have more 4x shocks next, at equal volatility? | MT5, FT |
| A4.3 | **Sensor disagreement de-risk.** When the vol clock, the envelope, the shock score and (crypto) funding or OI disagree, cut size | 5 item 3, 7 item 3 (sheaves) | Is the disagreement predictive beyond each sensor alone? Score an "obstruction" as the residual of a joint model | MT5, FT |
| A4.4 | **Regime-age hazard.** Tighten stops or cut size as a volatility regime ages, if the transition hazard rises with age | 4 item 18 | Fit P(transition \| age) on the vol-state sequence; compare with a memoryless (exponential) null | MT5, FT |
| A4.5 | **Strategy mortality and retirement.** A live hazard and CUSUM on each strategy's R; retire one when its marginal utility minus cost reaches zero | 4 item 8, 6 item 16, 7 item 1 | Backtest the retirement rule on the journal: would it have cut the losers sooner than [`triage.md`](triage.md) did, without cutting at random? | All |
| A4.6 | **Statistical process control on the feed.** A control chart on each feed's own statistics (spread, tick rate, return distribution); when the process shifts, stand aside until the models re-learn | 4 item 12 | How often do production models mis-quote just after a detected shift? [`rollover.md`](rollover.md) was one such shift | All |
| A4.7 | **Graceful degradation.** A fallback quote (the law or history envelope) when the boosted model's live calibration drifts; isolate a misbehaving feed | 4 item 9 | Replay: does the fallback cut tail error during the boosted model's worst weeks? | MT5 |
| A4.8 | **Diversity-aware exposure.** Count *behaviourally* distinct positions (by equivalence of their P&L paths), not instruments | 6 items 12 and 21 | Do correlated legs make the worst day worse than the per-trade bound suggests? Extends A1.12 | All |
| A4.9 | **Bitemporal guard.** Every backtest input carries (event time, knowledge time); refuse joins that use a value before it was known | 6 item 13 | A harness check, not a trial. Protects every external-data FT idea | All |
| A4.10 | **Type checks for research.** Tag volatility units, intervals and price conventions as types | 5 item 13 | Would have caught the 1,000x crypto spread and the lost size brake. Engineering, not a trial | All |
| A4.12 | **Shock half-life sizing.** After a shock, scale size back up on its fitted, state-dependent decay C_0 e^(−kt), not on a fixed cooldown | 8 item 7 | Does k differ by state (held out), and does a k-based ramp beat a fixed cooldown and a uniform cut? | MT5, FT |
| A4.13 | **Interlocking.** Refuse a new position that is valid alone but shares a liquidity source, execution window, collateral or risk budget with open ones | 8 items 13-14 | Replay the journal: how often did simultaneous positions collide, and what did the collisions cost? | All |
| A4.14 | **Flight envelope per strategy.** Map the state region (volatility, spread, shock score, hour) each strategy survives, and stand it aside outside it | 8 item 20 | Fit on the first half and apply to the second; beats standing aside at random for the same share of time? | All |
| A4.15 | **Evidence count.** Size by the *independent* evidence behind a signal (the gates' redundancy measured by their joint information), not the number of gates agreeing | 8 item 1 | Do signals with more independent agreement do better than ones with redundant agreement? | All |
| A4.16 | **Dead-reckoning staleness.** Widen the envelope and cut size as time since a fresh observation grows (gaps, stale feeds, the weekend) | 8 item 12 | Is coverage worse after gaps, and does a staleness widening fix it without loosening normal bars? | MT5, FT |
| A4.11 | **Liquidation-zone exposure.** Cut size when open interest is high and price nears a cluster of estimated liquidation prices (leverage tiers × OI by entry) | 5 items 6 and 8, 7 item 7 | Do 4x moves come more often from such states, beyond the shock score? | FT |

## Part B: trades that need no direction

| # | Idea | Source | Status and what to test | Venue |
|---|---|---|---|---|
| B1 | **Expansion-from-compression straddle.** Arm a two-sided breakout only when the compression alert fires | [`expansion.md`](expansion.md) | **Tested 2026-10-01, no as specified:** −0.053R straddle, −0.036R OCO (CIs touch zero) against −0.10/−0.07 unarmed. The gain is spread, not move: gross −0.024 vs −0.030. Halves disagree. Next: Part G's trailing-stop version | MT5, FT |
| B2 | **Shock-armed straddle.** The same, armed by the frozen shock model (AUC 0.73-0.76) | [`shockvolume.md`](shockvolume.md) | Untested. Costs two spreads, so start on the cheapest instruments | MT5, FT |
| B3 | **Volatility selling when the forecast says calm**, where a product allows it | [`implied.md`](implied.md), [`ecology.md`](ecology.md) | The S&P short-straddle proxy has gross Sharpe +5.6 with no costs, but the desk has no options. On crypto: Deribit options are reachable (BTC, ETH) | Deribit |
| B4 | **Deriv Accumulator on a real instrument** (break-even is a 2.51% fall in per-tick volatility) | [`accumulators.md`](accumulators.md) | Null on synthetics (0 of 25 cells). Re-open if ACCU lists a real instrument, or the barrier widens past 2.18σ at g = 0.03 | Deriv |
| B5 | **Funding carry, delta-neutral.** Long spot, short perp (or the reverse) when funding is extreme | `till_infinity/prices/funding.py`, [`crowding.md`](crowding.md) | Untested. Freqtrade cannot hold a pair, so this needs our own two-leg harness with spot and perp fees | FT (own harness) |
| B6 | **Range trading inside the boosted band.** Fade only touches of the P10/P90 the model says are unlikely to be touched again | [`gbm-envelope.md`](gbm-envelope.md), [`bandrace.md`](bandrace.md) | Untested. Note the band race found which band comes first **not** forecastable | MT5 |

## Part C: directional near-misses and open variants

Listed so they are not lost. Each needs fresh data or a cheaper venue, not a re-run.

| # | Idea | Source | Best number so far | What would settle it |
|---|---|---|---|---|
| C1 | Friday's last 4h faded into the Sunday open | [`gaptrade.md`](gaptrade.md) | +2.11/+2.33 bps gross in all 14 pairs; 1h-exit net +1.31 [−0.17, +2.73] bps before swap and commission | A venue with a tight Sunday-open spread; tick fills |
| C2 | Crypto crowding fade (funding, OI, long/short extremes, held a day) | [`crowding.md`](crowding.md) | +17.4 bp, but +41.5/−6.9 by half | **FT:** Bybit funding since 2024 now covers both halves |
| C3 | Coinbase premium leads price | [`coinbase-premium.md`](coinbase-premium.md) | +1.12 bp at 5m vs a 2.26 bp round trip | A cheaper venue, or a maker entry |
| C4 | Release surprise in the first 3 minutes | [`surprise.md`](surprise.md) | rho +0.231 in 3 min, dead after | Sub-minute latency |
| C5 | Drift Switch AR(1) (acf1 +0.1525, t +34) | [`families.md`](families.md) | 56.9% hit clears 0.103-0.692 of the spread | A longer hold where the cost advantage lives (4h+) |
| C6 | Stretch exhaustion on 4h/8h | [`stretch.md`](stretch.md) | Top cell +0.94 pts against a 2.5-pt hurdle | Hold-out instruments and a bootstrapped decile rank statistic |
| C7 | Stocks RSI(2) long | [`stocks.md`](stocks.md) | +2.38 (halves +2.18/+2.54), DSR 0.31-0.47 | Paper trade; more than one regime |
| C8 | Five shadowed confirmation gates (only crypto TRIX survives deflation) | [`confirm.md`](confirm.md) | +0.041 to +0.174R | Judge at about 200 signals; the Deriv pivot gate is first |
| C9 | LLM risk-first skip as a filter | [`agent-trading.md`](agent-trading.md) | +0.035R over random (t 0.8) | Shadow it |
| C10 | sweep-aware live | [`edge.md`](edge.md) | +0.154R, CI [−0.022, +0.346]; triage's replay says −0.117 net | About 800 closes |
| C11 | Fade-the-spike on Boom/Crash (n = 247, 50-82x short of power) | [`stop-free.md`](stop-free.md) | +0.030 to +0.374 vs always | Raise the changepoint target rate for thousands of events |
| C12 | Inverted Boom grind side (no-stop drift +0.04R at 30 bars to +0.20R at a day) | [`first-passage.md`](first-passage.md) | EV = +0.037B − S on 17 stop fills | Measured stop fills; it means being short the jump |
| C13 | Trend-efficiency context for level trades (break share 11.3% to 1.4%) | `docs/todo.md` 0n | Live gap +0.251R on 45 trades | Test as sizing (A1-style) |
| C14 | Instruments at a level at once (eurusd holds 78% with none, 96% with four) | [`tallying.md`](tallying.md) | Unconditioned | Hour and volatility conditioning, a block bootstrap |
| C15 | Origin-swing with a 15m+1h entry and a target at about 60% of the corridor | [`reachable.md`](reachable.md) | 94 signals with 15m | A replay |
| C16 | Trading the break (break_probability AUC 0.658; break push median 2.82v) | [`force.md`](force.md) | Untested | A replay against random breaks |
| C17 | Countering the anchor: scalp the pullback to a daily call's entry | `research/planned/countering-the-anchor.md` | Untested; falsifiers written | The planned run |
| C18 | Holdable implied cross (EURGBP from EURUSD and GBPUSD) | `research/planned/cross-spreads.md` | Pre-registered prediction: no | The planned run |
| C19 | CADJPY Thursday T+2 roll (+1.23 bps every Thursday, 9 of 9) | [`crossing.md`](crossing.md) | +0.69 bps a week, locked | Read the three swap rates |
| C20 | Momentum build-up at 15m, 4h and 1d (null at 1h, 0 of 12) | [`momentum-buildup.md`](momentum-buildup.md) | Untested at the other horizons | One run per horizon, no sweep |
| C21 | Daily turns with a contemporaneous volatility-scaled threshold (AUC 0.595) | [`turns.md`](turns.md) | One line in the harness | Re-run |
| C22 | β0 (connected components) drop 5-10 bars before reversals | `research/planned/carried-ideas.md` | Untested | One run, against walks |
| C23 | Queue order: slow strategies first, or Hedge weights over shadow intents | [`queueing.md`](queueing.md), [`bandits.md`](bandits.md) | swing-level's +0.576R did **not** stand (triage −0.079R net) | Only once a slow strategy has an edge |

## Part D: crypto ideas that need exchange data (FT)

Exchange data that MT5 does not carry: funding, open interest, long/short ratios, taker flow,
mark and index basis, liquidation levels, depth. Bybit is reachable through `bytick.com`; Binance
only through its archive. See [`../freqtrade/README.md`](../freqtrade/README.md).

| # | Idea | Agenda or source | What to test |
|---|---|---|---|
| D1 | **OI quadrants at structure levels.** A level approached by fresh positions (price and OI up) vs by covering (price up, OI down) | `till_infinity/prices/positioning.py`, 7 item 11 (capital age) | Do the quadrants change a level's hold or break rate? This is the question positioning.py was collected to answer |
| D2 | **Liquidation-cascade conditioning.** P(cascade \| state): when does a sharp move continue (fuel: high OI, extreme funding, crowded long/short) and when does it exhaust? | 5 items 6-7, 7 item 7 | Condition the shock forecaster's 4x events on fuel; trade continuation vs fade only where they separate |
| D3 | **Crowding fade, re-tested** (C2) on full history | [`crowding.md`](crowding.md) | Both halves now have funding (Bybit since 2024) |
| D4 | **Basis dislocation.** Mark vs index (premium) extremes revert? | Freqtrade's mark candles, 5 item 3 | Revert vs continue, at fees and funding |
| D5 | **Taker imbalance with the shock score.** Taker buy share as a sign for moves the shock model says are coming | [`vpin.md`](vpin.md) (VPIN null), [`shockvolume.md`](shockvolume.md) | VPIN found no sign; test the raw taker share conditional on a high shock score only |
| D6 | **Perp vs spot sheaf obstruction.** When perp, spot and another venue disagree beyond their spreads, does volatility follow? | 7 item 3 | A risk signal first (A4.3); direction only if it separates |
| D7 | **Consensus latency.** Time for Bybit, Binance (archive) and Coinbase to agree after a shock | 4 item 10, [`lagging.md`](lagging.md) | Measure first; tradable only with sub-second fills, so likely a risk input |
| D8 | **Capital age structure.** Cohort births and deaths from OI changes; does an "old" market behave differently from a "young" one? | 7 item 11 | Volatility and shock rate by OI age profile, against GARCH walks |
| D9 | **Global-games threshold.** Dispersion in long/short and funding across venues as "disagreement"; low dispersion and high crowding as a cascade risk | 7 item 7 | Cascades by dispersion bucket |
| D10 | **Funding-stamp drift.** Price behaviour into and after each funding stamp at extreme rates | A3.7 | Mean move around stamps by funding decile, both halves |

## Part E: structural ideas from the agendas that could become trades

These are research first. Each becomes a trade only if the research finds information the shock
forecaster lacks.

| # | Idea | Agenda | First test |
|---|---|---|---|
| E1 | Episode segmentation, with trades judged per episode type rather than per bar | 5 item 20, 6 item 17 | Do strategy results differ by segmented episode beyond volatility state? |
| E2 | Regime provenance: a fingerprint match to past regimes picks the strategy family | 6 item 1 | Out-of-sample: does the nearest past regime's best family beat the current one? |
| E3 | Phase-mixture weights α_i(t) scale trend vs reversion sleeves | 6 item 2 | Does a mixture model beat a discrete HMM on held-out likelihood, then on sleeve P&L? |
| E4 | Path signatures as memory: same state, different path, different outcome? | 7 item 5 | Incremental AUC over the shock forecaster, on markets vs walks |
| E5 | Optimal-transport speed of the return distribution as a regime-change alarm | 7 item 4 | Does a large W(P_t, P_t+1) lead shocks beyond realised volatility? |
| E6 | Strategy equivalence: collapse look-alike strategies before counting trials | 6 item 12 | Position-path correlation across all strategies; feeds the effective-trial count |
| E8 | Law-candidate grading: score every finding on invariance, mechanism, both halves, walks and a second measurement system | 8 item 21 | Apply to [`findings.md`](findings.md); the regularities that grade as laws are what strategies should be built on |
| E7 | Ontology test: which of our objects (levels, zones, sweeps, order blocks, cycles) carry information on markets that they do not on walks | 7 (ontology) | One run per object family, the same harness for each. No new data needed |

## Part F: trading ideas inspired by the agendas

Trades, not risk rules, drawn from agendas 3-8. Most are **conditional**: they trade only where an
agenda's measured state says the odds differ. That gives each a natural null: the same trade taken
unconditionally, or in random states for the same share of time.

| # | Idea | Agenda | How it trades | First test | Venue |
|---|---|---|---|---|---|
| F1 | **Shock-metabolism range trade.** After a shock, volatility decays at a state-dependent k. Once the fitted half-life has passed, fade excursions to the band edges | 8 item 7 | Range fades only in the post-shock decay window | Do band fades pay more after the half-life than at random times? | MT5, FT |
| F2 | **Unrecovered-stress straddle.** Arm B1 only when unrecovered stress F_t is high | 8 item 18 | B1 gated by F_t | **Tested 2026-10-01, null with the wrong sign:** −0.158R vs −0.102R at low stress ([`expansion.md`](expansion.md)) | MT5 |
| F3 | **Allosteric gating.** Take a setup only in states where the market's gain to that setup's trigger is high, ∂move/∂trigger = f(Z) | 8 item 8, 6 item 11 | Existing structure signals, filtered by the measured gain | Estimate the gain by state on the first half; does trading high-gain states beat all states on the second? | MT5 |
| F4 | **Alpha ore bodies.** Map each strategy's P&L over state space (volatility, spread, shock score, hour, ZMA state); trade only inside dense connected regions | 8 item 15 | Every strategy, restricted to its ore body | Map on the first half; does the second half's P&L inside the regions beat outside, and beat random regions of the same size? | All |
| F5 | **Bullwhip continuation.** When a small move meets high leverage (OI) and delayed reaction, trade for amplification | 8 item 10, 5 item 6 | Continuation entry after the first leg, crypto first | Is the second leg larger in high-OI states than in low-OI states with the same first leg? | FT |
| F6 | **Information congestion fade.** When participation in an obvious signal spikes (funding, OI, taker share, a big figure), fade it as it degrades | 8 item 5, 7 items 7 and 10 | Fade crowded signals once participation crosses a threshold | The crowding fade (C2/D3) is the first case; then FX big figures ([`focal-points.md`](focal-points.md)) | FT, MT5 |
| F7 | **Residence-time unwind.** When long-held open interest (old capital) starts leaving, trade continuation of the unwind | 8 item 19, 7 item 11 | Entry on falling OI with an aged position profile | Do unwinds of old OI run further than unwinds of young OI? | FT |
| F8 | **Special-cause regime trade.** After a special-cause shift (a control chart breaks), stop fading and follow the new process until the chart settles | 8 item 6, 4 item 12 | Switch from reversion to continuation only on a special-cause flag | Does continuation beat reversion after flags, and not at random times? | MT5, FT |
| F9 | **Lesion breaks.** Trade level breaks only where morphology is abnormal before the touch (spread, tick rate, range shape) | 8 item 9, 5 item 19 | Break entries filtered by an abnormality score | Break rate and push with and without the lesion, against break_probability alone (AUC 0.658) | MT5 |
| F10 | **Venue-invariant signals.** Trade a crypto signal only when it fires on both the broker's CFD (MT5) and the exchange perp (Bybit) | 8 item 11 (geodesy), 7 item 3 (sheaves) | The agreement filters out venue artefacts | Do signals present on both venues outperform single-venue ones? | MT5 + FT |
| F11 | **Episode-species strategies.** Classify episodes into species by invariant traits, then run each strategy only on the species it was built for | 8 items 2-3, 5 item 20 | A strategy-to-species map | Does species-matching beat volatility-state matching? | All |
| F12 | **Island re-coupling.** When an instrument decouples from its cluster, trade its return to the cluster | 8 item 4 | Convergence entry on a correlation break | Caution: cross-venue and cross-rate convergence was null ([`crossing.md`](crossing.md), [`chan.md`](chan.md)). Test only with a pre-registered bar | MT5 |
| F13 | **Regime-provenance analogues.** Match today's regime fingerprint to past regimes; trade what worked in the matched regime | 6 items 1 and 18, 4 item 19 | Strategy selection by analogue | [`fractal-twins.md`](fractal-twins.md): twins time volatility, not direction. So select *strategy families*, not sides | All |
| F14 | **Transport-speed breakout.** A fast optimal-transport shift in the return distribution arms a breakout in the direction of the shifted mean | 7 item 4 | Breakout after a large W(P_t, P_t+1) | Direction is the risky part: test the arming against B1's direction-free version | MT5, FT |
| F15 | **Liquidation-cascade follow and fade.** Follow a cascade while fuel remains (OI still falling, funding still extreme); fade it when fuel is spent | 5 items 6-7, 7 item 7 | Two rules from one state | Do cascades with fuel left run further than spent ones? | FT |
| F16 | **Funding-stamp positioning.** Hold into or out of the stamp at extreme funding where the drift around stamps is reliable | A3.7, D10 | Timed entries around stamps | D10 measures the drift first | FT |

## Part G: magnitude without direction

Set 2026-10-01. The expansion alert ([`expansion.md`](expansion.md)) predicts that volatility will
expand (AUC 0.78, 3.5x in its top decile). As specified, though, a box straddle could not trade it.
This part sharpens the question before more trades are tried:

> **Can a market state carry information about the size of the coming move while carrying little
> or none about its sign?** That is, I(C; |R|) > 0 while I(C; sign R) ≈ 0.

**Research, first:**

| # | Question | Measure |
|---|---|---|
| G1 | Does the alert predict *excursion*, not just a range percentile? | Two-sided excursion Y = max(MFE up, MFE down) over H bars, in volatility units and in box heights: P(Y > θ \| alert) against compressed-without-alert, not compressed, and all bars |
| G2 | Magnitude without sign | Mutual information of alert strength with \|R\| against with sign(R), each against a shuffled null; P(up \| alert) |
| G3 | When does the move arrive? | The hazard of a first excursion beyond kσ, bar by bar, by alert strength |
| G4 | Does it scale with compression intensity? | P(Y > θ) and bracket EV by alert-strength decile: monotone or not |
| G5 | Why did B1 lose gross? | Whipsaw rate (both box edges touched within H), and how much of the favourable excursion a static stop gives back |

**Then the trades, all SL-only (no take-profit, the stop takes the profit):**

| Strategy | Gate | Direction | Exit |
|---|---|---|---|
| A | none (any compressed bar) | two-sided bracket, OCO | initial stop at the opposite edge, then a trailing stop k·σ from the best price |
| B | the alert | two-sided bracket, OCO | the same |
| C | none | one-sided, in the box's drift | the same |
| D | the alert | one-sided, in the box's drift | the same |

The main comparison is A → B: does the gate turn an unprofitable direction-free bracket into a
profitable one? The ablation G4 asks whether the economics improve monotonically with
compression intensity. Judge on EV in R (not hit rate), with MFE, MAE, run length and activation
rate beside it, net of spread, swap and repeated activations. Use both halves and walks.

**Results (2026-10-01, [`expansion.md`](expansion.md)):** G1-G4 hold (energy 10x more than sign, a hazard of 79% by bar 16 under the alert, monotone with strength), but G5 kills the bracket: the alert raises the whipsaw from 0.10 to 0.30, and once price leaves the box it commits exactly as often as on GARCH walks (−0.082 vs −0.083 excess over martingale odds). Best SL-only bracket over 20 configurations: −0.010R.

**The wider program, if G1-G2 hold:** search for other *direction-free precursors of market
energy* (the shock forecaster, the vol clock, release timing, open interest) and test whether each
can be monetised through asymmetric execution.

## Part H: the pre-expansion state, and the life of an expansion

Set 2026-10-01; first results in [`expansion.md`](expansion.md). Compression is one sensor of a
possible pre-expansion state. Of 15 sensors bars can measure, only the calendar ahead added (now
shipped). The open sensors need order-book or trade data (crypto first):

| # | Sensor | Data |
|---|---|---|
| H1 | Liquidity: executable depth falling while the range stays tight (the buffer disappearing) | Binance `bookDepth`, Bybit order book |
| H2 | Volume composition: trade count against average trade size (participation against capital compression) | Binance `aggTrades` |
| H3 | Order flow against price: taker imbalance accumulating while price is trapped | Binance `aggTrades`, `metrics` |
| H4 | Scheduled releases inside the next 16 bars | the news service's calendar |

**The life of an expansion** (onset → acceleration → maturity → decay → recompression), as
questions to answer and then trade:

| # | Question | Use |
|---|---|---|
| H5 | Onset as time-to-event: P(onset ≤ t \| state) | arming windows for any direction-free entry |
| H6 | Duration, magnitude and velocity at onset, against walks fitted to each market's own persistence | stop width and hold time for trades already open; sizing |
| H7 | Phase recognition: which phase is the market in now? | stops that widen early and tighten in maturity and decay (SL-only, no take-profit) |
| H8 | A universal pre-expansion signature, or one per market? | the alert per family against pooled (pooled wins so far: one model, every family 0.75–0.85) |

## Part I: trading the energy without direction

Set 2026-10-01. The alert says a big move is coming and roughly when (79% reach 3σ within 16 bars,
median 7), but not which way. So these trades take both sides and rely on stops to cap the loser.
All are SL-only (no take-profit) and are judged per family (FX, metals, crypto, stocks, **Deriv**)
and per interval, against the quiet-alert arm and GARCH walks.

| # | Trade | How | Note |
|---|---|---|---|
| I1 | **Hedged pair** | On a hedging-mode MT5 account, open a long and a short at once when the alert fires, each with its own SL (at the opposite box edge, or 1.5σ), both trailing 2σ behind their best price | Economically the same as B1's bracket (stops at the edges), but it pays both spreads up front and swap on both legs while both are open. So expect slightly worse than B1, unless the fills differ |
| I2 | B1 bracket with trailing stops | Buy stop and sell stop at the box edges, OCO, trailing 2σ | −0.013R on real markets (Part G); rerun with Deriv, 4h and 1d |
| I3 | Volatility options on the alert | Buy a straddle when the alert fires | Monetises energy without needing commitment. Deribit BTC/ETH are reachable; MT5 has no options |
| I4 | **Closed 2026-10-01:** order-book-gated bracket (crypto). No order-book or flow sensor adds to the alert ([`expansion.md`](expansion.md)). Was: | Arm the bracket only when the alert fires and the buffer is thin (depth within 1% low against its norm) or flow is piling against a trapped price | Only if the order-book study finds a sensor that counts |
| I5 | **Closed 2026-10-01:** flow-signed entry (crypto). Flow calls no side on rows known in advance; the 0.558 was selection bias. Was: | When compressed, take the side of the net taker flow that price has not yet expressed | Only if flow calls the breakout's side (tested in `buffer.py`) |

**Results, 2026-10-01** ([`expansion.md`](expansion.md), [`../freqtrade/README.md`](../freqtrade/README.md)):

- **I1, the hedged pair:** positive in the pooled run (+0.082R), but almost all of it was Deriv
  bar-fill optimism (Boom, Crash, Range Break). On real markets it is negative in FX, metals and
  stocks.
- **I2, the trailing bracket:** +0.019R pooled with Deriv, same caveat. Real markets are mixed.
- **Candidates left:** Drift Switch 10 and Jump 50 at 15m, pending a tick-fill check.
- **Freqtrade on crypto** (D3 FundingFade, D10 FundingStamp, a close-confirmed B1): none beats its
  coin in both halves. Fading extreme funding did worse than a coin. Trading *with* it was then tested once on
  Binance 2023 and rejected (−0.437% a trade, worse than a coin in both halves): the effect's sign
  flips by period. Funding-based direction is closed.

## Closed: do not re-run without new information

- Deriv binaries and barrier products: a 2.41% margin on synthetics, 12-15.6% on real instruments
  ([`deriv-payouts.md`](deriv-payouts.md)).
- Halving size at a high crash score: beats halving at random in 1 of 18 cells
  ([`session-switch.md`](session-switch.md)).
- Changepoint (BOCPD) exits: +0.005R, t 0.5 ([`hold-clock.md`](hold-clock.md)).
- Wider stops at constant risk ([`widestop.md`](widestop.md)), limit and pullback entries
  ([`limitfills.md`](limitfills.md)), lagging-indicator entry timing ([`indicators.md`](indicators.md)).
- Pairs trading on the Deriv synthetics ([`generated.md`](generated.md)). FX carry
  cross-sectionally ([`carry.md`](carry.md)). VPIN ([`vpin.md`](vpin.md)).

## Suggested order

1. **Decisions that need no backtest:** A1.2 (uniform risk cut), A3.6 (stop-side gate), A4.9 and
   A4.10 (bitemporal and type checks).
2. **Risk from forecasts we trust:** A1.1, A1.3, A2.1, A4.1, A4.2. They use models that already
   pass, so the prior is best.
3. **Crypto exchange data:** D1, D2, D3, then F5, F7 and F15. They are the first test of information MT5 cannot give,
   and the study that converged on volume says new information is what moves the needle.
4. **Direction-free and conditional trades:** B1 and B2, then F1, F2 and F4 (the ore-body map also grades every existing strategy).
5. **The ontology test** (E7), which reframes the rest.
