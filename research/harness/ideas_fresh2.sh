# Run on the lab: the fresh metals and smooth Deriv indices for the validation set.
cd $HOME/till_infinity
set -a; . repo/.env; set +a
export TRADING_MT5_URL=http://127.0.0.1:8000 MT5BT_DB=$HOME/till_infinity/data/mt5bt.db GAP=0.5 PYTHONPATH=$HOME/till_infinity/repo
F="nice -n 10 .venv/bin/python -u repo/research/mt5bt/fetch.py"
NEW="XPTUSD,XPDUSD,XCUUSD,Volatility 10 Index,Volatility 50 Index,Volatility 100 Index,Step Index 200,Step Index 500,Drift Switch Index 20,Drift Switch Index 30"
$F specs --symbols "$NEW" > logs/ideas_fresh2.log 2>&1
$F bars --symbols "$NEW" --intervals 1d --days 4000 >> logs/ideas_fresh2.log 2>&1
$F bars --symbols "$NEW" --intervals 4h --days 2000 >> logs/ideas_fresh2.log 2>&1
$F bars --symbols "$NEW" --intervals 1h --days 1000 >> logs/ideas_fresh2.log 2>&1
$F bars --symbols "$NEW" --intervals 15m --days 600 >> logs/ideas_fresh2.log 2>&1
echo done > logs/ideas_fresh2.flag
