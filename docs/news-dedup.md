# Near-duplicate headlines: what they are, and what they are not

[news-models.md](news-models.md) puts SimHash near-duplicate detection first on
the grounds that 7.6% of the corpus is provably duplicated and that the
restatement count is a feature on its own. It also writes down what would
falsify that, and nobody had run it. This document runs both falsifications.

The short version: **the duplicates are real, the crowding interpretation is
not.** Eighty-nine percent of duplicated rows are one outlet counted twice by
our own collection, and not one duplicate group in the corpus is two
independent newsrooms judging the same story important. Deduplication is a
data-quality fix. It should be kept, and it should stop being called a signal.

## What is measured here

Everything below comes from a snapshot of `.data/news/news.db` and
`.data/prices/prices.db` taken on **2026-08-14**. The corpus at that moment:
**2,756 articles over 44.8 hours** of wall clock, which is larger than the 2,241
quoted in [news-models.md](news-models.md) because collection did not stop. The
ratios are close; the counts are not, so nothing here should be compared to that
document row by row.

Three properties of the clock matter before any number is read:

- **`fetched` is a per-poll batch stamp, not a per-article one.** There are
  **252 distinct `fetched` instants for 2,756 rows**, with a median gap of 297
  seconds. Every article from one poll of one source shares an identical
  timestamp. A "30-minute window" is therefore six poll cycles, and two stories
  inside one poll have no order between them at all.
- **The cold start is a third of the corpus.** **1,027 rows (37.3%)** share the
  very first instant. Those are stories we learned about simultaneously, so any
  timing analysis over them is measuring the moment the process booted. Every
  result below is reported with and without them.
- **`published` remains unusable as a clock.** 650 rows have a `published` more
  than a day before `fetched`; **643 of the 1,523 TradingView rows** are
  backfill, and the oldest `published` is 2023-12-04. Every window here is on
  `fetched`.

## 1. The sharp falsification, run first

> *If the duplicate groups turn out to be overwhelmingly one relay path, then
> the "crowding" interpretation is wrong. It is not many outlets independently
> judging a story important; it is one outlet counted twice by our own
> collection.*

It is worse than one relay path. It is several, and they account for nearly
everything.

Normalising titles to lowercase alphanumerics and grouping gives **105 duplicate
groups covering 214 rows — 7.76% of the corpus**. The groups are shallow: 102
pairs, two triples, one group of four. Nothing is restated five times.

Attributing each row to an *outlet* rather than to a feed — TradingView tags the
provider, so `provider='Cointelegraph'` and `source='cointelegraph'` are the
same newsroom under two labels — splits the 105 groups like this:

| | groups | rows |
|---|---|---|
| one outlet counted twice | **94** | **190 (89%)** |
| more than one outlet | 11 | 24 |

The same-outlet groups, in full:

| outlet | groups | spans two of our feeds |
|---|---|---|
| CoinTelegraph | 55 | 55 |
| Dow Jones Newswires | 23 | 0 |
| Reuters | 6 | 0 |
| Investing | 5 | 0 |
| ForexLive | 2 | 2 |
| dpa-AFX, Moneycontrol, Trading Economics | 1 each | 0 |

**The CoinTelegraph relay is exactly what was suspected**, and it is the single
largest pattern: 55 pairs, each one CoinTelegraph's own RSS feed and TradingView
relaying CoinTelegraph, identical text, different ids. `INSERT OR IGNORE` keyed
on `(source, id)` cannot see it, and is right not to.

**The second pattern was not suspected and is not a relay at all.** Twenty-three
groups are Dow Jones Newswires duplicated *within TradingView* — the "Market
Talk" column re-issued under a fresh id, sometimes hours apart. That is one wire
counting itself twice, upstream of us.

The eleven multi-outlet groups are worth listing individually, because the
listing is the finding:

- **4** — Chainwire and Investing carrying the same crypto **press release**
  (`Zebec Introduces "Earn on Pay"`, `BTCC Exchange Joins TOKEN2049`, …)
- **3** — Investing republishing **Reuters** copy verbatim
- **2** — CNBC TV18 and Moneycontrol, both Network18 titles, on the rupee close
- **1** — GlobeNewswire and Reuters on the same **press release**
- **1** — BusinessWire and Dow Jones on the same **press release**

