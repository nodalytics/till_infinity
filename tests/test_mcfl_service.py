"""The pattern-alert service: switches, restarts, duplicates, evidence and cards.

The engine (`Desk`) is driven bar by bar over real daily series from
`tests/fixtures/mcfl/`, with the clock set just after each bar's close - the
way the service sees bars arrive. The service around it is driven with a fake
fetcher, a temporary prices store and an in-memory bus, so no test touches the
network.
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
import sqlite3
import types
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from till_infinity import stack as st
from till_infinity.bus import ALERTS, Bus
from till_infinity.mcfl import cards, registry
from till_infinity.mcfl import state as ms
from till_infinity.mcfl.config import Settings
from till_infinity.mcfl.desk import Desk, Series
from till_infinity.mcfl.service import Service, classify
from till_infinity.mcfl.tokens import Bars, resample
from till_infinity.mcfl.universe import (
    DEFAULT_COINS,
    FRESH,
    ORIGINAL,
    SET_D,
    Fetcher,
    Venue,
    requests_per_day,
)
from till_infinity.notifications import from_message
from till_infinity.prices.models import Bar, WriteResult
from till_infinity.shared import effects

FIXTURES = Path(__file__).parent / "fixtures" / "mcfl"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def load(name: str) -> Bars:
    d = pd.read_csv(FIXTURES / f"{name}.csv")
    return Bars(
        d["ts"].to_numpy(np.int64),
        *(d[k].to_numpy(float) for k in ("open", "high", "low", "close")),
    )


def settings(tmp_path: Path, **kw) -> Settings:
    base = Settings(
        state_dir=tmp_path / "mcfl",
        pause_file=tmp_path / "mcfl.off",
        prices_db=tmp_path / "prices.db",
        charts=False,
    )
    for k, v in kw.items():
        setattr(base, k, v)
    return base


def replay(desk: Desk, series: Series, bars: Bars, start: int = 60, stop: int | None = None):
    """Feed the desk one closed bar at a time, the clock a minute after each close."""
    out = []
    for i in range(start, len(bars) if stop is None else stop):
        now = float(bars.ts[i]) + series.seconds + 60
        out += desk.observe(series, bars.upto(i), now)
    return out


ARB = Series("alt:ARB:1d", "ARB", "1d", "crypto", "binance:ARB/USDT")
ETH = Series("alt:ETH:1d", "ETH", "1d", "crypto", "binance:ETH/USDT")


# --------------------------------------------------------------- the switches


def test_mcfl_is_off_unless_asked_for(monkeypatch):
    monkeypatch.delenv("MCFL_ENABLED", raising=False)
    plan = st.Plan.from_env()
    assert not plan.mcfl
    assert "mcfl" not in plan.wanted()


def test_mcfl_enabled_starts_it(monkeypatch):
    monkeypatch.setenv("MCFL_ENABLED", "1")
    plan = st.Plan.from_env()
    assert plan.mcfl
    assert "mcfl" in plan.wanted()
    assert hasattr(st.Stack(plan), "_run_mcfl")


def test_mcfl_starts_after_notifications_and_before_prices():
    """A consumer of prices.bars, a publisher to alerts: in between, as the
    in-memory bus only delivers to groups that already exist."""
    order = list(st.ORDER)
    assert order.index("notifications") < order.index("mcfl") < order.index("prices")


async def test_off_means_never_started(monkeypatch, tmp_path):
    """With the flag off the stack never calls the service: no polling, no cards."""
    monkeypatch.setattr(st, "STATUS_FILE", tmp_path / "stack.json")
    called = []
    monkeypatch.setattr(st.mc, "watch", lambda *a, **k: called.append(1))
    plan = st.Plan(
        notifications=False,
        structures=False,
        prices=False,
        news=False,
        journal=False,
        duration=0.05,
        backfill=False,
    )
    status = await st.run(plan)
    assert "mcfl" not in status.running
    assert not called


def test_nothing_here_can_reach_trading():
    """Alert-only: no module of the package imports the trading service."""
    root = Path(st.__file__).parent / "mcfl"
    for path in root.glob("*.py"):
        text = path.read_text()
        assert "from ..trading" not in text, path.name
        assert "import trading" not in text, path.name


# --------------------------------------------------------------- the engine


def test_the_daily_signal_alerts_once_with_its_mirror_and_exits(tmp_path):
    desk = Desk(settings(tmp_path))
    out = replay(desk, ARB, load("ARBUSDT.1d"))
    rules = [c.key.split("|")[0] for c in out]
    assert rules.count("DISPLACE_C_LOW12") == 1
    assert rules.count("M1") == 1
    assert rules.count("DISPLACE_C_LOW12:exit") == 1
    assert rules.count("M1:exit") == 1
    assert not desk.state.trades
    assert not desk.state.mirrors


def test_a_second_source_for_the_same_coin_does_not_duplicate(tmp_path):
    """prices.bars and the alt universe can both carry ETH: one alert, one trade."""
    desk = Desk(settings(tmp_path))
    bars = load("ETHUSDT.1d")
    twin = Series("bars:tradingview:BINANCE:ETHUSDT:1d", "ETH", "1d", "crypto")
    keys = []
    for i in range(60, len(bars)):
        now = float(bars.ts[i]) + 86_400 + 60
        keys += [c.key for c in desk.observe(ETH, bars.upto(i), now)]
        keys += [c.key for c in desk.observe(twin, bars.upto(i), now)]
    assert len(keys) == len(set(keys))
    assert sum(k.startswith("DISPLACE_C_LOW12|") for k in keys) == 2  # a long and a short


def test_a_restart_neither_repeats_nor_loses_an_alert(tmp_path):
    bars = load("ETHUSDT.1d")
    whole = [c.key for c in replay(Desk(settings(tmp_path / "a")), ETH, bars)]
    s = settings(tmp_path / "b")
    first = Desk(s)
    keys = [c.key for c in replay(first, ETH, bars, stop=120)]
    ms.save(first.state, s.state_file)
    second = Desk(s, ms.load(s.state_file))
    keys += [c.key for c in replay(second, ETH, bars, start=120)]
    assert keys == whole
    # And the trade open across the restart still exits with an alert.
    assert any(k.startswith("DISPLACE_C_LOW12:exit") for k in keys)


def test_stale_bars_are_processed_quietly(tmp_path):
    """A bar that closed long ago steps trades but alerts nothing."""
    desk = Desk(settings(tmp_path))
    bars = load("ARBUSDT.1d")
    late = float(bars.ts[-1]) + 30 * 86_400
    out = []
    for i in range(60, len(bars)):
        out += desk.observe(ARB, bars.upto(i), late)
    assert out == []


def test_one_btc_card_per_daily_close_however_many_alts(tmp_path):
    """Ten alts on one close: one BTC card carrying the count, B folded in, and
    one exit card once the last of the ten trades has ended."""
    desk = Desk(settings(tmp_path))
    bars = load("ARBUSDT.1d")
    i = 369  # ARB's daily long signal, given to ten coins
    coins = [f"C{n:02d}" for n in range(10)]
    series = [Series(f"alt:{c}:1d", c, "1d", "crypto") for c in coins]
    for s in series:
        desk.state.last[s.id] = int(bars.ts[i - 1])
    desk.hold_mirror = True  # as the service does during a pass
    sent = []
    for s in series:
        sent += desk.observe(s, bars.upto(i), float(bars.ts[i]) + 86_460)
    desk.hold_mirror = False
    sent += desk.flush()
    mirror = [c for c in sent if c.key.startswith(("M1|", "B|"))]
    assert len(mirror) == 1
    assert mirror[0].key == f"M1|BTC|1d|{int(bars.ts[i])}"
    assert mirror[0].payload["title"] == "BTC 1d · Bullish reversal (market) · long"
    assert mirror[0].payload["fields"]["Breadth"] == "10 · wide"
    assert len(desk.state.mirrors[str(int(bars.ts[i]))]["signals"]) == 10  # kept per signal
    exits = []
    btc = Series("alt:BTC:1d", "BTC", "1d", "crypto")  # the reference prices
    desk.state.last[btc.id] = int(bars.ts[i])
    for j in range(i + 1, len(bars)):
        desk.observe(btc, bars.upto(j), float(bars.ts[j]) + 86_460)
        for s in series:
            exits += desk.observe(s, bars.upto(j), float(bars.ts[j]) + 86_460)
    mirror_exits = [c for c in exits if c.key.startswith("M1:exit")]
    assert len(mirror_exits) == 1
    assert "mean of 10" in mirror_exits[0].payload["fields"]["Result"]
    assert not desk.state.mirrors


def test_a_narrow_day_is_not_marked_wide(tmp_path):
    card = cards.mirror_day(0, 2, False, None)
    assert card.payload["fields"]["Breadth"] == "2"


def test_overlapping_days_each_get_their_card(tmp_path):
    """A new close signals while an earlier day's card is still open."""
    from till_infinity.mcfl.detect import Finding

    desk = Desk(settings(tmp_path))
    bars = load("ARBUSDT.1d")
    s = Series("alt:AAA:1d", "AAA", "1d", "crypto")
    for at in (300, 302):
        f = Finding("DISPLACE_C_LOW12", "DISPLACE_C_LOW12", 1, at, at)
        desk._mirror(f"k{at}", f, s, bars)
    keys = [c.key for c in desk.flush()]
    assert keys == [f"M1|BTC|1d|{int(bars.ts[300])}", f"M1|BTC|1d|{int(bars.ts[302])}"]
    assert desk.flush() == []  # each day once


