---
name: finding-edges
description: Use when hunting for a trading edge, proposing a gate or filter, or tuning the structures and trading models in this repo - the null-first method that has refuted two dozen ideas here, and the checks that catch the mistakes this desk actually makes
---

# Finding an edge, and improving the models

This desk has measured a great many ideas and refuted nearly all of them. That
is not pessimism, it is the base rate, and the method below exists because
every shortcut around it has produced a confident wrong answer in this
repository's own history.

**Read [research/docs/findings.md](../../../research/docs/findings.md) and
[walks-and-edge.md](../../../research/docs/walks-and-edge.md) before designing
anything.** Findings is the synthesis; walks-and-edge is what the null means.
The short version: this desk can forecast risk and cannot yet forecast
direction.

## Before you measure: has it already been refuted?

[research/docs/README.md](../../../research/docs/README.md) is an index of questions and answers, each marked
**measured** or **planned**. Grep it before designing. The ideas below are
settled; proposing them again costs a day each.

| idea | where | the answer |
|---|---|---|
| a rolling quantile of `edge` | [docs/edge.md](../../../docs/edge.md) | worse than the constant passing the same volume, 10,483 pairs |
| levels attract price | [docs/magnet.md](../../../docs/magnet.md) | 44.9% reached against 49.5% for an arbitrary price the same distance away |
| a reward-to-risk **gate** | `trading/risk.py`, at the `reward_to_risk` gate | 0.908R ungated against 0.868R at 1.2, refusing 40,421 of 47,676 calls |
| BOS/CHoCH as a better level | [lrc-retest.md](../../../research/docs/lrc-retest.md) | every broken level holds 0.601, BOS or not |
| the LRC break-and-retest setup | [lrc-retest.md](../../../research/docs/lrc-retest.md) | −0.291R over 167,501 trades, walks −0.274 |
| a structural take-profit | [structural-target.md](../../../research/docs/structural-target.md) | reaches 1/(1+D) no more often than a walk, 1,928,819 trades |
| pausing a strategy on recent P&L | [strategy-switching.md](../../../research/docs/strategy-switching.md) | no better than pausing at random |
| Boom/Crash spikes following the trend | [structural-target.md](../../../research/docs/structural-target.md) | rate and size flat across every 1h/4h/1d bucket |

A refuted idea can be re-opened, but only by changing the *claim*, not the
hope. "BOS retests, but trend-aligned and with a strong displacement" is a
different claim; "BOS retests, but tuned harder" is not.

## The null comes first

Write down what the null produces **before** looking at the result. For a trade
rule the null is two things, and you need both:

1. **1/(1+N)** - on a driftless walk the chance of reaching +N R before −1R is
   exactly 1/(N+1), so every reward-to-risk has expected value zero. R:R alone
   cannot make money. Beating 1/(N+1) is the entire game.
2. **Matched random walks** - iid and GARCH, same volatility, same calendar,
   same costs. Markets are close to walks, so most patterns *should* look
   similar on both. Matching them does not make the pattern fake; it means
   trading it this way has no edge.

Say "matches the walks: no edge before costs". Do not say "artefact" - that word
is reserved for measurement bugs (look-ahead, fill errors, cost scaling).

**Lead with the tail.** Real P(≥ N R) minus the walk's, at the N the trade is
built for. An edge that fires twice a month and reaches 10R 15% of the time
against 9% on walks is a real edge.

## The controls that have each caught a wrong answer here

**Duty cycle, for any on/off or sizing rule.** On a losing book *any* rule that
trades less shows a profit improvement. Report net **per unit traded**, and
compare against randomly switching off at the same rate. Every pause rule tested
on this desk beat the baseline by hundreds and none beat its own random twin
(p ≈ 0.45-0.51).

**Multiplicity, for any search over cells.** Count the cells you looked at -
instruments, timeframes, parameters, strategies - and apply Benjamini-Hochberg.
Picking the best of 43 instruments gives a winner every time. On this desk 18 of
43 instruments were nominally profitable where chance gives 22, and **not one
survived BH as profitable** while five survived as losers.

**A discovery / confirmation split.** Fix a date, find on one side, confirm on
the other. A tail picked out of many cells looks good by chance.

**Block bootstrap when the rows are not independent.** Regime labels persist for
hours and trades cluster in days, so an ordinary standard error is far too
narrow. Resample whole days.

