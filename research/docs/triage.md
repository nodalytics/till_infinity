# Strategy triage: keep, fix or cut

Harness: [`research/harness/triage.py`](../harness/triage.py). Read-only, on the lab's journal
snapshot (2026-08-13 to 2026-09-10) and research.db 1m bars. Run 2026-09-30.

## The question

[`stophunt.md`](stophunt.md), [`limitfills.md`](limitfills.md), [`widestop.md`](widestop.md) and
[`vetoes.md`](vetoes.md) each found every entry style losing after costs, and each ended with the same
advice: judge the strategies directly, and cut the losers. This does. For each production strategy:
does what it *selects* earn anything before costs, after costs, and more than a random pick of the
same signals?

## The strategies

`trading/strategies/`, by registered name. Every one takes structures' level calls; they differ in
which calls they accept, how they place entry, stop and target, and how long they hold.

| strategy | module | entries | context | in the journal |
|---|---|---|---|---|
| `level-scalp` | scalper | 1m-30m | 15m / 1h / 4h | yes |
| `confluence-scalp` | scalper | 1m-30m | 15m-1d | yes |
| `momentum-scalp` | scalper | 1m-30m | 15m / 1h | considered only |
| `snap` | scalper | 1m-30m | 15m / 1h / 4h | yes |
| `thesis-only` | scalper | 1m-30m | 15m / 1h / 4h | yes, the bulk |
| `inverse` | scalper | 1m-30m | 15m / 1h / 4h | yes, few |
| `sweep-aware` | scalper | 1m-30m | 15m / 1h / 4h | yes |
| `cycle-scalp` | scalper | 1m-15m | 30m / 1h / 4h | **no** |
| `cycle-turn-scalp` | stretching | 1m-15m | 15m-1h | **no** |
| `cycle-turn` | turning | 1m-1h | 1h / 4h / 1d | **no** |
| `approach-scalp` | swing | 1m-30m | 1h-4h | yes |
| `runner` | swing | 1m-30m | 1h-4h | yes |
| `swing-level` | swing | 1m-30m | 1h-4h | yes |
| `origin-swing` | swing | 1m-30m | 1h-4h | few |
| `opportunity`, `ride` | opportunity | 1m-30m | 1h-4h | yes |
| `fade-to-value` | swing | 1m-30m | 1h-4h | yes |
| `council` | council | (agents) | | no |

**What runs by default is ambiguous in the code.** The `Settings` dataclass defaults to
`("cycle-turn", "cycle-turn-scalp", "cycle-scalp")`, "the two the desk actually runs", but
`Settings.from_env` falls back to `("level-scalp",)` when `TRADING_STRATEGIES` is unset.
Production reads `from_env`, so an instance with no `TRADING_STRATEGIES` runs `level-scalp` only.
The three `cycle-*` strategies have **no trades or intents in this journal snapshot**, so this
study cannot judge them.

## Method

**The live record.** Every closed desk trade (`outcome` by `trading`, 207 with an R multiple), with
the R the account booked.

**The selections, replayed.** Every trade a strategy *asked for*, from four kinds of journal entry:
- its fills;
- the intents the risk layer declined, with entry, stop and target as placed;
- the untaken intents the service followed, excluding those that never filled;
- the intents it wanted while another strategy took the signal.

These are deduplicated per strategy, feed and minute. Each is settled on 1m bars through the
production walk (`shared.replay.walk`) at its placed stop and target, under two exits:
- `ships`, the walk's default, protecting at 1R;
- `barrier`, stop or target or the hold.

An intent is walked only if its entry was the market price at that minute (within 0.25R). A resting
limit away from price would book a fill the market never offered, and those were skipped: 870 of
7,617, mostly `level-scalp`, `confluence-scalp` and `fade-to-value`. The first run did not have this
filter, and the untaken intents and the random null read +0.3 to +2.5R. That was the artefact the
filter removes. Cost is each feed's median recorded spread, charged on both legs; gross is the same
walk at zero cost.

**Nulls and the bar.**
- **Random selection:** every published structures call at the strategy's entry timeframes, entered
  at the market in the call's own direction, with the strategy's median geometry (risk, reward to
  risk, hold), up to three times its count (21,966 picks in all).
- **Walks:** every intent on a walk we generate at its own volatility.
- **BH** across strategies.
- **Pre-registered verdicts:**
  - **keep:** net > 0 with its CI above 0, in both halves;
  - **fix:** gross CI above 0 but net ≤ 0;
  - **cut:** gross ≤ 0 and not beating random selection (BH q > 0.05);
  - **unclear:** otherwise, or n < 50.

## Results

### The live record

| strategy | trades | mean R [95%, days] | hit | total R |
|---|---|---|---|---|
| `thesis-only` | 159 | **-0.136 [-0.235, -0.026]** | 46% | -21.6 |
| `runner` | 17 | -0.127 [-0.521, +0.145] | 41% | -2.2 |
| `confluence-scalp` | 10 | -0.357 [-0.654, -0.068] | 30% | -3.6 |
| `fade-to-value` | 9 | -0.573 [-0.936, -0.116] | 0% | -5.2 |
| `opportunity` | 5 | -0.209 | 40% | -1.0 |
| `sweep-aware` | 4 | | 25% | -1.1 |
| `level-scalp` | 2 | | 0% | -1.5 |
| `approach-scalp` | 1 | | | +0.1 |
| **all** | **207** | | | **-36.1** |

### The selections, replayed (`ships` exit; `barrier` agrees within a few hundredths)

