# The hour of day: seasonality, regime, and the broker's rollover

Measured 2026-09-20 on 2,355,174 hourly bars from the broker's own feed, 42
instruments, 2016-06-14 to 2026-09-20, synthetics and crypto excluded from the
return work. Two questions, and one operational finding that pays for both.

## Seasonality: the large effects are the broker's quoting

Mean hourly return by UTC hour, one observation per (hour, day) taken across
instruments, because 22 instruments in the same hour are one event rather than 22:

| hour | mean | t |
|---|---|---|
| 20:00 | -1.005bp | -9.03 |
| **21:00** | **-1.438bp** | **-15.67** |
| **22:00** | **+1.415bp** | **+11.73** |
| **23:00** | **+1.628bp** | **+11.49** |
| 11:00 | -0.353bp | -2.84 |
| 14:00 | -0.545bp | -2.23 |

Seven of twenty-four hours above |t|=2 where 1.2 is expected - and four of those
seven are consecutive, with a **1.4bp fall at 21:00 and a 1.4bp recovery at 22:00 to
23:00**. A drift does not reverse itself an hour later. A round trip does, and the
day's returns sum to +1.063bp, which is near enough zero that nothing survives the
window.

**The mechanism is measurable, not inferred.** The spread is recorded on every bar,
and around the daily rollover it widens to **15.4x the day's median at 21:00**, 10.7x
at 22:00 and 2.5x at 23:00. Bars are built on the bid, so quotes widening push the
bid down and narrowing let it back - a dip and a recovery that no one could trade.

(The absolute spread figures in that run were in mixed units: points were divided by
price without applying each instrument's `point`, so only the hour-to-hour ratios are
meaningful. The ratios are the finding.)

Away from the rollover the hourly means are **±0.26bp at most**.

## Regime: mean reversion everywhere, momentum nowhere

The operator's framing - seasons of momentum and of mean reversion - tested as the
signed product of consecutive hourly returns. Positive is continuation, negative is
reversion.

Ten hours reach |t|>1.5. **Every one of them is negative.** Not a single hour of the
twenty-four shows continuation.

| hour | carry | t |
|---|---|---|
| 22:00 | -1.350bp | -13.01 |
| 21:00 | -0.774bp | -9.11 |
| 23:00 | -0.920bp | -6.95 |
| 20:00 | -0.323bp | -2.93 |
| 00:00 | -0.328bp | -2.48 |
| 19:00 | -0.297bp | -2.21 |
| 06:00 | -0.281bp | -2.09 |

The rollover hours dominate, for the reason above. What remains away from them is
reversion of **0.23 to 0.33bp an hour** - which is **smaller than the 0.10 to 1.07bp
spread**, so it cannot be traded even where it is real. This is the bid-ask bounce
seen hour by hour, and it agrees with the variance ratios measured independently:
H is about 0.49 on one-minute returns, mild reversion, which is the spread itself.

**So there are no momentum hours and no reversion hours worth trading.** The regime
does not rotate; it is mildly mean-reverting all day at below the cost of acting.

Leave-one-instrument-out was applied to the strongest hours after that control
caught the momentum work: 22:00 goes from t=-13.01 to -10.84 without its three
loudest names. Broad, not a few instruments - which is what a rollover artifact
should look like.

## What this is worth: do not open in the rollover window

The window was identified **from the spread alone**, and only then checked against
outcomes. That ordering is what makes it a finding rather than the worst of
twenty-four hours chosen after the fact.

| | |
|---|---|
| closed trades opened 20:00-23:00 UTC | **142 of 989, 14%** |
| their P&L | **-661.18 of -1,470.25, 45% of all losses** |
| 20:00 alone | 26 trades, -338.56, **mean R -0.343** - the worst hour |

Fourteen per cent of the trades carry forty-five per cent of the loss, in the hours
where the quote is two and a half to fifteen times wider.

**`max_spread_fraction` cannot catch this**, and that is why 142 trades got through:
it compares the spread to the *reward*, so a distant target passes however wide the
quote has become. `quiet_hours` is the gate that does - checked before anything about
the signal, since it is a fact about the clock, and off by default because the window
is a property of one broker's quoting.

## Caveats

142 trades is a modest sample and the hour-to-hour spread of mean R across all
twenty-four hours is wide, from -0.41 to +0.25, so 20:00's -0.343 is not individually
significant. The case rests on the mechanism being measured first and the window
being pre-specified, not on the P&L of one hour.

And the return work excludes crypto and the synthetics. Crypto trades around the
clock and has no rollover of this kind; the synthetics are generated and have no
sessions at all.
