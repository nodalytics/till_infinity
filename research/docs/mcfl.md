# MCFL v2 and the time core: a formal language for what a chart shows, and what a walk shows too

Code: [`research/mcfl/`](../mcfl/README.md). Specification written 2026-10-03 with v0 of the parser
and extended the same day to v1 and v2; the time core added 2026-10-04. v0-v2 were run on generated
bars only; the time core's study is the first run on market data (twelve MT5 markets, below).

**What the time core adds** ([Time core](#time-core)): every entity is an interval in bars and in UTC
with its `known_at_ts` and its trading against calendar time; EPISODE; Allen's interval relations as
clause operators; calendar tokens and a configurable holiday calendar; WINDOW anchors (sessions, ICT
killzones and macros), day, week and month opens and HTF_CLOSE - now the clock every multi-timeframe
relation reads by; remaining time and HTF progress; TIMEOUT, STALL, SESSION_FIRST_MOVE, LATE / EARLY;
the bar, wall-clock, trading, volume and event clocks with volume and tick bars; and seasonality: a
time-of-day volatility class, TEMPO_STATE and an hour rate on every event.

**What the sweeps study adds** ([Sweeps](#sweeps-failed-breaks-sweep-and-shift-inducement-broken-structures-protected-levels)):
the close-beyond failure (CLOSE_REVERT), a sweep followed by a shift the other way (SWEEP_SHIFT, rows of
the rule table), INDUCEMENT at a zone's first revisit, a broken zone's or FVG's first return
(BREAKER_RETEST, RECLAIM) and protected lows and highs graded STRONG, SWEEP_STRONG or WEAK (PROTECTED,
PROTECTED_TAKEN) - with the same causality, symmetry and brute-force tests.

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
| RANGE | v2: a box of k bars within x ATR, with its tests and escapes (v2 item 5 below; v0 reserved the name) | `high`, `low`, `height_atr`, `atr`, `bars` | the detecting bar |
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

### 7. Retracement depth

`retrace.py`. For an up structure (down mirrored): the leg runs from the structure's low L to the
peak P, the retracement from P down to the pullback's low x, and

```
depth = (P - x) / (P - L)       SHALLOW < 0.382 <= HALF < 0.618 <= DEEP <= 1 < BEYOND (past the origin)
```

| event | where | P, x | `known_at` | parts |
|---|---|---|---|---|
| **RETRACE** | every REVISIT of a zone, at the revisit bar t | P = the highest high from the origin to t - 1, x = low[t]; L = the zone's far edge | t | the REVISIT |
| **PULLBACK** `phase=INSIDE` | per BREAK: the last swing low strictly between its origin p and the break bar b, above the origin's low and confirmed by the break's known_at (the DAX course's "structural liquidity"; the confirmation clause was added with the time core, which found the leak - see its decisions) | P = the highest high of p..b (the leg to the break), x = the swing's price | the break's | the BREAK and the EXTREME |
| **PULLBACK** `phase=AFTER` | per BREAK: the first swing low after b | P = the highest high of p..that swing | max(the break's, the swing's) | the BREAK and the EXTREME |

Attributes `depth` (a number) and `depth_bin`, `peak`, `level` (x), and `revisit`, `count` or `break`,
`phase`. Text `RETRACE↑[DEEP]`, `PULLBACK↑[INSIDE:HALF]`.

Both are qualifiers through the v2 **entity qualifier** syntax (`grammar.qe`), the rule-table form
of v1's CANDLE[...]: `TYPE[key op value, ...]`, where a number compares with the attribute
(`PULLBACK[depth≥0.5]`), a value of a registered order compares by rank (`PULLBACK[depth≥HALF]` is
HALF, DEEP or BEYOND) and anything else is equality (`PULLBACK[phase=INSIDE]`). So **the DAX 50%
rule** ([`dax_smc.py`](../ideas/dax_smc.py) step 3: the structural liquidity is valid at or below the
50% of the leg, protected low to the break's high) is one row of the rule table:

```
DAX50_UP := BREAK_UP PULLBACK_UP[phase=INSIDE, depth≥0.5]       where PULLBACK.break == BREAK.id
```

known at the later of the two. The fixtures `DAX_DEEP` (a pullback to 0.8 of the leg: DAX50) and
`DAX_SHALLOW` (0.4: none) are in `tests/test_retrace.py`. With item 6's SWEEP_PROTECTED as the break's
origin, steps 1-3 of the DAX checklist are a sentence (below).

### 6. Liquidity pools and the protected sweep

`pools.py`. Written for highs (EQUAL_HIGHS); lows are the flipped chart.

| entity | definition | attributes | `known_at` | parts |
|---|---|---|---|---|
| **POOL** (L3), POOL↑ = EQUAL_HIGHS, POOL↓ = EQUAL_LOWS | when a swing high e becomes known, every earlier swing high within POOL_EQ_ATR (**0.1**) × ATR(14) at e of its price and still standing (no high strictly between them above the higher of the two) joins it. A third equal high makes a new POOL at its own bar (count 3); the earlier one is unchanged | `kind`, `count`, `level` (the highest member), `members`, `first` | e's (bar + 3) | the member EXTREMEs |
| **POOL_TAKEN** (L2) | the first bar after the pool's last member with a high above `level` | `pool`, `level`, `closed_back` (close ≤ level: the pool was swept; else closed through), `depth_atr`, `breach_revert` (how many members had a BREACH_REVERT on that bar; those events are parts too, relation LINK) | its bar | the POOL (and those BREACH_REVERTs) |
| **SWEEP_PROTECTED** (L2) | [`dax_smc.py`](../ideas/dax_smc.py) step 1, for a buy: a swing low s that trades below the last swing low q of the SWEEP_BACK (**40**) bars before it - q known by s, nothing below q between them - and closes back above q on s or the next bar. The low at s is PROTECTED. Direction UP: it protects an up move, like the ORIGIN at s | `swept` (q), `swept_level`, `level` (s's low), `origin` | s + 3 | q's and s's EXTREMEs |
| **DAX_SETUP** (L3) | the DAX checklist's steps 1-3 as one production: `SWEEP_PROTECTED_UP BREAK_UP PULLBACK_UP[phase=INSIDE, depth≥0.5]` where BREAK.origin = the sweep's origin and PULLBACK.break = BREAK | `sweep`, `break`, `pullback`, `depth` | the latest part's | the three |

A POOL_TAKEN that closed back links to BREACH_REVERT: v0's BREACH_REVERT is the same fact per
swing (traded through, closed back, before any close beyond), so the take lists the members'
on that bar - present exactly when the take closed back and the member had not been closed through
before. Relations: POOL CONTAIN each member; POOL_TAKEN TOUCH the POOL when it closed back, CROSS when
it closed through. Text `POOL↑[EQUAL_HIGHS:2]`, `POOL_TAKEN↑[SWEPT]` / `[THROUGH]`.

**SWEEP_PROTECTED is dax_smc's protected low exactly**: on walks and GARCH walks, both directions,
the set of protected lows equals that of the course's step 1 copied verbatim from
`dax_smc.long_setups`, and every `protected` low of `dax_smc.setups` (all steps) is one of them
(`tests/test_pools.py::test_sweep_protected_is_dax_smc_step_one`). DAX_SETUP differs from the course
in one documented way: its break is v1's BREAK (the leg's close above the last swing high known at
the origin, within LEG_MAX = 20 bars) where dax_smc allows 60.

### 5. RANGE as a structure

`ranges.py`; this replaces v0's reserved RANGE. A **RANGE** (L3, direction NONE) is detected causally
at bar t when the RANGE_BARS (**k = 10**) bars ending at t lie within RANGE_ATR (**x = 2**) × ATR(14)
at t, high to low. Its box is that window's highest high (`high`) and lowest low (`low`); its bar is
the window's first, its `known_at` t, its parts the window's CANDLEs. One range is live at a time; the
next window must start after the bar that confirmed the last one's escape. While it lives:

| event | definition | `known_at` | attributes |
|---|---|---|---|
| **RANGE_TEST**↑ / ↓ | a bar whose high comes within TEST_ATR (**0.1**) × the range's ATR of the top (low of the bottom), closing inside - the first of each run of such bars | its bar | `range`, `level`, `count` (that edge's tests so far) |
| **ESCAPE**↑ / ↓ | ESCAPE_HOLD (**m = 3**) consecutive closes beyond an edge, the first included; the range ends | the m-th close (bar + 2) | `range`, `level`, `upper_tests`, `lower_tests` |
| **FAILED_ESCAPE**↑ / ↓ | a close beyond an edge, then a close back inside (at or within the edge) before m closes beyond. The range lives on; the failure counts as a test of that edge | the close back | `range`, `level`, `bars_out` |

An escape's `at` is its first close beyond; its parts the CANDLEs from there to the bar that decided
it. A RANGE whose last excursion is undecided at the end of the series has neither event yet. Text
`RANGE·`, `RANGE_TEST↑[2]`, `ESCAPE↑`, `FAILED_ESCAPE↓`. The fixtures use the warm-up itself, which
is a range (99.75 .. 100.75, ATR 1, known at bar 14 when the ATR first exists).

### 2. Compression and expansion words

`candles.compression` adds four L1 qualifiers to the token table; `grammar.WORDS2` holds the runs.

| qualifier | token | definition |
|---|---|---|
| **NR4**, **NR7** | CANDLE | the bar's range (h - l) is strictly narrower than each of the 3 (6) bars before it: the narrowest of the last 4 (7). Ties are not |
| **WR7** | CANDLE | strictly wider than each of the 6 before it |
| **overlap** | BAR_RELATION | the share of the bar's range inside the previous bar's: (min(h, ph) - max(l, pl))+ / (h - l); a zero-range bar is 1 inside the previous range, 0 outside; none on bar 0 |

In the qualifier syntax the flags are bare names (`CANDLE[NR7]`, `CANDLE[not WR7]`) and overlap is a
number (`CANDLE[overlap≥0.75]`). The runs are words over them, firing once per run where it reaches k:

| event | production (up side) | direction | parts |
|---|---|---|---|
| **BALANCE** | `RUN[k≥3, overlap≥0.75]` - three bars each at least BALANCE_MIN (**0.75**) inside the one before | none (NONE): one event where it holds both ways | the three CANDLEs and BAR_RELATIONs |
| **IMBALANCE** | `RUN[k≥3, overlap≤0.25, rel=HH]` - three bars each at most IMBALANCE_MAX (**0.25**) inside the one before, each a higher high | UP; DOWN on the flipped chart (LL) | likewise |

A non-directional word is a `Word(..., sym=True)`: it is evaluated on both frames and emitted once,
with direction NONE, where it holds in both. The bar word carries the qualifiers after a `#` with
`bar_words(chart, v2=True)`: `BULL(M,M,M,M){...}/IN|... #NR4,ov1.00` (overlap printed to two
decimals).

### 8. Time and tempo

`timing.py`. Time words need a `ts` column (each bar's open, epoch seconds, UTC); a chart without one
has none. Tempo needs only bars.

**SESSION** and **DAY_OF_WEEK** are L1 qualifiers of every CANDLE (`session`, `dow`), from the UTC hour
and day of the bar's open, with fixed hours (no daylight saving):

| session | UTC hours | code |
|---|---|---|
| ASIA | 22:00 - 07:00 | AS |
| LONDON | 07:00 - 12:00 | LN |
| OVERLAP | 12:00 - 16:00 (London and New York both open) | OV |
| NY | 16:00 - 22:00 | NY |

Qualifiers `CANDLE[session=LONDON]`, `CANDLE[dow=FRI]`; the bar word ends `@LN.MON`. A session
**instance** is a run of consecutive bars with one session (a gap over 12 hours starts a new one).

| event | definition | `known_at` | attributes |
|---|---|---|---|
| **SESSION_OPEN** (NONE) | the first bar of each instance | that bar | `session`, `price` (its open) |
| **SESSION_EXTREME**↑ / ↓ | an instance's high / low, at the bar that made it (the first on a tie) | the first bar of the next instance: when the clock has shown the session over | `session`, `price`, `start`, `end`; parts the instance's CANDLEs |
| **SESSION_EXTREME_TAKEN**↑ / ↓ (SESSION_HIGH_TAKEN, SESSION_LOW_TAKEN) | the first bar, from the next instance on and before the same session's next instance, whose high is above the session high (low below the low) | its bar | `extreme`, `session`, `level`, `closed_back` |

**Tempo.** Every lifecycle event of a structure gets `tempo`, the bars since the previous event of the
same structure: a zone's REVISIT, REJECT_PATH, ACCEPT, FAIL and EXPIRE since the zone qualified or its
last event; a VOID's transitions since the void or its last transition; a RANGE's tests and escapes
since the range was known or its last event. And `pace`, by a rolling quantile of the same event
type: FAST when the tempo is at or under the 25th percentile of the last TEMPO_WINDOW (**50**) tempos of
that type known before it, SLOW at or over the 75th, NORMAL between, WARMUP with fewer than TEMPO_MIN
(**10**) of them. "A fast return" is then grammatical: `REVISIT[pace=FAST]`, and the text form is
`REVISIT↑[FAST]`.

### 9. Changepoints as events

`changepoints.py`, with `parse(df, changepoints=True)`. The research detectors are called as they are
(imported read-only); MCFL only turns their output into entities.

| event | detector | `at` | `known_at` | attributes |
|---|---|---|---|---|
| **FOCUS**↑ / ↓ | production's FOCuS (`till_infinity.structures.learning.focus.Focus`) through [`prims.focus_series`](../ideas/prims.py), fed exactly what `zone_events.py` feeds it: x = the close-to-close change (0 on bar 0), scale = EWM(span 100) of abs(x) shifted one bar × √(π/2); ↑ looks for an increase, ↓ a decrease, each resetting after a fire; threshold **12 + 3 ln(3600 / sec)**, at least 3 | the bar the change started (the detector's `at`) | the bar it fired | `threshold`, `lag` |
| **FOCUS6**↑ / ↓ | the same at threshold **6**, the sensitive variant | likewise | likewise | likewise |
| **CUSUM_IGNITION**↑ / ↓ | [`survivors.cusum`](../ideas/survivors.py), k = **0.5**, h = **5**: the first bar the up (down) sum of log returns, drifting k σ, crosses h σ (σ the 60-bar sd lagged 30), re-armed at 0 | its bar | its bar | `k`, `h` |
| **FOCUS_ZONE** (L3) | a production: `ZONE_UP FOCUS_UP` with the change starting within 3 bars of the zone's origin and fired by the zone's `known_at` (zone_events' `fc_origin`, made causal: it reads the fire only if known when the zone is); one row for FOCUS, one for FOCUS6 (the id's suffix is the threshold) | the zone's | the zone's | `of_zone`, `focus`, `threshold`, `lag` |

`sec`, the bar's length, is given (`parse(..., sec=900)`) or read from the first two timestamps, else
an hour (threshold 12). Parts: a FOCUS the CANDLEs from its start to its fire, a CUSUM its bar's.

`tests/test_changepoints.py` checks that FOCUS and FOCUS6 equal `prims.focus_series` run with
zone_events' own inputs, and CUSUM_IGNITION `survivors.cusum`, on walks, GARCH and momentum walks, at
every fire, both directions. FOCUS is flip-symmetric under the arithmetic flip. CUSUM reads log
returns, which do not exist on the flipped (negative) chart; its mirror is the log-price flip
(prices inverted, 1 / p), under which CUSUM_IGNITION↓ of a chart is CUSUM_IGNITION↑ of the inverted
one - tested. That is why the detectors are an option of the parse rather than part of every one:
the package-wide flip test parses the negated chart.

### 3. Volume: effort against result

`volume.py`. Any volume column works: tick volume on CFDs, real or taker volume on exchanges. Three
L1 qualifiers of the CANDLE:

| qualifier | definition |
|---|---|
| **VOLUME** (`volume_class`) | the bar's volume in the rolling distribution of the last 10 bars' volumes, with the size classes' edges: NONE (zero), VERY_SMALL ≤ m - s, SMALL ≤ m - 0.5 s, MEDIUM ≤ m + 0.5 s, LARGE ≤ m + s, VERY_LARGE ≤ m + 2 s, else EXTREMELY_LARGE; WARMUP until the window is full, or with no volume |
| **EFFORT_RESULT** (`effort`) | volume (effort) against size (result): ABSORPTION volume ≥ LARGE and size ≤ SMALL (much traded, little moved); EASE volume ≤ SMALL and size ≥ LARGE; AGREE both ≥ LARGE or both ≤ SMALL; NEUTRAL otherwise; WARMUP while either is |
| **TAKER_SKEW** (`taker_skew`, `taker`) | with a `taker_buy_volume` column (and `taker_sell_volume`, else volume - buy): (buy - sell) / volume, and BUY at ≥ TAKER_MIN (**0.2**), SELL at ≤ -0.2, else BALANCED |

Qualifiers `CANDLE[vol≥LARGE]`, `CANDLE[effort=ABSORPTION]`, `CANDLE[taker=BUY]`; the bar word
carries `v:XL,ABS,tb`. Under the flip buyers and sellers trade places: `parse.flip` swaps the two taker
columns, so BUY and SELL swap and the skew is negated exactly. Generated series have no volume of
their own (each bar's is its sub-step count); `synth.ticks` gives them a tick volume (Poisson in the
bar's range, with a lognormal burst) and a taker split leaning with the bar, so the null walks have the
same kind of volume as the series compared with them.

### 12. Candle range theory (CRT)

`crt.py`. **RANGE_CANDLE** is any CANDLE read as a box - its high, low and 50% mid. It is not a new
entity: the candle is a part of what is built on it (usually a higher timeframe's candle, below).

| entity | production / definition | `known_at` | attributes |
|---|---|---|---|
| **PURGE**↑ (↓ on the flipped chart) | a word over the v1 relation words of the next candle: `RANGE_CANDLE CANDLE[HIGH_ABOVE_PREV_HIGH, not CLOSE_ABOVE_PREV_HIGH, not CLOSE_BELOW_PREV_LOW]` - it trades beyond the range's high and closes back inside (close ≤ prev high and ≥ prev low, within the point tolerance). An outside candle closing inside purges both sides | the purge candle | `depth_atr` (beyond the high, ATR), `close_loc` (from the purged edge, 0, to the other, 1; slightly negative when the close is above the high within the tolerance), the box `upper_edge`, `lower_edge`, `range_mid` |
| **DISTRIBUTION**↓ (after PURGE↑) | within CRT_N (**3**) candles after the purge, a low at or below the range's low - CRT's outcome event | the first such candle | `purge`, `bars`, `mid_bars` (bars after the purge at which the mid was first reached), `mid_same_bar` (first reached on the distributing candle itself, so the bar does not order them) |
| **CRT3**↓ (L3) | `RANGE_CANDLE PURGE_UP DISTRIBUTION_DOWN`, a row of the rule table | the distribution's | `purge`, `bars`; its bar is the range candle's |

Text `PURGE↑`, `DISTRIBUTION↓[2,mid:1]`, `CRT3↓`. Multi-timeframe CRT (an HTF range candle whose purge
is seen on LTF candles) is item 10's `mtf.crt`, below.

### 10. Multiple timeframes

`mtf.py`: `parse_mtf(df, htf_sec=14400, label="4h")` parses the lower timeframe (LTF), builds the
higher timeframe (HTF) from it, parses that, and relates the two; `parse_mtf(df, ..., htf=bars)`
takes the HTF chart's own bars instead and maps them onto the LTF bars by time.

**Aggregation.** An HTF bar is built from the LTF CANDLE tokens' lexemes: the first open, the highest
high, the lowest low, the last close, the summed volume (and taker volumes). Bars are grouped by time
(`ts // htf_sec`), or by count (`factor`) without timestamps. An HTF bar is **complete** - and anything
read from it known - at the LTF bar that closes its period (that bar's `ts` plus the LTF bar length
reaches the period's end), or, when bars are missing at the end, at the next period's first bar; by
count, at its last bar. The incomplete last bar is never used. The HTF chart is then parsed as any
chart, so its CANDLE words are fuzzy classes against the HTF's own history, and every HTF entity is
read in LTF time: `MTF.span(e)` (the LTF bars of its HTF bars - a BREAK's leg from its origin to its
break bar, a LEG's origin to end, a ZONE's origin to break, a RANGE's window) and
`MTF.known_ltf(e)` (the LTF bar at which its HTF `known_at` bar is complete). HTF ids are prefixed
with the label: `4h:BREAK.U.66.o57`.

| relation | meaning | `known_at` |
|---|---|---|
| CONTAINS_TF(H, L) | the HTF entity's span holds L's bar. Materialised for each HTF CANDLE → the LTF CANDLEs it was built from (the aggregation's derivation); on demand for any pair (`MTF.contains`) | the later of the two |
| ALIGN / CONFLICT (L, H) | an LTF ZONE or BREAK against (a) the HTF STRUCTURE state known when L is: ALIGN when it is L's direction, CONFLICT when opposite, nothing when MIXED (H the STRUCTURE_SHIFT that set it); (b) an HTF BREAK whose leg spans L's bar **and which is known by L's known_at**: ALIGN same direction, CONFLICT opposite | L's |

**NESTED** (L3, `MTF.entities`): the desk's strongest finding (`zone_nested.py`, "inside_4h") as one
production, in its causal form:

```
NESTED_UP := ZONE_UP@LTF   where ZONE.at in span(BREAK_UP@HTF)  and  known_ltf(BREAK) <= ZONE.known_at
```

an LTF ZONE whose ORIGIN lies inside the leg of an HTF BREAK of the same direction - and only once that
HTF break was knowable when the LTF zone was. Parts the ZONE and the HTF BREAK (the first known),
attributes `of_zone`, `htf_break`, `htf_breaks`, `tf`. `mtf.nested_flags(m, mode)` gives the flag for
every LTF zone in four forms:

| mode | the HTF break must be | causal? |
|---|---|---|
| `causal` (default; = NESTED) | known by the LTF zone's `known_at` | yes |
| `entry` | known by the zone's first REVISIT (zone_nested's own later correction, CAUSAL=1) | for a trade entered at the revisit; not for the zone |
| `leg` | any whose leg spans the origin, whenever known | no |
| `research` | `leg`, among the HTF breaks zone_events recorded - those whose own HTF zone was later returned to (`zone_events_recorded`: 5 bars after the break exist and one of its four bounds was revisited before a close through it) | no: it reads the future twice |

**The research form reproduces `inside_4h` exactly**: `tests/test_mtf.py` runs `zone_nested.evs` on
the 15m walk and on its 4h aggregation and the flag's own leg test, and every LTF zone zone_nested
flags (qualified first returns filled at the near edge, body bound; 150-200 per series) has the same
flag, on two walks and two GARCH walks of 4,800 bars. **The causal form disagrees, and by a lot**: an
LTF zone qualifies within hours of its origin, while the HTF break whose leg holds that origin is
usually known days later, so on those walks the research form flags 49-84 zones per series and the
causal form 1-3; most research-flagged zones (over 50 in two series) are flagged only through breaks
the zone could not have known (`test_causal_and_research_forms_disagree`). This is the desk's lesson in
the language's terms: the conditioning event of a cross-timeframe relation must be known before the
entity it conditions.

**Multi-timeframe CRT** (`MTF.entities`): an HTF CANDLE j is the RANGE_CANDLE; its PURGE is seen on the
LTF, on the first LTF candle of the next HTF period (CONTAINS_TF) whose high is beyond the HTF candle's
high and whose close is back inside the HTF range - at that LTF bar, before the HTF candle closes;
DISTRIBUTION the first later LTF candle, up to the end of HTF period j + 1 + CRT_N, at the HTF range's
other side; CRT3 the three, as in item 12. Periods are read from the LTF bars' own timestamps, so a
purge is found at its LTF bar whether or not the HTF bar it falls in is complete.

### 13. The candlestick vocabulary

`vocabulary.py`. Every classical pattern is a row of a word table (`vocabulary.VOCAB`, run like
`grammar.WORDS`) over the v1 candle words, their strength grades and the OHLC point relations. There
is no new price code: where a pattern relates bars that are not neighbours (the point matrix relates
adjacent bars only) it compares two tokens' lexemes, as v1's VOID word does (`0.close > -2.body_mid`).
Every pattern is a **PATTERN** event: written once for its bullish (UP) side and run on the chart and
on the chart flipped, the flipped instance being its twin under the twin's name; known at its last
bar; parts the CANDLE (and BAR_RELATION) tokens it consumed; attributes

- `name`, the pattern's name on its side (HAMMER on UP, SHOOTING_STAR on DOWN);
- `pattern`, the pair's key, also the id's suffix (`PATTERN.U.57.hammer`), so several patterns can
  share a bar;
- `trend`, the STRUCTURE state (item 1) known at the bar before the pattern's first bar;
- SIGNAL_BAR also `quality`.

Text `PATTERN↑[HAMMER]`. A pattern with no direction (the dojis, DOJI_BAR) is one event with direction
NONE. A pattern whose canonical form is bearish (ON_NECK, IN_NECK, THRUSTING, ADVANCE_BLOCK, STALLED,
TWO_CROWS, UPSIDE_GAP_TWO_CROWS, IDENTICAL_THREE_CROWS) is written as its mirror and has the canon's
meaning on its DOWN side; its UP side, the mirror image, keeps the name. The direction of a PATTERN is
the direction of its signal, as TA-Lib signs its patterns (ADVANCE_BLOCK↓ is three rising bull bars),
which for the reversal patterns is not the direction of the bars.

**The trend.** Where the canon names one shape two ways by the trend before it, the trend is part of
the production: HAMMER and HANGING_MAN are one shape (a long lower wick), INVERTED_HAMMER and
SHOOTING_STAR another; written as HAMMER := shape after a DOWN structure and INVERTED_HAMMER := its
mirror shape after a DOWN structure, their twins are SHOOTING_STAR (the inverted shape after UP) and
HANGING_MAN (the hammer's shape after UP). BELT_HOLD also requires the down structure. Every other
pattern carries the trend as an attribute, so the canon's "after a downtrend" is `PATTERN[trend=DOWN]`
when it is wanted.

**Building blocks** (UP side): long body `body≥STRONG` (the body's force grade, body / ATR against its
rolling distribution); short `body≤MODERATE`; small `body≤WEAK`; doji `OPEN_EQ_CLOSE` (within the
point tolerance, 0.05 ATR); wick ratios `wick.low.body≥2`; and, new in v2, **point-cell qualifiers**:
`o>pc`, `c≤po`, `l>pc`, ... - one cell of the point matrix, this bar's o/h/l/c against the previous
bar's, ABOVE / EQUAL / BELOW with the tolerance (`grammar` compiles `x op py` to a clause on that
cell, read from the frame's own matrix, so it flips correctly).

**Single bars**

| pattern (UP / its twin) | production, UP side (cell: qualifiers) | also | in words |
|---|---|---|---|
| HAMMER / SHOOTING_STAR | `0: wick.low.body≥2, wick.up≤WEAK, body≤MODERATE, close≥Q3` | `STRUCTURE DOWN before` | a lower wick twice the body, little upper wick, after a down structure |
| INVERTED_HAMMER / HANGING_MAN | `0: wick.up.body≥2, wick.low≤WEAK, body≤MODERATE, close≤Q2` | `STRUCTURE DOWN before` | the hammer's shape upside down after a down structure (its twin, the hammer's shape after an up structure, is the hanging man) |
| SPINNING_TOP | `0: dir=BULL, body≤MODERATE, not OPEN_EQ_CLOSE, wick.up.body>1, wick.low.body>1` |  | a short body with both wicks longer than it |
| HIGH_WAVE | `0: dir=BULL, body≤WEAK, not OPEN_EQ_CLOSE, wick.up≥STRONG, wick.low≥STRONG, wick.up.body≥3, wick.low.body≥3` |  | a small body with very long wicks both ways |
| DOJI (no direction) | `0: OPEN_EQ_CLOSE` |  | open and close equal |
| LONG_LEGGED_DOJI (no direction) | `0: OPEN_EQ_CLOSE, wick.up≥STRONG, wick.low≥STRONG` |  | a doji with strong wicks both ways |
| DRAGONFLY_DOJI / GRAVESTONE_DOJI | `0: OPEN_EQ_CLOSE, CLOSE_AT_HIGH, wick.low≥MODERATE` |  | a doji at the bar's high with a lower wick (twin: at the low, an upper wick) |
| FOUR_PRICE_DOJI (no direction) | `0: OPEN_EQ_CLOSE, OPEN_AT_HIGH, OPEN_AT_LOW` |  | open, high, low and close all equal |
| TAKURI | `0: OPEN_EQ_CLOSE, wick.up≤WEAK, wick.low≥DOMINANT` |  | a dragonfly-like doji with a dominant lower wick |
| BELT_HOLD | `0: dir=BULL, body≥STRONG, OPEN_AT_LOW` | `STRUCTURE DOWN before` | a long bull body opening at its low, after a down structure |
| MARUBOZU | `0: dir=BULL, body≥STRONG, OPEN_AT_LOW, CLOSE_AT_HIGH` |  | FULL: a long body with no wick either way |
| OPENING_MARUBOZU | `0: dir=BULL, body≥STRONG, OPEN_AT_LOW, not CLOSE_AT_HIGH` |  | no wick at the open's end |
| CLOSING_MARUBOZU | `0: dir=BULL, body≥STRONG, CLOSE_AT_HIGH, not OPEN_AT_LOW` |  | no wick at the close's end |
| LONG_LINE | `0: dir=BULL, body≥STRONG, wick.up≤MODERATE, wick.low≤MODERATE` |  | a long body, modest wicks |
| SHORT_LINE | `0: dir=BULL, body≤WEAK, not OPEN_EQ_CLOSE, wick.up≤WEAK, wick.low≤WEAK` |  | a small body, small wicks |

**Two bars**

| pattern (UP / its twin) | production, UP side (cell: qualifiers) | also | in words |
|---|---|---|---|
| HARAMI | `-1: dir=BEAR, body≥STRONG; 0: body≤MODERATE, not OPEN_EQ_CLOSE, o≤po, o≥pc, c≤po, c≥pc` |  | a long bear body, then a short body inside it |
| HARAMI_CROSS | `-1: dir=BEAR, body≥STRONG; 0: OPEN_EQ_CLOSE, o≤po, o≥pc` |  | a long bear body, then a doji inside it |
| PIERCING / DARK_CLOUD | `-1: dir=BEAR, body≥STRONG; 0: dir=BULL, body≥STRONG, OPEN_BELOW_PREV_LOW, c<po` | `0.close > -1.body_mid` | a long bear, then a long bull opening under its low and closing above its body's middle |
| ON_NECK | `-1: dir=BULL, body≥STRONG; 0: dir=BEAR, OPEN_ABOVE_PREV_HIGH, CLOSE_AT_PREV_HIGH` |  | canon bearish (DOWN): a long bear, a bull opening under its low and closing at it |
| IN_NECK | `-1: dir=BULL, body≥STRONG; 0: dir=BEAR, OPEN_ABOVE_PREV_HIGH, CLOSE_AT_PREV_CLOSE` |  | canon bearish: the bull closes at the bear's close |
| THRUSTING | `-1: dir=BULL, body≥STRONG; 0: dir=BEAR, OPEN_ABOVE_PREV_HIGH, c<pc` | `0.close > -1.body_mid` | canon bearish: the bull closes into the bear's body, short of its middle |
| KICKER | `-1: dir=BEAR, body≥STRONG, OPEN_AT_HIGH, CLOSE_AT_LOW; 0: dir=BULL, body≥STRONG, OPEN_AT_LOW, CLOSE_AT_HIGH, LOW_ABOVE_PREV_HIGH` |  | a bear marubozu, then a bull marubozu wholly above it |
| MEETING_LINES | `-1: dir=BEAR, body≥STRONG; 0: dir=BULL, body≥STRONG, CLOSE_AT_PREV_CLOSE` |  | counterattack: opposite long bodies closing at the same price |
| SEPARATING_LINES | `-1: dir=BEAR; 0: dir=BULL, body≥STRONG, OPEN_AT_PREV_OPEN, OPEN_AT_LOW` |  | opposite bodies opening at the same price, the second a belt hold |
| MATCHING_LOW / MATCHING_HIGH | `-1: dir=BEAR; 0: dir=BEAR, CLOSE_AT_PREV_CLOSE` |  | two bears closing at the same price |
| HOMING_PIGEON | `-1: dir=BEAR, body≥STRONG; 0: dir=BEAR, body≤MODERATE, o≤po, c≥pc` |  | a long bear, then a short bear inside its body |
| DOJI_STAR | `-1: dir=BEAR, body≥STRONG; 0: OPEN_EQ_CLOSE, OPEN_GAP_DOWN` |  | a long bear, then a doji opening below its close |
| HIKKAKE | `-2: any; -1: rel=INSIDE; 0: HIGH_BELOW_PREV_HIGH, LOW_BELOW_PREV_LOW` |  | an inside bar, then a false break of it downward (a lower high and a lower low) |
| MODIFIED_HIKKAKE | `-3: any; -2: rel=INSIDE, close≤Q1; -1: rel=INSIDE; 0: HIGH_BELOW_PREV_HIGH, LOW_BELOW_PREV_LOW` |  | the hikkake after two inside bars, the first closing near its low |

**Three bars and more**

| pattern (UP / its twin) | production, UP side (cell: qualifiers) | also | in words |
|---|---|---|---|
| THREE_WHITE_SOLDIERS / THREE_BLACK_CROWS | `-2: dir=BULL, body≥MODERATE, wick.up≤WEAK, close≥Q3; -1: dir=BULL, body≥MODERATE, wick.up≤WEAK, close≥Q3, c>pc, o≥po, o≤pc; 0: dir=BULL, body≥MODERATE, wick.up≤WEAK, close≥Q3, c>pc, o≥po, o≤pc` |  | three bulls, each closing higher near its high and opening within the last body |
| ADVANCE_BLOCK | `-2: dir=BEAR; -1: dir=BEAR, c<pc, o≤po, o≥pc; 0: dir=BEAR, c<pc, o≤po, o≥pc` | `0.body_atr < -1.body_atr; -1.body_atr < -2.body_atr; 0.lower_atr > -2.lower_atr` | canon bearish: three bulls rising with shrinking bodies and growing upper wicks |
| STALLED | `-2: dir=BEAR, body≥STRONG; -1: dir=BEAR, body≥STRONG, c<pc; 0: dir=BEAR, body≤WEAK, OPEN_AT_PREV_CLOSE` |  | canon bearish (deliberation): two long bulls, then a small one opening at the close |
| THREE_INSIDE_UP / THREE_INSIDE_DOWN | `-2: dir=BEAR, body≥STRONG; -1: body≤MODERATE, o≤po, o≥pc, c≤po, c≥pc; 0: dir=BULL` | `0.close > -2.open` | a harami, then a close above the first open |
| THREE_OUTSIDE_UP / THREE_OUTSIDE_DOWN | `-2: dir=BEAR; -1: dir=BULL, engulf=BULL; 0: dir=BULL, c>pc` |  | an engulfing, then a higher close |
| MORNING_DOJI_STAR / EVENING_DOJI_STAR | `-2: dir=BEAR, body≥STRONG; -1: OPEN_EQ_CLOSE, OPEN_GAP_DOWN; 0: dir=BULL, body≥STRONG` | `0.close > -2.body_mid` | a long bear, a doji below its close, a long bull past the first body's middle |
| ABANDONED_BABY | `-2: dir=BEAR, body≥STRONG; -1: OPEN_EQ_CLOSE, HIGH_BELOW_PREV_LOW; 0: dir=BULL, LOW_ABOVE_PREV_HIGH` | `0.close > -2.body_mid` | a doji wholly below a long bear and wholly below the bull after it |
| TRI_STAR | `-2: OPEN_EQ_CLOSE; -1: OPEN_EQ_CLOSE, OPEN_GAP_DOWN; 0: OPEN_EQ_CLOSE, OPEN_GAP_UP` |  | three dojis, the middle one below the others |
| THREE_LINE_STRIKE | `-3: dir=BULL; -2: dir=BULL, c>pc; -1: dir=BULL, c>pc; 0: dir=BEAR, o≥pc` | `0.close < -3.open` | three rising bulls, then a bear from their close to below the first open |
| TWO_CROWS | `-2: dir=BEAR, body≥STRONG; -1: dir=BULL, o<pc, c<pc; 0: dir=BULL, o≥po, o≤pc` | `0.close > -2.close; 0.close < -2.open` | canon bearish: a long bull, a bear gapping above it, a bear opening in that one and closing in the first |
| UPSIDE_GAP_TWO_CROWS | `-2: dir=BEAR, body≥STRONG; -1: dir=BULL, o<pc, c<pc; 0: dir=BULL, o<po, c>pc` | `0.close < -2.close` | canon bearish: a long bull, a bear gapping above, a bear engulfing it that keeps the gap |
| STICK_SANDWICH | `-2: dir=BEAR; -1: dir=BULL, l>pc; 0: dir=BEAR` | `0.close <= (-2.close + 0.tol); 0.close >= (-2.close + (0.tol * -1.0))` | two bears closing at one price around a bull above them |
| UNIQUE_THREE_RIVER | `-2: dir=BEAR, body≥STRONG; -1: dir=BEAR, o≤po, c≥pc, LOW_BELOW_PREV_LOW; 0: dir=BULL, body≤MODERATE, c<pc` | `0.open > -1.low` | a long bear, a bear harami with a lower low, a small bull under its close |
| THREE_STARS_IN_SOUTH | `-2: dir=BEAR, body≥STRONG, wick.low≥STRONG; -1: dir=BEAR, body≤MODERATE, LOW_ABOVE_PREV_LOW, o≤ph; 0: dir=BEAR, body≤WEAK, wick.up≤WEAK, wick.low≤WEAK, rel=INSIDE` |  | three shrinking bears, each low higher, the last a small marubozu inside the second |
| IDENTICAL_THREE_CROWS | `-2: dir=BULL; -1: dir=BULL, OPEN_AT_PREV_CLOSE, c>pc; 0: dir=BULL, OPEN_AT_PREV_CLOSE, c>pc` |  | canon bearish: three bears each opening at the last close |
| TASUKI_GAP | `-2: dir=BULL; -1: dir=BULL, o>pc; 0: dir=BEAR, o≤pc, o≥po` | `0.close < -1.open; 0.close > -2.close` | a bull, a bull gapping above it, a bear from inside that one into the gap, not closing it |
| SIDE_BY_SIDE_WHITE_LINES | `-2: dir=BULL; -1: dir=BULL, o>pc; 0: dir=BULL, OPEN_AT_PREV_OPEN` | `0.body_atr <= (-1.body_atr * 1.5); 0.body_atr >= (-1.body_atr * 0.6666666666666666)` | a bull, then two like bulls side by side above a gap |
| RISING_THREE_METHODS / FALLING_THREE_METHODS | `-4: dir=BULL, body≥STRONG; -3: body≤MODERATE, dir=BEAR; -2: body≤MODERATE, c<pc; -1: body≤MODERATE, c<pc; 0: dir=BULL, body≥STRONG` | `-3.high <= -4.high; -3.low >= -4.low; -2.high <= -4.high; -2.low >= -4.low; -1.high <= -4.high; -1.low >= -4.low; 0.close > -4.close` | a long bull, three short falling bars within its range, a long bull closing above it |
| MAT_HOLD | `-4: dir=BULL, body≥STRONG; -3: body≤MODERATE, o>pc; -2: body≤MODERATE, c<pc; -1: body≤MODERATE, c<pc; 0: dir=BULL, o>pc` | `-3.low > -4.low; -2.low > -4.low; -1.low > -4.low; 0.close > -3.high; 0.close > -2.high; 0.close > -1.high` | a long bull, three short bars above a gap holding above its low, a bull closing above them |
| BREAKAWAY | `-4: dir=BEAR, body≥STRONG; -3: dir=BEAR, o<pc; -2: HIGH_BELOW_PREV_HIGH, LOW_BELOW_PREV_LOW; -1: HIGH_BELOW_PREV_HIGH, LOW_BELOW_PREV_LOW; 0: dir=BULL` | `0.close > -3.open; 0.close < -4.close` | a long bear, a bear gapping down, two lower bars, a bull closing inside the gap |
| CONCEALING_BABY_SWALLOW | `-3: dir=BEAR, OPEN_AT_HIGH, CLOSE_AT_LOW; -2: dir=BEAR, OPEN_AT_HIGH, CLOSE_AT_LOW; -1: dir=BEAR, o<pc, wick.up≥MODERATE; 0: dir=BEAR` | `-1.high > -2.close; 0.high >= -1.high; 0.low <= -1.low` | two bear marubozu, a bear gapping down with a wick into the second, a bear swallowing it whole |
| LADDER_BOTTOM | `-4: dir=BEAR; -3: dir=BEAR, o<po, c<pc; -2: dir=BEAR, o<po, c<pc; -1: dir=BEAR, wick.up≥MODERATE; 0: dir=BULL, o>po` | `0.close > -1.high` | three falling bears, a bear with an upper wick, a bull opening above its body and closing above it |

**Reversal bars outside the Japanese canon**

| pattern (UP / its twin) | production, UP side (cell: qualifiers) | also | in words |
|---|---|---|---|
| KEY_REVERSAL | `-9: any; -8: any; -7: any; -6: any; -5: any; -4: any; -3: any; -2: any; -1: any; 0: dir=BULL, LOW_BELOW_PREV_LOW, c>pc` | `0.low < -9.low; 0.low < -8.low; 0.low < -7.low; 0.low < -6.low; 0.low < -5.low; 0.low < -4.low; 0.low < -3.low; 0.low < -2.low` | a new 10-bar low, then a close above the previous close |
| OUTSIDE_REVERSAL | `-1: any; 0: rel=OUTSIDE, dir=BULL, CLOSE_ABOVE_PREV_HIGH` |  | an outside bar closing above the previous high |
| ISLAND_REVERSAL | `k = 1..4 island bars: -k: HIGH_BELOW_PREV_LOW; 0: LOW_ABOVE_PREV_HIGH, dir=BULL` | `the island bars' highs below the bar before the gap; 0.low above every island high` | a full gap down, 1 bar(s) wholly below it, a full gap up out of them |
| TWO_BAR_REVERSAL | `-1: dir=BEAR, body≥STRONG; 0: dir=BULL, body≥STRONG, c≥po` |  | a long bear, then a long bull taking back its whole body |
| THREE_BAR_REVERSAL | `-2: dir=BEAR; -1: LOW_BELOW_PREV_LOW; 0: dir=BULL, LOW_ABOVE_PREV_LOW, CLOSE_ABOVE_PREV_HIGH` |  | a bear, a lower low, a bull closing above that bar's high |
| OOPS | `-1: any; 0: OPEN_BELOW_PREV_LOW, h≥pl` |  | Williams: an open below the previous low, then back up to it |
| EXHAUSTION_BAR | `-3: dir=BEAR; -2: dir=BEAR; -1: dir=BEAR; 0: dir=BEAR, size≥VERY_LARGE, body≥STRONG, LOW_BELOW_PREV_LOW` |  | a very large bear bar at the end of a run of bears (the sellers' last push) |
| CLIMAX_BAR | `-1: any; 0: size≥VERY_LARGE, vol≥VERY_LARGE, LOW_BELOW_PREV_LOW, close≥Q3` |  | a very large bar on very large volume to a new low, closing in its upper half |
| SIGNAL_BAR | `0: dir=BULL, close=Q4, wick.up≤WEAK, conv≥MODERATE` |  | Brooks' bull signal bar; `quality` STRONG with a lower tail of a quarter of its range and at most half of it inside the previous bar |
| TREND_BAR | `0: dir=BULL, body≥LARGE` |  | Brooks: a bar that is mostly body |
| DOJI_BAR (no direction) | `0: body≤SMALL` |  | Brooks: a bar with a small body or none |

**Fixtures** (`tests/test_vocabulary.py`): for every pattern, a token table from explicit bars after
a quiet warm-up, with the pattern bars' rolling classes and grades set (neutral unless the fixture
says otherwise) - it fires at its last bar with `known_at` there; one bar or one qualifier changed and
it does not; and on the mirrored table it fires DOWN under its twin's name. On walks with gaps, the
parse of the flipped chart has every pattern with its twin's name and direction, and more than 40
patterns occur.

**Validation against TA-Lib.** TA-Lib (`talib`) is not installed in the lab's environment and was not
installed for this (the brief: no installs into the shared venv), so the agreement report against its
CDL functions is not made. Where the definitions differ on purpose, they are: TA-Lib measures bodies
and shadows against the average of the last 10 bars' real bodies or ranges (BodyLong, ShadowVeryShort
...); MCFL grades against the rolling mean and sd of the same measure (Nautilus' scheme, period 10),
and judges equality with 0.05 ATR (TA-Lib: a share of the average range). The comparison is the first
thing to run where TA-Lib exists.

**Gaps.** Generated bars open at the last close, as 24-hour markets' bars nearly do. A third of the
Japanese vocabulary needs a gap between one bar's close and the next bar's open (PIERCING, DARK_CLOUD,
the necks, KICKER, MEETING_LINES, DOJI_STAR, the doji stars, ABANDONED_BABY, TRI_STAR, the crows with a
gap, STICK_SANDWICH, TASUKI_GAP, SIDE_BY_SIDE_WHITE_LINES, MAT_HOLD, BREAKAWAY, CONCEALING_BABY_SWALLOW,
LADDER_BOTTOM, ISLAND_REVERSAL, OOPS) and **cannot occur at all** on such bars - while
IDENTICAL_THREE_CROWS, whose canon needs each open at the last close, is merely three falling bears.
`synth.gapped` adds an untraded overnight jump to each open; the study measures the vocabulary on it
too.

## Sweeps: failed breaks, sweep and shift, inducement, broken structures, protected levels

`sweeps.py`, added for the sweeps study ([sweeps.md](sweeps.md)), on merged v2 and the time core with
their rules: every entity has a `known_at`, is under the truncation tests (`tests/test_sweeps.py`
checks each at its `known_at` and one bar before; the every-prefix test of `test_v2_causality.py`
covers them too), is flip-symmetric (`test_v2_symmetry.py` compares every entity of the parse), and
the one production over entities is rows of the rule table. `core.SWEEP_TYPES` lists them. Each is
also checked against a brute-force restatement of its definition on GARCH walks.

What MCFL already had for the desk's sweep vocabulary, and which the study reuses rather than
repeats: the wick sweep or swing failure (SFP) is **BREACH_REVERT**; equal highs or lows swept is
**POOL_TAKEN[SWEPT]**; the candle-range sweep is **PURGE** (an HTF candle's: `mtf.crt`); a session raid
is **SESSION_EXTREME_TAKEN** with `closed_back`; the Judas swing is **SESSION_FIRST_MOVE**; the DAX
course's protected low is **SWEEP_PROTECTED**; the inverse FVG is **VOID_INVERTED**.

| entity | definition (written for a low / an up structure; the other side is the flipped chart) | attributes | `known_at` | direction |
|---|---|---|---|---|
| **CLOSE_REVERT** (L2), the close-beyond failure ("turtle soup") | a swing low (EXTREME↓, price P, known at k) whose first close under P after k is at u, and one of the next TURTLE_N (**3**) bars closes back at or above P: at the first such bar v. Once per extreme. Parts the tokens u..v | `extreme`, `level`, `through` (u), `bars` (v - u), `depth_atr` | v | the breach's, as BREACH_REVERT: CLOSE_REVERT↓ is a low closed through and reclaimed |
| **SWEEP_SHIFT** (L3), sweep then shift | `(BREACH_REVERT↓ \| CLOSE_REVERT↓) (DISPLACE_C↑ \| DELIVERY_SHIFT↑)` where `shift.at - SHIFT_K ≤ sweep.at ≤ shift.at` (SHIFT_K = **3**): four rows of the rule table, tried BREACH_REVERT before CLOSE_REVERT and DISPLACE_C before DELIVERY_SHIFT; the first that matches makes the one event of that bar and direction, binding its earliest sweep | `sweep`, `sweep_type`, `shift`, `shift_type`, `level` (swept), `bars` | the shift's bar | the shift's (the reversal's): SWEEP_SHIFT↑ follows a low swept |
| **INDUCEMENT** (L2) | at a ZONE↑'s first REVISIT (bar r): a swing low above the zone's near edge, known before it was taken, whose first take (a low under it) is within INDUCE_N (**10**) bars before r or on r; the latest-taken is bound (the lowest on a tie). Parts the ZONE, the REVISIT and the EXTREME | `zone`, `revisit`, `extreme`, `level`, `taken_at`, `bars`, `gap_atr` | r | the zone's |
| **BREAKER_RETEST** (L2) | a ZONE↑ broken by its FAIL, or a VOID↑ by its VOID_INVERTED, at bar f; the first bar t in f+1 .. f+BREAKER_MAX (**100**) whose high reaches the far edge again, closing at or under it: the broken structure is now the other side's level (the breaker; for a void, the inverse FVG's retest) | `of`, `kind` (ZONE or VOID), `level` (the edge), `broke_at`, `bars`, `wick_atr` | t | the structure's (a lifecycle event keeps its structure's direction: BREAKER_RETEST↑ is bearish) |
| **RECLAIM** (L2), the failed break | the same first return, closing back above the edge | as BREAKER_RETEST | t | the structure's |
| **PROTECTED** (L3) | for the leg from every swing low p: **STRONG** when the leg BROKE structure without trading under p (the low that caused the break; the trader's BOS when the BREAK is WITH); **SWEEP_STRONG** when also the low at p swept the previous swing low (SWEEP_PROTECTED) and the leg DISPLACED 2 ATR at or before the break; **WEAK** when the leg timed out (LEG_MAX bars, no break, never under p). A leg that traded under p makes none, and none is made if the low was traded under before it could be graded. Parts the LEG and, if any, the BREAK, SWEEP_PROTECTED and DISPLACE | `grade`, `level`, `origin`, `break`, `bos` | STRONG: its BREAK's; SWEEP_STRONG: the latest of its parts; WEAK: the leg's end | UP (it protects an up move, like the ORIGIN at p) |
| **PROTECTED_TAKEN** (L2) | the first bar after the PROTECTED is known whose low is under its level | `protected`, `grade`, `level`, `closed_back` (swept rather than broken), `bars` | its bar | the PROTECTED's |

Whether a protected low held until the next break of structure, whether an inducement made the zone
hold, and what a sweep was worth are outcomes, measured in [`ideas/sweeps.py`](../ideas/sweeps.py), not
part of the definitions. Text forms are the default (`CLOSE_REVERT↓`, `SWEEP_SHIFT↑`, ...).

## Time core

The roadmap's time core (between v2 and v3): time as a dimension of the language, not a tag on bars.
Built on merged v2 with its rules - `known_at` on everything (now also `known_at_ts`), every new
entity under the truncation tests, flip symmetry (time is unchanged by the flip), productions in the
rule table, and every new alphabet judged against walks given the same calendar
([below](#time-core-real-markets-against-walks-on-the-same-calendar)). `parse(df)` includes it;
`parse(df, time=False)` is the v2 chart, entity for entity. The calendar parts need a `ts` column
(bar open, UTC seconds); without one an entity still gets its interval in bars, and EPISODE, TIMEOUT
and STALL (one baseline for all bars) still exist.

### 1. Time in the core

`clocks.py`. **The clock.** Each bar has a length L known at it: `close_ts - ts` when the bars carry
their closes (volume and tick bars do), else the `sec` given, else the running minimum of the gaps
between opens. Bar 0 has no gap yet and takes the coarsest standard bar its open is aligned to (1m
... 1d; an hour if none), too long rather than too short, so nothing is stamped as known before it
could be. Whether a period has ended is the opposite question, and there bar 0's unobserved length
counts as 0 (`Clock.seen`): a guess must not close a session early.

**Every entity is an interval** (`core.Span`, the new `Entity.time`):

| field | meaning |
|---|---|
| `start`, `end` | bars, inclusive. An event's (L2) interval is the tokens it consumed and its own bar (a BREAK its leg, a PATTERN its bars, a STALL the confined bars; an event that consumed no token - a POOL_TAKEN, a SWING, a TIMEOUT - its own bar). A structure's (L3) is its derivation (ZONE origin to break, POOL first member to newest, RANGE its window). Exceptions: an EXTREME is its own bar (its window's right side is confirmation), a LEG runs from its origin to its end, a WINDOW has no last bar until it closes (`end` None) |
| `start_ts`, `end_ts` | the open of `start`, the close of `end` (a WINDOW: its scheduled start and end) |
| `known_at_ts` | the close of the `known_at` bar |
| `trade_sec`; `bars`, `seconds`, `gap_sec` | trading time (the bars' lengths summed) against calendar time; their difference is the clock's gaps - weekends, closures |
| `hour_rate` | item 8 |

Clauses read them by name (`known_at_ts`, `dur_bars`, `dur_sec`, `gap_sec`, `interval`,
`interval_ts`, `hour_rate`). **EPISODE** (L3) makes the lifecycles intervals: a ZONE to its ACCEPT,
FAIL or EXPIRE, a VOID to its VOID_INVERTED, a RANGE to its ESCAPE, known when that event is;
`of`, `outcome`, `events`, parts the structure and the ending event. JSON round-trips the spans.

### 2. Interval relations (Allen's algebra)

`intervals.py`. On half-open intervals - bars [start, end + 1), time [start_ts, end_ts) - exactly
one of BEFORE, MEETS, OVERLAPS, STARTS, DURING, FINISHES, EQUALS and the inverses AFTER, MET_BY,
OVERLAPPED_BY, STARTED_BY, CONTAINS, FINISHED_BY holds; WITHIN (STARTS, DURING, FINISHES or EQUALS)
is what a trader means by "during", HOLDS its inverse. Allen's CONTAINS is not v0's materialised
CONTAIN (parthood). `relate(x, y, "bar" | "time")` on demand; on the wall clock a weekend is time
(the Friday and Sunday bars are BEFORE, on the bar clock they MEET); an open WINDOW relates to
nothing on the bar clock. Every relation is a clause operator, so productions use them:

```
IN_WINDOW_UP := REVISIT_UP WINDOW[kind=SESSION]   where WINDOW.interval_ts HOLDS REVISIT.interval_ts
```

`REVISIT DURING SESSION[LONDON]` is `IN_WINDOW[name=LONDON]` of that row. Rows: REVISIT in a
session, SESSION_EXTREME_TAKEN in a killzone (ICT's raid), POOL_TAKEN in a macro window; attributes
`of`, `of_type`, `window`, `kind`, `name`, `rel` (the exact Allen relation). Decided at the event's
known_at, from windows open by then.

### 3. Calendar tokens

`calendars.py`, CANDLE qualifiers from the bar's open in UTC: `minute`, `hour`, `wom` (week of month,
days 1-7 are 1), `month` (JAN..DEC), `quarter` (QTR1..QTR4 - not Q1..Q4, the close quartiles the
flip swaps), `month_end` / `quarter_end` / `year_end` (the date is the period's last business day),
and `holiday` / `half_day` by the calendar's own local date. A `Calendar` is configuration: time zone,
holidays and half-days, closed weekends or not. NYSE (the default) lists 2024-2026 as published
(Good Friday 2024 makes Thursday 28 March the month's end); CRYPTO has none. `CANDLE[hour=8]`,
`CANDLE[month=DEC]`, `CANDLE[month_end]`, `CANDLE[not holiday]`.

### 4. Time anchors as events

`anchors.py`.

| entity | definition | `known_at` |
|---|---|---|
| **WINDOW** (L3, NONE) | a calendar window's instance at its first bar (a bar is in it when its open is): SESSION (v2's UTC hours), KILLZONE (ICT, New York time with daylight saving: ASIA_KZ 20-24, LONDON_KZ 02-05, NY_AM_KZ 07-10, LONDON_CLOSE_KZ 10-12, NY_PM_KZ 13:30-16), MACRO (02:33-03:00, 04:03-04:30, 08:50-09:10, 09:50-10:10, 10:50-11:10, 11:50-12:10, 13:10-13:40, 15:15-15:45 New York). `kind`, `name`, `sched_start`, `sched_end`, `open` | its first bar: the calendar has announced its end |
| **WINDOW_CLOSE** (NONE) | the instance's last bar; a session's close is WINDOW_CLOSE[kind=SESSION]. `window`, `close`, `high`, `low`, `complete` | that bar when its close reaches the scheduled end, else the next bar (bars missing at the end) |
| **DAY_OPEN** (NONE) | the first bar of a day, `clock` UTC or NY (midnight New York) | its bar |
| **WEEK_OPEN** (NONE) | the first bar of the trading week, which starts Sunday 17:00 New York | its bar |
| **MONTH_OPEN** (NONE) | the first bar of a UTC month | its bar |
| **HTF_CLOSE** (NONE) | every higher-timeframe bar's close: period `ts // tf` (default 1h, 4h, 1d, each longer than the bar), with the HTF bar's `open`, `high`, `low`, `close`, `bars`, `period_ts` | its last bar when that bar's close reaches the period's end, else the next bar |

An open event is at the bar whose period differs from the previous bar's (bar 0 only when it opens at
the period's start). **HTF_CLOSE is the shared clock of every multi-timeframe relation.** `mtf.py`
now takes `MTF.known` from the LTF chart's HTF_CLOSE events and reads an HTF entity only through
`MTF.visible(h, t)`; counted periods (no timestamps) get their own HTF_CLOSE events.
`tests/test_time_mtf.py` checks every MTF output against the LTF chart's HTF_CLOSE events alone,
independently of `MTF.known`, and shows that an MTF whose closes are moved an hour early fails it.

### 5. Elapsed and remaining time

`clocks.age(chart, e, t)`: bars, seconds, trading seconds and session WINDOWs since e became known.
In productions an age is a clause on the stamped fields (`C("known_at_ts", "<=", ("+",
"zone.known_at_ts", 3600))`). CANDLE qualifiers, in seconds from the bar's close: `left_session`,
`left_day` (to UTC midnight), `left_<tf>` and `prog_<tf>` (the share of the HTF bar elapsed:
`CANDLE[prog.4h≥0.75]`), and `killzone`, `macro` (the window's name or NONE).

### 6. Time-based events

`timed.py`.

| event | definition | at / `known_at` |
|---|---|---|
| **TIMEOUT** | rows of the rule table, each a structure and absent slots, decided TIMEOUT_BARS (**48**) bars after the structure is known: a ZONE with no REVISIT, a VOID with no VOID_PARTIAL, a RANGE with no excursion (FAILED_ESCAPE or ESCAPE: its edges are tested within a few bars almost always) - `kind`, `of`, `bars`; the RANGE row has no direction. Two grammar options make it a row: `timed` (the event is the decide bar, only once the series reaches it) and `sym` | the decide bar, both |
| **STALL** (NONE) | the bar's confinement c - bars back, itself included, inside STALL_ATR (**1**) ATR at the bar, at most 192 - first exceeds the STALL_Q (**90th**) percentile of the c of the last 120 bars that opened in the same UTC hour (at least 30). `bars`, `usual`, `hour` | its bar |
| **SESSION_FIRST_MOVE** ↑/↓ | in each SESSION and KILLZONE instance, the first EXTREME whose bar is inside it (a swing high: the first move was up). `kind`, `name`, `window`, `extreme`, `price`, `open`, `move_atr`, `bars`. Whether it was a Judas swing is an outcome, measured by the study, not part of the definition | the extreme's |
| **LATE** / **EARLY** | an event of BREAK, DISPLACE, ZONE, CHARACTER_SHIFT, SESSION_EXTREME_TAKEN, POOL_TAKEN or SESSION_FIRST_MOVE whose `hour_rate` is under **0.5**: LATE when its hour is after the type's usual hour (the circular mean of its recent hours), EARLY before. `of`, `of_type`, `hour`, `hour_rate`, `usual_hour` | the event's |

### 7. Several clocks

Bar time (`bar`), wall-clock time (`time`, the bar's close), trading time (`trade`), volume time
(`volume`, cumulative) and event time (`event`, one step per event known): `clocks.reading(chart,
clock)` is the same event sentence with each token at its known_at on that clock. `volume_bars(df,
size)` builds bars of equal volume (a source bar is not split; each is known at the source bar that
completes it) and `tick_bars(ticks, n)` bars of n ticks; both carry `close_ts`, so the parse runs on
them unchanged - the same grammar, on another clock (and TIMEOUT's 48 bars are then 48 volume bars).
`in_source` maps an entity back to the source bar it was known at; the tests check the volume-bar
parse is causal in source time.

### 8. Seasonality and tempo states

`seasonal.py`; every baseline is causal, per UTC hour of the day, over a fixed number of values known
strictly before.

| | definition |
|---|---|
| **tod_vol**, **tod_ratio** (CANDLE) | the bar's range against the last 80 bars that opened in the same hour: NORMAL inside their 10th-90th percentiles, UNUSUAL outside, WARMUP under 40; `tod_ratio` = range / their median. `CANDLE[tod=UNUSUAL]` |
| **TEMPO_STATE** (NONE) | events per hour (EXTREME, VOID, BREAK, DISPLACE, BREACH_REVERT, DELIVERY_SHIFT known in the last 4 hours of wall-clock time) against the same hour's last 80 rates: FAST above the 80th percentile, SLOW below the 20th, else NORMAL; an event where the state changes. `state`, `rate`, `lo`, `hi` |
| **hour_rate** (`Span`, every event) | 24 x the share of the type's last 400 events (known strictly before) that happened in this hour; 1 is the type's average hour. `BREAK[hour_rate<0.5]` is "rare for this hour". None for tokens and the calendar's anchors |
| `profile(chart)` | the market's time-of-day volatility profile: median range per hour over the median |

Any time effect is judged against walks on the same calendar with the same hour-of-day volatility
(`synth.profiled`, `synth.matched_profiled`).

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
| pin bar, hammer / shooting star | PIN; v2: PATTERN[HAMMER] / [SHOOTING_STAR] (with the trend) | |
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
| retracement, discount / premium, "the 50%" (v2) | RETRACE, PULLBACK[depth_bin], DAX50 | depth of a pullback in its leg |
| equal highs / lows, liquidity, "buy-side / sell-side liquidity taken" (v2) | POOL, POOL_TAKEN[SWEPT / THROUGH] | |
| protected low (the DAX course) (v2) | SWEEP_PROTECTED | `dax_smc.py` step 1, exactly |
| range, consolidation, box; breakout / fakeout (v2) | RANGE; ESCAPE / FAILED_ESCAPE | |
| NR4 / NR7, wide-range bar; balance / imbalance, overlapping or "clean" bars (v2) | NR4, NR7, WR7, overlap; BALANCE, IMBALANCE | |
| Asian range, London open, NY session; "London took the Asian high" (v2) | session; SESSION_OPEN, SESSION_EXTREME, SESSION_EXTREME_TAKEN | fixed UTC hours |
| a fast / slow return (v2) | REVISIT[pace=FAST] / [pace=SLOW] | tempo by rolling quartile |
| "momentum ignition", a change in drift (v2) | FOCUS, FOCUS6, CUSUM_IGNITION | the desk's own detectors |
| effort vs result, absorption, "no supply" (v2) | effort = ABSORPTION / EASE / AGREE; vol | Wyckoff's effort and result |
| CRT: range candle, purge (manipulation), distribution (v2) | RANGE_CANDLE (any CANDLE), PURGE, DISTRIBUTION, CRT3 | |
| HTF bias, "trade with the 4h", a 15m zone inside a 4h break (v2) | ALIGN / CONFLICT, NESTED | causal: the HTF event known first |
| the classical candlestick names (v2) | PATTERN[name] | item 13's table |
| BOS (v2, exactly) | BREAK[WITH] | a break in the direction of the structure |
| turtle soup, close-beyond failure (sweeps) | CLOSE_REVERT | a swing closed through and reclaimed within 3 bars |
| sweep then displacement / CISD, "manipulation then distribution" (sweeps) | SWEEP_SHIFT | a sweep and, within 3 bars, DISPLACE_C or DELIVERY_SHIFT the other way |
| inducement (sweeps) | INDUCEMENT | a minor swing above a zone taken just before the zone's first revisit |
| breaker block, inverse FVG retest; failed break (sweeps) | BREAKER_RETEST; RECLAIM | a broken zone's or FVG's first return to its far edge, holding beyond or closing back |
| strong / weak / protected high and low (sweeps) | PROTECTED[STRONG / SWEEP_STRONG / WEAK], PROTECTED_TAKEN | the low that caused a break of structure, and the same having swept a low and displaced |
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

### v2: the new alphabets against the walk

`research/mcfl/v2_study.py` ([`out/v2.txt`](../mcfl/out/v2.txt)): six 4,800-bar series per source -
an iid walk, GARCH(1,1), AR(1) momentum (phi 0.2) and a gapped walk (`synth.gapped`, overnight jumps
of 0.5 sigma) - each given 15-minute timestamps and a tick volume (`synth.ticks`) and parsed with the
changepoints; nine null sets per source (iid walks matched in volatility; for the gapped walk, gapped
walks), the data compared with the pool of eight and each null set with the others. p is floored at
1/10. **Calibration first**: with eight null sets, the walk against its own null reaches the p floor
on a few n-gram tests (the swing-label sequence at n = 2-3, the pool and range streams at n = 3) and
|z| up to 3.5-4 on shares that cannot differ (the share of escapes upward on GARCH, z = -3.7). So a
p at the floor or |z| under about 4 is noise here; the findings below are the ones well past that, or
consistent across measures.

| item | walk, GARCH, gapped walk | AR(1) momentum (the positive control) |
|---|---|---|
| 1 swing labels, STRUCTURE | every label and shift rate inside the null (|z| ≤ 1.8); time in UP / DOWN / MIXED 0.28-0.30 / 0.30 / 0.41 on all three, as on their nulls | fewer swings (EH, EL z ≈ -3), fewer shifts (z ≈ -4), less time MIXED (0.39 vs 0.41) |
| 11 vs_structure, CHoCH | WITH 31%, AGAINST 22%, NONE 46% of breaks, as on the null; 9 CHoCH per 1,000 bars; the next break after a CHoCH goes its way 52-57% (null 55-57%) | the same shares; fewer NONE breaks (z = -4.5); next break after a CHoCH 59% vs 56% (z = 1.1) |
| 4 VOID lifecycle | fill and inversion rates inside the null; 64-68% of voids are inverted on the bar they fill | many more voids (z = +20 to +28), each filled and entered more slowly (FILLED within 5 bars 45% vs 50%, z = -11) |
| 7 retracement | RETRACE at revisits is 79-82% DEEP, the rest BEYOND (geometry: a revisit reaches the body top, near the origin); INSIDE pullbacks mostly DEEP; GARCH a little more BEYOND (z = +4.6) | fewer pullbacks (z = -4.4), more SHALLOW after-break pullbacks (23% vs 20%, z = +3.9) |
| 6 pools, protected sweep | pool, take and sweep rates inside the null; 78-82% of pools taken within 100 bars, a third of takes close back (swept) | fewer pools, takes and protected sweeps (z = -3 to -4) |
| 5 RANGE | 6-7 ranges per 1,000 bars; ~58% of excursions escape; after an escape price goes a box height on before closing back in 65-68% of the time, as on the null | far fewer ranges (z = -8.8); escapes hold more (67% vs 58%) and run on more (76% vs 65%) |
| 2 compression | NR4/NR7/WR7 and the overlap runs inside the null; GARCH: after a WR7 the next 5 bars' mean range exceeds it 7.8% vs 5.0% (z = +11.5), after an NR7 slightly less often - volatility clustering, the one thing GARCH has | IMBALANCE runs twice as common (z = +16, +8), BALANCE rarer (z = -4.5) |
| 8 sessions, tempo | breaks and session-extreme takes spread over the sessions as on the null (the clock means nothing to a walk, and the study shows it); pace does not change what a revisit becomes | a SLOW revisit becomes REJECT_PATH less often (34% vs 43%, z = -7.6) |
| 9 changepoints | on walks and gapped walks FOCuS (12 + 3 ln 4 = 16.2) almost never fires (0.03 per 1,000 bars), FOCUS6 and CUSUM 1.3-1.7 per 1,000; what follows a fire is a coin (0.48-0.57) | GARCH and momentum double or triple the FOCUS6 and CUSUM rates (z = +6 to +14) and the FOCUS_ZONE share; the direction after a fire is still a coin at 5 and 20 bars |
| 3 volume | with tick volume built from the range, effort words read as on the null (ABSORPTION 1.1%, EASE 1.4% of bars; the next bar a coin after each) | different only through the trend generator's bar construction (see v1's caution), not information in volume |
| 12 CRT | a PURGE is followed by a DISTRIBUTION (the range's other side within 3 candles) **57-58% of the time on a walk** (gapped walk 61%), against 48% for an inside candle without a purge, identical on the null; in 65% it is the very next candle; the mid is reached on an earlier bar 24-28% of the time. CRT's base rate is geometry: the purge candle closes inside the range, often near the far side | CRT3 rarer (z ≈ -3), its hit rate unchanged (58%) |
| 10 multiple timeframes, 15m vs 4h | the research (non-causal) flag marks 20-23% of 15m zones, the causal NESTED **0.4-1.1%**; on walks the research-flagged zones' first revisits reach REJECT_PATH before FAIL 59% against 54% for all zones and 58% on the null's - the same "edge" appears on the walks it was compared with, so it is selection, not information; the 4h CRT seen on 15m distributes 49-50% | the nested flags carry nothing either (all-zone REJECT_PATH 45% vs 51%) |
| 13 candlestick vocabulary | every pattern occurs at the null's rate (GARCH: no rate beyond |z| = 3.5), except CLIMAX_BAR on the gapped walk, ↑ and ↓ moving opposite ways (z = -10.6, +6.5) in a process that is symmetric - its volume class varies between series more than eight null sets show; pooled over all patterns and trades, P(≥1R, 2R, 4R, 10R) = 0.49, 0.35, 0.23, 0.10 on walks, 0.49, 0.35, 0.22, 0.10 on GARCH, 0.48, 0.35, 0.22, 0.10 on gapped walks - the walk null's own 0.49, 0.35, 0.22, 0.10, against 1/(N+1) = 0.50, 0.33, 0.20, 0.09 (the discrete bars and the stop at the pattern's extreme put the finite-horizon walk a little above the continuous martingale at large N) | the continuation shapes gain: pooled P(≥1R) 0.54 vs 0.49, P(≥4R) 0.26 vs 0.22; LONG_LINE, MARUBOZU, KEY_REVERSAL, BELT_HOLD +4 to +10 z; HIKKAKE↑ worse (0.33 vs 0.41 at 1R) |

**Which new tokens differ from the walk null?** On an iid walk, a GARCH walk and a gapped walk,
**none** of the v2 alphabets does beyond the null's own spread, with two exceptions that are exactly
what those processes contain: GARCH moves the volatility-sensitive words (WR7 followed by wide bars,
more FOCuS and CUSUM fires, more RETRACE BEYOND), and nothing directional. Momentum, the positive
control, moves almost every alphabet - swings, voids, ranges, imbalance runs, pools, pullbacks, the
continuation candlesticks' P(N R) - so the instrument sees structure when there is some. The patterns'
P(N R) on walks sits on the walk's own curve (0.49, 0.35, 0.22, 0.10 at 1, 2, 4, 10 R), which is the
baseline any market measurement must beat, and slightly above 1/(N+1) for reasons of measurement.
CRT's 57-61% "success" and the nested zone's research flag both reproduce on random walks: geometry
and hindsight respectively. Real-market frequencies and P(N R) are not reported: no market data was
used in this build.

### Time core: real markets against walks on the same calendar

`research/mcfl/time_study.py` ([`out/time.txt`](../mcfl/out/time.txt)), run on the lab on
2026-10-04: twelve markets of MT5 15-minute bars (UTC; EURUSD, GBPUSD, USDJPY, XAUUSD, US SP 500, US
Tech 100, Germany 40, US Oil, BTCUSD, ETHUSD, and Deriv's Volatility 75 Index and Step Index -
markets in their own right, reported as such, not as controls), July 2024 to October 2026, cut into
115 chunks of 6,000 bars (690,000 bars). Each chunk was parsed with the time core, and so were six
walks of each of three kinds **on the chunk's own timestamps** (weekends, closures and holidays
carried over): **profile** - iid, with the chunk's own hour-of-day volatility (sd of close-to-close
changes per UTC hour) and its own overnight jumps, the null the brief asked for; **clustered** - the
same with GARCH(1,1) on top; **flat** - one volatility for every hour, the plain matched walk on the
calendar. 2,185 parses. z = (real - walk mean) / max(sd over the six walk sets, the real number's own
binomial or Poisson error). Numbers below are pooled over all markets unless named.

**Calibration.** Everything the calendar decides (WINDOW, WINDOW_CLOSE, the opens, HTF_CLOSE, the base
shares of bars per session, killzone, macro, month-end, Monday) is identical on real and walk, as it
must be. Several non-time counts differ on every market, Deriv's included, and are **not time
effects**: real charts have far fewer VOID episodes (206 against 335 per 1,000 bars), fewer zone
FAILs (19 against 29) and fewer zone TIMEOUTs (14 against 20). Deriv's synthetics, whose hours are
all alike, show the same gaps, so they come from how the bars are built (a 15-minute bar from ticks
against the walk's eight sub-steps; v1's caution), not from the clock.

**What the flat walk would have called a time effect, and the profile walk explains.**

| measure | real | profile walk | flat walk |
|---|---|---|---|
| BREAK hour concentration (chi-square / n against the bars) | 0.046 | 0.028 (z +12) | **0.0004** (z +275) |
| REVISITs in OVERLAP (12-16 UTC; 17% of bars) | 0.280 | 0.267 (+4.9) | 0.169 (+47) |
| session high or low taken inside an ICT killzone (61% of bars) | 0.675 | 0.658 (+5.1) | 0.598 (+31) |
| STALL per 1,000 bars | 37.1 | 37.0 (+0.4) | 33.8 (+14) |
| DISPLACE marked EARLY / LATE per 1,000 bars | 4.3 / 4.2 | 4.1 / 4.0 | 1.5 / 2.3 (+36, +25) |

Against the flat walk every one of these is an enormous "time effect"; against a walk with the same
hour-of-day volatility most of it is gone. Breaks, revisits, raids and stalls go where the volatility
is. What is left after the profile walk is small (killzone raids 67.5% against 65.8%, OVERLAP
revisits 28.0% against 26.7%) and **absent on Deriv** (raids in killzones 59.4% and 59.3% against
59.7% and 60.3% on their walks; BREAK hour concentration 0.005 against 0.005), as it should be for a
market without a day.

**Time effects beyond the profile.**
- **Session extremes form early, not late.** A walk puts a session's high and low near its ends (the
  arcsine law): 33.8% of them in the session's first quarter, 32.0% in the last, on the profile walk.
  Real sessions put 35.1% in the first quarter (z +6.4) and **29.5% in the last (z -13.6)**; the
  shortfall in the last quarter is there on every non-Deriv market (crypto most: ETHUSD 24.8% against
  31.8%, BTCUSD 26.6% against 31.4%) and on neither Deriv index (33.4%, 33.0% against 33.4%, 33.3%).
- **Mondays have fewer breaks than their bars** (16.8% of breaks on 17.7% of bars, z -5.7). The walk
  has no day-of-week profile (only hour-of-day), so this is the known day-of-week volatility, not
  something the language adds.
- **Bars UNUSUAL for their hour** are 23.3% against 22.1% (z +21; GARCH clustering takes it to 22.6%):
  real volatility has regimes the hour baseline does not know. Step Index is the exception (21.3%).
- **The event clock is burstier than the bar clock**: variance / mean of events per 16 bars 0.89
  against 0.72 (and 0.72 with GARCH), Deriv 0.77. Partly bar construction again (Deriv has it).
- Null: BREAKs on month-end days (4.0% of breaks on 4.0% of bars), BREAKs in the last quarter of a
  4h bar (24.4% on 25.4% of bars), pools taken inside a macro window (4.9% on 5.3% of bars - **ICT's
  macro windows hold nothing**), the share of zones that TIMEOUT once zones are counted (39.6% against
  39.6%), time in FAST and SLOW tempo (18.2% and 17.3% against 18.0% and 17.2%).

**The first move (the "Judas" swing).** The session's first swing is the session's own extreme 44.5%
of the time, as on the walk (44.7%). It reverses back through the session's open before going beyond
its own extreme 50.4% of the time against 47.2% (z +7.7) - but Deriv does too (49.8%, 50.5% against
47.3%, 47.4%), so this is short-horizon behaviour of real bars, not of sessions. **As a signal it
loses to the walk.** Fading the first move (entry at the close of the bar that confirms the swing, the
stop at the swing's extreme, the market's best excursion before the stop):

| P(≥ N R) | 1 | 2 | 3 | 4 | 5 | 10 |
|---|---|---|---|---|---|---|
| 1/(N+1) | 0.500 | 0.333 | 0.250 | 0.200 | 0.167 | 0.091 |
| fade, any session (29,769) | 0.486 | 0.334 | 0.250 | **0.200** | 0.164 | **0.078** |
| ... profile walk | 0.489 | 0.342 | 0.263 | 0.214 | 0.179 | 0.088 |
| fade, any killzone (35,479) | 0.485 | 0.331 | 0.251 | 0.200 (z -5.8) | 0.165 | 0.077 (z -4.9) |
| fade, LONDON (7,369) | 0.484 | 0.329 | 0.247 | 0.197 | 0.162 | 0.077 |
| BREAK, all (54,156) | 0.495 | 0.328 | 0.241 | 0.186 | 0.147 | 0.053 |
| ... profile walk | 0.498 | 0.339 | 0.255 | 0.199 | 0.158 | 0.055 |
| BREAK, LATE (2,405) / EARLY (2,187) | 0.489 / 0.484 | 0.314 / 0.315 | 0.231 / 0.228 | 0.168 / 0.176 | 0.130 / 0.148 | 0.047 / 0.052 |

Every curve sits on or under the walk's own and at or under 1/(N+1); fading the first move is 1 point
under the walk at 4R and 10R (z -3 to -6 pooled; no market is above it at 10R by more than 0.5
points). Breaks at a rare hour for breaks (LATE, EARLY) are no better than breaks. **No time alphabet
here is a signal.** What the time core does show is how much of a "time-of-day effect" is volatility
on the clock: almost all of it, which is why the flat matched walk must not be the null for any
time-of-day claim.

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
- **Does a multi-timeframe ALIGN/CONFLICT relation work?** v2 defines it (item 10), causally; whether
  it carries anything is to be measured on markets, not assumed. The desk's 4h-bias filter, a special
  case, helped nothing in [`origin-zones.md`](origin-zones.md).
- **EPISODE as an entity** (RANGE became one in v2), and whether lifecycle events should exist for failed
  candidates too, so that V = 0 origins have sentences comparable with zones'.

## Decisions the brief left open

### Time core

- **Time is a field, not attributes.** `Entity.time` is a `core.Span`, stamped once at the end of the
  parse (`clocks.stamp`), so no v2 constructor changed and `parse(df, time=False)` is the v2 chart. It is
  part of the entity's equality, so the truncation tests cover it; the flip test carries it unchanged
  (`tests/test_symmetry.mirror` now copies it), which is the brief's "time is unchanged by the flip".
- **Bar 0's length** is a guess when nothing gives it (the coarsest standard bar its open is aligned
  to): too long for `known_at_ts`, counted as zero trading time and as unobserved for deciding that a
  period has ended. Every other bar's length is the running minimum of gaps, known at it. Bars that
  carry `close_ts` (volume and tick bars) are exact.
- **Intervals.** An event's interval is the tokens it consumed, a structure's its derivation; an
  EXTREME is its own bar. So a BREAK is its leg and `BREAK DURING killzone` would mean the whole leg
  ran inside it - which is why the killzone row of IN_WINDOW is a session extreme taken (an instant),
  not a break.
- **Windows are known when they open**, with a scheduled end (the calendar announces it), and have no
  last bar until their WINDOW_CLOSE. Allen relations to an open window are on the wall clock only. A
  bar belongs to a window when its open is inside it; IN_WINDOW asks the bar's whole interval to be.
- **Killzones and macros are in New York time** with daylight saving (pandas' zone data); v2's sessions
  stay in fixed UTC hours, as v2 defined them. The trading week starts Sunday 17:00 New York.
- **Holidays are configuration** (`calendars.Calendar`); only NYSE 2024-2026 and CRYPTO are built in.
  The study used NYSE for every market that closes and CRYPTO for the rest, including Germany 40 (no
  Xetra calendar was written).
- **TIMEOUT** needed two grammar options, `timed` (the event is the decide bar, emitted only once the
  series reaches it - an absence cannot be decided early) and `sym` (a range has no direction). A
  RANGE times out when it is not left within 48 bars; "no test" almost never happens.
- **LATE / EARLY** come from the same hour baseline as `hour_rate` (the last 400 events of the type
  known before); LATE and EARLY split the rare hours by which side of the type's usual hour they fall.
  Without a day of week in the baseline.
- **The multi-timeframe retrofit** changes no v2 number: `MTF.known` already completed periods the same
  way; it is now read off HTF_CLOSE events, and `mtf.groups` uses the same `anchors.periods`.
- **A v2 leak found on the way.** The calendar truncation test caught PULLBACK[phase=INSIDE] taking the
  last swing low before the break even when that swing was confirmed after it (up to three bars), so a
  prefix had been given a pullback the full parse later replaced. The INSIDE pullback is now the last
  swing confirmed by the break's known_at, known then (`retrace.py`); DAX50 follows. It reproduced with
  `time=False` and without timestamps; the v2 test series had not hit it. The v2 study's INSIDE-pullback
and DAX50 numbers (`out/v2.txt`) predate the fix and were not rerun.

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
- **Retracement (item 7).** On a REVISIT the leg's peak is the highest high from the origin to the bar
  before the revisit (the revisit bar's own high may come after its low). After a BREAK, the
  pullback measured is the first swing low after the break (AFTER), and, for the DAX rule, the last
  swing low inside the leg (INSIDE) measured against the leg to the break, exactly as `dax_smc.py`
  measures its structural liquidity. Bins: 0.382 and 0.618 belong to the bin above; 1.0 is DEEP.
  The DAX rule's 50% is the number 0.5 (`depth≥0.5`), not the HALF bin, which starts at 0.382.
- **Pools (item 6).** The tolerance is the swing labels' (0.1 ATR at the newer swing), measured
  between the newest member and each earlier one. "Not yet traded through" is checked between each
  member and the newest (no high strictly between them above the higher of the two); a pool grows
  by new POOL entities (count 2, 3, ...) rather than by changing one, so every entity stays immutable.
  POOL_TAKEN is the first high strictly above the level; "with a close back" is an attribute, and the
  link to BREACH_REVERT is the list of the members' BREACH_REVERT events on that bar.
- **SWEEP_PROTECTED's direction** is the direction of the move it protects (UP for a protected low),
  as ORIGIN↑ is a swing low; BREACH_REVERT keeps v0's convention (the breach's direction).
- **RANGE (item 5).** k = 10 bars within x = 2 ATR (at the detecting bar), one live range at a time,
  the box fixed at detection (a wick beyond it is a test or an excursion, not a wider box). "Holds m
  bars" is m consecutive closes beyond, the first included (m = 3), so an ESCAPE is known two bars
  after its first close beyond. A failed escape counts as a test of its edge. A RANGE has no
  direction (Dir.NONE).
- **Compression (item 2).** NR and WR are strict (a tie is neither) and count the bar itself in its
  4 or 7. OVERLAP is a BAR_RELATION attribute (it relates two bars); NR4 / NR7 / WR7 are CANDLE
  attributes. BALANCE / IMBALANCE use k = 3 and thresholds 0.75 / 0.25 (the walk's overlap quartiles
  are 0.25 and 0.79, so each bar of a run is in the top or bottom quarter); IMBALANCE's direction is
  that of the bars' higher highs (rel = HH), BALANCE has none.
- **Sessions (item 8)** use fixed UTC hours, no daylight saving, read from the bar's open. SESSION is a
  CANDLE attribute (a qualifier), not a separate token per bar: one token per bar is the CANDLE, and a
  second L1 token type would only repeat its bar. A session's extremes are known at the first bar of
  the next session (the bar that shows the clock passed), and are watched for a take until the same
  session comes round again. SESSION_HIGH_TAKEN and SESSION_LOW_TAKEN are one type with two directions,
  so the flip maps them onto each other.
- **Tempo** is measured between consecutive events of one structure (the first since the structure was
  known), and FAST / SLOW are quartiles of the same event type's last 50 tempos, known strictly before
  it. A tie with a quartile is FAST (SLOW).
- **Changepoints (item 9) are an option of the parse**, `changepoints=True`, not in every parse: they
  import production's package, and CUSUM (log returns) is undefined on the negated chart the flip
  test parses. FOCUS's `at` is the detector's change start, so it can be well before its `known_at`.
  CUSUM's flip symmetry is tested under the log-price flip, which is the one its definition has. The
  bar length for FOCuS's threshold comes from the first two timestamps (known at bar 1), else an hour.
- **Volume (item 3)** is graded like the size class (same period and edges), and EFFORT_RESULT reads
  the two classes only; "≥ LARGE" and "≤ SMALL" include the extreme classes (and NONE). The taker side
  needs no new direction: the flip swaps the buy and sell columns, so a taker skew is flip-symmetric
  exactly. Generated bars get a tick volume from `synth.ticks`, built from the bar's range, so on them
  volume carries nothing a walk's does not - the comparison calibrates the words, it cannot find an
  effect.
- **CRT (item 12).** PURGE reads the brief's "close ≤ prev high ∧ close ≥ prev low" as the negations
  of the v1 words CLOSE_ABOVE_PREV_HIGH and CLOSE_BELOW_PREV_LOW, so both inequalities hold within the
  point tolerance. CRT_N = 3 candles after the purge, the purge candle itself not counted (its own
  low below the range is a purge of the other side, not a distribution). DISTRIBUTION's direction is
  the move's (down after a purge of the high), and so is CRT3's.
- **Multiple timeframes (item 10).** The HTF chart is parsed on its own bars (so its words are HTF
  words) and read in LTF time through two maps, span and known; the two charts stay separate objects
  (`MTF`), with HTF ids prefixed by the timeframe, rather than one chart with mixed bar clocks.
  CONTAINS_TF is materialised only for candles (any other pair is on demand; all pairs would be
  quadratic). ALIGN/CONFLICT are materialised for LTF ZONEs and BREAKs. NESTED is causal by default:
  the HTF break must be known, in LTF time, by the LTF zone's known_at - the brief's rule. The
  research's flag is kept as a non-causal form (`nested_flags(mode="research")`), with the selection of
  HTF breaks zone_events made (only those later returned to), because reproducing it exactly needs it;
  it is a check, not a relation the language offers.
- **The multi-timeframe CRT** waits for the HTF range candle to be complete but not for the purge's HTF
  candle: the purge is an LTF event, found by the LTF bars' own periods.
- **The candlestick vocabulary (item 13)** is one event type, PATTERN, with the name as an attribute
  and the pair's key as the id suffix, rather than ~60 types: the flip maps a pattern to its twin by
  swapping the name, and one type keeps the layer and ordering tables small. Thresholds are the
  grammar's grades, not TA-Lib's averages: long body = force grade STRONG or more, short = MODERATE or
  less, small = WEAK, doji = OPEN_EQ_CLOSE. The trend is in the production only where the name depends
  on it (the hammer family) or the canon's definition is the trend plus a shape with another name
  (BELT_HOLD vs OPENING_MARUBOZU); otherwise it is an attribute. A pattern with only a bearish canonical
  name keeps that name on its UP mirror. THREE_LINE_STRIKE is TA-Lib's: three rising bulls and a bear
  that wipes them out is the bullish one. ISLAND_REVERSAL is four rows (islands of 1-4 bars) sharing one
  id, so one island is one event. KEY_REVERSAL needs a new 10-bar low and a close above the previous
  close; EXHAUSTION_BAR a very large bear bar after three bears; CLIMAX_BAR a very large bar on very
  large volume to a new low, closing in its upper half; SIGNAL_BAR Brooks' bull reversal bar with a
  `quality` grade; TREND_BAR and DOJI_BAR the fuzzy body class (LARGE or more, SMALL or less).
- **TA-Lib** is not installed and was not installed: no agreement report (see item 13).

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
