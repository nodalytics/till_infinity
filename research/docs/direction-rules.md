# The published MT5 direction ideas, measured

Six batches of ideas arrived naming specific setups: the WM/Refinitiv London
fix as a 24-to-72-hour magnet, the London-New York overlap sweep, the Wednesday
triple-swap squeeze, the daily-open reversal from an extreme close, the
pre-announcement volatility squeeze, and three cross-asset lead-lag pairs.

They are written in different vocabularies but they are **two shapes**: a clock
or geometry condition fires and a direction is claimed over a forward window,
or one instrument moves and a tethered one is claimed to follow. So they get
two detectors and each idea is a row. That is the only way the answers are
comparable, and the only way a shared artefact shows up as a shared number
rather than as five separate discoveries.

## The clock was checked before anything that depends on it

Every calendar rule names a GMT hour and MT5 server time is usually UTC+2 or
UTC+3. An offset error shifts every window and would null all of them for a
reason unrelated to the ideas. The timestamps were verified against a fact
already measured here - FX volatility peaks at 14-15 UTC at about three times
its trough - and the cache reads **a peak at 14 UTC and a trough at 23, a ratio
of 3.47x**. The clock agrees, so the calendar rows are valid.

The London fix was run at both 15:00 and 16:00 UTC, because 16:00 London is one
or the other depending on British Summer Time and the cache does not carry the
offset.

## The conditional direction rules

Mean is the signed forward return of the published direction in units of the
feed's own median bar range, so a negative mean means the idea is **inverted**.
`z` is against a sign-flip null on the same events. `placebo` is the same rule
on Deriv synthetics, which have no London fix, no carry crowd and no rollover.
`shuffled` is the same rule on a block-shuffled surrogate of the same feeds,
which keeps bar geometry and destroys the calendar.

| rule | n | mean | hit | z | placebo | shuffled | verdict |
|---|---|---|---|---|---|---|---|
| london fix 16 UTC | 1,821 | +0.252 | 0.510 | 1.21 | **-0.273** | +0.084 | null |
| london fix 15 UTC | 1,738 | +0.204 | 0.517 | 0.92 | -0.105 | **+0.358** | null |
| ny overlap fade | 5,986 | +0.013 | 0.509 | 0.70 | +0.041 | +0.021 | **well-powered null** |
| wednesday swap | 279 | **-0.313** | 0.344 | **-4.99** | -0.037 | -0.015 | inverted, then closed |
| daily open reversal | 7,681 | +0.042 | 0.553 | 4.27 | -0.007 | **+0.041** | **mechanical** |
| squeeze fade | 285 | +0.036 | 0.523 | 0.32 | -0.072 | +0.091 | null, underpowered |

### The London fix is not a magnet, and the controls say so twice

Neither hour clears its null. More telling than the `z` is that the **placebo
arm reads -0.273 against the live +0.252** at 16 UTC - a magnitude as large as
the claimed effect, on instruments that have no London fix - and the
**shuffled twin reads +0.358 against the live +0.204** at 15 UTC, larger than
the thing it is controlling for. A detector that produces readings of this size
on markets with no fix and on surrogates with no calendar is measuring its own
construction.

This is also an underpowered test: planting a drift of 0.4 bar-ranges reaches
only `z` 3.1. So the honest statement is that the fix magnet is **not
established and could not have been established here** at anything below a very
large effect - not that a small one is excluded.

### The overlap fade is a null worth trusting

`z` 0.70 on 5,986 events, and the power line is the reason it means something:
a planted drift of **0.05 bar-ranges reaches z 3.3**, and 0.1 reaches 6.0. The
test could comfortably see an effect twenty times smaller than the one it
reports, and the placebo arm reads three times the live arm. There is nothing
there.

### The daily open reversal is mechanical

This one looked best on the raw numbers - `z` 4.27, hit rate 0.553 on 7,681
events, placebo clean at -0.007. The **shuffled twin reads +0.0410 against the
live +0.0423**.