def test_btc_is_never_its_own_mirror(tmp_path):
    desk = Desk(settings(tmp_path))
    btc = Series("alt:BTC:1d", "BTC", "1d", "crypto")
    out = replay(desk, btc, load("ARBUSDT.1d"))
    assert not [c for c in out if c.key.startswith(("M1|", "B|"))]


def test_the_mirror_alone_still_tracks_the_alts_trade_for_its_exit(tmp_path):
    desk = Desk(settings(tmp_path, patterns=("M1",)))
    out = replay(desk, ARB, load("ARBUSDT.1d"))
    rules = [c.key.split("|")[0] for c in out]
    assert rules == ["M1", "M1:exit"]


# ------------------------------------------------------------------- evidence


@pytest.mark.parametrize(
    ("tf", "badge"),
    [
        ("1d", registry.EDGE),
        ("4h", registry.WEAK),
        ("1h", registry.DESCRIPTIVE),
        ("15m", registry.DESCRIPTIVE),
    ],
)
def test_the_evidence_matches_the_timeframe(tf, badge):
    proof = registry.evidence("DISPLACE_C_LOW12", tf, "crypto")
    assert proof.badge == badge
    if tf != "1d":
        # The daily numbers never ride on another timeframe's card.
        assert "+0.142" not in proof.text
        assert "+0.169" not in proof.text


