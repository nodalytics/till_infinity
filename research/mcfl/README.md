# MCFL v2 + time core - Market Chart Formal Language

OHLC bars parsed into typed, causal events, structures and states, and written out as sentences
that can be counted and compared. The specification, the definitions and what the walk null shows
are in [`research/docs/mcfl.md`](../docs/mcfl.md). It is a research instrument, not a signal.

| file | what it does |
|---|---|
| `core.py` | the types: `Entity` (frozen; id, type, dir, at, **known_at**, attrs, force, parts), `Force`, `Relation`, `Failure`, `Transition`, `Chart`; the flip tables and the named point relations |
| `candles.py` | L1: the token table, CANDLE (fuzzy classes, strength, close quartile, lexeme) and BAR_RELATION (range relation, engulf, point matrices, named relations), the flipped frame, words as text |
| `parse.py` | the L2 level events (DISPLACE, BREAK with its age, BREACH_REVERT), ORIGIN and LEG over the tokens, then grammar, lifecycle, candle REJECT and relations: `parse(df) -> Chart` |
| `grammar.py` | productions as data: `WORDS` (fixed token windows: EXTREME, VOID, PIN, ENGULF, INSIDE_BREAK, STAR, DISPLACE_C), the qualifier syntax (`q`, `run`), the DELIVERY_SHIFT scan, `RULES` (ZONE) and `CANDLE_RULES` (REJECT) with the matcher |
| `lifecycle.py` | the zone state machine: REVISIT, REJECT_PATH, CONFIRMED, ACCEPT, FAIL, EXPIRE |
| `serialise.py` | the event sentence, the bar sentence, the interleaved view, derivation trees, episodes, exact JSON round trip |
| `ngrams.py` | n-gram and next-token statistics against matched iid walks, with a calibrated null |
| `candle_study.py` | candle words, point relations and candle productions against matched walks; REJECT vs REJECT_PATH; DISPLACE_C vs DISPLACE |
| `plot.py` | a chart with every token drawn on it and the L1 strip under it, to `out/` |
| `structure.py` | v2 items 1, 11: swing labels (SWING), STRUCTURE state and STRUCTURE_SHIFT, BREAK `vs_structure` (BOS), CHARACTER_SHIFT (CHoCH) |
| `voids.py` | v2 item 4: the VOID lifecycle (VOID_PARTIAL, VOID_FILLED, VOID_INVERTED) |
| `retrace.py` | v2 item 7: RETRACE, PULLBACK, depth bins, DAX50 |
| `pools.py` | v2 item 6: POOL, POOL_TAKEN, SWEEP_PROTECTED (= dax_smc step 1), DAX_SETUP |
| `ranges.py` | v2 item 5: RANGE, RANGE_TEST, ESCAPE, FAILED_ESCAPE |
| `timing.py` | v2 item 8: session / day qualifiers, SESSION_OPEN / _EXTREME / _EXTREME_TAKEN, tempo and pace |
| `changepoints.py` | v2 item 9: FOCUS, FOCUS6 (prims.focus_series), CUSUM_IGNITION (survivors.cusum), FOCUS_ZONE; `parse(df, changepoints=True)` |
| `volume.py` | v2 item 3: VOLUME class, EFFORT_RESULT, TAKER_SKEW |
| `crt.py` | v2 item 12: PURGE, DISTRIBUTION, CRT3 |
| `mtf.py` | v2 item 10: `parse_mtf`, aggregation, CONTAINS_TF, ALIGN / CONFLICT, NESTED (causal) and the research form of inside_4h, multi-timeframe CRT |
| `vocabulary.py` | v2 item 13: the candlestick vocabulary (PATTERN, 64 rows) |
| `v2_study.py` | every v2 alphabet against matched walks (iid, GARCH, AR(1), gapped), P(N R) of the patterns; writes `out/v2.txt` |
| `synth.py` | iid, GARCH and AR(1) momentum walks built from sub-steps; `matched_walk`; v2: `ticks` (tick and taker volume), `gapped` (overnight gaps); time core: `profiled` / `matched_profiled` (a walk on a market's own timestamps with its hour-of-day volatility and overnight jumps, optionally GARCH-clustered), `matched_on_calendar` |
| `clocks.py` | time core items 1, 5, 7: the `Clock` (bar lengths known at the bar), `stamp` (every entity's `core.Span`: interval in bars and UTC, `known_at_ts`, trading vs calendar time), EPISODE, `age`, the bar / time / trade / volume / event clocks and `reading`, `volume_bars`, `tick_bars`, `in_source` |
| `intervals.py` | item 2: Allen's 13 relations (+ WITHIN / HOLDS) as clause operators, `relate`, IN_WINDOW rows (`REVISIT DURING SESSION[LONDON]`) |
| `calendars.py` | item 3: minute, hour, week of month, month, quarter, month/quarter/year end, holidays and half-days from a `Calendar` (NYSE 2024-2026, CRYPTO) |
| `anchors.py` | items 4, 5: WINDOW (sessions, ICT killzones and macros, New York time with DST) and WINDOW_CLOSE, DAY_OPEN (UTC, NY), WEEK_OPEN, MONTH_OPEN, HTF_CLOSE[tf] (the shared multi-timeframe clock), remaining-time and HTF-progress qualifiers |
| `timed.py` | item 6: TIMEOUT (rule-table rows), STALL, SESSION_FIRST_MOVE, LATE / EARLY |
| `seasonal.py` | item 8: time-of-day volatility class (`tod_vol`), TEMPO_STATE, every event's `hour_rate`, the market's `profile` |
| `time_study.py` | every time alphabet on real markets (MT5 15m, on the lab) against walks on the same calendar: profile-matched, GARCH-clustered and flat; P(N R) of the time signals; writes `out/time.txt` |
| `tests/` | time core: `test_time_core`, `test_intervals`, `test_calendars`, `test_anchors`, `test_timed`, `test_seasonal`, `test_clocks`, `test_time_causality` (every prefix on a calendar with closures), `test_time_symmetry`, `test_time_mtf` (no HTF fact read before its HTF_CLOSE); causality (every prefix), flip symmetry, grammar fixtures, lifecycle, JSON, n-grams, reproduction of `zone_events.py`'s V = 1; v1: class and grade boundaries, point relations, every production, BREAK age, and DELIVERY_SHIFT against `zones._cisd` |

```python
import sys; sys.path.insert(0, "research")
from mcfl import synth
from mcfl.parse import parse
from mcfl.serialise import to_text, dumps, episode

chart = parse(synth.garch(2000, seed=1))   # any frame with open, high, low, close
print(to_text(chart, bins=True))            # EXTREME↑ VOID↓[size:m] ... BREAK↑[force:strong] ZONE↑ ...
z = chart.of("ZONE")[0]
print(episode(chart, z.id))                 # ['ORIGIN↑', 'DISPLACE↑', 'VOID↑', 'BREAK↑', 'REVISIT↑', ...]

from mcfl.serialise import bar_words, interleaved_text, derivation
print(bar_words(chart)[100])                # BULL(L,T,N,S){b:S,u:W,l:N,q4}/HH|c=h,c>ph
print(interleaved_text(chart, lo=z.at, hi=z.known_at + 1))
print(derivation(chart, z.id))              # the zone down to its candle words

# the time core: give the bars a `ts` (bar open, UTC seconds)
from mcfl.intervals import relate
print(z.time)                               # Span(start=.., end=.., start_ts=.., end_ts=.., known_at_ts=.., trade_sec=.., hour_rate=..)
print([e for e in chart.of("IN_WINDOW") if e.get("name") == "LONDON"][:1])   # REVISIT DURING SESSION[LONDON]
```

Run (the venv is the main checkout's; it has no matplotlib, so the plot runs on the system python):

```
.venv/bin/python -m pytest -q research/mcfl/tests        # 508 tests, 25-45 minutes
.venv/bin/python research/mcfl/v2_study.py                 # writes out/v2.txt
MT5BT_DB=... .venv/bin/python research/mcfl/time_study.py  # on the lab; writes out/time.txt (--demo without data)
.venv/bin/python research/mcfl/ngrams.py [--bins]          # writes out/ngrams[_bins].txt
.venv/bin/python research/mcfl/candle_study.py             # writes out/candles.txt (about 30 minutes)
python3 research/mcfl/plot.py --source garch --seed 3      # writes out/chart_garch_3.png
```

`out/` keeps the n-gram reports; PNGs there are not committed.