That is the whole result. Block-shuffling destroys every calendar and every
sequence of sessions while keeping each bar's own open-high-low-close geometry,
and the effect is unchanged. So it has nothing to do with daily opens,
inventory backlogs or the Asian session. Conditioning on a close in the top 5%
of its own bar range and then measuring the next return is reading a property
of bars, not of markets - the same family as `overshoot`, which was definitional
in exactly this way.

### The Wednesday swap squeeze is inverted, and then closed three ways

The only rule to clear its null, and it clears it **in the wrong direction**:
the published bet loses 0.313 bar-ranges an event at `z` -4.99 with a 0.344 hit
rate, on 5 of 5 pairs, while placebo and twin sit at zero. Fading it is the
side that pays. Three checks then close it.

**Cost.** The round-trip spread on these exotics is enormous - 0.40 to 0.97
bar-ranges, so on USDZAR a round trip costs nearly one entire typical bar.
Fading the break earns +0.313 gross against 0.594 in spread: **-0.281 net**,
dead by a factor of two.

| pair | n | raw | cost | net | z |
|---|---|---|---|---|---|
| USDMXN | 60 | -0.268 | 0.402 | -0.671 | -3.89 |
| USDZAR | 47 | -0.357 | 0.970 | -1.327 | -2.65 |
| USDPLN | 49 | -0.178 | 0.492 | -0.670 | -3.24 |
| USDNOK | 68 | -0.362 | 0.725 | -1.087 | -3.07 |
| USDSEK | 55 | -0.384 | 0.411 | -0.795 | -3.30 |
| pooled | 279 | -0.313 | 0.594 | -0.907 | -6.18 |

**The weekday control.** Running the identical rule on every other weekday
holds the pair, the hours, the drift and the break geometry fixed and changes
only the thing the idea says matters:

| weekday | n | mean | z |
|---|---|---|---|
| Mon | 275 | -0.475 | -5.94 |
| Tue | 298 | -0.272 | -4.00 |
| **Wed** | 279 | **-0.313** | **-4.99** |
| Thu | 291 | -0.441 | -6.70 |
| Fri | 180 | -0.667 | -3.69 |

Wednesday is the **second weakest of the five** and Friday is twice as strong.
The triple-swap rollover has nothing to do with it. What is actually there is
generic: an evening hourly break on a trending exotic mean-reverts, on every
day of the week.

**Direction.** Symmetric - -0.261 on up-breaks and -0.345 on down-breaks - so
it is not the pairs' large one-way drift showing through.

The mean reversion is real and well measured. The **swap story is refuted**,
and the effect is not tradable at these spreads.

## The cross-asset lead-lag pairs

A leader move past 2 sigma over 4 bars while the laggard stays inside 0.5
sigma, then the convergence bet held 8, 24 and 48 bars, in the laggard's own
sigma units. **The bet's sign is fitted on a training half** and applied to the
held-out half, because asserting that oil strengthens CAD and then testing it
is a way to get the answer from the assertion.

| pair | contemporaneous r | h=8 | h=24 | h=48 |
|---|---|---|---|---|
| oil -> USDCAD | **-0.175** | +0.94 | -0.29 | +0.95 |
| brent -> USDCAD | **-0.181** | +0.54 | +0.49 | +0.61 |
| gold -> AUDUSD | +0.419 | +1.12 | **+2.47** | **+2.19** |
| gold -> USDCAD | -0.343 | +2.02 | **+2.81** | **+2.18** |
| placebo vol75 -> vol100 | +0.004 | -0.75 | -1.30 | -0.64 |
| constructed USD -> Germany_40 | -0.033 | -0.46 | +0.17 | +1.15 |
| constructed USD -> XAUUSD | -0.456 | -0.47 | -0.39 | -0.79 |
| constructed USD -> AUDUSD | -0.738 | -0.59 | -0.40 | -0.08 |

(cells are `z`.)

### Oil to CAD fails on its own premise

The idea states the correlation "should be deeply negative, historically
between -0.75 and -0.90". Measured on this cache at 1h it is **-0.175 for WTI
and -0.181 for Brent**. The premise is not true at this frequency, so there is
no "temporary break" of a tight relationship to trade - and every horizon is
null anyway.

### The dollar index divergence is null, and the construction is sound

