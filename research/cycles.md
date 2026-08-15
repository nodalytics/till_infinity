# Does it matter where a level sits in the larger move

Run: `python research/harness/cycles.py`

Every feature the model has is local to the touch — `approach_vol`,
`depth_vol`, `run_vol`, `pivot`, `backcheck`, and the six candidates
[features.md](features.md) §4 tested all describe the last few bars before
price arrived. None says whether the instrument has been climbing for a
quarter, falling for one, or oscillating; nor, if oscillating, whether this
level is near the floor or the ceiling. [todo.md](../docs/todo.md) §6c asks
whether that missing context carries anything.

**It does not, on this data — and the more useful half of the answer is that
this data cannot really be asked.** 1,862 touches sound like a sample and are
not: they span **26 cycles**, and four of the six instruments contribute one or
two apiece with *zero* touches in an uptrend, so the cross-instrument gate
cannot be run at all.

## 1. The label is a rule, because otherwise it is hindsight

"We were in an uptrend" is trivially true afterwards and worthless in advance.
The label here is computed from daily closes **strictly before the touch
began**, by Kaufman's efficiency ratio over a 60-day window:

    ER = |last - first| / sum of |day-to-day moves|

One if price went straight there, near zero if it wandered back over itself.
The threshold was fixed before looking, against a stated null: a random walk of
N steps has an expected ER of about 1/sqrt(N), which is **0.129** at N=60, so
`TREND = 0.30` means "more than twice as directional as a coin".

That null is also the check that the measure works. Across twelve years of
daily closes the observed median ER is **0.131** against the predicted 0.129.

## 2. Two ways to get this wrong, both found by running it

### A cross-venue median destroys the measure

The first version took the median close across venues, on the reasoning that
`structures` takes a cross-venue consensus everywhere else. It was wrong here,
and the failure is instructive.

Venues within a feed sit at slightly different levels — spx500 quotes between
7,780 and 7,805 across eight of them, a third of a percent — and they do not
all report every day. So the median switches between price levels as coverage
changes, and **every switch adds a step to the path the instrument never
took**. ER is a ratio *to* that path, so inflating it crushes the ratio:

| | median across venues | one venue's own series |
|---|---|---|
| spx500 ER, same window | 0.081 | 0.121 |
| median over all touches | 0.049 | 0.131 |

Consensus earns its keep at tick level, where one broker's spike is a false
touch. It buys nothing across a quarter, where the venues disagree about the
third decimal and agree about the direction.

### A fixed threshold cannot label a downtrend

Under `TREND = 0.30`, the touch period contained **no downtrend days at all**.
That is not a quirk of six months. Over the full daily history:

| feed | days | uptrend | range | downtrend |
|---|---|---|---|---|
| us100 | 2,945 | 12.5% | 87.5% | **0.0%** |
| spx500 | 2,942 | 9.0% | 90.9% | **0.1%** |
| gold | 4,942 | 7.4% | 90.7% | 1.9% |
| btc | 4,941 | 13.5% | 84.0% | 2.5% |
| eurusd | 4,941 | 2.0% | 95.1% | 2.9% |
| gbpusd | 4,941 | 0.8% | 95.1% | 4.1% |

Markets fall faster and messier than they rise, so a decline rarely sustains a
high efficiency ratio over a quarter. **A symmetric threshold on an asymmetric
process labels one tail and never the other**, which leaves half the question
unasked rather than answered.

The fix is the one this project reaches for everywhere else: stop using a
constant. Terciles of *the feed's own* prior ratio distribution are symmetric
by construction and self-calibrating, since btc's ordinary directionality is
not eurusd's. That gives a usable split — 60% range, 33% downtrend, 7% uptrend
— and it is the labeller the real test runs under.

## 3. The falsification, and it fails

The question is not "does cycle state predict direction". Position-in-range
alone will correlate with `side` — near a range floor most touches come from
above — and would score as a discovery while adding nothing `side` did not
already say. The question is whether cycle state **changes what `side`
means**: within each state, does the up-rate for a given side differ from that
side's pooled rate by more than the interval on the cell?

Under the self-calibrating labeller:

