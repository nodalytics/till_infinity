# The calendar predicts volatility, and the number is large

Run: `python research/harness/news_vol.py`

**Measured 2026-09-23** over 191 instrument-events on eurusd, gbpusd and xauusd at 15m resolution,
from the live news store's calendar. Shipped as `structures/context/releases.py`, 16 tests.

The desk's framing was right and it is why this worked where so much else has not:

> *we can use news calls to anticipate volatility too and how high the volatility might go*

**Volatility, not direction.** Every directional candidate in this folder has died. And a scheduled
release is the one event on a desk's horizon whose **timing carries no estimation at all** - it is
published days in advance. So there is no look-ahead to argue about, which makes this the cleanest
causal setup in the repository.

## The result

Realised volatility over the matched control median, pooled across the three instruments:

| window | x normal | first half | second half | 95% interval |
| --- | ---: | ---: | ---: | --- |
| **pre −2h to −30m** | **0.789** | 0.848 | 0.718 | [0.757, 0.872] |
| the print's own bar | **2.424** | 1.316 | 2.531 | [2.075, 2.612] |
| +30m | **1.762** | 1.544 | 2.581 | [1.569, 2.432] |
| +1h | **1.349** | 1.312 | 1.591 | [1.309, 1.440] |
| +2h | **1.120** | 1.073 | 1.379 | [1.032, 1.185] |
| +4h | **0.920** | 0.883 | 1.050 | [0.883, 0.972] |

**Every interval excludes 1.0.** Both halves agree in sign at every horizon. Nothing else in this
folder has a table that looks like this.

Three readings, in increasing order of what they are worth:

**The spike is real and short.** 2.42x on the release bar, decaying through 1.76x, 1.35x, 1.12x and
gone within two hours. Anyone who has watched a CPI print knows this; the value here is that the
number is net of the session rather than a description of it.

**It overshoots and then undershoots.** By four hours the ratio is **0.920** - *below* normal, with
the interval [0.883, 0.972] excluding one. The market spends its volatility early and is then
quieter than a comparable non-event afternoon. That was not expected and it is not in the folklore.

**The lull is the part worth having.** Volatility runs at **0.789x** in the two hours before a
print, and only 19-22% of events see above-normal pre-release volatility on eurusd and gbpusd. It
is the least obvious of the three, the one knowable furthest in advance, and a 21% change in a
volatility-scaled sizing input.

## The confound that decides the study, and what happens without it

**61 of the 161 high-importance events land in the 12:30 UTC hour** - the US 08:30 Eastern slot,
which is also the London/New York overlap. Volatility is high in that hour for reasons that have
nothing to do with news, and `context/sessions.py` already learns exactly that.

So the control is **the same instrument, the same hour of the day, the same weekday, within 120
days, with no event of any importance inside two hours.** Four years of 15m bars make that pool
large. Against an all-hours average this study would have produced a big, confident, entirely
spurious multiplier.

### A second confound, found because gold behaved oddly

The first run drew controls from the whole four-year history while the events span six weeks. Gold's
pre-release window then came out at **1.431x** - *above* normal, where every other instrument
lulled at 0.58 to 0.89.

A lull is a market waiting for a number. **1.431 is not a market doing anything**: it is gold's
recent volatility sitting above its own four-year mean, and that level difference was landing in
every ratio. Restricting the control pool to within 120 days of each event removed it and gold fell
into line at 0.905.

That is worth stating as a method note rather than a footnote: **a ratio against a long-history
baseline measures level drift plus effect, and the effect is usually the smaller term.** The
anomaly is what exposed it, which is the argument for reporting per-instrument panels rather than a
pooled number alone.

## What is excluded, and one hypothesis that failed

**usdjpy is not in the profile.** It shows 5.0x on the print and **1.902x before it** - a market
getting busier while it waits, which none of the others do - and 1.7x still at four hours.

