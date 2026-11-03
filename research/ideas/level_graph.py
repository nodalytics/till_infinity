"""The level transition graph, and whether centrality is worth anything.

Runs `research/docs/level-graph-prereg.md`. Read the pre-registration first;
this file is the harness and does not restate the claim or the pass rule.

**Every null arm, the level book and the volatility unit are imported from
`level_shield.py` unchanged.** That is the point rather than convenience:
`null-structure-claims-on-the-same-detector` requires the null to walk through
the same detector with the same bar geometry, and `level-shield.md` is the
study this one has to be comparable to - it measured 1 of 210 cells beating its
hardest null with real *below* the null in 188. A difference in result here
must not be reducible to a difference in how a level was drawn.

## Node identity, which is the one thing a transition graph has to get right

A level's price drifts: `Levels` returns `lv.at(when)`, so the same level is a
slightly different number on every bar. Identifying nodes by price would make
every bar's book a fresh set of nodes and every edge a self-loop.

So a node is a **bin**, `round(price / (tol * unit))` at the bin's first
appearance, with `unit` the trailing volatility at that moment. A bin is
therefore a band of width `tol` volatility units fixed when the level was first
seen, and a level that drifts within its band stays the same node. This is
stated here because it is the degree of freedom that could manufacture
structure, and `tol` is swept rather than chosen.

**Dwell is not an edge.** Re-entering the node price has just left is counted
as a dwell and never as a self-loop: a single oscillation between two
neighbouring prices would otherwise dominate the weighted degree of both.

## Causality

The graph at anchor `t` is built only from bars strictly before `t`, and the
outcome is read strictly after. `open-gap-filters-are-lookahead` is the
standing cost of getting this wrong - `drawing.gaps` emits only *unfilled*
gaps, so using it as a bias read +0.50R a trade out of nothing.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

import research.ideas.level_shield as shield

#: Volatility-unit half-width of a node's band. Swept: it is the degree of
#: freedom that could manufacture structure.
TOLS: tuple[float, ...] = (0.25, 0.5, 1.0)

#: Outcome distances, in volatility units, matching `level_shield.py` so the
#: two studies' numbers sit side by side.
REACHES: tuple[float, ...] = (1.0, 2.0, 3.0)

#: Volatility strata. `topology-restates-volatility` is the most likely
#: explanation of any positive result here, so nothing is reported pooled
#: without its per-stratum twin.
STRATA = 5

#: Draws per null arm. Sixteen, not four: `fear-greed.md` measured a
#: hardest-of-N test at four draws reading +0.093 where sixteen read -0.037,
#: because four draws understate an arm whose own sd is 0.09-0.12.
DRAWS = 16

#: The arms that decide the verdict, hardest-of taken over all of them.
ARMS: tuple[str, ...] = ("bar-shuffle", "walk-geometry", "garch-bars")

#: Two Deriv volatility indices, carried in every cell.
#: `carry-an-independent-placebo-pair` caught two leaks in one run, and
#: `the-placebo-arm-selects-the-null` rejects any null a placebo passes.
PLACEBO: tuple[str, ...] = ("nzdusd", "usdcad")

#: `Range_Break` is a range by construction, so its graph must show two
#: dominant nodes with a heavy edge between them; `Drift_Switch` is the regime
#: control and must not. A harness that misses the first is broken rather than
#: null - `range-break-is-the-level-positive-control`.
CONTROLS: tuple[str, ...] = ("Range_Break", "Drift_Switch")

FEEDS: tuple[str, ...] = (
    "eurusd",
    "gbpusd",
    "audusd",
    "usdcad",
    "usdchf",
    "usdjpy",
    "usdcnh",
    "nzdusd",
    "gold",
    "btc",
    "eth",
    "spx500",
    "us100",
    "sol",
)


@dataclass(frozen=True, slots=True)
class Graph:
    """A transition graph and the four centralities, per node."""

    edges: dict[tuple[int, int], int]
    dwell: dict[int, int]
    #: `1 / time taken` summed per edge. `a-magnet-is-a-shared-reference` says
    #: to use the time exponent rather than the return rate, and
    #: `a-return-rate-is-geometry` is why: the origin's 82% return rate is
    #: matched by a distance-matched placebo on every class.
    speed: dict[tuple[int, int], float]

    @property
    def nodes(self) -> list[int]:
        found: set[int] = set(self.dwell)
        for a, b in self.edges:
            found.add(a)
            found.add(b)
        return sorted(found)

    def degree(self) -> dict[int, int]:
        out: dict[int, int] = defaultdict(int)
        seen: dict[int, set[int]] = defaultdict(set)
        for a, b in self.edges:
            seen[a].add(b)
            seen[b].add(a)
        for node in self.nodes:
            out[node] = len(seen[node])
        return dict(out)

    def weighted(self) -> dict[int, float]:
        out: dict[int, float] = defaultdict(float)
        for (a, b), n in self.edges.items():
            out[a] += float(n)
            out[b] += float(n)
        return {node: out[node] for node in self.nodes}

    def pagerank(self, damping: float = 0.85, rounds: int = 60) -> dict[int, float]:
        """Degree with the neighbours' importance folded in.

        Undirected, because an edge here records that price moved between two
        prices and the direction of that move is a separate question this
        study does not ask.
        """
        nodes = self.nodes
        if not nodes:
            return {}
        out: dict[int, set[int]] = defaultdict(set)
        for a, b in self.edges:
            out[a].add(b)
            out[b].add(a)
        rank = dict.fromkeys(nodes, 1.0 / len(nodes))
        for _ in range(rounds):
            nxt = dict.fromkeys(nodes, (1.0 - damping) / len(nodes))
            sunk = 0.0
            for node in nodes:
                links = out[node]
                if not links:
                    sunk += rank[node]
                    continue
                share = damping * rank[node] / len(links)
                for other in links:
                    nxt[other] += share
            if sunk:
                for node in nodes:
                    nxt[node] += damping * sunk / len(nodes)
            rank = nxt
        return rank

    def betweenness(self) -> dict[int, float]:
        """Brandes on an unweighted undirected graph.

        The centrality that matches "many participants compute this price" most
        directly: the share of shortest paths routed through a node.
        """
        nodes = self.nodes
        out: dict[int, set[int]] = defaultdict(set)
        for a, b in self.edges:
            out[a].add(b)
            out[b].add(a)
        score = dict.fromkeys(nodes, 0.0)
        for source in nodes:
            stack: list[int] = []
            paths: dict[int, list[int]] = defaultdict(list)
            sigma = dict.fromkeys(nodes, 0.0)
            dist = dict.fromkeys(nodes, -1)
            sigma[source] = 1.0
            dist[source] = 0
            queue = [source]
            while queue:
                node = queue.pop(0)
                stack.append(node)
                for other in out[node]:
                    if dist[other] < 0:
                        dist[other] = dist[node] + 1
                        queue.append(other)
                    if dist[other] == dist[node] + 1:
                        sigma[other] += sigma[node]
                        paths[other].append(node)
            delta = dict.fromkeys(nodes, 0.0)
            while stack:
                node = stack.pop()
                for before in paths[node]:
                    if sigma[node]:
                        delta[before] += (sigma[before] / sigma[node]) * (1.0 + delta[node])
                if node != source:
                    score[node] += delta[node]
        # Undirected, so each pair is counted twice.
        return {node: value / 2.0 for node, value in score.items()}


def centrality(graph: Graph, kind: str) -> dict[int, float]:
    """One of the four, by name. A function and not a dict of lambdas, because
    a lambda built inside the anchor loop closes over the loop's `graph` and
    would read whichever graph the loop had reached by the time it was
    called."""
    if kind == "degree":
        return {k: float(v) for k, v in graph.degree().items()}
    if kind == "weighted":
        return graph.weighted()
    if kind == "betweenness":
        return graph.betweenness()
    if kind == "pagerank":
        return graph.pagerank()
    raise ValueError(f"{kind!r} is not a centrality this harness computes")


def bins_of(book: list[tuple[float, int]], unit: float, tol: float) -> dict[int, float]:
    """This bar's levels as `node -> price`.

    A node is `round(price / width)` with `width = tol * unit`, so a level
    drifting inside its band stays the same node. See the module docstring:
    identifying a node by its price would make every bar a fresh node set.
    """
    width = tol * unit
    if not (width > 0.0) or not math.isfinite(width):
        return {}
    return {round(price / width): price for price, _ in book if price > 0.0}


def build(
    series: shield.Series,
    books: list[list[tuple[float, int]]],
    unit: np.ndarray,
    *,
    tol: float,
    upto: int,
) -> Graph:
    """The graph from bars `[0, upto)`. Causal by construction."""
    edges: Counter[tuple[int, int]] = Counter()
    dwell: Counter[int] = Counter()
    speed: dict[tuple[int, int], float] = defaultdict(float)
    where: int | None = None
    since = 0
    for i in range(min(upto, len(series.close))):
        u = float(unit[i])
        if not (u > 0.0):
            continue
        here = bins_of(books[i], u, tol)
        if not here:
            continue
        close = float(series.close[i])
        width = tol * u
        node = round(close / width)
        if node not in here:
            continue
        if where is None:
            where, since = node, i
            continue
        if node == where:
            # A dwell, never a self-loop: one oscillation between two
            # neighbouring prices would otherwise dominate both their degrees.
            dwell[node] += 1
            continue
        key = (min(where, node), max(where, node))
        edges[key] += 1
        took = max(1, i - since)
        speed[key] += 1.0 / float(took)
        where, since = node, i
    return Graph(edges=dict(edges), dwell=dict(dwell), speed=dict(speed))


@dataclass(frozen=True, slots=True)
class Row:
    feed: str
    venue: str
    interval: str
    arm: str
    draw: int
    tol: float
    reach: float
    #: Which centrality this row is. **Named `centrality` and not `kind`**:
    #: the row-type marker is `kind`, and `{"kind": "cell", **asdict(row)}`
    #: let this field overwrite it, so every cell in the smoke run was written
    #: with `kind` reading "degree" and a reporter filtering on "cell" would
    #: have found none of them.
    centrality: str
    stratum: int
    nodes: int
    edges: int
    n_high: int
    n_low: int
    travelled_high: float
    travelled_low: float
    gap: float
    dwell_r: float


def _spearman(a: list[float], b: list[float]) -> float:
    """Rank correlation, for the "is this dwell renamed" check.

    A centrality that tracks dwell at r > 0.9 is dwell, and the
    pre-registration says so before the result.
    """
    if len(a) < 3:
        return float("nan")

    def rank(xs: list[float]) -> list[float]:
        order = sorted(range(len(xs)), key=lambda i: xs[i])
        out = [0.0] * len(xs)
        for place, i in enumerate(order):
            out[i] = float(place)
        return out

    ra, rb = rank(a), rank(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb, strict=True))
    da = math.sqrt(sum((x - ma) ** 2 for x in ra))
    db = math.sqrt(sum((y - mb) ** 2 for y in rb))
    return num / (da * db) if da > 0 and db > 0 else float("nan")


def measure(
    series: shield.Series,
    *,
    tol: float,
    reach: float,
    draws_arm: str,
    draw: int,
    stride: int,
    warm: int,
) -> list[Row]:
    """Every (centrality, stratum) cell for one series.

    The outcome is `level_shield`'s: given a fixed distance, does price travel
    it before returning to the node. The claim is **not** that a central node
    is reached more often, but that the outcome differs between a central node
    and a **distance-matched, stratum-matched** peripheral one - matching on
    distance being the single control that turned the magnet claim from 44.9%
    into nothing.
    """
    books = shield.book_path(series)
    unit = shield.units(series, 48)
    n = len(series.close)
    anchors = list(range(max(warm, 240), n - int(reach * 48) - 1, stride))
    if len(anchors) < 20:
        return []

    out: list[Row] = []
    for name in ("degree", "weighted", "betweenness", "pagerank"):
        # Collected per stratum, then reported per stratum. Pooling first and
        # splitting later is how `pooled-medians-invert-subgroups` happened.
        per: dict[int, list[tuple[float, float, float]]] = defaultdict(list)
        dwell_pairs: list[tuple[float, float]] = []
        seen_nodes = 0
        seen_edges = 0
        for at in anchors:
            graph = build(series, books, unit, tol=tol, upto=at)
            nodes = graph.nodes
            if len(nodes) < 4:
                continue
            scores = centrality(graph, name)
            if not scores:
                continue
            seen_nodes = max(seen_nodes, len(nodes))
            seen_edges = max(seen_edges, len(graph.edges))
            dwelt = graph.dwell
            dwell_pairs.extend(
                (scores.get(node, 0.0), float(dwelt.get(node, 0))) for node in nodes
            )

            u = float(unit[at])
            if not (u > 0.0):
                continue
            close = float(series.close[at])
            # Candidate nodes: the book's prices, with their centrality and
            # their distance from here in volatility units.
            here = bins_of(books[at], u, tol)
            picks = [
                (scores.get(node, 0.0), abs(price - close) / u, price)
                for node, price in here.items()
                if abs(price - close) / u > 0.1
            ]
            if len(picks) < 2:
                continue
            middle = sorted(s for s, _, _ in picks)[len(picks) // 2]
            high = [p for p in picks if p[0] > middle]
            low = [p for p in picks if p[0] <= middle]
            if not high or not low:
                continue
            # **Distance matching.** Each high-centrality candidate is paired
            # with the peripheral one closest to it in distance, and the pair
            # is dropped if they differ by more than a fifth of a volatility
            # unit. An unmatched comparison is the magnet claim again.
            stratum = min(STRATA - 1, max(0, _stratum(unit, at)))
            for _, dist, price in high:
                mate = min(low, key=lambda c: abs(c[1] - dist))
                if abs(mate[1] - dist) > 0.2:
                    continue
                per[stratum].append(
                    (
                        _travelled(series, at, price, u, reach),
                        _travelled(series, at, mate[2], u, reach),
                        dist,
                    )
                )

        dwell_r = _spearman([a for a, _ in dwell_pairs], [b for _, b in dwell_pairs])
        for stratum, rows in sorted(per.items()):
            if len(rows) < 20:
                continue
            hi = sum(r[0] for r in rows) / len(rows)
            lo = sum(r[1] for r in rows) / len(rows)
            out.append(
                Row(
                    feed=series.feed,
                    venue=series.venue,
                    interval=series.interval,
                    arm=draws_arm,
                    draw=draw,
                    tol=tol,
                    reach=reach,
                    centrality=name,
                    stratum=stratum,
                    nodes=seen_nodes,
                    edges=seen_edges,
                    n_high=len(rows),
                    n_low=len(rows),
                    travelled_high=hi,
                    travelled_low=lo,
                    gap=hi - lo,
                    dwell_r=dwell_r,
                )
            )
    return out


def _stratum(unit: np.ndarray, at: int) -> int:
    """Which quintile of the trailing volatility this anchor sits in.

    Computed from the history **before** the anchor, so the stratum is a
    causal label rather than a quantile of the whole sample - which would let
    the future decide which bucket a trade was in.
    """
    past = unit[max(0, at - 1000) : at]
    past = past[past > 0]
    if len(past) < 50:
        return 0
    here = float(unit[at])
    return min(STRATA - 1, int(np.searchsorted(np.quantile(past, [0.2, 0.4, 0.6, 0.8]), here)))


def _travelled(series: shield.Series, at: int, price: float, unit: float, reach: float) -> float:
    """1.0 if price travelled `reach` units away from `price` before returning
    to it, else 0.0. `level_shield`'s outcome, so the numbers are comparable."""
    want = reach * unit
    side = 1.0 if float(series.close[at]) > price else -1.0
    horizon = min(len(series.close), at + 1 + int(48 * max(1.0, reach)))
    for i in range(at + 1, horizon):
        away = (float(series.close[i]) - price) * side
        if away >= want:
            return 1.0
        if away <= 0.0:
            return 0.0
    return 0.0


