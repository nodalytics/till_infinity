# The breaker block: 92.6% of order blocks flip, and the flip is a distance-matched placebo

**Measured 2026-11-10**, pre-registered as shortlist item 1 of
[`tradingview-survey.md`](tradingview-survey.md) and run to the specification
there without alteration. Code: [`breaker_blocks.py`](../ideas/breaker_blocks.py)
(detector, trades, nulls, cost, power, sweep, detector overlap),
[`breaker_report.py`](../ideas/breaker_report.py) (every table below), tests in
[`test_breaker_blocks.py`](../ideas/test_breaker_blocks.py).

**The headline is a rate, not a mean.** The published breaker reaches a 2R
target before a 1R stop on **0.2979 of 23,730 trades** where the arithmetic rate
is **0.3333** and matched walks through the same detector read 0.2866-0.3187.
Mean R is **-0.0265** [-0.0471, -0.0032] day-blocked, against a **measured round
trip of 0.0531R**. The flip beats a distance-matched prior swing with no order
block behind it by **+0.0018R** [-0.0224, +0.0290].

**And the refuted arm was kept in the run, which is what the design was for: it
does not beat its null either.** The fade to the un-flipped zone reads -0.0478
[-0.0678, -0.0264] against walks at -0.0291 to -0.0613. Neither arm clears its
null, so the small positive gap over the walks belongs to neither claim.

## Verdict

