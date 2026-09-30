# López de Prado's methods on this desk: what survives deflation, and whether meta-labeling rescues the signals

Harness: [`research/harness/lopezdeprado.py`](../harness/lopezdeprado.py). Lab run 2026-09-30.

## The question

Marcos López de Prado's work ([quantresearch.org](https://quantresearch.org/Vita.htm)) is mostly about not fooling yourself. It
covers deflating a result for the number of things tried, labelling trades by the path they take,
cross-validating without leakage, and sizing bets from probabilities. This desk has now run dozens of
studies with hundreds of cells, and it plans a confirmation layer that is, formally, his
meta-labeling. So there are two questions:

1. Which of the desk's "survivors" survive once deflated for the trials behind them?
2. Done his way, does meta-labeling rescue the structures signals where confirm.md's learned
   confirmer did not?

Two smaller checks follow: trend-scanning labels and VPIN. There is also a note on HRP.

All sources are freely available:
- Bailey & López de Prado, "The Deflated Sharpe Ratio" (JPM 2014, SSRN 2460551), and "The Sharpe
  Ratio Efficient Frontier" (2012, SSRN 1821643) for the PSR;
- Bailey, Borwein, López de Prado & Zhu, "The Probability of Backtest Overfitting" (2015, SSRN
  2326253), for the False Strategy Theorem;
- *Advances in Financial Machine Learning* (2018): ch. 3 on triple barrier and meta-labeling, ch. 7
  and 12 on purged and combinatorial CV, ch. 10 on bet sizing, ch. 19 on VPIN;
- Easley, López de Prado & O'Hara (RFS 2012; JFE 2016), for VPIN and bulk volume classification;
- *Machine Learning for Asset Managers* (2020), ch. 5 on trend-scanning;
- "Building Diversified Portfolios that Outperform Out of Sample" (JPM 2016), for HRP.

## 1. The desk's survivors, deflated

**Method.** Each result is expressed as a z: a t-statistic, or an estimate over its standard error.
Under the null each of N trials is a unit-variance z, and the False Strategy Theorem gives the
expected maximum:

E[max_N] = (1 − γ) Φ⁻¹(1 − 1/N) + γ Φ⁻¹(1 − 1/(N e))

The deflated confidence is Φ(z − E[max_N]), which is the DSR's logic applied to a t rather than a
Sharpe ratio.

N is estimated three ways:
- **N cells:** every cell the study tested;
- **N eff:** a clustered effective count, e.g. confirm.md's 8,366 cells are about 405 gate × family
  × pair × target combinations, the rest being stop and entry variants of each;
- **N = 100:** for scale.

A survivor passes at a deflated confidence above 0.95 at N eff.

| study | claim | z | N cells: defl / Šidák | N eff: defl | verdict |
|---|---|---|---|---|---|
| confirm.md | FX 1h + 15m candle, 2R (+0.370R vs plain) | 4.0 | 0.573 / 0.767 | 0.844 (405) | **fail** |
| confirm.md | FX 4h + choppy 1h, 1R | 3.8 | 0.493 / 0.546 | 0.791 | **fail** |
| confirm.md | Deriv 1h + 15m sweep, 1R | 3.6 | 0.414 / 0.264 | 0.730 | **fail** |
| confirm.md | Deriv pivot + 1h MFI, 2R | 3.2 | 0.269 / 0.003 | 0.584 | **fail** |
| confirm.md | crypto 1h + TRIX, 1R | 5.4 | 0.943 / 1.000 | 0.992 | pass |
| gaptrade.md | Friday-close fade, gross +2.11 bps | 5.0 | 0.981 / 1.000 | 0.999 (24) | pass |
| fridayflag.md | big-gap AUC 0.601 | 5.7 | 1.000 | 1.000 (3) | pass |
| bandrace.md | FX touch skill +0.0865 (se 0.0026) | 33 | 1.000 | 1.000 (16) | pass |
| bandrace.md | FX race skill +0.0207 at N = 20 | 7.1 | 1.000 | 1.000 | pass |
| calendar-returns.md | FX vol profile corr +0.96, 168 buckets | 25 | 1.000 | 1.000 (8) | pass |
| anomalies.md | shock AUC 0.76 | ~50 | 1.000 | 1.000 | pass |
| triage.md | `opportunity` gross +0.010R | 0.3 | 0.086 | 0.086 (13) | fail |
| triage.md | `snap` gross +0.011R | 0.5 | 0.121 | 0.121 | fail |
| stophunt.md | best trigger gross +0.045R | 1.2 | 0.063 | 0.191 (30) | fail |

