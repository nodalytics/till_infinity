# The zero-skill null for the desk's weighting loops

Harness: [`research/harness/zeroskill.py`](../harness/zeroskill.py). Lab run 2026-09-29.

## The question

Production has online loops that turn their own outcomes into rankings and permissions. If nothing
had skill, would they look any different? A loop that picks a winner on noise is acting on nothing,
and what it prints ("best arm at +0.13R", "right 55% of 400 calls") reads exactly like skill.

The pre-registered target: under the null, a loop may take its action on at most **5%** of the
occasions it acts on, counted across every feed or context it covers at once.

## The loops

| loop | update | decay | feeds | acts when |
|---|---|---|---|---|
| `Policy` (`trading/strategies/policy.py`) | EWMA of each exit shape's clipped R, per family\|interval, family and book | 0.05 (half-life about 14) | the exit geometry `opportunity` trades with | an arm has been seen 30 times and has the highest mean. **There is no margin** |
| `Entries` (same file) | the same ledger per family and strategy | 0.05 | nothing (recording only) | - |
| ZMA edge record (`structures/zma.py`) | cumulative calls and right, undecayed | none | `TRADING_ZMA_GATE` veto (on by default); permission for `cycle-turn` and `turning` | 200 calls and right > 52%, per feed and interval |
| cycles depth head (`structures/cycles.py`) | online regression; skill against the running mean | none | the push cap (`STRUCTURES_CYCLES_ACT`, **off** by default) | 200 settled turns and skill > 0.05 |

Not covered here:
- the volatility ensemble's weights, which weight estimators rather than arms with a skill;
- the break model's calibration, which gates nothing;
- the retrain gates, which are already judged against day-bootstrap standard errors.

## Method

Each loop is driven through **its production code**, with streams in which nothing has skill:
- **iid:** rewards resampled from the journal's own resolved rewards, independent of arm and
  context;
- **perm:** the journal's real stream with its rewards permuted across rows, keeping each arm and
  context and breaking only the link to the reward;
- **walks we generate:** iid Student-t(3) and GARCH(1,1) walks, for the loops that read prices.

Streams are run at the desk's real volume for the journal's own length and for 30, 90 and 180
days, with 200 seeds where affordable. Deriv is in the journal stream as a market.

## Results

### Policy: every warm context departs from the default, and the real ranking is inside the noise

The journal holds 773 resolved untaken rewards over 7.5 days (103 a day), credited to 9 exit
shapes. Rewards clipped to the ledger's range average −0.230R (sd 0.753).

| stream | warm contexts | departs from the fallback | best arm's mean, p50 / p95 | top-bottom gap, p50 / p95 |
|---|---|---|---|---|
| **real, 7.5 days** | 3 | **3 of 3** | +0.033R (max +0.058R) | 0.201R |
| perm null, same length | 3.0 | 100% | −0.095 / **+0.068R** | 0.264 / 0.520R |
| perm null, 30 days | 15.2 | 100% | −0.086 / +0.133R | 0.288 / 0.552R |
| perm null, 90 days | 23.8 | 100% | −0.082 / +0.100R | 0.295 / 0.531R |
| perm null, 180 days | 27.1 | 100% | −0.082 / +0.085R | 0.300 / 0.525R |

The iid null reads the same, within a few thousandths.

- **0% of the real contexts are beyond the null's 95th percentile** on the best arm's mean, the gap,
  the winner's lead over the rest, and `Entries`' gap. The shape the policy picks today is
  indistinguishable from picking on noise.
- **Under the null the policy departs from its default in 100% of warm contexts.** It always will,
  because the fallback shape is never credited: none of the null's contexts had a warm fallback. So
  the "highest mean among warm arms" always beats a default that isn't in the race. The rule has no
  way to say "nothing here has earned it", and its false-action rate is 100% against a 5% target.
  One caveat: the fallback can be credited through `opportunity` itself while it trades cold, via
  `_arm_of`. The journal's stream never made it warm (under 30 observations in every context), and
  the rule would still have no margin if it were.
- On noise, the winner's lead over the other arms reaches **0.35-0.42R at the 95th percentile**.
  That is the margin a pick would have to clear to mean anything.

### ZMA edge record: 200 calls above 52% passes 10-22% of series on a coin

| interval | horizon | edge calls | earned at the end (binomial) | share of time earned | ever earned |
|---|---|---|---|---|---|
| 1m | 30d | 5,048 | 0.0% (0.2%) | 4.4% | 38% |
| 5m | 30d | 1,371 | 5.0% (6.9%) | 14.6% | 41% |
| 15m | 30d | 758 | **20.0%** (13.5%) | **20.9%** | 37% |
| 15m | 180d | 2,289 | 3.0% (2.8%) | 9.3% | 41% |
| 1h | 90d | 682 | **21.0%** (14.8%) | **20.9%** | 35% |
| 4h | 90d | 510 | **20.0%** (18.3%) | **21.8%** | 29% |

