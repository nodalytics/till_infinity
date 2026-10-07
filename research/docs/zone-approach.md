# How price comes back to a zone: the opposite of the prediction, and not by enough

**Measured 2026-10-07.** The desk's hypothesis, stated with a sign, which is what
made it worth testing:

> the momentum candles with which it comes back to the zone matters before the
> candlestick pattern - if the candles start becoming choppy as it is getting
> closer back to the zone ... measure the hold rate for these compared to the
> ones where momentum candles were coming back to the zone especially as the
> price was getting closer, so if it does not slow when getting closer to the
> zone, the zone might get voided

Code: [`zone_approach.py`](../ideas/zone_approach.py), `approach_shape` and
`zone_held` in [`zones.py`](../ideas/zones.py). The rule is
[`zone-rules.md`](zone-rules.md). Sixteen instruments, 4h and 1d, `touch` entries
with no filter.

## First, the base rate

**A zone holds about half the time.** No close beyond the band's far edge within
the reaction window: **49.7%** at 1d (169 zones) and **45.5%** at 4h (358). That
is the number every claim below has to beat, and it is worth having on its own -
"does the zone hold" had never been answered as a rate.

## The hypothesis does not hold, and at 1d it points the other way

Four readings of the approach, all from bars strictly before the one that
re-enters the band. Against the hold rate, in terciles, against a shuffle of the
feature **within symbol**:

| iv | feature | bottom | top | spread | q |
|---|---|---:|---:|---:|---:|
| 1d | `app_decel` (slowing into the zone) | 0.536 | 0.554 | +0.018 | 0.84 |
| 1d | `app_speed` | 0.482 | 0.596 | +0.114 | 0.59 |
| 1d | `app_body` (momentum against chop) | 0.509 | 0.607 | +0.098 | 0.59 |
| 1d | `app_run` | 0.441 | 0.596 | +0.155 | 0.35 |
| 4h | `app_decel` | 0.417 | 0.458 | +0.042 | 0.77 |
| 4h | `app_speed` | 0.425 | 0.400 | -0.025 | 0.84 |
| 4h | `app_body` | 0.467 | 0.445 | -0.021 | 0.84 |
| 4h | `app_run` | 0.454 | 0.416 | -0.038 | 0.77 |

**Nothing passes.** And every 1d sign is the wrong way round for the hypothesis:
a *faster*, *more momentum-driven*, *less decelerating* approach holds slightly
**more** often, not less. At 4h there is nothing at all - the four spreads are
+0.042, -0.025, -0.021, -0.038 on a 45.5% base rate.

The clearest view is `app_run` - consecutive bars closing the zone's way at the
end of the approach - read bar by bar rather than in terciles:

| `app_run` | 1d n | 1d R | 1d held | 4h n | 4h R | 4h held |
|---:|---:|---:|---:|---:|---:|---:|
| 0 | 42 | **-0.587** | 33% | 60 | -0.177 | 42% |
| 1 | 38 | -0.226 | 50% | 88 | -0.037 | 49% |
| 2 | 26 | -0.182 | 50% | 78 | +0.151 | 50% |
| 3 | 22 | +0.394 | 64% | 46 | +0.047 | 48% |
| 4 | 10 | **+1.272** | 70% | 26 | +0.187 | 27% |
| 5 | 7 | -0.774 | 43% | 11 | +0.450 | 18% |
| 6 | 2 | -0.468 | 50% | 19 | -0.541 | 47% |

A run of **zero** means the bar before the return closed *away* from the zone -
price was not even moving into it on the last bar; it drifted or chopped in. That
is the **worst** bucket on both timeframes and the weakest hold rate at 1d, 33%
against a 50% base.

So the chop the desk was pointing at is real and it is visible - but it marks the
trades that **lose**, not the ones that hold.

## What survives, and why it should not be traded

One cell of sixteen passes Benjamini-Hochberg: `app_run` against **R** at 1d,
bottom tercile -0.416R, top +0.367R, spread +0.782, p = 0.001, q = 0.016.

Four reasons it is not an edge yet, in order of how much they matter:

1. **The top tercile's own interval includes zero** - [-0.081, +0.867]. What is
   reliable here is that the *bottom* is negative [-0.569, -0.254]. This is a
   filter against bad trades, not a signal for good ones.
2. **It is not monotone.** R rises 0 -> 4 and then collapses at 5 and 6, and the
   single best bucket is **ten trades** at +1.272R. Take that bucket out and the
   spread is most of the way gone.
3. **147 trades over 16 instruments is nine each**, so no instrument can show the
   pattern on its own - the per-symbol check cannot even run at 1d. The pooled
   result is the only result there is.
4. **4h says nothing** - the same feature, the same code, 328 trades, spread
   +0.110 and q = 0.77. A rule that works on one timeframe and not the other,
   with no mechanism that distinguishes them, is usually a sample.

## What this changes

Nothing in the rule. The honest summary for the desk:

* **the hold rate is ~50% at 1d and ~46% at 4h**, and none of the four readings
  of the approach moves it by a believable amount
* **the sign is backwards** from the hypothesis on every 1d measure
* the one thing that does look real is that **a zone price drifts into, rather
  than drives into, loses** - and that is worth another look as a *veto* rather
  than as a signal, which is a different and much weaker claim than the one being
  tested here
* it is one timeframe, one tercile, and ten trades in the best bucket

Re-measuring this on the held-out instruments is pointless at current
populations - they produced about a hundred zones in total. More time, not more
instruments.