For reference, E[max] is 1.57 at N = 10, 2.53 at 100, 2.99 at 405, 3.26 at 1,000 and 3.82 at 8,366.

**What survives is volatility, not direction.** The shock forecaster, the vol profile, the touch
probabilities and the gap-size model are all about *how much*, and they clear deflation by a mile.

Of the five shadowed confirmation gates, **four fail deflation**. Their t of 3.2-4.0 is roughly what
the best of ~400 null cells produces (E[max] 2.99). Only the crypto TRIX gate (t 5.4) survives, and
confirm.md already noted its second half is weaker. The shadow run (`trading/shadow.py`) is the right
treatment, since live data is the only out-of-sample test left. But the prior should now be that
four of the five are noise.

The gap reversal survives as a statistical effect. gaptrade.md already found the Sunday spread eats
it.

The race skill (+0.021) survives statistically too, but bandrace.md found it does not trade.

## 2. Meta-labeling under combinatorially purged CV

**Setup.**
- **Primary model:** the structures signal's side (fade the zone), entered at the level timeframe's
  close. Production's zone touches come from confirm.py's replay: 58,721 real-market signal ×
  timeframe pairs, 37,460 Deriv and 40,508 walks. FX rollover touches are excluded.
- **Label:** triple barrier, i.e. whether the 1R target is hit before the structure stop within
  the time limit.
- **Secondary model:** gradient boosting on the card features and the 24 indicator states
  confirm.py computed. Variant B adds trend-scanning (part 3).
- **CPCV:** 6 time groups with 2 in the test set, giving 15 splits and 5 backtest paths. Training
  labels whose span overlaps a test group are purged, with a 1% embargo after each.
- **Bet size:** m = 2Φ((p − ½)/√(p(1−p))) − 1, taken at zero below ½.
- **Null:** the same sizes shuffled within each test group.

| universe | variant | median path Sharpe (range) | primary | random-size null median / 95th | paths positive | paths beat null 95th | AUC | taken |
|---|---|---|---|---|---|---|---|---|
| real, all | A | −0.62 (−1.31, −0.05) | −7.49 | −3.11 / −2.57 | 0% | 100% | 0.539 | 15% |
| real, all | B | −0.53 (−1.08, −0.19) | −7.49 | −3.33 / −2.67 | 0% | 100% | 0.541 | 16% |
| real, FX | A | −1.62 | −7.75 | −4.19 / −3.52 | 0% | 100% | 0.533 | 22% |
| real, crypto | A | −0.70 | −3.16 | −1.37 / −0.77 | 0% | 60% | 0.536 | 21% |
| real, metals | A | −1.02 | −2.52 | −1.41 / −0.65 | 0% | 0% | 0.508 | 23% |
| Deriv | A | −0.37 | −2.03 | −1.07 / −0.38 | 0% | 40% | 0.536 | 18% |
| Deriv | B | −0.19 (−0.44, +0.10) | −2.03 | −1.03 / −0.35 | 20% | 60% | 0.538 | 21% |
| **walks** | A | **+0.22** (−0.72, +0.42) | −2.08 | −1.07 / −0.30 | **80%** | **80%** | **0.541** | 20% |
| walks | B | −0.21 | −2.08 | −1.11 / −0.46 | 40% | 60% | 0.540 | 20% |

- **The verdict does not change.** Done properly, the meta-labeler's AUC is 0.533-0.541 on real
  markets, and **0.541 on our walks**. confirm.md's learned confirmer read 0.537 on both. The
  secondary model learns the stop-and-target geometry, which is the same on memoryless walks, not
  the market.
- **It never makes the strategy positive on a real market.** No path is positive in any real
  family.
- **The walks' formal "pass" is the proof of that.** On memoryless walks the meta-labeled
  strategy's median path Sharpe is +0.22 with 80% of paths positive. Whatever the secondary model
  does there, it cannot be market skill.
