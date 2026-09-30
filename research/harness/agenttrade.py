"""Agents that trade structures signals: does a small LLM, shown the card, choose better than chance?

The desk's request: "test agents for trading: agents do the trading based on the signals, not
deterministic rules". `agents.md` found specialist agents forecasting tomorrow's close have no skill
and answer like fixed priors. This asks the other form: an agent that sees each **structures
signal** as a trader would - the card - and decides whether to take it, which way and how big.

Signals: every zone touch the production `Engine` opens, replayed over the lab's bars as
`indicators.py` does (15m and 1h), from `START`. At the touch the harness records what production
would put on the card, read off the engine itself:

  the level     price, side of arrival, its record on that side (hold rate, symmetric rate,
                touches), and the engine's own P(up) and edge
  the envelope  P10 / P50 / P90 of the next 5 bars (`Engine._envelope_at`), as % from price
  shocks        P(a shock within a few bars) and its lift (`Engine._shock_at`), where the model
                has a reading
  ZMA           the z-score, its threshold, and whether it is stretched (`_zma_context`)
  the clock     the hour's volatility multiple (`Engine._clock_at`)
  price action  the last 20 closes as % from the last close
  the family    fx / metals / crypto / deriv (walks are presented as an unnamed index)

The agent (qwen2.5:7b-instruct, temperature 0, JSON) answers take or skip, fade or break,
confidence 0-1 and a size tier. Two prompts, a neutral trader and a risk-first trader, are each
given half the signals. Half of each half is anonymised: no instrument and no date (the family and
the numbers stay).

Settlement: every signal is settled both ways at the touch's close, so taken and skipped trades
and every null share one ledger. The stop is anchored to the level, as `stophunt.py`'s is:
  fade  stop 1 bar-vol beyond the level
  break stop 1 bar-vol back on the level's other side
R is the risk from the entry to that stop; targets are 1R and 2R; 40-bar limit; a bar touching
both counts as stopped; costs `indicators.COST_V` scaled to the interval, in R. Entries risking
under 0.25 bar-vol are dropped (as `stophunt.py`). (This is `stophunt.py`'s level-anchored
simulation rather than `shared.replay.walk`, whose stop is placed from the entry: the question is a
structure trade, and its geometry is the one the other structure studies used.)

Nulls, per prompt:
  random selection  the expected R of a random subset of the same signals at the agent's take
                    rate, with the agent's own fade/break mix (computed exactly, not sampled)
  random direction  the agent's taken signals with fade/break drawn at its mix
  deterministic     every signal, faded
  walks             the same agent on walks we generate, presented identically
  Deriv             a market of its own

Pre-registered pass: an agent's taken trades beat random selection at the same rate by >= 0.05R
**gross** at k = 1, with t >= 3 (days resampled), in both halves of time, and the walks show no such
gain. Confidence must also sort outcomes (calibration) for the confidence to be usable.

Run on the lab:
  PART=zones UNIVERSE=real|deriv|walks START=2025-09-01 ...   (engine replay, in parallel)
  PART=ask   (samples ~3,000 signals stratified by family and interval; cached, resumable)
  PART=report
"""
from __future__ import annotations

import heapq
import json
import os
import random
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import indicators as ind
from stophunt import LIMIT, MIN_R, simulate

from till_infinity.structures.engine import Engine, _zma_context

PART = os.environ.get("PART", "zones")
UNIVERSE = os.environ.get("UNIVERSE", "real")
OUT = Path(os.environ.get("OUT", ".data/agenttrade"))
OLLAMA = os.environ.get("OLLAMA", "http://172.22.0.4:11434")
MODEL = os.environ.get("MODEL", "qwen2.5:7b-instruct")
SAMPLE = int(os.environ.get("SAMPLE", "3000"))
BUFFER = 1.0
TARGETS = (1, 2)

