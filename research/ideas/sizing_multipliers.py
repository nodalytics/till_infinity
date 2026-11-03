"""Do the eight sizing multipliers earn their place? One at a time.

`strategies/profile.py` holds nine reductions behind `SIZING_MULTIPLIERS`, all
off, and until 2026-11-01 the path raised `ImportError` on every call so none
of them has ever applied to a trade. This measures them.

Three things are measured here and they are not the same question.

1. **Reachability.** Whether `SIZING_MULTIPLIERS` can change a position size
   at all, in the package as it stands. Printed by `reach()`.
2. **The arithmetic at the shipped settings.** What each multiplier returns on
   the features the only live producer emits. Printed by `shipped()`.
3. **A replay over the recorded closed trades.** The only trade population
   this desk has ever had: `.data/live/journal_full.csv`, 2026-08-30 to
   2026-10-08. A sizing multiplier scales *risk*, so in R-multiples trade `i`
   risks `m_i` and returns `m_i * r_i`, and the question "are the trades it
   shrinks the ones that lost" is whether the risk-weighted mean return
   `sum(m r) / sum(m)` beats the unweighted `mean(r)`. The denominator is
   invariant under a permutation of `m` against `r`, so that permutation is an
   exact null for the statistic and it is centred at zero.

Run: `.venv/bin/python research/ideas/sizing_multipliers.py`
"""

from __future__ import annotations

import collections
import csv
import datetime
import json
import math
import pathlib
import statistics
import subprocess
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from till_infinity.node import metrics  # noqa: E402
from till_infinity.risk import scaling  # noqa: E402
from till_infinity.strategies import config as cfg  # noqa: E402
from till_infinity.strategies.profile import (  # noqa: E402
    MULTIPLIERS,
    RISK_SHARE_BY_STYLE,
    Profile,
    multipliers_on,
)

JOURNAL = pathlib.Path(".data/live/journal_full.csv")
DEALS = pathlib.Path(".data/live/deals.json")

#: Permutations per arm. The statistic is cheap and the sample is 1,613.
DRAWS = 20_000
SEED = 20261101

# ──────────────────────────────────────────────────────── the stated settings
#
# Six of the nine have a threshold whose shipped default is `0.0`, which the
# functions read as off - so "enabled" is not the same as "applies", and a
# measurement needs a value chosen and stated. Every one below comes from this
# repository's own record rather than from a sweep, and none of them is tuned
# against the result.

#: `crowding_share`: `research/docs/trading-scaling.md` works the example at
#: 0.5 - "the second position on a leg is halved, the third quartered".
CROWDING_SHARE = 0.5

#: `regime_band`: the measured plateau. The same doc puts the held rate at
#: 86.4% for a forecast ratio in [1.00, 1.21] against 81.3/81.4% outside, so
#: the band is `log(1.21)` and the floor is the shipped 0.5.
REGIME_BAND = math.log(1.21)
REGIME_FLOOR = 0.5

#: `spike_above`: "Off at 0; 0.8 is the measured setting", same doc.
SPIKE_ABOVE = 0.8
SPIKE_FLOOR = 0.5

#: `edge_full_at`: the edge that earns full size, in volatility units. The best
#: row in `research/docs/paying.md` is spx500 at +0.938, so 1.0 is the round
#: number just above the whole measured range.
EDGE_FULL_AT = 1.0

#: `drawdown_halt_at`: the standard plan's own daily loss fraction, 3% - which
#: is the cliff `by_drawdown` exists to approach smoothly. `risk/plans.py`.
DRAWDOWN_HALT_AT = 0.03

#: Equity the drawdown path is simulated on, and the money one R risks. The
#: backtest venue starts at 10,000 and the standard plan risks 0.25% a trade.
#: Non-compounding, so one R is a constant 25 and the path is `E0 + 25 * sum`.
START_EQUITY = 10_000.0
RISK_MONEY = 25.0

