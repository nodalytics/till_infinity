"""Which TA indicator, if any, should confirm a structures signal before the trading models take it?

The desk wants a confirmation layer in the trading service: a structures signal arrives, from any
timeframe, and TA indicators confirm or reject it before a model takes over. Some models' own entry
plans would then be dropped. The problem it must solve is being stopped out before the market goes
our way, which is poor entry timing. `indicators.md` found no lagging indicator times the touch on
its own timeframe at a fixed horizon, and `stophunt.md` measures the stop-out complaint directly.
This widens the search, and makes **timeframe alignment** the main design: the signal comes from a
higher timeframe (HTF), and the indicators confirm it on a lower one (LTF).

## Signals

Every touch the production `Engine` opens on **1h, 4h and 1d** levels, daily pivots included,
replayed in time order over the lab's bars. The trade fades the arrival: long when price came down
onto the level, short when it came up. A pivot touch is assigned to the bar series that fired it.

## Pairs (HTF -> LTF)

1d->1h, 1d->30m, 4h->1h, 4h->30m, 4h->15m, 1h->15m, and 1h->1h, the same-timeframe test. The LTF
window opens at the LTF bar that closes with the HTF touch bar, when the signal is first known.

  window   gates may fire on LTF bars k0 .. k0 + W, with W = HTF / LTF, capped at 32 (16 x 15m for 4h,
           24 x 1h for 1d, 32 x 30m for 1d); 8 bars on the same timeframe
  entry    the close of the confirming LTF bar
  stop     anchored to the **HTF level**: the level minus (long) or plus (short) 1 x the HTF bar's
           volatility x price (`htf`), and also 1 x the LTF bar's volatility (`ltf`), the tighter
           stop an LTF entry makes possible
  R        the risk from the actual LTF entry to that stop. Entries risking under 0.25 LTF bar vols
           are skipped
  targets  1R and 2R; a bar touching both counts as stopped
  limit    10 HTF bars, in LTF bars, capped at 400; still open at the limit is marked to the close
  cost     `indicators.COST_V` in 5-minute vols, carried to the LTF bar's vol, in R

## Baselines

  htf_close   no gate: enter at the close that completes the HTF touch bar, the plain entry
  ltf_touch   no gate: enter at the first LTF bar in the window that comes back to the level
  random gate a random subset of the htf_close trades, of the gate's own pass rate (selection)
  wait:<g>    every signal, entered after a delay drawn from g's own delays, independent of the path
              (timing)

## Gates, per signal and pair (long shown; short mirrors)

Triggers enter at the first LTF bar in the window where they fire:

  rsi stoch stochrsi bb ema sma macd   as `indicators.py`
  willr        Williams %R(14) back above -80
  cci          CCI(20) back above -100 (mean deviation approximated by 0.798 sd)
  fisher       Fisher transform(10) turning up below 0
  ha           Heikin-Ashi turning from red to green
  supertrend   Supertrend(10, 3) flipping long
  psar         Parabolic SAR(0.02, 0.2) flipping long
  choch        a close above the last 5 bars' highs (a lower-timeframe change of character)
  displacement a bar whose body is at least 1.5 bar vols in the trade's direction
  keltner      a close back inside the lower Keltner band (EMA20 - 1.5 ATR)
  squeeze_fire the Bollinger-in-Keltner squeeze releasing on an up close
  trix         TRIX(15) turning up
  roc          ROC(10) turning up while below zero
  obv          the OBV slope (EMA 5) turning up (FX volume is tick volume)
  mfi          MFI(14) back above 20 (tick volume)
  connors      Connors RSI(3, 2, 100) back above 10
  ultimate     the Ultimate Oscillator(7, 14, 28) back above 30
  vortex       VI+ crossing above VI-(14)
  rsi_div      bullish divergence at the level: a low at or under the window's first bar's, with RSI
               2+ points higher, on an up close
  macd_div     the same with the MACD histogram
  sweep        through the level, no close beyond the stop, then a close back on its side
  candle       production's `trading/candles.py confirms` on the last 3 LTF bars, as `_candle_at`

States are read at the window's first bar and enter there:

  adx_range adx_with chop_range er_low vr_mr aroon_with ichimoku_with ema_with mtf_with
  atr_calm squeeze_on chandelier_with vwap_discount mfi_extreme supertrend_with psar_with
  vortex_with

  (`adx_range`: ADX < 20. `adx_with`: ADX > 25 and the DI on the trade's side. `chop_range`:
  Choppiness(14) > 61.8. `er_low`: Kaufman efficiency ratio(10) < 0.3. `vr_mr`: variance ratio(10)
  over 100 bars < 0.9, a Hurst proxy for mean reversion. `ema_with`: the LTF EMA(200) sloping the
  trade's way. `mtf_with`: the HTF EMA(50) sloping the trade's way. `atr_calm`: ATR(14) / ATR(100)
  < 0.9. `vwap_discount`: under the one-day rolling VWAP for a long.)

Sources for the candidates beyond `indicators.py`: StockCharts ChartSchool
(chartschool.stockcharts.com), TradingView's Vortex and Connors RSI pages, and LuxAlgo's "5
indicators for confirming support and resistance" and Connors RSI guide.

## Learned confirmer

Gradient boosting on every indicator's state at the window's first bar, signed to the trade, plus
the HTF context. The label: the htf_close trade reaches 1R before its HTF stop. Trained on the first
60% by time, scored on the last 40%: AUC, and the net R of the signals it passes at its top 50 / 30
/ 10% (thresholds from the training predictions).

## Controls and pre-registration

Walks we generate (iid Student-t(3) 15m, aggregated to 30m, 1h, 4h and 1d) are the null. Deriv is a
market, reported apart. FX is shown without the 21:00 UTC rollover touches as the primary view
(`rollover.md`): a touch whose extreme printed in the 21:00-21:59 UTC 15m bars.

A gate passes on a (family, pair) if it beats htf_close by at least 0.05R net, with t >= 3
(clustered by series-day) and Benjamini-Hochberg q < 0.05 across every market cell. It must also
beat its random gate, be positive in both halves, and beat the same cell on the walks by 0.05R with
t >= 3. The last condition exists because a later entry against a level-anchored stop risks more,
so it pays less cost in R, and `stophunt.md` found that is worth up to +0.15R on walks.

Added after the first full run: that mechanical gain scales with the cost, and the walks are charged
0.15 against FX's 0.8, so the walks understate it about five times on FX. The first run passed 180
cells, all of them losing money in absolute terms, nearly all on FX with entries about 2 bars late.
So a cell must also beat htf_close **gross of costs** by at least 0.05R more than the walks do, with
gross t >= 3.

Run on the lab, one process per universe, then the report:
  UNIVERSE=real  START=2024-01-01 SEQLAB=$HOME/till_infinity/data/seqlab python research/harness/confirm.py
  UNIVERSE=deriv ...    UNIVERSE=walks ...    then  PART=report
"""
from __future__ import annotations

