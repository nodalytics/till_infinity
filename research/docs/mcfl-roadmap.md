# MCFL roadmap: v2, v3, v4

The desk's requests for the chart language after v1 (2026-10-03), recorded as the briefs each version will be built from. Each version builds on the previous one once it is merged and keeps its rules: every entity carries `known_at`, truncation-invariance and flip-symmetry tests cover everything, productions live in the declarative rule table, and every new alphabet is compared against random walks. v1 (in progress) adds the candle layer: fuzzy candle words as L1, bar relations, OHLC point relations, body and wick strength, break age and DELIVERY_SHIFT (CISD). The specification is [`mcfl.md`](mcfl.md).

## v2

MCFL v2. The desk asked for all ten of these (2026-10-03). Build on merged v1, keeping its rules:
- known_at on everything;
- the truncation-invariance causality test covering every new entity;
- flip symmetry;
- the declarative rule table;
- content ids;
- `parts` derivations down to L1 candle tokens;
- v0/v1 tests green;
- exact zone_events reproduction.

1. **Swing-structure labels.** Each confirmed EXTREME is labelled against the previous EXTREME of its kind: HH / LH for highs, HL / LL for lows, with an EQ tolerance. Add:
   - a STRUCTURE state, built from the sequence of labels: UP (HH+HL), DOWN (LH+LL), MIXED;
   - a STRUCTURE_SHIFT event when the state changes, with `known_at` = the label's `known_at`.
2. **Compression and expansion words.**
   - NR4 / NR7: the narrowest range of the last 4 or 7 bars.
   - WR7: the widest of 7.
   - An OVERLAP attribute: the share of the bar inside the previous bar's range.
   - BALANCE / IMBALANCE runs: k bars with overlap ≥ / ≤ a threshold.
   - These are L1 qualifiers plus L2 run events.
3. **Volume, effort against result.**
   - A fuzzy VOLUME class per bar (rolling mean and sd, like the candle classes).
   - EFFORT_RESULT = volume class against size class: ABSORPTION (volume ≥ LARGE, size ≤ SMALL), EASE (volume ≤ SMALL, size ≥ LARGE), AGREE, NEUTRAL.
   - Works with any volume column: tick volume on CFDs, real or taker volume on exchanges. An optional `taker_buy_volume` column adds TAKER_SKEW.
4. **The VOID lifecycle.** Each VOID transitions UNTOUCHED → PARTIAL (price entered it) → FILLED (fully traded through) → INVERTED (a close beyond its far side, the IFVG). Each transition is an event with `known_at`, and a VOID's current state is queryable at any bar.
5. **RANGE as a structure.**
   - A box detected causally: k+ bars confined within a band of ≤ x ATR, with its top and bottom and the count of tests per edge.
   - Events: ESCAPE_UP / ESCAPE_DOWN (a close beyond the edge that holds m bars) and FAILED_ESCAPE (a close beyond, then back inside within m bars).
   - This replaces the reserved RANGE.
6. **Liquidity pools.**
   - EQUAL_HIGHS / EQUAL_LOWS: 2+ EXTREMEs of a kind at the same level within tolerance (EQ_ATR), not yet traded through, as a POOL entity with its count.
   - Events: POOL_TAKEN (traded through), with or without a close back (links to BREACH_REVERT).
   - SWEEP_PROTECTED: the DAX course's rule, where a swept low becomes "protected", expressed exactly.
7. **Retracement depth.**
   - On every REVISIT, and on every pullback after a BREAK: depth = retracement ÷ leg, binned SHALLOW (<0.382) / HALF (0.382–0.618) / DEEP (0.618–1) / BEYOND (>1, past the origin).
   - As an attribute and a qualifier, so the DAX 50% rule can be written as a production.
8. **Time and tempo.**
   - SESSION token per bar (ASIA / LONDON / NY / OVERLAP, in UTC with documented hours), DAY_OF_WEEK, and session-open and session-extreme anchors (SESSION_HIGH_TAKEN etc.).
   - A `tempo` attribute (bars between consecutive events of a structure), plus FAST / SLOW qualifiers by rolling quantile, so "fast return" is grammatical.
9. **Changepoints as events.**
   - FOCUS_UP / FOCUS_DOWN from the production FOCuS detector (`research/ideas/prims.focus_series`, threshold 12 + 3 ln(3600/sec), and 6 as a sensitive variant), carrying `at` (the change start) and `known_at` (the fire).
   - CUSUM_IGNITION_UP / DOWN from `research/ideas/survivors.cusum` (k 0.5, h 5).
   - Usable in productions.
