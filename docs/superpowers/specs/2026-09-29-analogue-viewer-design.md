# The analogue viewer: a design

A web app that shows, for a symbol and interval, the historical windows most like the
present one and the distribution of what followed them — with every number carrying the
control that says whether it means anything.

Requested 2026-09-29: "something similar to `aipricepatterns.com/candles?symbol=BTCUSDT&
interval=1h&q=5&f=5`, but instead of that dry design a sleek looking theme", built with
**Next.js**, as a **web app**, with **mobile/responsive support**.

**Status: design only.** Nothing here is built. The instruction was "just document it for
now", so this records the design and the one decision that blocks implementation.

## What this is for

The reference site is a pattern-analogue workspace: pick a symbol and interval, give it a
query window of `q` bars, and it finds the most similar past windows and shows the next
`f` bars of each, aggregated into a P10/P50/P90 envelope. It marks every message
`NO_TRADE` and concedes the direction is a coin, and it publishes to a telegram channel -
our own harness counts "sixteen published messages" from it.

We are not short of a chart. What this repository has that the reference does not is
**the measurements underneath the claim**, and three of them are already on the record:

| question | what we measured | where |
| --- | --- | --- |
| does the distance order neighbours better than chance? | **AUC 0.4921** at 300–1,800s against 0.5000 shuffled; flat at every horizon the desk trades | [`similarity.md`](../../../research/docs/similarity.md) |
| do analogue shapes predict direction? | chance, twice — `motifs.py` died on bootstrap, `shapes.py` came out at chance at two embeddings | `analogue_envelope.py` header |
| is the next-N-bars **range** forecastable? | **yes, and it is shipped** — percentiles that hold their stated rates, with drift correction | [`envelope.md`](../../../research/docs/envelope.md), `structures/vol/envelope.py` |

And a fourth that is set up but never run: [`analogue_envelope.py`](../../../research/harness/analogue_envelope.py)
was written **about this exact service** — five-bar window, ten twins, five bars forward,
`NO_TRADE`, published match scores "from 59% down to 9%" — to ask whether its envelope is
tighter than a trailing sigma at equal coverage. Its own framing:

> *"If the analogue envelope is no tighter at equal coverage, the nearest-neighbour
> machinery is decoration on a volatility estimate, and the honest description of the
> service is 'a trailing sigma with extra steps'."*

The harness is committed. There is no write-up and no sign it was ever run. **That is the
prerequisite**, not a nice-to-have: it decides whether the analogue panel is a forecast or
an exhibit. See *Phase 0*.

So the product thesis inverts the reference:

1. **Range is the headline.** It is the part that measures up, and it is already shipped
   and calibrated in production.
2. **Direction is labelled a coin, prominently**, because we have measured it twice.
3. **Every panel carries its control.** A P50 with no null beside it is decoration; a
   match score of 9% presented as a "match" is a lie of omission. This is the one thing
   that cannot be copied without doing the work, and it is the product.

That third point is a **design constraint, not a disclaimer**. It drives the layout.

## Audience: assumed, and the one blocking decision

The audience question was asked and deferred. Implementation cannot start without it,
because it decides hosting, authentication, and which data may leave the lab.

**Assumed for this design: private now, public-ready later.** Build for one operator, but
put the data boundary and the theme tokens where a public landing page and shareable links
drop in without a rewrite. This assumption is load-bearing in exactly two places — the
*Data boundary* section and *Phase 3* — and both are written so that choosing "private
forever" deletes work rather than redoing it.

If the answer turns out to be **public**, three things change and none of them are cosmetic:
broker bar redistribution may be licensed rather than ours to publish; the symbol universe
probably narrows to the Deriv synthetics, which we can characterise freely; and rate
limiting and abuse handling stop being optional. Flagged, not solved.

## Approaches considered

**A. Next.js frontend + a new read-only Python API. Recommended.**
The analogue search, the envelope and every control already exist in Python, measured and
tested. A thin FastAPI service exposes them as JSON; Next.js renders. One new service, no
algorithm is written twice, and the numbers on screen are the numbers the desk uses.
FastAPI because the MT5 bridge in the sibling repo already uses it — no new framework
enters the estate.

**B. Next.js only, computing analogues in TypeScript.**
Rejected. It reimplements `similarity.py`, `envelope.py` and the causality guard in a
second language, and the guard is the part the harness calls "the whole difficulty". Two
implementations of a leakage rule is one implementation and one liability.

**C. Next.js reading precomputed static JSON, no API at all.**
Rejected as the destination, adopted as a mechanism. A nightly job writing JSON is how the
*heavy* work gets off the request path (see *Where compute runs*), but as the whole
architecture it cannot serve an arbitrary `?symbol=&q=&f=` without precomputing every
combination.

## Architecture

```
web/                          Next.js 15, App Router, TypeScript, Tailwind
  app/
    page.tsx                  landing (public-ready; trivial while private)
    candles/page.tsx          the viewer, SSR for shareable links
  components/
    chart/                    candles + envelope cone + analogue overlay
    panels/                   match strip, distribution, coverage, control toggle
  lib/api.ts                  the one typed client for the API below