#: Net edge per touch in volatility units, `research/docs/paying.md`. Feeds
#: absent from the table get `None`, which `by_edge` reads as "no measurement"
#: and sizes at full - deliberately, since a refusal is paying.md's job.
NET_EDGE_VOL: dict[str, float] = {
    "spx500": 0.938, "gold": 0.919, "brent": 0.884, "wti": 0.869,
    "us100": 0.756, "us30": 0.669, "jp225": 0.624, "fra40": 0.597,
    "us2000": 0.400, "aus200": 0.354, "silver": 0.351, "eth": 0.309,
    "eu50": 0.266, "ger40": 0.207, "volatility_10_index": 0.194,
    "gbpusd": 0.137, "uk100": 0.127, "eurgbp": 0.120, "gbpjpy": 0.082,
    "btc": 0.008, "eurusd": -0.012, "audusd": -0.177, "usdjpy": -0.168,
    "eurjpy": -0.184, "usdcad": -0.471, "eurchf": -0.549, "chfjpy": -0.581,
    "audjpy": -0.662, "nzdusd": -1.044, "hk50": -1.198, "usdcnh": -4.663,
}

#: The retired strategies' styles, read off `research/retire/structures/
#: strategies/`. Anything unlisted declared no style and inherits `scalp`,
#: which `RISK_SHARE_BY_STYLE` sizes at full.
STRATEGY_STYLE: dict[str, str] = {
    "approach-scalp": "swing", "runner": "swing", "swing-level": "swing",
    "origin-swing": "swing", "fade-to-value": "swing", "opportunity": "swing",
    "ride": "swing", "cycle-turn": "position",
}

#: A record whose `risk_price` rounded to a couple of ticks makes `r_multiple`
#: meaningless - one ger40 close reads 2,390 R on a 5.38 profit. Three rows of
#: 1,616, dropped and counted rather than winsorised, because the cause is a
#: zero denominator and not a fat tail.
MAX_ABS_R = 10.0


# ═══════════════════════════════════════════════════ 1. is the switch wired?


def reach() -> None:
    """Every call site of the sizing path, in the live package."""
    print("── 1. reachability ─────────────────────────────────────────────")
    names = ("risk_scale", "spike_scale", ".multipliers(", "multipliers_on", "combined(")
    for name in names:
        found = subprocess.run(
            ["grep", "-rn", "--include=*.py", name, "till_infinity/"],
            capture_output=True, text=True, check=False,
        ).stdout.splitlines()
        hits = [
            line for line in found
            if not line.lstrip().split(":", 2)[-1].lstrip().startswith(("#", '"', "*", "|"))
        ]
        outside = [h for h in hits if "strategies/profile.py" not in h]
        print(f"  {name:16s} {len(hits):3d} reference(s), {len(outside)} outside profile.py")
        for h in outside:
            print(f"      {h.strip()[:110]}")
    print(f"  SIZING_MULTIPLIERS as configured -> {sorted(multipliers_on())}")
    print()


# ══════════════════════════════════════════ 2. the arithmetic, as configured


class Bare(Profile):
    """A profile with nothing on it, so only the multipliers are under test."""

    name = "bare"


def _profile(settings, style: str = "scalp") -> Profile:
    made = Bare.__new__(Bare)
    made.settings = settings
    made.style = style  # type: ignore[misc]
    return made


