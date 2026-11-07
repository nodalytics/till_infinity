"""The intelligent-trading-bot method, ported to BTCUSD H1 and nulled.

Runs on the lab under its own interpreter, because scikit-learn is not in the
shared venv and must not be added to it - the full suite runs there and a
transitive scipy would disturb `test_every_third_party_import_is_declared`:

    ./.secrets/lab.sh exec "cd \\$HOME/till_infinity/repo && \\
      OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \\
      nohup \\$HOME/itb-venv/bin/python -u research/harness/itb1h.py \\
      > \\$HOME/till_infinity/logs/itb1h.log 2>&1 &"

## What is being ported

The public repository (asavinov/intelligent-trading-bot) generates a wide
feature set from OHLCV with talib/tsfresh-style operators, builds a
`highlow2` label - did price rise by a threshold within a horizon *without* a
significant adverse move first - trains a classifier on it, and trades the
score. Feature generation, the barrier label and the classifier are the
method; the specific library is not, so the operators here are written in
numpy rather than pulling talib onto the lab.

**One deliberate deviation.** The published label uses thresholds in *percent*.
Over 5.7 years of BTC the volatility regime moves by an order of magnitude, so
a percent threshold is non-stationary - the same 1.5% is a routine hour in one
year and a tail in another, and the label's base rate would drift with the
regime rather than with the signal. The barriers here are in **ATR units**,
which is also the unit this desk sizes and stops in.

## Why the clock is an hour

`btccost.py` measured it: BTCUSD's quoted round trip is **99.4% of the median
1-minute move**, so at a one-ATR M1 stop the cost is 0.463R and a 1:2 trade
breaks even at 0.488. The desk's 0.16R ceiling is not reached until the stop
is 2.9x the M1 ATR, which the median move takes 37 minutes to travel. At H1
with a one-ATR stop the same spread is a few percent of risk, so the method
can at least be measured here.

## The arm that decides it

`iid` rebuilds a price series by bootstrapping BTC's own hourly returns -
same distribution, no time structure - and runs the **identical** pipeline.
A classifier on a wide feature set will always report an AUC above 0.5 on a
barrier label, because the label is partly a function of volatility and the
features measure volatility. `bos-predict.md` is the precedent: geometry
sorted a break's side at AUC 0.75 and walks scored 0.755-0.757. So the real
number means nothing on its own; the gap to `iid` is the whole result.

`shuffled-y` permutes the training labels and must read ~0.5. It is the
harness's own leak detector: a feature built with future data would still
score above chance there.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request as request
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler

DATA = Path.home() / "till_infinity" / "data" / "btc"
SYMBOL = "BTCUSD"
BASE = os.environ.get("BRIDGE", "http://localhost:8000") + "/api/v1"

HORIZON = 24
TARGET_ATR = 2.0
STOP_ATR = 1.0
ATR_N = 14
TRAIN = 8_000
TEST = 1_000
#: Bars held out between train and test. The label at bar i reads bars
#: i+1..i+HORIZON, so without this the last HORIZON rows of a training fold
#: carry outcomes that lie inside the test fold - the purge every barrier
#: label needs and the one `lopez-de-prado.md` is cited for here.
EMBARGO = HORIZON
SEED = 20261107
#: Fallback only; the live quote is fetched when the bridge answers. From
#: `btccost.py`, 2026-11-07.
COST_PX_FALLBACK = 18.42


def quoted_round_trip() -> float:
    try:
        key = (Path.home() / ".mt5key").read_text().strip()
        req = request.Request(  # noqa: S310
            f"{BASE}/symbols/info/{SYMBOL}", headers={"X-API-Key": key}
        )
        with request.urlopen(req, timeout=30) as response:  # noqa: S310
            info = json.loads(response.read().decode())
        bid, ask = float(info.get("bid") or 0.0), float(info.get("ask") or 0.0)
        if ask > bid:
            return ask - bid
    except Exception:  # noqa: BLE001
        pass
    return COST_PX_FALLBACK


def load() -> dict[str, np.ndarray]:
    with np.load(DATA / f"{SYMBOL}.1h.npz") as data:
        return {k: data[k] for k in ("time", "open", "high", "low", "close", "volume")}


def atr(high, low, close, n):
    prev = np.concatenate(([close[0]], close[:-1]))
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev), np.abs(low - prev)))
    out = np.full(len(tr), np.nan)
    csum = np.concatenate(([0.0], np.cumsum(tr)))
    out[n:] = (csum[n:-1] - csum[:-n-1]) / n
    return out


def _roll(values: np.ndarray, n: int, fn) -> np.ndarray:
    """A trailing window ending at i-1, so bar i never sees itself."""
    out = np.full(len(values), np.nan)
    for i in range(n, len(values)):
        out[i] = fn(values[i - n : i])
    return out


def features(bars: dict[str, np.ndarray]) -> tuple[np.ndarray, list[str]]:
    close, high, low, vol = bars["close"], bars["high"], bars["low"], bars["volume"]
    ret = np.concatenate(([0.0], np.diff(np.log(np.maximum(close, 1e-12)))))
    unit = atr(high, low, close, ATR_N)
    cols: list[np.ndarray] = []
    names: list[str] = []

    def add(name: str, values: np.ndarray) -> None:
        cols.append(values)
        names.append(name)

    for k in (1, 2, 3, 6, 12, 24, 48, 96, 168):
        shifted = np.full(len(close), np.nan)
        shifted[k:] = np.log(close[k:] / close[:-k])
        add(f"ret{k}", shifted)
    for k in (6, 12, 24, 48, 96, 168):
        sma = _roll(close, k, np.mean)
        add(f"sma{k}", close / sma - 1.0)
    for k in (12, 24, 48, 96):
        add(f"vol{k}", _roll(ret, k, np.std))
    add("atr_rel", unit / close)
    add("range_rel", (high - low) / close)
    for k in (24, 96):
        add(f"skew{k}", _roll(ret, k, lambda w: float(((w - w.mean()) ** 3).mean() / (w.std() ** 3 + 1e-12))))
        add(f"kurt{k}", _roll(ret, k, lambda w: float(((w - w.mean()) ** 4).mean() / (w.std() ** 4 + 1e-12))))
    # itbstats operators: longest strike below mean, first location of max,
    # slope and area - the ones the published config actually enables.
    add("lsbm24", _roll(close, 24, lambda w: float(_longest_below(w))))
    add("fmax24", _roll(close, 24, lambda w: float(np.argmax(w) / len(w))))
    for k in (12, 48):
        add(f"slope{k}", _roll(close, k, _slope))
    add("area24", _roll(close, 24, lambda w: float((w / w.mean() - 1.0).mean())))
    add("rsi14", _rsi(close, 14))
    vsma = _roll(vol, 24, np.mean)
    add("vol_rel", vol / np.maximum(vsma, 1e-9) - 1.0)

    matrix = np.column_stack(cols)
    return matrix, names


def _longest_below(window: np.ndarray) -> int:
    mean = window.mean()
    best = run = 0
    for value in window:
        run = run + 1 if value < mean else 0
        best = max(best, run)
    return best


def _slope(window: np.ndarray) -> float:
    x = np.arange(len(window), dtype=np.float64)
    x -= x.mean()
    return float((x * (window - window.mean())).sum() / ((x * x).sum() + 1e-12) / (window.mean() + 1e-12))


def _rsi(close: np.ndarray, n: int) -> np.ndarray:
    diff = np.concatenate(([0.0], np.diff(close)))
    up = np.where(diff > 0, diff, 0.0)
    down = np.where(diff < 0, -diff, 0.0)
    out = np.full(len(close), np.nan)
    for i in range(n, len(close)):
        gain, loss = up[i - n : i].mean(), down[i - n : i].mean()
        out[i] = 100.0 - 100.0 / (1.0 + gain / (loss + 1e-12))
    return out


def label(bars: dict[str, np.ndarray], unit: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(y, realised R) for a long 1:2 race. y is 1 where the target lands first.

    Barriers are checked on the **wick**, not the close: a stop read off closes
    is the defect that produced six fake 3:1 survivors elsewhere in this repo.
    """
    close, high, low = bars["close"], bars["high"], bars["low"]
    n = len(close)
    y = np.full(n, np.nan)
    realised = np.full(n, np.nan)
    for i in range(n - HORIZON - 1):
        if not np.isfinite(unit[i]) or unit[i] <= 0.0:
            continue
        entry = close[i]
        up, down = entry + TARGET_ATR * unit[i], entry - STOP_ATR * unit[i]
        hit = 0.0
        for k in range(i + 1, i + HORIZON + 1):
            # The stop is checked first within a bar: one bar can span both
            # barriers and assuming the favourable one is how a backtest
            # invents an edge.
            if low[k] <= down:
                hit = -1.0
                break
            if high[k] >= up:
                hit = TARGET_ATR
                break
        if hit == 0.0:
            hit = (close[i + HORIZON] - entry) / unit[i]
        y[i] = 1.0 if hit > 0 else 0.0
        realised[i] = hit
    return y, realised