def test_only_the_validated_rules_carry_an_edge_badge():
    edged = set()
    for name, p in registry.PATTERNS.items():
        for tf in p.timeframes:
            for klass in p.classes:
                if registry.evidence(name, tf, klass).edge:
                    edged.add((name, tf, klass))
    assert edged == {
        ("DISPLACE_C_LOW12", "1d", "crypto"),
        ("M1", "1d", "crypto"),
        ("B", "1d", "crypto"),
    }


def test_choch_is_not_a_pattern():
    kinds = {k for p in registry.PATTERNS.values() for k in p.kinds}
    assert "CHARACTER_SHIFT" not in kinds
    assert "CHARACTER_SHIFT" not in str(registry.PATTERNS)


def test_the_default_set_is_the_trade_and_the_mirror():
    assert set(registry.DEFAULT_ENABLED) == {"DISPLACE_C_LOW12", "M1", "B"}


def test_15m_bos_alerts_only_the_major_break(tmp_path):
    from till_infinity.mcfl.detect import detect

    bars = load("BTCUSDT.15m")
    kinds_15m, kinds_1h = set(), set()
    for last in range(100, len(bars)):
        w = bars.upto(last).tail(300)
        kinds_15m |= {f.kind for f in detect(w, "15m", "crypto", ("BOS",))}
        kinds_1h |= {f.kind for f in detect(w, "1h", "crypto", ("BOS",))}
    assert kinds_15m == {"MAJOR_BOS"}
    assert kinds_1h == {"STRUCTURE_SHIFT"}