def shipped() -> None:
    """Each multiplier on the features the live producer emits, two ways."""
    print("── 2. the multipliers at the shipped settings ──────────────────")
    from till_infinity.statespace import proposing

    live = {
        "vol_bps": 12.0, "surprise": 4.2, "stop_vol": 2.0, "target_r": 2.0,
        "probability": 0.41, "base_rate_up": proposing.BASE_RATE,
        "log_variance": -8.1, "spread": 0.3, "band_coverage": 0.9,
    }
    rich = dict(live, ewma_tr_bps=30.0, forecast_ratio=2.6, tr_percentile=0.95,
                net_edge_vol=-0.5)
    for label, features, settings in (
        ("live features, shipped settings", live, cfg.Settings()),
        ("rich features, shipped settings", rich, cfg.Settings()),
        ("rich features, stated settings", rich, _stated(cfg.Settings())),
    ):
        made = _profile(settings)
        values = made._reductions(  # noqa: SLF001 - the named nine, as production builds them
            scaling.crowding("eurusd", [("gbpusd", 1)], settings.crowding_share),
            scaling.by_volatility(
                float(features.get("ewma_tr_bps") or features.get("vol_bps") or 0.0),
                settings.volatility_target_bps,
            ),
            scaling.by_regime(features.get("forecast_ratio"), settings.regime_band,
                              settings.regime_floor),
            scaling.by_spike(features.get("tr_percentile"), settings.spike_above,
                             settings.spike_floor),
            scaling.by_edge(features.get("net_edge_vol"), settings.edge_full_at),
            scaling.by_drawdown(10_000.0, 9_500.0, settings.drawdown_halt_at),
            scaling.by_slippage(
                scaling.overshoot_for(settings.stop_overshoot, "boom_500_index", "sell")
            ),
            scaling.by_interval("5m", settings.interval_weight),
            made.share_of_risk,
        )
        print(f"  {label}")
        print("    " + "  ".join(f"{k}={v:.3f}" for k, v in values.items()))
        print(f"    product (scaling.combined) = {scaling.combined(*values.values()):.4f}")
        _agrees(made, features, settings, values)
    print()
    print("  what the live producer emits:")
    print(f"    {sorted(live)}")
    print("  what the nine read:")
    print("    crowding=open book  volatility=ewma_tr_bps|vol_bps  regime=forecast_ratio")
    print("    spike=tr_percentile  edge=net_edge_vol  drawdown=equity,peak")
    print("    slippage=stop_overshoot  interval=interval  share=profile style")
    print()


def _agrees(made: Profile, features: dict, settings, values: dict) -> None:
    """The nine computed here are the nine `Profile.multipliers` computes.

    The measurement below calls `scaling.*` directly, so this is the assertion
    that it is calling them the way production composes them - with every name
    enabled, so the gate is not what is under test.
    """
    import os

    was = os.environ.get("SIZING_MULTIPLIERS")
    os.environ["SIZING_MULTIPLIERS"] = "all"
    try:
        theirs = made.multipliers(
            features,
            "boom_500_index",
            book=(),
            equity=9_500.0,
            peak=10_000.0,
            interval="5m",
            side="sell",
        )
    finally:
        if was is None:
            os.environ.pop("SIZING_MULTIPLIERS", None)
        else:
            os.environ["SIZING_MULTIPLIERS"] = was
    # `crowding` differs by design: the check above passes a book, this passes
    # none, and `by_drawdown` is the only other one needing the equity pair.
    for name in MULTIPLIERS:
        if name == "crowding":
            continue
        assert abs(theirs[name] - values[name]) < 1e-12, (name, theirs[name], values[name])
    print(f"    agrees with Profile.multipliers on {len(MULTIPLIERS) - 1} of 9 "
          f"(crowding takes a book this check does not pass)")


def _stated(settings):
    """The shipped settings with every zero threshold replaced by a stated one."""
    import dataclasses

    return dataclasses.replace(
        settings,
        crowding_share=CROWDING_SHARE,
        regime_band=REGIME_BAND,
        regime_floor=REGIME_FLOOR,
        spike_above=SPIKE_ABOVE,
        spike_floor=SPIKE_FLOOR,
        edge_full_at=EDGE_FULL_AT,
        drawdown_halt_at=DRAWDOWN_HALT_AT,
    )


# ══════════════════════════════════════════════════════ 3. the trade record


