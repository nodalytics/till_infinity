# Does a stop anchored at a level's floor beat a fixed volatility stop?

**Measured 2026-11-03, pre-registered.** `strategies/surprise.py` computes
`risk = stop_vol * unit` and never reads the level book.
`indicators/grouping.py` gained `Anchor.FLOOR`/`CEILING`/`SIDED` and
`Group.price(anchor, side=)` this session for the opposite rule - put the stop
beyond the nearest cluster's *extreme*, so the level has to break before the
stop is reached - and that primitive has **no caller anywhere**. This decides
whether it should get one.

Harness: [`research/ideas/stop_anchor.py`](../ideas/stop_anchor.py) and
[`stop_anchor_book.py`](../ideas/stop_anchor_book.py), tests in
[`test_stop_anchor.py`](../ideas/test_stop_anchor.py).

**The answer is no, and nothing was wired.** The anchor cannot move a stop far
enough to matter: the nearest cluster holds a median of **2 touches** spanning
**0.028 to 0.105 volatility units**, so choosing its floor over its centre
changes the stop by **1.4% to 5.3%** of a 2-unit stop. Over 140 cells on 14
feed-intervals, **0 instruments** beat the distance-matched placebo on both
sides on either statistic, and the surrogates manufacture a larger
floor-over-placebo advantage than the real market shows.

## Verdict

| question | answer | kind |
|---|---|---|
| Is the nearest level's floor a *wider* stop than the incumbent, as the premise assumes? | **No - it is four to five times tighter.** The nearest cluster's floor sits **0.427 volatility units** below the close (eurusd 1d median) against `SurpriseProfile.stop_vol` of 2.0. Anchoring there is a cost change, not a width change | mechanic |
| How much can the anchor move a stop at all? | **0.028 to 0.105 volatility units**, the floor-to-centre span, on all 14 feed-intervals. The nearest group has a median of **2 touches**, so the "weighted mean inside the body of touches" argument is at its weakest case | mechanic |
| Does `floor` beat the distance-matched placebo? | **No. 4 of 28 cells** beat their hardest surrogate draw on R where 12 draws give **2.2** by chance, and **0 of 14 instruments** on both sides. The stop-out rate points the predicted way on both sides on **3 of 14** feeds against **3.5** by chance | null |
| Does `floor` beat `centre` - is the anchor the finding? | **No. 2 of 28 cells**, **0 instruments on both sides.** On the catalogue the centre is marginally *better*: -0.382R against the floor's -0.390R | null |
| Does `floor` beat `mirror` - the far-side level? | **No. 4 of 28, 1 instrument on both sides** | null |
| Can `floor` be compared with the incumbent at matched width? | **No, and that is worth stating. 0 of 28 cells** share a single quarter-unit width stratum with `vol-2`. The level book and a 2-unit stop are different widths everywhere, so only the placebo can decide | mechanic |
| What does the nearest-level stop cost? | **0.108R pooled and 0.169-0.198R on btc, eurusd and gbpusd**, against the baseline's 0.050R. The desk's own measured limit is `MAX_SPREAD_RISK_FRACTION` **0.16 of the risk**, so this arm is outside the cost envelope on three of six feeds | cost |
| Does the harness reproduce a known number? | **Yes, exactly, per instrument.** The rule's own ATR/N20 stop reads **-0.533R on n 75**, day-block [-0.830, -0.237], and btc -0.207 / eurusd -0.311 / gbpusd -0.336 / gold -1.196 / spx500 -1.475 / us100 -0.126 - every figure identical to [`smc-bos-reconcile.md`](smc-bos-reconcile.md) | mechanic |
| Where does the test go blind? | **Very high, and asymmetrically.** A barrier that reflects the **close** path is invisible at *every* strength up to a hard wall. One that price may not **print** through is visible only at strength **1.00** (dP -0.043/-0.053 both sides) and reads nothing at 0.75 | power |
| Does `indicators.Levels` support the primitive at all? | **No.** It keeps a Kalman posterior per level and discards the touch prices, so no floor or ceiling can be recovered from it. A production wiring would have to change that first | mechanic |
| Does `Anchor.SIDED` name the price the claim needs? | **On 51-64% of anchors only.** It is keyed on the level's *formed* side, not the trade's, so it hands a long the group's ceiling - a price above the entry - on a third to a half of them | mechanic |

## The claim, and the arithmetic it rests on

A support cluster's weighted mean sits inside the body of touches, so a stop
below the mean is still above the lowest touch. Four touches at
99.80/99.95/100.00/100.02 weighted 1,3,4,2 give a centre of **99.969** against
a floor of **99.800**, and two of the four touches sit under the centre. That
much is arithmetic, is not in dispute, and is asserted through `Group.price` in
`test_a_clusters_floor_is_outside_its_touches_and_its_centre_is_inside`.