SYSTEM = {
    "trader": (
        "You are a discretionary trader on a small desk. A level-detection system has flagged that "
        "price is touching a level. Decide whether to take the trade, which way (fade the level or "
        "trade its break), how confident you are, and how big to go. Judge from the numbers shown."
    ),
    "risk": (
        "You are a risk-first trader on a small desk. Most trades lose after costs; your job is to "
        "take only trades whose evidence is clearly good, and to skip the rest. A level-detection "
        "system has flagged that price is touching a level. Decide whether to take it, which way "
        "(fade or break), how confident you are, and how big to go. Judge from the numbers shown."
    ),
}
ASK = ('Reply with only JSON: {"take": true or false, "direction": "fade" or "break", '
       '"confidence": <0 to 1>, "size": "small" or "normal" or "large"}')


# ---------------------------------------------------------------------------------------- zones

def _pct(x: float | None, ref: float) -> float | None:
    return None if not x or not ref else round((x / ref - 1) * 100, 3)


def zones() -> None:
    frames = {}
    for sym in ind.SYMBOLS[UNIVERSE]:
        for iv in ind.INTERVALS:
            df = ind.frame(sym, iv)
            if df is not None and len(df) > 2 * ind.SWING:
                frames[(sym, iv)] = df
    print(f"{UNIVERSE}: {len(frames)} series", flush=True)
    engine = Engine(intervals=ind.INTERVALS)
    engine.consensus.single_source = frozenset(s.lower() for s, _ in frames)
    stream = heapq.merge(*(ind.bars_of(s, iv, df) for (s, iv), df in frames.items()),
                         key=lambda b: (b["time"], b["interval"]))
    cards, seen = [], set()
    for n, bar in enumerate(stream):
        for call in engine.observe_bar(bar):
            touch = engine.tracker.open_touch(call.level)
            if touch is None or touch.started != call.time:
                continue
            k = (call.feed, call.interval, round(touch.level_price, 8), touch.started)
            if k in seen:
                continue
            seen.add(k)
            side = touch.features.side
            stats = call.level.stats(side)
            price = float(bar["close"])
            inf = call.inference
            card = {
                "feed": call.feed, "interval": call.interval, "time": int(call.time),
                "level": float(touch.level_price), "above": side.name == "ABOVE", "price": price,
                "hold_rate": round(stats.hold_rate, 3), "sym_hold_rate": round(stats.sym_hold_rate, 3),
                "touches": round(stats.touches, 1),
                "p_up": round(float(inf.probability_up), 3), "edge": round(float(inf.edge or 0.0), 3),
            }
            try:
                env = engine._envelope_at(call.feed, bar["interval"], price)
                card.update({f"env_{q}": _pct(env.get(f"env5_{q}"), price) for q in ("p10", "p50", "p90")})
            except Exception:
                pass
            try:
                card.update({k2: round(v, 3) for k2, v in engine._shock_at(call.feed, bar["interval"]).items()})
            except Exception:
                pass
            try:
                card.update({k2: round(float(v), 3) for k2, v in
                             _zma_context(engine.zma.of(call.feed, bar["interval"])).items()
                             if k2 in ("zma_z", "zma_strong", "zma_stretched")})
            except Exception:
                pass
            try:
                card.update(engine._clock_at(call.feed, bar["interval"], float(call.time)))
            except Exception:
                pass
            cards.append(card)
        if n % 50_000 == 0:
            print(f"  {n:,} bars, {len(cards):,} touches", flush=True)
    settle(frames, cards)


