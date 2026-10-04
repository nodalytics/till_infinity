"""Time core item 8: the time-of-day volatility profile (NORMAL / UNUSUAL for this hour), the tempo
state against its own hour-of-day baseline, and every event's hour rate - each judged against the
market's own hour, so an hour that is always busy is not unusual for being busy."""
from __future__ import annotations

import fixtures as F
import numpy as np
import pytest
from mcfl import synth
from mcfl.parse import parse
from mcfl.seasonal import (HOUR_MIN, HOUR_WINDOW, TEMPO_EVENTS, TEMPO_HI, TEMPO_LO, TEMPO_SPAN, TOD_HI, TOD_LO, TOD_MIN,
                           TOD_N, Rolling, profile)

BUSY = (13, 14, 15)


@pytest.fixture(scope="module")
def chart():
    sig = np.ones(24)
    sig[list(BUSY)] = 3.0  # the afternoon is three times as volatile
    ts = F.calendar_ts(4000, 900, F.WINTER_MONDAY, "fx")
    df = synth.ticks(synth.profiled(ts, sig, 1.0, seed=81), seed=82)
    return df, parse(df)


def test_rolling_quantiles_are_numpys():
    rng = np.random.default_rng(1)
    r = Rolling(25)
    xs = rng.normal(size=300).round(1)  # ties
    for i, x in enumerate(xs):
        r.add(float(x))
        w = xs[max(0, i - 24):i + 1]
        for q in (0.1, 0.5, 0.9):
            assert r.quantile(q) == pytest.approx(np.quantile(w, q), abs=1e-12)


def test_tod_vol_against_the_same_hour(chart):
    df, ch = chart
    hr = (df["ts"].to_numpy() // 3600) % 24
    rng = (df["high"] - df["low"]).to_numpy()
    c = {e.at: e for e in ch.of("CANDLE")}
    seen: dict = {}
    for t in range(len(rng)):
        past = seen.setdefault(hr[t], [])[-TOD_N:]
        seen[hr[t]].append(rng[t])
        e = c[t]
        if len(past) < TOD_MIN:
            assert e.get("tod_vol") == "WARMUP"
            continue
        lo, med, hi = np.quantile(past, (TOD_LO, 0.5, TOD_HI))
        assert e.get("tod_ratio") == pytest.approx(rng[t] / med)
        assert e.get("tod_vol") == ("UNUSUAL" if rng[t] < lo or rng[t] > hi else "NORMAL")
    warm = [e for e in c.values() if e.get("tod_vol") != "WARMUP"]
    busy = [e for e in warm if hr[e.at] in BUSY]
    share = np.mean([e.get("tod_vol") == "UNUSUAL" for e in busy])
    # judged against its own hour, a busy hour is unusual as often as any other (about 20%) ...
    assert 0.1 < share < 0.35
    # ... where one band for all hours would call most of it unusual
    lo, hi = np.quantile(rng, (TOD_LO, TOD_HI))
    assert np.mean([rng[e.at] > hi or rng[e.at] < lo for e in busy]) > 0.5


def test_profile(chart):
    _, ch = chart
    p = profile(ch)
    assert all(p[h] > 2.4 for h in BUSY) and all(0.8 < p[h] < 1.25 for h in p if h not in BUSY)


def _q(xs: list[float], q: float) -> float:
    """numpy's linear quantile, written out: the rates are multiples of 1/4 and sit on the quantiles
    often, so the comparison needs the same arithmetic, not just the same number to 1e-12."""
    a = sorted(xs)
    pos = q * (len(a) - 1)
    i = int(pos)
    return a[i] if i + 1 >= len(a) else a[i] + (pos - i) * (a[i + 1] - a[i])


def test_tempo_state_brute_force(chart):
    df, ch = chart
    ts = df["ts"].to_numpy()
    close = ts + ch.clock.seen
    cnt = np.zeros(len(ts))
    for e in ch.entities:
        if e.type in TEMPO_EVENTS:
            cnt[e.known_at] += 1
    rate = np.array([cnt[(close > close[t] - TEMPO_SPAN) & (np.arange(len(ts)) <= t)].sum() for t in range(len(ts))])
    rate = rate / (TEMPO_SPAN / 3600)
    hr = (ts // 3600) % 24
    want, last, seen = [], None, {}
    for t in range(len(ts)):
        past = seen.setdefault(hr[t], [])[-TOD_N:]
        seen[hr[t]].append(rate[t])
        if len(past) < TOD_MIN:
            continue
        lo, hi = _q(past, TEMPO_LO), _q(past, TEMPO_HI)
        st = "FAST" if rate[t] > hi else "SLOW" if rate[t] < lo else "NORMAL"
        if st != last:
            want.append((t, st))
            last = st
    got = [(e.at, e.get("state")) for e in sorted(ch.of("TEMPO_STATE"), key=lambda e: e.at)]
    assert got == want and len(got) > 50
    assert {s for _, s in got} == {"FAST", "SLOW", "NORMAL"}


def test_hour_rate_of_any_event(chart):
    df, ch = chart
    hr = (df["ts"].to_numpy() // 3600) % 24
    for typ in ("VOID", "SWING", "PATTERN"):
        es = sorted(ch.of(typ), key=lambda e: (e.known_at, e.at))
        k = 0
        for e in es[::7]:
            past = [hr[x.at] for x in es if x.known_at < e.known_at][-HOUR_WINDOW:]
            if len(past) < HOUR_MIN:
                assert e.time.hour_rate is None
                continue
            k += 1
            assert e.time.hour_rate == pytest.approx(24 * past.count(hr[e.at]) / len(past))
        assert k > 10
    assert all(e.time.hour_rate is None for e in ch.of("CANDLE", "WINDOW", "HTF_CLOSE"))