What is in dispute is whether the distinction buys anything. Two ways it can
look as though it does while carrying no level information at all:

* **width.** A floor is further from price than a centre by the group's span,
  so a floor-anchored stop is a *wider* stop, and on a time exit a wider stop
  is hit less often for purely geometric reasons -
  `a-return-rate-is-geometry`, where a distance-matched placebo reproduced an
  82% return rate on every class and a walk reads 0.825. So the deciding arm is
  `matched`: the floor arm's own distances, in volatility units, **permuted
  across anchors**. Same width distribution, no pairing with any level.
* **consulting a book at all.** If `floor` beats `vol` and `centre` beats `vol`
  by the same amount, the gain is from reading levels and not from the anchor,
  and the anchor is not the finding. `centre` reads the **same group** under
  `Anchor.CENTRE`, so the two arms differ in one argument to one call.

## The prior, written down before the run

Poor. [`level-shield.md`](level-shield.md) measured the parent claim and it is
null: of 210 mirror cells asking whether a level in the path suppresses the
move, **1** beat its hardest null arm at z > +2 where chance gives about 2, and
real sat *below* the hardest null in **188**. "The level has to break first" is
the same mechanism read at a shorter range, so a null was the expected result
and a clean null is the one this desk values.

## The rules, as frozen before the run

**The arms.** All on the same anchors, the same bar path, the same forward
window and the same clock; only the stop *distance* differs.

| arm | the stop |
|---|---|
| `vol-k` | `k * unit` from the entry, `k` in 1.0, 1.5, 2.0, 2.5, 3.0, 4.0. The incumbent's form; `SurpriseProfile.stop_vol` is 2.0 |
| `floor+b` | the chosen cluster's extreme on the **trade's** side, `b` volatility units further out |
| `centre+b` | the **same** cluster under `Anchor.CENTRE`, same buffer |
| `matched+b` | `floor+b`'s own distances in volatility units, permuted across anchors - the arm that decides |
| `mirror+b` | the cluster on the **far** side of the entry, its distance placed on the trade's side - same book, same construction, no level in the stop's path |

Buffers 0.0, 0.25, 0.5, 1.0, swept rather than chosen
(`sweep-thresholds-on-the-mean-not-z`, so the whole grid is reported).

**Two books, because the claim has two readings and they are different rules.**
`near` is the nearest cluster each side of the close. `beyond` is the nearest
whose own extreme clears `MIN_VOL` = 2.0 volatility units, which is
`SurpriseProfile.stop_vol`. The second exists because of a mechanic measured
before anything else: see the first results table.

**The book.** `grouping.cluster` over confirmed `trend.pivots` at `REACH` 3,
width `WIDTH_VOL` 0.35 volatility units, `KEEP` 24 levels nearest price,
`FORGET_BARS` 500. Each pivot is one touch of weight one, so a weighted mean is
the mean of the touch prices: a level's evidence is how many *independent*
turns agree (`a-magnet-is-a-shared-reference`). The volatility unit is a causal
EWMA of the bar **range** (`drive-q-from-the-range`), asserted equal to
`level_shield.units` so the two studies measure distances in one unit.

**`indicators.Levels` could not be used, and that is a finding.** It keeps a
Kalman posterior per level and **discards the touch prices**, so no floor or
ceiling can be recovered from it. Any production wiring of `Anchor.FLOOR` has
to change that first.

**The exit.** No target, time exit at the interval's horizon (20 bars at 1d, 48
at 15m). **This is the only exit rule on which the stop width can matter at
all**: with a target at `target_r * risk` the width cancels out of R exactly -
the race is 1/(1+target_r) whatever the stop - so a stop-width question posed
against a risk-scaled target is answering nothing. A stop fills at the stop, so
a stop-out is exactly -1R.

**Entry-agnostic.** Every bar past warm-up is an anchor, on both sides, with no
signal. A stop rule is not a function of the entry signal, so dropping the
signal costs nothing the question needs and buys 19.2-19.9 years of daily
history against the 75 trades the recorded rule gives.

**The prediction, fixed before the run.** A barrier means the floor arm is
**stopped less often than `matched` at the same width**, on **both** sides,
with the sign stable across intervals. One sign long and the other short is a
drift or a book-geometry effect, not a barrier -
[`level-shield.md`](level-shield.md)'s dose arm died on exactly that. A finding
needs the real contrast outside its hardest surrogate arm's draws and survival
of Benjamini-Hochberg over every cell.

**What decides, and what only describes.** The verdict is **mean R with its
block-bootstrap interval**, the **profit factor** (the same event, since
`mean_r > 0` is `pf > 1`) and **DSR** over the trial count. A **win rate
decides nothing and a fall in it is not a cost**: a wider stop lowers the win
rate and raises the payoff, and a rule at 50% on 1:1 and one at 25% on 4:1 have
the same expectancy. The win rate, mean win and mean loss are reported so the
shape of the trade-off is visible, and never as a verdict.