# ---------------------------------------------------------------------- cards


def test_a_card_reads_at_a_glance(tmp_path):
    desk = Desk(settings(tmp_path))
    out = replay(desk, ARB, load("ARBUSDT.1d"))
    card = next(c for c in out if c.key.startswith("DISPLACE_C_LOW12|"))
    p = card.payload
    assert p["title"] == "ARB 1d · Bullish reversal · long"
    assert p["body"].splitlines() == ["Tier A · an exit alert will follow", registry.FOOTER]
    for name in ("Entry ref", "Stop", "Risk", "Venue", "Bar"):
        assert name in p["fields"]
    assert p["fields"]["direction"] == "up"
    assert len(p["fields"]) <= 25
    assert all(len(v) <= 1024 for v in p["fields"].values())
    note = from_message(p)
    assert note.mark.startswith("📈")
    assert "\nref:" not in note.as_text()  # routing, not content
    # The evidence stays machine-side.
    assert p["meta"]["evidence"].startswith("EDGE (measured)")


def test_4h_is_context_not_tier_a(tmp_path):
    """A measured but not significant edge is not shown as one."""
    assert registry.tier("DISPLACE_C_LOW12", "4h", "crypto") == registry.CONTEXT
    assert registry.tier("DISPLACE_C_LOW12", "1d", "crypto") == registry.TIER_A
    assert registry.tier("DISPLACE_C_LOW12_X", "1d", "fx") == registry.CONTEXT


def test_an_exit_card_names_its_alert_and_its_result(tmp_path):
    desk = Desk(settings(tmp_path))
    out = replay(desk, ARB, load("ARBUSDT.1d"))
    card = next(c for c in out if c.key.startswith("DISPLACE_C_LOW12:exit"))
    assert card.payload["title"] == "ARB 1d · Exit"
    assert card.payload["fields"]["Result"].endswith("R")
    assert card.payload["fields"]["Opened by"].startswith("the ARB 1d alert of 2026-")
    assert card.payload["fields"]["shape"] == "exit"


#: What must never reach a reader: the method, its numbers and its sources.
LEAKS = re.compile(
    r"[A-Z0-9]{2,}_[A-Z]|12-bar|bar low|bar high|ATR|CISD|displace|violent|\.md|fresh coins"
    r"|\d+R \[|MCFL|mcfl|DISPLACE|BREACH|DELIVERY|STRUCTURE_|CHARACTER|EDGE|evidence",
    re.IGNORECASE,
)


def _rendered(card) -> list[str]:
    """Everything a transport can show: the Telegram text, the Discord embed, the chart title."""
    from till_infinity.notifications import Channel, DiscordNotifier
    from till_infinity.notifications import Settings as NotifySettings

    note = from_message(card.payload)
    embed = DiscordNotifier(NotifySettings(), Channel("discord", "x")).payload(note)
    out = [note.as_text(escape=True), json.dumps(embed, ensure_ascii=False)]
    if card.chart is not None:
        out.append(card.chart.title)
        out += [line.label for line in card.chart.levels]
    return out