def iid_twin(bars: dict[str, np.ndarray], rng) -> dict[str, np.ndarray]:
    """BTC's own hourly returns, resampled - same distribution, no memory.

    The bar's shape is carried across too: high and low are rebuilt from the
    original bar's wick fractions, because a label read off wicks on a series
    with no wicks would be a different measurement, not a null.
    """
    close, high, low, open_ = bars["close"], bars["high"], bars["low"], bars["open"]
    ret = np.diff(np.log(np.maximum(close, 1e-12)))
    drawn = rng.choice(ret, size=len(ret), replace=True)
    new_close = np.concatenate(([close[0]], close[0] * np.exp(np.cumsum(drawn))))
    span = np.maximum(high - low, 1e-12) / np.maximum(close, 1e-12)
    up_share = (high - np.maximum(open_, close)) / span / np.maximum(close, 1e-12)
    up_share = np.clip(np.nan_to_num(up_share, nan=0.25), 0.0, 1.0)
    width = span * new_close
    return {
        "time": bars["time"],
        "open": new_close,
        "close": new_close,
        "high": new_close + width * up_share,
        "low": new_close - width * (1.0 - up_share),
        "volume": bars["volume"],
    }


def walk_forward(matrix, y, realised, name: str, cost_r: np.ndarray, rng) -> None:
    rows = np.isfinite(matrix).all(axis=1) & np.isfinite(y)
    index = np.flatnonzero(rows)
    aucs: dict[str, list[float]] = {"logistic": [], "boosted": []}
    trades: dict[str, list[float]] = {"logistic": [], "boosted": []}
    start = 0
    while True:
        train_end = start + TRAIN
        test_start = train_end + EMBARGO
        test_end = test_start + TEST
        if test_end > len(index):
            break
        tr, te = index[start:train_end], index[test_start:test_end]
        x_tr, y_tr = matrix[tr], y[tr]
        x_te, y_te = matrix[te], y[te]
        if len(np.unique(y_tr)) < 2 or len(np.unique(y_te)) < 2:
            start += TEST
            continue
        scaler = StandardScaler().fit(x_tr)
        models = {
            "logistic": LogisticRegression(max_iter=2000, C=0.1).fit(scaler.transform(x_tr), y_tr),
            "boosted": HistGradientBoostingClassifier(
                max_depth=3, max_iter=200, learning_rate=0.05, random_state=SEED
            ).fit(x_tr, y_tr),
        }
        for label_name, model in models.items():
            x = scaler.transform(x_te) if label_name == "logistic" else x_te
            score = model.predict_proba(x)[:, 1]
            aucs[label_name].append(float(roc_auc_score(y_te, score)))
            # The trade: act on the top decile of the fold's own scores, one
            # position at a time, net of the round trip.
            cut = np.quantile(score, 0.90)
            free = -1
            for position, row in enumerate(te):
                if score[position] < cut or row <= free:
                    continue
                trades[label_name].append(float(realised[row] - cost_r[row]))
                free = row + HORIZON
        start += TEST
    for label_name in ("logistic", "boosted"):
        auc = aucs[label_name]
        book = trades[label_name]
        if not auc:
            continue
        se = float(np.std(book, ddof=1) / np.sqrt(len(book))) if len(book) > 1 else float("nan")
        print(
            f"{name:12s} {label_name:9s} folds {len(auc):3d}  AUC {np.mean(auc):.4f}"
            f" +-{np.std(auc) / np.sqrt(len(auc)):.4f}   trades {len(book):5d}"
            f"  R/trade {np.mean(book) if book else float('nan'):+.4f} +-{se:.4f}"
            f"  win {np.mean([v > 0 for v in book]) if book else float('nan'):.3f}"
        )