**What the trade-off does cost is sample.** The observations needed for a given
confidence scale with the variance, so an arm that widens the payoff
distribution needs *more* evidence than the incumbent, not the same amount.
Every arm therefore carries its own `sd`, its own `n_eff` - the independent
observations the overlap between forward windows leaves, `(sd/se)**2` against
the block-bootstrap se - and `n_needed`, the sample at which **that arm's own**
mean would be two of **its own** standard errors from zero. Two arms with
different sd are never compared as though their means were equally well
measured.

## The nulls

Every arm runs through the same book, the same clustering and the same race on
three surrogate series as well as the real one
(`null-structure-claims-on-the-same-detector`), four draws each. The arms are
[`level_shield.py`](../ideas/level_shield.py)'s, imported rather than rewritten
so the two studies cannot disagree about what an arm is:

| arm | keeps | removes |
|---|---|---|
| `garch-bars` | volatility clustering, fat tails, bar wickiness | path structure |
| `walk-geometry` | bar wickiness, the step distribution | path structure **and** clustering |
| `bar-shuffle` | each bar's own shape, the marginal step distribution | all memory |

`garch-bars` is not optional. A level below price is a price price has recently
turned at, so "a level is 2 units away" is a statement about the recent path,
and clustering is the mechanical route by which that predicts a smaller forward
excursion. An arm without it cannot judge the claim.

**The criterion is the hardest draw, not the z.** Each z's standard deviation
comes from 12 surrogate draws, so every p derived from it is far too small and
the Benjamini-Hochberg table inherits that. What the z's are for is ranking
cells; what passes a cell is exceeding its own hardest draw.

**And never against a closed form.** [`level-shield.md`](level-shield.md)
measured a bar-extreme barrier race departing from 1/(1+N) by -0.25 to +0.12R,
monotone in (stop distance - target distance), with **every surrogate doing it
three to seven times harder** - up to 54% of R on a GARCH surrogate. A
wide-stop arm judged against the analytic 1/(1+N) inherits a spurious
advantage of 2-7% of R on real bars that has nothing to do with levels.

## The data

**Part B, the geometry panel - gross, nothing is priced.** One venue per feed,
chosen by bar count at that interval before any result was seen.

| feed | venue | bars | span |
|---|---|---|---|
| gold.1d | YAHOO | 5,009 | 19.92y |
| eurusd.1d / gbpusd.1d | FOREXCOM | 5,002 | 19.24y / 19.25y |
| usdjpy.1d / usdchf.1d | FOREXCOM | 5,000 | 19.21y / 19.23y |
| usdcad.1d / audusd.1d / nzdusd.1d | FOREXCOM | 5,000 | 19.31y / 19.23y / 19.23y |
| eurusd.15m / gbpusd.15m | FOREXCOM | 5,136 | 0.21y |
| gold.15m | FOREXCOM | 5,428 | 0.24y |
| btc.15m | BINANCE | 5,538 | 0.17y |
| us100.15m / spx500.15m | CAPITALCOM | 5,132 | 0.21y |

**These are not the catalogue's venues and the difference is deliberate.** The
panel picks the venue with the most bars at that interval, a data-volume rule
fixed before any result and the one [`level_shield.py`](../ideas/level_shield.py)
uses; the catalogue picks the venue whose recorded **quotes** support a measured
spread. So gold, btc, us100 and spx500 appear at different venues in the two
halves. That is sound only because the panel prices nothing: a bar is a bar,
and no figure in the panel is in money.

**Part A, the recorded catalogue - net of the modelled spread.** The six feeds
of `node/corpus.py`, one modelled quote per bar at the measured median spread
for that feed **on that venue**. **us100 (FOREXCOM) and spx500 (PEPPERSTONE)
are not the venue the live desk trades**, and the same instrument's recorded
spread runs 0.17 to 3.30 bps across venues, so both rows are statements about
that venue's cost. The eleven other feeds have two or fewer recorded quotes
anywhere and are skipped rather than priced off a guess.

The 1d panel is **gross and is a different rule**: the swing reach, the
volatility unit and the hold all scale with the bar, so it is named separately
throughout and never presented as the same thing as the 15m run.

## What came back

### The mechanic that decides it before any null

The anchor can only move a stop by the distance between a group's extreme and
its weighted mean. Per instrument, on the shared anchor set:

