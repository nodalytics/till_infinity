# The null for the post-stop replay

A measurement nobody has taken. It decides whether the strongest claim in
[failing.md](../failing.md) survives.

## What was measured, and what it cannot say on its own

Walking `quotes.db` forward from each of 55 stopped trades on 2026-09-02 found
that price went on to reach the trade's target **82% of the time within 24
hours** — 25% within 30 minutes, 56% within two hours, 69% within four. That
reads as "the stops are early", and it was reported that way.

The comparison inside it is sound: the recovery rate is **flat across the
model's confidence bands** — 90%, 87%, 88% for the 0.7-0.8, 0.8-0.9 and 0.9+
bands. Every band shares one horizon, so whatever inflates the absolute figure
inflates all three equally, and the model's stated probability adds nothing to
whether a stopped trade was going the right way.

The **absolute** figure is the problem. A target sits roughly one risk unit
from entry. A driftless process will touch a level that close given a day, so a
large fraction of that 82% may be arithmetic about random walks rather than
anything about these calls. Nothing in the measurement separates the two,
because there is no null to subtract.

## What to run

The same replay, from **entry times that carry no signal**.

1. Take the 55 stopped trades. Keep each one's feed, side, target distance in
   price, and horizon set (30m, 2h, 4h, 24h).
2. For each, draw **k random timestamps** on the same feed — same instrument,
   and ideally the same session and weekday, so liquidity and the daily
   volatility cycle are held rather than averaged over. `k` of 20 to 50 keeps
   the standard error small next to a 55-trade sample.
3. From each random timestamp, place a synthetic entry at the mid, and a target
   the same *price distance* away on the same side.
4. Ask the same question with the same aggregate query: did bid (for a long) or
   ask (for a short) reach it inside each horizon.
5. Report the difference, per horizon, with an interval.

The `quotes_feed_ts` index makes this the same shape of query that has already
been run — four cumulative `min`/`max` aggregates per sample. At k=30 that is
about 6,600 aggregates, where 220 took three minutes, so budget an hour and run
it detached rather than through a live SSH session. Two background watchers
have already died on a broken pipe.

## What each outcome would mean

| result | reading |
| --- | --- |
| random ≈ 82% at 24h | the replay measures prices moving, not skill. The stop-widening argument loses its main support and rests only on the flat-across-bands comparison. |
| random well below the trades | reaching target after a stop is a property of *these entries*, and the stops really are cutting winners. |
| random above the trades | worse than nothing: being stopped would select *against* recovery, which would need explaining before anything is changed. |

Judge it at **30m and 2h** first. Those are near the horizon the trades
actually live on, and 24h is where a random walk most flatters itself.

## Why not to skip it

The obvious action from the original number is "widen the stops", and that is
not a free change: the 18% that never came back would have run further than
they did, and the replay says nothing about how far. Acting on an 82% that
turns out to be a 78% null would be sizing a real change off noise.

The honest prerequisite is this, and then
[excursion.md](excursion.md) — which measures how much room a trade needs
rather than inferring it.

## Related

* [failing.md](../failing.md) — the measurement this qualifies.
* [horizon.md](../horizon.md) — where banding by *interval* and scoring by
  *realised duration* was the same class of mistake: an answer that looks like
  a result until you ask what it is being compared against.