def arms_for(series: shield.Series, rng: random.Random, fitted=None):
    """The three deciding arms, from `level_shield` unchanged."""
    return {
        "bar-shuffle": lambda: shield.bar_shuffle(series, rng),
        "walk-geometry": lambda: shield.walk_geometry(series, rng),
        "garch-bars": lambda: shield.garch_bars(series, rng, fitted),
    }


def job(args: tuple) -> list[dict]:
    feed, interval, store, draws, tols, reaches, stride, warm = args
    rows: list[dict] = []
    try:
        con = sqlite3.connect(store, uri=True)
        series = shield.load(con, feed, interval)
        con.close()
        if series is None:
            return [{"kind": "error", "feed": feed, "interval": interval, "error": "no series"}]

        fitted = None
        try:
            returns = np.diff(np.log(series.close))
            fitted = shield.fit_garch(returns)
        except Exception as exc:  # the arm is reported missing, not faked
            rows.append(
                {
                    "kind": "note",
                    "feed": feed,
                    "interval": interval,
                    "note": f"garch unfitted: {exc!r}"[:160],
                }
            )

        for tol in tols:
            for reach in reaches:
                rows.extend(
                    {"kind": "cell", **asdict(row)}
                    for row in measure(
                        series,
                        tol=tol,
                        reach=reach,
                        draws_arm="real",
                        draw=0,
                        stride=stride,
                        warm=warm,
                    )
                )
                for name in ARMS:
                    for draw in range(draws):
                        rng = random.Random(hash_of(feed, interval, name, draw))
                        made = arms_for(series, rng, fitted)[name]()
                        rows.extend(
                            {"kind": "cell", **asdict(row)}
                            for row in measure(
                                made,
                                tol=tol,
                                reach=reach,
                                draws_arm=name,
                                draw=draw,
                                stride=stride,
                                warm=warm,
                            )
                        )
    except Exception as exc:
        import traceback

        rows.append(
            {
                "kind": "error",
                "feed": feed,
                "interval": interval,
                "error": repr(exc),
                "where": traceback.format_exc(limit=4).splitlines()[-3:],
            }
        )
    return rows


