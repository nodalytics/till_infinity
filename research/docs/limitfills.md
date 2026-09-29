# The winner's curse on limit fills: the better price is paid for by which touches fill

Harness: [`research/harness/limitfills.py`](../harness/limitfills.py). Lab run 2026-09-29, on the
journal snapshot (2026-08-13 to 09-10) and on production's zone touches (the `stophunt.py` cache
from the production `Engine`).

## The question

[`game-theory.md`](game-theory.md) ranked it fourth. An order resting at a better price is filled
only when price trades to it, and it trades to it more often on the way *through*. So the fills a
resting order gets may be the ones that go on against it, and the ones it misses the ones that went
its way at once. Does the better price pay for that adverse selection plus the missed winners?

## How production waits for a better price

`trading/service.py`:

| path | what it does | default |
|---|---|---|
| `_park` | holds the signal as a `Waiting` with a trigger at the level's wick depth, `wick + pullback_sigmas x wick sd` (0.5), capped at `pullback_max_vol` (4 vol), if the level has `pullback_min_wicks` (2) wicks and the improvement is at least `pullback_min_gain` (0.25 vol) | on where a strategy sets `pullback_fraction` (the swing strategies and `opportunity`: 1.0; `pullback_when_wick` 0.35 on one swing) |
| `_rest_at_named_price` | waits at the price a strategy names | per strategy |
| `_edge_entry` | waits `entry_edge_vol` better than the quote | off (0.0) |