def test_no_card_leaks_the_method(tmp_path):
    """Every card every pattern can send, on every fixture and timeframe, is
    checked against LEAKS - title, body, every Discord field, the chart title
    and its line labels."""
    every = tuple(registry.PATTERNS)
    checked = 0
    for name, tf in (
        ("ARBUSDT.1d", "1d"),
        ("ETHUSDT.1d", "1d"),
        ("BTCUSDT.4h", "4h"),
        ("BTCUSDT.15m", "15m"),
    ):
        for klass in ("crypto", "fx"):
            desk = Desk(settings(tmp_path / f"{name}{tf}{klass}", patterns=every))
            series = Series(
                f"t:{name}:{tf}:{klass}", "BTC" if "BTC" in name else name[:3], tf, klass, "binance"
            )
            bars = load(name)
            for i in range(60, len(bars), 1 if tf == "1d" else 3):
                step = series.seconds
                for card in desk.observe(series, bars.upto(i), float(bars.ts[i]) + step + 1):
                    for text in _rendered(card):
                        hit = LEAKS.search(text)
                        assert hit is None, f"{card.key}: {hit.group(0)!r} in {text[:200]!r}"
                    checked += 1
    for card in (
        cards.mirror_day(0, 7, True, 1.0),
        cards.mirror_exited(0, "k", 12.0, 7, 5 * 86_400),
    ):
        for text in _rendered(card):
            assert LEAKS.search(text) is None, text
    assert checked > 50


def test_two_mirror_days_are_two_findings_to_the_filter(tmp_path):
    """Same shape and instrument (BTC) - different closes - both get through."""
    from till_infinity.notifications import Filter

    a = cards.mirror_day(0, 4, True, None)
    b = cards.mirror_day(86_400, 1, False, None)
    f = Filter()
    assert f.accept(a.payload, when=1.0)
    assert f.accept(b.payload, when=2.0)


# ------------------------------------------------------------------ the service


def _store(path: Path, feed: str, venue: str, ticker: str, interval: str, bars: Bars) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS bars (source TEXT, feed TEXT, venue TEXT, ticker TEXT,"
            " interval TEXT, ts INTEGER, open REAL, high REAL, low REAL, close REAL, volume REAL)"
        )
        conn.executemany(
            "INSERT INTO bars VALUES ('tradingview', ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
            [
                (feed, venue, ticker, interval, int(t), o, h, lo, c)
                for t, o, h, lo, c in zip(
                    bars.ts, bars.open, bars.high, bars.low, bars.close, strict=True
                )
            ],
        )


def _notice(feed, venue, ticker, interval, ts):
    return {
        "source": "tradingview",
        "feed": feed,
        "venue": venue,
        "ticker": ticker,
        "interval": interval,
        "time": int(ts),
        "closed": True,
    }


class FakeFetcher:
    def __init__(self, series: dict[str, Bars]):
        self.series = series
        self.asked: list[tuple[str, str]] = []
        self.upto: int | None = None

    async def open(self):
        return None

    async def close(self):
        return None

    async def bars(self, coin, tf, limit):
        self.asked.append((coin, tf))
        b = self.series.get(coin)
        if b is None:
            return None
        if self.upto is not None:
            b = b.upto(self.upto)
        rows = [
            Bar(int(t), o, h, lo, c)
            for t, o, h, lo, c in zip(b.ts, b.open, b.high, b.low, b.close, strict=True)
        ][-limit:]
        return "binance:X/USDT", rows


async def _collect(bus: Bus) -> list[dict]:
    got = []
    sub = bus.subscribe(ALERTS, group="test")
    while True:
        try:
            m = await asyncio.wait_for(sub.next(), 0.01)
        except TimeoutError:
            return got
        if m is not None:
            got.append(m.payload)
    return got  # pragma: no cover


async def test_prices_bars_are_read_back_from_the_store_and_alerted(tmp_path):
    bars = load("ETHUSDT.1d")
    i = 95  # ETH's long: the store holds the series up to it, as when its notice arrives
    s = settings(tmp_path, patterns=("DISPLACE_C_LOW12",))
    _store(s.prices_db, "eth", "BINANCE", "ETHUSDT", "1d", bars.upto(i))
    bus = Bus()
    bus.subscribe(ALERTS, group="test")
    clock = types.SimpleNamespace(now=float(bars.ts[i]) + 86_400 + 60)
    service = Service(bus, s, clock=lambda: clock.now)
    service.desk.state.last["bars:tradingview:BINANCE:ETHUSDT:1d"] = int(bars.ts[i - 1])
    sent = await service.on_bar(_notice("eth", "BINANCE", "ETHUSDT", "1d", bars.ts[i]))
    assert sent == 1
    got = await _collect(bus)
    assert got[0]["title"] == "ETH 1d · Bullish reversal · long"


