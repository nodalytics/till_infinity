# MCFL v0: a formal language for what a chart shows, and what a walk shows too

Code: [`research/mcfl/`](../mcfl/README.md). Specification written 2026-10-03, with v0 of the
parser. Run on generated bars only; no market data was used.

## What it is, and what it is not

MCFL (Market Chart Formal Language) parses OHLC bars into typed entities - events, structures and
the states a structure passes through - and writes a chart out as a sentence of tokens that can be
counted, compared and replayed. It exists so that the desk's informal vocabulary (BOS, imbalance,
order block, sweep, retest) has one exact, causal and testable definition, and so that a question
like "does a zone that was revisited and rejected behave differently from one that was not" can be
asked of a sentence instead of re-coded in each study.

It is a **research instrument, not a signal**. The desk's own measurement of its canonical
structure ([`origin-zones.md`](origin-zones.md), zone events) found that zones with a break of
structure and an imbalance beat ordinary swing points by **2-4 points of P(1R)** on the first
return (+2.4 at 1h, +2.9 at 4h, +3.8 at 1d), not at all on the second, and that both lose money
after costs. On a pure random walk, **30% of swing origins** pass this grammar (5,312 origins on six
5,000-bar walks; 29.5% on GARCH walks, 32.8% on a momentum walk). Nothing in this document says the
structures it names are where anything happens.

The earlier "market language" study ([`grammar.md`](grammar.md)) built alphabets from bar shapes
and found no small alphabet and a grammar that is about size only. MCFL is different in kind: its
alphabet is not learned, it is the desk's vocabulary made exact, and its units are events with
identity and time rather than one symbol a bar.

## Syntax and semantics are kept apart

Everything MCFL emits is **syntax**: what the bars show, measured. "A close above the last swing
high known when the leg began" is syntax. "Buyers are stronger", "smart money defended the level",
"liquidity was taken" are interpretations; the language has no tokens for them and its attributes
are prices, bars and ATR multiples, never intent. Direction is the direction the price moved in the
event (BREACH_REVERT↓ is a low traded through, whatever one thinks it implies). Semantics - whether
a sentence predicts anything - is a separate, measured question for each study, answered against
walks we generate ([`null.md`](null.md), [`controls.md`](controls.md)).

## Layers

| layer | contents | entities? |
|---|---|---|
| L0 observations | `BAR(t, o, h, l, c, v)`, t = 0..n-1 | no - the input |
| L1 geometric facts | true range, Wilder ATR(14), body top/bottom, the three-bar gap `l[k] - h[k-2]`, close beyond a level | no - functions (`parse.true_range`, `parse.gap_up`, `prims.atr`) |
| L2 atomic events | EXTREME, VOID, DISPLACE, BREAK, BREACH_REVERT; and the lifecycle events REVISIT, REJECT, ACCEPT, FAIL, EXPIRE | yes |
| L3 structures | ORIGIN, LEG, ZONE (RANGE and EPISODE reserved, below) | yes |
| L4 states | a ZONE's state, and the transitions between states | transitions are records; each is caused by an L2 event |

## Entities

Every entity is a frozen dataclass (`core.Entity`):

| field | meaning |
|---|---|
| `id` | built from content: `TYPE.U|D.at[.suffix]`, e.g. `BREAK.U.66.o57` (a BREAK up at bar 66 by the leg from origin 57). Content ids are what let a truncated parse produce the *identical* entity |
| `type`, `dir` | the primitive, UP or DOWN |
| `at` | the bar it happened at |
| `known_at` | **mandatory**: the first bar at whose close it is knowable. Always `>= at` |
| `attrs` | a sorted tuple of (name, value); prices in the chart's units, sizes in ATR |
| `force` | BREAK only: the FORCE vector |
| `parts` | structures only: constituent ids, in the rule's order |

Units: ATR is Wilder's ATR(14) (`prims.atr`). Unless stated, "ATR" in a leg's measurements is the
ATR **at the origin bar**, as in `zone_events.py`. All thresholds are module constants with a
docstring.

### Causality

