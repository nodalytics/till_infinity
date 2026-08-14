# Models for news, and which of them this box can run

A survey of the model families that could turn stored headlines into features,
checked against the schema in [news.md](news.md) and against the machine the
thing actually runs on. Written because the interesting question is not "what is
the best news model" — that is answered every six months by somebody with a GPU
— but "what can be run inside 640MB alongside everything else, learned online,
and graded against realised outcomes".

Nothing below is built. The shape of the document follows
[behaviours.md](behaviours.md): map the idea onto what already exists, say
plainly where the data is missing, and end with an ordered list.

## What is measured here

The counts in this document are not illustrative. They come from
`.data/news/news.db` on **2026-08-14**, and every one of them is reproducible:

```sql
SELECT source, COUNT(*), SUM(symbols != '[]'), SUM(summary != '') FROM articles GROUP BY source;
SELECT COUNT(*) FROM articles WHERE published < fetched - 86400;
SELECT COUNT(*) FROM events WHERE actual NOT IN ('') AND forecast NOT IN ('');
```

The corpus at that moment: **2,241 articles** and **573 calendar events**,
collected over roughly 37 hours of wall clock. It is small, and several
conclusions below turn on how small it is. Re-run the queries before trusting
any ratio quoted here; a month of collection may change them.

## The honest constraints, stated once

**The box is small.** The operating envelope is ~640MB of memory with ~232MB
already resident, CPU sitting near 8.5%, and 2.1GB of free disk. That leaves on
the order of 400MB of headroom for *everything* — a model, its runtime, its
tokeniser, and the working set of whatever else the process is doing. A 400MB
checkpoint does not fit. It does not nearly fit. This single number removes most
of the published literature from consideration, and it does so before any
argument about accuracy.

**Dependencies are deliberately lean.** `river` is the only ML dependency in
`pyproject.toml`. There is no torch, no transformers, no sentence-transformers,
and adding one is not free: the wheel competes for the same 2.1GB as the data
directory, which is already at 104MB and growing with every poll. A dependency
is a permanent cost paid for a benefit that has to be demonstrated first.

**Online beats batch.** Everything in [structures.md](structures.md) is
`learn_one`/`predict_one` over a stream, with state files that refuse to load
into a version mismatch rather than silently half-restoring. A news model that
requires a nightly batch fit over the whole corpus does not fit that shape and
should not pretend to.

**Point-in-time correctness is sacred**, and news is where it is easiest to
lose. Each candidate below carries its own look-ahead note. Two hazards are
general enough to state up front, and both are visible in the data:

- **`published` is not when we knew.** 650 of 2,241 articles have a `published`
  timestamp more than a day older than `fetched`; 330 are more than a week
  older, and the oldest is from **2023-12-04** — collected in August 2026.
  Almost all of it is TradingView: **643 of its 1,378 rows**, 47% of the
  single most valuable feed, is backfill. Any window built on `published`
  silently includes stories we had not seen. `fetched` is the honest clock, and
  it is written to SQLite but is absent from the `Article` model and from
  `latest_articles`, so today it is only reachable by raw SQL.
- **The calendar rewrites itself.** The SQLite upsert overwrites `actual`,
  `forecast` and `previous` in place. A surprise computed from that row next
  month may use a *revised* actual the market never traded against. The JSONL
  store appends rather than edits — but it only appends when `actual` changes,
  so a forecast that moved in the week before the print leaves no trace
  anywhere. **There is currently no point-in-time record of what the forecast
  was.** That is a collection bug to fix before it is a modelling problem.

**Everything must be gradeable.** A sentiment score that nobody can check is
worse than no score, because it looks like information. The outcome machinery in
[journal.md](journal.md) grades a decision against what followed it, and that is
the test every candidate here has to survive — not a benchmark number from a
paper trained on 10-K filings.

## What the data actually is

Four properties of the stored schema decide most of what follows. They are all
in [models.py](../till_infinity/news/models.py) and all confirmed against the
live store.

**There is no body text — and usually no summary either.** `Article` holds
`title`, `summary`, `url`, `provider`, `symbols`, `urgency`. **1,861 of 2,241
rows (83%) have an empty summary**, and the split is clean by source: FXStreet,
ForexLive, CoinDesk and CoinTelegraph supply one; Investing and TradingView
supply none at all. So for five rows in six, the entire text is a title
averaging **67 characters**. Every model below is operating on one short
sentence. That is not a fatal problem — headlines are what move prices in the
first minute — but it rules out anything that needs a document, and it means
window sizes and vocabularies should be chosen for a sentence, not an article.

