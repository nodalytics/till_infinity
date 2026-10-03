# MCFL v0 - Market Chart Formal Language

OHLC bars parsed into typed, causal events, structures and states, and written out as sentences
that can be counted and compared. The specification, the definitions and what the walk null shows
are in [`research/docs/mcfl.md`](../docs/mcfl.md). It is a research instrument, not a signal.

| file | what it does |
|---|---|
| `core.py` | the types: `Entity` (frozen; id, type, dir, at, **known_at**, attrs, force, parts), `Force`, `Relation`, `Failure`, `Transition`, `Chart` |
| `parse.py` | L1 facts, the L2 events (EXTREME, VOID, DISPLACE, BREAK, BREACH_REVERT), ORIGIN and LEG, then grammar, lifecycle and relations: `parse(df) -> Chart` |
| `grammar.py` | production rules as data (`RULES`) and the matcher; ZONE := ORIGIN DISPLACE VOID+ BREAK, failures reported with slot and clause |
| `lifecycle.py` | the zone state machine: REVISIT, REJECT, ACCEPT, FAIL, EXPIRE |
| `serialise.py` | the chart sentence, episodes, readable text, exact JSON round trip |
| `ngrams.py` | n-gram and next-token statistics against matched iid walks, with a calibrated null |
| `plot.py` | a chart with every token drawn on it, to `out/` |
| `synth.py` | iid, GARCH and AR(1) momentum walks built from sub-steps; `matched_walk` |
| `tests/` | causality (every prefix), flip symmetry, grammar fixtures, lifecycle, JSON, n-grams, and reproduction of `zone_events.py`'s V = 1 |

```python
import sys; sys.path.insert(0, "research")
from mcfl import synth
from mcfl.parse import parse
from mcfl.serialise import to_text, dumps, episode

chart = parse(synth.garch(2000, seed=1))   # any frame with open, high, low, close
print(to_text(chart, bins=True))            # EXTREME↑ VOID↓[size:m] ... BREAK↑[force:strong] ZONE↑ ...
z = chart.of("ZONE")[0]
print(episode(chart, z.id))                 # ['ORIGIN↑', 'DISPLACE↑', 'VOID↑', 'BREAK↑', 'REVISIT↑', ...]
```

Run (the venv is the main checkout's; it has no matplotlib, so the plot runs on the system python):

```
.venv/bin/python -m pytest -q research/mcfl/tests        # 25 tests, about 45 s
.venv/bin/python research/mcfl/ngrams.py [--bins]          # writes out/ngrams[_bins].txt
python3 research/mcfl/plot.py --source garch --seed 3      # writes out/chart_garch_3.png
```

`out/` keeps the n-gram reports; PNGs there are not committed.