async def test_paused_means_no_fetches_and_no_sends(tmp_path):
    s = settings(tmp_path)
    s.pause_file.parent.mkdir(parents=True, exist_ok=True)
    s.pause_file.touch()
    fetcher = FakeFetcher({"ARB": load("ARBUSDT.1d")})
    bus = Bus()
    service = Service(bus, s, fetcher=fetcher, clock=lambda: 2e9)
    assert await service.alt_cycle(("4h", "1d")) == 0
    assert fetcher.asked == []
    assert await service.on_bar(_notice("eth", "BINANCE", "ETHUSDT", "1d", 0)) == 0
    card = cards.mirror_day(0, 3, True, None)
    assert await service.send(card) == 0


async def test_resume_sends_no_backlog(tmp_path):
    """Bars that closed while paused are processed quietly after the resume."""
    s = settings(tmp_path, alt_coins=("ARB",))
    bars = load("ARBUSDT.1d")
    fetcher = FakeFetcher({"ARB": bars})
    bus = Bus()
    bus.subscribe(ALERTS, group="test")
    clock = types.SimpleNamespace(now=float(bars.ts[300]) + 86_400 + 60)
    service = Service(bus, s, fetcher=fetcher, clock=lambda: clock.now)
    fetcher.upto = 300
    await service.alt_cycle(("1d",))  # seeds, before the signal at 369
    s.pause_file.touch()
    assert service.paused()
    # Paused across the signal bar and well past it.
    clock.now = float(bars.ts[369]) + 86_400 + 60
    assert await service.alt_cycle(("1d",)) == 0
    s.pause_file.unlink()
    fetcher.upto = 369
    sent = await service.alt_cycle(("1d",))
    assert sent == 0, "the signal closed before the resume: no backlog"
    assert service.desk.state.last["alt:ARB:1d"] == int(bars.ts[369])


async def test_the_alt_cycle_alerts_a_fresh_signal_and_declares_its_effect(tmp_path):
    effects.reset()
    s = settings(tmp_path, alt_coins=("ARB",))
    bars = load("ARBUSDT.1d")
    fetcher = FakeFetcher({"ARB": bars})
    bus = Bus()
    bus.subscribe(ALERTS, group="test")
    clock = types.SimpleNamespace(now=float(bars.ts[368]) + 86_400 + 60)
    service = Service(bus, s, fetcher=fetcher, clock=lambda: clock.now, render=lambda spec: PNG)
    service.settings.charts = True
    assert effects.report()["mcfl.alerts"]["enabled"]
    fetcher.upto = 368
    await service.alt_cycle(("1d",))
    fetcher.upto = 369
    clock.now = float(bars.ts[369]) + 86_400 + 60
    assert await service.alt_cycle(("1d",)) == 2  # the alt's card and M1
    got = await _collect(bus)
    titles = {p["title"]: p for p in got}
    assert set(titles) == {
        "ARB 1d · Bullish reversal · long",
        "BTC 1d · Bullish reversal (market) · long",
    }
    # The alt's card carries its chart; the BTC card has none - its trigger is not shown.
    alt = titles["ARB 1d · Bullish reversal · long"]
    assert base64.b64decode(alt["image"]["data"]) == PNG
    assert "image" not in titles["BTC 1d · Bullish reversal (market) · long"]
    assert effects.report()["mcfl.alerts"]["count"] == 2
    assert from_message(alt).image == PNG
    effects.reset()


