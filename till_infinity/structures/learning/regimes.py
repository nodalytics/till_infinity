"""Which market this is, learned online rather than named in advance.

Everything in this package conditions on the shape of price. `sessions.py`
conditions on the hour. Nothing conditions on **what kind of market it is right
now** - whether this is the quiet drift where a level holds or the violent
stretch where it is run - and the strategies that read these signals are
selected by an operator editing a list, once, for all conditions.

The replay in [replay.md](../../research/replay.md) is why this is a measurement
and not a switch. Regime separates real outcomes - quiet beat wild at every stop
width over 49,338 touches - and it is **small next to the stop and the entry**,
which dominate it by an order of magnitude. So this labels the market and
records how each strategy did in each label. It does not choose.

## Why clustering rather than thresholds

Named windows and hand-cut thresholds are the folk version, and they have the
same problem here that they have with sessions: the boundaries are asserted, and
an asserted boundary is a free parameter that never gets measured. Clustering
puts the boundaries where the data actually separates, and moves them when the
market changes - which an instrument that has doubled its typical volatility
since the thresholds were written badly needs.

Online, because a batch fit would be stale the day after it ran and would need
refitting per instrument forever.

## The labels are ordered, not arbitrary

A k-means cluster id is a memory address, not a meaning: the cluster called 2
today may be the one called 0 after the next restart, and a per-regime scoreboard
keyed on it would silently pool unrelated conditions. So the clusters are sorted
by how energetic their centre is and named in that order. The names then mean the
same thing across restarts even as the centres move, which is the property a
record kept over weeks needs.

## Everything it reads is scale-free

Volatility in basis points is not comparable between gold and EURUSD, so none of
the inputs are levels. `stretch` is current volatility over its own long-run
level, `regime` is where it sits in its own recent history, `activity` is volume
against this instrument's own typical bar. A cluster found on one instrument
therefore means the same thing on another, which is what makes one model across
the book honest rather than convenient.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from river import cluster, preprocessing

from ..state import Restorable

#: How many regimes to find. Four because the replay bucketed four and the
#: comparison is worth keeping legible; the clustering is what decides where
#: the boundaries actually fall.
REGIMES = 4

#: Names in order of how energetic the cluster's centre is. See the module note
#: on why the ordering matters more than the names.
NAMES: tuple[str, ...] = ("quiet", "normal", "busy", "wild")

#: Observations before a label is worth acting on or recording against. Below
#: this the centres are still chasing the first few points.
WARMUP = 200

#: The scale-free readings a regime is judged from. Levels are deliberately
#: absent: basis points are not comparable across instruments, and a model that
#: pooled them would be describing the instrument rather than the moment.
FEATURES: tuple[str, ...] = (
    "vol_stretch",
    "regime",
    "activity",
    "hour_vol_share",
    "forecast_ratio",
    "sweep_rate",
)


def _model():
    return preprocessing.StandardScaler() | cluster.KMeans(n_clusters=REGIMES, seed=7)


@dataclass(slots=True)
class Regimes(Restorable):
    """An online partition of market conditions, and what happened in each."""

    _model: object = field(default_factory=_model)
    _seen: int = 0
    #: Cluster id -> a running mean of how energetic that cluster is, used only
    #: to order the labels. Kept separately from the model because river does
    #: not promise a stable ordering of its centres.
    _energy: dict[int, list[float]] = field(default_factory=dict)
    #: (label, strategy) -> [trades, total R]. The scoreboard this exists for.
    _record: dict[str, list[float]] = field(default_factory=dict)

    def observe(self, features: dict[str, float]) -> str:
        """Fold one reading in and return the regime it belongs to."""
        x = {k: float(features.get(k) or 0.0) for k in FEATURES}
        self._model.learn_one(x)
        self._seen += 1
        got = self._model.predict_one(x)
        if got is None:
            return ""
        # Energy is what orders the names. `stretch` above 1 is livelier than
        # this instrument's own normal, and `regime` is where it sits in its
        # own recent range - both scale-free, so the ordering means the same
        # thing on every instrument.
        energy = x["vol_stretch"] + x["regime"] + x["activity"]
        seen = self._energy.setdefault(int(got), [0.0, 0.0])
        seen[0] += 1.0
        seen[1] += energy
        return self.label(int(got))

    def label(self, cluster_id: int) -> str:
        """The name for a cluster, by where its energy ranks among the others."""
        if not self.warm or cluster_id not in self._energy:
            return ""
        means = {
            cid: (total / count if count else 0.0) for cid, (count, total) in self._energy.items()
        }
        order = sorted(means, key=lambda cid: means[cid])
        try:
            rank = order.index(cluster_id)
        except ValueError:
            return ""
        # Spread the ranks over the names, so fewer live clusters than names
        # still land at the ends rather than bunching at "quiet".
        if len(order) == 1:
            return NAMES[len(NAMES) // 2]
        step = (len(NAMES) - 1) / (len(order) - 1)
        return NAMES[min(len(NAMES) - 1, round(rank * step))]

    @property
    def warm(self) -> bool:
        return self._seen >= WARMUP

    # ------------------------------------------------------------ scoreboard

    def record(self, label: str, strategy: str, r: float) -> None:
        """Note what a strategy made in this regime, in R."""
        if not label or not strategy:
            return
        got = self._record.setdefault(f"{label}/{strategy}", [0.0, 0.0])
        got[0] += 1.0
        got[1] += r

    def standings(self, label: str = "") -> list[tuple[str, int, float]]:
        """(regime/strategy, trades, mean R), worst first.

        Worst first on purpose: the useful question of a scoreboard like this
        is which pairing to stop, and a list sorted best-first buries it.
        """
        out = []
        for key, (count, total) in self._record.items():
            if label and not key.startswith(f"{label}/"):
                continue
            if count:
                out.append((key, int(count), total / count))
        return sorted(out, key=lambda row: row[2])