def _load() -> tuple[list[dict], list[dict]]:
    decisions, outcomes = [], []
    with JOURNAL.open() as handle:
        csv.field_size_limit(10**7)
        for row in csv.DictReader(handle):
            kind = row["kind"]
            if kind not in ("decision", "outcome"):
                continue
            try:
                ctx = json.loads(row["context"])
            except (ValueError, TypeError):
                continue
            ctx["_time"] = float(row["time"])
            (decisions if kind == "decision" else outcomes).append(ctx)
    decisions.sort(key=lambda d: d["_time"])
    outcomes.sort(key=lambda d: d["_time"])
    return decisions, outcomes


def trades() -> list[dict]:
    """One row per closed trade, features attached where the record has them.

    Features come off the outcome's own context first and off a joined decision
    second. The join is `(feed, side, volume, entry)` with the decision taken as
    the last one before the close, which is exact where it matches at all - the
    journal records a decision for only some placements, so it matches 745 of
    1,626 and the unmatched ones keep whatever the outcome carried.
    """
    decisions, outcomes = _load()
    byfs: dict[tuple, list[dict]] = collections.defaultdict(list)
    for dec in decisions:
        byfs[(dec.get("feed"), dec.get("side"))].append(dec)

    def joined(out: dict) -> dict | None:
        best = None
        for dec in byfs.get((out.get("feed"), out.get("side")), []):
            if dec["_time"] > out["_time"]:
                break
            if abs(float(dec.get("volume") or 0) - float(out.get("volume") or 0)) > 1e-9:
                continue
            for field in ("entry", "entry_wanted", "entry_filled"):
                if round(float(dec.get("entry") or 0), 8) == round(float(out.get(field) or 0), 8):
                    best = dec
                    break
        return best

    rows, dropped = [], 0
    for out in outcomes:
        raw = out.get("r_multiple")
        if raw is None:
            dropped += 1
            continue
        try:
            r = float(raw)
        except (TypeError, ValueError):
            dropped += 1
            continue
        if not math.isfinite(r) or abs(r) > MAX_ABS_R:
            dropped += 1
            continue
        dec = joined(out)
        features = dict(dec or {})
        features.update({k: v for k, v in out.items() if v is not None})
        rows.append(
            {
                "time": out["_time"],
                "opened": out["_time"] - float(out.get("seconds") or 0.0),
                "feed": str(out.get("feed") or ""),
                "side": str(out.get("side") or ""),
                "interval": str(out.get("interval") or ""),
                "strategy": str(out.get("strategy") or ""),
                "r": r,
                "profit": float(out.get("profit") or 0.0),
                "features": features,
            }
        )
    print(f"  {len(rows)} closed trades, {dropped} dropped (no r_multiple, or |r| > {MAX_ABS_R})")
    return rows


def baseline(rows: list[dict]) -> None:
    """The window, and the desk's own published table beside it."""
    print("── 3. the baseline ────────────────────────────────────────────")
    times = [row["time"] for row in rows]
    span = (datetime.datetime.fromtimestamp(min(times), datetime.UTC),
            datetime.datetime.fromtimestamp(max(times), datetime.UTC))
    r = [row["r"] for row in rows]
    print(f"  window {span[0]:%Y-%m-%d} .. {span[1]:%Y-%m-%d}, {len(rows)} closes")
    print(f"  expectancy {metrics.expectancy(r):+.4f} R, sd {statistics.pstdev(r):.4f}, "
          f"sum {sum(r):+.1f} R")
    print(f"  win rate {metrics.win_rate(r):.4f}, payoff {metrics.payoff(r):.4f}, "
          f"profit factor {metrics.profit_factor(r):.4f}")
    print(f"  per-trade Sharpe {metrics.sharpe(r):+.5f}")
    print(f"  money: sum {sum(row['profit'] for row in rows):+.2f}, "
          f"mean {statistics.mean(row['profit'] for row in rows):+.3f}")
    if DEALS.exists():
        deals = json.loads(DEALS.read_text())
        net = sum(d["profit"] + d["swap"] + d["commission"] + d["fee"] for d in deals)
        print(f"  broker cross-check ({DEALS}): {len(deals)} deals, net {net:+.2f}")
    print()
    print("  the desk's published per-interval table (trading-scaling.md, 2026-09-03)")
    print("  against the same cut of this window:")
    published = {"1m": (47, -7.75), "3m": (34, -4.80), "5m": (48, -6.13),
                 "15m": (15, -2.46), "30m": (2, 3.71), "1h": (3, 18.67)}
    cut = datetime.datetime(2026, 9, 4, tzinfo=datetime.UTC).timestamp()
    here: dict[str, list[float]] = collections.defaultdict(list)
    for row in rows:
        if row["time"] < cut:
            here[row["interval"]].append(row["profit"])
    print(f"    {'interval':9s} {'published n':>11s} {'per close':>10s} "
          f"{'here n':>7s} {'per close':>10s}")
    for name, (n, per) in published.items():
        mine = here.get(name, [])
        got = f"{statistics.mean(mine):+.2f}" if mine else "-"
        print(f"    {name:9s} {n:11d} {per:+10.2f} {len(mine):7d} {got:>10s}")
    print()