| feed | anchors kept | group touches | floor-to-centre, long / short | `SIDED` names the trade's side |
|---|---|---|---|---|
| gold.1d | 0.806 | 2.0 | **0.028** / 0.040 | 0.526 / 0.606 |
| eurusd.1d | 0.796 | 2.0 | 0.083 / 0.101 | 0.569 / 0.583 |
| gbpusd.1d | 0.822 | 2.0 | 0.088 / 0.101 | 0.559 / 0.570 |
| usdjpy.1d | 0.809 | 2.0 | 0.067 / 0.091 | 0.585 / 0.598 |
| usdchf.1d | 0.834 | 2.0 | 0.087 / **0.105** | 0.622 / **0.512** |
| eurusd.15m | 0.810 | 2.0 | 0.089 / 0.101 | 0.531 / 0.574 |
| gbpusd.15m | 0.809 | 2.0 | 0.068 / 0.091 | 0.534 / 0.635 |
| gold.15m | 0.806 | 2.0 | 0.064 / 0.084 | 0.536 / 0.587 |
| btc.15m | 0.856 | 2.0 | 0.067 / 0.090 | 0.553 / 0.583 |
| us100.15m | 0.787 | 2.0 | 0.060 / 0.089 | 0.608 / 0.542 |
| spx500.15m | 0.783 | 2.0 | 0.081 / 0.097 | 0.588 / 0.559 |

**The median group has two touches.** With two, the centre is their midpoint
and the floor is half the span away, which is the weakest case the "the mean
sits inside the body of touches" argument has: the worked example's four
touches weighted 1,3,4,2 are not what a causal book at `REACH` 3 and
`WIDTH_VOL` 0.35 actually holds. So the anchor moves a 2-unit stop by **1.4%
to 5.3%**, and no result below could have been large.

**And the premise about width is false in the opposite direction.** The nearest
cluster's floor is **0.427** volatility units below the close on eurusd 1d
against the incumbent's 2.0, so the `near` arms are a stop four to five times
*tighter*. `cost_px / risk` rises in proportion, which is the Part A table.
The first cluster whose floor clears 2.0 units sits at **2.322**, which is why
the `beyond` book exists and is reported as the comparable reading.

### The arms, entry-agnostic: eurusd 1d as the worked cell

19.24 years, 3,980 anchors per side. **Gross.** The verdict columns are
R/anchor with its block-bootstrap se, PF and DSR; the rest describe the shape
of the trade-off.

| arm, long | width (v) | P(stop) | R/anchor | se | sd | PF | DSR | win | mean win | mean loss | n_eff | n for 2σ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `vol-2` | 2.000 | 0.479 | -0.0064 | 0.0672 | 1.209 | 0.988 | 0.057 | 0.418 | +1.222 | -0.889 | 323 | 144,212 |
| `near-floor+0.25` | 0.652 | 0.786 | +0.0208 | 0.1031 | **2.557** | 1.026 | 0.228 | **0.200** | **+4.054** | -0.989 | 615 | 60,174 |
| `near-centre+0.25` | 0.566 | 0.805 | +0.0301 | 0.1092 | 2.794 | 1.037 | 0.281 | 0.182 | +4.604 | -0.990 | 654 | 34,432 |
| `beyond-floor+0.25` | 2.560 | 0.343 | -0.0009 | 0.0580 | 0.987 | 0.998 | 0.096 | 0.463 | +0.893 | -0.772 | 289 | 4,584,557 |
| `beyond-centre+0.25` | 2.471 | 0.358 | -0.0000 | 0.0591 | 1.012 | 1.000 | 0.106 | 0.459 | +0.927 | -0.785 | 293 | 1.4e11 |
| `beyond-matched+0.25` | 2.560 | 0.356 | -0.0104 | 0.0576 | 0.994 | 0.976 | 0.029 | 0.457 | +0.906 | -0.782 | 298 | 36,776 |

**The trade-off is exactly as the arithmetic predicts and decides nothing.**
`near-floor` wins 20% of anchors at +4.05R a win against `beyond-floor`'s 46%
at +0.89R - a different rule with the same expectancy, which is why the win
rate is not read as a cost. What it *does* cost is sample: `near-floor` carries
a per-trade sd of **2.557** against `beyond-floor`'s 0.987, so its own mean
needs 6.6x the observations for the same confidence.

**No arm's mean is measurable here, the incumbent's included.** `n for 2σ` is
each arm's own `(2 sd / mean)**2` in effective observations, and 19.2 years of
daily bars supplies 240-660 of them after the overlap between forward windows
is paid for. The shortfall runs from 50x to eleven orders of magnitude. That is
the honest headline on R: **this is not a close call that more feeds would
settle.**

### The contrast that decides, per instrument

`beyond-floor+0.25` minus `beyond-matched+0.25`, standardised on the stop's own
quarter-unit width stratum, against the hardest of 12 surrogate draws. `hard`
is the criterion; **a cell passes only by exceeding it, and an instrument only
by passing on both sides.**

