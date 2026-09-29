# Can Friday's state predict the FX weekend gap, and is flattening before it worth it?

Harness: [`research/harness/fridayflag.py`](../harness/fridayflag.py). Lab run 2026-09-29.

## The question

The FX week closes on Friday at about 21:00 UTC and reopens on Sunday at about 21:00. News lands in
between, and a stop cannot bound the move it causes, because a gap fills at the open wherever that
is. A "Friday flag" would flatten or shrink positions before a weekend with a likely large gap. That
is only worth having if the gap is predictable from what is known at the Friday close, and if
stepping out saves more than it forgoes.

## Method

For each pair and weekend, using 1h bars since 2015, the gap is log(Sunday open / Friday close). It
is measured in units of the pair's slow causal hourly volatility: the 480-bar mean of an EWMA of
|log return|.

The slow volatility matters. The first version divided the gap by the fast volatility that one of
the features also reads. That made the gap "predictable" by arithmetic, and the control caught it:
AUC 0.61 on memoryless walks. With the slow unit, the control reads 0.49-0.52.

Friday state at the close, in the same units:

| feature | what it is |
|---|---|
| `week` | the last 120 hours' return |
| `friday` | the last 24 hours' return |
| `late` | the last 4 hours' return |
| `range` | the last 6 hours' high-low |
| `vol` | the hourly volatility against its own four-week mean |
| `absweek` | the size of the week's move, `|week|` |

There are two targets:

- **big:** |gap| above twice the discovery half's median |gap|, a fixed threshold that is never fit
  on the half it scores.
- **signed:** does the gap continue or reverse Friday's move?

The flag flattens when a logistic model's big-gap probability is in discovery's top quartile. It
is scored on the verification half, on a position held with the week's move and on one held
against it, net of a round-trip cost per flattening.

Confidence intervals come from a bootstrap over whole weekends, because one weekend hits every pair.
The data is split 60/40 by time. The control is FX-calendar walks we generate: iid Student-t(3)
hourly moves, and an independent t(3) weekend gap that nothing on Friday can predict. Deriv indices
and crypto trade through the weekend and have no gap, so they are outside this question rather than
controls.

**Pre-registered.** The flag is worth building only if all of these hold:

- verification AUC for `big` is at least 0.60, with a 95% interval above 0.5;
- the control's interval contains 0.5;
- the flag's net P&L after costs is positive in verification, with an interval above zero.

A signed gap counts as predictable if |rank correlation| ≥ 0.1, with an interval excluding zero, in
both halves.

## Results

### Is a big gap predictable?

FX has 5,793 pair-weekends (415 weekends, 14 pairs). The big-gap threshold is |gap| > 1.50 hourly
volatilities. The four pairs the lab has no bars for were skipped.

| AUC for a big gap | FX discovery | FX verification [95%] | metals verification [95%] | walks verification [95%] |
|---|---|---|---|---|
| `week` | 0.524 | 0.547 [0.516, 0.579] | 0.493 [0.415, 0.568] | 0.516 [0.478, 0.551] |
| `friday` | 0.540 | 0.575 [0.548, 0.608] | 0.493 [0.404, 0.576] | 0.530 [0.488, 0.573] |
| `late` | 0.576 | 0.587 [0.554, 0.621] | 0.540 [0.455, 0.618] | 0.492 [0.459, 0.523] |
| `range` | 0.608 | 0.551 [0.512, 0.593] | 0.482 [0.397, 0.583] | 0.496 [0.464, 0.528] |
| `vol` | 0.617 | 0.553 [0.510, 0.596] | 0.493 [0.396, 0.594] | 0.463 [0.424, 0.501] |
| `absweek` | 0.540 | 0.544 [0.513, 0.581] | 0.565 [0.492, 0.629] | 0.520 [0.481, 0.556] |
| **model** | 0.647 (in-sample) | **0.601 [0.567, 0.637]** | 0.517 [0.434, 0.596] | 0.520 [0.482, 0.554] |

The **big-gap base rate moved from 24.0% in discovery to 38.4% in verification** on FX (metals
23.2% → 24.8%, walks 20.5% → 20.3%). The threshold is fixed in volatility units from the discovery
half, so recent weekends have gapped more for the same quiet Friday. AUC is a ranking and is
unaffected by the base rate, so the 0.601 still reads as skill.