That is six press releases, three syndication republications, and two sister
publications of one owner. **Zero groups are two independent newsrooms deciding
the same story matters.** The corpus contains no observation of the thing the
crowding hypothesis is about.

**Verdict on the second falsification: it fires.** The restatement count in this
corpus counts collection paths, not editorial judgement. Deduplication drops
from "highest-value cheap win" to hygiene, and it is worth roughly what hygiene
is worth: canonicalising removes **109 rows, 3.96% of the corpus**.

## 2. SimHash, and what it adds over `GROUP BY`

Implemented as [news-models.md](news-models.md) specifies — 64-bit fingerprint
over word shingles, `blake2b` from the standard library, Hamming distance by
popcount, no new dependency. Three-word shingles over the normalised title.
**2,756 fingerprints cost 22,048 bytes — 21.5 KB.** The footprint argument in
that document is sound and is not in question here.

**At distance zero it reproduces exact matching precisely.** 114 identical-
fingerprint pairs against 114 exact-title pairs, with **no false positives and
no misses**. That is a measured property of this corpus rather than a guarantee,
but it means SimHash costs nothing in accuracy for the job exact matching
already does.

Above zero it finds very little, and it starts lying quickly. Every pair beyond
exact match, hand-labelled — a pair is genuine when both headlines report the
same event:

| threshold | new pairs | genuine | precision |
|---|---|---|---|
| d ≤ 5 | 1 | 0 | 0% |
| d ≤ 6 | 5 | 4 | 80% |
| d ≤ 7 | 7 | 5 | 71% |
| d ≤ 8 | 9 | 5 | 56% |
| d ≤ 9 | 12 | 5 | 42% |
| d ≤ 11 | 27 | 5 | 19% |
| d ≤ 12 | 50 | 8 | 16% |

**There is no threshold that separates.** The single false positive at d=5 sits
*below* all four true positives at d=6, so no cut-off admits the genuine finds
without admitting a wrong one. And the total yield at the most generous usable
threshold is **five extra pairs over forty-five hours** — StoneX's acquisition
release picked up twice, a Barron's piece re-headlined by Mint, and Reuters
rewriting its own headline (`Dollar rises` → `Dollar climbs`, `investors leery`
→ `investors wary`).

**The failure mode is specific to a wire, and it is instructive.** SimHash's
false positives are all *templated* headlines whose only difference is the token
that carries the information:

```
FX option expiries for 22 June 10am New York cut
FX option expiries for 22 July 10am New York cut

PBOC is expected to set the USD/CNY reference rate at 6.7497 – Reuters estimate
PBOC is expected to set the USD/CNY reference rate at 6.7413 – Reuters estimate

Canada stocks higher at close of trade; S&P/TSX Composite up 0.51%
Canada stocks higher at close of trade; S&P/TSX Composite up 0.26%
```

Masking digits and month names collapses the corpus onto 2,598 families, of
which **118 hold more than one row, covering 276 rows (10.0%)**. The largest is
`FX option expiries for # <M> #am New York cut` at 32 rows. A shingle
fingerprint is blind to exactly the character that distinguishes these, so it
merges different days' fixings, different expiry dates and different closes.
Ten percent of this corpus is a form letter, and the form letter is where
near-duplicate detection is most confidently wrong.

Shingle size was varied, and the comparison is stark. At d ≤ 7, **k=2 produces
13 new pairs and every one of them is wrong** — its closest match of all, at
d=3, is two PBOC fixings at different rates. **k=4** produces one new pair,
also wrong. k=3 produces seven, of which five are genuine. k=3 is what is
reported above, and it is the best of the three by a wide margin.

**Recommendation: implement SimHash, and run it at d=0.** It is worth writing
because the fingerprint is 8 bytes, it is what a larger corpus will need, and
storing it costs nothing. It is not worth thresholding above zero on 2,756
rows, and MinHash is not the answer to a problem that turned out to be
precision rather than recall.

## 3. The falsification proper, and why it cannot be run

> *Group headlines by fingerprint within a 30-minute window, split at a
> restatement count of one versus three or more, and compare the realised
> excursion on the tagged instrument over the following hour.*

