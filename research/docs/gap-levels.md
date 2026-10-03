# Levels the `gap` pass helped draw hold seven points worse, and `drawn_by_n` is a proxy for age

Two results from one scan of the production journal, 2026-10-02. The question asked was whether
`drawn_by_n` - how many drawing passes agree on a price - works as a filter. It does not, and the
reason it *looks* like it does is worth as much as the answer. What did survive the controls was
not a count at all: a level the `gap` pass helped draw is **7.4 points less likely to hold**, and
that effect is five sigma.

## What was measured

110,299 resolved level outcomes, 2026-09-22 22:40 to 2026-10-02 22:39, 51 feeds, eleven
intervals from 1m to weekly. No join was needed: a `kind='outcome'` journal entry carries both
`drawn_by` - the `+`-joined names of the passes that found the price - and the outcome itself.

| outcome | rows | what it means |
| --- | --: | --- |
| `reject` | 75,336 | price was turned away: the level held |
| `trap` | 20,836 | a false break that came back |
| `break` | 7,669 | the level failed |
| `backcheck` | 5,896 | broken, then revisited |
| `chop` | 562 | neither |

A level's job is to hold, so `reject` is the headline rate throughout and `break` is reported
beside it as a check. Both move together in everything below, so nothing here depends on which
one is chosen. `pivot:*` parts are counted separately from the formation passes, because session
pivots are a different family that arrives at most once per instrument per day.

## `drawn_by_n` looks like a filter and is not

Pooled, it is exactly the result the setting was hoping for - monotone, nearly seven points wide,
with breaks halving across it:

| formation passes | rows | reject % | break % |
| --: | --: | --: | --: |
| 0 (pivot only) | 23,003 | 66.79 ± 0.31 | 0.00 |
| 1 | 32,512 | 67.11 ± 0.26 | 10.29 |
| 2 | 17,016 | 68.56 ± 0.36 | 8.72 |
| 3 | 14,106 | 68.86 ± 0.39 | 8.48 |
| 4 | 11,153 | 69.73 ± 0.44 | 7.85 |
| 5 | 8,128 | 71.10 ± 0.50 | 6.37 |
| 6 | 4,264 | 73.87 ± 0.67 | 5.44 |
| 7 | 117 | 57.26 ± 4.57 | 15.38 |

**Then subtract each instrument-and-interval's own mean and the trend is gone.** Not weakened -
gone, and not ordered:

| passes | rows | demeaned lift, points | sigma |
| --: | --: | --: | --: |
| 1 | 32,512 | -0.19 ± 0.26 | -0.7 |
| 2 | 17,016 | +0.24 ± 0.35 | +0.7 |
| 3 | 14,106 | -0.08 ± 0.38 | -0.2 |
| 4 | 11,153 | -0.11 ± 0.42 | -0.3 |
| 5 | 8,128 | +0.21 ± 0.49 | +0.4 |
| 6 | 4,264 | +1.03 ± 0.66 | +1.6 |
| 7 | 117 | -12.94 ± 4.36 | -3.0 |

The composition that did the work is visible in the same rows. The synthetics are 15.1% of the
one-pass population and 4.2% of the six-pass one, so pass count partly *is* which instrument the
level sits on. And `experience` - how much history the level has - rises monotonically with the
count, 0.245 at one pass to 0.727 at six, while the reject rate rises with experience on its own
(67.03%, 66.45%, 71.42% by tercile). **Pass count is a proxy for how old the level is and what it
is on, and both of those are already published separately.** Inside an experience tercile no
ordering survives.

It is not confluence in disguise either: `drawn_by_n` correlates with `confluence_n` at r = 0.15,
and the median `confluence_n` is 0 at every count.

So the hope written beside the setting - *"a pass that is useless alone can still carry
information about a price something else already drew"* - is now measured, and **as a count it is
false**. Filed as the nineteenth entry in [inert.md](inert.md).

Two details worth keeping. The seven-pass cell is not noise and not a seventh of anything: with
seven formation passes configured in production, a seven-pass level contains **every** pass, so
it necessarily contains `gap` - which is the next section, and the whole of that cell's -12.9
points. And pivot-only levels record a `break` rate of exactly zero across 23,003 rows, which is
either a different resolution path or a producer that never writes one, and is not explained here.

## The effect that survived: `gap`

Asking the same question of pass *identity* rather than pass count:

| pass | rows | reject % |
| --- | --: | --: |
| `equal` | 27,445 | 72.12 ± 0.27 |
| `origin` | 16,737 | 70.93 ± 0.35 |
| `pip` | 43,677 | 70.12 ± 0.22 |
| `profile` | 35,682 | 69.23 ± 0.24 |
| `run` | 48,586 | 69.21 ± 0.21 |
| `round` | 47,219 | 68.58 ± 0.21 |
| **`gap`** | **1,171** | **56.62 ± 1.45** |

