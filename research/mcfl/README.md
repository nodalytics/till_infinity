# MCFL v1 - Market Chart Formal Language

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
| `synth.py` | iid, GARCH and AR(1) momentum walks built from sub-steps; `matched_walk` |
| `tests/` | causality (every prefix), flip symmetry, grammar fixtures, lifecycle, JSON, n-grams, reproduction of `zone_events.py`'s V = 1; v1: class and grade boundaries, point relations, every production, BREAK age, and DELIVERY_SHIFT against `zones._cisd` |

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
```

Run (the venv is the main checkout's; it has no matplotlib, so the plot runs on the system python):

```
.venv/bin/python -m pytest -q research/mcfl/tests        # 132 tests, about 2 minutes
.venv/bin/python research/mcfl/ngrams.py [--bins]          # writes out/ngrams[_bins].txt
.venv/bin/python research/mcfl/candle_study.py             # writes out/candles.txt (about 30 minutes)
python3 research/mcfl/plot.py --source garch --seed 3      # writes out/chart_garch_3.png
```

`out/` keeps the n-gram reports; PNGs there are not committed.