10. **Multiple timeframes.**
    - An aggregator builds a higher-timeframe bar and its CANDLE word from the lower-timeframe tokens (e.g. 16 × 15m → 4h), and also parses the HTF chart itself.
    - Relations:
      - CONTAINS_TF (an HTF entity contains LTF entities by time);
      - ALIGN / CONFLICT (an LTF event's direction against the active HTF structure state or the leg of an HTF BREAK).
    - The desk's strongest finding must be writable as one production: "an LTF ZONE whose ORIGIN lies inside the leg of an HTF BREAK of the same direction" (`research/ideas/zone_nested.py` "inside_4h"). Test that it reproduces that flag exactly on walks.

**Each needs:**
- spec sections and tables;
- fixtures;
- flip tests;
- causality coverage;
- token text forms;
- an n-gram report against walks (iid, GARCH, AR(1)) for the new alphabets.

Report which of the new tokens differ from the walk null.

11. **CHARACTER_SHIFT (trader alias CHoCH).**
    - Every BREAK gets `vs_structure` ∈ {WITH, AGAINST, NONE}, read from the STRUCTURE state (item 1) known at the break.
    - CHARACTER_SHIFT = the first AGAINST BREAK after an established UP or DOWN state, i.e. ≥ 2 consecutive same-state labels.
    - BOS = a WITH break: document that BREAK with WITH is the trader's BOS.
    - Tests: fixtures for a trend, then a CHoCH, then a BOS in the new direction; flip symmetry.
12. **Candle range theory (CRT).**
    - RANGE_CANDLE: any L1 CANDLE token treated as a box (high, low, 50% mid), usually on a higher timeframe via item 10's aggregation.
    - PURGE_UP / PURGE_DOWN:
      - built from the v1 relation words, not raw prices;
      - the next candle trades beyond the range's high (low) and closes back inside the range: `HIGH_ABOVE_PREV_HIGH` ∧ close ≤ prev high ∧ close ≥ prev low;
      - attributes: purge depth (ATR) and close location in the range.
    - DISTRIBUTION: within N candles (documented constant), price reaches the opposite side of the range. This is CRT's outcome event; record whether, and when, the mid is reached first.
    - CRT3: the three-candle production RANGE_CANDLE → PURGE → DISTRIBUTION.
    - Multi-timeframe CRT: an HTF RANGE_CANDLE with the PURGE seen on LTF candles, using CONTAINS_TF.
    - Report CRT's base rate against the walk null. Earlier desk research recorded intraday CRT as negative, so this is a re-check, not a hope.


## v3

MCFL v3. The desk asked for all of these (2026-10-03). Build on merged v2, with the same rules:
- known_at on everything;
- causality and truncation coverage;
- flip symmetry;
- the declarative rule table;
- content ids;
- `parts` down to L1 candles;
- all earlier tests green;
- a walk-null n-gram report for each new alphabet.

Build in this order (cheapest and most used first): E, F, A, B, C, G, H, D, I, J.

**E. Reference levels as entities and events.**
- Levels:
  - the previous day's, week's and month's high, low, open and close;
  - daily floor pivots (P, R1–R3, S1–S3);
  - session and daily VWAP, plus anchored VWAP (anchored at a chosen event, e.g. a BREAK or a FOCuS change);
  - the opening range (the first N minutes of a session) and its ORB_UP/ORB_DOWN events;
  - round numbers, with a documented grid;
  - new-week and new-day opening gaps (ICT NWOG/NDOG: Friday close → Sunday open, previous close → open).
- Each is a LEVEL entity, known when its inputs are complete, with TOUCH, CROSS, BREACH_REVERT and BREAK relations to price.

**F. Zone types.**
- Classify every ORIGIN by its base: rally-base-rally, drop-base-rally, rally-base-drop, drop-base-drop. The leg into the base, the base (1–k bars of small bodies and overlap), and the leg out.
- ICT block types as productions:
  - BREAKER (a zone that failed and is retested from the other side);
  - MITIGATION (the failed origin of a move that did not sweep);
  - REJECTION (a wick-defined zone);
  - BALANCED_PRICE_RANGE (overlapping opposite VOIDs).

**A. Diagonal geometry.**
- LINE: a line through two or more EXTREMEs, its slope in ATR per bar, its touches and a tolerance. Relations TOUCH, BREAK and BREACH_REVERT, all against the line's value at that bar. CHANNEL: a parallel line through the opposite swings.
- Classical patterns as productions over EXTREMEs, LINEs and LEGs, with documented tolerances:
  - ascending, descending and symmetric TRIANGLE;
  - rising and falling WEDGE;
  - FLAG and PENNANT, which follow a DISPLACE;
  - HEAD_AND_SHOULDERS and its inverse, with a neckline LINE;
  - DOUBLE_TOP / DOUBLE_BOTTOM, TRIPLE variants, CUP_AND_HANDLE, RECTANGLE (= v2 RANGE).
- Each has a completion event (the breakout) and a FAILED variant.

**B. Legs, counts and ratios.**
- LEG as a first-class entity between consecutive EXTREMEs, with size, duration and ratios to the previous legs.
- Al Brooks counts: H1/H2/L1/L2 pullback counts in a trend, THREE_PUSH (wedge), MICRO_CHANNEL (k bars without a pullback beyond the prior bar).
- MEASURED_MOVE (AB=CD: leg CD ≈ leg AB within tolerance).
- Fibonacci extensions (1.272, 1.618, 2.0 of a leg) as projected LEVELs, with reached / not-reached events.
- Elliott-style 5-3 sequences (motive and corrective leg counts) and harmonic XABCD patterns (Gartley, Bat, Butterfly, Crab), with documented ratio bands.
- These are descriptive productions. They must say nothing about outcomes.

**C. Phases (L4 state machines over existing events).**
- Wyckoff accumulation and distribution:
  - events PS, SC, AR, ST, SPRING, TEST, SOS, LPS (and UTAD/UT/SOW for distribution);
  - phases A–E, with transition rules documented in a table.
- ICT Power of 3 (AMD) per day: ACCUMULATION (Asia range) → MANIPULATION (a sweep of one side) → DISTRIBUTION (expansion the other way).
- Brooks ALWAYS_IN (long/short/none) and TREND vs TRADING_RANGE states.

**G. Cross-market relations.**
- Parse two or more charts and relate them by time. SMT_DIVERGENCE: one chart makes a new EXTREME beyond its previous one while its correlated twin does not, within a time tolerance.
- RELATIVE_STRENGTH between charts over a window. CORRELATED_CONFIRMATION when both make the same event.
- The twins are configurable; use the desk's pairs (`research/ideas/zone_context.py` TWINS).

**H. Indicator-derived events.**
- A small plugin interface: a derived series (RSI 14, MACD, an EMA, Bollinger bands) emits events.
- Events:
  - DIVERGENCE_BULL/BEAR (price makes a lower EXTREME while the indicator makes a higher one at the matched swings);
  - CROSS_ABOVE/BELOW of price and an MA;
  - BAND_TOUCH.
- Each has `known_at` at the confirming swing or bar.

**D. Volume at price.**
- Per session or per range: a volume profile from bars (each bar's volume spread over its range; documented) and, when trades are available, from trades.
- POC, VALUE_AREA (70%), HVN/LVN levels, SINGLE_PRINTS, INITIAL_BALANCE (the first hour), POOR_HIGH / POOR_LOW, EXCESS.
- All as LEVEL entities with the same relations as in E.

**I. Alternative lexers.**
- Heikin-Ashi, Renko (box in ATR), range bars and volume bars as alternative bar builders in front of the same grammar, with `known_at` on the source bars.
- Test that the grammar runs unchanged on each.

**J. True order flow (trade data).**
- An optional lexer from trade prints (Binance aggTrades: price, qty, side) to footprint bars: delta per price, STACKED_IMBALANCE (k consecutive price levels with buy/sell ratio ≥ x), ABSORPTION at a price, delta divergence.
- Only where trade data exists. Document how to fetch it from data.binance.vision.

**Each needs:**
- spec sections and tables;
- fixtures;
- flip tests;
- causality coverage;
- token text forms;
- n-gram comparison against walks.

Report, for each family, whether its tokens differ from the walk null.


## v4

MCFL v4. The desk asked for all six (2026-10-03). Build on merged v3, with the same rules:
- known_at on everything;
- causality and truncation coverage;
- flip symmetry where it applies;
- the declarative rule table;
- content ids;
- `parts` derivations;
- all earlier tests green;
- a walk-null comparison for each new alphabet.

**Build order: 1, 2, 3, 5, 4, 6.**

A rule learned twice on 2026-10-03 (see memory `lookahead-in-conditioning-flags`): every condition a strategy reads must be known before its entry. The strategy layer must ENFORCE this. A rule that reads an entity whose known_at > the entry bar is a compile error, not a runtime surprise.

**1. Strategy and execution language.** A small declarative DSL over MCFL sentences that compiles to the desk's backtester (`research/mt5bt`) signals:
- **Setup:** an MCFL pattern or production with qualifiers (e.g. `ZONE↑ [first revisit] & DELIVERY_SHIFT↑ within 12`).
- **Side.**
- **Entry:** MARKET next open, LIMIT at a named price (zone edge, mid, level), STOP order beyond a level, or a confirmation event.
- **Stop:** past a named price + k ATR, at a swing, or ATR-based, with a minimum distance in spreads.
- **Targets:** k R, a named level (the opposite zone, liquidity pool, measured move, Fib extension), or none.
- **Management:** move to break-even at x R, partials, trailing (ATR or swing), time exit, exit on an event (e.g. CHARACTER_SHIFT against).
- **Sizing:** fixed risk %, volatility-scaled; max concurrent.
- **Validation:** a static known_at check (above). A compiled strategy prints its rules in plain words.
- **Proof:** the desk's past setups must be expressible and must reproduce their earlier results through mt5bt within tolerance:
  - the origin-zone touch (`research/ideas/zones.py`);
  - the DAX checklist (`dax_smc.py`);
  - APA (`apa.py`);
  - the rejection trade.

**2. Outcomes and learning.**
- Attach outcome labels to any entity or sentence: P(+1R before −1R), MFE / MAE in ATR, whipsaw, time to resolution. Use the production Episode definitions (`till_infinity/structures/reactions.py`, Episode) so research and the journal speak the same language.
- Grammar induction: learn frequent productions from token streams (e.g. Sequitur, or MDL-guided pair merging), with a report of the learned rules and their description-length gain against walks.
- A next-token model over sentences (n-gram with smoothing as the baseline; optionally a small sequence model) that predicts the next L2/L4 event, judged on held-out time and against walks.
- Always report whether the learned structure or prediction beats the walk null.

**3. Non-price information as events.**
- **Positioning:** FUNDING_EXTREME (rolling percentile), OI_SURGE / OI_FLUSH, LONG_SHORT_FLIP, from the Binance metrics and funding already on the lab (`~/till_infinity/data/binance/*metrics.npz`, `*funding.csv`). COT weekly for futures, if a source is configured.
- **Options levels (BTC/ETH, Deribit):** OI_STRIKE levels (large open interest), GAMMA_FLIP, MAX_PAIN, as LEVEL entities, known at their snapshot time.
- **Scheduled releases:** a calendar source (configurable file) giving NEWS_EVENT anchors (CPI, NFP, FOMC, central banks), with PRE_EVENT / EVENT_WINDOW / POST_EVENT states and their relations to other events.
- **Macro and intermarket regime:**
  - DXY, US yields and risk proxies as companion charts;
  - REGIME states (risk-on/off, USD up/down) from their structure;
  - relations ALIGN / CONFLICT to a traded chart.

**5. Cross-sectional and portfolio concepts.**
- A UNIVERSE of parsed charts. Then:
  - RANK (an instrument's rank on a measure among peers);
  - BASKET (an equal-weight or defined basket chart);
  - RELATIVE_MOMENTUM, DISPERSION;
  - TOP_K / BOTTOM_K membership events.
- Portfolio-level strategies in the DSL (rebalance cadence, weights, vol-targeting).
- Proof: express the desk's time-series momentum book (`research/ideas/portfolio.py` tsmom: a 7/14/30/60-day sign ensemble, 10% vol target per instrument, cap 3) and reproduce its Sharpe on the same data within tolerance. It is the one strategy that has replicated on every venue, so the language must be able to state it.

**4. Statistical states.**
- VOL_REGIME (compressed / normal / expanding), from the production expansion model or a documented rolling percentile.
- MEAN_REVERSION_STATE (z-score from a rolling mean, estimated half-life).
- TREND_STRENGTH (ADX, efficiency ratio).
- CYCLE phase (the production `structures/cycles.py`).
- SEASON tokens: hour of day, day of week, day of month, turn of month, holidays.
- All as L4 states with transitions.

**6. Order-book microstructure** (where depth data exists; Binance `book15m` on the lab, finer if fetched):
- SPREAD_WIDEN;
- BOOK_IMBALANCE_FLIP;
- LIQUIDITY_VACUUM (depth within x% below a rolling percentile);
- WALL_APPEAR / WALL_VANISH (a large resting size at a price);
- each with known_at at the snapshot.

**Each needs:**
- spec sections and tables;
- fixtures;
- causality tests;
- token text forms;
- reproduction proofs where noted;
- a walk or shuffle null for anything claiming information.