**The right-hand cell is empty.** Grouping on `fetched` with a 30-minute window
gives 76 groups of two or more and **zero groups of three or more**. Widening
the window does not rescue it:

| window | groups ≥2 | groups ≥3 | measurable ≥2 | measurable ≥3 |
|---|---|---|---|---|
| 5 min | 54 | 0 | 10 | 0 |
| 15 min | 67 | 0 | 14 | 0 |
| 30 min | 76 | **0** | 15 | 0 |
| 1 hour | 77 | 0 | 15 | 0 |
| 6 hours | 92 | 2 | 23 | 0 |
| unbounded | 105 | 3 | 24 | 1 |

*Measurable* means the group resolves to exactly one instrument that has 1m bars
locally and has a full hour of them after the group's first `fetched`.

There are three groups of three-or-more in the whole corpus, at any window, and
none of them survives contact:

- **×4, spanning 33 hours** — `Bitcoin Edges Higher as U.S. Stock Futures Rise —
  Market Talk`, all four Dow Jones Newswires. One outlet, four times, over a day
  and a half. Not a burst.
- **×3, spanning 3.4 hours** — `Rate hike bets leave yen's post-intervention
  gains at BOJ's mercy`, Reuters and Investing. Tagged to no instrument we price
  locally.
- **×3, spanning 2.6 hours** — `Yen's weekly loss puts more intervention on
  traders' radar`, Reuters and Investing. Resolves to two instruments at once.

**The test as specified cannot be run. That is the result.**

### The weakest version that has any data, and its answer

Splitting at one versus **two or more** instead, and measuring on the honest
unit — the distinct `(instrument, minute)` cell an excursion is actually
computed over, not the group, since the 500 measurable groups — singletons
included, which is nearly all of them — collapse onto 47 such cells:

| | cells | median 1h max excursion |
|---|---|---|
| singleton | 40 | 21.4 bps |
| restated ≥2 | **7** | 38.8 bps |

Uncontrolled, that is +17.4 bps and a permutation p of 0.016 over 20,000 label
shuffles. It is also meaningless, for three separate reasons.

**First, it is instrument composition.** All seven restated cells are BTC. The
singleton cells are 28 BTC, 4 GBPUSD, 3 EURUSD, 3 SPX500, 2 gold. The
unconditional hourly excursion is not remotely comparable across those:

| | btc | gold | us100 | spx500 | gbpusd | eurusd |
|---|---|---|---|---|---|---|
| median 1h max excursion | 23.5 | 23.9 | 11.7 | 5.8 | 4.4 | 4.1 bps |

Comparing a bag of BTC against a bag containing EURUSD is comparing instruments,
not restatements. **Within BTC alone**: restated n=7 median 38.8 bps, singleton
n=28 median 24.0 bps, +14.8 bps, p=0.048. Removing the cold-start burst:
restated n=6 median 41.5 bps, +17.5 bps, p=0.033. A one-sided permutation test
on six observations does not establish anything, and a p just under 0.05 from
n=6 is what a null looks like a twentieth of the time.

**Second, the seven cells are not seven observations.** Four of them fall inside
seventy-five minutes on one afternoon — 2026-08-14, 14:22 to 15:37 UTC, around
the US inflation print — and their hour-long measurement windows overlap, so
they read the same BTC price path several times. Taken greedily, the seven cells
reduce to **five non-overlapping hours**, two of which are that same afternoon.
That is the real denominator.

**Third, and fatally: every restated group being tested is a collection
artefact.** All fourteen restated BTC groups are either CoinTelegraph counted
twice (RSS plus TradingView relay) or Dow Jones Market Talk republished inside
TradingView. Not one is two independent outlets. Whatever this measures, it is
not crowding — it is that CoinTelegraph publishes more about Bitcoin when
Bitcoin is moving, observed through a duplicate.

One control is worth recording because it is a clean null in its own right:
**BTC cells carrying a singleton tagged headline have a median excursion of 24.0
bps against an unconditional 23.5 bps.** On this corpus, a tagged headline
arriving tells you nothing at all about the next hour.

