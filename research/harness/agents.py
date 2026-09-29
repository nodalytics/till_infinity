"""Specialist small-LLM agents, weighed into one decision: do they know anything a model on the same
inputs does not?

The design asked for: small local models (qwen2.5:7b-instruct), each a specialist - a chart reader, a
macro analyst, a positioning analyst - whose opinions are weighed into a decision. The same shape as
ATLAS (`research/docs/atlas.md`), which could not show skill: its LLM backtest ran over years the
model had read about, and its weighting was a bounded random walk on a noisy score.

This design avoids both.
  - The test window, January 2025 to September 2026, is after Qwen2.5's training data, so no outcome
    can be recalled. The chart agent is also anonymised: prices as % from the last close, with no
    symbol and no date.
  - Every agent answers with a probability, P(the pair closes higher tomorrow), as JSON at
    temperature 0, and is scored like any forecaster: AUC, and Brier and log-loss skill against the
    base rate.
  - The decisive control is a plain logistic regression on the same numbers the agents were
    shown. If the LLM cannot beat it, the language model adds nothing to its inputs.
  - A second control runs the chart agent on Deriv random walks, disguised identically; its AUC
    must be 0.5.

Agents, per pair per trading day (decision at the daily close, scored on the next day's close):
  chart        the last 30 daily bars (O/H/L/C as % from the last close), distance from the 20/50-day
               means in daily sigmas, RSI(14), and the distance to the 20-day high and low
  macro        the pair's two currencies: every medium/high-importance release in the last 7 days
               with actual, forecast, previous and the surprise's sign; and the releases scheduled
               tomorrow with their forecasts (no actuals)
  positioning  CFTC speculators (legacy non-commercial) and leveraged funds (TFF) net positioning in
               each non-USD currency's future: level as a z-score against 3 years, and the 4-week change
The weighing:
  equal     the mean of the three probabilities
  hedge     multiplicative weights on each agent's running log loss, causal
  stacked   a logistic regression on the three probabilities, fit on the first half, scored on
            the second

PART=pilot runs January 2025 only. PART=run runs everything. Responses are cached in
calls.jsonl, so a run can resume. PART=score scores the cache.
The model runs in the lab's Ollama container at 16 threads, one request at a time, so the MT5
tunnel on the same machine keeps its cores.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import spikerisk

OUT = Path(os.environ.get("OUT", ".data/agents"))
CAL = Path(os.environ.get("CALENDAR", ".data/surprise/calendar.jsonl"))
COT = Path(os.environ.get("COT", ".data/crowding/cftc.csv.gz"))
OLLAMA = os.environ.get("OLLAMA", "http://172.22.0.4:11434")
MODEL = os.environ.get("MODEL", "qwen2.5:7b-instruct")
PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD"]
CONTROL = ["Volatility_10_Index", "Volatility_25_Index", "Volatility_50_Index", "Volatility_75_Index"]
COT_KEY = {"EUR": "EURO FX - ", "JPY": "JAPANESE YEN - ", "GBP": "BRITISH POUND", "AUD": "AUSTRALIAN DOLLAR - ",
           "CAD": "CANADIAN DOLLAR - ", "CHF": "SWISS FRANC - ", "NZD": "NEW ZEALAND DOLLAR"}
START, END = pd.Timestamp("2025-01-02", tz="UTC"), pd.Timestamp("2026-09-10", tz="UTC")

SYSTEM = {
    "chart": "You are a veteran technical analyst. You read price action, trend, momentum, support and resistance. "
             "You are shown one anonymous market's recent daily bars. Estimate the probability that the next daily close is "
             "higher than the last close. Be calibrated: 0.5 means no edge; move away from 0.5 only as far as the evidence supports.",
    "macro": "You are a macro FX strategist. You judge currencies by economic surprises, central-bank expectations, inflation and "
             "growth - markets move on the gap between expectations and reality. Estimate the probability that the currency pair "
             "closes higher tomorrow than today (the base currency strengthens against the quote). Be calibrated: 0.5 means no edge.",
    "positioning": "You are a positioning analyst. You read CFTC Commitments of Traders data: speculator and leveraged-fund net "
                   "positioning, how extreme it is, and how it is changing. Crowded trades can unwind; fresh flows can extend. "
                   "Estimate the probability that the currency pair closes higher tomorrow. Be calibrated: 0.5 means no edge.",
}
ASK = 'Reply with only JSON: {"p_up": <number between 0 and 1>, "why": "<at most 15 words>"}'


def ask(agent, text):
    body = {"model": MODEL, "system": SYSTEM[agent], "prompt": text + "\n\n" + ASK, "stream": False, "format": "json",
            "options": {"num_thread": 16, "temperature": 0, "num_predict": 60, "seed": 7}}
    req = urllib.request.Request(f"{OLLAMA}/api/generate", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    for attempt in range(4):
        try:
            d = json.load(urllib.request.urlopen(req, timeout=300))
            got = json.loads(d["response"])
            p = float(got.get("p_up"))
            return (min(max(p, 0.0), 1.0) if np.isfinite(p) else np.nan), str(got.get("why", ""))[:120]
        except Exception as exc:  # malformed JSON or a transient failure: retry, then record as missing
            err = str(exc)[:80]
            time.sleep(2 * (attempt + 1))
    return np.nan, f"error: {err}"


# ---------------------------------------------------------------------------------------------- inputs

def daily(sym):
    df = spikerisk.load(None, sym, "SEQLAB", "1d")
    df = df.assign(day=pd.to_datetime(df["ts"].to_numpy(), unit="s", utc=True).floor("1D"))
    return df.drop_duplicates("day").set_index("day")


def chart_text(df, i):
    w = df.iloc[i - 29:i + 1]
    last = w["close"].iloc[-1]
    rows = [f"{(o / last - 1) * 100:+.2f} {(h / last - 1) * 100:+.2f} {(lo / last - 1) * 100:+.2f} {(c / last - 1) * 100:+.2f}"
            for o, h, lo, c in zip(w["open"], w["high"], w["low"], w["close"])]
    c = df["close"].iloc[:i + 1]
    r = np.log(c).diff()
    sd = r.iloc[-60:].std()
    ma20, ma50 = c.iloc[-20:].mean(), c.iloc[-50:].mean()
    up, dn = r.clip(lower=0).iloc[-14:].mean(), (-r.clip(upper=0)).iloc[-14:].mean()
    rsi = 100 - 100 / (1 + up / dn) if dn > 0 else 100.0
    hi20, lo20 = df["high"].iloc[i - 19:i + 1].max(), df["low"].iloc[i - 19:i + 1].min()
    feats = dict(ma20=np.log(last / ma20) / sd, ma50=np.log(last / ma50) / sd, rsi=rsi,
                 hi20=np.log(hi20 / last) / sd, lo20=np.log(last / lo20) / sd, r1=r.iloc[-1] / sd, r5=r.iloc[-5:].sum() / sd)
    text = ("Last 30 daily bars, oldest first, each as open high low close in % from the last close:\n" + "\n".join(rows) +
            f"\n\nDistance from 20-day mean: {feats['ma20']:+.2f} daily sigmas; from 50-day mean: {feats['ma50']:+.2f}. "
            f"RSI(14): {rsi:.0f}. 20-day high is {feats['hi20']:.2f} sigmas above, 20-day low {feats['lo20']:.2f} sigmas below.")
    return text, feats


def macro_text(cal, pair, day):
    base, quote = pair[:3], pair[3:]
    past = cal[(cal["t"] < day + pd.Timedelta("21h")) & (cal["t"] >= day - pd.Timedelta("7D")) & cal["currency"].isin([base, quote])]
    nxt = cal[(cal["t"] >= day + pd.Timedelta("21h")) & (cal["t"] < day + pd.Timedelta("45h")) & cal["currency"].isin([base, quote])]
    lines = [f"Pair {pair}: base {base}, quote {quote}.", "Releases in the last 7 days (currency, title, actual, forecast, previous, surprise):"]
    zsum = {base: 0.0, quote: 0.0}
    for _, e in past.tail(25).iterrows():
        s = "n/a"
        if pd.notna(e["actual"]) and pd.notna(e["forecast"]):
            diff = float(e["actual"]) - float(e["forecast"])
            s = "above forecast" if diff > 0 else "below forecast" if diff < 0 else "in line"
            zsum[e["currency"]] += np.sign(diff) * (-1 if any(w in e["title"].lower() for w in ("unemployment", "jobless", "claimant")) else 1)
        lines.append(f"- {e['currency']} {e['title']}: {e['actual']} vs {e['forecast']} (prev {e['previous']}) {s}")
    lines.append("Scheduled tomorrow (forecast, previous):")
    for _, e in nxt.head(15).iterrows():
        lines.append(f"- {e['currency']} {e['title']}: forecast {e['forecast']}, previous {e['previous']}")
    return "\n".join(lines), dict(surprise_base=zsum[base], surprise_quote=zsum[quote])


def cot_series(cot):
    out = {}
    for ccy, key in COT_KEY.items():
        for rep in ("legacy", "tff"):
            m = cot[(cot["report"] == rep) & cot["market"].str.upper().str.contains(key.upper(), regex=False)
                    & ~cot["market"].str.upper().str.contains("XRATE|/", regex=True)].sort_values("date").drop_duplicates("date")
            net = (m["long"] - m["short"]) / m["oi"]
            z = (net - net.rolling(156, min_periods=52).mean().shift(1)) / net.rolling(156, min_periods=52).std().shift(1)
            out[(ccy, rep)] = pd.DataFrame({"public": pd.to_datetime(m["date"]).dt.tz_localize("UTC") + pd.Timedelta(days=3, hours=21),
                                            "net": net.to_numpy(), "z": z.to_numpy(), "chg4": net.diff(4).to_numpy()})
    return out


def positioning_text(cots, pair, day):
    lines, feats = [f"Pair {pair}. CFTC futures positioning, net long as a share of open interest (latest public report):"], {}
    for ccy in (pair[:3], pair[3:]):
        if ccy == "USD":
            continue
        for rep, lab in (("legacy", "speculators (non-commercial)"), ("tff", "leveraged funds")):
            s = cots[(ccy, rep)]
            s = s[s["public"] <= day + pd.Timedelta("21h")]
            if not len(s) or not np.isfinite(s["z"].iloc[-1]):
                continue
            row = s.iloc[-1]
            lines.append(f"- {ccy} {lab}: net {row['net']:+.1%} of open interest, {row['z']:+.1f} sd vs 3 years, "
                         f"4-week change {row['chg4']:+.1%}")
            feats[f"{rep}_z"] = row["z"] * (1 if ccy == pair[:3] else -1)
    lines.append(f"(A long position in a {pair[3:] if pair[:3] == 'USD' else pair[:3]} future is "
                 f"{'bearish' if pair[:3] == 'USD' else 'bullish'} for {pair}.)")
    return "\n".join(lines), feats


# ---------------------------------------------------------------------------------------------- run

def run(start, end):
    OUT.mkdir(parents=True, exist_ok=True)
    cache_path = OUT / "calls.jsonl"
    done = set()
    if cache_path.exists():
        for line in cache_path.open():
            r = json.loads(line)
            done.add((r["sym"], r["day"], r["agent"]))
    cal = pd.DataFrame([json.loads(x) for x in CAL.open()])
    cal["t"] = pd.to_datetime(cal["date"], utc=True)
    cal = cal[cal["importance"] >= 0].sort_values("t")
    cots = cot_series(pd.read_csv(COT))
    jobs = [(s, "real") for s in PAIRS] + [(s, "control") for s in CONTROL]
    with cache_path.open("a") as fh:
        for sym, kind in jobs:
            df = daily(sym)
            idx = [i for i, d in enumerate(df.index) if start <= d <= end and i >= 60 and i + 1 < len(df)]
            if kind == "control":
                idx = idx[::3]  # a third of the days is enough to show a random walk reads as 0.5
            for i in idx:
                day = df.index[i]
                nxt = float(np.log(df["close"].iloc[i + 1] / df["close"].iloc[i]))
                tasks = {"chart": chart_text(df, i)}
                if kind == "real":
                    tasks["macro"] = macro_text(cal, sym, day)
                    tasks["positioning"] = positioning_text(cots, sym, day)
                for agent, (text, feats) in tasks.items():
                    key = (sym, str(day.date()), agent)
                    if key in done:
                        continue
                    p, why = ask(agent, text)
                    fh.write(json.dumps({"sym": sym, "kind": kind, "day": str(day.date()), "agent": agent, "p": p,
                                         "why": why, "next": nxt, **{f"f_{k}": float(v) for k, v in feats.items()}}) + "\n")
                    fh.flush()
            print(f"{sym}: {len(idx)} days", flush=True)


# ---------------------------------------------------------------------------------------------- score

def score():
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    rows = [json.loads(x) for x in (OUT / "calls.jsonl").open()]
    d = pd.DataFrame(rows)
    print(f"\n{'=' * 110}\nAGENTS ({MODEL}) - {len(d):,} calls, {d['p'].isna().mean():.1%} unparseable")
    print("  answer distribution per agent (share exactly 0.5, quartiles):")
    for a, g in d.groupby(["kind", "agent"]):
        p = g["p"].dropna()
        print(f"    {a[0]:<8} {a[1]:<12} n={len(p):>5} at 0.5 {np.mean(p == 0.5):.0%} quartiles "
              f"{np.quantile(p, 0.25):.2f} / {np.median(p):.2f} / {np.quantile(p, 0.75):.2f}")
    real = d[d["kind"] == "real"]
    wide = real.pivot_table(index=["sym", "day"], columns="agent", values="p").reset_index()
    info = real.drop_duplicates(["sym", "day"]).set_index(["sym", "day"])
    wide = wide.join(info[["next"] + [c for c in real.columns if c.startswith("f_")]], on=["sym", "day"])
    wide = wide.dropna(subset=["chart", "macro", "positioning"]).sort_values("day").reset_index(drop=True)
    y = (wide["next"] > 0).to_numpy(float)
    half = (wide["day"] >= wide["day"].iloc[len(wide) // 2]).to_numpy()
    base = y[~half].mean()

    def line(name, p, mask=half):
        p = np.clip(np.asarray(p, float)[mask], 1e-4, 1 - 1e-4)
        yy = y[mask]
        b, b0 = np.mean((p - yy) ** 2), np.mean((base - yy) ** 2)
        auc = roc_auc_score(yy, p) if np.std(p) > 0 else 0.5
        side = np.where(p > 0.55, 1, np.where(p < 0.45, -1, 0))
        r = side * wide["next"].to_numpy()[mask] * 1e4
        cost = 1.0  # bp round trip on a daily FX position, roughly; the answer does not turn on it
        traded = side != 0
        tr = f"traded {traded.mean():.0%} of days, net {np.mean(r[traded] - cost) if traded.any() else float('nan'):+.1f}bp"
        print(f"    {name:<26} AUC {auc:.3f} | Brier skill {1 - b / b0:+.4f} | {tr}")

    print(f"\n  real pairs, second half (n={half.sum():,}); the stacker and the no-LLM logistic are fit on the first half")
    for a in ("chart", "macro", "positioning"):
        line(f"agent {a}", wide[a])
    line("equal weights", wide[["chart", "macro", "positioning"]].mean(1))
    # hedge: weights on running log loss, causal
    P = wide[["chart", "macro", "positioning"]].to_numpy()
    w = np.ones(3) / 3
    hedge = np.empty(len(wide))
    for i in range(len(wide)):
        hedge[i] = w @ P[i]
        loss = -(y[i] * np.log(np.clip(P[i], 1e-4, 1)) + (1 - y[i]) * np.log(np.clip(1 - P[i], 1e-4, 1)))
        w = w * np.exp(-0.5 * loss)
        w /= w.sum()
    line("hedge weights", hedge)
    X = wide[["chart", "macro", "positioning"]].to_numpy()
    st = LogisticRegression().fit(X[~half], y[~half])
    line("stacked", st.predict_proba(X)[:, 1])
    fc = [c for c in wide.columns if c.startswith("f_")]
    Xf = wide[fc].fillna(0.0).to_numpy()
    lr = LogisticRegression(max_iter=1000).fit(Xf[~half], y[~half])
    line("NO-LLM logistic, same inputs", lr.predict_proba(Xf)[:, 1])
    ctl = d[(d["kind"] == "control") & d["p"].notna()]
    if len(ctl) > 50:
        yc = (ctl["next"] > 0).to_numpy(float)
        print(f"\n  control: chart agent on disguised random walks, n={len(ctl)}: AUC "
              f"{roc_auc_score(yc, ctl['p']) if ctl['p'].std() > 0 else 0.5:.3f}")


if __name__ == "__main__":
    part = os.environ.get("PART", "pilot")
    if part == "pilot":
        run(START, pd.Timestamp("2025-01-31", tz="UTC"))
    elif part == "run":
        run(START, END)
    score() if part in ("score", "pilot", "run") else None