| question | answer |
|---|---|
| Does the **published breaker** pay at 2R? | **No.** 23,730 trades on 30 traded instruments at 1h, 4h and 1d: `P(>= 2R)` **0.2979** against an arithmetic 0.3333 and 0.2866 on the hardest walk; mean **-0.0265R** [-0.0471, -0.0032] gross, **-0.0795R** net of a 0.0531R round trip |
| Does it beat the **placebo** - a breaker declared at a prior swing with no order block behind it, matched on zone height and drawn one per real trade? | **No. +0.0018R** [-0.0224, +0.0290], paired on days. The zone heights match to three decimals (median 1.197 against 1.201 units), so this is the same geometry with and without an order block, and the order block adds nothing |
| Does the **refuted fade** also beat the null? | **No**, and that is the single most important column. Fade -0.0478 [-0.0678, -0.0264] against iid -0.0613, GARCH -0.0291 and the geometry walk -0.0568. Neither the flip nor the fade clears its own walk, so there is no finding to assign to either claim |
| Does **EmreKb's confirmation** - a fresh swing inside the broken band - help? | **No.** -0.0332R [-0.0744, +0.0097] on 4,513 trades, worse than the unconfirmed arm, and it applies to only **0.2591 of flips** because the zone is usually deleted first |
| Does the prior study's **+0.337R at 1d / +0.506R at 4h** reproduce? | **Not on either zone population, and the 1d cell cannot settle it.** On the published blocks: 1d -0.0096R [-0.1220, +0.1129] on 567 trades, 4h -0.0288R [-0.0717, +0.0146] on 4,573. On **the desk's own blocks** with the published flip lifecycle: 4h -0.1189R [-0.2668, +0.0335] on 328, which excludes +0.506R; 1d **-0.0667R [-0.4667, +0.3636] on 45 trades**, which excludes nothing and is reported as unmeasurable |
| Is the published order block the **same object** as this repo's? | **No, and this is why neither null transfers.** Jaccard **0.0027** over 219,000 bars on eight instruments: LuxAlgo cuts **20,133** blocks where `zones.ob_zones` cuts **1,316**, and finds 4.4% of them. Two detectors with the same name are usually two detectors |
| Is "flipped" a **selection** at all? | **Barely. 0.9264 of order blocks flip** (0.9297 on the desk's), and 0.94-0.96 of flipped zones are retested before deletion. The published polarity flip is the default outcome of an order block, not a rare event, which is the mechanical reason it carries so little information |
| Does **cost** kill it first? | **No, and the survey priced it at the wrong stop.** The breaker's own stop is the zone plus a pad - **1.14 to 1.87 ATR**, not the 3.46-3.55 ATR of a 20-bar swing - so the real cost is about **2.6x** the survey's figure: median 0.0416R at 1h, 0.0204R at 4h, 0.0085R at 1d, outside the desk's 0.16 ceiling on 2 of 27 at 1h (XAGUSD 0.2500, XCUUSD 0.3113) and 0 of 27 at 4h |
| Does **any** parameter cell pay? | **No. 0 of 432.** Twelve configurations, one parameter moved at a time, three clocks, three arms, four targets: not one cell has a lower bound above zero. The best is +0.0339 +- 0.1037 |
| Does any **instrument** pay? | **No. 0 of 68 traded cells** have a lower bound above zero and **0 of 98 survive Benjamini-Hochberg**. The only two cells with a positive lower bound are **Boom 1000 Index** and **Boom 500 Index** - the arm that must be empty |
| Where does the test go **blind**? | Below about **0.2R of planted edge** pooled (z +1.88), and it sees 0.4R at z +6.25. In realised terms 2 sigma needs 0.019R at 1h, 0.040R at 4h and **0.11R at 1d**. About a fifth of each plant is what the estimator resolves, because the median trade closes in 5 bars of a 60-bar window |
| What is the most valuable thing here? | **A leak in `node/surrogates.walk_with_bar_geometry`**, found by this harness's own leak check and worth **0.171R** on a long-entry arm. It is a shipped package function and other studies use it |

## The leak, first, because it decided which null is believable

`node/surrogates.walk_with_bar_geometry` builds a surrogate by walking the
closes on resampled steps and then placing each bar's **open inside that bar's
own range** at a resampled fraction:

```python
low = price - close_frac * span
out.append((low + open_frac * span, high, low, price))
```

The open is therefore independent of the previous close. In any market whose
bars close above their opens on average - every up-trending instrument - the
resampled `(open_frac, close_frac)` pair carries that asymmetry, so the
surrogate emits a **systematic down-gap at every open followed by an up-move
inside the bar**. A resting limit below the market is filled at the gap and
rides the rise. Measured directly on a 60,000-bar series with its close-to-close
steps demeaned:

| | |
|---|---:|
| `mean(close[i] - open[i])`, inside the bar | **+4.0e-04** |
| `mean(open[i] - close[i-1])`, across the join | **-3.9e-04** |
| `mean(close[i] - close[i-1])`, the walk itself | +3.9e-06 |

Through this harness, on the traded book:

| the long-entry arm (`fade`), on a walk | mean R at 2R | `P(>= 2R)` | n |
|---|---:|---:|---:|
| the package's construction (`legacy`) | **+0.1241** | 0.3466 | 83,295 |
| the same walk, assembled continuously (`geom`) | **-0.0468** | 0.2897 | 92,678 |
| **the correction** | **0.1709** | | |

A walk is a martingale, so +0.1241R is impossible: `a-martingale-cannot-pay`.
Two wrong explanations were tried and recorded rather than deleted:

* **Drift.** Resampling `diff(close)` i.i.d. keeps the series' realised drift,
  which looked like the cause and was not: demeaning the steps moved the number
  by **0.004R**. The drifted arm is kept as `geomdrift` anyway, and reads within
  0.002R of the demeaned one everywhere, so the market's unconditional drift
  reaches none of these arms.
* **Zone imbalance.** The sawtooth also distorts the *detector*: the legacy arm
  takes 42,154 breaker trades where the corrected one takes 102,116, a 2.4x
  difference, which was first read as a drift-driven long/short imbalance.

The fix is one line of construction - each bar **opens at the previous close**,
with the two wicks resampled as a pair and attached outside the body - and
`geom_bars` carries it. The corrected arm then agrees with the iid and GARCH
arms to within 0.007R on every arm of this study, which is the check that it is
now a walk.

**This matters outside this document.** The package function is used by
`level_shield.py` and the harnesses built on it as `walk-geometry`. Those read a
first-passage rate rather than a limit-order trade, and a two-sided
distance-matched statistic may absorb the bias; **this study did not measure
that**, and it is the obvious next thing to check. `expect-the-correction-to-be-the-size-of-the-effect`
is the standing rule and the correction here is five times the effect the arm
was being used to judge.

## The rules, as frozen before the run

Nothing below was tuned. `SWING`, `PAD`, `EXPIRE` and `HOLD` were fixed before
the first cell and the full sweep over them is reported.

| part | rule | source |
|---|---|---|
| **swing** | `pivothigh(10, 10)` / `pivotlow(10, 10)`, known 10 bars after it prints | LuxAlgo's `swing lookback 10` |
| **order block** | on `ta.crossover(close, top)` against the last known swing high, the block is the **lowest-low bar** between the swing and the crossing bar; one block per swing. The band is that bar's whole range (`body` is a sweep variant) | LuxAlgo *Order Blocks & Breaker Blocks* |
| **breaker** | the first bar after the block is known whose `min(close, open)` closes through the far edge | LuxAlgo |
| **deleted** | the first bar after the flip whose `close` clears the near edge - the top, for a flipped demand zone | LuxAlgo |
| **confirmed** | the first fresh pivot after the flip whose price lands inside the broken band, taken at the bar it is **known**, so the confirmation is charged its 10 bars of delay | EmreKb *Market Structure Break & Order Block* |
| **the trade** | **against** the zone's original direction, a resting limit at the near edge of the breaker, live from the flip until deletion or `EXPIRE` 300 bars | the survey's shortlist entry |
| **stop** | `PAD` 0.1 ATR(14) beyond the far edge; realised median **1.30-1.36 ATR** | `origin-zones.md`, `zones.py` |
| **target** | 1R, 2R, 3R, 4R; the headline is 2R | the desk's own brief |
| **hold** | 60 bars, **the same for every arm** | `CLAUDE.md`, "a stop and sixty" |
| **cost** | one round trip from the terminal's live ask minus bid, charged as `trip / stop`, never the per-bar `spread` column, which is in points | `research/harness/venue.quoted` |

Short setups are the same rules on the mirrored frame, which is the idiom
`zones.py` uses and whose absence once cost that study its entire supply side.
**Every parameter is a bar count**, so the same rule is ten hours at 1h and ten
days at 1d; the three clocks are three horizons and are never pooled.

### Settlement, and the three conservative conventions

Entries are resting limits and the fill bar is settled as
`research/mt5bt/engine.walk` settles one: the **stop counts** on the fill bar,
the **target counts only if that bar closes beyond it**, and when both legs are
reachable in one bar the **stop wins**. All three are conservative, so a walk
must read at or below zero and at or below `1/(1+N)`. It does, on every arm:

| walk | `flip` | `fade` | `placebo` |
|---|---:|---:|---:|
| iid, Student-t(3) sub-steps | -0.0400 | -0.0653 | -0.0431 |
| GARCH(1,1)-t(5) | -0.0339 | -0.0309 | -0.0375 |
| this market's geometry, continuous | -0.0347 | -0.0468 | -0.0380 |

A fourth convention is new here and drops trades: **a resting limit must sit on
the far side of the market when it is placed**. LuxAlgo's `min(close, open) <
btm` can be satisfied by an up-closing bar's open alone, which would leave the
sell limit at or below the market and make the entry a market order wearing a
limit's settlement rules. 2,029 trades at 1h were refused for it.

## The data

Fifteen-minute stores folded to 1h, 4h and 1d by **UTC timestamp bucket**, never
by index - index folding puts Friday's close in the same bar as Monday's open.
The daily bar is therefore a UTC day and not the broker's 21:00 session, which is
a different clock from the prior study's.

| store | instruments | from | to | bars at 1h / 4h / 1d |
|---|---:|---|---|---|
| deep | 8 (5 FX legs, gold, silver, BTC) | 2015-01-07 | 2026-11-05 | 572,185 / 149,193 / 28,510 |
| wide | 22 (10 indices, 2 oils, 2 metals, 2 coins, 6 FX) | 2024-06-12 | 2026-11-07 | 222,194 / 58,944 / below the floor |
| synthetic | 13 Deriv families | 2019-01-05 | 2026-11-08 | 364,918 / 91,245 / 10,520 |

Cells under 1,200 bars are not reported, which is why the wide store carries no
daily row. **Duplicate timestamps are dropped unconditionally and counted**: 44
bars at 1h and 4h, 0 at 1d. The `spx500`/`us100` daily duplication found on
2026-11-10 is in the prices store, which this study does not read; the guard is
here because a duplicate bar doubles a detector's firing rate in silence.

The Deriv synthetics are **real markets with a published generator**, and the
property they control for is narrow and named: no participant in them leaves
unfilled interest, so there is no order block to flip, while they do have levels
(`Range Break` is the level positive control) and a switching drift
(`Drift Switch`). They are never pooled with the traded book and they are not a
tail control.

## Result

### The arms, pooled over the traded book

"`P` given resolved" is `P(>= 2R)` among the trades that reached a barrier at
all; a finite hold makes `1/(1+N)` an upper bound rather than the rate, and the
conditional rate is the quantity a walk must put on 0.3333.

| arm | n | `P(>= 2R)` | `P` given resolved | mean R, day-blocked | cost | net |
|---|---:|---:|---:|---|---:|---:|
| **breaker (`flip`)** | 23,730 | **0.2979** | 0.3164 | **-0.0265** [-0.0471, -0.0032] | 0.0531 | -0.0795 |
| breaker, confirmed | 4,513 | 0.2725 | 0.3059 | -0.0332 [-0.0744, +0.0097] | 0.0462 | -0.0794 |
| **the refuted fade** | 21,982 | 0.2901 | 0.3081 | -0.0478 [-0.0678, -0.0264] | 0.0531 | -0.1009 |
| **the placebo** | 22,141 | 0.2967 | 0.3153 | -0.0283 [-0.0548, -0.0034] | 0.0491 | -0.0774 |
| arithmetic null | | **0.3333** | 0.3333 | 0.0000 | | |
| iid walk | 74,724 | 0.3166 | 0.3187 | -0.0406 | | |
| GARCH walk | 74,211 | 0.3187 | 0.3207 | -0.0343 | | |
| geometry walk | 69,083 | 0.2866 | 0.3098 | -0.0336 | | |

Every mean has its median beside it, because one row has ended a study here
before: the flip arm's median R is **-1.00**, its range is [-5.60, +11.43], and
winsorising to [-1.5, 2.5] or dropping the 234 gap exits moves the mean by
**0.0002R**. Record consistency over all 420,000 rows: 0 rows claim a target
they did not reach, 0 reach one without claiming it, 0 are unresolved without
having timed out, and 0 stops paid anything but -1R.

### The gaps, which are the finding

Paired on days, so the two arms see the same market conditions:

| | pooled | 1h | 4h | 1d |
|---|---|---|---|---|
| flip - placebo | **+0.0018** [-0.0224, +0.0290] | -0.0034 [-0.0323, +0.0260] | +0.0139 [-0.0424, +0.0655] | +0.0756 [-0.0842, +0.2353] |
| flip - fade | +0.0213 [-0.0109, +0.0533] | +0.0212 [-0.0134, +0.0545] | +0.0176 [-0.0459, +0.0784] | +0.0545 [-0.1132, +0.2159] |
| flip - geometry walk | +0.0071 +- 0.0103 | +0.0093 +- 0.0117 | +0.0042 +- 0.0236 | -0.0393 +- 0.0674 |
| **the round trip it must clear** | **0.0531** | 0.0593 | 0.0324 | 0.0165 |

The largest gap over any walk is **+0.0142R** (iid, pooled) with a standard
error of 0.0103, against a round trip of 0.0531R - so even read at face value
and ignoring that it does not clear two standard errors, it is **27% of a
spread**. That is the same shape
[`statespace-directional-edge.md`](statespace-directional-edge.md) reports for
every directional gate measured here, which earns about 2% of a spread against
the 1.0 it needs.

### Per clock, and per instrument

| clock | n | `P(>= 2R)` | mean R | fade | placebo | geometry walk | net |
|---|---:|---:|---|---:|---:|---:|---:|
| 1h | 18,590 | 0.2976 | -0.0264 [-0.0506, -0.0033] | -0.0476 | -0.0230 | -0.0357 | -0.0857 |
| 4h | 4,573 | 0.2974 | -0.0288 [-0.0717, +0.0146] | -0.0464 | -0.0427 | -0.0330 | -0.0611 |
| 1d | 567 | 0.3122 | -0.0096 [-0.1220, +0.1129] | -0.0641 | -0.0852 | +0.0297 | -0.0261 |
| Deriv, all clocks | 11,036 | 0.3243 | -0.0167 [-0.0438, +0.0122] | -0.0351 | -0.0360 | -0.0371 | -0.0364 |

By family, weighted by n: index -0.0627, fx -0.0378, deriv -0.0167, metal
-0.0015, crypto +0.0170 (n 2,475), energy +0.0440 (n 746). **Net of cost every
family is negative except energy at +0.0059 on 746 trades**, which is four cells.

Per (instrument, clock), 98 cells:

| | count |
|---|---:|
| traded cells with a nominally positive mean | 29 of 68 |
| traded cells with a day-blocked lower bound above zero | **0 of 68** |
| Deriv cells with a lower bound above zero | 2 of 30 - **Boom 1000 Index** 4h (n 50) and **Boom 500 Index** 1h (n 294) |
| cells beating the geometry walk at p < 0.05 | 2 of 98 - Boom 1000 Index 4h, and USDCHF 4h on **n 24** |
| cells surviving Benjamini-Hochberg at q 0.05 | **0 of 98** |

**The only cells that pass are in the arm that must be empty.** Boom and Crash
spike one way by construction, so a short arm on them is a different trade; this
is `a-control-is-only-for-a-named-property` and
`the-placebo-arm-selects-the-null` arriving together, and the right reading is
that the test's positives at this sample size are noise.

### Overlap, non-overlap, halves and legs

* **Non-overlapping subsample**, one live trade at a time per instrument, clock
  and arm: flip -0.0205 [-0.0445, +0.0024] on 19,748, placebo -0.0288, fade
  -0.0453. The ranking and the magnitudes survive, so the dense overlap that
  `HOLD` and `EXPIRE` create is not carrying the reading.
* **Split halves**, reported as information and not a verdict: 1h flip -0.0253
  then -0.0275, 4h -0.0333 then -0.0243, 1d +0.0538 then -0.0728. Both halves
  negative on both intraday clocks; the 1d halves straddle zero on 283 trades
  each, which is below the floor.
* **Legs.** 1h flip long -0.0078 (n 9,134), short -0.0444 (n 9,456). The
  population is 49/51, so nothing here is a standing short - the defect that
  took the first version of `order-block-zones.md` apart.
* **Deep against wide.** -0.0259 [-0.0508, -0.0019] on the eight instruments
  with 11.8 years, -0.0283 [-0.0779, +0.0202] on the twenty-two with 2.4. Adding
  22 instruments did not reverse the sign, which is the test
  `widening-the-universe` exists for.

### The sweep, in full

One parameter moved at a time from the pre-registered default - never the full
cross - over three clocks, three arms and four targets. **432 cells, 0 with a
lower bound above zero.** The flip arm at 2R:

| config | 1h | 4h | 1d |
|---|---:|---:|---:|
| pre-registered default | -0.0258 | -0.0277 | -0.0096 |
| `pad` 0.25 | -0.0157 | -0.0084 | -0.0331 |
| `pad` 0.5 | -0.0130 | -0.0129 | -0.0644 |
| `band` body | -0.0378 | -0.0435 | +0.0145 |
| `swing` 5 | -0.0307 | -0.0062 | -0.0531 |
| `swing` 20 | -0.0065 | -0.0099 | +0.0225 |
| `expire` 50 | -0.0277 | -0.0235 | -0.0022 |
| `expire` 1000 | -0.0259 | -0.0315 | -0.0146 |
| `hold` 5 | -0.0197 | +0.0004 | -0.0167 |
| `hold` 30 | -0.0217 | -0.0132 | -0.0142 |
| `hold` 120 | -0.0256 | -0.0330 | -0.0239 |
| `hold` 300 | -0.0251 | -0.0337 | -0.0225 |

The best cell anywhere is `swing` 20 at 1d and a 3R target, **+0.0339 +-
0.1037** on 269 trades. `P(>= NR)` is below `1/(1+N)` in **every** cell at every
N: the default at 1h reads 0.4621 / 0.2982 / 0.2062 / 0.1464 against 0.5000 /
0.3333 / 0.2500 / 0.2000.

## The prior study's arms, and why its number is not contradicted

[`order-block-zones.md`](order-block-zones.md)'s open positive is **+0.337R at
1d and +0.506R at 4h**. This study does not reproduce it and does not refute it
in the same object, for two reasons that have to be stated separately.

**First, the zone is a different zone.** `MODE=overlap` runs LuxAlgo's
construction and `zones.ob_zones` over the same 219,000 bars on eight
instruments:

| | LuxAlgo | the desk's rule | both |
|---|---:|---:|---:|
| order blocks cut | **20,133** | **1,316** | 58 |
| Jaccard of the block bars | | | **0.0027** |
| share of the desk's blocks LuxAlgo finds | | | **0.0441** |

Fifteen times the firing rate and almost no agreement. The desk's rule wants two
impulsive candles at a 70% body floor, an imbalance, and a break of structure
that holds three bars and travels an ATR; LuxAlgo wants a swing high, a close
through it, and the lowest low in between. `displace` and `DISPLACE_C` agreed on
a quarter of their union and were correctly kept apart; these two agree on 0.3%.

**So the desk's own blocks were run too**, with the published flip lifecycle
applied to them - which is the mechanical definition that study lacked and the
whole reason this one exists (`ZONES=desk`):

| arm, the desk's blocks | n | `P(>= 2R)` | mean R, day-blocked | cost |
|---|---:|---:|---|---:|
| **breaker (`flip`)** | 1,534 | 0.3096 | **-0.0635** [-0.1314, +0.0109] | 0.0672 |
| the refuted fade | 1,387 | 0.3273 | -0.0104 [-0.0868, +0.0664] | 0.0694 |
| the placebo | 1,414 | 0.3253 | -0.0169 [-0.0920, +0.0612] | 0.0592 |
| flip - placebo, paired | | | **-0.0466** [-0.1542, +0.0604] | |
| 1h | 1,161 | 0.3144 | -0.0477 [-0.1257, +0.0379] | 0.0740 |
| **4h** | 328 | 0.2927 | **-0.1189** [-0.2668, +0.0335] | 0.0485 |
| **1d** | **45** | 0.3111 | **-0.0667 [-0.4667, +0.3636]** | 0.0285 |

On the desk's own population the flip is **worse** than both its controls, and
0.9297 of its blocks flip too. At 4h the interval excludes +0.506R. **At 1d it
excludes nothing**: 45 trades give a half-width of 0.4R, so the 1d claim is not
refuted here - it is unmeasurable on this data, and saying so is the result. One
cell of 96 survives Benjamini-Hochberg on this population: **XAGUSD at 1d on n =
4**, which is what BH cannot protect against and what the sample floor is for.

**Second, the prior study's arms did not hold for the same number of bars.** Its
`real` arm ran at `HOLD_DAYS = 5` while `flip`, `straight` and `coin` ran at
`MAXHOLD = 300`, so at 1d the comparison moved the side, the entry style *and* a
sixty-fold holding period at once. Measured here on one rule with only the hold
changed, at 1d:

| hold | `P(>= 2R)` | `P(>= 4R)` | mean R at 2R |
|---|---:|---:|---:|
| 5 bars | 0.1129 | 0.0159 | -0.0167 |
| 60 bars | 0.3122 | 0.1411 | -0.0096 |
| 300 bars | 0.3245 | 0.1764 | -0.0225 |

The hit rate moves by **2.9x at 2R and 11.1x at 4R**; the mean moves by at most
0.065R across every clock and target. So the asymmetry is a real defect in that
study's arm construction and is **not large enough on its own** to produce
+0.337R. Every arm here holds 60 bars.

## Power, and where it goes blind

A drift of `g` R spread over the holding window is added to the forward path
**from the fill bar on**, so the detector and the fill are untouched and `g` is
exactly "the edge this trade would have to carry". Pooled over the real series,
the flip arm:

| planted edge | 0 | 0.05R | 0.1R | 0.2R | 0.4R | 0.8R |
|---|---:|---:|---:|---:|---:|---:|
| measured mean R | -0.0215 | -0.0131 | -0.0046 | +0.0154 | +0.0518 | +0.1220 |
| z | -2.64 | -1.61 | -0.56 | **+1.88** | +6.25 | +14.53 |
| `P(>= 2R)` | 0.3078 | 0.3100 | 0.3123 | 0.3184 | 0.3288 | 0.3501 |

The placebo arm's curve tracks it to within 0.004R at every strength, which is
the control working. **The test is blind below about 0.2R of planted edge** and
sees 0.4R comfortably. About **a fifth of each plant** is what the estimator
resolves, because a drift spread over 60 bars mostly has not arrived when the
median trade closes in 5 - so the blind spot in realised terms is 2 sigma, which
is 0.019R at 1h, 0.040R at 4h and **0.11R at 1d**.

Two consequences, and they point opposite ways:

* at 1h and 4h the blind spot is **below the round trip** (0.0593R and 0.0324R),
  so the test can see any edge large enough to matter, and it sees none;
* at 1d on the published blocks the half-width is 0.117R, which **does** exclude
  +0.337R - but at 1d on the desk's blocks it is 0.4R, which does not. The
  unsettled positive therefore remains unsettled in the one place it was found,
  and the reason is sample, not method.

## Cost, re-derived

`./.secrets/lab.sh run research/ideas/breaker_blocks.py MODE=cost`, the
terminal's own ask minus bid through `research/harness/venue.quoted`, 2026-11-10.
Two columns because they answer different questions: `swing20` is the survey's
geometry and reproducing it checks that this harness reads the same book;
`breaker` is **this rule's own realised stop**, the median over the trades it
actually takes.

| clock | breaker stop, ATR | `swing20` stop, ATR | breaker cost, median | range | inside 0.16 of risk |
|---|---:|---:|---:|---|---:|
| 1h | 1.27-1.87 | 3.53 | **0.0416** | 0.0082-0.3113 | 25 of 27 |
| 4h | 1.14-1.85 | 3.55 | **0.0204** | 0.0039-0.1354 | 27 of 27 |
| 1d | 1.19-1.42 | 3.46 | **0.0085** | 0.0065-0.0624 | 8 of 8 |

**The survey priced this idea at a stop 2.6x wider than the rule uses.** It
quoted `swing20` at 0.006-0.074 of risk at 15m, median 0.017, and concluded the
idea "is affordable at every clock the venue serves". That conclusion survives at
4h and 1d and fails on two instruments at 1h - XAGUSD at 0.2500 and XCUUSD at
0.3113 - because a breaker's stop is the zone plus a pad and not a 20-bar swing.
Three of the thirty traded instruments are **unpriced** (the bridge did not
answer for AUDCAD, EURCAD or BNBUSD); they are reported as geometry and carry no
cost column, never a zero.

Both numbers carry the width the survey recorded: a **single live snapshot**, and
two snapshots of the same book two days apart disagreed by 3.7x on gold. A cost
screen wants a week of quotes and does not yet have one.

## What is refuted, what is not, and what is merely unmeasurable

**Refuted.**

* The **published breaker block** as a trade, at 1h, 4h and 1d, on 30 traded
  instruments and 23,730 trades: it reaches 2R less often than the arithmetic
  rate, less often than two of three matched walks, and it is within +0.0018R of
  a distance-matched prior swing with no order block behind it.
* **The polarity flip as a source of information.** 92.6% of order blocks flip,
  so "flipped" selects almost nothing, and EmreKb's confirmation - which does
  select, applying to a quarter of flips - reads worse than no confirmation.
* **The reframing.** The rule for reopening a refuted claim is that the new
  statistic beats its null where the old one does not. Here **neither** beats
  it, so there is nothing to assign to the flip and the fade's refutation stands
  unchanged.
* On **the desk's own blocks** with the published lifecycle, the **4h** half of
  the prior study's open positive: -0.1189R [-0.2668, +0.0335] on 328 trades
  excludes +0.506R.

**Not refuted, and not supported.**

* The **1d** half of the prior study's open positive **on the desk's own
  blocks**. 45 trades, [-0.4667, +0.3636]. The sample is 3.4 times too small and
  the daily clock is a UTC day rather than the broker's session. This is the one
  cell in the study where the honest answer is *unmeasurable*, and the way to
  settle it is the frozen forward test that document already asked for - not
  another pass over the same bars.

**Unmeasurable on the data available.**

* Anything at 1d on the wide store: 2.4 years of 15m folds to about 520 daily
  bars, under the 1,200-bar floor, so the daily clock rests on eight instruments.
* The maker side. Every entry here is a resting limit charged a full round trip,
  which is what crossing from ask to bid costs; `polymarket-taker-fee` aside,
  this desk has no measured maker rebate to credit.
* Whether the `walk_with_bar_geometry` leak has moved any published number in
  `level-shield.md` or the studies downstream of it. The defect is demonstrated;
  its effect on a two-sided first-passage statistic is not.

## Caveats

* **Three clocks are three detectors.** `SWING`, `EXPIRE` and `HOLD` are bar
  counts, so the 1d rule looks back ten days where the 1h rule looks back ten
  hours. That is what the published script says and it is why no number is
  compared across clocks except by naming the horizon.
* **The placebo matches height, not staleness.** Zone heights match to 1.197
  against 1.201 units at the median with the same quartiles, but the median wait
  from the zone being known to its flip is 86 bars for the breaker and 60 for
  the placebo. A level that has stood longer is a different object, and that
  difference is unmatched.
* **The geometry walk loses the body-wick correlation.** A big body comes with
  big wicks in a real market and does not in `geom_bars`, which is why the iid
  and GARCH arms are read beside it rather than instead of it.
* **No ticks.** Every both-barriers-in-one-bar race is given to the stop, which
  is conservative and identical across arms, and is why the walks read 0.31
  rather than 0.3333 conditional on resolving.
* **One snapshot of cost**, as above.
* **The multiplicity count.** 98 instrument-clock cells, 432 sweep cells, 4
  arms, 5 null series, 2 zone populations. Nothing was selected on; the full grid
  is printed; and 0 cells survive BH on the published population.

## Re-running

    ./.secrets/lab.sh run research/ideas/breaker_blocks.py MODE=cost    OUT=.data/breaker
    ./.secrets/lab.sh run research/ideas/breaker_blocks.py MODE=run     OUT=.data/breaker WORKERS=28
    ./.secrets/lab.sh run research/ideas/breaker_blocks.py MODE=run     OUT=.data/breakerdesk ZONES=desk WORKERS=28
    ./.secrets/lab.sh run research/ideas/breaker_blocks.py MODE=sweep   OUT=.data/breaker WORKERS=28
    ./.secrets/lab.sh run research/ideas/breaker_blocks.py MODE=power   OUT=.data/breaker
    ./.secrets/lab.sh run research/ideas/breaker_blocks.py MODE=overlap OUT=.data/breaker
    ./.secrets/lab.sh exec 'cd ~/till_infinity && PYTHONPATH=$HOME/till_infinity/repo \
        OUT=.data/breaker .venv/bin/python -u repo/research/ideas/breaker_report.py'

Set `OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1` on any pooled
mode. `MODE=smoke` runs on generated bars in seconds and prints every stage's
count, which exists because a detector that finds nothing and a detector that is
out of scope read identically.

Outputs under `$OUT`, none committed: `trades.csv.gz` (one row per real trade
per target), `cells.csv` (every arm and every null series summarised),
`zones.csv` (firing rates and drops), `cost.csv`, `sweep.csv`, `power.csv`,
`overlap.csv`, `per_instrument.csv`.