| feed | side | dR\|width | hardest null | dP(stop)\|width | hardest null |
|---|---|---|---|---|---|
| gold.1d | +1 / -1 | -0.0034 / +0.0042 | +0.0224 / +0.0236 | **+0.0050** / -0.0070 | -0.0155 / -0.0065 |
| eurusd.1d | +1 / -1 | +0.0085 / +0.0048 | +0.0141 / +0.0172 | -0.0114 / -0.0076 | -0.0114 / -0.0132 |
| gbpusd.1d | +1 / -1 | -0.0021 / -0.0009 | +0.0062 / +0.0109 | **+0.0015** / **+0.0037** | -0.0087 / -0.0073 |
| usdjpy.1d | +1 / -1 | **+0.0191** / +0.0015 | +0.0096 / +0.0147 | -0.0045 / -0.0032 | -0.0092 / -0.0111 |
| usdchf.1d | +1 / -1 | -0.0103 / **+0.0093** | +0.0237 / +0.0076 | **+0.0147** / -0.0072 | -0.0097 / -0.0076 |
| usdcad.1d | +1 / -1 | +0.0071 / -0.0131 | +0.0075 / +0.0155 | -0.0093 / **+0.0072** | -0.0079 / -0.0123 |
| audusd.1d | +1 / -1 | -0.0103 / -0.0020 | +0.0070 / +0.0252 | **+0.0110** / +0.0000 | -0.0091 / -0.0140 |
| nzdusd.1d | +1 / -1 | -0.0097 / -0.0014 | +0.0163 / +0.0210 | **+0.0097** / **+0.0051** | -0.0106 / -0.0169 |
| eurusd.15m | +1 / -1 | **+0.0282** / -0.0056 | +0.0263 / +0.0328 | -0.0102 / **+0.0068** | -0.0104 / -0.0136 |
| gbpusd.15m | +1 / -1 | -0.0288 / +0.0168 | +0.0181 / +0.0210 | **+0.0148** / -0.0041 | -0.0109 / -0.0139 |
| gold.15m | +1 / -1 | +0.0247 / +0.0020 | +0.0267 / +0.0126 | -0.0067 / **+0.0073** | -0.0110 / -0.0080 |
| btc.15m | +1 / -1 | +0.0264 / **+0.0213** | +0.0478 / +0.0187 | -0.0023 / -0.0102 | -0.0112 / -0.0092 |
| us100.15m | +1 / -1 | +0.0081 / -0.0099 | +0.0222 / +0.0223 | -0.0050 / **+0.0118** | -0.0050 / -0.0130 |
| spx500.15m | +1 / -1 | -0.0074 / -0.0053 | +0.0196 / +0.0204 | **+0.0106** / -0.0015 | -0.0071 / -0.0146 |

**4 of 28 cells** exceed their hardest draw on R, where 12 draws give 2.2 by
chance, and **0 of 14 instruments do so on both sides**: usdjpy passes long and
fails short, usdchf short and fails long, eurusd.15m long, btc.15m short. The
sign is not stable across intervals either - gold is -0.0034 long at 1d and
+0.0247 at 15m, and eurusd is +0.0048 short at 1d and -0.0056 at 15m.

**The stop-out rate is the pre-registered statistic and it is the cleaner
null.** The predicted sign on *both* sides appears on **3 of 14** feeds against
**3.5** by chance, and the bolded wrong-sign entries are the tell: a barrier is
a property of the path, so it cannot be present long and reversed short.
[`level-shield.md`](level-shield.md)'s dose arm died on exactly this, and it
has reproduced at a shorter range.

**The surrogates are the calibration worth keeping.** The hardest null arms
produce a floor-over-placebo advantage of **+0.006 to +0.048R an anchor** with
no levels in them whatsoever - larger than all but four of the 28 real
readings. A floor-anchored stop looks better than a width-matched one on bar
geometry alone, which is `a-return-rate-is-geometry` arriving in a new place.

### Across every contrast and every cell

| contrast | cells | beats hardest, dR | on both sides | beats hardest, dP | on both sides | dP predicted sign on both sides |
|---|---|---|---|---|---|---|
| `beyond-floor` - `beyond-matched` | 28 | 4 | **0** | 3 | **0** | 3 of 14 |
| `beyond-floor` - `beyond-centre` | 28 | 2 | **0** | 1 | **0** | 5 of 14 |
| `beyond-floor` - `beyond-mirror` | 28 | 4 | 1 | 3 | **0** | 3 of 14 |
| `near-floor` - `near-matched` | 28 | 4 | **0** | 2 | **0** | 3 of 14 |
| `near-floor` - `near-centre` | 28 | 2 | **0** | 4 | 1 | 11 of 14 |
| `beyond-floor` - `vol-2` | **0** | - | - | - | - | - |