import heapq
import json
import math
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import indicators as ind

from till_infinity.structures.engine import Engine
from till_infinity.trading import candles
from till_infinity.trading.sizing import price_distance

UNIVERSE = os.environ.get("UNIVERSE", "real")
PART = os.environ.get("PART", "run")
OUT = Path(os.environ.get("OUT", ".data/confirm"))
MIN = {"15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}
SIGNALS = ("1h", "4h", "1d")
LTFS = ("15m", "30m", "1h")
PAIRS = (("1d", "1h"), ("1d", "30m"), ("4h", "1h"), ("4h", "30m"), ("4h", "15m"), ("1h", "15m"),
         ("1h", "1h"))
CAP_WINDOW, SAME_WINDOW = 32, 8
LIMIT_HTF, CAP_LIMIT = 10, 400
TARGETS = (1, 2)
MIN_R = 0.25
TRIGGERS = ("rsi", "stoch", "stochrsi", "bb", "ema", "sma", "macd", "willr", "cci", "fisher", "ha",
            "supertrend", "psar", "choch", "displacement", "keltner", "squeeze_fire", "trix", "roc",
            "obv", "mfi", "connors", "ultimate", "vortex", "rsi_div", "macd_div", "sweep", "candle")
STATES = ("adx_range", "adx_with", "chop_range", "er_low", "vr_mr", "aroon_with", "ichimoku_with",
          "ema_with", "mtf_with", "atr_calm", "squeeze_on", "chandelier_with", "vwap_discount",
          "mfi_extreme", "supertrend_with", "psar_with", "vortex_with")
GATES = TRIGGERS + STATES


# ------------------------------------------------------------------------------------------ bars

def aggregate(df: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """Bars of `minutes` from finer ones, bucketed on UTC boundaries; buckets under half full go."""
    step = minutes * 60
    fine = int(np.median(np.diff(df["ts"].to_numpy()))) if len(df) > 1 else step
    need = max(1, step // max(fine, 1))
    d = df.assign(b=(df["ts"] // step) * step)
    cols = {"open": ("open", "first"), "high": ("high", "max"), "low": ("low", "min"),
            "close": ("close", "last"), "n": ("ts", "size")}
    if "volume" in d:
        cols["volume"] = ("volume", "sum")
    out = d.groupby("b").agg(**cols)
    out = out[out["n"] >= need / 2].drop(columns="n").reset_index().rename(columns={"b": "ts"})
    return out


def load() -> dict[tuple[str, str], pd.DataFrame]:
    frames = {}
    for sym in ind.SYMBOLS[UNIVERSE]:
        fine = ind.frame(sym, "15m")
        if fine is None or len(fine) < 500:
            continue
        frames[(sym, "15m")] = fine
        frames[(sym, "30m")] = aggregate(fine, 30)
        for iv in ("1h", "4h", "1d"):
            got = aggregate(fine, MIN[iv]) if sym.startswith("walk_") else ind.frame(sym, iv)
            if got is not None and len(got) > 60:
                frames[(sym, iv)] = got.reset_index(drop=True)
    return frames


def bars_of(sym, iv, df):
    for t, h, lo, c in zip(df["ts"].to_numpy(), df["high"].to_numpy(), df["low"].to_numpy(),
                           df["close"].to_numpy(), strict=True):
        yield {"feed": sym.lower(), "venue": "SEQLAB", "interval": iv, "time": int(t),
               "high": float(h), "low": float(lo), "close": float(c)}


def zones(frames) -> list[dict]:
    """Every touch the production engine opens on the signal timeframes, in time order."""
    htf = {k: v for k, v in frames.items() if k[1] in SIGNALS}
    engine = Engine(intervals=SIGNALS)
    engine.consensus.single_source = frozenset(s.lower() for s, _ in htf)
    stream = heapq.merge(*(bars_of(s, iv, df) for (s, iv), df in htf.items()),
                         key=lambda b: (b["time"], MIN[b["interval"]]))
    out, seen = [], set()
    for n, bar in enumerate(stream):
        for call in engine.observe_bar(bar):
            touch = engine.tracker.open_touch(call.level)
            if touch is None or touch.started != call.time:
                continue
            k = (call.feed, call.interval, round(touch.level_price, 8), touch.started)
            if k in seen:
                continue
            seen.add(k)
            out.append({"feed": call.feed, "interval": call.interval, "time": int(call.time),
                        "level": float(touch.level_price),
                        "above": touch.features.side.name == "ABOVE"})
        if n % 50_000 == 0:
            print(f"  {n:,} bars, {len(out):,} touches", flush=True)
    return out


# ------------------------------------------------------------------------------------ indicators

def prev(a, n=1):
    a = np.asarray(a, dtype=float)
    return np.r_[np.full(n, np.nan), a[:-n]] if n < len(a) else np.full(len(a), np.nan)


def wilder(x, n):
    return pd.Series(x).ewm(alpha=1 / n, adjust=False).mean().to_numpy()


def supertrend(h, lo, c, atr, mult=3.0):
    mid = (h + lo) / 2
    up, dn = mid - mult * atr, mid + mult * atr
    side = np.ones(len(c))
    fu, fd = up.copy(), dn.copy()
    for t in range(1, len(c)):
        fu[t] = max(up[t], fu[t - 1]) if c[t - 1] > fu[t - 1] else up[t]
        fd[t] = min(dn[t], fd[t - 1]) if c[t - 1] < fd[t - 1] else dn[t]
        if side[t - 1] > 0:
            side[t] = -1 if c[t] < fu[t] else 1
        else:
            side[t] = 1 if c[t] > fd[t] else -1
        if not np.isfinite(fu[t]) or not np.isfinite(fd[t]):
            side[t] = side[t - 1]
    return side


def psar(h, lo, step=0.02, cap=0.2):
    n = len(h)
    side = np.ones(n)
    if n < 3:
        return side
    long, af, ep, sar = True, step, h[0], lo[0]
    for t in range(1, n):
        sar = sar + af * (ep - sar)
        if long:
            sar = min(sar, lo[t - 1], lo[t - 2] if t > 1 else lo[t - 1])
            if lo[t] < sar:
                long, sar, ep, af = False, ep, lo[t], step
            elif h[t] > ep:
                ep, af = h[t], min(af + step, cap)
        else:
            sar = max(sar, h[t - 1], h[t - 2] if t > 1 else h[t - 1])
            if h[t] > sar:
                long, sar, ep, af = True, ep, h[t], step
            elif lo[t] < ep:
                ep, af = lo[t], min(af + step, cap)
        side[t] = 1 if long else -1
    return side


def features(df: pd.DataFrame, minutes: int) -> dict[str, np.ndarray]:
    x = ind.indicators(df)
    o, h, lo, c = (df[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
    vol_ = df["volume"].to_numpy(dtype=float) if "volume" in df else np.ones(len(c))
    vol_ = np.where(np.isfinite(vol_) & (vol_ > 0), vol_, 1.0)
    cs, hs, ls = pd.Series(c), pd.Series(h), pd.Series(lo)
    pc = prev(c)
    tr = np.nanmax(np.column_stack([h - lo, np.abs(h - pc), np.abs(lo - pc)]), axis=1)
    atr = wilder(tr, 14)
    x.update(open=o, high=h, low=lo, atr=atr)
    # ADX / DMI
    up_move, dn_move = h - prev(h), prev(lo) - lo
    pdm = np.where((up_move > dn_move) & (up_move > 0), up_move, 0.0)
    mdm = np.where((dn_move > up_move) & (dn_move > 0), dn_move, 0.0)
    pdi = 100 * wilder(pdm, 14) / atr
    mdi = 100 * wilder(mdm, 14) / atr
    dx = 100 * np.abs(pdi - mdi) / np.where(pdi + mdi > 0, pdi + mdi, np.nan)
    x["adx"], x["di"] = wilder(np.nan_to_num(dx), 14), pdi - mdi
    # Aroon(25)
    x["aroon"] = (hs.rolling(26).apply(np.argmax, raw=True) - ls.rolling(26).apply(np.argmin, raw=True)
                  ).to_numpy() * 100 / 25
    # Choppiness, efficiency ratio, variance ratio
    rng14 = hs.rolling(14).max() - ls.rolling(14).min()
    x["chop"] = (100 * np.log10(pd.Series(tr).rolling(14).sum() / rng14) / np.log10(14)).to_numpy()
    x["er"] = (np.abs(cs - cs.shift(10)) / cs.diff().abs().rolling(10).sum()).to_numpy()
    lc = np.log(cs)
    x["vr"] = ((lc - lc.shift(10)).rolling(100).var() / (10 * lc.diff().rolling(100).var())).to_numpy()
    # Supertrend, PSAR
    x["st"] = supertrend(h, lo, c, wilder(tr, 10))
    x["psar"] = psar(h, lo)
    # Ichimoku cloud
    tenkan = (hs.rolling(9).max() + ls.rolling(9).min()) / 2
    kijun = (hs.rolling(26).max() + ls.rolling(26).min()) / 2
    x["span_a"] = ((tenkan + kijun) / 2).shift(26).to_numpy()
    x["span_b"] = ((hs.rolling(52).max() + ls.rolling(52).min()) / 2).shift(26).to_numpy()
    # Keltner, squeeze, chandelier
    ema20 = cs.ewm(span=20, adjust=False).mean().to_numpy()
    x["kc_lo"], x["kc_hi"] = ema20 - 1.5 * atr, ema20 + 1.5 * atr
    x["squeeze"] = ((x["bb_lo"] > x["kc_lo"]) & (x["bb_hi"] < x["kc_hi"])).astype(float)
    x["chand_long"] = (hs.rolling(22).max().to_numpy() - 3 * atr)
    x["chand_short"] = (ls.rolling(22).min().to_numpy() + 3 * atr)
    x["atr_ratio"] = atr / wilder(tr, 100)
    # EMA slopes
    e200 = cs.ewm(span=200, adjust=False).mean()
    x["slope200"] = (e200 - e200.shift(5)).to_numpy()
    e50 = cs.ewm(span=50, adjust=False).mean()
    x["slope50"] = (e50 - e50.shift(3)).to_numpy()
    # CCI, Williams %R, ROC, TRIX, Fisher
    tp = (hs + ls + cs) / 3
    x["cci"] = ((tp - tp.rolling(20).mean()) / (0.015 * 0.798 * tp.rolling(20).std())).to_numpy()
    hh14, ll14 = hs.rolling(14).max(), ls.rolling(14).min()
    x["willr"] = (-100 * (hh14 - cs) / (hh14 - ll14)).to_numpy()
    x["roc"] = (100 * (cs / cs.shift(10) - 1)).to_numpy()
    t3 = cs.ewm(span=15, adjust=False).mean().ewm(span=15, adjust=False).mean().ewm(span=15, adjust=False).mean()
    x["trix"] = (100 * t3.pct_change()).to_numpy()
    mid = ((hs + ls) / 2).to_numpy()
    lo10, hi10 = ls.rolling(10).min().to_numpy(), hs.rolling(10).max().to_numpy()
    raw = 2 * ((mid - lo10) / np.where(hi10 > lo10, hi10 - lo10, np.nan) - 0.5)
    fish, val = np.zeros(len(c)), 0.0
    for t in range(len(c)):
        r = raw[t] if np.isfinite(raw[t]) else 0.0
        val = min(max(0.33 * r + 0.67 * val, -0.999), 0.999)
        fish[t] = 0.5 * math.log((1 + val) / (1 - val)) + 0.5 * (fish[t - 1] if t else 0.0)
    x["fisher"] = fish
    # Heikin-Ashi colour
    ha_c = (o + h + lo + c) / 4
    ha_o = np.empty(len(c))
    ha_o[0] = (o[0] + c[0]) / 2
    for t in range(1, len(c)):
        ha_o[t] = (ha_o[t - 1] + ha_c[t - 1]) / 2
    x["ha"] = np.sign(ha_c - ha_o)
    # volume: OBV slope, MFI, VWAP
    obv = np.cumsum(np.sign(np.nan_to_num(np.diff(c, prepend=c[0]))) * vol_)
    x["obv"] = pd.Series(obv).ewm(span=5, adjust=False).mean().diff().to_numpy()
    tpa = tp.to_numpy()
    flow = tpa * vol_
    dtp = np.diff(tpa, prepend=tpa[0])
    pos = pd.Series(np.where(dtp > 0, flow, 0.0)).rolling(14).sum()
    neg = pd.Series(np.where(dtp < 0, flow, 0.0)).rolling(14).sum()
    x["mfi"] = (100 - 100 / (1 + pos / neg.replace(0, np.nan))).to_numpy()
    day = max(1, 1440 // minutes)
    x["vwap"] = (pd.Series(flow).rolling(day).sum() / pd.Series(vol_).rolling(day).sum()).to_numpy()
    # Connors RSI(3, 2, 100)
    ch = np.sign(np.diff(c, prepend=c[0]))
    streak = np.zeros(len(c))
    for t in range(1, len(c)):
        streak[t] = (streak[t - 1] + 1 if streak[t - 1] > 0 else 1) if ch[t] > 0 else \
            (streak[t - 1] - 1 if streak[t - 1] < 0 else -1) if ch[t] < 0 else 0
    rank = cs.pct_change().rolling(100).rank(pct=True).to_numpy() * 100
    x["connors"] = (ind.rsi(cs, 3).to_numpy() + ind.rsi(pd.Series(streak), 2).to_numpy() + rank) / 3
    # Ultimate Oscillator(7, 14, 28)
    bp = c - np.fmin(lo, pc)
    tr2 = np.fmax(h, pc) - np.fmin(lo, pc)
    avg = [pd.Series(bp).rolling(n).sum() / pd.Series(tr2).rolling(n).sum() for n in (7, 14, 28)]
    x["uo"] = (100 * (4 * avg[0] + 2 * avg[1] + avg[2]) / 7).to_numpy()
    # Vortex(14)
    vp = pd.Series(np.abs(h - prev(lo))).rolling(14).sum()
    vm = pd.Series(np.abs(lo - prev(h))).rolling(14).sum()
    trs = pd.Series(tr).rolling(14).sum()
    x["vortex"] = ((vp - vm) / trs).to_numpy()
    x["hist"] = x["macd"] - x["signal"]
    x["body"] = (c - o) / (x["vol"] * c)
    x["hh5"], x["ll5"] = prev(hs.rolling(5).max().to_numpy()), prev(ls.rolling(5).min().to_numpy())
    return x


def trigger_arrays(x) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """Every level-independent trigger as (fires for a long, fires for a short) per bar."""
    c = x["close"]

    def up_through(a, lvl):
        return (prev(a) < lvl) & (a >= lvl)

    def down_through(a, lvl):
        return (prev(a) > lvl) & (a <= lvl)

    def turn_up(a):
        return (a > prev(a)) & (prev(a) <= prev(a, 2))

    def turn_down(a):
        return (a < prev(a)) & (prev(a) >= prev(a, 2))

    def cross(a, b):
        d = a - b
        return (d > 0) & (prev(d) <= 0), (d < 0) & (prev(d) >= 0)

    t = {}
    t["rsi"] = (up_through(x["rsi"], 30), down_through(x["rsi"], 70))
    lk, sk = cross(x["k"], x["d"])
    t["stoch"] = (lk & (x["k"] < 20), sk & (x["k"] > 80))
    lk, sk = cross(x["rk"], x["rd"])
    t["stochrsi"] = (lk & (x["rk"] < 20), sk & (x["rk"] > 80))
    t["bb"] = ((prev(c) < prev(x["bb_lo"])) & (c >= x["bb_lo"]), (prev(c) > prev(x["bb_hi"])) & (c <= x["bb_hi"]))
    t["ema"] = cross(c, x["ema"])
    t["sma"] = cross(c, x["sma"])
    t["macd"] = cross(x["macd"], x["signal"])
    t["willr"] = (up_through(x["willr"], -80), down_through(x["willr"], -20))
    t["cci"] = (up_through(x["cci"], -100), down_through(x["cci"], 100))
    t["fisher"] = (turn_up(x["fisher"]) & (x["fisher"] < 0), turn_down(x["fisher"]) & (x["fisher"] > 0))
    t["ha"] = ((x["ha"] > 0) & (prev(x["ha"]) < 0), (x["ha"] < 0) & (prev(x["ha"]) > 0))
    t["supertrend"] = ((x["st"] > 0) & (prev(x["st"]) < 0), (x["st"] < 0) & (prev(x["st"]) > 0))
    t["psar"] = ((x["psar"] > 0) & (prev(x["psar"]) < 0), (x["psar"] < 0) & (prev(x["psar"]) > 0))
    t["choch"] = (c > x["hh5"], c < x["ll5"])
    t["displacement"] = (x["body"] >= 1.5, x["body"] <= -1.5)
    t["keltner"] = ((prev(c) < prev(x["kc_lo"])) & (c >= x["kc_lo"]), (prev(c) > prev(x["kc_hi"])) & (c <= x["kc_hi"]))
    sq = x["squeeze"] > 0
    rel = (prev(x["squeeze"]) > 0) & ~sq
    t["squeeze_fire"] = (rel & (c > prev(c)), rel & (c < prev(c)))
    t["trix"] = (turn_up(x["trix"]), turn_down(x["trix"]))
    t["roc"] = (turn_up(x["roc"]) & (prev(x["roc"]) < 0), turn_down(x["roc"]) & (prev(x["roc"]) > 0))
    t["obv"] = ((x["obv"] > 0) & (prev(x["obv"]) <= 0), (x["obv"] < 0) & (prev(x["obv"]) >= 0))
    t["mfi"] = (up_through(x["mfi"], 20), down_through(x["mfi"], 80))
    t["connors"] = (up_through(x["connors"], 10), down_through(x["connors"], 90))
    t["ultimate"] = (up_through(x["uo"], 30), down_through(x["uo"], 70))
    t["vortex"] = ((x["vortex"] > 0) & (prev(x["vortex"]) <= 0), (x["vortex"] < 0) & (prev(x["vortex"]) >= 0))
    return {k: (np.nan_to_num(a, nan=0).astype(bool), np.nan_to_num(b, nan=0).astype(bool)) for k, (a, b) in t.items()}


def state(name, x, k, s, hx=None, hi=None) -> bool:
    c = x["close"][k]
    if name == "adx_range":
        return x["adx"][k] < 20
    if name == "adx_with":
        return x["adx"][k] > 25 and s * x["di"][k] > 0
    if name == "chop_range":
        return x["chop"][k] > 61.8
    if name == "er_low":
        return x["er"][k] < 0.3
    if name == "vr_mr":
        return x["vr"][k] < 0.9
    if name == "aroon_with":
        return s * x["aroon"][k] > 0
    if name == "ichimoku_with":
        top, bot = max(x["span_a"][k], x["span_b"][k]), min(x["span_a"][k], x["span_b"][k])
        return bool(c > top) if s > 0 else bool(c < bot)
    if name == "ema_with":
        return s * x["slope200"][k] > 0
    if name == "mtf_with":
        return hx is not None and s * hx["slope50"][hi] > 0
    if name == "atr_calm":
        return x["atr_ratio"][k] < 0.9
    if name == "squeeze_on":
        return x["squeeze"][k] > 0
    if name == "chandelier_with":
        return bool(c > x["chand_long"][k]) if s > 0 else bool(c < x["chand_short"][k])
    if name == "vwap_discount":
        return s * (x["vwap"][k] - c) > 0
    if name == "mfi_extreme":
        return x["mfi"][k] < 20 if s > 0 else x["mfi"][k] > 80
    if name == "supertrend_with":
        return x["st"][k] == s
    if name == "psar_with":
        return x["psar"][k] == s
    if name == "vortex_with":
        return s * x["vortex"][k] > 0
    raise ValueError(name)


FEATURES = ("rsi", "k", "willr", "cci", "fisher", "adx", "di", "chop", "er", "vr", "aroon", "ichimoku",
            "slope200", "atr_ratio", "squeeze", "bbpos", "kcpos", "hist", "trix", "roc", "obv", "mfi",
            "vwap", "ha", "st", "psar", "connors", "uo", "vortex", "dist", "approach", "mtf")


def feature_row(x, k, s, level, hx, hi) -> list[float]:
    """Every indicator's state at bar k, signed so that + leans with the trade."""
    c, v = x["close"][k], x["vol"][k] * x["close"][k]

    def z(a):
        return float(a) if np.isfinite(a) else np.nan

    cloud = (x["span_a"][k] + x["span_b"][k]) / 2
    return [
        z(s * (x["rsi"][k] - 50)), z(s * (x["k"][k] - 50)), z(s * (x["willr"][k] + 50)), z(s * x["cci"][k]),
        z(s * x["fisher"][k]), z(x["adx"][k]), z(s * x["di"][k]), z(x["chop"][k]), z(x["er"][k]), z(x["vr"][k]),
        z(s * x["aroon"][k]), z(s * (c - cloud) / v), z(s * x["slope200"][k] / v), z(x["atr_ratio"][k]),
        z(x["squeeze"][k]), z(s * (c - x["sma"][k]) / max(x["bb_hi"][k] - x["sma"][k], 1e-12)),
        z(s * (c - (x["kc_hi"][k] + x["kc_lo"][k]) / 2) / v), z(s * x["hist"][k] / v), z(s * x["trix"][k]),
        z(s * x["roc"][k]), z(s * np.sign(x["obv"][k])), z(s * (x["mfi"][k] - 50)), z(s * (c - x["vwap"][k]) / v),
        z(s * x["ha"][k]), z(s * x["st"][k]), z(s * x["psar"][k]), z(s * (x["connors"][k] - 50)),
        z(s * (x["uo"][k] - 50)), z(s * x["vortex"][k]), z(s * (c - level) / v),
        z(s * (c - x["close"][max(k - 5, 0)]) / v),
        z(s * hx["slope50"][hi] / (hx["vol"][hi] * hx["close"][hi])) if hx is not None else np.nan,
    ]


# ------------------------------------------------------------------------------------ simulation

def simulate(h, lo, c, j, s, stop, risk, limit):
    end = min(j + limit, len(c) - 1)
    if end <= j:
        return None
    hh, ll = h[j + 1 : end + 1], lo[j + 1 : end + 1]
    stopped_at = np.flatnonzero(ll <= stop if s > 0 else hh >= stop)
    ts = stopped_at[0] if len(stopped_at) else np.inf
    out = []
    for k in TARGETS:
        target = c[j] + s * k * risk
        reached = np.flatnonzero(hh >= target if s > 0 else ll <= target)
        tk = reached[0] if len(reached) else np.inf
        if tk < ts:
            out.append((float(k), False, False, True))
        elif np.isfinite(ts):
            out.append((-1.0, True, bool(np.isfinite(tk)), False))
        else:
            out.append((float(s * (c[end] - c[j]) / risk), False, False, False))
    return out


def rollover(fine_ts, fine_lo, fine_hi, t0, t1, s) -> bool:
    """Whether the touch's extreme inside [t0, t1) printed in the 21:00 UTC 15m bars."""
    a, b = np.searchsorted(fine_ts, t0), np.searchsorted(fine_ts, t1)
    if b <= a:
        return False
    k = a + (int(np.argmin(fine_lo[a:b])) if s > 0 else int(np.argmax(fine_hi[a:b])))
    return (fine_ts[k] // 3600) % 24 == 21


def run() -> None:
    frames = load()
    print(f"{UNIVERSE}: {len(frames)} series", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    cache = OUT / f"{UNIVERSE}.touches.json"
    if cache.exists():
        touches = json.loads(cache.read_text())
    else:
        touches = zones(frames)
        cache.write_text(json.dumps(touches))
    print(f"{UNIVERSE}: {len(touches):,} signals on {', '.join(SIGNALS)}", flush=True)

    X, TRIG, TS = {}, {}, {}
    for (sym, iv), df in frames.items():
        X[(sym.lower(), iv)] = features(df, MIN[iv])
        TS[(sym.lower(), iv)] = df["ts"].to_numpy()
        if iv in LTFS:
            TRIG[(sym.lower(), iv)] = trigger_arrays(X[(sym.lower(), iv)])
    fam_of = {s.lower(): ind.FAMILY.get(s, "walks") for s, _ in frames}
    print(f"{UNIVERSE}: indicators computed", flush=True)

    rng = np.random.default_rng(17)
    rows, feats = [], []
    delays = {g: [] for g in TRIGGERS}
    plans = []
    for sid, z in enumerate(touches):
        feed = z["feed"]
        options = [z["interval"]] if z["interval"] in SIGNALS else list(SIGNALS)
        htf = None
        for iv in options:
            if (feed, iv) in TS:
                i = int(np.searchsorted(TS[(feed, iv)], z["time"]))
                if i < len(TS[(feed, iv)]) and TS[(feed, iv)][i] == z["time"]:
                    htf, hi = iv, i
                    break
        if htf is None or hi < 60:
            continue
        hx = X[(feed, htf)]
        s = 1 if z["above"] else -1
        closes_at = z["time"] + MIN[htf] * 60
        fine = (feed, "15m")
        roll = fam_of[feed] == "fx" and fine in TS and rollover(
            TS[fine], X[fine]["low"], X[fine]["high"], z["time"], closes_at, s)
        for a, b in PAIRS:
            if a != htf or (feed, b) not in TS:
                continue
            lts, x = TS[(feed, b)], X[(feed, b)]
            if a == b:
                k0 = hi
            else:
                k0 = int(np.searchsorted(lts, closes_at)) - 1
                if k0 < 0 or lts[k0] < z["time"]:
                    continue
            if k0 < 210:
                continue
            ratio = MIN[a] // MIN[b]
            window = SAME_WINDOW if a == b else min(ratio, CAP_WINDOW)
            limit = min(LIMIT_HTF * max(ratio, 1), CAP_LIMIT)
            plans.append((sid, feed, a, b, k0, hi, s, z["level"], z["time"], window, limit, roll))
            feats.append([sid, f"{a}>{b}", *feature_row(x, k0, s, z["level"], hx, hi)])
    print(f"{UNIVERSE}: {len(plans):,} signal x pair plans", flush=True)

    for n, (sid, feed, a, b, k0, hi, s, level, t, window, limit, roll) in enumerate(plans):
        x, trig = X[(feed, b)], TRIG[(feed, b)]
        hx = X[(feed, a)]
        o, h, lo, c = x["open"], x["high"], x["low"], x["close"]
        end = min(k0 + window, len(c) - 2)
        stops = {"htf": level - s * hx["vol"][hi] * hx["close"][hi], "ltf": level - s * x["vol"][k0] * c[k0]}
        entries: dict[str, int] = {"htf_close": k0}
        back = np.flatnonzero((lo[k0 + 1 : end + 1] <= level) if s > 0 else (h[k0 + 1 : end + 1] >= level))
        if len(back):
            entries["ltf_touch"] = k0 + 1 + int(back[0])
        for g, (lg, sg) in trig.items():
            fired = np.flatnonzero((lg if s > 0 else sg)[k0 : end + 1])
            if len(fired):
                entries[g] = k0 + int(fired[0])
        for j in range(k0 + 1, end + 1):
            if "rsi_div" not in entries and s * (x["rsi"][j] - x["rsi"][k0]) > 2 and s * (c[j] - o[j]) > 0 and \
                    (lo[j] <= lo[k0] if s > 0 else h[j] >= h[k0]):
                entries["rsi_div"] = j
            if "macd_div" not in entries and s * (x["hist"][j] - x["hist"][k0]) > 0 and s * (c[j] - o[j]) > 0 and \
                    (lo[j] <= lo[k0] if s > 0 else h[j] >= h[k0]):
                entries["macd_div"] = j
        tol = price_distance(level, x["vol"][k0] * 10_000, 0.25)
        for j in range(max(k0, 2), end + 1):
            bars = [candles.Bar(o[m], h[m], lo[m], c[m]) for m in range(j - 2, j + 1)]
            if candles.confirms(bars, level, s > 0, tol):
                entries["candle"] = j
                break
        for g in STATES:
            if state(g, x, k0, s, hx, hi):
                entries[g] = k0
        for skind, stop in stops.items():
            sweep = None
            swept = False
            for j in range(k0, end + 1):
                if s * (c[j] - stop) <= 0:
                    break
                swept = swept or (lo[j] < level if s > 0 else h[j] > level)
                if swept and s * (c[j] - level) > 0 and j > k0:
                    sweep = j
                    break
            here = dict(entries)
            if sweep is not None:
                here["sweep"] = sweep
            elif "sweep" in here:
                del here["sweep"]
            for rule, j in here.items():
                if rule in TRIGGERS and skind == "htf":
                    delays[rule].append(j - k0)
                risk = s * (c[j] - stop)
                if not risk > MIN_R * x["vol"][j] * c[j]:
                    continue
                got = simulate(h, lo, c, j, s, stop, risk, limit)
                if got is None:
                    continue
                cost = ind.COST_V[fam_of[feed]] * np.sqrt(5 / MIN[b]) * x["vol"][j] * c[j] / risk
                for k, (r, stopped, then_right, hit) in zip(TARGETS, got, strict=True):
                    rows.append((sid, rule, fam_of[feed], feed, f"{a}>{b}", skind, k, t, roll, j - k0,
                                 r - cost, cost, stopped, then_right, hit))
        if n % 20_000 == 0:
            print(f"  {n:,} of {len(plans):,} plans, {len(rows):,} rows", flush=True)

    # timing control: every signal, entered after a delay drawn from each trigger's own delays
    for n, (sid, feed, a, b, k0, hi, s, level, t, window, limit, roll) in enumerate(plans):
        x, hx = X[(feed, b)], X[(feed, a)]
        h, lo, c = x["high"], x["low"], x["close"]
        stop = level - s * hx["vol"][hi] * hx["close"][hi]
        for g, ds in delays.items():
            if not ds:
                continue
            j = k0 + int(rng.choice(ds))
            if j >= len(c) - 1:
                continue
            risk = s * (c[j] - stop)
            if not risk > MIN_R * x["vol"][j] * c[j]:
                continue
            got = simulate(h, lo, c, j, s, stop, risk, limit)
            if got is None:
                continue
            cost = ind.COST_V[fam_of[feed]] * np.sqrt(5 / MIN[b]) * x["vol"][j] * c[j] / risk
            for k, (r, stopped, then_right, hit) in zip(TARGETS, got, strict=True):
                rows.append((sid, f"wait:{g}", fam_of[feed], feed, f"{a}>{b}", "htf", k, t, roll, j - k0,
                             r - cost, cost, stopped, then_right, hit))
    df = pd.DataFrame(rows, columns=["sid", "rule", "family", "feed", "pair", "stop", "k", "time", "rollover",
                                     "delay", "net", "cost", "stopped", "then_right", "hit"])
    for col in ("rule", "family", "feed", "pair", "stop"):
        df[col] = df[col].astype("category")
    df["universe"] = UNIVERSE
    df.to_pickle(OUT / f"{UNIVERSE}.pkl.gz")
    pd.DataFrame(feats, columns=["sid", "pair", *FEATURES]).to_pickle(OUT / f"{UNIVERSE}.features.pkl.gz")
    print(f"{UNIVERSE}: {len(df):,} rows written", flush=True)


# ---------------------------------------------------------------------------------------- report

def mean_se(g: pd.DataFrame) -> tuple[float, float, int]:
    g = g[np.isfinite(g["net"])]
    if len(g) < 3:
        return float("nan"), float("nan"), len(g)
    m = g["net"].mean()
    cl = g["feed"].astype(str) + "|" + (g["time"] // 86_400).astype(str)
    sums = (g["net"] - m).groupby(cl).sum()
    return float(m), float(np.sqrt((sums**2).sum()) / len(g)), len(g)


def diff(a, b):
    ma, sa, na = mean_se(a)
    mb, sb, nb = mean_se(b)
    if na < 3 or nb < 3:
        return float("nan"), float("nan"), float("nan")
    d = ma - mb
    return d, d / np.sqrt(sa**2 + sb**2), np.sqrt(sa**2 + sb**2)


def bh(p: np.ndarray) -> np.ndarray:
    p = np.asarray(p, float)
    ok = np.isfinite(p)
    q = np.full(len(p), np.nan)
    if ok.sum() == 0:
        return q
    pv = p[ok]
    order = np.argsort(pv)
    ranked = pv[order] * ok.sum() / (np.arange(ok.sum()) + 1)
    ranked = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty(ok.sum())
    out[order] = np.minimum(ranked, 1)
    q[ok] = out
    return q


def cells(df: pd.DataFrame) -> pd.DataFrame:
    """One row per (view, pair, stop, k, rule): the measures, and the differences from htf_close."""
    from math import erf

    cut = df["time"].quantile(0.6)
    rng = np.random.default_rng(3)
    views = []
    for fam, g in df.groupby("family", observed=True):
        if fam == "fx":
            views.append(("fx", g[~g["rollover"]]))
            views.append(("fx+rollover", g))
        else:
            views.append((str(fam), g))
    out = []
    for view, g in views:
        for (pair, stop, k), c in g.groupby(["pair", "stop", "k"], observed=True):
            base = c[c["rule"] == "htf_close"]
            # Every signal the cell holds is the denominator: a gate can pass a signal whose plain
            # entry was skipped for risking too little at that bar.
            nsig = c["sid"].nunique()
            base_sids = base["sid"].unique()
            if len(base_sids) < 50:
                continue
            for rule, r in c.groupby("rule", observed=True):
                if len(r) < 30 or str(rule).startswith("wait:"):
                    continue
                passed = r["sid"].unique()
                rate = len(passed) / nsig
                d, t, _ = diff(r, base)
                dg, tg, _ = diff(r.assign(net=r["net"] + r["cost"]), base.assign(net=base["net"] + base["cost"]))
                size = min(len(base_sids), max(1, int(round(rate * len(base_sids)))))
                pick = rng.choice(base_sids, size, replace=False)
                rnd = base[base["sid"].isin(pick)]
                dr, tr_, _ = diff(r, rnd)
                wait = c[c["rule"] == f"wait:{rule}"]
                dw, tw, _ = diff(r, wait) if len(wait) else (np.nan, np.nan, np.nan)
                rejected = base[~base["sid"].isin(passed)]
                halves = [diff(r[r["time"] < cut], base[base["time"] < cut])[0],
                          diff(r[r["time"] >= cut], base[base["time"] >= cut])[0]]
                p = 2 * (1 - 0.5 * (1 + erf(abs(t) / np.sqrt(2)))) if np.isfinite(t) else np.nan
                out.append({
                    "view": view, "pair": pair, "stop": stop, "k": k, "rule": str(rule), "n": len(r),
                    "pass": rate, "net": r["net"].mean(), "stop_rate": r["stopped"].mean(),
                    "then_right": r["then_right"].mean(), "hit": r["hit"].mean(),
                    "d_base": d, "t_base": t, "p": p, "d_gross": dg, "t_gross": tg, "cost_r": r["cost"].mean(), "d_random": dr, "t_random": tr_, "d_wait": dw, "t_wait": tw,
                    "h1": halves[0], "h2": halves[1], "rejected_net": rejected["net"].mean(),
                    "delay": r["delay"].mean(),
                })
    return pd.DataFrame(out)


def learned(universe: str) -> None:
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import roc_auc_score

    rows = pd.read_pickle(OUT / f"{universe}.pkl.gz")
    feats = pd.read_pickle(OUT / f"{universe}.features.pkl.gz")
    base = rows[(rows["rule"] == "htf_close") & (rows["stop"] == "htf")]
    k1 = base[base["k"] == 1][["sid", "pair", "family", "feed", "time", "rollover", "hit", "net"]]
    k2 = base[base["k"] == 2][["sid", "pair", "net"]].rename(columns={"net": "net2"})
    d = k1.merge(k2, on=["sid", "pair"]).merge(feats, on=["sid", "pair"])
    if len(d) < 500:
        return
    d = d[~((d["family"] == "fx") & d["rollover"])]
    d["pair_code"] = d["pair"].astype("category").cat.codes
    cols = [*FEATURES, "pair_code"]
    cut = d["time"].quantile(0.6)
    tr, te = d[d["time"] < cut], d[d["time"] >= cut]
    model = HistGradientBoostingClassifier(max_depth=3, max_iter=200, learning_rate=0.05, min_samples_leaf=100)
    model.fit(tr[cols], tr["hit"].astype(int))
    ptr, pte = model.predict_proba(tr[cols])[:, 1], model.predict_proba(te[cols])[:, 1]
    print(f"\n  LEARNED CONFIRMER ({universe}): trained on {len(tr):,} signal x pair, scored on {len(te):,}")
    for fam, g in [("all", te), *list(te.groupby("family", observed=True))]:
        if len(g) < 200 or g["hit"].nunique() < 2:
            continue
        p = pte[te.index.get_indexer(g.index)]
        print(f"    {str(fam):10s} AUC {roc_auc_score(g['hit'].astype(int), p):.3f} | base 1R hit {g['hit'].mean():.1%}"
              f" | net R k=1 {g['net'].mean():+.3f} k=2 {g['net2'].mean():+.3f}")
        for top in (0.5, 0.3, 0.1):
            thr = np.quantile(ptr, 1 - top)
            m = p >= thr
            sub = g[m]
            if len(sub) < 30:
                continue
            dd, tt, _ = diff(sub.assign(net=sub["net"]), g)
            print(f"      top {top:.0%}: pass {m.mean():.1%} | net R k=1 {sub['net'].mean():+.3f}"
                  f" (vs all {dd:+.3f}, t {tt:+.1f}) | k=2 {sub['net2'].mean():+.3f} | 1R hit {sub['hit'].mean():.1%}")
    for pair, g in te.groupby("pair", observed=True):
        p = pte[te.index.get_indexer(g.index)]
        if g["hit"].nunique() == 2 and len(g) > 200:
            print(f"      pair {pair:7s} AUC {roc_auc_score(g['hit'].astype(int), p):.3f} (n {len(g):,})")


def report() -> None:
    # Every pickle read here was written by `run` above, on the lab, not taken from elsewhere.
    frames = {u: pd.read_pickle(p) for u in ("real", "deriv", "walks")
              if (p := OUT / f"{u}.pkl.gz").exists()}
    allc = []
    for u, df in frames.items():
        c = cells(df)
        c["universe"] = u
        allc.append(c)
    res = pd.concat(allc, ignore_index=True)
    walks = res[res["universe"] == "walks"].set_index(["pair", "stop", "k", "rule"])
    market = res["universe"] != "walks"
    res["q"] = np.nan
    res.loc[market, "q"] = bh(res.loc[market, "p"].to_numpy())
    wd, wg = [], []
    for _, r in res.iterrows():
        key = (r["pair"], r["stop"], r["k"], r["rule"])
        wd.append(walks.loc[key, "d_base"] if key in walks.index else np.nan)
        wg.append(walks.loc[key, "d_gross"] if key in walks.index else np.nan)
    res["walk_d"], res["walk_gross"] = wd, wg
    res["did"] = res["d_base"] - res["walk_d"]
    # Added after the first full run, before this rerun: the mechanical gain of a later entry
    # (more risk against a level-anchored stop, so a fixed cost is fewer R) scales with the cost,
    # and the walks are charged 0.15 against FX's 0.8. So a cell must also beat the walks gross.
    res["did_gross"] = res["d_gross"] - res["walk_gross"]
    res["passes"] = (market & (res["d_base"] >= 0.05) & (res["t_base"] >= 3) & (res["q"] < 0.05)
                     & (res["d_random"] > 0) & (res["h1"] > 0) & (res["h2"] > 0) & (res["did"] >= 0.05)
                     & (res["did_gross"] >= 0.05) & (res["t_gross"] >= 3))
    res.to_csv(OUT / "results.csv", index=False)
    print(f"cells: {len(res):,} ({int(market.sum()):,} market); results in {OUT / 'results.csv'}")
    print(f"PASSING the pre-registered bar: {int(res['passes'].sum())}")
    if res["passes"].any():
        print(res[res["passes"]].sort_values("did", ascending=False).to_string(max_rows=60))
    for u in frames:
        print(f"\n===== {u}: baselines (stop htf, k=1 and k=2) =====")
        b = res[(res["universe"] == u) & res["rule"].isin(["htf_close", "ltf_touch"])]
        print(b[["view", "pair", "stop", "k", "rule", "n", "net", "stop_rate", "then_right", "hit", "d_base", "t_base"]]
              .sort_values(["view", "pair", "stop", "k", "rule"]).to_string(index=False, float_format="%.3f"))
    for u in ("real", "deriv"):
        if u not in frames:
            continue
        print(f"\n===== {u}: top gates by difference-in-differences against walks (stop htf, k=1) =====")
        g = res[(res["universe"] == u) & (res["stop"] == "htf") & (res["k"] == 1)
                & ~res["rule"].isin(["htf_close", "ltf_touch"])]
        for (view, pair), c in g.groupby(["view", "pair"]):
            top = c.sort_values("did", ascending=False).head(5)
            print(f"\n  {view} {pair}")
            print(top[["rule", "pass", "n", "net", "stop_rate", "then_right", "d_base", "t_base", "q", "d_random",
                       "d_wait", "h1", "h2", "walk_d", "did", "d_gross", "t_gross", "did_gross", "cost_r"]].to_string(index=False, float_format="%.3f"))
        t3 = g[(g["t_base"] >= 3)]
        print(f"\n  cells with t >= 3 against htf_close: {len(t3)} of {len(g)}; with q < 0.05: {int((g['q'] < 0.05).sum())}")
    for u in frames:
        learned(u)


if __name__ == "__main__":
    report() if PART == "report" else run()
