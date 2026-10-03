# MCFL v2: a formal language for what a chart shows, and what a walk shows too

Code: [`research/mcfl/`](../mcfl/README.md). Specification written 2026-10-03 with v0 of the parser
and extended the same day to v1 and v2. Run on generated bars only; no market data was used.

**What v2 adds** (the thirteen items of [`mcfl-roadmap.md`](mcfl-roadmap.md), section v2; their
definitions are in [v2](#v2-structure-lifecycles-time-timeframes-and-the-candlestick-vocabulary)
below): swing-structure labels and a STRUCTURE state, the BREAK's relation to it and the CHoCH;
compression and expansion words; volume (effort against result); the VOID lifecycle; RANGE as a
structure; liquidity pools and the DAX course's protected sweep; retracement depth; sessions, days
and tempo; FOCuS and CUSUM changepoints as events; multiple timeframes, with the desk's nested-zone
finding as one production in a causal form; candle range theory; and the classical candlestick
vocabulary as productions over the v1 words. v0 and v1 are unchanged (`parse(df, v2=False)` gives
the v1 chart; the default parse adds the v2 entities and attributes). Every v2 entity has a
`known_at`, is under the truncation test, and is flip-symmetric.

**What v1 adds.** v0 started at events: an EXTREME, a VOID, a BREAK, each computed from prices.
v1 puts a token layer under them, so a chart reads as one sentence from the bars up. Every bar is
one CANDLE word (a fuzzy class of its size, body and wicks, plus graded strength) and one
BAR_RELATION token (its relation to the previous bar, down to every pair of price points). Every L2
event is now a production over those tokens and lists the tokens it consumed, so a ZONE's
derivation prints down to candle words. On top come candle-level productions - PIN, ENGULF,
INSIDE_BREAK, STAR, DISPLACE_C, DELIVERY_SHIFT (the desk's CISD) and a candle REJECT - a qualifier
syntax for writing them, BREAK attributes for the age of the level broken, and a CONFIRMED state.
v0's behaviour is unchanged: its zone grammar still reproduces `zone_events.py` exactly, and v0's
path-based REJECT is kept as REJECT_PATH.

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
| L0 observations | `BAR(t, o, h, l, c, v)`, t = 0..n-1 | no - the input, not part of the language |
| L1 tokens | one CANDLE per bar, one BAR_RELATION per bar from the second (`candles.py`). Each CANDLE is a lexeme: it carries its raw bar, true range and ATR(14) as attributes. v0's L1 helper functions (true range, the gap) are now attribute computations on tokens | yes |
| L2 events | productions over L1 tokens. Pattern events: PIN, ENGULF, INSIDE_BREAK, STAR, DISPLACE_C, DELIVERY_SHIFT, REJECT. Level events: EXTREME, VOID, DISPLACE, BREAK, BREACH_REVERT, and the lifecycle events REVISIT, REJECT_PATH, ACCEPT, FAIL, EXPIRE | yes; `parts` lists the L1 tokens consumed |
| L3 structures | ORIGIN, LEG, ZONE (RANGE and EPISODE reserved, below) | yes |
| L4 states | a ZONE's state, and the transitions between states | transitions are records; each is caused by an L2 event |

**Pattern and level events.** Fuzzy classes discard absolute price. A pattern event (PIN,
ENGULF, ...) can be decided from the tokens' classes and grades alone. A level event cannot ("the
close is beyond the level of the EXTREME referenced", "low[k] > high[k-2]"). Level events are
written as attributed-grammar rules: a match on tokens plus a semantic condition on the tokens'
price attributes. Both kinds are productions over L1 and both list the tokens they consumed.

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
| `parts` | what it was built from: for an L2 event, the L1 token ids it consumed (REJECT also its REVISIT; a BAR_RELATION its two CANDLEs); for a structure, its constituent ids in the rule's order (ORIGIN: its EXTREME) |

Ids of tokens are `CANDLE.U.57` (a BULL bar; D for BEAR, N for a doji) and `BAR_RELATION.U.57` (U
for HH, D for LL, N for INSIDE and OUTSIDE). Directions are UP, DOWN and, for tokens only, NONE.

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
of the full parse with `known_at <= T`, attribute for attribute. In v1 this covers every token
and every candle production; the rarer candle REJECT and CONFIRMED transition are checked on a
longer series at their known_at and one bar before. Rolling means and deviations are summed left to
right over each window so that a window gives the same floating-point numbers whatever came before
it - otherwise a class at a boundary could differ between a prefix and the full series. So each entity is present and
identical at its `known_at`, and absent one bar earlier.

Every rule is written once, for the up side, and run on the chart and on the chart flipped (prices
negated, highs and lows swapped); down entities are the flipped chart's up entities mapped back.
`tests/test_symmetry.py` checks that parsing the flipped chart gives the same entities with every
direction reversed and every price negated.

## L1: the token layer

### CANDLE

Each bar is `CANDLE(direction, size, body, upper wick, lower wick)`. The scheme is that of
NautilusTrader's fuzzy candlesticks (`FuzzyCandlesticks`, crates/indicators/src/volatility/fuzzy.rs);
the idea is theirs, the code here is our own. Each class places the bar's measure in the rolling
distribution of the same measure over the last PERIOD = **10** bars, with mean m and population
standard deviation s; t1 = **0.5**, t2 = **1.0**, t3 = **2.0** (t4 = 3.0 is defined, as in Nautilus,
and unused):

| measure | NONE | then, each up to and including its edge | above the last edge |
|---|---|---|---|
| direction | c = o | BULL c > o, BEAR c < o | |
| size: h - l | 0 | VERY_SMALL ≤ m - t2·s, SMALL ≤ m - t1·s, MEDIUM ≤ m + t1·s, LARGE ≤ m + t2·s, VERY_LARGE ≤ m + t3·s | EXTREMELY_LARGE |
| body: abs(c - o) / (h - l) | 0 | SMALL ≤ m - t1·s, MEDIUM ≤ m + t1·s, LARGE ≤ m + t2·s | TREND |
| upper wick: (h - max(o, c)) / (h - l) | 0 | SMALL ≤ m - t1·s, MEDIUM ≤ m + t2·s | LARGE |
| lower wick: (min(o, c) - l) / (h - l) | 0 | likewise | LARGE |

Choices the scheme leaves open:

- **The current bar is in its own window**, as in Nautilus. It is known at the bar's close, so this
  is causal either way. A consequence: in a sample of 10 that includes it, a bar's z-score cannot
  exceed 9/√10 = 2.85, so EXTREMELY_LARGE (> 2) is rare and a t4 = 3 class could never occur.
- **Warm-up.** A token is emitted for every bar, because level events need every bar's prices from
  bar 0. Until its window is full (the first 9 bars) its classes are WARMUP; grades that need the
  ATR wait for it too (bar 23). No pattern matches a WARMUP class.
- **s = 0** (a window of equal values) collapses every edge onto m; a literal reading would call the
  bar VERY_SMALL. It is the middle class (MEDIUM; MODERATE for grades). A zero value is NONE first.
- A zero-range bar has body and wick shares of 0.

### Strength

Each CANDLE also carries the strength of its body and wicks, graded against the measure's own
rolling distribution with the same period and thresholds: WEAK ≤ m - t1·s < MODERATE ≤ m + t1·s <
STRONG ≤ m + t2·s < DOMINANT; a zero is NONE for wicks and WEAK for bodies.

| attribute | definition | grade |
|---|---|---|
| `body_conv` | abs(c - o) / (h - l), conviction | `conv_g`; on the same measure and edges as the body class, so it is that class renamed (SMALL = WEAK ... TREND = DOMINANT), kept for the grammar |
| `body_atr` | abs(c - o) / ATR(14), force | `force_g` - the body strength the grammar's `body≥STRONG` reads |
| `upper_share`, `lower_share` | wick / (h - l) | `upper_share_g`, `lower_share_g` |
| `upper_atr`, `lower_atr` | wick / ATR(14), the wick's force | `upper_g`, `lower_g` - the wick strength `wick.up` / `wick.low` read |
| `upper_body`, `lower_body` | wick / max(body, 0.05·(h - l)), the rejection ratio | not graded: a doji's ratio is set by the floor, so its rolling sd means nothing. Read as a number (`wick.low.body≥2`) |
| `close_q` | (c - l) / (h - l) in quartiles | Q1..Q4 |

Close quartiles are decided on a = c - l against b = h - c, which the flip swaps exactly: Q4 when
a > 3b, Q1 when b > 3a, Q3 when b < a ≤ 3b, else Q2 (so 0.75 is Q3, 0.25 is Q2). The flip maps Qk
to Q(5-k) except at an exact midpoint close (a = b), which is Q2 on both sides.

### BAR_RELATION

For each bar against the previous one (none for bar 0):

| attribute | values |
|---|---|
| `rel` | INSIDE (h ≤ prev h and l ≥ prev l), OUTSIDE (h > prev h and l < prev l), else HH (h > prev h) or LL (l < prev l). "HH_LL" cannot occur: a bar that extends both ways is OUTSIDE |
| `engulf` | BULL when a BULL body covers the previous BEAR body (top ≥ prev top, bottom ≤ prev bottom, strictly larger); BEAR mirrored; else NONE |
| `beyond`, `mother` | the close against the mother bar's range: ABOVE, BELOW or NONE. The mother is the previous bar, or after an INSIDE bar that bar's own mother (the outer bar of a run of inside bars) |
| `points` | the point-relation matrix, below |
| `named` | the named point relations that hold, below |

`rel` and `engulf` use exact comparisons; the point relations use a tolerance.

### Point relations

**The matrix.** `points` is a 16-character string: the bar's O, H, L, C (rows) against the previous
bar's O, H, L, C (columns), row-major in the order OHLC, each `+` (ABOVE), `=` (EQUAL) or `-`
(BELOW). Character 4·i + j is current point i against previous point j; `points[3]` is the open
against the previous close. The CANDLE carries `inner`, the same matrix of the bar against itself.

**Tolerance.** Two points are EQUAL when they differ by at most tol = max(EQ_ATR × ATR(14), one
tick), EQ_ATR = **0.05**. The tick is the series' tick size if given (`table(df, tick=...)`), else
the smallest non-zero price difference seen so far (between the bar's own points and against the
previous close) - a running minimum, so it is causal and can only shrink. Before the ATR exists
the tolerance is the tick alone. On our generated bars the ATR term always dominates.

**Named relations.** Every name is a production over one matrix cell; no named relation reads a
price. The flip twin swaps H and L on both sides and ABOVE and BELOW. The within-bar names have
second names for the grammar: HIGH_AT_OPEN = OPEN_AT_HIGH, HIGH_AT_CLOSE = CLOSE_AT_HIGH, LOW_AT_OPEN = OPEN_AT_LOW, LOW_AT_CLOSE = CLOSE_AT_LOW.

| name | cell it reads | flip twin | text |
|---|---|---|---|
| OPEN_AT_PREV_CLOSE | `points`[O,pC] = | OPEN_AT_PREV_CLOSE | `o=pc` |
| OPEN_GAP_UP | `points`[O,pC] + | OPEN_GAP_DOWN | `o>pc` |
| OPEN_GAP_DOWN | `points`[O,pC] - | OPEN_GAP_UP | `o<pc` |
| OPEN_AT_PREV_OPEN | `points`[O,pO] = | OPEN_AT_PREV_OPEN | `o=po` |
| OPEN_ABOVE_PREV_HIGH | `points`[O,pH] + | OPEN_BELOW_PREV_LOW | `o>ph` |
| OPEN_BELOW_PREV_LOW | `points`[O,pL] - | OPEN_ABOVE_PREV_HIGH | `o<pl` |
| OPEN_AT_PREV_HIGH | `points`[O,pH] = | OPEN_AT_PREV_LOW | `o=ph` |
| OPEN_AT_PREV_LOW | `points`[O,pL] = | OPEN_AT_PREV_HIGH | `o=pl` |
| CLOSE_AT_PREV_CLOSE | `points`[C,pC] = | CLOSE_AT_PREV_CLOSE | `c=pc` |
| CLOSE_AT_PREV_OPEN | `points`[C,pO] = | CLOSE_AT_PREV_OPEN | `c=po` |
| CLOSE_ABOVE_PREV_HIGH | `points`[C,pH] + | CLOSE_BELOW_PREV_LOW | `c>ph` |
| CLOSE_BELOW_PREV_LOW | `points`[C,pL] - | CLOSE_ABOVE_PREV_HIGH | `c<pl` |
| CLOSE_AT_PREV_HIGH | `points`[C,pH] = | CLOSE_AT_PREV_LOW | `c=ph` |
| CLOSE_AT_PREV_LOW | `points`[C,pL] = | CLOSE_AT_PREV_HIGH | `c=pl` |
| HIGH_ABOVE_PREV_HIGH | `points`[H,pH] + | LOW_BELOW_PREV_LOW | `h>ph` |
| HIGH_AT_PREV_HIGH | `points`[H,pH] = | LOW_AT_PREV_LOW | `h=ph` |
| HIGH_BELOW_PREV_HIGH | `points`[H,pH] - | LOW_ABOVE_PREV_LOW | `h<ph` |
| HIGH_AT_PREV_CLOSE | `points`[H,pC] = | LOW_AT_PREV_CLOSE | `h=pc` |
| HIGH_AT_PREV_OPEN | `points`[H,pO] = | LOW_AT_PREV_OPEN | `h=po` |
| HIGH_AT_PREV_LOW | `points`[H,pL] = | LOW_AT_PREV_HIGH | `h=pl` |
| HIGH_BELOW_PREV_LOW | `points`[H,pL] - | LOW_ABOVE_PREV_HIGH | `h<pl` |
| LOW_BELOW_PREV_LOW | `points`[L,pL] - | HIGH_ABOVE_PREV_HIGH | `l<pl` |
| LOW_AT_PREV_LOW | `points`[L,pL] = | HIGH_AT_PREV_HIGH | `l=pl` |
| LOW_ABOVE_PREV_LOW | `points`[L,pL] + | HIGH_BELOW_PREV_HIGH | `l>pl` |
| LOW_AT_PREV_CLOSE | `points`[L,pC] = | HIGH_AT_PREV_CLOSE | `l=pc` |
| LOW_AT_PREV_OPEN | `points`[L,pO] = | HIGH_AT_PREV_OPEN | `l=po` |
| LOW_AT_PREV_HIGH | `points`[L,pH] = | HIGH_AT_PREV_LOW | `l=ph` |
| LOW_ABOVE_PREV_HIGH | `points`[L,pH] + | HIGH_BELOW_PREV_LOW | `l>ph` |
| OPEN_AT_HIGH | `inner`[O,H] = | OPEN_AT_LOW | `o=h` |
| OPEN_AT_LOW | `inner`[O,L] = | OPEN_AT_HIGH | `o=l` |
| CLOSE_AT_HIGH | `inner`[C,H] = | CLOSE_AT_LOW | `c=h` |
| CLOSE_AT_LOW | `inner`[C,L] = | CLOSE_AT_HIGH | `c=l` |
| OPEN_EQ_CLOSE | `inner`[O,C] = | OPEN_EQ_CLOSE | `o=c` |
| BODY_MIRROR | OPEN_AT_PREV_CLOSE and CLOSE_AT_PREV_OPEN | BODY_MIRROR | `mirror` |

The fuzzy NONE classes agree with these: an upper wick of NONE means OPEN_AT_HIGH or CLOSE_AT_HIGH,
a lower wick of NONE OPEN_AT_LOW or CLOSE_AT_LOW, a body of NONE OPEN_EQ_CLOSE
(`test_fuzzy_none_agrees_with_within_bar_relations`). The converse does not hold: the tolerance
makes a small wick AT the high too.

**Flip symmetry** of the whole layer is tested column by column: the token table of the flipped
chart equals the token table read in the flipped frame (`candles.frame`), with BULL and BEAR, upper
and lower, Qk and Q(5-k), HH and LL, ABOVE and BELOW, and every named relation and its twin
exchanged, and size, body and the body grades unchanged.

## L2 events

### Level events

Below for the up side; DOWN is the same on the flipped chart. h, l, o, c are the high, low, open
and close of the CANDLE tokens consumed (their lexemes); A is the ATR at the origin. Each is an
attributed rule - tokens matched, then a condition on their prices - and lists the tokens it
consumed in `parts`. EXTREME and VOID are fixed-window words in `grammar.WORDS`
(`C-3 C-2 C-1 C0 C+1 C+2 C+3 where C-k.high < C0.high, C+k.high <= C0.high`; `C-2 C-1 C0 where
C0.low > C-2.high`); the others scan a variable run of tokens and are code, catalogued with their
syntax and condition in `parse.LEVEL_RULES`.

| primitive | definition | attributes | `known_at` |
|---|---|---|---|
| **EXTREME** | a 3/3 swing (`prims.pivots(h, l, 3, 3)`): a high strictly above the 3 highs before it and at or above the 3 after (a flat top reports once, at its first bar); a low likewise. EXTREME↑ is a swing high, EXTREME↓ a swing low | `price`, `swing` = 3 | at + 3 |
| **VOID** | a three-bar gap: `l[k] > h[k-2]` (VOID↑) at bar k, of any positive size. The grammar decides which are big enough | `band` = (h[k-2], l[k]), `size` (price), `size_atr` (size / ATR at k) | k |
| **DISPLACE** | the leg from origin p has travelled DISPLACE_MIN = **2 ATR**: the first bar t in p..end of leg with max(h[p..t]) - l[p] >= 2A | `origin`, `bars` = t - p, `threshold_atr` | max(t, p + 3) |
| **BREAK** | the leg from origin p closes above the reference: the last EXTREME↑ known at p (so known before the break bar), priced above l[p]. The first such close in p+1..p+20, before any bar trades below l[p] (a bar that does both is not a break) | `origin`, `ref` (the EXTREME id), `level`, and FORCE | max(b, p + 3) |
| **BREACH_REVERT** | an EXTREME↓ traded through and closed back: the first bar after it is known with l < price and c >= price, before any close below it. Once per extreme | `extreme`, `level`, `depth_atr` | its bar |
| **REVISIT**, **REJECT_PATH**, **ACCEPT**, **FAIL**, **EXPIRE** | a ZONE's lifecycle events - defined with the state machine below. REJECT_PATH is v0's REJECT, renamed | `zone`, `count` (REVISIT also `depth_atr`) | their bar |

`parts`: EXTREME the seven tokens p-3..p+3; VOID the three k-2..k; DISPLACE and BREAK the tokens
from the origin to their bar (the leg); BREACH_REVERT and the lifecycle events their own bar's
token. A condition may read more than its parts (BREACH_REVERT reads every close since its extreme
was known; BREAK reads the reference EXTREME).

**How old the level broken was** (BREAK attributes, all in bars and causal):

| attribute | definition |
|---|---|
| `ref_age` | break bar - the reference EXTREME's bar |
| `ref_known_age` | break bar - the reference's known_at |
| `swings_taken` | how many still-standing EXTREME↑ (no close above them since they formed), known by the break bar, the break close cleared at once. It can be 0 when the reference itself had been closed above before the origin |
| `max_ref_age` | the age of the oldest of those (None when 0) |
| `leg_bars` | origin to break, = FORCE duration |
| `strength_mean`, `strength_max` | the mean and max `body_atr` of the leg's tokens |

**LEG_MAX = 20 caps how long the breaking move may take, origin to break. It does not limit the
age of the level broken**, which can be any number of bars old: `test_break_age.py` breaks a level
10 bars old, one 200 bars old, and, with one close, a young level and a 200-bar-old one together
(`swings_taken` 2, `max_ref_age` 200). On walks the reference is usually young - the last swing
known at the origin; median `ref_age` 11 bars, 90th percentile 22.

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

### Candle productions and the qualifier syntax

Pattern events are written in a qualifier syntax over L1 tokens (`grammar.q`, `grammar.run`):

```
qualified := "CANDLE[" qual ("," qual)* "]"
run       := "RUN[" "k" ("≥" | "=") INT ("," qual)* "]"     K consecutive tokens that all qualify;
                                                            fires at the K-th, once per run
qual      := key op value | NAME | "not" NAME
op        := "=" | "!=" | "≥" | ">=" | "≤" | "<=" | ">" | "<"
key       := "dir"                                   BULL BEAR NONE
           | "size" | "body" | "upper" | "lower"     fuzzy classes, ordered NONE < ... (body also takes grades)
           | "body" | "force" | "conv"               strength grades WEAK < MODERATE < STRONG < DOMINANT
           | "wick.up" | "wick.low"                  wick force grades NONE < WEAK < ... < DOMINANT
           | "wick.up.share" | "wick.low.share"      wick share grades
           | "wick.up.body" | "wick.low.body"        the rejection ratio, a number
           | "close"                                 Q1 < Q2 < Q3 < Q4
           | "rel" | "engulf" | "beyond"             the BAR_RELATION token
NAME      := any named point relation, or its alias
```

`body` with a grade (WEAK..DOMINANT) reads the force grade `force_g`; with a class (NONE..TREND)
the fuzzy body class. `≥ STRONG` means STRONG or DOMINANT; nothing compares with WARMUP. A
qualifier compiles to a clause; a word is a fixed window of token cells with clauses and an
optional `unless` (a context that must not hold, which is how RUN fires once). Each word is
written for the up side and run on the token table and on the flipped one. Two rows with one head
on one bar (DISPLACE_C's two forms) make one event, the first row's.

| event | production (up side; down is the mirror) | `parts` | attributes |
|---|---|---|---|
| **PIN** | `CANDLE[wick.low≥STRONG, body≤MODERATE, close≥Q3, wick.up≤WEAK]`: a strong wick toward the rejection, a modest body, the close in the half away from the wick, little wick on the other side | the token | |
| **ENGULF** | `CANDLE[dir=BEAR] CANDLE[dir=BULL, engulf=BULL]` | two CANDLEs and the BAR_RELATION | |
| **INSIDE_BREAK** | `CANDLE[rel=INSIDE] CANDLE[beyond=ABOVE]`: an inside bar, then a close above the mother bar | two CANDLEs and two BAR_RELATIONs | |
| **STAR** | `CANDLE[dir=BEAR, body≥LARGE] CANDLE[body≤SMALL] CANDLE[dir=BULL, body≥LARGE]`: the morning star (evening on the flipped chart) | three CANDLEs | |
| **DISPLACE_C** | `RUN[k≥2, dir=BULL, body≥STRONG, close=Q4]` or `CANDLE[dir=BULL, size=EXTREMELY_LARGE, body≥DOMINANT, close=Q4]` | the run's tokens (or the bar) | `rule`, `strength_mean`, `strength_max` (body_atr) |
| **DELIVERY_SHIFT** (CISD) | a scan: `CANDLE[dir=BEAR]+ CANDLE[dir!=BEAR]{0,2} CANDLE[dir=BULL]` where the BULL close > the open of the run's first BEAR token, and the BULL token is at most 3 bars after the run's last | the run's tokens and the shifting token | `run_len`, `lag` (run end to shift), `run_force_mean`, `run_force_max`, `margin` = (close - run's first open) / ATR |
| **REJECT** | a rule over entities: `REVISIT_UP CANDLE[wick.low≥STRONG]`, the first CANDLE in the reaction window (the revisit bar and the 2 after) with a strong wick toward the zone and `close > zone.near` (closed back out), before any FAIL of the zone | the REVISIT and the CANDLE | `zone`, `revisit`, `count` |

All are known at their last token's close. DELIVERY_SHIFT reproduces the desk's
`zones._cisd` exactly: on walks and GARCH walks, both directions, every bar
(`test_delivery_shift_is_the_desks_cisd`). REJECT and DELIVERY_SHIFT each need one price condition,
so strictly they are attributed rules too; everything else in the table reads classes and grades
only. The pattern fixtures (`test_patterns.py`) are hand-built token tables in which one qualifier
is changed at a time, so each production is shown to pass, and to fail on strength alone.

## Structures (L3)

| structure | definition | attributes | `known_at` |
|---|---|---|---|
| **ORIGIN** | the bar of a swing low (with a defined ATR) seen as the start of an up leg. Its band is the bar's low to its body top, widened to at least ORIGIN_MIN_HEIGHT = 0.05 ATR (zone_events' `body` bound) | `extreme`, `atr`, `far` (the low), `near` (the body top), `band` | p + 3 |
| **LEG** | the bars from an origin until it BREAKs, is INVALIDATED (a bar trades below the origin's low; that bar is not part of it) or TIMEs OUT (p + 20). A leg still open at the last bar is not emitted | `origin`, `end`, `reason`, `ref`, `extreme_px`, `displacement_atr` | max(end, p + 3) |
| **ZONE** | an ORIGIN the grammar accepts | `rule`, `far`, `near`, `band`, `atr`, `break_at`, `level`, `n_voids`, `magnitude`; `parts` | the latest `known_at` of its parts |
| RANGE | reserved: the band between the EXTREME↑ and EXTREME↓ in force while neither is broken | | |
| EPISODE | a zone's whole sentence, origin to terminal state; still a serialisation (`serialise.episode`), not an entity | | |

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
two-VOID zone that way). v1 adds to the matcher what the candle rules need, all as row fields:
clauses on the anchor itself, slots of either direction (`dir="any"`, a CANDLE of any colour),
absent slots (REJECT's "before any FAIL"), a decision window instead of a horizon structure, the
event's bar taken from another slot, and an id suffix. Clauses read entities through `core.view`,
the flipped-frame view, so a rule is written once for the up side. Fixed windows of tokens are a
second table, `grammar.WORDS`, evaluated over all bars at once (above). The canonical rule, in
BNF-like notation:

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
| REVISITED(k) | DELIVERY_SHIFT | CONFIRMED(k) | a DELIVERY_SHIFT (CISD) in the zone's direction within the reaction window (the revisit bar and the next 2) | the shift's bar |
| REVISITED(k), CONFIRMED(k) | REJECT_PATH | REJECTED(k) | a bar after the revisit bar whose high reaches near + REJECT_MOVE (**1 ATR**), before a FAIL | its bar |
| REVISITED(k), CONFIRMED(k) | ACCEPT | ACCEPTED | ACCEPT_BARS (**3**) consecutive closes inside [far - 0.1 ATR, near], the revisit bar's close counting | its bar |
| any live state | FAIL | FAILED | a close below far - FAIL_BUF (**0.1 ATR**; zone_events' death) | its bar |
| any live state | EXPIRE | EXPIRED | no terminal event within ZONE_EXPIRE (**500**) bars of qualifying | qualifying + 500 |

ACCEPTED, FAILED and EXPIRED are terminal. Within one bar the order is CONFIRM (of an earlier
revisit), REJECT_PATH (a high), REVISIT (a low), then FAIL, CONFIRM (of a revisit on this bar) and
ACCEPT (the close). A REVISIT and a REJECT_PATH are never on the same bar, since a bar does not say
which of its high and low came first. CONFIRM is placed before REJECT_PATH because a shift bar has
usually travelled the 1 ATR as well; such a bar records both, REVISITED → CONFIRMED → REJECTED, at
its close (the first ordering tried recorded almost no confirmations, for that reason). The
CONFIRMED transition is caused by the DELIVERY_SHIFT entity itself; no new entity is made. In
words: REJECT_PATH is price moving 1 ATR back the zone's way before closing through it; CONFIRMED is
the delivery into the zone reversing; ACCEPT is price settling in the zone for three closes, after
which the zone has stopped being a turning point; FAIL is a close through it.

The candle REJECT sits alongside REJECT_PATH as an observation and does not move the state machine:
the state machine is v0's, and REJECT_PATH keeps its v0 behaviour exactly.

The transitions are `Transition(zone, src, dst, at, known_at, event)` records, each caused by an
entity. A zone's state at the last bar is in `Chart.states`; it is the one thing in a Chart without
a `known_at`, because it depends on where the series stops.

On six 5,000-bar random walks the 1,604 zones ended 878 FAILED, 388 ACCEPTED, 288 EXPIRED, and the
rest still live.

## v2: structure, lifecycles, time, timeframes and the candlestick vocabulary

The items in the roadmap's build order. Each is written for the up side and run on the chart and on
the chart flipped, like everything else; each entity's `known_at` is the first bar it could be known,
checked by the truncation tests (`tests/test_causality.py`, `tests/test_v2_causality.py`). Text forms
are `token(e, v2=True)`: the type, the arrow, then the qualifier that says which one it is in brackets.
Non-directional v2 entities (BALANCE, RANGE, a DOJI) have direction NONE, which v1 allowed only for
L1 tokens.

### 1. Swing-structure labels and the STRUCTURE state

`structure.py`. Each EXTREME after the first of its kind is labelled against the previous EXTREME of
its kind (by bar), with tol = SWING_EQ_ATR (**0.1**) × ATR(14) at the later swing:

| kind | label | condition | flip twin |
|---|---|---|---|
| high (EXTREME↑) | HH | price > previous high + tol | LL |
| | EH | within tol | EL |
| | LH | price < previous high - tol | HL |
| low (EXTREME↓) | LL | price < previous low - tol | HH |
| | EL | within tol | EH |
| | HL | price > previous low + tol | LH |

A label is a **SWING** event: `at` and `known_at` the EXTREME's (bar + 3), `parts` the previous
EXTREME and this one, attributes `label`, `price`, `prev` (the previous EXTREME's id), `diff_atr`
(signed, positive further out) and `bars` between them. Text `SWING↑[HH]`.

The **STRUCTURE** state (L4) is read from the last high label and the last low label known:

| state | condition |
|---|---|
| UP | last high HH and last low HL |
| DOWN | last high LH and last low LL |
| MIXED | anything else, including an EH or EL (an equal high is not a higher high), and before both kinds have a label |

Labels known on the same bar (a bar can be both a swing high and a swing low) are applied together
and the state read once, so their order cannot matter. **STRUCTURE_SHIFT** is the event of a change:
at the latest labelled bar, known at the labels' `known_at`, attributes `from`, `to` and `run` (the
labels the previous state held), parts the SWING events that caused it; direction UP when the state
rose in the order DOWN < MIXED < UP, DOWN when it fell. Text `STRUCTURE_SHIFT↑[MIXED>UP]`. The
state known at any bar is `structure.structure_at(chart, t)` (and, inside the parser, the token
table's `trend` column, which the candlestick vocabulary reads).

### 11. vs_structure, BOS and CHARACTER_SHIFT (CHoCH)

Every BREAK gets `vs_structure` and `structure`, read from the STRUCTURE state known at the break's
own bar b (labels with `known_at` ≤ b):

| `vs_structure` | condition | trader term |
|---|---|---|
| WITH | the state is the break's direction (UP and BREAK↑) | **BOS**: a BREAK with WITH is the trader's break of structure |
| AGAINST | the state is the other direction | |
| NONE | the state is MIXED | |

Text `BREAK↑[WITH]`.

**CHARACTER_SHIFT** (alias CHoCH): the first AGAINST BREAK while an **established** UP or DOWN state
holds, once per run of that state. A state is established once ESTABLISH_LABELS (**2**) consecutive
labels have held it, the label that set it counting; a run ends at the next STRUCTURE_SHIFT. Breaks
are taken in the order they became known (known_at, then bar, then the earliest origin), so a prefix
sees the same first one; at most one per bar. Direction the break's, `known_at` the break's, `parts`
the BREAK; attributes `break`, `structure` (the state it went against), `run`, `level`.

The fixture `TREND_CHOCH_BOS` (`tests/test_structure.py`): an up trend labelled HH HL HH HL HH
(state UP from bar 41, established at 49), BOS↑ at 43 and 55 (WITH), a fall that breaks the last
higher low at bar 67 (AGAINST: the CHARACTER_SHIFT↓), then LL and LH (MIXED at 77, DOWN at 83), and
breaks down at 87 and 103 that are WITH - the BOS in the new direction - and not further CHoCHs. A
break against a state that only one label holds is AGAINST without being a CHoCH.

### 4. The VOID lifecycle

`voids.py`. Every VOID is followed from the bar after it to its end:

```
UNTOUCHED --VOID_PARTIAL--> PARTIAL --VOID_FILLED--> FILLED --VOID_INVERTED--> INVERTED (terminal)
```

For a VOID↑ at bar k (down mirrored), `near` = its top l[k] (the edge price meets first on the way
back), `far` = its bottom h[k-2]:

| event | the first bar t > k with | attributes | `known_at` |
|---|---|---|---|
| VOID_PARTIAL | l[t] < near (price entered the gap; a low exactly at the edge has not) | `void`, `share` = (near - l[t]) / (near - far), capped at 1 | t |
| VOID_FILLED | l[t] ≤ far (traded through it) | `void`, `share` (1) | t |
| VOID_INVERTED | c[t] < far (a close beyond its far side: the IFVG) | `void`, `beyond_atr` = (far - c[t]) / ATR | t |

Each implies the ones before it, so one bar can make two or three transitions; all are recorded, in
order, at its close. `parts` is that bar's CANDLE. Each transition is also a
`Transition(void, src, dst, at, known_at, event)` in `Chart.transitions` (keyed by the VOID's id), so a
void's state at any bar is `voids.void_state(chart, void_id, t)` - None before the VOID is known,
UNTOUCHED from then. Exact comparisons, no tolerance, as v1's VOID itself.

## Serialisation

**The chart sentence** (`serialise.tokens`, `to_text`): every L2 event plus a ZONE token when a
zone qualifies, ordered by `known_at` - the order a reader watching the bars live would have learned
them - and within a bar observation before interpretation (EXTREME, BREACH_REVERT, VOID, DISPLACE,
BREAK, then ZONE, then lifecycle). ORIGIN and LEG are left out: an ORIGIN is an EXTREME seen again
and a LEG is the span between tokens already there. Same-bar BREAKs (or DISPLACEs) from different
legs print once, the longest leg's. Tokens are `TYPE` plus an arrow (the canonical zone fixture, revisited and rejected):

```
EXTREME↑ DISPLACE↓ EXTREME↓ VOID↑ DISPLACE↑ VOID↑ BREAK↑ ZONE↑ VOID↑ EXTREME↑ VOID↓ DISPLACE↓ VOID↓ VOID↓ REVISIT↑ REJECT_PATH↑
```

This is v0's event sentence, unchanged but for the name REJECT_PATH; the candle productions are
not in it (they are in the interleaved view).

Optional binning (`bins=True`): `BREAK↑[force:weak|mid|strong,age:young|mid|old,took:0|1|2|3+]` -
force on magnitude (under 2, 2-4, 4+ ATR), age on `ref_age` (under 10, 10-19, 20+ bars; on walks
about 45%, 41% and 14% of breaks), took on `swings_taken`; `VOID↑[size:s|m|l]` on size (under
0.25, 0.25-0.75, 0.75+ ATR at its bar), `REVISIT↑[n:1|2|3+]`.

**The episode** (`serialise.episode`): one zone's parts in the order they happened, then its
lifecycle - `ORIGIN↑ DISPLACE↑ VOID↑ VOID↑ BREAK↑ REVISIT↑ REJECT_PATH↑`.

**The bar sentence** (`bar_words`, `bar_sentence`): one word a bar,

```
BULL(L,T,S,S){b:S,u:W,l:W,q4}/HH|c=h,o=l,c>ph,l=pc,o=ph
```

- direction(size, body, upper wick, lower wick): codes N VS S M L VL XL, N S M L T, N S M L; a
  warm-up bar prints `BULL(W)`;
- `{b: body force, u / l: wick force, q: close quartile}`: grades N W M S D, `-` in warm-up;
- `/` the relation to the previous bar, IN OUT HH LL, `+E` when the body engulfs;
- `|` the named point relations, within the bar and to the previous bar (codes in the table
  above). OPEN_AT_PREV_CLOSE and the four high/low-against-previous-high/low names are left out of
  the text because they hold on most bars or repeat the relation; `word(..., points="all")` prints
  them. JSON keeps everything.

**The interleaved view** (`interleaved`, `interleaved_text`): the bar words with every L2/L3
event (v0's and the candle productions) placed after the word of the bar at which it became known.
The canonical zone fixture, bars 26-32:

```
    26  BEAR(M,M,M,M){b:M,u:M,l:M,q2}/LL|c=l,o=h,c=pl,h=pc,h=po,o=pl
    27  BEAR(M,M,M,M){b:M,u:M,l:M,q2}/LL|c=l,o=h,c=pl,h=pc,h=po,o=pl
    28  BEAR(M,M,M,M){b:M,u:M,l:M,q2}/LL|c=l,o=h,c=pl,h=pc,h=po,o=pl
    29  BULL(M,M,M,M){b:M,u:M,l:M,q3}/IN|c=h,o=l,mirror,c=ph,c=po,h=ph,h=po,l=pc,l=pl,o=pl
    30  BULL(XL,T,S,S){b:D,u:W,l:W,q4}/HH|c=h,o=l,c>ph,l=pc,l=po,o=ph INSIDE_BREAK↑ DISPLACE_C↑
    31  BULL(XL,T,S,S){b:D,u:W,l:W,q4}/HH|c=h,o=l,c>ph,l=pc,o=ph EXTREME↓ VOID↑ DISPLACE_C↑ DISPLACE↑
    32  BULL(L,T,S,S){b:S,u:W,l:W,q4}/HH|c=h,o=l,c>ph,l=pc,o=ph VOID↑ BREAK↑ ZONE↑
```

(The fixture's bars all have wicks of exactly 0.25, which is also the smallest price difference in
the series, so the tick, and with it the tolerance, is 0.25: every wick is AT its end.)

**The derivation** (`derivation`): any entity's tree through `parts`, down to the candle words:

```
ZONE↑  [ZONE.U.28  at 28  known 32]
  ORIGIN↑  [ORIGIN.U.28  at 28  known 31]
    EXTREME↓  [EXTREME.D.28  at 28  known 31]
      BEAR(M,M,M,M){b:M,u:M,l:M,q2}|c=l,o=h  [CANDLE.D.25]
      ...                                       (seven tokens, 25-31)
  DISPLACE↑  [DISPLACE.U.30.o28  at 30  known 31]
    ...
  BREAK↑  [BREAK.U.32.o28  at 32  known 32]
    BEAR(M,M,M,M){b:M,u:M,l:M,q2}|c=l,o=h  [CANDLE.D.28]
    ...
    BULL(L,T,S,S){b:S,u:W,l:W,q4}|c=h,o=l  [CANDLE.U.32]
```

**Verbose text**: one token a line - `known_at at token id attributes force`.

**JSON** (`dumps`, `loads`, `"mcfl": 1`): the whole graph - tokens and entities with attributes
(the matrices as 16-character strings, named relations as lists), force and parts, relations,
failures, transitions, final states and pending candidates. It round-trips exactly
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
| "respected", "held" | REJECT_PATH | 1 ATR back its way before closing through (v0's REJECT) |
| rejection candle at the zone | REJECT | a strong wick toward the zone, closed back out, within 3 bars of the revisit |
| "price is accepted here" | ACCEPT | three closes inside |
| "invalidated" | FAIL | |
| CISD (change in state of delivery) | DELIVERY_SHIFT | a close above the open of the last down run's first bar, at most 3 bars after the run; in a zone's reaction window it CONFIRMs the revisit |
| displacement candle(s) | DISPLACE_C | two strong same-direction bodies closing in the outer quartile, or one extremely large dominant one |
| pin bar, hammer / shooting star | PIN | |
| engulfing | ENGULF | |
| inside bar break | INSIDE_BREAK | close beyond the mother bar after an inside bar |
| morning / evening star | STAR | |
| tweezer top / bottom | HIGH_AT_PREV_HIGH / LOW_AT_PREV_LOW | named point relations, within the tolerance |
| marubozu | OPEN_AT_LOW and CLOSE_AT_HIGH (bull) | within-bar point relations |
| doji | OPEN_EQ_CLOSE | |
| gap | OPEN_GAP_UP / OPEN_GAP_DOWN; a full gap HIGH_BELOW_PREV_LOW / LOW_ABOVE_PREV_HIGH | |
| higher high, lower low, ... (v2) | SWING↑[HH], SWING↓[LL], ... | labels of 3/3 swings |
| market structure bullish / bearish (v2) | STRUCTURE UP / DOWN | last high HH and last low HL / LH and LL |
| FVG filled / mitigated, inverted FVG (IFVG) (v2) | VOID_FILLED, VOID_PARTIAL, VOID_INVERTED | |
| BOS (v2, exactly) | BREAK[WITH] | a break in the direction of the structure |
| CHoCH, change of character (v2) | CHARACTER_SHIFT | the first break against an established structure |

## What the walk null shows

### v0: the event sentence

The v0 results below were measured before the rename; their REJECT is v1's REJECT_PATH, and
the event sentence and its counts are otherwise unchanged in v1.

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

### v1: the candle words against the walk

`research/mcfl/candle_study.py` puts the bar words through the same comparison: eight 5,000-bar
series per source, eleven matched iid-walk null sets, the data against the pool of ten and each
null set against the others; p floored at 1/12 = 0.083 ([`out/candles.txt`](../mcfl/out/candles.txt)).
Six alphabets: the fuzzy word (about 500 words seen), the fuzzy word with strength (about 3,300),
a coarse word, direction × size in 3 × body in 3 (18 seen), the coarse word with body force
(weak/strong) and close half (about 50), the coarse word with the bar relation (72), and the set of
named point relations a bar has (about 670). The two large alphabets and the point sets are
compared on KL at orders 1-2 only; with thousands of words their n-grams are mostly sparsity.

One caution first. `synth.trend` does not build bars the way `synth.walk` does: it spreads each
bar's return evenly over its sub-steps and adds within-bar noise that sums to zero. Candle shapes
depend on that construction, so momentum is measured against the same generator with phi = 0
(`trend0`, matched in volatility), not only against the walk.

| comparison | coarse n=1, n=2, k=1 | coarse+s n=1, n=2 | rel n=1, n=2, k=1 | points n=1 | full+s n=1, n=2 |
|---|---|---|---|---|---|
| iid walk vs walk null | 0.75, 0.17, 0.083 | 0.58, 0.58 | 1.0, 1.0, 0.75 | 0.75 | 0.25, 0.58 |
| GARCH vs walk null | **0.083**, 0.92, 1.0 | **0.083**, 0.33 | 0.92, 0.67, 0.50 | 0.50 | **0.083**, **0.083** |
| trend0 (phi 0) vs walk null | 0.92, 1.0, 0.92 | 0.92, 0.33 | 0.92, 0.67, 0.58 | **0.083** | 0.50, 0.92 |
| momentum (phi 0.2) vs trend0 null | 0.33, **0.083**, **0.083** | 0.58, **0.083** | **0.083**, **0.083**, **0.083** | **0.083** | 0.58, 0.83 |

(p-values; 0.083 is the floor, reached by nothing in eleven null sets.)

- **A walk sits inside its null at every order and in every alphabet.** The one p at the floor
  (coarse, k = 1) is one of 20 p-values; the walk's largest single differences are |z| = 3.1-3.3,
  which is what several hundred tests produce.
- **GARCH reaches the edge of the null on unigrams only, and only through magnitudes.** It is at
  the floor on coarse unigrams and on the strength alphabets, nowhere on transitions. Its largest
  single differences are |z| = 2.1-3.2 - no bigger than the walk's against itself - spread over
  large-range and weak-force words. The fuzzy classes are relative to the last ten bars and the
  force grades to the ATR, so clustering is mostly normalised away; what is left is a slightly
  different mix of sizes, not a different grammar. No candle production's rate moves (all |z| <
  2.4 on walks and GARCH).
- **Momentum is plainly visible, and it is what one would expect momentum to look like.** Against
  its own generator at phi = 0, every bigram and transition test is at the floor. Same-direction
  large bars follow each other: `U.l.l U.l.l` 13.1 per 1,000 words against 7.0 (z = +14),
  `D.l.l D.l.l` 11.9 against 7.2 (z = +8), three large up bars 1.55 against 0.47 (z = +10), and a
  large up bar followed by a large down one 3.4 against 7.0 (z = -7). In the relation alphabet, a
  large up HH bar is followed by another 14.5% of the time against 7.9% (z = +12); inside bars
  and outside bars become rarer. Unigrams barely move (coarse n = 1, p = 0.33): momentum lives in
  the order of the words, not their frequencies.
- **Point relations.** OPEN_AT_PREV_CLOSE is universal on every generated series (each bar opens
  at the last close), against walks and markets alike. The trend generator's construction shows up
  only as a few within-bar rates (trend0: CLOSE_AT_HIGH 235 against 231 per 1,000 bars, z = +3.7;
  OPEN_AT_PREV_HIGH +4.5). Momentum moves the cross-bar ones: closes beyond the previous range
  (CLOSE_ABOVE_PREV_HIGH 303 against 285, z = +10; CLOSE_BELOW_PREV_LOW +6.6), full-range gaps (a
  low AT the previous high 62 against 53, z = +16; a high AT the previous low +17), and fewer
  tweezers (HIGH_AT_PREV_HIGH 87 against 98, z = -8; LOW_AT_PREV_LOW -7) and body mirrors (-4.5).
  On the walk and GARCH no point relation is over- or under-represented beyond |z| = 2.8.
- **Candle productions.** On walks and GARCH every production occurs at the walk's rate and the
  next bar goes its way half the time (0.44-0.53, the spread of a few hundred cases; rate |z| at most 2.3). Under
  momentum, DISPLACE_C is more common (38 against 30 per 1,000 bars, z = +8) and ENGULF,
  DELIVERY_SHIFT and INSIDE_BREAK less (z = -13 to -4) - reversal shapes are rarer when moves
  persist. The next bar goes the pattern's way 0.58-0.66 of the time, but a bar of this process
  goes its predecessor's way 0.565 of the time anyway. ENGULF and DELIVERY_SHIFT (0.58) barely
  exceed that; DISPLACE_C (0.65-0.66) and INSIDE_BREAK (0.59-0.62) do; PIN (0.51) falls below it,
  since a pin points against the run it ends.

**Do candle words carry anything a walk does not, on synthetic data?** No: on a walk and on a
GARCH walk they read as a walk does, with the strength grades adding a faint, magnitude-only trace
of clustering. When the process has structure - momentum - the words show it at once, in their
order. So the layer is a calibrated instrument, and on these series it confirms the desk's
experience: the candle shapes traders name (pins, engulfings, stars, inside-bar breaks, CISDs)
appear on a random walk at the rate they appear anywhere else, and say nothing there about the
next bar.

**REJECT against REJECT_PATH** (per REVISIT, full parses of the same series):

| source | revisits | both | REJECT only | REJECT_PATH only | neither | agreement | kappa | P(REJECT_PATH \| REJECT) | P(REJECT_PATH \| no REJECT) |
|---|---|---|---|---|---|---|---|---|---|
| walk | 2,946 | 734 | 338 | 487 | 1,387 | 0.72 | 0.41 | 0.69 | 0.26 |
| GARCH | 2,918 | 782 | 278 | 465 | 1,393 | 0.75 | 0.47 | 0.74 | 0.25 |
| momentum | 2,710 | 579 | 266 | 351 | 1,514 | 0.77 | 0.48 | 0.69 | 0.19 |

The two agree moderately (kappa 0.41-0.48). A revisit with a candle REJECT is followed by
REJECT_PATH (1 ATR back out) 69-74% of the time against 19-26% without, and ends in FAIL 18-24%
of the time against 48-61%. **This is on random walks**, so it is geometry, not information: a bar
that has closed back out of the zone with a long wick has already moved away from the far edge,
and has the rest of the window to travel the remaining distance. Any claim that the candle REJECT
predicts a zone holding has to beat these walk numbers, not 50%.

**DISPLACE_C against v0's DISPLACE.** The candle displacement is a different thing from the ATR
displacement: about 61 DISPLACE_C per 1,000 bars on walks (half runs of two strong bodies, half
single extreme bars) against 132 bars carrying a v0 DISPLACE. Only 23% of DISPLACEs have a
same-direction DISPLACE_C anywhere on their leg, and 50% of DISPLACE_Cs fall inside a DISPLACE leg,
where those legs cover 25% of bars per direction - twice chance, so they overlap, but neither
implies the other. v0's measures how far a leg went from its origin, however it got there; the
candle form measures how a bar or two looked. Under momentum the candle form rises (75 against 61
per 1,000 bars) while v0's does not move (128 against 132).

**CONFIRMED.** A DELIVERY_SHIFT confirmed 260 of 2,946 revisits on walks (8.8%), 249 of 2,918 on
GARCH and 152 of 2,710 under momentum.

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

### v2

- **v2 is part of the default parse.** `parse(df)` adds every v2 entity and attribute (FOCuS and
  CUSUM only with `changepoints=True`, multiple timeframes through `mtf.py`), so the v1 truncation
  and flip tests cover v2 as well; `parse(df, v2=False)` is the v1 chart, entity for entity.
- **Swing labels (item 1).** The equality tolerance is SWING_EQ_ATR = 0.1 ATR at the later swing,
  not v1's EQ_ATR (0.05, for adjacent price points): swings are further apart in time and price. An
  equal high or low makes the state MIXED - the brief's UP is HH and HL, and an equal high is not a
  higher one. The first swing of each kind has no label. Labels known on one bar are applied together.
- **STRUCTURE_SHIFT's direction** is the direction the state moved in the order DOWN < MIXED < UP
  (UP → MIXED is a shift down), so every shift has one and the flip maps it.
- **vs_structure reads the state at the break's bar**, not at its known_at (a break can be known up
  to three bars later, when its origin swing is confirmed). Both are causal; the bar is what a trader
  means by "the structure when it broke".
- **CHoCH (item 11)**: "established" counts labels, not shifts, and includes the label that set the
  state; "first" is per run of the state and in the order breaks became known, so a truncated parse
  finds the same one. At most one per bar (two legs breaking on one bar make one CHoCH, the longer
  leg's).
- **VOID transitions are exact** (no tolerance), like the VOID: entering is a low strictly below
  the near edge, filling a low at or below the far edge, inverting a close strictly below it. A void
  is followed to the end of the series (no expiry); INVERTED is terminal. The transitions go into
  `Chart.transitions` beside the zones', keyed by the VOID's id.

### v1

- **The rolling window includes the current bar**, as Nautilus does (causal: the bar is known at
  its close). A token is emitted for every bar from bar 0, with WARMUP classes until its window is
  full, rather than no token: level events need every bar's lexeme.
- **s = 0 is the middle class**, not VERY_SMALL; a literal reading of the thresholds would call
  every bar of a flat window VERY_SMALL.
- **HH_LL does not exist.** With INSIDE and OUTSIDE defined as in the brief, a bar that is neither
  extends one way only: HH or LL.
- **ENGULF needs a strictly larger body**, and is an attribute of BAR_RELATION, not a fifth `rel`
  value: a bar can be OUTSIDE and engulfing at once. On our gapless generated bars (each opens at
  the last close) a reversal bar engulfs whenever it moves further than the bar before, so ENGULF is
  frequent (about 24% of bars).
- **INSIDE_BREAK reads `beyond`**, the close against the mother bar's range, kept on BAR_RELATION so
  the pattern references tokens only; the mother of a run of inside bars is its outer bar.
- **REJECT needs one price condition** (the close back out of the zone), since "closed back out" is
  a relation to a zone, not a class; likewise DELIVERY_SHIFT (close above the run's first open). The
  candle REJECT does not drive the state machine; v0's REJECT is kept as REJECT_PATH and does. The
  rename meant editing three v0 tests (the name only; their checks are unchanged), and the v0
  lifecycle test now filters the zone's events to lifecycle types.
- **Strength.** `body≥STRONG` reads the body's force grade (body_atr); the conviction grade
  (body_conv) is the fuzzy body class renamed, available as `conv`. Wick strength is the force
  grade of the wick (wick_atr); the share grade is `wick.up.share`. The rejection ratio is not
  graded. PIN, REJECT and DISPLACE_C are redefined on these, as the desk asked: PIN on wick and body
  force and the close quartile, keeping the brief's "other wick NONE or SMALL" as `wick.up≤WEAK`;
  DISPLACE_C's single-bar form is EXTREMELY_LARGE with a DOMINANT body closing in Q4.
- **DISPLACE_C fires once per run**, at the token where the run reaches two (a RUN qualifier with
  an `unless` on the token before), so its parts are those two tokens; a longer run is not extended.
- **CONFIRMED** is a live state that behaves as REVISITED, recorded before REJECT_PATH in its bar.
- **The tick, when not given, is a running minimum** of non-zero price differences, not the
  series' minimum, which would read the future.
- **Point relations use a tolerance; `rel` and `engulf` do not**, as the brief defined them. So
  HIGH_ABOVE_PREV_HIGH (beyond the tolerance) and `rel = HH` (exact) can disagree on a bar whose high
  is a hair above the previous one.
- **BREAK `swings_taken`** counts standing swing highs whose first close above is the break bar.
  The reference itself is not counted if it had been closed above before the origin (it can then be
  0).

### v0

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
