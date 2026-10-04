# The tail scan: which MCFL patterns reach high R more often than randomness allows

**Measured, 2026-10-04. The 4h and 1d momentum words do have a fat right tail that walks don't have, and it
holds on unseen data. It doesn't pay: no selected cell makes money after costs except three 15m doji
fades, and those come from a broken data feed.** Discovery covered 2,960 cells and 133 survived
Benjamini-Hochberg. All 15 selected cells kept a positive tail excess on data the scan never saw, and 14
of them kept it with a 90% interval above zero. Twelve fail the frozen test, all on mean R after costs
(−0.01 to −1.1R a trade); one of them also loses its excess. The three that pass the rule as written (15m dragonfly and gravestone doji, faded) owe
it entirely to the broker's alt-coin crypto CFDs. Those quote on a coarse price grid with no recorded
spread, so a stop one or two price steps away turns a single tick into 5R. On every other asset class the
same three cells make +0.01 to +0.04 excess and −1 to −3R. Deriv's diffusive generators show no excess,
as they should. Its jumpy generators and Range Break 100 show a large excess, which comes from their
jumps and not from any pattern.

## Framing

Markets are close to random walks, so most patterns look much the same on walks, and that alone doesn't
make them fake. On a martingale, P(+N R before −1 R) = 1/(N+1) for **any** rule. A high-RR rule on a
walk pays for its big wins with a lower hit rate, exactly. The edge the desk wants is a pattern whose
P(≥ N R) at large N beats both 1/(N+1) and the same pattern on matched walks, even if it fires rarely.
Every table below leads with that **tail excess**: ex_N = P_real(≥ N R) − max(P_iid, P_garch).

## Frozen rules (`ideas/tail_rule.json`, committed before any real-data run)

- **Patterns.** Every directional entity of `mcfl.parse(df, changepoints=True)`: v1 productions, v2
  alphabets, the 64-row candlestick vocabulary, the time core and changepoints. CANDLE, BAR_RELATION and
  EPISODE are excluded. That gives 112–125 names per series, after splitting PATTERN by name, SWING by
  label, BREAK by vs_structure, POOL_TAKEN by sweep or take, IN_WINDOW/LATE/EARLY by type and TIMEOUT by
  kind.
  - Each name is traded **with** its direction (W) and **faded** (F).
  - Each has three variants: ALL; X12 (fires at a 12-bar extreme against its direction); RZ (the bar's
    range z is in the top decile of its last 1,000 bars, causal).
  - Each is tested at 15m, 1h, 4h and 1d.
- **Trade.**
  - Entry: the next open after known_at.
  - Stop: 0.1 ATR beyond the pattern's own bars (if they start at most 5 bars back), else beyond the 3-bar
    extreme. Stop fills take 0.05 ATR of slippage.
  - Horizon: 20 days.
  - Tail measure: the most R reached before the initial stop (a barrier probability).
  - Money measure: a 2-ATR trail exit, net of costs. Binance pays 0.07%; MT5 pays the broker's spread
    floor; walks pay the real series' cost in ATR.
- **Nulls.** iid and GARCH walks for each series: 256 sub-steps a bar, the real timestamps, parsed and
  traded identically. Also 1/(N+1).
- **Discovery set.** Binance 12 perpetuals, plus the MT5 FX majors and crosses, metals, and BTC/ETH/SOL
  CFDs. Signals before 2023-12-12. MT5 has no 15m before 2024, so 15m discovery is Binance only.
- **Selection.** Eligible cells need at least 300 real trades. Test: a one-sided z on ex_5 with
  day-clustered variance, then BH at q = 0.05. Take the top 15 survivors by ex_5 (`tail_selected.json`,
  committed before confirmation).
- **Confirmation set** (never seen):
  - the 131 fresh Binance coins, at 4h and 1d;
  - the Binance 12 and the MT5 discovery markets from 2024;
  - the MT5 markets discovery didn't use: 7 indices, 2 oils, copper and 32 alt-coin crypto CFDs.
- **Confirmation pass**, all of these:
  - ex_5 > 0 with its 90% day-bootstrap interval above 0;
  - P(≥5R) above both 1/6 and the walk;
  - mean trail R > 0 after costs;
  - BH over the 15.
