"""Run a strategy over MT5 CFD history.

    python research/mt5bt/bt.py --strategy research/mt5bt/strategies/donchian.py:strategy \
        --symbols EURUSD,XAUUSD --interval 15m --source sqlite --start 2025-01-01 --null 200 --audit

    # on walks we generate, with the real contract and spread
    python research/mt5bt/bt.py --strategy ...:strategy --walk garch --symbols EURUSD --bars 50000

Specs come from the mt5bt store (`fetch.py specs`), or `--specs file.json`, or the built-in
examples for walks. Results print in R (net of spread, commission and swap) and in money.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # research/, so `mt5bt` imports

import pandas as pd  # noqa: E402

from mt5bt import (  # noqa: E402
    Book, Costs, bars_from_ticks, garch_walk, load_bars, load_specs, load_ticks, lookahead,
    random_null, run, summary, t_walk)
from mt5bt.data import EXAMPLE_SPECS  # noqa: E402
from mt5bt.report import show  # noqa: E402


def load_strategy(ref: str):
    path, _, name = ref.partition(":")
    spec = importlib.util.spec_from_file_location(Path(path).stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, name or "strategy")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", required=True, help="file.py:function")
    ap.add_argument("--symbols", required=True)
    ap.add_argument("--interval", default="15m")
    ap.add_argument("--source", default="sqlite", choices=("sqlite", "seqlab", "csv"))
    ap.add_argument("--path")
    ap.add_argument("--specs")
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--walk", choices=("garch", "t"))
    ap.add_argument("--bars", type=int, default=50_000)
    ap.add_argument("--walks", type=int, default=1,
                    help="independent walks to average over: one walk's mean R swings about "
                         "+-0.07 at 20k bars, so a walk control needs many")
    ap.add_argument("--spread-points", type=float, default=0.0, help="where bars carry none")
    ap.add_argument("--spread-mult", type=float, default=1.0)
    ap.add_argument("--commission", type=float, default=0.0, help="money per lot per side")
    ap.add_argument("--slippage-points", type=float, default=0.0)
    ap.add_argument("--stop-slip-frac", type=float, default=0.0)
    ap.add_argument("--risk", type=float, default=0.005)
    ap.add_argument("--equity", type=float, default=10_000.0)
    ap.add_argument("--max-open", type=int, default=0)
    ap.add_argument("--null", type=int, default=0, help="random-entry replays")
    ap.add_argument("--audit", action="store_true")
    ap.add_argument("--ticks", action="store_true",
                    help="load the store's ticks for the span: fills from ticks where they cover")
    ap.add_argument("--from-ticks", action="store_true",
                    help="build the bars themselves from ticks (true bid/ask OHLC, tick counts)")
    ap.add_argument("--fill", default="auto", choices=("auto", "ticks", "bars"))
    ap.add_argument("--out", help="write trades to this CSV")
    a = ap.parse_args()

    strat = load_strategy(a.strategy)
    if a.walk and a.walks > 1:
        import numpy as np

        means = []
        for w in range(a.walks):
            specs = load_specs(a.specs) if a.specs else EXAMPLE_SPECS
            make = garch_walk if a.walk == "garch" else t_walk
            books = [Book(sym, make(a.bars, interval=a.interval,
                                    price={"XAUUSD": 2400.0, "US 500": 5500.0}.get(sym, 1.10),
                                    spread_points=a.spread_points or 8.0, seed=1000 * w + k),
                          specs[sym], a.interval)
                     for k, sym in enumerate(s.strip() for s in a.symbols.split(","))]
            t, _ = run(books, strat, Costs(spread_points=a.spread_points, spread_mult=a.spread_mult,
                                           commission_per_lot=a.commission,
                                           slippage_points=a.slippage_points,
                                           stop_slip_frac=a.stop_slip_frac),
                       equity=a.equity, risk=a.risk, max_open=a.max_open)
            g = (t["gross"] / t["risk_money"]).mean() if len(t) else np.nan
            means.append((t["R"].mean() if len(t) else np.nan, g, len(t)))
            print(f"  walk {w:3d}: {len(t):6d} trades  net {means[-1][0]:+.4f}R  gross {g:+.4f}R")
        m = np.array(means)
        se = lambda x: np.nanstd(x, ddof=1) / np.sqrt(np.sum(~np.isnan(x)))
        print(f"over {a.walks} walks: net {np.nanmean(m[:, 0]):+.4f}R (se {se(m[:, 0]):.4f}), "
              f"gross {np.nanmean(m[:, 1]):+.4f}R (se {se(m[:, 1]):.4f}). A strategy with no "
              "edge should show gross about 0 and net about minus its costs.")
        return
    if a.walk:
        specs = load_specs(a.specs) if a.specs else EXAMPLE_SPECS
    else:
        specs = load_specs(a.specs)
    books = []
    for k, sym in enumerate(s.strip() for s in a.symbols.split(",")):
        spec = specs[sym]
        if a.walk:
            make = garch_walk if a.walk == "garch" else t_walk
            price = {"XAUUSD": 2400.0, "US 500": 5500.0}.get(sym, 1.10)
            bars = make(a.bars, interval=a.interval, price=price,
                        spread_points=a.spread_points or 8.0, seed=100 + k)
        elif a.from_ticks:
            ticks = load_ticks(sym, pd.Timestamp(a.start, tz="UTC").timestamp(),
                               pd.Timestamp(a.end, tz="UTC").timestamp(), a.path)
            bars = bars_from_ticks(ticks, a.interval, spec)
        else:
            bars = load_bars(sym, a.interval, a.source, a.path, a.start, a.end)
        book = Book(sym, bars, spec, a.interval)
        if (a.ticks or a.from_ticks) and not a.walk:
            book.ticks = ticks if a.from_ticks else load_ticks(
                sym, float(book.bars["ts"].iat[0]), float(book.bars["ts"].iat[-1]) + 86400, a.path)
        books.append(book)
    costs = Costs(spread_points=a.spread_points, spread_mult=a.spread_mult,
                  commission_per_lot=a.commission, slippage_points=a.slippage_points,
                  stop_slip_frac=a.stop_slip_frac, fill=a.fill)
    if a.audit:
        for b in books:
            res = lookahead(strat, b)
            print(f"look-ahead audit {b.symbol}: {'pass' if res['ok'] else 'FAIL'} over "
                  f"{res['cuts']} cuts")
            if not res["ok"]:
                print(res["failures"].to_string(index=False))
                sys.exit(1)
    kw = dict(costs=costs, equity=a.equity, risk=a.risk, max_open=a.max_open)
    trades, refused = run(books, strat, **kw)
    null = random_null(books, trades, draws=a.null, **kw) if a.null and len(trades) else None
    print(show(summary(trades, refused, a.equity, null)))
    if a.out and len(trades):
        trades.to_csv(a.out, index=False)


if __name__ == "__main__":
    main()