Six passes inside 3.5 points of each other, and one twelve points below the nearest. Demeaned on
instrument x interval x experience tercile - the three confounds that killed the count - it is
**-7.39 ± 1.39 points, -5.3 sigma**, against **+0.08 ± 0.14** for every level without a gap in it.

None of the ordinary explanations holds:

* **Not youth.** Gap-drawn levels are slightly *older*: mean experience 0.521 against 0.475.
* **Not thin agreement.** They are the *most* agreed levels in the book: mean 3.81 formation
  passes against 1.98, and they are spread across every count from one to seven.
* **Not one instrument or one side.** The sign is the same in all six testable count strata
  (-3.99 to -11.69 points) and on both sides of price (57.55% above, 55.54% below).
* **Not the metric.** Breaks go the same way, 11.02% against 6.91%.

What they do instead of holding is specific, and it is not simply failing:

| | gap % | rest % |
| --- | --: | --: |
| `reject` | 56.62 | 68.43 |
| `trap` | 20.24 | 18.88 |
| `backcheck` | **11.19** | 5.28 |
| `break` | **11.02** | 6.91 |
| `chop` | 0.94 | 0.50 |

**Backcheck roughly doubles and so do breaks, while traps barely move.** A gap-drawn level is
not a level price pokes through and returns from - that is what `trap` counts, and it is flat.
It is a level price goes *through* and then comes back to later.

### A lead, not a result: where it is worst

Post-hoc, so this is a direction to test and not a finding:

| feed | gap rows | gap reject % | rest rows | rest reject % |
| --- | --: | --: | --: | --: |
| us30 | 184 | 45.7 | 1,851 | 70.8 |
| ger40 | 58 | 39.7 | 2,155 | 66.5 |
| crash_300_index | 140 | 55.0 | 606 | 51.7 |
| usdcnh | 110 | 73.6 | 5,091 | 73.5 |
| boom_1000_index | 49 | 38.8 | 259 | 44.4 |
| crash_1000_index | 47 | 57.4 | 333 | 62.5 |

The index CFDs carry it; usdcnh is flat; on the boom/crash synthetics gap levels are near their
own already-poor baseline. A gap on an instrument that gaps for structural reasons may not be the
same object as a gap on one that does not.

## What it does not establish

**That `gap` makes a level worse.** It is observational, and the alternative reading is at least
as plausible: gaps form in one-sided, trending, freshly-displaced areas, and those are exactly
the places a level should be expected to fail. On that reading `gap` is an accurate *marker* of
bad locations rather than a cause of them - which is just as useful as a filter and means
something completely different for the formation.

The sample is also modest: 1,171 gap-drawn outcomes over ten days, against 109,128 without. The
-5.3 sigma pooled figure is the defensible number; every split of it is a lead.

## Why it matters more than it looks

[`imbalance.md`](imbalance.md) measured fair value gaps as levels and found the **edge** at first
touch worth 50.2% against a 49.6% placebo - a real but unpayable +0.6 points on a 51.5%
breakeven. Production's `gaps.points` does not emit the edge. **It emits the midpoint**, and
argues for it in the module: *"picking an edge would be picking which end of a band to believe"*.

So the two results are about different prices, and this one says the price production actually
draws is the bad one. That turns edge-versus-midpoint from a tidiness question into the
substantive follow-up, and [`zones.py`](../ideas/zones.py)'s `ZONES=fvg` mode already builds its
zones far-edge-to-near-edge, which is the machinery to settle it.

It also inverts the reason `gap` is kept. The argument for keeping an unproven pass in
`DEFAULT_FORMATION` is that a pass can be worthless as a *source* and still informative as a
*vote* - which is how `profile` survives failing [shelves.md](shelves.md). That argument now has
a measurement behind it for `gap`, and **the vote has a negative sign**: "gap drew this" is a
reason to trust the level about seven points less. Useful, and the opposite of what was hoped.

## Reproducing it

The extraction runs on production and must stay cheap - two cores, and a desk on them. One
bounded sequential pass at `nice -n 19` over the last 600,000 journal rows, parsing only
`kind='outcome'`, writing fourteen columns to a gzipped CSV (110,299 rows, 2.8MB, 35 seconds).
Everything after that is local. The analysis is three scripts: the pooled and demeaned tables,
the experience control, and the gap controls.

The demeaning is the whole method and is worth stating plainly: subtract the mean of the
`feed@interval` cell - and then of `feed@interval|experience-tercile` - from each row's outcome,
and report the residual. Any effect that is really composition disappears; anything left is
within-cell. The pooled table above is what not doing that looks like.