till_infinity/web/            new package, read-only
  api.py                      FastAPI app; routes only, no computation
  panels.py                   assembles a response from existing modules
  cache.py                    keyed by (symbol, interval, q, f, as_of)
  boundary.py                 the allowlist; the only place that names a data source
```

The API imports from `structures/vol/` and `research/harness/`. Nothing in
`till_infinity/web/` computes a statistic of its own — if a number needs deriving, it is
derived in the module that owns it and the API asks for it. That keeps the viewer honest by
construction: it can only show what the desk has measured.

### Where compute runs

**Never on the production instance.** It has two cores and about a gigabyte spare, and has
been OOM-killed sixty-three times. `structures/vol/analogue.py` says so in its own header:
a Mondrian forest was rejected at 46MB per model, and attention over four hundred series
"would be orders of magnitude worse".

So the split is:

* **Live envelope readings** are free. The structures service already computes them —
  `Book.reading(feed, interval, price)` returns the percentile prices, and `card_lines`
  already formats them. The API reads what exists; it does not recompute.
* **Analogue searches are not free.** A `q`-bar query against years of bars, per request,
  is a scan. These run **on the lab** as a job that writes a panel per
  `(symbol, interval, q, f)` on the interval's own cadence, and the API serves the written
  panel. A request for a combination not yet computed gets a 202 and a queued job, not a
  scan on the production box.
* **The one exception** is a replay/step request against an already-loaded window, which is
  bounded by the window and may be computed inline.

### Data boundary

`boundary.py` is an allowlist, and it exists because this repository is public and the
desk's own state is not.

**May be served:** OHLC bars for the allowlisted symbol universe; envelope percentiles and
their realised coverage; analogue windows, distances and forward paths; every control and
null; the research docs' own published figures.

**Must never be reachable from the web service:** the trade journal, positions, order
history, account balances or equity, credentials of any kind, the contents of the
gitignored secrets directory, and anything identifying the broker account. The web service
gets its own read-only mount and a redis user that can subscribe to price and structure
channels and nothing else. It does not open the desk's SQLite journal — not read-only, not
at all. A viewer that can see the book is a viewer that can leak the book.

### The URL contract

Mirrors the reference so a link from either is legible:

```
/candles?symbol=BTCUSDT&interval=1h&q=5&f=5
         symbol   an allowlisted feed
         interval 15m | 1h   (what the lab holds at both; see below)
         q        query window length in bars     default 5, clamp 3..50
         f        forward horizon in bars          default 5, clamp 1..50
         k        neighbours to return             default 10, clamp 1..50
         as_of    optional ISO bar timestamp for a reproducible link
         control  on | off   default **on**
