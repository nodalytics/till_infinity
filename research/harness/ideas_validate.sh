# Run on the lab: the one-shot validation of the frozen candidates (research/ideas/candidates.json).
cd $HOME/till_infinity
export MT5BT_DB=$HOME/till_infinity/data/mt5bt.db PYTHONPATH=$HOME/till_infinity/repo OMP_NUM_THREADS=1
PY="nice -n 10 .venv/bin/python -u -W ignore"
FRESH="AAVUSD,ADAUSD,ALGUSD,APEUSD,APTUSD,AVAUSD,BATUSD,BCHUSD,BNBUSD,COMUSD,DOGUSD,DOTUSD,DSHUSD,ETCUSD,FILUSD,IMXUSD,IOTUSD,LNKUSD,LTCUSD,MLNUSD,NEOUSD,NERUSD,SANUSD,SHBUSD,TRUUSD,TRXUSD,UNIUSD,XLMUSD,XMRUSD,XRPUSD,XTZUSD,ZECUSD"
# crypto: every candidate is daily, so it waits only for the daily bars
while ! grep -q " 4h " logs/ideas_fresh.log; do sleep 30; done
mkdir -p out/ideas_fresh_crypto
OUT=out/ideas_fresh_crypto SYMBOLS="$FRESH" INTERVALS=1d WALKS=0 WORKERS=16 EXITS=trail,t4,t10,focus \
  SETUPS=donchian_trend,box_breakout,cusum_follow,triangle_cook,focus_size,anomaly \
  $PY repo/research/ideas/run.py > logs/ideas_fresh_crypto.log 2>&1
OUT=out/ideas_fresh_crypto $PY repo/research/ideas/validate.py >> logs/ideas_fresh_crypto.log 2>&1
OUT=out/ideas_portfolio FRESH=1 $PY repo/research/ideas/portfolio.py > logs/ideas_fresh_books.log 2>&1
# metals and Deriv: wait for their fetch
while [ ! -f logs/ideas_fresh2.flag ]; do sleep 30; done
mkdir -p out/ideas_fresh_other
OUT=out/ideas_fresh_other SYMBOLS="XPTUSD,XPDUSD,XCUUSD,Volatility 10 Index,Volatility 50 Index,Volatility 100 Index,Step Index 200,Step Index 500,Drift Switch Index 20,Drift Switch Index 30" \
  INTERVALS=15m,4h WALKS=0 WORKERS=10 EXITS=t10,t4,focus SETUPS=tf_coherent_breakout,cusum_follow,asc_triangle \
  $PY repo/research/ideas/run.py > logs/ideas_fresh_other.log 2>&1
OUT=out/ideas_fresh_other $PY repo/research/ideas/validate.py >> logs/ideas_fresh_other.log 2>&1
echo done > logs/ideas_validate.flag