Chance is 2.2 cells per row. Over the whole panel of 140 cells, **16 beat their
hardest draw on R against 10.8 expected and 14 on the stop-out rate against the
same 10.8**; one cell survives Benjamini-Hochberg on R
(`spx500.15m near-floor - near-matched`, q 0.0010) and none on the stop-out
rate. The q values are reported but should not be read: each z's standard
deviation comes from 12 draws, so every p is too small.

**The one row that looks like a finding is the one that is pure width.**
`near-floor` is stopped less often than `near-centre` in the predicted
direction on both sides on **11 of 14** feeds - and it is 14% wider (0.652
against 0.566 units) on a stop so tight that 79-81% of anchors are stopped.
Only 4 of 28 of those cells beat their own surrogate, and 1 on both sides, so
the surrogates caught it.

**`beyond-floor` against `vol-2` produced no comparable cell at all.** The two
arms do not share a single quarter-unit width stratum on any feed, so the
standardised contrast is undefined and the raw difference (+0.0054 / -0.0008 on
eurusd 1d, se 0.0144 / 0.0168) is a comparison of two different stop widths.
This is the reason the placebo exists: without it there is no way to ask the
question at all.

## Power: where the test goes blind, and an asymmetry worth keeping

A walk with eurusd 15m's bar geometry whose own cluster book reflects it at
every group edge, swept over strength, two plants and two draws each. The
recovered quantity is the same `beyond-floor` minus `beyond-matched` contrast.

| planted strength | `close` plant, dP\|width long / short | `print` plant, dP\|width long / short |
|---|---|---|
| 0.00 | -0.0018 / -0.0027 | -0.0018 / -0.0027 |
| 0.10 | -0.0052 / +0.0076 | -0.0069 / +0.0062 |
| 0.25 | +0.0071 / -0.0016 | +0.0030 / -0.0002 |
| 0.50 | +0.0113 / -0.0005 | -0.0004 / +0.0090 |
| 0.75 | +0.0031 / +0.0036 | -0.0068 / +0.0064 |
| **1.00** | -0.0061 / +0.0052 | **-0.0428 / -0.0525** |

**At strength 0 the test correctly reads nothing** (-0.002), which is the
control an estimator manufacturing a result out of estimation error would have
failed.

**A barrier that reflects the close path is invisible to a stop at every
strength, including a hard wall.** That is not a weakness of the harness, it is
the mechanism: a stop is hit by the bar's *extreme*, and the `close` plant
leaves each bar's own resampled range either side of a close that never crossed
the wall. With the nearest cluster 0.43 volatility units away and a median bar
range near one unit, the wick is more than twice the distance to the level. So
**"the level holds" and "the level protects a stop" are different claims, and
only the second one is about a stop.**

**The second claim is visible, but only at an absolute wall.** The `print`
plant - price may not print through a level - recovers -0.043 and -0.053 on
both sides at strength 1.00 and reads nothing at 0.75. **The test therefore
goes blind between 0.75 and 1.00**, which is a very high bar, and the null
above is only a statement about barriers that hold essentially every print.
The real readings are ±0.01 against a hard wall's -0.05, so the honest upper
bound is that any barrier here holds **well under three prints in four** - and
that is not a quantity worth a parameter.

## Part A: the recorded catalogue, net of the modelled spread

`smc_bos_c_L50|M15|N20|time`'s own signals, entries, one-position slot, 96-bar
clock and sizing, with only the stop distance replaced.

**Read this for the cost and the mechanics and for nothing else.** 73-79 trades
at a per-trade sd of 1.3-2.1R is a standard error of 0.156-0.239R, so no
difference between arms here is measurable; the baseline's *own* loss is,
because it is six times larger than its standard error.

| arm | n | R/trade | day-block | stopped | clocked | win | cost in R | sd | PF |
|---|---|---|---|---|---|---|---|---|---|
| ATR/N20 (the rule) | 75 | **-0.533** ±0.196 | [-0.830, -0.237] | 55 | 20 | 0.19 | 0.050 | 1.697 | - |
| `vol-2` | 76 | -0.637 ±0.174 | [-0.878, -0.370] | 64 | 12 | 0.16 | 0.055 | 1.521 | 0.365 |
| `near-floor+0.25` | 79 | **-0.863** ±0.226 | [-1.220, -0.499] | 72 | 7 | 0.09 | **0.108** | 2.004 | 0.308 |
| `near-centre+0.25` | 79 | **-0.943** ±0.239 | [-1.335, -0.558] | 73 | 6 | 0.08 | **0.120** | 2.125 | 0.288 |
| `beyond-floor+0.25` | 73 | -0.390 ±0.156 | [-0.578, -0.166] | 52 | 21 | 0.29 | 0.043 | 1.336 | 0.504 |
| `beyond-centre+0.25` | 73 | -0.382 ±0.161 | [-0.576, -0.155] | 52 | 21 | 0.29 | 0.046 | 1.373 | 0.518 |
| **`beyond-matched+0.25`** | 73 | **-0.350** ±0.163 | [-0.560, -0.133] | 50 | 23 | 0.30 | 0.036 | 1.389 | **0.553** |