There is no dollar index and no equity index in the cache - `DOW` sits in the
222-name equity set and is Dow Inc. the company, not the average, which is
exactly the kind of mistake that would quietly produce a headline. So the
dollar leg is **constructed** from the six ICE basket currencies at their
published weights.

The construction works: it reads a contemporaneous **beta of -1.154 and r of
-0.738 against AUDUSD** and -0.947 against gold, which is what a dollar index
should do. And every lagged convergence bet off it is null, at every horizon.
That is the standing result of this repo restated on constructed data -
**relationships here are contemporaneous, and the lagged versions of them are
not there.**

### Gold to the commodity currencies is the one survivor, and it is not established

Four readings, on two different laggards at two horizons, all positive at `z`
2.2 to 2.8 with hit rates of 0.57 to 0.60, placebo clean. The two laggards
carry opposite signs in the raw data - gold up implies AUDUSD up and USDCAD
down - and both come out positive once each sign is fitted, so it is one effect
seen twice: **after gold moves and a commodity currency has not, the currency
follows over the next day or two.**

It is not established, for two reasons that should be stated with it. The two
laggards share the same leader and overlapping events, so the four readings are
**not four independent confirmations**. And this table is **21 tests**; a single
`z` of 2.81 among 21 is about 0.1 family-wise, which is not significance.

## Costing the gold leg: the cost is not the problem, the decay is

Unlike the exotics, this is the one leg where costing was worth a run rather
than a formality, and the answer is favourable. The round trip is **0.43 to
0.61 basis points of price**, or 0.025 to 0.031 of the laggard's own sigma,
against a gross effect of 0.68 to 0.76. **Cost takes 3 to 4% of the effect**,
where on the exotic carry pairs it took roughly 200%.

| pair | round trip | h | n | gross | cost | net | net z | hit |
|---|---|---|---|---|---|---|---|---|
| gold -> AUDUSD | 0.61 bp | 8 | 134 | 0.144 | 0.024 | 0.120 | 0.91 | 0.455 |
| | | 24 | 101 | 0.678 | 0.023 | **0.655** | **2.43** | 0.564 |
| | | 48 | 80 | 0.952 | 0.023 | 0.929 | 2.20 | 0.588 |
| gold -> USDCAD | 0.43 bp | 8 | 163 | 0.255 | 0.029 | 0.226 | 1.79 | 0.552 |
| | | 24 | 122 | 0.757 | 0.029 | **0.728** | **2.65** | 0.574 |
| | | 48 | 93 | 0.900 | 0.028 | 0.872 | 2.09 | 0.591 |

Cost is measured from the spread **actually quoted at entry and exit** rather
than from a median, because these events are selected on a volatility condition
and spreads widen exactly then - a median would flatter the result in a way
specific to this kind of event. The point size is inferred per feed from the
series' own tick grid, since the spread column is in points.

### The threshold grid is monotone, which was worth checking the right way

`MOVE` of 2.0 sigma and `STILL` of 0.5 were picked out of the air, so an effect
living only in that cell would be a fitted one. The first version of this grid
printed `z` and appeared to show a ridge at exactly 2.0 - **which was an
artefact of the statistic, not the data.** `n` falls fast as `MOVE` rises and
`z` is about the effect times the root of `n`, so a `z` peak at a threshold can
be pure power. The grid has to show the **mean**.

Net mean at h=24, `MOVE` down the side and `STILL` across:

| | 0.25 | 0.50 | 0.75 | 1.00 |
|---|---|---|---|---|
| **gold -> AUDUSD** | | | | |
| 1.0 | -0.074 | 0.073 | -0.107 | 0.066 |
| 1.5 | 0.153 | 0.308 | 0.125 | 0.124 |
| 2.0 | 0.637 | 0.655 | 0.614 | 0.508 |
| 2.5 | 0.755 | 0.512 | 0.587 | 0.562 |
| 3.0 | 0.453 | 0.592 | 0.710 | 0.575 |
| **gold -> USDCAD** | | | | |
| 1.0 | 0.124 | 0.189 | 0.218 | 0.123 |
| 1.5 | 0.420 | 0.303 | 0.295 | 0.260 |
| 2.0 | 1.139 | 0.728 | 0.602 | 0.522 |
| 2.5 | 0.944 | 0.607 | 0.521 | 0.469 |
| 3.0 | 0.591 | 0.287 | 0.177 | 0.277 |

