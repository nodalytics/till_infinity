"""Fit and judge Deriv's own-law tables: the N-bar move of a mechanics-only index, from its bars.

`research/docs/deriv-variants.md`: Boom/Crash, DEX, Range Break and Drift Switch publish mechanics
but no volatility, and their feeds are memoryless, so the N-bar log return is the N-fold
convolution of the one-bar log return. Quoted from that convolution - fitted on history, drawn by
Monte Carlo - the envelope beat production's empirical, live-unit envelope by 3-7% pinball at
20-50 bars with coverage flat by regime, and AgACI on top made it worse.

The tables ship as data (`till_infinity/models/deriv_law.json`, read by `structures/vol/envelope.py`
through `shared/frozen.py`) rather than being built online from each series' resolved moves, so a
newly followed index quotes a calibrated band from its first bar - the doc's point that the
convolved law "needs a history" is met by the history the table was fitted on.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

import numpy as np

from ..prices.models import Bar
from ..structures.vol import envelope as ev

#: Monte Carlo draws per table; 40,000 as the study used.
SIMS = 40_000
#: Fewest one-bar returns a table is fitted from.
MIN_BARS = 2_000


def one_bar(bars: Sequence[Bar]) -> np.ndarray:
    """One-bar log returns, close to close, oldest first."""
    close = np.array([b.close for b in bars], dtype=float)
    close = close[close > 0]
    r = np.diff(np.log(close))
    return r[np.isfinite(r)]


def table(returns: np.ndarray, n: int, *, seed: int = 0) -> list[float]:
    """The `LAW_LEVELS` quantiles of the n-fold sum of iid draws from `returns`."""
    rng = np.random.default_rng(seed)
    draws = rng.choice(returns, size=(SIMS, n)).sum(axis=1)
    return [round(float(q), 10) for q in np.quantile(draws, ev.LAW_LEVELS)]


def fit(series: Mapping[tuple[str, str], Sequence[Bar]]) -> dict:
    """A spec with a table per (feed, interval, horizon) whose feed is a mechanics-only index."""
    tables: dict[str, list[float]] = {}
    for (symbol, interval), bars in series.items():
        feed = ev._canonical(symbol)
        if not ev.own_law_family(feed):
            continue
        r = one_bar(bars)
        if len(r) < MIN_BARS:
            continue
        for n in ev.HORIZONS:
            tables[f"{feed}|{interval}|{n}"] = table(r, n)
    return {
        "recipe": ev.LAW_RECIPE,
        "names": list(ev.LAW_NAMES),
        "tables": tables,
        "trained": datetime.now(UTC).strftime("%Y-%m-%d"),
    }


def _pinball(y: np.ndarray, q: np.ndarray, level: float) -> float:
    d = y - q
    return float(np.mean(np.maximum(level * d, (level - 1) * d)))


def score(
    spec: dict, series: Mapping[tuple[str, str], Sequence[Bar]], since: float
) -> dict[str, dict]:
    """The table's quotes against production's empirical envelope on bars from `since` on.

    Per (horizon): P10/P90 coverage and pinball of both, pooled over every scored series. The
    empirical envelope is production's own `Envelope` fed the production unit (`Ranges`), warmed
    on the bars before `since`, so the comparison is what the table would replace.
    """
    from ..structures.vol.ranges import Ranges

    out: dict[str, dict] = {}
    for n in ev.HORIZONS:
        law_y, law_q, emp_y, emp_q = [], [], [], []
        for (symbol, interval), bars in series.items():
            feed = ev._canonical(symbol)
            got = spec.get("tables", {}).get(f"{feed}|{interval}|{n}")
            if not got:
                continue
            env, ranges = ev.Envelope(horizon=n), Ranges()
            closes = [b.close for b in bars]
            for i, b in enumerate(bars):
                ranges.observe(b.open, b.high, b.low, b.close)
                bps = ranges.ewma_tr_bps
                if bps <= 0 or b.close <= 0:
                    continue
                env.observe(b.close, bps / 10_000)
                # Both quote the next n bars from this close: the empirical envelope as it now
                # stands, the table as it always does.
                if b.time >= since and i + n < len(bars) and env.warm:
                    y = math.log(closes[i + n] / b.close)
                    law_y.append(y)
                    law_q.append([ev.table_quantile(got, t) for t in ev.TARGETS])
                    emp_y.append(y)
                    emp_q.append([z * env.sigma for z in env.quote])
        if not law_y:
            continue
        ly, lq = np.array(law_y), np.array(law_q)
        ey, eq = np.array(emp_y), np.array(emp_q)
        row = {"n": len(ly)}
        for name, y, q in (("law", ly, lq), ("empirical", ey, eq)):
            row[f"{name}_cover10"] = round(float(np.mean(y <= q[:, 0])), 4)
            row[f"{name}_cover90"] = round(float(np.mean(y <= q[:, 2])), 4)
            row[f"{name}_pinball"] = round(
                sum(_pinball(y, q[:, i], t) for i, t in enumerate(ev.TARGETS)), 8
            )
        out[str(n)] = row
    return out


#: What the retrain contest requires of a table set, judged per horizon on the hold-out.
LAW_GATES: dict[str, float] = {
    # no worse than the empirical envelope it replaces
    "pinball_ratio": 1.0,
    # P10 / P90 coverage within this many points of 10% / 90%
    "cover_points": 1.5,
}


def gate(scores: dict[str, dict]) -> list[str]:
    """Every reason not to promote a table set; empty means promote."""
    if not scores:
        return ["no mechanics-only Deriv series to judge"]
    reasons = []
    for n, row in scores.items():
        ratio = row["law_pinball"] / row["empirical_pinball"] if row["empirical_pinball"] else 1.0
        if ratio > LAW_GATES["pinball_ratio"]:
            reasons.append(f"N={n}: pinball {ratio:.3f} of the empirical envelope's")
        for target, key in ((0.1, "law_cover10"), (0.9, "law_cover90")):
            if abs(row[key] - target) * 100 > LAW_GATES["cover_points"]:
                reasons.append(f"N={n}: P{round(target * 100)} held {row[key]:.1%}")
    return reasons


def family_of(feed: str) -> str:
    """The own-law family a feed belongs to (`boom_`, `crash_`, ...), or ""."""
    name = ev._canonical(feed)
    return next((f for f in ev.OWN_LAW_FAMILIES if name.startswith(f)), "")


def cell_passes(row: dict) -> bool:
    """Whether one (family, interval, horizon) cell's scores clear `LAW_GATES`."""
    ratio = row["law_pinball"] / row["empirical_pinball"] if row["empirical_pinball"] else 1.0
    if ratio > LAW_GATES["pinball_ratio"]:
        return False
    return all(
        abs(row[key] - target) * 100 <= LAW_GATES["cover_points"]
        for target, key in ((0.1, "law_cover10"), (0.9, "law_cover90"))
    )