**The placebo is the best arm on all three verdict statistics** - R, profit
factor and cost - and the centre beats the floor. Every arm loses.

The baseline row's sd is derived from its own standard error (`0.196 * sqrt(75)`)
and its profit factor is blank, because the machinery check is printed by
`smc_bos_c_catalogue.describe` and does not pass through the metric block the
arms do. Its R, interval and exit mix are the point of that row.

**The arms are not on the same trade set and that is a real caveat.** n runs
73-79 because the stop width changes how fast the one-position slot frees up: a
tighter stop is stopped sooner, so more breaks get taken. The catalogue
comparison is therefore unpaired, which is the second reason the entry-agnostic
panel is the one that decides.

### The cost, per instrument - the one thing this catalogue settles

`cost_px / risk`, set by the stop and by nothing else.

| arm | POOLED | btc | eurusd | gbpusd | gold | spx500* | us100* |
|---|---|---|---|---|---|---|---|
| ATR/N20 | 0.050 | 0.050 | 0.050 | 0.050 | 0.016 | 0.029 | 0.042 |
| `vol-2` | 0.055 | 0.057 | 0.124 | 0.084 | 0.010 | 0.021 | 0.025 |
| `near-floor+0.25` | **0.108** | **0.169** | **0.198** | **0.186** | 0.030 | 0.054 | 0.070 |
| `near-centre+0.25` | **0.120** | **0.186** | **0.198** | **0.195** | 0.034 | 0.057 | 0.075 |
| `beyond-floor+0.25` | 0.043 | 0.044 | 0.087 | 0.060 | 0.006 | 0.016 | 0.019 |
| `beyond-matched+0.25` | 0.036 | 0.037 | 0.088 | 0.059 | 0.007 | 0.015 | 0.018 |

\* spx500 on PEPPERSTONE and us100 on FOREXCOM, **not the venue the live desk
trades**; the same instrument's recorded spread runs 0.17 to 3.30 bps across
venues.

**The nearest-level stop is outside the desk's own measured cost envelope on
three of six feeds.** `costs.MAX_SPREAD_RISK_FRACTION` is **0.16 of the risk**,
measured from 49 trades that passed a reward-denominated test while expensive
against risk and lost -0.471R. `near-floor` reads 0.169 on btc, 0.198 on
eurusd and 0.186 on gbpusd. So anchoring on the nearest level is not merely
unhelpful; on the tight-spread feeds it is a rule the production gate already
refuses, and `near-centre` is worse still because the centre is nearer.

**`beyond-mirror` is reported at n 20 and is not comparable.** It refused 58 of
78 signals as `no-anchor`, because a level two volatility units away on the
*wrong* side of the entry often does not exist. The mirror arm is sound in the
entry-agnostic panel, where it runs on the shared anchor set.

## What would have had to be true

For this to be wired into `Surprise.decide`, all of:

1. **A group wide enough for the anchor to matter.** The floor-to-centre span
   is 0.028-0.105 volatility units on 14 of 14 feed-intervals. It would have
   needed to be a meaningful fraction of a 2-unit stop - call it 0.3 units -
   which means groups with more than two touches and a wider `WIDTH_VOL`. That
   is a different book, and widening it is a measurement of its own.
2. **`floor` above its hardest surrogate draw on both sides of one
   instrument.** 0 of 14 instruments, on either statistic, on every contrast.
   Not one.
3. **`floor` above `centre` by more than `centre` is above `vol`.** The centre
   is marginally better on the catalogue (-0.382 against -0.390) and 2 of 28
   cells beat chance's 2.2 on the panel.
4. **A cost that clears 0.16 of the risk.** The `near` book reads 0.108-0.198R,
   and the `beyond` book only clears it by being a 2.5-unit stop - which the
   incumbent already is.
5. **A barrier holding more prints than the test's blind point.** The honest
   bound is well under three in four, and a hard wall is needed to read -0.05.

And `indicators.Levels` would have had to keep its touch prices, which it does
not. `Anchor.FLOOR`/`CEILING`/`SIDED` and `Group.price` are kept: the
arithmetic is correct, `test_grouping.py` and
`test_a_clusters_floor_is_outside_its_touches_and_its_centre_is_inside` pin it,
and a future claim about cluster edges should not have to rebuild them. They
remain without a production caller, now for a measured reason.

## What was not done, and why

* **No 1h or 4h interval.** The store holds about 0.8-1.0 years at 1h on these
  feeds and 2-6 years at 4h on the indices only. Both are affordable and
  neither was run; the two intervals here were fixed before the run as the
  longest daily history and the only costed 15-minute one.