The mean **rises monotonically with the leader's move** up to 2 sigma in both
pairs - roughly threefold to ninefold from 1.0 to 2.0 - and then plateaus or
decays on samples too small to read. That is the shape the idea predicts: a
bigger leader move implies a bigger catch-up. It is not a ridge at the
threshold that found it.

The stillness condition behaves as claimed on USDCAD, where stricter stillness
monotonically raises the effect from 0.522 to 1.139, and is roughly flat on
AUDUSD. Dropping it **entirely** still nets +0.471 and +0.473 at `z` 2.69 and
2.49 on 222 events each, so about 70% of this is plain gold-to-commodity-
currency momentum transmission and the divergence condition supplies the rest.
The "decoupling" framing is doing less work than the idea implies.

### What closes it

**It decays monotonically across the holdout**, in both pairs, in thirds:

| pair | first third | second | third |
|---|---|---|---|
| gold -> AUDUSD | +1.219 | +0.879 | **-0.087** |
| gold -> USDCAD | +1.646 | +0.313 | +0.251 |

Each third holds only 33 to 42 events so none is precise alone, but the decline
is monotone in both pairs and the most recent third of AUDUSD is **negative**.
The split halves say the same more coarsely: +0.906 to +0.410 and +1.236 to
+0.221.

And the best net `z` is **2.65**, against roughly 3.0 needed for a family-wise
0.05 over the 21 tests the screen had already spent - before counting the grid.

So the verdict is not the one cost usually delivers. The effect has the right
shape, a clean placebo - gold to EURGBP is negative at every horizon and shows
no structure anywhere in its grid - and spreads far too small to matter. It is
**not tradable as it stands** because it is decaying toward zero in the recent
data and it does not clear the multiple-testing bar it has to clear. An effect
that strengthens with the leader's move, survives cost easily, and fades over
the sample is the signature of something real that has been arbitraged, or of a
regime that has passed. Either way it is not a forward edge now.

## What outlives the ideas, continued

**A threshold sweep must print the effect size, not the test statistic.** `z`
confounds the effect with the sample, and `n` usually falls as a threshold
tightens, so a `z` grid manufactures an apparent peak at whichever threshold
balances the two. Print the mean and `n` separately. This one reversed a
reading within a single session: the `z` grid said fitted ridge, the mean grid
said monotone.

## The ideas that cannot be tested here, and why

* **Multi-broker latency arbitrage** needs two broker feeds and there is one.
  Worth adding that the generic form of its claim - one price source leading
  another - is the class this repo has repeatedly found null, although a
  genuine millisecond LP latency is a microstructure effect that bar data
  cannot speak to either way.
* **Global M2 / liquidity impulse**, **GEX and option flow**, and **macro
  regime switching on CPI/PMI** need central bank balance sheets, option chains
  and macro releases. None exist in an MT5 bar cache. The pre-announcement
  squeeze was tested with its **mechanism** substituted for its calendar - a
  width percentile rather than a known release - and came back null and
  underpowered.
* **CVD, tick velocity, Asian-session sweeps, weekly POC, break-and-retest,
  currency-strength rotation, FVG, volume climax and the weekend gap** were
  measured in the earlier batches; see `mt5-ideas.md` and
  `displacement-origin.md`.

## What this run adds that outlives the ideas

**A calendar claim needs the other-weekday control.** It holds the instrument,
the hours, the drift and the trigger geometry fixed and varies only the
calendar. It turned a `z` of -4.99 from a rollover finding into a generic
property of evening breaks, and nothing else in the harness would have.

**Exotic spreads are large enough to close most questions before they open.**
0.40 to 0.97 bar-ranges round trip. Any edge on these pairs has to clear
roughly one bar's range to exist, which almost nothing does.

**Conditioning on where a close sits in its own bar is mechanical.** The
shuffled twin matched the live arm to three decimals. Any rule built on a close
percentile, a pin bar or a close-at-the-extreme needs that control before it
means anything.