def select(
    spec: dict, series: Mapping[tuple[str, str], Sequence[Bar]], since: float
) -> tuple[dict, list[dict]]:
    """Keep only the tables whose (family, interval, horizon) cell passes on bars from `since`.

    `research/docs/deriv-variants.md`'s memoryless premise holds for Boom, Crash and DEX but not
    everywhere: Drift Switch switches its drift, so a convolution of its one-bar move understates
    its N-bar spread (P10 / P90 13-17% / 83-87% at 3m-30m), and Range Break's pinball is worse at
    1h and 4h. A cell that fails keeps the empirical envelope. Returns the pruned spec and every
    cell's scores.
    """
    groups: dict[tuple[str, str], dict[tuple[str, str], Sequence[Bar]]] = {}
    for key, bars in series.items():
        fam = family_of(key[0])
        if fam:
            groups.setdefault((fam, key[1]), {})[key] = bars
    keep: set[str] = set()
    report = []
    for (fam, interval), group in sorted(groups.items()):
        for n, row in score(spec, group, since).items():
            ok = cell_passes(row)
            report.append({"family": fam, "interval": interval, "n": int(n), "pass": ok, **row})
            if ok:
                keep |= {f"{ev._canonical(s)}|{interval}|{n}" for s, _ in group}
    tables = {k: v for k, v in spec.get("tables", {}).items() if k in keep}
    return {**spec, "tables": tables}, report