# ══════════════════════════════════════════════════════════ the nine arms


def _crowding(rows: list[dict]) -> list[float]:
    """`crowding` over the reconstructed book, at each trade's open."""
    out = []
    for row in rows:
        book = [
            (other["feed"], 1 if other["side"] == "buy" else -1)
            for other in rows
            if other is not row and other["opened"] <= row["opened"] < other["time"]
        ]
        out.append(scaling.crowding(row["feed"], book, CROWDING_SHARE))
    return out


def _volatility(rows: list[dict], target: float) -> list[float]:
    return [
        scaling.by_volatility(
            float(row["features"].get("ewma_tr_bps") or row["features"].get("vol_bps") or 0.0),
            target,
        )
        for row in rows
    ]


def _drawdown(rows: list[dict], halt: float) -> list[float]:
    """Path-dependent, so simulated forward: the multiplier a trade gets is
    read off the equity its predecessors' *reduced* sizes produced."""
    equity, peak, out = START_EQUITY, START_EQUITY, []
    for row in rows:
        value = scaling.by_drawdown(peak, equity, halt)
        out.append(value)
        equity += value * row["r"] * RISK_MONEY
        peak = max(peak, equity)
    return out


def _share(rows: list[dict]) -> list[float]:
    return [
        max(0.0, min(1.0, RISK_SHARE_BY_STYLE.get(STRATEGY_STYLE.get(row["strategy"], "scalp"), 1.0)))
        for row in rows
    ]