- **Amendments before the run.** 15m was added at the desk's request. Series over 60k bars are parsed in
  50k-bar segments with 5k bars of warm-up; this keeps 99.85% of a whole parse's events on a test series.
  Per-asset-class reporting was added during the run, for reporting only; the selection didn't change.

The barrier calibration was checked before freezing. On 30 generated GARCH series, P(≥ N R) matched
1/(N+1) within noise for N ≥ 3. At small N it is lower, because a bar that touches both the target and
the stop counts as stopped.

## Discovery (Binance 12 + MT5, before 2024)

| | cells | eligible | BH survivors | mean ex_5 | share ex_5 > 0 |
|---|---|---|---|---|---|
| all | 2,960 | 2,043 | **133** | −0.0053 | 0.37 |
| 15m | | 598 | 39 | −0.0011 | 0.51 |
| 1h | | 560 | 4 | −0.0067 | 0.24 |
| 4h | | 474 | 18 | −0.0090 | 0.26 |
| 1d | | 411 | 72 | −0.0049 | 0.48 |

The typical pattern reaches 5R slightly **less** often than a walk. The survivors are a tail of the
distribution, not a shift of it.

The with/fade excesses are anti-correlated (r = −0.26 overall, −0.52 at 1d). The excess is
directional, not just volatility; if it were volatility, both sides would gain.

By class, mean ex_5 among eligible cells:

| class | 15m | 1h | 4h | 1d |
|---|---|---|---|---|
| Binance perps | −0.001 | −0.007 | −0.008 | −0.005 |
| FX | | −0.007 | −0.012 | −0.007 |
| metals | | −0.010 | −0.012 | −0.008 |
| crypto CFDs | | −0.011 | −0.007 | +0.028 |

The broker had no stock bars, and its indices and oils start in 2024, so those classes appear in
confirmation only.

## The 15 selected cells: discovery against confirmation

"walk" is max(iid, GARCH). 1/(N+1) is 0.167 at 5R and 0.091 at 10R. R is the mean trail R after costs.
"conf" pools all confirmation data at the cell's timeframe.

| cell | disc P5 / walk / ex5 | disc P10 / walk | disc R | conf n | conf P5 / walk / ex5 [90%] | conf P10 / walk | conf R [90%] | verdict |
|---|---|---|---|---|---|---|---|---|
| FOCUS W ALL 4h | .106 / .021 / +.085 | .037 / .000 | +0.008 | 24,323 | .096 / .039 / **+.057** [+.044, +.070] | .031 / .001 | −0.011 [−.050, +.028] | fails (R) |
| THREE_WHITE_SOLDIERS W ALL 4h | .149 / .079 / +.070 | .039 / .007 | +0.034 | 2,348 | .158 / .062 / **+.096** [+.070, +.125] | .070 / .005 | −0.084 [−.139, −.030] | fails (R, P5 < 1/6) |
| THREE_WHITE_SOLDIERS W ALL 1h | .216 / .149 / +.067 | .101 / .045 | +0.051 | 2,313 | .165 / .157 / +.008 [−.014, +.027] | .067 / .044 | −0.074 | fails |
| SWING:HL F RZ 4h | .184 / .123 / +.061 | .072 / .039 | −0.054 | 6,481 | .148 / .125 / +.023 [+.003, +.040] | .065 / .041 | −0.122 | fails |
| DRAGONFLY_DOJI F X12 15m | .212 / .154 / +.058 | .131 / .101 | −1.547 | 18,027 | .421 / .165 / +.257 [+.238, +.268] | .330 / .109 | +2.425 | passes the letter; **feed artifact** |
| FOCUS6 W ALL 4h | .104 / .050 / +.054 | .035 / .002 | −0.008 | 37,014 | .102 / .045 / **+.057** [+.046, +.069] | .034 / .001 | −0.019 [−.054, +.018] | fails (R) |
| THREE_BLACK_CROWS F ALL 15m | .214 / .164 / +.050 | .117 / .102 | −0.647 | 5,836 | .194 / .163 / +.031 [+.018, +.042] | .116 / .099 | −0.759 | fails (R) |
| VOID W RZ 4h | .109 / .062 / +.046 | .025 / .006 | −0.029 | 34,931 | .102 / .064 / **+.038** [+.029, +.049] | .029 / .005 | −0.020 [−.050, +.010] | fails (R) |
| FOCUS6 W RZ 4h | .102 / .057 / +.045 | .032 / .001 | +0.000 | 28,330 | .106 / .053 / **+.053** [+.040, +.067] | .034 / .001 | −0.012 [−.053, +.031] | fails (R) |
| THREE_WHITE_SOLDIERS F ALL 15m | .215 / .170 / +.045 | .114 / .104 | −0.782 | 7,053 | .205 / .171 / +.034 [+.022, +.044] | .128 / .104 | −0.700 | fails (R) |
| DRAGONFLY_DOJI F ALL 15m | .203 / .160 / +.043 | .118 / .103 | −1.575 | 45,057 | .365 / .163 / +.203 [+.191, +.210] | .269 / .107 | +1.602 | passes the letter; **feed artifact** |
| GRAVESTONE_DOJI F ALL 15m | .205 / .163 / +.042 | .121 / .107 | −1.561 | 44,786 | .347 / .161 / +.186 [+.175, +.195] | .250 / .102 | +1.303 | passes the letter; **feed artifact** |
| MARUBOZU W ALL 1d | .078 / .036 / +.042 | .021 / .002 | −0.927 | 1,987 | .075 / .037 / **+.038** [+.023, +.055] | .022 / .000 | −0.127 | fails (R) |
| OUTSIDE_REVERSAL W ALL 1d | .079 / .038 / +.042 | .015 / .001 | −0.071 | 17,401 | .077 / .036 / **+.041** [+.029, +.053] | .019 / .001 | −0.031 [−.106, +.041] | fails (R) |
| CLOSING_MARUBOZU F ALL 15m | .197 / .157 / +.041 | .124 / .106 | −1.349 | 163,599 | .184 / .156 / +.028 [+.026, +.031] | .121 / .104 | −1.130 | fails (R) |