```

`as_of` is what makes a shared link mean the same thing tomorrow, and it is also the
replay mechanism: stepping the chart advances `as_of`. `control=on` by default is a
deliberate choice — the null is not an advanced option.

Intervals are 15m and 1h because that is what the lab holds for every family and what
every measurement cited here was made on. Adding 4h or 1d means re-measuring, not adding a
dropdown.

### API routes

All read-only, all `GET`, all returning the control alongside the estimate.

| route | returns |
| --- | --- |
| `/api/symbols` | the allowlisted universe, grouped fx / metals / crypto / synthetic |
| `/api/bars` | the OHLC window ending at `as_of`, plus enough history to draw |
| `/api/envelope` | shipped P10/P50/P90 for `f` bars, realised coverage, drift state, warm flag |
| `/api/analogues` | the `k` nearest windows: distance, match %, forward path, **and the shuffled-distance control set** |
| `/api/nulls` | for the panel on screen: the placebo and what it scores |
| `/api/health` | warm, last bar, last panel build, which symbols are stale |

`/api/analogues` returning its control **in the same response** is not a convenience. A
separate endpoint invites a frontend that renders the estimate and forgets the null.

## The honesty surface

These are UI requirements with the same standing as the layout.

1. **A forecast is never drawn without its control.** The analogue envelope renders as a
   cone; the control cone renders behind it, dimmed, always. If they coincide, the user
   sees that they coincide. This is the product.
2. **Match quality is a number, never a word.** The reference publishes matches "from 59%
   down to 9%" and calls a 10% match the day's best twin. Each neighbour shows its distance
   and its percentile against the distance distribution, so "the tenth nearest neighbour"
   has a figure attached.
3. **Direction carries a standing label.** Not a footnote: a persistent chip reading
   *no directional claim — measured at chance twice*, linking to `similarity.md`. The
   reference's own `NO_TRADE` is the precedent; ours cites the measurement.
4. **Coverage is shown realised against stated.** A "P90" covering like a P80 is the
   failure mode `envelope.md` was written to catch, and production already corrects for it.
   Show both numbers and the correction.
5. **Warm-up is visible.** `MIN_HISTORY` is 3,000 bars in the harness and the envelope has
   its own `warm()`. Before that, the panel says what it is waiting for. It does not
   display a provisional number as a finished one.
6. **Every panel links to the doc that measured it.** The research folder is the moat;
   linking to it costs a line and is the difference between a claim and a citation.

## The look

The brand is already monochrome: the logo is `#14181A` on light and `#E7EAE6` on dark — a
near-black with a faint cool cast and a slightly warm off-white. That is the palette
anchor, and it means the accent is a free choice.

* **Surface**: `#0E1113` page, `#14181A` cards, `#1C2124` raised, hairline borders at
  `rgba(231,234,230,0.08)`. Dark by default; the tokens are defined on `:root` with a
  light override so a toggle is a class, not a second stylesheet.
* **Ink**: `#E7EAE6` primary, `rgba(231,234,230,0.62)` secondary, `rgba(231,234,230,0.38)`
  tertiary.
* **One accent**, used only for the live/active state and the primary action — a cool
  signal green `#5BE9B9` reads as instrument-panel rather than crypto-casino and sits
  correctly on `#14181A`. Directional colour is separate and deliberately muted, because
  the whole thesis is that direction is not the claim: gains `#6FBF8F`, losses `#D97B7B`,
  both desaturated so the envelope, not the candle colour, carries the eye.
* **Type**: one family, Geist or Inter, 400/500/600. Tabular figures everywhere a number
  can change — a P50 that reflows while stepping the chart is a bug. Numerals in
  `font-variant-numeric: tabular-nums`, no exceptions.
* **Geometry**: 10px radius on cards, 8px on controls, 999px on chips. Shadows almost
  absent; separation by surface step and hairline, which is what stops a dark data app
  turning muddy.
* **Rhythm**: an 8px scale, generous between sections and tight inside panels. The chart is
  the one dense element on the page and everything around it should be quiet.
* **Motion**: 120–180ms on state, transform and opacity only. The cone animates when `as_of`
  steps; nothing else moves. No scroll-jacking, and `prefers-reduced-motion` is honoured.

**Mobile is the default case, not a breakpoint.** The viewer is a chart plus stacked
panels, single column, with the controls in a bottom sheet rather than a sidebar. The chart
keeps a 16:10 box and gets pinch-zoom and drag-to-step; panels below it scroll. At `md` the
panels move into a right rail. Touch targets are 44px. There is no horizontal page scroll
at 360px, and the chart is the only element permitted its own scroll axis.