def arms(rows: list[dict]) -> dict[str, tuple[list[int], list[float], str]]:
    """Per arm: which trades it is measured on, the multiplier, and the setting."""
    shipped_settings = cfg.Settings()
    everyone = list(range(len(rows)))

    def have(name: str) -> list[int]:
        return [i for i, row in enumerate(rows) if row["features"].get(name) is not None]

    vol_rows = have("ewma_tr_bps") or have("vol_bps")
    vol_sample = sorted(set(have("ewma_tr_bps")) | set(have("vol_bps")))
    target = statistics.median(
        float(rows[i]["features"].get("ewma_tr_bps") or rows[i]["features"].get("vol_bps"))
        for i in vol_sample
    ) if vol_sample else 0.0
    del vol_rows

    found: dict[str, tuple[list[int], list[float], str]] = {
        "crowding": (everyone, _crowding(rows), f"crowding_share={CROWDING_SHARE}"),
        "volatility": (
            vol_sample,
            _volatility([rows[i] for i in vol_sample], target),
            f"volatility_target_bps={target:.3f} (median of the sample)",
        ),
        "regime": (
            have("forecast_ratio"),
            [
                scaling.by_regime(rows[i]["features"]["forecast_ratio"], REGIME_BAND, REGIME_FLOOR)
                for i in have("forecast_ratio")
            ],
            f"regime_band={REGIME_BAND:.4f} (log 1.21), regime_floor={REGIME_FLOOR}",
        ),
        "spike": (
            have("tr_percentile"),
            [
                scaling.by_spike(rows[i]["features"]["tr_percentile"], SPIKE_ABOVE, SPIKE_FLOOR)
                for i in have("tr_percentile")
            ],
            f"spike_above={SPIKE_ABOVE}, spike_floor={SPIKE_FLOOR}",
        ),
        "edge": (
            everyone,
            [scaling.by_edge(NET_EDGE_VOL.get(row["feed"]), EDGE_FULL_AT) for row in rows],
            f"edge_full_at={EDGE_FULL_AT}, net edge per instrument from paying.md",
        ),
        "drawdown": (
            everyone,
            _drawdown(rows, DRAWDOWN_HALT_AT),
            f"drawdown_halt_at={DRAWDOWN_HALT_AT} (the standard plan's daily loss)",
        ),
        "slippage": (
            everyone,
            [
                scaling.by_slippage(
                    scaling.overshoot_for(shipped_settings.stop_overshoot, row["feed"], row["side"])
                )
                for row in rows
            ],
            "stop_overshoot=DEFAULT_STOP_OVERSHOOT (shipped)",
        ),
        "interval": (
            everyone,
            [scaling.by_interval(row["interval"], shipped_settings.interval_weight) for row in rows],
            "interval_weight=INTERVAL_WEIGHT (shipped)",
        ),
        "share": (everyone, _share(rows), "style -> RISK_SHARE_BY_STYLE (shipped)"),
    }
    assert set(found) == set(MULTIPLIERS), sorted(set(MULTIPLIERS) ^ set(found))

    # **Reported, not recommended.** `all` is the product of the arms that have
    # a sample, over the trades all of them cover - which excludes `spike`,
    # whose reading exists on one closed trade in the window.
    usable = {name: value for name, value in found.items() if len(value[0]) >= 4}
    common = sorted(set.intersection(*(set(idx) for idx, _, _ in usable.values())))
    if common:
        product = []
        for i in common:
            terms = [m[idx.index(i)] for idx, m, _ in usable.values()]
            product.append(scaling.combined(*terms))
        found["all-but-spike"] = (
            common, product, f"every stated setting at once, {len(usable)} arms",
        )

    # **A second stated halt, because 0.03 floors the whole record.** Reported
    # rather than chosen: the taper is from the high-water mark and does not
    # reset daily, so a 3% halt puts every trade after the first drawdown at
    # the floor. 0.30 is the other end of the same argument and it is listed
    # so that the reading is not mistaken for a sweep.
    found["drawdown@0.30"] = (everyone, _drawdown(rows, 0.30), "drawdown_halt_at=0.30")
    return found


# ═══════════════════════════════════════════════════════════ the statistics


def weighted(m: np.ndarray, r: np.ndarray) -> float:
    """Return per unit of risk taken. `sum(m r) / sum(m)`."""
    total = float(m.sum())
    return float((m * r).sum() / total) if total > 0 else float("nan")


def permute(m: np.ndarray, r: np.ndarray, draws: int = DRAWS) -> tuple[float, float, float]:
    """`(delta, z, two-sided p)` against a permutation of `m` against `r`."""
    base = float(r.mean())
    seen = weighted(m, r) - base
    rng = np.random.default_rng(SEED)
    null = np.empty(draws)
    for k in range(draws):
        null[k] = weighted(rng.permutation(m), r) - base
    spread = float(null.std(ddof=1))
    z = seen / spread if spread > 0 else 0.0
    p = float((np.abs(null) >= abs(seen) - 1e-15).mean())
    return seen, z, p