**Verdict on the first falsification: not run, and not runnable today.** The
≥3 cell is empty and the ≥2 cell is five non-overlapping BTC hours drawn from
two relay paths. This is a sample-size finding, not a null result, and it should
not be reported as either the claim confirmed or the claim refuted.

## 4. The look-ahead trap, corrected

[news-models.md](news-models.md) says: keep the first copy by `fetched`, record
the duplicates as a count, because the fuller copy usually arrives later and
stamping it with the earlier timestamp imports the future into the past. **The
hazard is real and the measurement confirms it** — in 41 of 105 duplicate
groups the later copy carries more symbols, and among the 55 CoinTelegraph
pairs the RSS copy arrives first 54 times while it is the TradingView copy that
carries the symbol tags.

But the rule as written throws away the only thing that routes a headline to an
instrument. **In 34 of 55 CoinTelegraph pairs, keeping the first copy discards
symbols that exist only on the second.** Without those tags the story is
untaggable, and half the corpus is already untaggable.

The measurement supplies the fix. **41 of the 55 relay pairs arrive in the same
poll** — lag under one second, because `fetched` is a batch stamp — and 50 of
all 105 duplicate groups do. Within one poll there is no future to import: both
copies were known at the same instant. So the honest rule is finer than
first-wins:

> Stamp the record with `min(fetched)`. Merge fields freely across copies whose
> `fetched` equals that same poll. A copy from a **later** poll contributes only
> to the restatement count, never a field.

That recovers 27 of the 41 groups where symbols would otherwise be lost, and it
is point-in-time correct by construction rather than by convention. The
remaining 14 stay lossy, and correctly so.

## What could not be measured

- **Eight of the fourteen tracked instruments have no local 1m bars.** Only
  `btc`, `eurusd`, `gbpusd`, `gold`, `spx500` and `us100` are present.
  `usdjpy` is the fourth most-mentioned instrument in the news table — 208
  articles, behind `btc` at 319, `eurusd` at 274 and `gbpusd` at 229 — and
  there is nothing to measure it against. Of 1,267 symbol-carrying rows,
  700 resolve onto a locally priced instrument and 524 onto exactly one.
- **RSS rows carry no symbols at all.** The CoinTelegraph relay pairs are only
  measurable because the TradingView half supplies the tags. Every duplicate
  group made purely of RSS rows is invisible to any price test.
- **Direction.** Excursion here is unsigned. With six observations a signed test
  would be theatre.
- **Restatement across genuinely independent outlets.** No such event exists in
  this corpus, so its effect on price is not merely unmeasured — it is
  unobserved.
- **Whether more collection fixes this.** Duplicates arrive at roughly 105
  groups per 45 hours, but the *composition* is the problem, not the rate. More
  weeks of the same six sources will produce more CoinTelegraph relay pairs and
  no more independent restatements. What would change the answer is adding
  outlets that are not already relayed by TradingView.

## Order of work

1. **Implement the fingerprint, run it at d=0, and treat it as hygiene.** 8
   bytes a row, no dependency, and it stops the same story being counted twice
   by whatever consumes the stream. Do not set a threshold above zero on this
   corpus, and do not reach for MinHash — the measured problem is precision, not
   recall, and MinHash does not help with precision.
2. **Adopt the same-poll merge rule** above rather than plain first-wins, or
   deduplication will silently delete the symbol tags on the largest duplicate
   family in the corpus.
3. **Store the restatement count anyway**, because it is free once the groups
   exist and it will become testable if the source list ever grows. Store it
   next to the count of *distinct outlets*, which is the quantity the crowding
   hypothesis was actually about and which is 1 for 89% of groups today.
4. **Do not promote the restatement count to a feature.** It is currently a
   measurement of our own collection topology. Journalling it costs nothing;
   trading it would be trading the shape of `sources`.
5. **Re-run §3 when there are groups of three or more spanning three or more
   outlets.** Today there are none. That is the trigger, and it is a collection
   question, not a modelling one.

This is the same shape as [behaviours.md](behaviours.md): the idea was
falsifiable, the falsification was cheap, and it came back saying the corpus
cannot support the claim yet and that the mechanism behind it was misread. A
null that arrives before the feature is built is the cheapest one available.
