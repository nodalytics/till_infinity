# Run on the lab: waits for the Deriv tick fetch, fetches 30 days of real-market ticks, then runs
# deriv_ticks.py and ta_ticks.py. One bridge fetch at a time, everything niced.
cd $HOME/till_infinity
while [ ! -f logs/deriv_ticks.flag ]; do sleep 60; done
set -a; . repo/.env; set +a
export TRADING_MT5_URL=http://127.0.0.1:8000 MT5BT_DB=$HOME/till_infinity/data/mt5bt.db GAP=1.0 PYTHONPATH=$HOME/till_infinity/repo SEQLAB=$HOME/till_infinity/data/seqlab
nice -n 10 .venv/bin/python -u repo/research/mt5bt/fetch.py specs --symbols "EURUSD,XAUUSD,BTCUSD,US 500" > logs/real_ticks.log 2>&1
nice -n 10 .venv/bin/python -u repo/research/mt5bt/fetch.py ticks --symbols "EURUSD,XAUUSD,BTCUSD,US 500" --start "$(date -u -d '30 days ago' '+%Y-%m-%d %H:%M')" --end "$(date -u '+%Y-%m-%d %H:%M')" >> logs/real_ticks.log 2>&1
mkdir -p out/deriv_ticks out/ta_ticks
OUT=$HOME/till_infinity/out/deriv_ticks PRED=$HOME/till_infinity/out/expansion_all nice -n 10 .venv/bin/python -u repo/research/harness/deriv_ticks.py > logs/deriv_ticks_run.log 2>&1
OUT=$HOME/till_infinity/out/ta_ticks OMP_NUM_THREADS=1 nice -n 10 .venv/bin/python -u repo/research/harness/ta_ticks.py > logs/ta_ticks.log 2>&1
echo done > logs/chain.flag