What the shift does affect is the flag. Its threshold was set on discovery's scores and flags
25.9% of verification weekends, fewer than the 38.4% that were big. A flag fitted to today's rate
would flag more often, and pay more cost for it.

### Does the gap continue or reverse Friday?

| rank correlation of the signed gap with | FX discovery [95%] | FX verification [95%] | walks verification [95%] |
|---|---|---|---|
| `week` | −0.077 [−0.138, −0.017] | −0.091 [−0.161, −0.023] | −0.020 [−0.068, +0.031] |
| `friday` | **−0.134** [−0.203, −0.077] | **−0.163** [−0.234, −0.097] | −0.010 [−0.061, +0.041] |
| `late` | **−0.242** [−0.291, −0.185] | **−0.234** [−0.311, −0.160] | −0.031 [−0.076, +0.023] |

On metals the late move's correlation flips sign between halves: −0.143 [−0.247, −0.033], then
+0.157 [+0.019, +0.278].

### Does the flag pay?

Verification half, in hourly-volatility units, flattening in the model's top quartile:

| position | flags | tail losses caught | avoided | forgone | cost | net per weekend [95%] | weekend sd |
|---|---|---|---|---|---|---|---|
| FX, with the week | 25.9% | 32.7% | 625.6 | 549.2 | 138.6 | −0.027 [−0.132, +0.065] | 2.51 → 2.07 |
| FX, against the week | 25.9% | 32.6% | 549.2 | 625.6 | 138.6 | −0.093 [−0.177, +0.017] | 2.51 → 2.07 |
| metals, with | 31.8% | 24.4% | 45.7 | 71.0 | 5.0 | −0.088 [−0.224, +0.027] | 1.55 → 1.15 |
| metals, against | 31.8% | 43.2% | 71.0 | 45.7 | 5.0 | +0.059 [−0.055, +0.196] | 1.55 → 1.15 |
| walks, with | 25.3% | 27.2% | 1028.9 | 963.7 | 15.9 | +0.034 [−0.174, +0.244] | 7.64 → 6.51 |

## What this means

- **A big FX weekend gap is predictable, modestly, and it passes the AUC bar.** Verification AUC is
  0.601 [0.567, 0.637], and every single feature is above 0.5 out of sample. The control reads 0.520
  [0.482, 0.554], which contains 0.5. The late-Friday move and the Friday session carry the most.
  This is the anomalies result again ([`anomalies.md`](anomalies.md)): the size of what comes next
  is visible, and its direction is not. Metals do not generalise (0.517).
- **The flag does not pay, and it fails its pre-registered bar.** Gaps are two-sided, so stepping
  out of a weekend forgoes the gains in proportion to the losses it avoids (FX: 625.6 avoided against
  549.2 forgone). The round trips then tip it negative, at −0.027 and −0.093 per weekend, with neither
  interval above zero. Catching a third of the tail losses by flagging a quarter of the weekends is
  only slightly better than chance would do.
- **What the flag does buy is risk, not return.** The weekend standard deviation falls from 2.51 to
  2.07 hourly volatilities (−18%) for roughly −0.03 to −0.09 of a volatility per weekend. That is a
  sizing trade-off for a book that cares about gap risk, not an edge.
- **The FX gap reverses the late-Friday move, strongly and in both halves:** −0.242, then −0.234,
  with the walks at −0.03. The obvious reading is not an edge, though. The late return and the gap
  share the Friday close price. If the close is noisy (a thin last hour, a widened broker spread, a
  bid-only quote), the late move carries that noise and the gap carries it back. That produces a
  negative correlation mechanically: bid-ask bounce. Our walks have no quote noise, so they cannot
  rule this out. Trading it would mean buying or selling at that same noisy close, which is where
  the cost is.

## For production

1. **No Friday flag.** It fails its bar: the net is negative in both directions.
2. **Optional:** a card line for weekend gap risk, like the shock forecaster's. It would be a
   statement of risk, with no side, for the model's top quartile on FX. It costs nothing to publish,
   and the AUC supports it. It should not size anything until measured in production's R units.
3. **The late-Friday reversal is not for production.** Before any trade test, it needs a check on
   the Friday close quote itself: the spread at the close, and bid versus mid. The simplest test is
   to rerun with the close taken one hour before the market shuts.
