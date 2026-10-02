# The imported ideas: catalogues and a harness that trades every one on the broker's bars

Results: [`../docs/imported-ideas.md`](../docs/imported-ideas.md).

| File | What it is |
|---|---|
| `catalogue-*.md` | Every trading idea from the desk's earlier projects (sage docs and code, its api, the research lab's docs, code and scripts), copied here with its exact rule, parameters, claimed results and the flaws found in how it was tested |
| `prims.py` | Causal primitives: ATR, pivots known only once confirmed, candles as sage defines them, ADX, the higher-timeframe index, New York hours, the production FOCuS detector |
| `setups.py` | 56 rule families as signal frames: entry, structural stop, resting limit or stop entries; mirrored so every rule is symmetric |
| `run.py` | Trades every setup x exit on every symbol and timeframe with mt5bt, plus a coin twin and GARCH walks |
| `score.py` | Cells, coin and walk comparisons, Benjamini-Hochberg, the jump-instrument flag |
| `candidates.json` | The passing cells, frozen before the validation data was scored |
| `validate.py` | The one-shot validation on fresh instruments |
| `portfolio.py` | The books: cross-sectional and time-series momentum, currency strength, acceleration, gold's real-rate switch |

On the lab (data from `../harness/ideas_fetch.sh`, `ideas_fresh.sh`, `ideas_fresh2.sh`):

    OUT=out/ideas1 MT5BT_DB=data/mt5bt.db WALKS=6 python research/ideas/run.py
    OUT=out/ideas1 python research/ideas/score.py
    SETUPS=cusum_follow,anomaly SYMBOLS=... INTERVALS=1d EXITS=t10,focus python research/ideas/run.py
    OUT=... python research/ideas/validate.py
    MT5BT_DB=... python research/ideas/portfolio.py          # FRESH=1 for the fresh-universe check
