# Choosing between strategies, when the strategies do not differ

`TRADING_STRATEGIES` is a priority list and the first taker wins, so the order
decides which strategy owns a signal two of them want. The proposal is to
replace that hand-written order with a model - an HMM over market regimes,
picking the strategy that suits the state.

**The data to test it already exists**, and it says the ordering is not the
problem.

## What was measured

`Untaken` follows every intent a strategy wanted and did not get, to its own
barriers, and records `reward_r`. That is a counterfactual return per strategy
on a **common population** - the signals another strategy actually took - which
is exactly the comparison a hand-written order is guessing at. 536 of them have
resolved.

| strategy | n | total R | mean R | win |
| --- | --- | --- | --- | --- |
| thesis-only | 13 | -0.40 | **-0.031** | 54% |
| snap | 13 | -2.04 | -0.157 | 38% |
| **confluence-scalp** | **127** | -21.88 | **-0.172** | 46% |
| **sweep-aware** | **109** | -19.52 | **-0.179** | 47% |
| **level-scalp** | **135** | -25.66 | **-0.190** | 44% |
| ride | 21 | -4.22 | -0.201 | 43% |
| swing-level | 21 | -4.80 | -0.229 | 43% |
| runner | 24 | -7.96 | -0.332 | 25% |
| opportunity | 53 | -18.63 | -0.351 | 34% |
| approach-scalp | 14 | -6.08 | -0.434 | 36% |
| fade-to-value | 6 | -4.71 | -0.785 | 17% |
| **all** | **536** | | **-0.216** | |

## Two things follow, and the second is the larger

**The three strategies with real samples are indistinguishable.**
`confluence-scalp`, `sweep-aware` and `level-scalp` carry 371 of the 536
resolutions and land at -0.172, -0.179 and -0.190. That spread is 0.018R across
samples of 109 to 135, which is noise. The eight strategies that look better or
worse have between 6 and 53 resolutions each, and at that size the ordering of
the table is mostly the ordering of their luck.

So a selector - HMM, bandit, or anything else - would be choosing between
options that have not been shown to differ. **That is the argument against
building one now, and it is about the evidence rather than about the method.**

**And every strategy is negative.** The pooled counterfactual is **-0.216R**.
Choosing better among options that are all around -0.2R gets -0.2R. The problem
this points at is not which strategy takes a signal; it is that the signals
themselves are not worth taking, which is the same conclusion
[locking.md](locking.md) reaches from the other end - 19% of trades are never in
profit at any point and the median best is 0.26R.

## What would make the HMM question answerable

The conditional version is the interesting one and it is **not** answered above:
strategies could be indistinguishable *pooled* and separate cleanly *within a
regime*, which is exactly the hypothesis an HMM encodes.

That cannot be tested yet, and for a small reason: **`regime` is not recorded on
untaken rows.** It is on every level call and it is dropped when the
counterfactual is journalled, so the 536 resolutions cannot be split by state.
Adding it is one field.

In order:

1. **Journal `regime` on untaken intents.** One field, and it turns 536 rows
   into a table that can answer the question.
2. **Then split the counterfactuals by regime** and ask whether the ordering
   changes between them. If `confluence-scalp` beats `level-scalp` in one state
   and loses in another, a state-dependent selector has something to select on.
   If the ordering is stable, it does not, whatever the model.
3. **Only then a model, and the simplest one first.** A lookup of "best mean R
   per regime" is a selector. An HMM earns its place over that lookup only if
   the regime label already computed by `learning/regimes.py` is a poor proxy
   for the latent state - which is itself a measurement, not an assumption.

The prior from the literature is modest: the HMM regime filter in
[reading.md](reading.md) refused about 70% of trades for a profit factor of
1.73 against 1.48 out of sample, and **1.10 over a twenty-year rolling test**.
The gap between those two numbers is what one favourable window is worth.

## What the ranking is good for right now

Not selection - ordering. The current priority list is hand-written, and on
2026-09-08 it was accidentally alphabetised, which promoted `confluence-scalp`
from tenth to second and demoted `thesis-only` from first to last without
anything warning. A list that can be reordered by accident should at least be
checked against the measured ranking, and this table is that check.

It does not currently justify a different order. It justifies knowing that the
order does not matter as much as the list being reordered by accident suggests.