**Symbols come from exactly one feed, and they are not normalised.** All 1,147
symbol-tagged articles are TradingView's; the 866 RSS rows carry none.
Worse, those 1,147 rows reference **579 distinct symbol strings** for a universe
of eight tracked instruments, because the venue prefix varies:
`FX:EURUSD`, `BITSTAMP:EURUSD` and `FTMO_OANDA:EURUSD.SIM` are one instrument;
`FX:USDJPY` and `FX_IDC:USDJPY` are another; `ICEUS:DXY` and `TVC:DXY` a third.
[news.md](news.md) says TradingView headlines "line up against the gold series
without a keyword search", and that is true only after this normalisation, which
nothing currently does.

**`urgency` is very nearly a constant.** 1,362 rows carry `2`, thirteen carry
`1`, and 866 carry nothing at all because RSS does not supply it. A feature
with that distribution has almost no information in it, and should not be
mistaken for a priority signal until a month of data says otherwise.

**The calendar is data-starved.** 573 events, but only 145 carry a forecast and
116 an actual, and only **57 have both as parseable numbers**. Those 573 rows
span **410 distinct event titles** — an average of 1.4 observations per event
type. Section 6 turns on this number.

## The candidates

### 1. Sentiment and tone

**The question that has to be answered first:** is general-purpose sentiment
worth anything on a financial wire? Largely no, and the reason is structural
rather than a matter of model quality. General sentiment models are trained to
detect *affect* — is the writer pleased. A wire headline has almost no affect;
it has direction and magnitude. "Fed holds rates, signals two cuts" carries no
sentiment in the ordinary sense and enormous information. Meanwhile the words a
general model treats as negative — *liability*, *tax*, *cost*, *decline* — are
neutral vocabulary in finance. That observation is the entire origin of the
Loughran-McDonald work: general-purpose word lists misclassify financial text
systematically, not randomly
([sraf.nd.edu](https://sraf.nd.edu/loughranmcdonald-master-dictionary/)).

**FinBERT is the obvious candidate and it does not fit.** The checkpoint on
Hugging Face is **437,992,753 bytes** for `pytorch_model.bin`
([HF API](https://huggingface.co/api/models/ProsusAI/finbert?blobs=true)) — 418
MiB, against roughly 400MB of total headroom, before the torch and transformers
wheels that are needed to execute it and before any activation memory. It is a
BERT-base classifier fine-tuned on the Financial PhraseBank for
positive/negative/neutral ([model card](https://huggingface.co/ProsusAI/finbert)).
I have not verified the CPU wheel sizes for torch and transformers and will not
guess at them; the checkpoint alone already settles it. **Disqualified on
footprint, not on merit.**

**Loughran-McDonald is a lexicon, and lexicons are free.** The master dictionary
tags words as negative, positive, litigious, uncertainty, constraining or
superfluous ([SRAF](https://sraf.nd.edu/loughranmcdonald-master-dictionary/)).
Scoring a headline is a set intersection over ~67 characters: microseconds, a
few megabytes of resident dictionary, no dependency beyond a data file. Two
cautions. First, it was built for **10-K filings and earnings calls**, not FX
wires and crypto — the *uncertainty* and *constraining* lists may transfer
better than the polarity ones, and that is an empirical question the journal can
settle. Second, it is **free for academic research; commercial use requires a
licence** from the authors. That is a real check to perform before shipping,
not a footnote.

**VADER** is the general-purpose lexicon usually reached for. I have not
verified its footprint or its behaviour on financial text, so I am marking it
**unverified** rather than quoting numbers. My expectation is that it will
underperform Loughran-McDonald here for the reason above, and that expectation is
cheap to test: score the same headlines with both, and grade both against the
realised move.

**Look-ahead hazard:** low, provided the lexicon is fixed. It becomes severe the
moment anyone "tunes" the word list against outcomes already observed — that is
fitting labels to the future and calling it a dictionary.

**Grading:** score every headline, bucket by score, and compare the realised
volatility and direction of the tagged instrument over the following 5, 15 and
60 minutes against the unconditional distribution. If the buckets do not
separate, the lexicon carries nothing and the finding is worth as much as a
positive one.

### 2. Entity recognition and linking

**Without this, nothing routes.** A sentiment score attached to no instrument is
not a feature.

**This is a lookup table, not a model.** The measured shape of the problem is
579 symbol strings collapsing onto eight instruments, plus 866 untagged RSS
rows. The first half is a normalisation map — strip the venue prefix, alias
`XAUUSD`/`GOLD` to `gold`, `BTCUSD` to `btc`, and drop what is not tracked. The
pattern already exists: [prices/config.py](../till_infinity/prices/config.py)
carries an alias map that folds `nas100`, `nasdaq`, `ndx` and `nq` onto `us100`.
The news side needs the same table, and it should be *the same table*, or the two
halves of the project will disagree about what "gold" means.

The second half — the 866 untagged rows — is keyword matching over a 67-character
title, and it should stay that dumb. A statistical NER model buys nothing here:
the entity set is closed and has eight members. The real difficulty is not
recognition but **disambiguation of macro stories**, which is where the value
is: "Dollar firms after hot CPI" mentions no tracked instrument and is relevant
to `eurusd`, `gbpusd`, `gold` and `us100` at once. A currency-to-instrument
expansion table handles that deterministically and is auditable when it is wrong.

**Look-ahead hazard:** none in the mapping itself. It appears if the keyword
list is grown by reading which stories preceded big moves.

**Grading:** precision is checkable by hand on a hundred rows in an afternoon.
Recall is checkable against the TradingView symbols we already have — run the
keyword matcher on those 1,147 rows and see how much of the truth it recovers.
That is a free labelled set, and it is the reason to build the matcher second
rather than first.

### 3. Near-duplicate detection and clustering

**This is the cheapest real win available, and the data already proves it.**
Normalising titles to lowercase alphanumerics and grouping produces **83 exact
collision groups covering 170 rows — 7.6% of the corpus — of which 52 groups
span more than one source.** The dominant pattern is a story arriving twice: once
from CoinTelegraph's own RSS feed and once from TradingView relaying
CoinTelegraph, with identical text and different ids. `INSERT OR IGNORE` keyed
on `(source, id)` cannot see this, and correctly so — it is doing its job.

That 7.6% is a floor, found by *exact* match after trivial normalisation. It
costs one `GROUP BY`. Anything cleverer is an increment on top of a number we
already know is non-zero.

**SimHash before MinHash.** For a 67-character title, SimHash over word shingles
gives a 64-bit fingerprint per article — **8 bytes**, so the entire corpus is
18KB and a hundred thousand articles is 800KB — and near-duplicates are Hamming
distance over integers. It needs no dependency at all: hashing and popcount are
in the standard library. MinHash is the better-characterised tool and
`datasketch` supports it well: the default 128 permutations give a Jaccard
sampling error of roughly 0.03–0.04, and memory grows linearly at one hash value
per permutation
([datasketch docs](https://ekzhu.com/datasketch/minhash.html)) — 512 bytes per
document at the 32-bit default, so ~1.1MB for the current corpus and ~51MB at
100k documents. That is affordable but it is a new dependency and 60× the memory
of SimHash, and on a one-sentence document the shingle set is small enough that
the estimator's variance matters. **Start with SimHash; reach for MinHash only
if measured recall on the 52 known cross-source groups is inadequate.**

Clustering proper — grouping the fifth restatement with the first — is
`river.cluster` territory (DBSTREAM and CluStream are both online, both shipped)
but it is premature. A fingerprint plus a time window answers the question that
matters now.

**Look-ahead hazard:** the trap is subtle and worth naming, because it nearly
catches everyone. It is tempting to keep the *best* copy of a duplicated story —
the one with a summary, or the richer symbol list. But the fuller copy usually
arrives later. Keeping it and stamping it with the earlier timestamp imports
information from the future into the past. **Keep the first copy by `fetched`,
and record the duplicates as a count.**

**Grading:** the count itself is the feature, and it is immediately gradeable.
"This story has been restated eleven times in twenty minutes across five wires"
is a crowding measurement, and the hypothesis — that heavily restated stories
precede larger moves than singletons — is testable against the journal with no
new collection whatsoever.

### 4. Novelty and surprise

Novelty is what §3 gives you once the duplicates are counted: is this the first
telling or the fifth? The naive version is one number — inverse cluster size
within a window — and it should be tried before anything else, because it costs
nothing on top of work already done.

The less naive version measures novelty against the *recent stream* rather than
against exact copies: how unusual is this headline's vocabulary compared with the
last few hours. `river.feature_extraction.TFIDF` maintains term statistics
online and is already installed, so a per-headline surprise score is a few lines
over machinery that exists. It handles the case §3 misses — a genuinely new story
that shares no shingles with anything but is phrased in familiar language.

**Look-ahead hazard:** the IDF statistics must be updated **only from headlines
already seen**. A batch TF-IDF fit over the whole table gives every historical
headline a novelty score computed partly from its own future, and the resulting
backtest will look excellent. This is the same failure as the smoothed-versus-
filtered HMM estimate in [structures.md](structures.md), and it is worth
recognising as a recurring shape rather than a one-off.

**Grading:** journal the novelty score with each detection and compare realised
excursion for high-novelty against low-novelty stories on the same instrument.

### 5. Event and relation extraction

A typed event — `{kind: rate_decision, entity: FOMC, direction: hold}` — is
strictly more useful than a sentiment scalar, because it can be joined to the
calendar and to the levels model rather than merely correlated with returns. A
CPI print, an exchange hack and an ETF flow move different instruments in
different directions on different horizons, and collapsing all three onto one
number in [-1, +1] discards exactly the part that is tradeable.

**The honest position: this is the right target and the wrong next step.**
Supervised extraction needs typed labels, and there are none in the schema and
none in the store. A rule-based extractor over 67-character titles is genuinely
viable for a small closed taxonomy — perhaps a dozen types, matched on trigger
phrases — and would be the cheap first version. But its quality cannot be
established without a labelled sample, and producing that sample is the actual
cost. §8 is the plausible route to it: use an LLM to label a few thousand
headlines *once*, then use that set to test whether the rules are good enough to
run alone.

**Look-ahead hazard:** high and easy to miss. If the event taxonomy is designed
by looking at which stories preceded large moves, the taxonomy is fitted to the
outcome and every subsequent evaluation is circular. The types must be defined
from domain knowledge before any outcome is consulted.

### 6. Calendar surprise

This is the one candidate whose feature is already half-built. `Event.surprise`
is a property on the model — actual minus forecast, once both parse — and
`parse_number` already handles the `220K` / `-1.2%` shapes the feeds emit
([models.py](../till_infinity/news/models.py)). `importance` is normalised to
LOW/MEDIUM/HIGH across two providers that word it differently.

**Raw surprise is not comparable across events**, and the store shows why: of
573 rows, 316 carry no unit at all, 233 are percentages, and the rest are six
different currencies. A 0.2 miss on core CPI and a 0.2 miss on a PMI are not the
same event. The standard fix is to divide by the historical dispersion of that
event's own surprises — a z-score per event type, which is exactly what
`river.stats.RollingQuantile` and friends are for, and exactly the move that
[structures.md](structures.md) recommends for grading regime change.

**And we cannot do it yet.** Only **57 events** have both a numeric actual and a
numeric forecast, spread across **410 distinct titles**. There is not enough
history to estimate a dispersion for any single event type — not close. Two
things have to happen first, in this order:

1. **Fix the point-in-time record**, per the constraint stated above. Today the
   forecast that gets stored is whatever was current at the last poll, and a
   forecast that moved before the print leaves no trace. A surprise computed
   against a forecast we never actually held is not a surprise.
2. **Collect.** High-impact releases arrive at a rate of a few dozen a month;
   a usable per-event dispersion needs quarters, not weeks. `NEWS_CAL_BACK_DAYS`
   controls how far back each poll reaches and is the only lever on how fast
   this fills.

In the meantime the *raw* surprise, sign only, on the ~50 high-importance events
is worth journalling. Sign is unit-free, which sidesteps the whole problem, and
it starts accumulating the record that the standardised version will need.

**Look-ahead hazard:** the worst in this document, and the reason for the
ordering above. Both `actual` and `previous` are revised, and the SQLite row is
rewritten in place. Backtesting against the current table means trading on
revised figures — a leak that is invisible, produces beautiful results, and is
the precise failure the journal's copied-in `context` was designed to prevent.

### 7. Embeddings

Small sentence encoders are the general-purpose answer to §§1, 3 and 4 at once.
`all-MiniLM-L6-v2` is the standard small model: **22.7M parameters**, 384
dimensions, 256-wordpiece maximum sequence
([model card](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2)) —
roughly 91MB at float32 by arithmetic, which is a size the box could survive.
The problem is not the checkpoint, it is that executing it requires torch or
onnxruntime, and that wheel is the real cost against 2.1GB of disk.

Static embeddings avoid the runtime entirely. Model2Vec distils a sentence
transformer into a token-lookup table, so inference is an embedding lookup and a
mean — numpy, no framework. `potion-base-8M` is reported at ~7.56M parameters
with a 30k vocabulary and 384 dimensions, giving roughly 30MB at float32
([model2vec](https://github.com/MinishLab/model2vec)). **I am marking the
parameter count and the quoted ~1.7ms latency unverified** — they came from an
aggregator page rather than the primary source, and the arithmetic above is mine.
If this line is pursued, read the sizes off the model repository directly.

**Do embeddings beat hashing here?** For near-duplicate detection on 67
characters, almost certainly not: SimHash finds near-identical text more cheaply
and more interpretably, and §3's measured 7.6% is available today for free.
Embeddings earn their place at *semantic* clustering — recognising that "ETF
inflows hit record" and "Institutional demand surges" are the same story — which
is a real capability that hashing cannot deliver. That is a second-order want.
The honest sequence is to ship hashing, measure how many genuine duplicates it
misses, and only then decide whether the misses justify a dependency.

**Look-ahead hazard:** low for a frozen pretrained encoder — its training data
predates our stream. It reappears if any downstream classifier is fitted in
batch over embeddings of the whole corpus.

### 8. LLM extraction via the existing agents module

The infrastructure exists. [agents/](../till_infinity/agents/) is built on
pydantic-ai with providers for Anthropic, Google, Groq and the OpenAI wire
format, model selection is `provider:model` with Claude as the default, and the
roles/tools plumbing is described in [agents.md](agents.md). Adding a headline
extractor is a role, not a subsystem — and crucially, **it moves the compute off
the box entirely**, which makes every footprint objection above irrelevant.

**The cost, computed rather than asserted.** Current collection is 2,241
articles over ~37 hours, so roughly **1,450 a day** — an upper bound, since the
first pass included backfill. A short system prompt plus a 67-character title
and a structured reply is on the order of 350 input and 60 output tokens; **that
token estimate is mine and unverified**, and it is the number to check with a
token counter before believing any figure below it. At Claude Haiku 4.5 rates of
$1 per million input and $5 per million output tokens, that is about **$0.95 a
day, or roughly $29 a month**, to type every headline that arrives. At Opus
rates it is about 5× that on input and 5× on output.

**Groq changes the arithmetic and introduces a different limit.** Third-party
summaries put the free tier at 30 requests per minute, 6,000 tokens per minute
and 14,400 requests per day
([TokenMix](https://tokenmix.ai/blog/groq-free-tier-limits-2026)) — **unverified
against Groq's own documentation, and worth checking before depending on it.**
If those figures are right, the binding constraint is tokens, not requests: at
~410 tokens per call, 6,000 TPM allows about 15 calls a minute, half the request
allowance. Our average is one headline a minute, so the steady state fits
comfortably — but news does not arrive at the average rate. It arrives in bursts
around releases, which is precisely when the extraction is worth having.

**The three real objections.**

- **Latency.** A network round trip is seconds. That is irrelevant for a
  nightly labelling job and disqualifying for anything on the alerting path.
- **Non-determinism.** The same headline can yield different output on different
  days. For a *feature* that is corrosive: the model downstream cannot tell a
  change in the world from a change in the labeller. Structured output with a
  fixed schema and a pinned model version narrows it; it does not close it.
- **It is an external dependency on the critical path**, which the rest of this
  project conspicuously avoids — every source has retries, every store has a
  fallback, and adding a paid API between a headline and a feature is a
  reliability regression.

**The use that survives all three is offline labelling.** Run the LLM once over
the stored corpus to produce typed events (§5), then train or write something
small and deterministic against those labels and run *that* on the box. The
labels are a fixed artefact, gradeable, reproducible, and costing $29 once
rather than $29 a month.

**Look-ahead hazard:** severe and non-obvious. These models were trained on text
that includes the period being labelled. Ask one to classify a 2024 headline and
it may know how the story ended. Labels produced this way are contaminated for
any historical evaluation, and the only clean use is labelling headlines from
*after* the model's training cutoff — which means recording the model version
alongside every label, and treating the cutoff as part of the dataset's
metadata.

## Where the derived data would live

One structural note, because getting it wrong is expensive later. **`articles` is
immutable by design** — `INSERT OR IGNORE` on `(source, id)`, re-polling writes
nothing. Adding a `sentiment` column and updating rows in place would break that
property and destroy the ability to reconstruct what was known when.

Derived annotations belong in a **separate, append-only table keyed on
`(source, id, model, version)`**, with its own timestamp for when the annotation
was computed. That way re-scoring with a better lexicon adds rows rather than
overwriting history, two models can be compared on the same headline, and the
question "what did we believe about this story at 14:32" has an answer. It is the
same discipline as the journal's copied-in context, applied one layer down.

## Order of work

Cheapest useful first, and each step's output is the next step's input.

1. **Near-duplicate detection by SimHash.** 7.6% of the corpus is already
   provably duplicated, and finding it needs no dependency, no checkpoint and no
   labels. The restatement count is a feature on its own and immediately
   gradeable against the journal. Nothing else here has that ratio of value to
   cost.
2. **Symbol normalisation, sharing the alias map with prices.** 579 strings onto
   eight instruments. Without it nothing routes, and it is a table.
3. **Keyword matching for the 866 untagged rows**, validated against
   TradingView's 1,147 tagged ones — a free labelled set that will not exist
   again once we start relying on the matcher.
4. **Fix the calendar's point-in-time record**, so a forecast revision leaves a
   trace. This is a collection change, it is small, and every month it is
   deferred is a month of unusable surprise history. It must land before §6 is
   worth attempting, not after.
5. **Loughran-McDonald tone**, checking the commercial licence first, and graded
   honestly — including the honest possibility that a lexicon built for 10-K
   filings tells us nothing about FX wires, which is a useful thing to learn.
6. **Novelty via online TF-IDF**, once duplicates are handled and the residual
   is genuinely-new stories rather than restatements.
7. **A one-off LLM labelling pass** for typed events, once there is enough
   corpus to justify it and with the training-cutoff contamination recorded.
8. **Calendar surprise, standardised** — only when there are enough observations
   per event type to estimate a dispersion. Today there are 57 usable rows
   across 410 titles. That is a collection problem wearing a modelling costume.

## What would falsify the top recommendation

The claim behind §1 of that list is: *stories restated across many wires in a
short window precede larger moves than singletons do.* It is falsifiable now,
without any new collection.

Group headlines by fingerprint within a 30-minute window, split at a restatement
count of one versus three or more, and compare the realised excursion on the
tagged instrument over the following hour against the unconditional
distribution. **If the two distributions do not separate, the restatement count
is not a feature** — and the deduplication is still worth keeping, because it
stops the same story being counted five times by whatever consumes the stream,
but it drops from "highest-value cheap win" to "hygiene", and §5 or §6 should be
promoted above it.

A second, sharper falsification: if the 83 duplicate groups turn out to be
overwhelmingly one relay path — CoinTelegraph via TradingView, which is what the
sample suggests — then the "crowding" interpretation is wrong. It is not many
outlets independently judging a story important; it is one outlet counted twice
by our own collection. That would make deduplication a **data-quality fix**
rather than a signal, and the honest response is to say so and move on.

## What I would not do

**FinBERT, or any transformer checkpoint on this box.** 418MB against ~400MB of
headroom settles it before the runtime is even discussed. This is not a close
call and revisiting it is a waste of an afternoon.

**Adding torch for anything.** If a neural model becomes genuinely necessary, the
route is a static embedding table (numpy only) or an ONNX export — not the
training framework.

**A general-purpose sentiment model on financial wires.** The vocabulary
mismatch is structural, not a matter of tuning, and the finance-specific lexicon
is cheaper anyway.

**A statistical NER model.** Eight entities, closed set, one-sentence documents.
A dictionary wins and can be corrected by hand when it is wrong.

**An LLM on the alerting path.** Latency, non-determinism and an external
dependency between a headline and a feature. Offline, once, producing a fixed
artefact — that is the shape that fits.

**Standardised calendar surprise, this month.** Not because it is wrong, but
because 57 observations across 410 event types cannot support it, and building it
now would produce a number that looks like a z-score and is noise. Collect first.

Everything above is unbuilt and ungraded. The reason to write it down is the same
as in [behaviours.md](behaviours.md): the outcome machinery can settle each one,
and an idea that can be settled is worth more than an idea that sounds right.