- **"Beats the random-size null" is mechanical here.** The primary loses, so any rule that bets
  less on average, with sizes of about 0.01 taken on 15-23% of signals, loses less than a random
  reshuffle of the same sizes. The pre-registered "beats null" leg therefore passes on real FX
  without any skill. The two legs that matter, a positive median and 80% of paths positive, fail
  everywhere real.
- **Trend-scanning adds nothing** (variant B against A, AUC +0.001-0.002).

## 3. Trend-scanning as a regime feature

The trend-scanning t is the OLS t of log price on time over the last 10, 20, 40 or 60 bars of the
confirming timeframe, taking the window with the largest |t|. It is known before the touch and
signed so that positive means already trending the fade's way.

| universe | trend_t AUC for "hits 1R" [95%] | halves | \|t\| AUC |
|---|---|---|---|
| real, all | 0.495 [0.484, 0.506] | 0.495 / 0.495 | 0.503 |
| FX | 0.494 | 0.495 / 0.493 | 0.505 |
| crypto | 0.504 | 0.513 / 0.499 | 0.498 |
| metals | 0.487 | 0.466 / 0.503 | 0.497 |
| Deriv | 0.499 | 0.492 / 0.506 | 0.497 |
| walks | 0.493 | 0.498 / 0.489 | 0.502 |

**Null.** Neither the trend into the level nor its strength separates touches that hold from those
that don't, on any family, and every interval spans 0.5. This is the same answer as the chan.md
stationarity filter's question, asked a different way.

## 4. VPIN as a toxicity feature

VPIN here is built from bulk volume classification on tick volume, with the buy share Φ(Δp/σ),
averaged over 50 bars. It is added to a shock forecaster at 15m, predicting a 4× shock in the next
4 bars from volatility state, shock clustering and the clock, as in anomalies.md.

| family | base AUC | + VPIN | gain [95%] | halves |
|---|---|---|---|---|
| FX | 0.7613 | 0.7583 | **−0.0030** [−0.0056, −0.0001] | −0.0004 / −0.0054 |
| crypto | 0.7511 | 0.7564 | +0.0052 [+0.0014, +0.0105] | +0.0105 / +0.0004 |
| Deriv | 0.6966 | 0.6946 | −0.0021 [−0.0079, +0.0031] | −0.0006 / −0.0031 |
| walks | 0.5032 | 0.5084 | +0.0052 [−0.0002, +0.0109] | +0.0048 / +0.0055 |

**Null.**
- VPIN makes the FX forecaster slightly worse.
- On crypto it adds +0.005, which is below the 0.01 bar, gone in the second half, and the same as
  the walks' +0.005 (whose volume is drawn independently of price).
- Tick volume on a retail MT5 feed is a count of quote updates, not signed trade flow, so VPIN's
  premise, informed order flow, has nothing to measure here. Easley et al. built it on exchange
  volume.

## 5. HRP, a note

Hierarchical Risk Parity allocates risk across strategies by their correlation tree, and it is more
stable out of sample than mean-variance because it never inverts the covariance matrix. It can only
allocate among strategies with an edge, and triage.md found none (gross −0.10 to +0.03R, none better
than random selection). So there is nothing to allocate. Once the shadow gates or the `cycle-*`
strategies earn a positive, deflated record, HRP is the right way to size among them. Their returns
are correlated through shared signals and shared FX exposure, which is exactly the case HRP's
clustering handles and inverse-variance weighting mis-sizes.

## What this means

- **The desk's real findings are about volatility.** The shock forecaster, the vol clock, the touch
  probabilities and the envelope are the results that survive deflation, and they are all shipped.
  Every directional result was either null from the start or, like four of the five confirmation
  gates, is within what the best of several hundred null cells produces.
- **Meta-labeling does not rescue the signals.** It is the formal version of the planned
  confirmation layer, and under purged combinatorial CV it learns what the walks also offer. It
  never turns a real-market path positive.
- **For the shadow gates:** keep recording them. Judge them with a deflated bar, not t ≥ 3. With
  five gates live, the live test is N = 5 (E[max] about 1.2), so a live t around 3 would be
  convincing. The historical t's were not.
- **For future research:** report each study's trial count, and deflate its best cell before
  calling it a survivor. This doc's table is the template.

Nothing here changes production.