def settle(frames: dict, cards: list[dict]) -> None:
    """Both directions at k = 1, 2, net and gross, plus the last 20 closes for the card."""
    arrays = {}
    for (sym, iv), df in frames.items():
        x = ind.indicators(df)
        arrays[(sym.lower(), iv)] = (x, df["high"].to_numpy(), df["low"].to_numpy(), df["ts"].to_numpy())
    fam_of = {s.lower(): ind.FAMILY.get(s, "walks") for s, _ in frames}
    out = []
    for z in cards:
        options = [z["interval"]] if z["interval"] in ind.MINUTES else list(ind.INTERVALS)
        for iv in options:
            key = (z["feed"], iv)
            if key not in arrays:
                continue
            x, h, lo, ts = arrays[key]
            i = int(np.searchsorted(ts, z["time"]))
            if not (i < len(ts) and ts[i] == z["time"] and i >= ind.SWING and i + LIMIT < len(ts)):
                continue
            c, v = x["close"], x["vol"][i]
            if not np.isfinite(v) or v <= 0:
                break
            s_fade = 1 if z["above"] else -1
            row = {**z, "bar_interval": iv, "family": fam_of[z["feed"]],
                   "recent": [round((c[m] / c[i] - 1) * 100, 3) for m in range(i - 19, i + 1)]}
            ok = True
            for name, s in (("fade", s_fade), ("break", -s_fade)):
                stop = z["level"] - s * BUFFER * v * c[i] if name == "fade" else z["level"] + s_fade * BUFFER * v * c[i]
                risk = s * (c[i] - stop)
                if not risk > MIN_R * v * c[i]:
                    ok = False
                    break
                got = simulate(h, lo, c, i, s, stop, risk)
                if got is None:
                    ok = False
                    break
                cost_r = ind.COST_V[row["family"]] * np.sqrt(5 / ind.MINUTES[iv]) * v * c[i] / risk
                for k, r, _stopped, _tr, _hit in got:
                    if k in TARGETS:
                        row[f"{name}_g{k}"] = round(r, 4)
                        row[f"{name}_n{k}"] = round(r - cost_r, 4)
            if ok:
                out.append(row)
            break
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{UNIVERSE}.cards.json").write_text(json.dumps(out))
    print(f"{UNIVERSE}: {len(out):,} settled cards written", flush=True)


# ---------------------------------------------------------------------------------------- ask

def card_text(c: dict, anonymous: bool) -> str:
    fam = {"walks": "index"}.get(c["family"], c["family"])
    who = (f"instrument: an unnamed {fam} instrument" if anonymous or c["family"] == "walks"
           else f"instrument: {c['feed'].upper()} ({fam}), {pd.Timestamp(c['time'], unit='s'):%Y-%m-%d %H:%M} UTC")
    arrived = "from above (price fell onto it)" if c["above"] else "from below (price rose onto it)"
    lines = [
        who,
        f"timeframe: {c['interval']}",
        f"level: {(c['level'] / c['price'] - 1) * 100:+.3f}% from price, touched {arrived}",
        f"level record on this side: hold rate {c['hold_rate']:.0%}, symmetric hold rate "
        f"{c['sym_hold_rate']:.0%}, {c['touches']:.0f} past touches",
        f"model: P(up) {c['p_up']:.2f}, edge {c['edge']:+.2f}",
    ]
    if c.get("env_p10") is not None:
        lines.append(f"next 5 bars envelope: P10 {c['env_p10']:+.2f}% / P50 {c['env_p50']:+.2f}% / "
                     f"P90 {c['env_p90']:+.2f}%")
    if c.get("shock_probability") is not None:
        lines.append(f"chance of a shock bar soon: {c['shock_probability']:.0%} "
                     f"({c.get('shock_lift', 1):.1f}x normal)")
    if c.get("zma_z") is not None:
        state = ("stretched down" if c["zma_z"] < -c["zma_strong"] else
                 "stretched up" if c["zma_z"] > c["zma_strong"] else "inside its band")
        lines.append(f"z-score around the moving average: {c['zma_z']:+.2f} ({state})")
    if c.get("vol_clock") is not None:
        lines.append(f"this hour's volatility: {c['vol_clock']:.1f}x average")
    lines.append("last 20 closes, % from the last close: " + " ".join(f"{r:+.2f}" for r in c["recent"]))
    lines.append("fade = trade back away from the level; break = trade through it. "
                 "The stop sits one bar-volatility on the far side.")
    return "\n".join(lines)