| side | cycle | n | up-rate | 95% interval | vs pooled |
|---|---|---|---|---|---|
| above | *(pooled)* | 1,013 | 74.6% | 71.9% – 77.2% | |
| | uptrend | 62 | 83.9% | 72.8% – 91.0% | +9.2pp |
| | range | 661 | 74.6% | 71.1% – 77.8% | −0.0pp |
| | downtrend | 290 | 72.8% | 67.4% – 77.6% | −1.9pp |
| below | *(pooled)* | 849 | 24.9% | 22.1% – 27.9% | |
| | uptrend | 60 | 31.7% | 21.3% – 44.2% | +6.8pp |
| | range | 464 | 22.6% | 19.1% – 26.7% | −2.2pp |
| | downtrend | 325 | 26.8% | 22.2% – 31.8% | +1.9pp |

**Every cell's interval contains the pooled rate.** Nothing separates.

Nor is that an artifact of where the threshold was put. Sweeping the fixed
threshold from 0.10 to 0.40 — which moves the uptrend share from 19.7% to 0.0%
— produces **no separating cell at any value**.

## 4. It does not help a model either

Walk-forward over 1,712 touches, every touch predicted before it is learned:

| features | accuracy | AUC |
|---|---|---|
| assume the level holds *(no model)* | **75.2%** | — |
| side only | 75.2% | 0.739 |
| all nine features | 74.9% | 0.741 |
| all nine + cycle | 74.5% | 0.742 |
| side + cycle | 74.7% | 0.739 |

A thousandth of AUC, and accuracy moves the wrong way. The trivial rule still
beats everything, which is [features.md](features.md) §3 holding for the fifth
document running.

## 5. The one thing pointing anywhere, and why not to build on it

Both sides shift *up* in an uptrend: +9.2pp for touches from above, +6.8pp for
touches from below. That is directionally coherent — in an uptrend price is
likelier to go up whichever side it arrived from — but it is a **main effect**,
not the interaction that was predicted, and it does not survive any gate:

- **Significance.** z = +1.73 (above) and +1.27 (below). Neither reaches 1.96.
- **Across instruments.** Only spx500 and us100 have any uptrend touches at
  all. Of the four testable cells, three are positive and one is negative.
- **Independence.** Those 122 uptrend touches sit inside a handful of cycles.
  Touches within one uptrend are not independent draws on "does an uptrend
  matter".

This is precisely the shape [features.md](features.md) documented when +22.9
points pooled became +3.1 within cells, and [magnet.md](../docs/magnet.md)
documented when one positive estimate had an interval five times its own width.

## 6. What the sample actually is

The number that sizes every claim above is not 1,862.

| feed | touches | cycles | span |
|---|---|---|---|
| spx500 | 390 | 11 | 184d |
| us100 | 383 | 8 | 184d |
| btc | 349 | 2 | 14d |
| gbpusd | 306 | 2 | 18d |
| eurusd | 223 | 2 | 18d |
| gold | 211 | 1 | 18d |
| **total** | **1,862** | **26** | |

Two index feeds carry 19 of the 26 cycles. The other four have 14–18 days of
fine-grained history each, which is a fraction of one 60-day window — they
cannot vary in cycle state, so they contribute touches and no information.

This is the constraint §6c predicted and it binds harder than expected: **count
cycles, not touches.**

## Recommendations, in order

1. **Do not add cycle state to `Features`.** Nothing separates, the model gains
   a thousandth of AUC, and the one positive is insignificant in two of six
   instruments.
2. **Re-test when the fine-grained history reaches a few months.** The four
   short feeds need span, not more touches. At 60 days per window, a year of
   1m/5m history across all instruments is roughly when this becomes askable —
   and the harness is written and cached, so re-running it is one command.
3. **Keep the labeller.** It is point-in-time, self-calibrating and cheap, and
   [todo.md](../docs/todo.md) §6a needs exactly this to label major turns — it
   named that labelling as its hardest part. This is most of it, already built
   and already checked against a stated null.
4. **Do not reach for a longer window to manufacture cycles.** Shortening it
   until the data shows variety is fitting the measure to the sample, which is
   the failure mode §6c was written to avoid.
5. **Two findings to carry elsewhere.** Cross-venue consensus is wrong at
   cycle scale, for a reason that will recur in any path-dependent measure. And
   a symmetric threshold cannot label a market's downside — worth remembering
   for §6a, where the turns that matter most are the ones down.
