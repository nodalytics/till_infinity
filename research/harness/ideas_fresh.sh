# Run on the lab: specs and bars for the broker's other crypto CFDs, the fresh-coin validation set.
cd $HOME/till_infinity
set -a; . repo/.env; set +a
export TRADING_MT5_URL=http://127.0.0.1:8000 MT5BT_DB=$HOME/till_infinity/data/mt5bt.db GAP=0.5 PYTHONPATH=$HOME/till_infinity/repo
F="nice -n 10 .venv/bin/python -u repo/research/mt5bt/fetch.py"
FRESH="AAVUSD,ADAUSD,ALGUSD,APEUSD,APTUSD,AVAUSD,BATUSD,BCHUSD,BNBUSD,COMUSD,DOGUSD,DOTUSD,DSHUSD,ETCUSD,FILUSD,IMXUSD,IOTUSD,LNKUSD,LTCUSD,MLNUSD,NEOUSD,NERUSD,SANUSD,SHBUSD,TRUUSD,TRXUSD,UNIUSD,XLMUSD,XMRUSD,XRPUSD,XTZUSD,ZECUSD"
$F specs --symbols "$FRESH" > logs/ideas_fresh.log 2>&1
$F bars --symbols "$FRESH" --intervals 1d --days 4000 >> logs/ideas_fresh.log 2>&1
$F bars --symbols "$FRESH" --intervals 4h --days 2000 >> logs/ideas_fresh.log 2>&1
$F bars --symbols "$FRESH" --intervals 1h --days 1000 >> logs/ideas_fresh.log 2>&1
$F bars --symbols "$FRESH" --intervals 15m --days 400 >> logs/ideas_fresh.log 2>&1
echo done > logs/ideas_fresh.flag