**Check the attribution before trusting any grouped table.** `DEFAULT_MAGIC` is
777701 and `magic_for` is `base + 1 + MAGIC_ORDER.index(name)`, so reading a
magic against the wrong base relabels *every* strategy as its neighbour - and
every neighbour is a real strategy name, so the table still reads as a finding.
Use `strategy_for(DEFAULT_MAGIC, magic)`, never hand arithmetic, and cross-check
against the MT5 order comment, which carries `till <strategy>`.

## Costs, and what a target can and cannot change

Cost in R is `cost_px / risk` - **set by the stop, not the target**. Moving a
target further out does not dilute the spread by a single basis point; it only
reshapes a zero-mean distribution. A setup losing 0.29R a trade on a 0.78-ATR
stop is paying for the stop, and no exit rule fixes that.

So when a rule loses, separate the three causes before proposing a fix:

- **no edge** - P(N R) sits on 1/(1+N). Nothing but a different signal helps.
- **cost** - the stop is tight relative to the spread. A wider stop, fewer
  trades, or a cheaper instrument.
- **geometry** - reward below risk for arithmetic reasons. This one is fixable
  and worth fixing: see `Strategy.reward_floor`, which moves a target out and
  refuses nothing.

## Publish, then measure, then gate - in that order

Every refuted gate in the table above was built before it was scored. The
ordering that works:

1. **Publish the reading as a feature** on every decision, named so it can be
   scored later (`regression_slope_vol`, `displacement_vol`). Costs nothing and
   gates nothing.
2. **Read the record** once there is one, against the nulls above.
3. **Gate only what survived**, as a separate change with its own measurement.

Two disciplines for step 1, both learned the hard way:

- **Absent is not zero.** A dict of zeros written on every decision reads, later,
  as a measurement. Return `{}` and omit the key.
- **One column, one unit.** A feature that silently falls back to a different
  scale (ATR when the volatility unit is missing) puts one journal column in two
  units, and both readings look fine. Publish nothing instead.
- **Carry the sign.** `efficiency` went in unsigned and the repo's own note says
  the obvious way to trade it would have had the sign backwards.

## Judging what the desk actually did

**The broker's deal history is the only complete record.** The journal is
authoritative for *intent* - strategy, gates, `reward_to_risk` - and undercounts
outcomes: positions open across a restart come back without `risk_money`, and
decisions age out before outcomes do. Pull deals from inside the container
(`GET /api/v1/history/deals?days=N`), net `profit + swap + commission + fee` per
`position_id`. The endpoint retains about 26 days whatever you ask for, so two
pulls are over different windows.

Report P&L, win rate, profit factor, max drawdown **and** a permutation test:
shuffle the same trades into random order and see whether the real drawdown is
deeper than its own shuffles. Near 0.50 means the depth is variance and position
sizing, not a losing run - which is the case for most of this desk's
instruments, where the drift is tiny against a per-trade sd and sizes vary 10-25x.

## Where the work runs

**Never on the production instance.** It has two cores and a 2.6GB container
limit; research there OOM-killed the live desk three times. Analysis belongs on
the lab (`.secrets/lab.sh`, 64 cores), and the journal is read from the host
bind-mount `~/till-data`, never through `docker exec`.

`lab.sh run <script>` **syncs the repo first**, which overwrites anything pushed
by hand. Push files after the sync, or launch with `lab.sh exec`.

## Improving the structures models

The same method, with one extra question: the structures service exists to say
*whether* a level is worth trading, so every change to it has to be scored
against the trades it produced, not against its own internal metric. A
calibration that improves `probability` and does not move the record has
improved nothing that matters.

Check the alignment claim before assuming it: this desk's strategies were found
to violate the entry/context timeframe contract in 9 of 17 cases, and the
violating trades made *more* money (+0.69 against −1.36 a trade), confounded
with interval. A plausible-sounding misalignment is still a hypothesis.

## Writing it up

Every study becomes a `research/docs/*.md` with a verdict table at the top, the
rules as frozen, the data, the results, and a row in `research/docs/README.md`.
Include the result that killed it, the caveat that weakens it, and any bug the
tests caught on the way - a study that quietly dropped its own off-by-one is
worth less than one that reports it.
