# The score — a plan

**Status: designed, not built.** Nothing in this document exists in the code
yet. It is written down first because the interesting decisions here are the
ones that are easy to get wrong quietly, and a plan that only lives in a commit
message cannot be argued with.

The target is one number per instrument, in **[−1, +1]**, positive meaning up.
Smoothed at three speeds, with thresholds that decide when it is worth saying
out loud, and a message on the channel when it crosses.

## What it is, and what it is not

It is a **summary of what the level model already says**, not a new model. Every
input below is something the system computes today: per-side directional
inference (levels §7), multi-timeframe confluence (§11), the regime (structures
§ADWIN). The score's job is to collapse them into something a person can read
in one glance, and to be quiet the rest of the time.

It is not a signal to trade. There is no position sizing here, no stop, no
performance claim. Those need resolved outcomes, and at the time of writing
there are dozens rather than the hundreds required.

## 1. From levels to a number

At any moment, price sits somewhere among the known levels. Each level *l*
already answers: given price arrives from this side, the expected push is
`push_l` volatility units, with an effective touch count `n_l` behind it.

Each level contributes a bounded opinion:

```
sᵢ = tanh(push_l / κ)                    κ = 1v, so ±1v maps to ±0.76
```

`tanh` rather than a clip: the difference between a 3v and a 4v expected push is
much less interesting than the difference between 0.2v and 1.2v, and a clip
would call them equal for the wrong reason.

Levels far from price should barely count, and "far" has to be scale-free, so
distance is measured in volatility units and passed through a Gaussian kernel:

```
proximity_l = exp(−d_l² / 2τ²)           d_l in vol units, τ ≈ 1.5v
confidence_l = n_l / (n_l + n₀)          n₀ ≈ 5 effective touches
w_l = proximity_l · confidence_l
```

```
score = Σ w_l · s_l  /  Σ w_l            ∈ [−1, +1] by construction
```

A weighted mean rather than a sum, so the range is guaranteed without a second
squashing step, and so the number does not grow just because a symbol happens to
have more levels.

**Above the base rate, or not at all.** A score of +0.6 where price drifts up
60% of the time anyway is not a finding. The reported number is the score minus
the base rate mapped into the same space, the same discipline §7 already applies
to `P(up)`.

## 2. Three speeds, and why

The chart that prompted this has three moving averages. The reason they help is
that a single smoothed line cannot distinguish *"turning"* from *"noisy"*. Three
EWMAs over the raw score, at half-lives of roughly **3, 12 and 48 bars**:

```
eₖ ← eₖ + (1 − 2^(−1/hₖ))·(score − eₖ)          h ∈ {3, 12, 48}
```

The fast line is what is happening, the slow line is the context, and **their
agreement is the confidence**. All three the same sign is the state worth
naming; the fast one alone crossing is noise most of the time, and the model
should say so rather than send it.

## 3. Thresholds it measures rather than assumes

The chart has two fixed threshold lines. Fixed thresholds are exactly the
mistake this project has already made once, and it is worth restating because
the failure is so quiet: `HalfSpaceTrees` was gated at a fixed `0.75` when the
median score was `0.766`, so it fired on **55% of bars**. The threshold looked
principled and was a claim about a distribution nobody had measured.

So the thresholds are **rolling quantiles of the score's own history**, per
`(feed, interval)`, exactly as `QuantileFilter` fixed the anomaly gate:

```
enter = q₉₀(|score|)          exit = q₇₀(|score|)
```

Two of them, not one, which gives **hysteresis**: a state is entered at the 90th
percentile and only released back to neutral below the 70th. A single threshold
makes a score hovering near it flip state every bar — the noisiest possible
behaviour precisely when the evidence is weakest.

## 4. A state machine, so the channel gets transitions

```
                 |score| > enter  and  all three EWMAs agree
    neutral  ─────────────────────────────────────────────►  up / down
        ▲                                                       │
        └───────────────────  |score| < exit  ──────────────────┘
```

**Only transitions are published.** A score that stays at +0.8 for six hours is
one finding, not seventy-two, and this is the property that decides whether the
channel is readable. It composes with the notification filter (shape `score`,
which the cooldown and hourly ceiling then apply to as a backstop) rather than
relying on it.

Every transition is journalled with the score, the three EWMAs, the thresholds
in force, the contributing levels and the regime — so the question *"why did it
say that, then?"* has an answer later, and so the transitions become labelled
examples once the following move resolves.

## 5. Sending a picture

The chart is most of what makes that indicator readable, and Telegram takes
images via `sendPhoto`. A small renderer — price with the levels drawn as
**bands** rather than lines (they are zones, see levels §5b), the score below
with its three EWMAs and the two current thresholds — would go on the message.

This is the only part that needs a new dependency (matplotlib), so it belongs
behind an optional extra and must degrade to text when it is not installed. A
notifier that cannot send a picture should send the words, not fail.

## 6. Order of work

1. `structures/score.py` — aggregation, the three EWMAs, rolling-quantile
   thresholds, the state machine. Publishes on transition only.
2. Wire into `structures/service.py` and the `structures.signals` topic; give it
   the shape name `score`.
3. `sendPhoto` in the Telegram transport plus the renderer, behind an extra.
4. **Evaluation, and not before there is data.** Score at the time against the
   push that followed, from the journal — the same progressive-validation
   discipline `facto.py` uses, against the same two baselines. Until that runs,
   the score is a summary of the model's opinion and is documented as one.

## What could make it wrong

- **Double counting.** Nearby levels on different timeframes are not
  independent evidence; confluence (§11) already fuses those, so the score
  should consume the fused view rather than each timeframe separately.
- **A quantile learned in one regime.** The rolling window has to be long enough
  to be a distribution and short enough to still be *this* market. ADWIN already
  detects the shift; the honest response to a regime change is to widen the
  thresholds until the window refills, not to keep firing at the old ones.
- **Reading like a recommendation.** A number in [−1, +1] with a colour looks
  far more certain than P(up) with a base rate beside it. Whatever is sent has
  to carry the count behind it, or it will be believed more than it deserves.
