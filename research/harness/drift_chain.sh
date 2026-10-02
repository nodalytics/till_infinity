# Run on the lab: fetch Drift Switch Index 20 and 30 ticks (and their specs), then drift_validate.py.
cd $HOME/till_infinity
set -a; . repo/.env; set +a
export TRADING_MT5_URL=http://127.0.0.1:8000 MT5BT_DB=$HOME/till_infinity/data/mt5bt.db GAP=1.0 PYTHONPATH=$HOME/till_infinity/repo
nice -n 10 .venv/bin/python -u repo/research/mt5bt/fetch.py specs --symbols "Drift Switch Index 20,Drift Switch Index 30" > logs/drift_chain.log 2>&1
nice -n 10 .venv/bin/python -u repo/research/mt5bt/fetch.py ticks --symbols "Drift Switch Index 20,Drift Switch Index 30" --start "2026-02-13 00:00" --end "$(date -u '+%Y-%m-%d %H:%M')" >> logs/drift_chain.log 2>&1
mkdir -p out/drift_validate
OUT=$HOME/till_infinity/out/drift_validate OMP_NUM_THREADS=1 nice -n 10 .venv/bin/python -u repo/research/harness/drift_validate.py > logs/drift_validate.log 2>&1
echo done > logs/drift_chain.flag
