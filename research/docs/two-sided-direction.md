# `probability_up` and `probability_down` as separate estimators, and an AUC of 0.79 that was leakage

Asked on 2026-10-14: *markets are not random and they have directions*, *it is
even more pronounced when the directions have tails, up or down tails*, *at any
point the direction decision is either up or down*, and *we should do
probability_up and probability_down separately*.

Two results. The design point stands and is worth implementing. The predictive
result does not exist, and the way it failed is the more useful half.

## The design point: one counter cannot hold the answer

`reactions.py` returns `1.0 - probability_up` for `probability_down`, and
`levels.SideStats` keeps a single counter, `ups` over `touches`. So a level that
runs twenty sigma in each direction and a level that never moves are both
written down as 0.5.

Estimated on **different events** they become independent:

    p_up   = P(the path reaches +k sigma within the horizon)
    p_down = P(the path reaches -k sigma within the horizon)

Not complementary - both happen when the path runs up then down, neither when it
sits still - so `p_up - p_down` is direction and `p_up + p_down` is volatility,
a separation one counter cannot make. Measured on twelve traded feeds with
outcome windows held disjoint, at two sigma: **both tails reached on 39.8% of
touches, neither on 2.0%**. Forty-two percent of touches are in states the
current field cannot represent.

That is worth changing on its own, independently of whether either side
predicts.

## The predictive result, and why it was not real

The first version reported exactly what had been asked for. Direction AUC rising
monotonically with tail depth, significant everywhere, and better still when
restricted to high conviction:

| k | real, all | real, top 5% | placebo, top 5% | shuffled, top 5% |
| ---: | ---: | ---: | ---: | ---: |
| 1 sigma | 0.5511 | 0.6438 | 0.6316 | 0.6482 |
| 2 sigma | 0.6378 | 0.7420 | 0.7247 | 0.7152 |
| 3 sigma | 0.6582 | **0.7948** | 0.6515 (all) | - |
| 4 sigma | - | - | - | **0.8091** (top 10%) |

Every p was 0.002. Per-level dispersion in the up rate came back at `tau` 0.1031
against a simulated null of 0.0000 - nothing like the hold rate's 0.0109 against
0.0085, which is the gate `sym_hold_rate` failed.

**It was the outcome windows overlapping.** The walk skipped forward only until
price moved half a typical bar off the level - three to five bars - while scoring
the next **forty**. Touch `i`'s outcome was thirty-five of the forty bars that
made up touch `i+1`'s outcome, so a posterior built from earlier touches was
reading its own answer.

Forcing consecutive touches `REACH` bars apart:

| k | all | top 20% | top 10% |
| ---: | ---: | ---: | ---: |
| 1 sigma | 0.4767, p 0.392 | 0.4901, p 0.845 | 0.4754, p 0.805 |
| 2 sigma | 0.5059, p 0.838 | 0.5088, p 0.890 | 0.4997, p 0.993 |

and the dispersion gate with it: `tau` **0.0306 against a null of 0.0068,
p 0.337**.

This is not a power loss. Separation cut the sample from 3,640 touches to 408,
and at 408 an AUC of 0.6378 would still be about five sigma. The effect did not
weaken; it was never there.

`push_direction.py` carried the same defect with a ten-bar window and showed the
same thing at smaller scale - 0.5387 to 0.5682 rising with tail depth, every
p at or below 0.005, and corrected: **0.4910, 0.4935, 0.4764, 0.4927**, p 0.249
to 0.761, with per-level `tau` of exactly 0.0000.

## The tell, which is the part to keep

**Matched placebo prices and block-shuffled bars tracked the real arm at every
`k` and every coverage.** A level-specific directional signal cannot survive a
block shuffle - the shuffle destroys level structure by construction - but an
overlap artefact survives it perfectly, because it lives in the forward window
rather than in the price.

The rising-with-tail-depth gradient was the artefact's **signature**, not its
refutation: a deeper tail is a larger excursion, and a larger excursion fills
more of the shared window. The most convincing feature of the result was the
strongest evidence against it.

## What is still open

The claim was that direction is predictable and more so in the tails. This
tested it on **touches of a 100-bar extreme, per level, on twelve traded feeds**
and found chance once the windows were made disjoint. It does not test a
regional drift state, a conditional setup defined some other way, or
production's `probability_up` on production's own journalled touches - where the
0.6365 AUC was measured and where the same overlap question has not been asked.

**That last one is the first thing to check.** Production touches are journalled
with their own spacing, and if they can sit minutes apart while the outcome is
scored over a longer horizon, the measured 0.6365 is owed the same test this
file just failed.