The obvious explanation was tested and **rejected**. Central bank decisions have no fixed release
minute: a statement happens "some time in" a window, so a nominal timestamp would put the real move
inside the pre-release window and read as pre-release activity. usdjpy's only non-US
high-importance events are `Monetary Policy Statement` and `BOJ Policy Rate`, so this looked
certain. Dropping every floating-time event - 22 of them, across all instruments - left usdjpy's
pre-release window at **1.902x, unchanged.**

So it is unexplained. It may be genuine: the yen is the classic US-rates instrument and US
inflation data plausibly moves it more than it moves sterling. But a figure that is unexplained on
one of four instruments does not go into a shared table, and the headline is reported without it -
`--feeds eurusd,gbpusd,xauusd` reproduces the table above, `--feeds usdjpy` shows the anomaly.

The floating-time filter was kept anyway. A nominal timestamp is a worse measurement than a
published one whatever this particular test said.

## The surprise does not resolve, and the reason is the sample

On the 144 events carrying both `actual` and `forecast`, `|actual − forecast|` scaled by
`|forecast|` correlates **+0.091** with the first hour's volatility - and the decile split runs the
*other way*: the loudest 30% of surprises moved **1.226x** normal against the quietest 30% at
**1.692x**.

Those two readings contradict each other, so the honest verdict is **unresolved**, and the cause is
identifiable rather than mysterious. Scaling by `|forecast|` is unstable when a forecast is near
zero - "GDP m/m, forecast 0.0%" falls back to a scale of 1.0 - and the proper normalisation is per
indicator, against that indicator's own history of misses. With 144 events spread over dozens of
titles, most titles have one to three observations and there is no history to normalise against.

Worth being clear about what this question could ever be worth: **the surprise is known only at
release.** It can size a position after the print. It cannot anticipate anything, which is a
smaller claim than the timing above, and the timing is the part that shipped.

## What shipped

`structures/context/releases.py`, wired into `structures/service.py` beside `Macro`, publishing
three features on every level call and **deciding nothing**.

It is **fed from the same file and the same poll `Macro` already uses** - `upcoming()` reads the
news store's `events` table read-only, for important events within thirty days either side, and is
called *before* the `settings.macro` guard rather than under it: release proximity is a separate
consumer of that file, and tying it to the policy switch would make a volatility feature vanish
because somebody turned interest-rate features off. A missing or unwritten store logs and returns
nothing, which is the contract `macro.stored` already keeps.

The three features:

* `release_minutes` - negative before the print, positive after. The sign is pinned by a test,
  because getting it backwards would read the post-release spike as the pre-release lull and size
  **up** into the quietest window of the day;
* `release_vol_multiple` - the measured step from `PROFILE`;
* `release_vol_log` - the same in logs, so a doubling and a halving sit the same distance from
  normal, which is the form every other volatility ratio here is compared in.

Absent keys rather than a 1.0 when no important release is within four hours: *no opinion* and
*expect normal volatility* are different claims and the journal has to distinguish them.

**The +4h undershoot is deliberately not published.** 0.920 is the realised volatility over the
*whole* four hours after a print - a statement about a window, not about the instant a caller
stands in - so exposing it as a live multiple would be modelling past the measurement. A test pins
that too.

### Why it decides nothing yet

A volatility multiple is not an edge, it is an input to sizing, and `paying.md`'s arithmetic has
not been run on it. Two specific gaps:

* the profile is measured on **15m bars**, the coarsest resolution that could see this. The print's
  own bar at 2.42x is really "the first fifteen minutes", and the first *two* minutes are certainly
  worse. The desk now trades from 1m, so the near-release shape needs 1m bars to size against;
* the study covers **six weeks of events on three instruments.** Prod trades 32 symbols. The
  currency mapping generalises by construction, but the multiplier has been measured on four
  currencies' releases and nothing else.

The promotion path is the same one `bandits.md` argues for everywhere: let it publish, then compare
sizing that reads it against sizing that does not, on real fills.