A parked signal is a **virtual limit**. When the quote crosses the trigger it wakes and is sent **at
market**, so it pays the spread like any other entry. It expires after `pullback_bars` (10) bars of
its interval. The journal records it as a declined signal with reason `waiting` ("holding out for
<price>"), and a woken one as a trade with `after_pullback = 1`.

## Results

### The desk's trades (observational)

| | n | R [95%, days resampled] | hit | adverse / best excursion |
|---|---|---|---|---|
| after a pullback | 100 | -0.138 [-0.214, -0.095] | 49% | 0.22R / 0.35R |
| at market | 107 | -0.208 [-0.330, -0.076] | 36% | 0.15R / 0.26R |
| thesis-only, after a pullback | 79 | -0.123 [-0.217, -0.020] | 51% | 0.20R / 0.29R |
| thesis-only, at market | 80 | -0.148 [-0.284, +0.032] | 41% | 0.14R / 0.25R |

The intervals overlap. The two groups differ in more than the entry (the strategies, levels and
hours that park are not a random subset), so this can't separate the effect of parking.

### The desk's parks, replayed

There are 997 distinct parked signals (feed x trigger); 905 have 1m bars to replay. Market means
entering at the signal's own price when it was parked; park means filling at the trigger within 10
bars of the interval. Both use the record's own stop and target and the same clock, net of the
feed's median spread. Unfilled parks earn 0.

| fill rule | fill | park R / signal | market R / signal | park - market [95%] | fills vs market on them | missed (market R) |
|---|---|---|---|---|---|---|
| touch (the trigger is reached) | 78% | -0.088 | -0.102 | **+0.014 [-0.011, +0.048]** | -0.112 vs -0.227 | **+0.353** |
| through (a spread beyond) | 74% | -0.139 | -0.102 | **-0.037 [-0.064, +0.019]** | -0.188 vs -0.252 | +0.321 |

In units of the market trade's risk, the fill bar closed at about the fill (-0.022 / -0.058), and the
drift after the fill was -0.042 / -0.089, against the market entry's -0.250 / -0.326 on the same
signals.

### Simulated on production's zone touches

There are 44,732 real-market and 29,188 Deriv touches, and 25,299 on our walks. A limit rests at
level - side x k x vol for k = 0.25, 0.5 and 1.0, for a life of 1, 3 or 10 bars, against a market
entry at the touch. The stop is 2 vol past the level and the target is 2R from each entry's own
risk.

**The pre-registered test compared the limit with a market entry that trades every touch, and it
misled.** Eight cells passed it: FX 15m at every k with a 1-bar life (+0.068 to +0.092R per signal,
t 8-9, both halves), and crypto 15m at k = 1.0 (+0.058, t 3.1). But on FX 15m every market entry
loses to costs (-0.223R net against -0.003R gross), so a limit that trades a fifth to two-fifths of
the touches wins by trading less, and the walks, charged 0.15 against FX's 0.8, cannot net that
out. A comparison was added after the run and flagged as post hoc: a **random skip**, the market
entry on a random subset at the limit's own fill rate, before and after costs. Against it, **0 cells
pass.**

Touch fills, against the random skip at the same rate:

| family, interval | k, life | fill | net vs random skip (t) | gross vs random skip (t) | fills gross vs market on them | missed (market R) |
|---|---|---|---|---|---|---|
| FX 15m | 0.25, 1 | 43.5% | -0.057 (-10.2) | **-0.000 (-0.1)** | +0.130 | -0.047 |
| FX 15m | 1.00, 1 | 23.1% | -0.079 (-15.7) | **-0.007 (-1.5)** | +0.273 | -0.079 |
| FX 15m | 1.00, 10 | 56.6% | -0.175 (-22.0) | -0.022 (-2.6) | +0.420 | **+0.438** |
| FX 1h | 0.50, 10 | 70.0% | -0.016 (-0.6) | +0.030 (+1.1) | +0.347 | +0.583 |
| metals 15m | 0.50, 1 | 37.7% | -0.004 (-0.4) | +0.009 (+0.8) | +0.182 | +0.061 |
| crypto 15m | 1.00, 1 | 21.8% | -0.046 (-5.2) | -0.002 (-0.3) | +0.322 | -0.012 |
| crypto 15m | 0.50, 10 | 64.5% | -0.079 (-6.0) | -0.023 (-1.7) | +0.291 | +0.502 |
| Deriv 15m | 1.00, 10 | 57.9% | -0.063 (-7.0) | -0.034 (-3.7) | +0.421 | +0.629 |
| Deriv 1h | 0.25, 1 | 49.7% | +0.000 (+0.0) | +0.006 (+0.5) | +0.106 | +0.088 |
| **walks 15m** | 0.25, 1 | 37.9% | -0.015 (-2.8) | **-0.005 (-0.9)** | +0.138 | +0.064 |
| **walks 15m** | 0.25, 10 | 72.1% | -0.019 (-2.4) | -0.005 (-0.6) | +0.264 | +0.674 |

Across all 72 market cells (4 families x 2 intervals x 3 k x 3 lives, touch fill), the gross
difference against the random skip runs from -0.088 to +0.037. Thirteen cells are below t -2 and
none above t +2.

Averaged per family and interval, a filled order's bar closed within 0.1 vol of the fill, and its
drift over the next 10 bars was within 0.1 vol of zero:

| | fill bar's close (thru) | drift after the fill |
|---|---|---|
| FX 15m | -0.006 | -0.003 |
| crypto 15m | -0.013 | -0.015 |
| Deriv 15m | -0.055 | -0.026 |
| **metals 1h** (333 touches, the smallest sample) | -0.150 | -0.431 |

The market entry's drift on those same touches was -0.36 to -1.56 vol.

## What this means

- **The winner's curse is real, and it is exactly the size of the better price.**
  - On the touches it fills, a resting order beats the market entry before costs by 0.10-0.47R, the
    better price.
  - But which touches fill is not random: they are the ones that came back against the trade (the
    market entry's drift on them is -0.4 to -1.6 vol).
  - Scored per signal against skipping the same share of touches at random, the two cancel to about
    zero in every family, **and on our walks** (-0.005). It is the arithmetic of a martingale, not a
    market that picks off our orders.
- **The curse lives in the selection, not after the fill.** A filled order's bar closes at about the
  fill, and it drifts about zero afterwards: within 0.1 vol in every family but metals 1h, whose 333
  touches are the noisiest cell. It is not run over. It is filled on the touches worth less, and
  misses the ones worth more.
- **Missed winners grow with the order's life.** A 1-bar limit misses little (the touches that don't
  come back within a bar are, on FX 15m, if anything losers after costs). A 10-bar limit, like
  production's `pullback_bars`, misses touches worth +0.44 to +0.69R each at market.
- **After costs a limit is worse than skipping at random**, by 0.02-0.18R per signal. A fill closer
  to the stop has a smaller risk, so the same spread is a larger share of R.
- **The desk's own parks say the same.** On 905 replayed parks the fills beat the market on the
  same signals (-0.112 against -0.227R), and the missed parks would have made +0.353R at market. Per
  signal it nets to +0.014R [-0.011, +0.048] with the touch rule and -0.037R [-0.064, +0.019] with
  the through rule. That is nothing either way.
- **The appearance of an edge came from costs.** The literal pre-registered test passed eight cells
  because a limit trades less where every trade loses to costs. That is a reason to trade less, not
  a reason to wait for a better price. This is the third study here (after `confirm.md` and
  `stophunt.md`) where a cheaper-charged control could not net out a cost effect. Cost-neutral
  comparisons (gross, and against a same-rate random skip) belong in the pre-registration from the
  start.

## For production

No code change made here. Recommendations:

1. **Parking has no edge, so don't extend it** (no new resting-price paths, and `entry_edge_vol`
   stays off). Per signal it is equivalent to skipping a random share of trades before costs, and
   slightly worse after them.
2. **If parking stays for its other effects** (fewer trades on a strategy that loses to costs), then
   shorten `pullback_bars` from 10 toward 1-3. The missed winners are what a long wait costs
   (+0.44 to +0.69R per unfilled touch at 10 bars), and `config.py` already notes that a touch
   resolves in a median of 1.33 of its bars.
3. **If trading less is the point, do it on purpose.** A strategy that loses to costs is better cut
   or gated (see `vetoes.md` once written) than thinned by waiting for prices it only gets on its
   worse trades.