* **No cost on the 1d panel**, and none invented. Only six feeds have enough
  recorded quotes to measure a median spread per venue, and the eight daily FX
  and gold feeds are not all among them. Geometry is sound on all of them
  because nothing is priced.
* **No overshoot charge.** A stop filled off bar extremes overshoots - a median
  +0.363R on spx500 (`smc-bos-reconcile.md`) - and the overshoot **grows with
  the distance to the barrier**, so charging it would hand the wide arm a
  width-dependent debit against a width-dependent advantage. The control for
  both is the same race on matched surrogates.
* **The Bjorgum zone was not tested.** It is the level primitive with a
  measurement behind it, and it is a different object with a width; "price
  stops inside a band" is not the claim tested here.
* **`Anchor.SIDED` was not raced.** It names the extreme by the **level's**
  formed side, so it hands a long the group's *ceiling* whenever the nearest
  group below was built mostly from pivot highs - a price above the entry,
  which is not a stop. Racing it would mean either dropping those anchors,
  biasing the shared anchor set towards supports, or folding them in as a tight
  stop, which is two rules under one name. It is reported as a rate instead.

## The code

| file | what it is |
|---|---|
| `research/ideas/stop_anchor_book.py` | the causal cluster book (`Walker`), the arms, the race, the width strata and the permuted placebo |
| `research/ideas/stop_anchor.py` | the panel, the signal-conditioned run, the planted-floor power sweep and the tables |
| `research/ideas/test_stop_anchor.py` | nine tests, run explicitly - `research/` is outside `testpaths` |

### Running it

```sh
uv run ruff check --isolated --select F821 research/ideas/stop_anchor.py \
  research/ideas/stop_anchor_book.py
uv run pytest research/ideas/test_stop_anchor.py -q
uv run python research/ideas/stop_anchor.py --all --draws 4 --out .data/out/stop_anchor
```

**One process, no pool anywhere, one core**, so it is safe to run beside other
work. Measured: a `--geometry --draws 4` pass is **about 45 minutes** (14
feed-intervals times 13 series, the clustering dominating), `--catalogue` is
**about 8 minutes** (54 engine runs: six for the machinery check, six per arm,
and a second pass per instrument for the permuted arm), and `--power --draws 2`
is **about 25 minutes** (two plants times six strengths times two draws, each
plant maintaining its own causal book bar by bar). So **`--all --draws 4` is
about 80 minutes.**

**The figures above come from two invocations rather than one**, and that is
reported rather than smoothed over: the panel is from the first `--all` pass
and the catalogue and power tables are from a second `--catalogue --power` pass
after the two bugs below were fixed. A single `--all --draws 4` is the
reproduction command and nothing in the panel was touched between them.

The `--sanity` block runs first and asserts the three things that make the rest
readable, so a changed primitive or a failed sync stops the run rather than
producing numbers (`a-failed-sync-still-launches-the-run`). `--out` takes any
directory, and `report.txt`, `geometry.json`, `catalogue.json` and `power.json`
land in it.

Parts run alone with `--geometry`, `--catalogue`, `--power` or `--sanity`.
Nothing here is parallel, so a bigger box makes it no faster - it makes it
possible to raise `--draws`, which is what the surrogate criterion wants: the
hardest-draw bar rises with the draw count and 12 draws is the weakest form of
the test reported here.

### The bugs this caught on the way

Reported rather than quietly fixed, because a study that hides its own
off-by-ones is worth less than one that does not.

* **The mirror arm's stop distance was signed, and the arm reported `n 0`
  rather than failing.** Its anchor is on the far side of the entry, so
  `(entry - anchor) * side` is negative and all 78 catalogue signals were
  refused as `no-anchor`. A zero-trade arm reads as "the book had nothing to
  say" and is indistinguishable from a sign error, which is why the engine path
  now takes the absolute value exactly as `distances` does.
* **`self.taken` shadowed `Desk.taken`.** The desk keeps an int counter of that
  name and the research subclass used it for a list, which raised on the first
  signal. It crashed rather than miscounted only because `+=` differs between
  the two types.
* **The `no-anchor` refusal count read zero on every arm.** `Desk.consider`
  keys a refusal from `decide` as `f"{label}:{gate}"`, so a lookup on a fixed
  string silently reports "the book always had an anchor".
* **The first power sweep planted the wrong barrier**, reflecting only the
  nearest group's edge where the `beyond` arms anchor on the first group past
  2.0 units - so the sweep measured the blind point of a test for an effect it
  had not planted where that test looks. `Walker.edges` plants every cluster
  edge.
* **The first width strata were half-unit bins** and the "stratified" stop-out
  contrast between `vol-2` at 2.000 and `beyond-floor+0.25` at 2.560 still read
  -0.11, because both fell in the bin [2.0, 3.0). Quarter-unit bins put them in
  different bins and the contrast correctly became undefined, with the overlap
  share printed beside every standardised number.