| strategy | n | net R [95%] | gross R [95%] | halves (net) | random gross | walks net | verdict |
|---|---|---|---|---|---|---|---|
| `thesis-only` | 1,676 | -0.108 [-0.126, -0.081] | -0.035 [-0.047, -0.024] | -0.129 / -0.081 | -0.007 | -0.076 | **cut** |
| `sweep-aware` | 739 | -0.117 [-0.168, -0.080] | -0.033 [-0.056, -0.011] | -0.131 / -0.099 | -0.041 | -0.112 | **cut** |
| `level-scalp` | 712 | -0.085 [-0.106, -0.062] | -0.027 [-0.050, -0.004] | -0.086 / -0.083 | -0.070 | -0.128 | **cut** |
| `confluence-scalp` | 660 | -0.082 [-0.114, -0.053] | -0.027 [-0.057, +0.000] | -0.091 / -0.076 | -0.056 | -0.091 | **cut** |
| `runner` | 445 | -0.150 [-0.241, -0.075] | -0.044 [-0.083, -0.018] | -0.169 / -0.093 | +0.010 | -0.090 | **cut** |
| `fade-to-value` | 258 | -0.134 [-0.230, -0.030] | -0.001 [-0.051, +0.056] | -0.159 / -0.059 | -0.016 | -0.222 | **cut** (unclear on barrier) |
| `opportunity` | 230 | -0.050 [-0.091, -0.000] | +0.010 [-0.080, +0.037] | - / -0.050 | +0.023 | -0.075 | unclear |
| `swing-level` | 217 | -0.079 [-0.141, -0.043] | -0.039 [-0.112, -0.002] | -0.065 / -0.116 | -0.005 | -0.049 | **cut** |
| `snap` | 178 | -0.161 [-0.305, +0.003] | +0.011 [-0.029, +0.052] | -0.321 / -0.005 | -0.008 | -0.182 | unclear |
| `approach-scalp` | 121 | -0.130 [-0.229, -0.044] | -0.023 [-0.078, +0.028] | -0.147 / -0.085 | -0.066 | -0.029 | **cut** |
| `ride` | 57 | -0.100 [-0.150, -0.058] | -0.083 [-0.130, -0.029] | - / -0.100 | -0.025 | -0.090 | **cut** |
| `inverse` | 35 | -0.392 | -0.095 | | -0.006 | -0.219 | unclear (n < 50) |
| `origin-swing` | 10 | -0.027 | +0.033 | | +0.038 | -0.111 | unclear (n < 50) |

- **No strategy clears "keep" or "fix".** Every net mean is negative. Every gross mean is between
  -0.10 and +0.03, and no gross CI sits above zero.
- **No strategy beats random picks of the same signals.** Every BH q is 0.48 or above; the random
  picks read -0.07 to +0.04 gross.
- **By family,** the only positive cells are `opportunity` on Volatility indices (+0.126 on
  barrier), `thesis-only` on Crash (+0.038) and Boom (+0.004), `confluence-scalp` and `runner` on
  Crash, and `fade-to-value` on Volatility. Every one of their CIs crosses zero, which is what about
  70 family cells produce by chance.
- **FX is consistently the worst family:** `thesis-only` -0.295, `runner` -0.331, `sweep-aware`
  -0.483, `fade-to-value` -0.50 net. It is the family with the highest spread in volatility units.

## What this means

- **The strategies differ in how much they lose, not in whether they have an edge.** Selected
  trades are about zero before costs, like random picks of the same signals, and each then loses its
  spread. This is `stophunt.md` and `limitfills.md` again, now per strategy: the entry style is not
  where an edge is, and neither is the choice among these strategies.
- **The live record agrees:** -36.1R over 207 closed trades, 159 of them `thesis-only` at -0.136R
  [-0.235, -0.026].
- **Cutting what the bar says to cut is close to not trading.** On the live record, only
  `opportunity` (5 trades, -1.0R) and the tiny `origin-swing`/`inverse` survive, so the desk would
  have lost about 1R instead of 36R over the snapshot. That is the honest reading: the gain comes from
  not paying the spread, not from anything a surviving strategy knows.
- **FX is where the losses concentrate.** The FX quiet-hours and Sunday-open vetoes (PR #20) remove
  the worst hours, but even outside them no strategy's FX selections are near zero gross.
- **The shadow gates** (`confirm.md`) record whether a narrow confirmation rescues a subset; none of
  their five cells is judged yet. Nothing here argues for acting on them early.
- **The strategies production's code names as "the two the desk actually runs"** (`cycle-scalp`,
  `cycle-turn`, `cycle-turn-scalp`) left no record in this snapshot. They are the ones that need
  judging next, from a fresh journal.

## For production (proposed, not applied)

1. **Resolve the default.** Make `Settings.from_env`'s fallback equal the dataclass default, or set
   `TRADING_STRATEGIES` explicitly on the instance, so what runs is what the code says runs.
2. **Take the cut strategies out of `TRADING_STRATEGIES`:** `thesis-only`, `sweep-aware`,
   `level-scalp`, `confluence-scalp`, `runner`, `fade-to-value`, `swing-level`, `approach-scalp` and
   `ride`. Keep `opportunity` and `snap` in shadow (paper), not live, until they have a sample that
   can say something.
3. **Judge the `cycle-*` strategies** on a fresh journal snapshot with this harness before they trade
   live; this one has none of their trades.
4. **Before anything re-enters live on FX,** demand it clears gross > 0 with a CI on FX specifically;
   FX is where every strategy lost most.