def hash_of(*parts) -> int:
    """A seed that does not move between processes.

    **`hash()` of a tuple containing a string is salted per process**, so a
    surrogate seeded with one is not reproducible and two workers draw
    different arms for the same cell. That defect was found in four harnesses
    on this desk.
    """
    import hashlib

    text = "|".join(str(p) for p in parts)
    return int(hashlib.sha256(text.encode()).hexdigest()[:12], 16)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--store", default=getattr(shield, "STORE", ""))
    ap.add_argument("--draws", type=int, default=DRAWS)
    ap.add_argument("--feeds", default="")
    ap.add_argument("--intervals", default="1d")
    ap.add_argument("--tols", default=",".join(str(t) for t in TOLS))
    ap.add_argument("--reaches", default=",".join(str(r) for r in REACHES))
    ap.add_argument("--stride", type=int, default=20)
    ap.add_argument("--warm", type=int, default=240)
    ap.add_argument("--controls", action="store_true", help="add the two generated controls")
    args = ap.parse_args(argv)

    feeds = tuple((args.feeds or " ".join(FEEDS)).replace(",", " ").split())
    if args.controls:
        feeds = feeds + CONTROLS
    intervals = tuple(args.intervals.replace(",", " ").split())
    tols = tuple(float(t) for t in args.tols.split(","))
    reaches = tuple(float(r) for r in args.reaches.split(","))

    where = Path(args.out)
    where.mkdir(parents=True, exist_ok=True)
    sink = where / "cells.jsonl"

    jobs = [
        (feed, interval, args.store, args.draws, tols, reaches, args.stride, args.warm)
        for interval in intervals
        for feed in feeds
    ]
    print(
        f"{len(jobs)} jobs, {args.draws} draws an arm, {len(tols)} tols x "
        f"{len(reaches)} reaches, {args.workers} workers -> {sink}",
        file=sys.stderr,
    )
    started = time.time()
    done = 0
    with sink.open("w") as fh:
        if args.workers <= 1:
            streams = (job(one) for one in jobs)
        else:
            from concurrent.futures import ProcessPoolExecutor

            pool = ProcessPoolExecutor(max_workers=args.workers)
            streams = pool.map(job, jobs)
        for rows in streams:
            done += 1
            for row in rows:
                fh.write(json.dumps(row) + "\n")
            fh.flush()
            print(f"  {done}/{len(jobs)} {time.time() - started:.0f}s", file=sys.stderr, flush=True)
    print(f"wrote {sink}")


if __name__ == "__main__":
    main()