### What held up: a real fat right tail after 4h/1d momentum bars, which costs as much as it pays

FOCUS, FOCUS6 (changepoint ignitions), VOID in a range shock, a 1d OUTSIDE_REVERSAL or MARUBOZU, and
three white soldiers at 4h were all traded **with** their direction. They reach 5R about **twice** as
often as matched walks and 10R about **20 to 30 times** as often (0.03 against 0.001), and that held on
data the scan never saw. Two things stop it being a trade:

- It isn't above 1/(N+1). These wide-stop trades (the stop sits beyond a large bar) reach 5R only 8-10%
  of the time within 20 days, and walks only 4%. Both are far below 1/6, because the horizon runs out
  before the barrier is hit. The real market's excess over the walk is fat-tailed, trending follow-through
  that a Gaussian walk with a matched ATR lacks.
- It doesn't pay. Trail R is −0.01 to −0.03 after costs, with intervals straddling zero, against about −0.07
  for the same rule on walks in discovery. The tail is real and **worth about +0.05R a trade over a walk**, but that is
  less than the friction.

By class, the excess is broad rather than local. It holds on Binance perps, crypto CFDs and, more weakly,
on metals and FX:

| cell, confirmation | Binance perps | crypto CFDs | FX | metals | indices | energy |
|---|---|---|---|---|---|---|
| FOCUS6 W ALL 4h ex5 | +.060 (28,645) | +.062 (6,146) | +.017 (1,042) | +.009 (358) | +.008 (643) | −.012 (180) |
| OUTSIDE_REVERSAL W ALL 1d ex5 | +.042 (12,320) | +.046 (2,953) | +.020 (998) | +.053 (371) | −.004 (634) | +.069 (125) |
| VOID W RZ 4h ex5 | +.041 (27,525) | +.037 (5,738) | −.006 (799) | +.010 (232) | −.006 (471) | −.029 (166) |
| FOCUS W ALL 4h ex5 | +.055 (18,939) | +.067 (3,984) | +.036 (675) | +.035 (227) | −.007 (371) | +.079 (127) |

It is strongest in crypto, present in FX and metals, and absent in indices. In discovery the same cells
showed +0.10 to +0.13 on Binance and crypto CFDs against +0.00 to +0.03 on FX. Read it as a crypto trend
property that the momentum words pick out.

### What didn't: the 15m doji fades, and why they "pass"