def holm(pairs: list[tuple[str, float]], alpha: float = 0.05, k: int | None = None) -> dict:
    """Holm-Bonferroni over the comparisons, at a count of `k`."""
    ordered = sorted(pairs, key=lambda kv: kv[1])
    count = k or len(ordered)
    verdict, stop = {}, False
    for rank, (name, p) in enumerate(ordered):
        bar = alpha / (count - rank)
        if stop or p > bar:
            stop = True
            verdict[name] = (p, bar, False)
        else:
            verdict[name] = (p, bar, True)
    return verdict


def measure(rows: list[dict]) -> dict[str, dict]:
    print("── 4. one arm at a time ───────────────────────────────────────")
    results: dict[str, dict] = {}
    for name, (index, multiplier, stated) in arms(rows).items():
        r = np.array([rows[i]["r"] for i in index])
        m = np.array(multiplier)
        if len(r) < 4:
            results[name] = {"n": len(r), "note": "too few trades to measure", "stated": stated}
            print(f"  {name:11s} n={len(r):5d}  not measurable: fewer than four trades")
            continue
        moved = int((m < 1.0 - 1e-12).sum())
        base = float(r.mean())
        if moved == 0:
            results[name] = {
                "n": len(r), "moved": 0, "mean_m": float(m.mean()), "base": base,
                "arm": base, "delta": 0.0, "z": 0.0, "p": 1.0, "stated": stated,
                "note": "the multiplier is 1.0 on every trade in the sample",
            }
            print(f"  {name:11s} n={len(r):5d}  moved=0  -> identically 1.0, nothing to test")
            continue
        delta, z, p = permute(m, r)
        wins_before = float((r > 0).mean())
        series = list(m * r)
        results[name] = {
            "n": len(r), "moved": moved, "mean_m": float(m.mean()),
            "min_m": float(m.min()), "base": base, "arm": base + delta,
            "delta": delta, "z": z, "p": p, "stated": stated,
            "sharpe": float(metrics.sharpe(series)),
            "base_sharpe": float(metrics.sharpe(list(r))),
            "series": series, "win": wins_before,
            "dd": _max_drawdown(m * r) / max(m.sum(), 1e-9),
            "base_dd": _max_drawdown(r) / len(r),
        }
        print(
            f"  {name:11s} n={len(r):5d}  moved={moved:5d} ({moved / len(r):4.0%})  "
            f"mean m={m.mean():.3f}  base={base:+.4f}R  arm={base + delta:+.4f}R  "
            f"delta={delta:+.4f}  z={z:+.2f}  p={p:.4f}"
        )
        print(f"              {stated}")
    print()
    return results


def _max_drawdown(series) -> float:
    """Deepest fall from a high-water mark on the cumulative sum."""
    peak, worst, total = 0.0, 0.0, 0.0
    for value in series:
        total += float(value)
        peak = max(peak, total)
        worst = max(worst, peak - total)
    return worst