def main() -> int:
    rng = np.random.default_rng(SEED)
    bars = load()
    cost_px = quoted_round_trip()
    unit = atr(bars["high"], bars["low"], bars["close"], ATR_N)
    cost_r = cost_px / (STOP_ATR * unit)
    print(f"{SYMBOL} H1: {len(bars['close'])} bars")
    print(
        f"round trip {cost_px:.2f} px = {np.nanmedian(cost_r):.4f} R at a "
        f"{STOP_ATR:g}-ATR stop; break-even at 1:{TARGET_ATR:g} is "
        f"{(1 + np.nanmedian(cost_r)) / (1 + TARGET_ATR):.4f}\n"
    )

    matrix, names = features(bars)
    y, realised = label(bars, unit)
    print(f"{len(names)} features, label base rate {np.nanmean(y):.4f} "
          f"(a driftless walk gives {1 / (1 + TARGET_ATR):.4f})\n")

    head = "arm          model     folds      AUC            trades   R/trade        win"
    print(head)
    print("-" * len(head))
    walk_forward(matrix, y, realised, "real", cost_r, rng)

    shuffled = y.copy()
    finite = np.isfinite(shuffled)
    shuffled[finite] = rng.permutation(shuffled[finite])
    walk_forward(matrix, shuffled, realised, "shuffled-y", cost_r, rng)

    twin = iid_twin(bars, rng)
    twin_unit = atr(twin["high"], twin["low"], twin["close"], ATR_N)
    twin_matrix, _ = features(twin)
    twin_y, twin_realised = label(twin, twin_unit)
    twin_cost = cost_px / (STOP_ATR * twin_unit)
    walk_forward(twin_matrix, twin_y, twin_realised, "iid", twin_cost, rng)

    print(
        "\n`real` minus `iid` is the result. A wide feature set always beats 0.5 on a\n"
        "barrier label because the label is partly volatility and the features measure\n"
        "volatility - geometry sorted a break's side at AUC 0.75 here and walks scored\n"
        "0.755. `shuffled-y` must read about 0.5 or the harness leaks."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