**Charting**: `lightweight-charts` (TradingView's open library) — small, canvas-based,
performant on a phone, and it already understands candles, so we are not hand-rolling price
axes. Its limit is custom overlays: the analogue forward paths and the two cones are drawn
as line series, which it supports, but anything more exotic means a custom pane. If the
overlay ambitions grow past that, `uPlot` plus hand-drawn candles is the fallback, and it
is a bigger job.

## Phasing

### Phase 0 — run the harness that already exists. No UI.

Run `research/harness/analogue_envelope.py` on the lab across the four metrics it already
defines (`euclid`, `cosine`, `corr`, `rich`), write up the result as
`research/docs/analogue-envelope.md`, and answer its own question: **is the analogue
envelope tighter than a trailing sigma at equal coverage?**

This gates the shape of everything after it:

* **If analogues win** — the analogue panel is the headline and the shipped envelope is the
  baseline shown beside it.
* **If they do not** — the shipped envelope is the headline, and the analogue panel becomes
  an *exhibit*: here are the twins, here is why they look convincing, here is the trailing
  sigma matching them. That is a better product than the reference and an honest one, and
  it is still worth building.

Either way the UI is worth building. What changes is which number is large, and building
the UI first means guessing that.

### Phase 1 — the API, against the shipped envelope only

`till_infinity/web/` with `/api/symbols`, `/api/bars`, `/api/envelope`, `/api/health`. No
analogues yet. Added to `docker-compose.yml` as `web-api` alongside the existing services,
with its own restricted redis credentials and read-only mounts. Contract tests on every
route. This is independently useful — it is the first HTTP read surface the desk has ever
had.

### Phase 2 — the viewer

The Next.js app at `web/`: chart, envelope cone with its control, coverage panel, replay by
`as_of`, the full theme, mobile-first. Shareable links via SSR. Still no analogue panel.

### Phase 3 — analogues, shaped by Phase 0

`/api/analogues` plus the lab-side panel builder, the match strip, and the distribution
panel. The causality guard is the whole job (see *Testing*).

### Phase 4 — public, only if that is the answer

The landing page, rate limits, and the narrowed symbol universe. Not started until the
audience question is settled and the licensing question with it.

## Testing

**The causality test is the one that matters.** `analogue_envelope.py` states it plainly:
neighbours are searched only in bars strictly before the decision bar, *and the forward
window of a neighbour must also end before it*. "Getting this wrong is what makes analogue
backtests look remarkable: a twin whose 'what happened next' overlaps the present is
reporting the answer." So:

* a test that plants a distinctive window immediately after the decision bar and asserts it
  is never returned as a neighbour;
* a test that plants one whose *forward* window straddles the decision bar and asserts the
  same;
* a property test that for every returned neighbour, `neighbour_index + f < decision_index`.

Then the ordinary work: contract tests per route including the 202 path; a boundary test
asserting the web service cannot reach the journal, positions or secrets — asserted by
attempting it and requiring failure, because an allowlist nobody tests is a comment;
clamp tests on every query parameter; a warm-up test asserting no number is served before
`warm()`; and a control-presence test asserting `/api/analogues` never returns an estimate
without its control, which is the invariant the whole product rests on.

Frontend: the chart renders from a fixture without network; no horizontal scroll at 360px;
tabular figures do not reflow while stepping; `prefers-reduced-motion` honoured.

## Out of scope, explicitly

Accounts, payments and tiers. Order entry or any write path — this is a viewer, and the
absence of a write path is a security property worth keeping. Alerts, telegram publishing,
or anything that pushes. Live desk state: positions, equity, open orders. Intervals beyond
15m and 1h until they are measured. Symbol universe beyond what the lab already holds.
Backtesting or strategy building. Multi-user anything.

## Open questions

1. **Audience and hosting** — the blocker. Everything else can proceed under the stated
   assumption; Phase 4 cannot start without it.
2. **Broker bar redistribution.** If public, are the broker's bars ours to serve? The Deriv
   synthetics are characterised in our own research and are the safe universe. This needs an
   answer before a public deployment, not before Phase 1.
3. **Where the lab-side panel builder is scheduled.** The lab already refuses SSH
   intermittently while continuing to serve, so a builder that assumes a reachable lab needs
   a stale-panel story. `/api/health` reporting which symbols are stale is the minimum.
4. **Whether the landing page is this repo's job at all.** A marketing page has a different
   deploy cadence from a research API. Keeping it in `web/app/page.tsx` is simplest until it
   needs to change weekly, at which point it should move.
5. **Does the viewer show the desk's own levels?** The trap-level and hold-label work is
   directly visualisable and would be the most interesting thing on the page — but levels
   are closer to the desk's positioning than bars are, and that is a judgement about
   disclosure rather than engineering.