The three 15m doji fades pass every frozen condition, at +1.3 to +2.4R a trade. All of it comes from the
**32 alt-coin crypto CFDs** at 15m: 38,000 of the 45,000 trades come from them, about ten times the doji
rate per market of Binance. Their 15m feed (from 2025-08) quotes on a grid far coarser than its `point`:
FILUSD steps in 0.01 at a price near 1.0. The bars are flat and gapped. The broker records no spread for
them (cost 0 in the scan). A doji's stop then sits 1–9 price steps away; NEOUSD's median ATR is 14
points and its risk is 1.8. A single tick is several R. Both effects are invisible to a continuous walk
and don't exist on an exchange; see `tail_gallery_1.png`.

On every other class the same cells give ex5 of +0.01 to +0.04 and −0.9 to −3.1R after costs:

| cell, confirmation | crypto CFDs | Binance perps | FX | metals | indices |
|---|---|---|---|---|---|
| DRAGONFLY_DOJI F ALL 15m | +.236, **+2.28R** | +.036, −2.07R | +.011, −2.86R | +.024, −0.88R | −.014, −1.23R |
| GRAVESTONE_DOJI F ALL 15m | +.212, **+1.93R** | +.017, −2.05R | +.057, −3.13R | +.009, −1.01R | +.031, −1.49R |

These are **rejected as a feed artifact**, not confirmed. They should be judged on exchange data: on the
Binance 12 from 2024 they make −2R.

## Deriv synthetics, reported apart

| class | 15m mean ex5 | 1h | 4h | 1d | cells with z5 > 3 (15m/1h/4h/1d) |
|---|---|---|---|---|---|
| Deriv diffusive (Volatility, Step, Drift Switch) | −0.003 | −0.008 | −0.009 | −0.013 | 44 / 0 / 0 / 0 |
| Deriv jumpy (Boom, Crash, Jump, Range Break) | **+0.068** | +0.034 | +0.007 | −0.005 | 348 / 247 / 21 / 0 |
| Range Break 100 alone | **+0.156** | +0.096 | +0.032 | +0.003 | 321 / 249 / 54 / 0 |

The diffusive generators sit at or below zero, as published iid generators should. That rules out a bug
in the parser or the trade code. Their 44 cells with z > 3 at 15m (of 538) suggest the day-clustered z
understates the spread somewhat, which is why confirmation uses a bootstrap.

The jumpy generators and Range Break 100 show large excesses in **both** directions: 81% of 15m cells
have W and F both positive. The excess is the jumps and Range Break's range walls, which a Gaussian walk
can't produce, not pattern information. Bar fills also miss the jump's true fill price (`run.py` flags
the same thing), so their R is overstated.

## Caveats

- **The walks are Gaussian.** Their P(≥ N R) falls well below 1/(N+1) wherever the horizon binds (4h/1d
  wide stops). "Above the walk" there means fatter tails than a Gaussian with a matched ATR, not "above
  a martingale". A t-distributed or bootstrap-of-returns walk would be the stricter null for the 4h/1d
  momentum tail, and is the natural next test.
- **Discovery z understates its spread.** Deriv diffusive's excess of z > 3 at 15m shows it. The 133
  survivors are therefore generous; the bootstrap confirmation is the honest filter.
- **Costs.** Binance 0.07% at 15m is about a third of an R on these tight stops, which is why every 15m
  cell loses on exchange data. The MT5 alt-coin CFDs' zero spread is missing data, not zero cost.
- **Seams.** Long series were parsed in segments, so 0.15% of events at the seams differ from a whole
  parse.
- **Window overlap.** Discovery trades end before 2024; the Binance 12 and MT5 confirmation uses the same
  markets from 2024, so cross-market structure is shared.

## Files

- `ideas/tail_scan.py`: `MODE=discover|classes|confirm|plot|smoke`.
- `ideas/tail_rule.json`: frozen before the run, amended before it for 15m.
- `ideas/tail_selected.json`: frozen before confirmation.
- Lab outputs in `out/tail/`; plots and tables fetched to `.data/tail/`:
  - `tail_heatmap.png`: ex5 and ex10 on discovery, Deriv beside it.
  - `tail_heatmap_variants.png`: the X12 and RZ variants.
  - `tail_heatmap_classes.png`: the asset-class facet.
  - `tail_scatter.png`: discovery against confirmation for the 15.
  - `tail_curves.png`: P(≥ N R) for N = 0.5 to 20, against iid, GARCH and 1/(N+1).
  - `tail_selected_classes.png`: each cell's excess per class.
  - `tail_gallery_1..3.png`: trades that reached 5R and typical losers.
  - `tail_discovery.csv`, `tail_confirm.csv`.