These are t(3) walks; GARCH walks read within a few points.

- **The binomial column matches the simulation,** so the calls behave as independent coin flips
  and the arithmetic below is exact. Right > 52% at n calls is only 0.57σ above a coin at n = 200,
  0.89σ at 500 and 1.26σ at 1,000.
- **A slow series never escapes it.** At 1h and 4h the record grows by only ~100-500 calls a quarter,
  so a coin stays "earned" about **21% of the time**. Across a book of F series all on a coin, that
  is:

  | series in the book | series "earned" by chance at 1h, 90 days |
  |---|---|
  | 50 | 10.5 |
  | 100 | 21 |
  | 200 | 42 |

- **"Ever earned" is 25-44%,** because early in its life a record crosses 52% easily. That matters
  for the permission gates in `cycle-turn` and `turning`, which act the moment it does.
- The veto can only remove trades, so an on-by-default veto that fires on a coin mostly costs the
  trades it removes. The permissions **add** trades on a coin, which is worse.

### Cycles depth head: "skill" of +0.29 on memoryless walks

| walk | horizon | settled turns | skill p50 / p95 | earned (> 0.05) |
|---|---|---|---|---|
| t(3) | 30d | 25,554 | +0.300 / +0.316 | 10 / 10 |
| t(3) | 90d | 79,928 | +0.290 / +0.303 | 10 / 10 |
| GARCH | 90d | 78,862 | +0.285 / +0.291 | 10 / 10 |

The depth head beats the running mean by 0.29 on walks that have no turns to predict. How deep a
leg runs before a 2σ retracement is set by the volatility the head is fed, which is geometry, not
foresight. `MIN_SKILL = 0.05` is cleared by every series. The cap is off by default, so nothing acts
on it today, but switching `STRUCTURES_CYCLES_ACT` on as it stands would act on geometry
everywhere.

### Production's own state

The lab has no copy of production's structures or trading state: no zma or cycles records, and no
policy ledger. So the real ZMA standings could not be checked against the null. The thresholds
below are what to check them against. The journal carries the policy's inputs, and that part is
checked above.

## What this means

- **Policy:** the exit shape `opportunity` trades with is chosen on noise. With 7.5 days of rewards
  nothing separates the arms, and the rule would depart from its default even if something did not.
- **ZMA gate, on by default since PR #16:** on a coin it vetoes on about 1 in 5 of the desk's 1h and
  4h series and hands out `cycle-turn` / `turning` permissions just as often. The 52% margin was
  meant to stop "a hundred coin flips reading as evidence". It does at 1m, not at 15m or slower.
- **Cycles:** its skill measure can't tell skill from geometry. Leave the cap off until it is judged
  against the walks.

## Proposed changes (not made; production code is unchanged)

1. **ZMA gate: a significance line, not a flat 52%.** A feed has earned it when
   right / calls > 0.5 + z·√(0.25 / calls), with z the Bonferroni value for the number of series the
   desk scores (3.29 for 100, 3.48 for 200). That is 0.574 at 500 calls, 0.552 at 1,000 and 0.523 at
   5,000. It replaces `zma_min_accuracy` in `zma_gate` (scalper.py), `stretching.py` and
   `turning.py`, all of which read the same record. Until it is in, turn `TRADING_ZMA_GATE` back to
   off by default, or at least keep the permissions (`cycle-turn`, `turning`) off.
2. **Policy: margin and a scored default.**
   - Make sure the fallback shape is scored like every other arm. It is credited only when
     `opportunity` trades cold, and in the journal's stream it never reached 30 observations, so it
     was never in the race.
   - Depart only when the best arm's lead over the fallback exceeds the null's 95th percentile for
     that context's size, about 0.35-0.42R at today's volume. That shrinks with n, so a
     √(n)-scaled margin is the general form: lead > z·sd/√n_eff, with sd 0.75R and the ledger's
     effective n about 1/decay = 20.
   - At decay 0.05 the ledger remembers about 20 observations. That is too few for any real edge on
     this desk to clear the noise. A longer memory (decay 0.01) is needed for a margin rule to ever
     pass.
3. **Cycles:** judge `depth_skill` against the same head run on walks at the series' volatility (or
   against a volatility-scaled baseline) and require skill beyond that, not beyond 0. Keep
   `STRUCTURES_CYCLES_ACT` off until then.
4. **Every "earned" gate:** state its false-action rate on the book, not per series. The zma
   arithmetic above is the template: a per-series 5% becomes near-certain false passes across 50+
   series.