def test_classify_sorts_the_prices_feeds():
    assert classify("btc", "tradingview", "BTCUSDT") == ("crypto", "BTC")
    assert classify("gold", "tradingview", "XAUUSD") == ("metals", "GOLD")
    assert classify("us100", "tradingview", "NAS100") == ("indices", "US100")
    assert classify("wti", "yahoo", "CL=F") == ("energy", "WTI")
    assert classify("eurusd", "tradingview", "EURUSD") == ("fx", "EURUSD")
    assert classify("volatility-75-index", "broker", "Volatility 75 Index") == (
        "deriv",
        "VOLATILITY-75-INDEX",
    )
    assert classify("pepe-usdt-usdt", "ccxt", "PEPE/USDT:USDT") == ("crypto", "PEPE")


# --------------------------------------------------------------- the universe


def test_the_default_universe_is_what_the_rules_were_validated_on():
    assert len(ORIGINAL) == 12
    assert len(FRESH) == 58
    assert len(SET_D) == 274
    assert len(DEFAULT_COINS) == 344
    assert requests_per_day(344, ("4h", "1d")) == 2_408


class FakeSource:
    def __init__(self, bars: dict[str, list[Bar]]):
        self.bars = bars
        self.calls = []

    async def fetch(self, job, limit, sink):
        self.calls.append(job.symbol.ticker)
        got = self.bars.get(job.symbol.ticker, [])
        await sink(job.key(job.intervals[0]), got)
        return WriteResult(inserted=len(got))


async def test_a_stale_venue_hands_the_coin_to_the_next(monkeypatch):
    now = 2_000_000_000
    monkeypatch.setattr("till_infinity.mcfl.universe.time.time", lambda: now)
    day = 86_400
    fresh = [Bar(now - day * k - day, 1, 2, 0.5, 1.5) for k in range(5, 0, -1)]
    stale = [Bar(now - day * k - 10 * day, 1, 2, 0.5, 1.5) for k in range(5, 0, -1)]
    spot = Venue("binance", "spot", listed={"OLD/USDT", "PEPE/USDT"})
    swap = Venue("okx", "swap", listed={"OLD/USDT:USDT"})
    spot.source = FakeSource({"OLD/USDT": stale, "PEPE/USDT": fresh})
    swap.source = FakeSource({"OLD/USDT:USDT": fresh})
    f = Fetcher([spot, swap])
    venue, rows = await f.bars("OLD", "1d", 300)
    assert venue == "okx:OLD/USDT:USDT"
    assert rows == fresh
    # The 1000x perpetual is found under its spot name.
    venue, _ = await f.bars("1000PEPE", "1d", 300)
    assert venue == "binance:PEPE/USDT"
    assert await f.bars("NOWHERE", "1d", 300) is None


async def test_ccxt_overrides_reach_the_exchange_and_nothing_else_changes():
    from till_infinity.mcfl.universe import BINANCE_MIRROR
    from till_infinity.prices.crypto import CcxtSource

    venue = Venue("binance", "spot", BINANCE_MIRROR)
    async with CcxtSource(venue.settings()) as source:
        ex = source._pick("binance")
        assert ex.urls["api"]["public"] == BINANCE_MIRROR
        assert ex.options["defaultType"] == "spot"
        assert ex.options["fetchMarkets"]["types"] == ["spot"]
    plain = types.SimpleNamespace(ccxt_exchanges=("binance",), ccxt_market_type="swap")
    async with CcxtSource(plain) as source:
        ex = source._pick("binance")
        assert ex.options["defaultType"] == "swap"
        assert "binance.com" in ex.urls["api"]["public"]


# ---------------------------------------------------------------- resampling


def test_daily_bars_are_built_on_utc_days_and_only_when_complete():
    hour = 3_600
    start = 1_700_006_400  # 2023-11-15 00:00 UTC
    ts = start + np.arange(50) * hour
    o = np.arange(50, dtype=float)
    b = Bars(ts.astype(np.int64), o, o + 2, o - 1, o + 1)
    days = resample(b, 86_400, hour)
    assert list(days.ts) == [start, start + 86_400]  # the third day is still forming
    assert days.open[0] == 0
    assert days.close[0] == 24
    assert days.high[1] == 47 + 2
    assert days.low[1] == 24 - 1
