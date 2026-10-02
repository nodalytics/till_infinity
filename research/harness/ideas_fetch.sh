# Run on the lab: specs and broker bars to today for the idea backtests (and the leads re-check).
cd $HOME/till_infinity
set -a; . repo/.env; set +a
export TRADING_MT5_URL=http://127.0.0.1:8000 MT5BT_DB=$HOME/till_infinity/data/mt5bt.db GAP=0.5 PYTHONPATH=$HOME/till_infinity/repo
F="nice -n 10 .venv/bin/python -u repo/research/mt5bt/fetch.py"
CORE="EURUSD,GBPUSD,USDJPY,AUDUSD,USDCAD,USDCHF,NZDUSD,EURJPY,GBPJPY,EURGBP,AUDJPY,USDCNH,XAUUSD,XAGUSD,BTCUSD,ETHUSD,SOLUSD,US SP 500,US Tech 100,Wall Street 30,Germany 40,UK 100,Japan 225,Australia 200,US Oil,UK Brent Oil"
DERIV="Volatility 75 Index,Volatility 25 Index,Jump 50 Index,Boom 1000 Index,Crash 1000 Index,Step Index,Range Break 100 Index,Drift Switch Index 10"
$F specs --symbols "$CORE,$DERIV" > logs/ideas_fetch.log 2>&1
$F bars --symbols "$CORE,$DERIV" --intervals 1d --days 9000 >> logs/ideas_fetch.log 2>&1
$F bars --symbols "$CORE,$DERIV" --intervals 4h --days 3000 >> logs/ideas_fetch.log 2>&1
$F bars --symbols "$CORE,$DERIV" --intervals 1h --days 2200 >> logs/ideas_fetch.log 2>&1
$F bars --symbols "$CORE,$DERIV" --intervals 15m --days 800 >> logs/ideas_fetch.log 2>&1
$F bars --symbols "$CORE" --intervals 5m --days 200 >> logs/ideas_fetch.log 2>&1
echo done > logs/ideas_fetch.flag