def ask(prompt: str, text: str) -> dict:
    body = {"model": MODEL, "system": SYSTEM[prompt], "prompt": text + "\n\n" + ASK, "stream": False,
            "format": "json", "options": {"num_thread": 16, "temperature": 0, "num_predict": 60, "seed": 7}}
    req = urllib.request.Request(f"{OLLAMA}/api/generate", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    err = ""
    for attempt in range(4):
        try:
            d = json.load(urllib.request.urlopen(req, timeout=300))
            got = json.loads(d["response"])
            take = got.get("take")
            take = take if isinstance(take, bool) else str(take).lower() == "true"
            direction = str(got.get("direction", "")).lower()
            conf = float(got.get("confidence"))
            return {"take": take, "direction": "break" if direction == "break" else "fade",
                    "confidence": min(max(conf, 0.0), 1.0) if np.isfinite(conf) else None,
                    "size": str(got.get("size", "")).lower()[:10], "ok": True}
        except Exception as exc:
            err = str(exc)[:80]
            time.sleep(2 * (attempt + 1))
    return {"ok": False, "error": err}


def sample() -> list[dict]:
    """~SAMPLE cards stratified by family and interval: 60% real, 20% deriv, 20% walks."""
    rng = random.Random(3)
    picked = []
    shares = {"real": 0.6, "deriv": 0.2, "walks": 0.2}
    for universe, share in shares.items():
        path = OUT / f"{universe}.cards.json"
        if not path.exists():
            continue
        cards = json.loads(path.read_text())
        strata: dict[tuple, list] = {}
        for c in cards:
            strata.setdefault((c["family"], c["bar_interval"]), []).append(c)
        want = int(SAMPLE * share)
        per = max(1, want // max(len(strata), 1))
        for key in sorted(strata):
            got = strata[key]
            picked += rng.sample(got, min(per, len(got)))
    rng.shuffle(picked)
    for n, c in enumerate(picked):
        c["prompt"] = "trader" if n % 2 == 0 else "risk"
        c["anonymous"] = (n // 2) % 2 == 1
        c["id"] = f"{c['feed']}|{c['bar_interval']}|{c['time']}|{c['level']}"
    return picked


def run_ask() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cache = OUT / "calls.jsonl"
    done = set()
    if cache.exists():
        done = {json.loads(x)["id"] for x in cache.open()}
    todo = [c for c in sample() if c["id"] not in done]
    print(f"{len(done):,} cached, {len(todo):,} to ask", flush=True)
    t0 = time.time()
    with cache.open("a") as fh:
        for n, c in enumerate(todo, 1):
            got = ask(c["prompt"], card_text(c, c["anonymous"]))
            fh.write(json.dumps({**c, **got}) + "\n")
            fh.flush()
            if n % 50 == 0:
                rate = n / (time.time() - t0) * 3600
                print(f"  {n:,}/{len(todo):,} asked, {rate:.0f}/h", flush=True)


# ---------------------------------------------------------------------------------------- report

def _boot_t(values: np.ndarray, days: np.ndarray, n: int = 1000, seed: int = 0):
    ok = np.isfinite(values)
    values, days = values[ok], days[ok]
    if len(values) < 10:
        return float("nan"), float("nan")
    uniq = np.unique(days)
    idx = {d: np.flatnonzero(days == d) for d in uniq}
    rng = np.random.default_rng(seed)
    means = [values[np.concatenate([idx[d] for d in rng.choice(uniq, len(uniq))])].mean() for _ in range(n)]
    se = float(np.std(means))
    return float(values.mean()), float(values.mean() / se) if se > 0 else float("nan")


def report() -> None:
    d = pd.DataFrame([json.loads(x) for x in (OUT / "calls.jsonl").open()])
    d = d[d["ok"] == True].copy()  # noqa: E712
    d["group"] = np.where(d["family"] == "walks", "walks", np.where(d["family"] == "deriv", "deriv", "real"))
    d["day"] = (d["time"] // 86_400).astype(int)
    cut = d["time"].median()
    print(f"AGENT TRADING ({MODEL}): {len(d):,} answered cards")
    print("fade/break R in bar-vol-anchored R; k = target in R; gross before costs, net after\n")
    for (prompt, group), g in d.groupby(["prompt", "group"]):
        taken = g[g["take"]]
        rate = len(taken) / len(g)
        mix_break = (taken["direction"] == "break").mean() if len(taken) else 0.0
        print(f"== prompt {prompt} · {group} · cards {len(g):,} · take rate {rate:.1%} · break share "
              f"{mix_break:.1%} · anonymous take rate {g[g['anonymous']]['take'].mean():.1%} vs named "
              f"{g[~g['anonymous']]['take'].mean():.1%}")
        for k in TARGETS:
            for kind in ("g", "n"):
                chosen = np.where(taken["direction"] == "break", taken[f"break_{kind}{k}"], taken[f"fade_{kind}{k}"])
                # random selection at the same rate and mix: its expectation over all cards
                expect = (1 - mix_break) * g[f"fade_{kind}{k}"] + mix_break * g[f"break_{kind}{k}"]
                rand_dir = (1 - mix_break) * taken[f"fade_{kind}{k}"] + mix_break * taken[f"break_{kind}{k}"]
                # difference per day: agent's taken mean against the random expectation, days resampled
                diff_rows = np.concatenate([chosen - expect.mean()]) if len(taken) else np.array([])
                m, t = _boot_t(diff_rows, taken["day"].to_numpy()) if len(taken) else (np.nan, np.nan)
                halves = []
                for part in (g["time"] < cut, g["time"] >= cut):
                    gg, tt = g[part], g[part][g[part]["take"]]
                    if len(tt) < 5:
                        halves.append(float("nan"))
                        continue
                    ch = np.where(tt["direction"] == "break", tt[f"break_{kind}{k}"], tt[f"fade_{kind}{k}"])
                    ex = ((1 - mix_break) * gg[f"fade_{kind}{k}"] + mix_break * gg[f"break_{kind}{k}"]).mean()
                    halves.append(float(np.mean(ch) - ex))
                skipped = g[~g["take"]]
                sk = ((1 - mix_break) * skipped[f"fade_{kind}{k}"] + mix_break * skipped[f"break_{kind}{k}"]).mean()
                label = "gross" if kind == "g" else "net"
                print(f"   k={k} {label:5s} taken {np.mean(chosen) if len(taken) else float('nan'):+.3f} "
                      f"(n {len(taken)}) | random selection {expect.mean():+.3f} | agent - random {m:+.3f} "
                      f"(t {t:+.1f}) halves {halves[0]:+.3f} / {halves[1]:+.3f} | random direction on its "
                      f"picks {rand_dir.mean() if len(taken) else float('nan'):+.3f} | skipped {sk:+.3f} | "
                      f"fade-everything {g[f'fade_{kind}{k}'].mean():+.3f}")
        if len(taken) > 20 and taken["confidence"].notna().sum() > 20:
            won = np.where(taken["direction"] == "break", taken["break_g1"], taken["fade_g1"]) > 0
            conf = taken["confidence"].to_numpy(float)
            bins = pd.qcut(pd.Series(conf).rank(method="first"), 4, labels=False)
            cal = [f"{conf[bins == b].mean():.2f}->{won[bins == b].mean():.0%}" for b in range(4)]
            print("   confidence quartile -> win rate at 1R: " + " | ".join(cal))
            for tier in ("small", "normal", "large"):
                m_ = taken["size"] == tier
                if m_.sum() >= 10:
                    r = np.where(taken[m_]["direction"] == "break", taken[m_]["break_g1"], taken[m_]["fade_g1"])
                    print(f"   size {tier:6s} n {m_.sum():4d} gross 1R {np.mean(r):+.3f}")
        print(f"   answer spread: confidence distinct {taken['confidence'].round(2).nunique() if len(taken) else 0}, "
              f"size mix {dict(taken['size'].value_counts(normalize=True).round(2)) if len(taken) else {}}")
        print()


if __name__ == "__main__":
    {"zones": zones, "ask": run_ask, "report": report}[PART]()