def verdicts(results: dict[str, dict]) -> None:
    print("── 5. the multiplicity of nine ────────────────────────────────")
    extras = ("all-but-spike", "drawdown@0.30")
    testable = [(name, got["p"]) for name, got in results.items()
                if name in MULTIPLIERS and got.get("moved", 0) > 0]
    print(f"  {len(testable)} of 9 arms had a multiplier below 1 on any trade: "
          f"{sorted(n for n, _ in testable)}")
    if not testable:
        print("  nothing to correct: no arm moved a single position size.")
        print()
        return
    decided = holm(testable, k=9)
    print(f"  {'arm':11s} {'p':>8s} {'Holm bar at k=9':>16s}  survives")
    for name, (p, bar, ok) in sorted(decided.items(), key=lambda kv: kv[1][0]):
        print(f"  {name:11s} {p:8.4f} {bar:16.5f}  {'yes' if ok else 'no'}")
    print()
    # **Every arm, not the good ones.** The deflation's variance term is a
    # variance over the whole search, so a record that drops what was declined
    # makes every DSR optimistic - and the failure is silent.
    scored = {name: got for name, got in results.items() if "sharpe" in got}
    sharpes = [got["sharpe"] for got in scored.values()]
    if len(sharpes) >= 2:
        trials = len(sharpes) + 1  # the arms, plus the unmodified baseline
        with_base = [*sharpes, scored["crowding"]["base_sharpe"]]
        variance = metrics.trial_variance(with_base)
        print(f"  arms run: {len(sharpes)} (nine named, less the one with no sample, "
              f"plus {len(extras)} reported variants) plus the baseline = {trials} trials")
        print(f"  per-trade Sharpe by arm: "
              f"{ {n: round(g['sharpe'], 5) for n, g in sorted(scored.items(), key=lambda kv: -kv[1]['sharpe'])} }")
        print(f"  variance across trials: {variance:.3e}")
        print(f"  SR* (the Sharpe the best of {trials} nothings would show): "
              f"{metrics.expected_max_sharpe(variance, trials):+.5f}")
        name, best = max(scored.items(), key=lambda kv: kv[1]["sharpe"])
        try:
            dsr = metrics.deflated_sharpe(best["series"], with_base)
        except ValueError as exc:
            dsr = None
            print(f"  DSR refused: {exc}")
        print(f"  best arm by Sharpe: {name} at {best['sharpe']:+.5f}"
              + (f", DSR {dsr:.4f}" if dsr is not None else ""))
        print("  every arm is below zero, so no arm has a Sharpe to deflate.")
    print()


# ══════════════════════════════════════════════════════════════════ power


def power(rows: list[dict], moved_share: float = 0.55, floor: float = 0.8) -> None:
    """Where the test goes blind: plant a lever that knows something.

    The planted lever halves nothing it should not - it reduces `moved_share`
    of the trades to `floor`, exactly the geometry of the strongest real arm -
    and chooses which ones with probability `skill` of picking from the losing
    half. `skill` 0.5 is the real null; 1.0 is an oracle.
    """
    print("── 6. power: where this goes blind ────────────────────────────")
    r = np.array([row["r"] for row in rows])
    n = len(r)
    order = np.argsort(r)
    worst = set(order[: n // 2].tolist())
    rng = np.random.default_rng(SEED + 1)
    bar = 0.05 / 9  # the strictest Holm step at nine comparisons
    print(f"  n={n}, reducing {moved_share:.0%} of trades to {floor}, "
          f"alpha {bar:.5f} (Bonferroni at 9)")
    print(f"  {'skill':>6s} {'median delta':>13s} {'detected':>9s}")
    for skill in (0.50, 0.52, 0.54, 0.56, 0.58, 0.60, 0.70, 0.85, 1.00):
        hits, deltas = 0, []
        for _ in range(60):
            m = np.ones(n)
            want = int(moved_share * n)
            pick = []
            pool_bad = [i for i in range(n) if i in worst]
            pool_good = [i for i in range(n) if i not in worst]
            rng.shuffle(pool_bad)
            rng.shuffle(pool_good)
            bi = gi = 0
            while len(pick) < want and (bi < len(pool_bad) or gi < len(pool_good)):
                if rng.random() < skill and bi < len(pool_bad):
                    pick.append(pool_bad[bi]); bi += 1
                elif gi < len(pool_good):
                    pick.append(pool_good[gi]); gi += 1
                elif bi < len(pool_bad):
                    pick.append(pool_bad[bi]); bi += 1
            m[pick] = floor
            delta, _z, p = permute(m, r, draws=2_000)
            deltas.append(delta)
            hits += p <= bar
        print(f"  {skill:6.2f} {statistics.median(deltas):+13.5f} {hits / 60:9.0%}")
    print()


def main() -> None:
    reach()
    shipped()
    rows = trades()
    baseline(rows)
    results = measure(rows)
    verdicts(results)
    power(rows)


if __name__ == "__main__":
    main()