A bar's close is known at that bar. A 3/3 swing at p is known at p + 3. An entity's `known_at` is
the latest bar any of its inputs needed, and the parser reads nothing later. The grammar decides a
candidate using only entities whose `known_at` is at or before its decision bar - even the *reason*
a candidate failed must not depend on the future (the first run of the causality test caught exactly
that: a failure's clause changed when later VOIDs existed).

This is enforced by `tests/test_causality.py`, the most important test in the package: for every
bar T, parsing the series cut at T gives exactly the entities, relations, failures and transitions
of the full parse with `known_at <= T`, attribute for attribute. So each entity is present and
identical at its `known_at`, and absent one bar earlier.

Every rule is written once, for the up side, and run on the chart and on the chart flipped (prices
negated, highs and lows swapped); down entities are the flipped chart's up entities mapped back.
`tests/test_symmetry.py` checks that parsing the flipped chart gives the same entities with every
direction reversed and every price negated.

## Primitives (L2)

Below for the up side; DOWN is the same on the flipped chart. h, l, o, c are the bar's high, low,
open and close; A is the ATR at the origin.

| primitive | definition | attributes | `known_at` |
|---|---|---|---|
| **EXTREME** | a 3/3 swing (`prims.pivots(h, l, 3, 3)`): a high strictly above the 3 highs before it and at or above the 3 after (a flat top reports once, at its first bar); a low likewise. EXTREME↑ is a swing high, EXTREME↓ a swing low | `price`, `swing` = 3 | at + 3 |
| **VOID** | a three-bar gap: `l[k] > h[k-2]` (VOID↑) at bar k, of any positive size. The grammar decides which are big enough | `band` = (h[k-2], l[k]), `size` (price), `size_atr` (size / ATR at k) | k |
| **DISPLACE** | the leg from origin p has travelled DISPLACE_MIN = **2 ATR**: the first bar t in p..end of leg with max(h[p..t]) - l[p] >= 2A | `origin`, `bars` = t - p, `threshold_atr` | max(t, p + 3) |
| **BREAK** | the leg from origin p closes above the reference: the last EXTREME↑ known at p (so known before the break bar), priced above l[p]. The first such close in p+1..p+20, before any bar trades below l[p] (a bar that does both is not a break) | `origin`, `ref` (the EXTREME id), `level`, and FORCE | max(b, p + 3) |
| **BREACH_REVERT** | an EXTREME↓ traded through and closed back: the first bar after it is known with l < price and c >= price, before any close below it. Once per extreme | `extreme`, `level`, `depth_atr` | its bar |
| **REVISIT**, **REJECT**, **ACCEPT**, **FAIL**, **EXPIRE** | a ZONE's lifecycle events - defined with the state machine below | `zone`, `count` (REVISIT also `depth_atr`) | their bar |

**FORCE** (BREAK only; `core.Force`), from origin p to break b:

| component | definition | unit |
|---|---|---|
| magnitude | (max h[p..b] - l[p]) / A | ATR |
| speed | magnitude / duration | ATR per bar |
| efficiency | (c[b] - c[p]) / sum of abs(c[k] - c[k-1]) over p..b | ratio, None if no movement |
| penetration | (c[b] - level) / A | ATR |
| surprise | mean true range of p+1..b / mean true range of the 20 bars before p | ratio, None with fewer than 5 bars before p |
| duration | b - p | bars |

BREAK is defined on a leg, not on a level alone, because that is what the desk's BOS is: the move
from a swing breaking the structure in force when the move began. Two legs from different origins
can break the same reference on the same bar; they are two BREAKs (different ids, different force),
and the sentence prints one token for them (below).

## Structures (L3)

| structure | definition | attributes | `known_at` |
|---|---|---|---|
| **ORIGIN** | the bar of a swing low (with a defined ATR) seen as the start of an up leg. Its band is the bar's low to its body top, widened to at least ORIGIN_MIN_HEIGHT = 0.05 ATR (zone_events' `body` bound) | `extreme`, `atr`, `far` (the low), `near` (the body top), `band` | p + 3 |
| **LEG** | the bars from an origin until it BREAKs, is INVALIDATED (a bar trades below the origin's low; that bar is not part of it) or TIMEs OUT (p + 20). A leg still open at the last bar is not emitted | `origin`, `end`, `reason`, `ref`, `extreme_px`, `displacement_atr` | max(end, p + 3) |
| **ZONE** | an ORIGIN the grammar accepts | `rule`, `far`, `near`, `band`, `atr`, `break_at`, `level`, `n_voids`, `magnitude`; `parts` | the latest `known_at` of its parts |
| RANGE | reserved for v1: the band between the EXTREME↑ and EXTREME↓ in force while neither is broken | | |
| EPISODE | a zone's whole sentence, origin to terminal state; in v0 a serialisation (`serialise.episode`), not an entity | | |

## Relations

| relation | meaning | materialised |
|---|---|---|
| BEFORE(a, b) | a.at < b.at | no - computed (`core.before`); n squared otherwise |
| AFTER(a, b) | a.at > b.at | no - computed (`core.after`) |
| TOUCH(a, b) | a's bar reached b's price or band without closing through: BREACH_REVERT → EXTREME, REVISIT → ZONE | yes |
| CROSS(a, b) | a's close went through b's price: BREAK → its reference EXTREME | yes |
| CONTAIN(a, b) | b is part of or inside a: ZONE → each part; LEG → each VOID on its path (origin + 2 .. end) | yes |
| INVALIDATE(a, b) | a ended b: FAIL → ZONE | yes |

A materialised relation is `Relation(kind, src, dst, known_at)` with `known_at` the later of the
two ends'.

## The grammar

Rules are data (`grammar.RULES`): a head, an anchor slot, a horizon structure, and slots, each a
type, a count and clauses - `(field, op, expression)` triples over the slots already bound. One
matcher reads them; a production rule is a new row, not new code (`test_rules_are_data` builds a
two-VOID zone that way). The canonical rule, in BNF-like notation:

```
ZONE_UP   := ORIGIN_UP DISPLACE_UP VOID_UP+ BREAK_UP
ZONE_DOWN := ORIGIN_DOWN DISPLACE_DOWN VOID_DOWN+ BREAK_DOWN

  where (binding order origin, break, displace, void)
    BREAK.origin    == ORIGIN.id
    BREAK.at        <= ORIGIN.at + 20                       ZONE_BREAK_MAX
    DISPLACE.origin == ORIGIN.id
    DISPLACE.at     <= BREAK.at
    VOID.at         >= ORIGIN.at + 2                        VOID_PATH_START
    VOID.at         <= BREAK.at
    VOID.size       >= ORIGIN.atr * 0.1                     VOID_MIN
```

The right-hand side's order is the canonical order of the parts, not a timing constraint: the
timing is in the clauses (a VOID can come before the DISPLACE bar, and the first VOID can be known
before its origin is).

**Decision.** A candidate is every ORIGIN. It is decided when its horizon - the LEG from the same
origin - has closed, using only what was known by then; until then it is FORMING and listed in
`Chart.pending`. Accepted, it becomes a ZONE. Refused, it becomes a `Failure(candidate, rule, slot,
clause, known_at)` naming the first slot that could not be filled and the clause that emptied it.
Nothing is dropped: every ORIGIN is exactly one of zone, failure or pending (`test_grammar.py`). On
six 5,000-bar walks, the failures were 2,873 `break` (no break from the leg), 550 `void` and 277
`displace`.

**Reproduction.** With these defaults the rule is the desk's qualified zone (V = 1) in
[`zone_events.py`](../ideas/zone_events.py): a BOS within 20 bars of a 3/3 swing origin, before any
trade under it, against the last swing high known at the origin; a gap of 0.1+ ATR on the path;
2+ ATR of displacement. `tests/test_reproduces_zone_events.py` runs zone_events itself on walks and
GARCH walks: every origin it records is a MCFL ZONE exactly when it calls it V = 1 (1,989 of 1,989
origins on ten series when first checked). One deliberate difference: zone_events arms a zone 5
bars after the break, to measure `bos_follow`; MCFL qualifies it on the break bar, when the chain is
complete, and leaves follow-through to the lifecycle.

## The state machine

A ZONE's lifecycle, for an up zone (down mirrored), with A the origin's ATR, `near` the band's top,
`far` its bottom:

| from | event | to | condition | known_at |
|---|---|---|---|---|
| FORMING | ZONE | QUALIFIED | the grammar accepts | the zone's |
| FORMING | (failure) | DISQUALIFIED | the grammar refuses | the failure's |
| QUALIFIED, REJECTED | REVISIT | REVISITED(k+1) | a bar after qualifying whose low reaches `near` (from REJECTED, not the bar of the rejection) | its bar |
| REVISITED(k) | REJECT | REJECTED(k) | a bar after the revisit bar whose high reaches near + REJECT_MOVE (**1 ATR**), before a FAIL | its bar |
| REVISITED(k) | ACCEPT | ACCEPTED | ACCEPT_BARS (**3**) consecutive closes inside [far - 0.1 ATR, near], the revisit bar's close counting | its bar |
| QUALIFIED, REVISITED, REJECTED | FAIL | FAILED | a close below far - FAIL_BUF (**0.1 ATR**; zone_events' death) | its bar |
| QUALIFIED, REVISITED, REJECTED | EXPIRE | EXPIRED | no terminal event within ZONE_EXPIRE (**500**) bars of qualifying | qualifying + 500 |

ACCEPTED, FAILED and EXPIRED are terminal. Within one bar the order is REJECT (a high), REVISIT (a
low), then FAIL and ACCEPT (the close). A REVISIT and a REJECT are never on the same bar, since a
bar does not say which of its high and low came first. In words: REJECT is price moving 1 ATR
back the zone's way before closing through it; ACCEPT is price settling in the zone for three
closes, after which the zone has stopped being a turning point; FAIL is a close through it.

The transitions are `Transition(zone, src, dst, at, known_at, event)` records, each caused by an
entity. A zone's state at the last bar is in `Chart.states`; it is the one thing in a Chart without
a `known_at`, because it depends on where the series stops.

On six 5,000-bar random walks the 1,604 zones ended 878 FAILED, 388 ACCEPTED, 288 EXPIRED, and the
rest still live.

## Serialisation

**The chart sentence** (`serialise.tokens`, `to_text`): every L2 event plus a ZONE token when a
zone qualifies, ordered by `known_at` - the order a reader watching the bars live would have learned
them - and within a bar observation before interpretation (EXTREME, BREACH_REVERT, VOID, DISPLACE,
BREAK, then ZONE, then lifecycle). ORIGIN and LEG are left out: an ORIGIN is an EXTREME seen again
and a LEG is the span between tokens already there. Same-bar BREAKs (or DISPLACEs) from different
legs print once, the longest leg's. Tokens are `TYPE` plus an arrow (the canonical zone fixture, revisited and rejected):

```
EXTREME↑ DISPLACE↓ EXTREME↓ VOID↑ DISPLACE↑ VOID↑ BREAK↑ ZONE↑ VOID↑ EXTREME↑ VOID↓ DISPLACE↓ VOID↓ VOID↓ REVISIT↑ REJECT↑
```

Optional binning (`bins=True`): `BREAK↑[force:weak|mid|strong]` on magnitude (under 2, 2-4, 4+
ATR), `VOID↑[size:s|m|l]` on size (under 0.25, 0.25-0.75, 0.75+ ATR at its bar), `REVISIT↑[n:1|2|3+]`.

**The episode** (`serialise.episode`): one zone's parts in the order they happened, then its
lifecycle - `ORIGIN↑ DISPLACE↑ VOID↑ VOID↑ BREAK↑ REVISIT↑ REJECT↑`.

**Verbose text**: one token a line - `known_at at token id attributes force`.

**JSON** (`dumps`, `loads`): the whole graph - entities with attributes, force and parts,
relations, failures, transitions, final states and pending candidates. It round-trips exactly
(`loads(dumps(c)) == c`, and dumping again gives the same string). Undefined numbers are null,
never NaN.

## Trader vocabulary

| trader term | MCFL | note |
|---|---|---|
| swing high / low | EXTREME↑ / EXTREME↓ | 3/3, known 3 bars later |
| BOS (break of structure) | BREAK | a leg's close beyond the swing in force at its start |
| imbalance, FVG | VOID | any positive three-bar gap; size is an attribute |
| displacement | DISPLACE | the leg has travelled 2 ATR |
| order block, zone origin | ORIGIN | the origin bar's low to body top |
| the zone | ZONE | ORIGIN DISPLACE VOID+ BREAK |
| sweep, liquidity grab | BREACH_REVERT | traded through a swing, closed back |
| retest, mitigation | REVISIT | |
| "respected", "held" | REJECT | 1 ATR back its way before closing through |
| "price is accepted here" | ACCEPT | three closes inside |
| "invalidated" | FAIL | |

## What the walk null shows

`research/mcfl/ngrams.py` counts n-grams (n = 1-4) and next-token probabilities (context k = 1-3)
of chart sentences, and compares them with the same counts on iid Gaussian walks matched in length
and close-to-close volatility. The divergence is read only against the null's own: eleven null
sets are drawn; the data is compared with the pool of ten, and each null set with the pool of the
other ten. The p-value is the share of null KLs at least as large, floored at 1/12. Ten series of
5,000 bars per source, about 49,000 tokens each
([`out/ngrams.txt`](../mcfl/out/ngrams.txt)):

| source | KL n=1 | n=2 | n=3 | next-token k=1 | p (n=1, n=2, k=1) |
|---|---|---|---|---|---|
| iid walk (a null against itself) | 0.00026 (null median 0.00046) | 0.0059 (0.0069) | 0.062 (0.063) | 0.0069 (0.0076) | 0.58, 0.92, 0.92 |
| GARCH(1,1) walk (clustering, no direction) | 0.00059 (0.00031) | 0.0083 (0.0066) | 0.065 (0.064) | 0.0090 (0.0074) | 0.25, 0.083, 0.083 |
| AR(1) momentum walk, phi 0.2 (the positive control) | **0.0097** (0.00046) | **0.030** (0.0070) | **0.082** (0.064) | **0.022** (0.0078) | 0.083 (the floor), all three |

- **The calibration holds.** A walk against walks is inside the null at every order.
- **Volatility clustering is nearly invisible to the sentence.** GARCH sits at the edge of the
  null on bigrams and first-order transitions and nowhere else; its largest single differences are
  |z| = 3-4.4 among several hundred n-grams tested, which is what that many tests produce. Because
  every threshold is in ATR, the language normalises volatility away, so a market whose only
  structure is clustering reads as a walk.
- **The tool can see structure when there is some.** Momentum moves every unigram rate: more
  VOIDs (201 against 176 per 1,000 tokens, z = +13), fewer swings (85 against 92, z = -5.5), fewer
  BREACH_REVERTs and REJECTs, more FAILs, and an EXTREME is followed by a VOID 44% of the time
  against 36%. At 4-grams and k = 3 the KL is *below* the null's (p = 1.0), because smoothed KL on
  sparse 4-grams measures sparsity rather than structure; read orders 1-2.
- **The ZONE itself does not tell momentum from a walk.** Its rate is 27.8 per 1,000 tokens under
  momentum against 26.6 on walks (z = +1.6), and the share of origins qualifying is 33% against
  30%. The chain the desk trades appears on a walk at almost the rate it appears on a trending
  series. That is the desk's experience restated in the language's own terms: most chart structure
  is what a random walk draws.

- **Binning the attributes sharpens the positive control and changes nothing else**
  ([`out/ngrams_bins.txt`](../mcfl/out/ngrams_bins.txt)). The walk stays inside its null and GARCH
  at its edge (p = 0.25, 0.083, 0.083). Under momentum, large VOIDs rise from 43 to 58 per 1,000
  tokens (z = +16), strong BREAKs from 10.1 to 12.6 (z = +5.4) at the expense of mid ones, and a
  large VOID follows a large VOID 8.5% of the time against 4.6%. The force of a break is visible
  in the sentence when the process has momentum - which a walk does not have, and the desk found
  real zones' force to be flat against their outcome.

These are generated series. Whether real markets' sentences differ from their matched walks is
the first question to put to the language once it runs on the broker's bars.

## Open questions

- **Is the grammar compressible?** A minimum-description-length test: does adding ZONE (or any
  production) to the alphabet shorten the encoded sentences of real markets more than it shortens
  those of matched walks? If a rule compresses walks as well as markets, it describes geometry,
  not behaviour. [`grammar.md`](grammar.md) found no small bar-shape alphabet; the question here
  is whether an event alphabet does better.
- **Are structurally identical sentences equivalent across assets and timeframes?** If the episode
  `ORIGIN↑ DISPLACE↑ VOID↑ BREAK↑ REVISIT↑ REJECT↑` has the same continuation distribution on EURUSD
  1h and BTC 4h, the language is scale-free and pooling is legitimate; if not, sentences need an
  asset/timeframe context, which is a different language.
- **Does a multi-timeframe ALIGN/CONFLICT relation work?** ALIGN(a, b) for a lower-timeframe
  entity inside a same-direction higher-timeframe ZONE, CONFLICT for the opposite, mapped with
  `prims.htf_index` so the higher bar is closed. The desk's 4h-bias filter is a special case; it
  helped nothing in [`origin-zones.md`](origin-zones.md), so this is to be measured, not assumed.
- **RANGE and EPISODE as entities**, and whether lifecycle events should exist for failed
  candidates too, so that V = 0 origins have sentences comparable with zones'.

## Decisions the brief left open

- BREAK is leg-anchored, per origin. A level-only BREAK cannot reproduce zone_events, whose
  reference is the swing in force *at the origin* even if a later swing became known before the
  break.
- VOID is emitted at any positive size and judged by the grammar against the origin's ATR, since an
  emission threshold in the gap bar's own ATR would disagree with zone_events at the margin. Its
  leg membership is the CONTAIN relation from the LEG, not an attribute, because the leg is often
  known after the gap is (a gap at p + 2 is known before its origin at p + 3).
- ORIGIN exists for every swing low with an ATR; it is a candidate, not a claim.
- BREACH_REVERT's direction is the breach's, not the reversion's.
- EXPIRE is a fifth lifecycle event, so the terminal EXPIRED state has a cause like the others.
