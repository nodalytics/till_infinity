"""Many instruments at once: the vector observation the family lacked.

Every other member here observes a **scalar**. `relating.Relating` works around
that for a hedge by putting the other legs in the observation *row*, which is
the right shape for a regression - one leg explained by the others - and the
wrong shape for two questions:

* **Cross-impact.** Lillo (arXiv:2105.00521) measures the response of asset `j`
  to an order on asset `i` as non-zero and about **five times smaller** than
  the self-response. That is a statement about a matrix, and a regression
  cannot hold one: it has a dependent leg and the others are inputs, so it
  cannot say how `j` responds to `i` *and* how `i` responds to `j`.
* **A basket with no dependent leg.** A pairs book asks "how much of the others
  per one of this". A panel asks "which of these is away from where the rest
  imply it should be", which is symmetric and has no privileged instrument.

`Panel` is the member with a genuinely vector observation: `n` latent values,
`n` readings at a time, an `n`-square covariance that carries the cross terms,
and process noise with off-diagonals so that a move in one instrument informs
the filter about the others.

## A factor and reverting idiosyncratics, because free walks have nothing to
## deviate from

The first version of this was `n` correlated random walks, and it did not work
for the reason that is obvious in hindsight: a random walk **absorbs** a
dislocation. Instrument 2 was given a persistent 2.0 shift halfway through a
3,000-bar fixture and its mean absolute residual afterwards was **1.31**
against 1.31 and 1.34 for the two that had not moved. Nothing separated,
because a free walk has no level to be away from.

So the state is a **common factor** plus one **mean-reverting idiosyncratic**
per instrument:

    value_i(t) = factor(t) + idio_i(t)
    factor  random-walks       - the thing they share, and it may go anywhere
    idio_i  reverts to zero    - the thing that makes a deviation temporary

Observation row `i` is `[1, 0, .., 1, .., 0]`: the factor plus that
instrument's own idiosyncratic, which is a genuinely vector observation of an
`n + 1` state. The reversion is what makes `idio_i` a *spread* rather than a
second walk, and `theta` is a half-life in hours like every other rate here.

That also fixes what the correlated-noise version was reaching for. The
instruments share information through the **factor** rather than through a
correlation nobody fitted, and the factor is a state with its own uncertainty
instead of a parameter.

## `spread_of` is the reading, and it is not a z-score of a precomputed spread

Each instrument's **idiosyncratic**, in units of its own uncertainty. The usual
construction - a rolling standard deviation of a hand-built spread - cannot
tell "this instrument moved" from "the factor moved and this one did not
follow". This can, because the two are different states.

## Nothing here publishes

Nulls, both named: `n` independent `linear` members - which is this with
`rho = 0` - on held-out likelihood; and for any trading reading, the same
cost line as everything else, against a desk that has already measured the
relationship trade at a gross Sharpe of +0.27 and a net of **-0.97**.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

HOUR = 3600.0

#: Process noise per instrument, per hour.
WANDER = 1e-3

#: Correlation of the process noise between instruments: how much of each
#: latent move is shared. **Not fitted.**
SHARED = 0.5


def _solve(matrix: list[list[float]], rhs: list[list[float]]) -> list[list[float]]:
    """`matrix^-1 @ rhs` by Gauss-Jordan with partial pivoting.

    Written out because `n` is small and numpy is transitive rather than
    declared. `tests/test_statespace.py` checks it against `numpy.linalg.solve`,
    which is the module rule: anything hand-written arrives with a reference.
    """
    size = len(matrix)
    width = len(rhs[0])
    work = [list(matrix[i]) + list(rhs[i]) for i in range(size)]
    for col in range(size):
        pivot = max(range(col, size), key=lambda r: abs(work[r][col]))
        if abs(work[pivot][col]) < 1e-15:
            raise ValueError("singular innovation covariance")
        work[col], work[pivot] = work[pivot], work[col]
        scale = work[col][col]
        work[col] = [v / scale for v in work[col]]
        for row in range(size):
            if row == col:
                continue
            factor = work[row][col]
            if factor:
                work[row] = [a - factor * b for a, b in zip(work[row], work[col], strict=True)]
    return [row[size : size + width] for row in work]


@dataclass(slots=True)
class Panel:
    """A common factor plus one reverting idiosyncratic per instrument."""

    size: int = 2
    #: Process noise on the **factor**, per hour. The shared component is a
    #: random walk: it may go anywhere and nothing reverts it.
    wander: float = WANDER
    #: Process noise on each idiosyncratic, per hour.
    idio_wander: float = WANDER
    #: Reversion rate of the idiosyncratics, per hour. `ln 2 / theta` is the
    #: half-life of a dislocation - **the parameter a pairs desk actually
    #: cares about**, because it is how long a spread takes to close. Not
    #: fitted; `diagnostics.fit_both` is the pattern.
    theta: float = 0.1

    #: State: the factor first, then one idiosyncratic per instrument.
    state_values: list[float] = field(default_factory=list)
    #: What each idiosyncratic reverts **to**, fixed at the first reading.
    #:
    #: **Reverting to zero was wrong and the fixture showed it.** Instruments
    #: sit at permanent different levels - 100, 50 and 20 in the test - and
    #: those offsets land in the idiosyncratics at initialisation. With a
    #: reversion target of zero the filter spends every step fighting a level
    #: difference that is not a dislocation, and the idiosyncratic z-scores
    #: came out at 610, 105 and 505 when the only real dislocation was one
    #: instrument moved by 2.0.
    #:
    #: Same shape as `relating.Relating`'s centring: a quantity that reverts
    #: has to revert to where it lives, and the first reading is the best
    #: causal estimate of where that is.
    anchors: list[float] = field(default_factory=list)
    covariance: list[list[float]] = field(default_factory=list)

    at: float | None = None
    seen: int = 0
    loglike: float = 0.0
    burn: int = 10
    existence: float = 1.0
    standardised: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        width = self.size + 1
        if not self.state_values:
            self.state_values = [0.0] * width
        if not self.covariance:
            self.covariance = [[1.0 if i == j else 0.0 for j in range(width)] for i in range(width)]
        if not self.standardised:
            self.standardised = [0.0] * self.size

    # ------------------------------------------------------------- the reading

    @property
    def factor(self) -> float:
        """The shared component. What the whole panel is doing."""
        return self.state_values[0]

    def implied(self, index: int) -> float:
        """What the panel says instrument `index` should be."""
        return self.state_values[0] + self.state_values[index + 1]

    @property
    def values(self) -> list[float]:
        return [self.implied(i) for i in range(self.size)]

    @property
    def value(self) -> float:
        return self.implied(0) if self.size else 0.0

    @property
    def rate(self) -> float:
        return 0.0

    @property
    def sd(self) -> float:
        return self._row_spread(0)

    @property
    def last_standardised(self) -> float:
        return self.standardised[0] if self.standardised else 0.0

    def _row(self, index: int) -> list[float]:
        row = [0.0] * (self.size + 1)
        row[0] = 1.0
        row[index + 1] = 1.0
        return row

    def _row_spread(self, index: int) -> float:
        row = self._row(index)
        total = sum(
            row[i] * self.covariance[i][j] * row[j]
            for i in range(self.size + 1)
            for j in range(self.size + 1)
        )
        return math.sqrt(max(total, 0.0))

    def spread_of(self, index: int) -> float:
        """One instrument's idiosyncratic, in units of its own uncertainty.

        **The stat-arb reading.** Persistent, because the idiosyncratic
        reverts rather than walks - a dislocation stays visible until it
        closes, where a free walk would absorb it within a few bars.
        """
        variance = self.covariance[index + 1][index + 1]
        spread = math.sqrt(max(variance, 0.0))
        if spread <= 0:
            return 0.0
        anchor = self.anchors[index] if self.anchors else 0.0
        return (self.state_values[index + 1] - anchor) / spread

    def half_life(self) -> float:
        """Hours for a dislocation to close by half. `inf` if nothing reverts."""
        return math.log(2.0) / self.theta if self.theta > 0 else math.inf

    def state(self) -> tuple[float, ...]:
        return tuple(self.state_values)

    def output(self) -> tuple[float, ...]:
        return tuple(self.values)

    def observation(self) -> tuple[tuple[float, ...], ...]:
        """`C`: row `i` is the factor plus instrument `i`'s idiosyncratic."""
        return tuple(tuple(self._row(i)) for i in range(self.size))

    def transition(self, dt_hours: float) -> tuple[tuple[float, ...], ...]:
        """Factor holds; idiosyncratics decay toward zero."""
        keep = math.exp(-self.theta * max(dt_hours, 0.0))
        width = self.size + 1
        return tuple(
            tuple((1.0 if i == 0 else keep) if i == j else 0.0 for j in range(width))
            for i in range(width)
        )

    def at_time(self, when: float) -> float:
        """The first instrument, with its dislocation decayed to `when`.

        **This is where the reversion earns its place.** A free walk forecasts
        a dislocation forward unchanged; this says it closes, and how fast.
        """
        elapsed = 0.0
        if self.at is not None:
            elapsed = max((float(when) - self.at) / HOUR, 0.0)
        keep = math.exp(-self.theta * elapsed)
        anchor = self.anchors[0] if self.anchors else 0.0
        return self.state_values[0] + anchor + keep * (self.state_values[1] - anchor)

    def band(self, when: float, sigmas: float = 2.0) -> tuple[float, float]:
        elapsed = 0.0
        if self.at is not None:
            elapsed = max((float(when) - self.at) / HOUR, 0.0)
        half = sigmas * math.sqrt(max(self._row_spread(0) ** 2 + self.wander * elapsed, 0.0))
        middle = self.at_time(when)
        return (middle - half, middle + half)

    # ------------------------------------------------------------- the filter

    def predict(self, when: float, control: float = 0.0) -> None:  # noqa: ARG002
        if self.at is None:
            self.at = float(when)
            return
        dt = (float(when) - self.at) / HOUR
        self.at = float(when)
        if dt <= 0.0:
            return
        width = self.size + 1
        keep = math.exp(-self.theta * dt)
        anchors = self.anchors or [0.0] * self.size
        self.state_values = [
            self.state_values[0],
            *[a + keep * (v - a) for v, a in zip(self.state_values[1:], anchors, strict=True)],
        ]
        transition = [1.0] + [keep] * self.size
        self.covariance = [
            [
                transition[i] * self.covariance[i][j] * transition[j]
                + ((self.wander if i == 0 else self.idio_wander) * dt if i == j else 0.0)
                for j in range(width)
            ]
            for i in range(width)
        ]

    def update(
        self,
        measured: float | Sequence[float],
        noise: float | Sequence[float],
        when: float | None = None,
    ) -> float:
        """Fold in one reading **per instrument**. Returns the first innovation."""
        readings = [float(measured)] if isinstance(measured, int | float) else list(measured)
        if len(readings) != self.size:
            raise ValueError(
                f"this panel holds {self.size} instruments and was given "
                f"{len(readings)}. A panel that changes width mid-stream is a "
                "different model, not the same one short a column."
            )
        spreads = [float(noise)] * self.size if isinstance(noise, int | float) else list(noise)
        if when is not None and self.at is None:
            self.at = float(when)
        width = self.size + 1

        if self.seen == 0:
            # The factor takes the average and the idiosyncratics the rest,
            # which is the only split that does not privilege an instrument.
            middle = sum(readings) / len(readings)
            self.state_values = [middle] + [r - middle for r in readings]
            self.anchors = [r - middle for r in readings]
            for i in range(width):
                self.covariance[i][i] = max(spreads[min(i, self.size - 1)], 1e-12)
            self.seen = 1
            self.existence = 1.0
            return 0.0

        rows = [self._row(i) for i in range(self.size)]
        innovations = [readings[i] - self.implied(i) for i in range(self.size)]
        # PH' is width x size; S = H P H' + R is size x size.
        ph = [
            [
                sum(self.covariance[a][b] * rows[i][b] for b in range(width))
                for i in range(self.size)
            ]
            for a in range(width)
        ]
        s = [
            [
                sum(rows[i][a] * ph[a][j] for a in range(width))
                + (max(spreads[i], 0.0) if i == j else 0.0)
                for j in range(self.size)
            ]
            for i in range(self.size)
        ]
        try:
            gain = _transpose(_solve(s, _transpose(ph)))
        except ValueError:
            return innovations[0]

        self.standardised = [
            innovations[i] / math.sqrt(s[i][i]) if s[i][i] > 0 else 0.0 for i in range(self.size)
        ]
        if self.seen >= self.burn:
            self.loglike += _gaussian(innovations, s)

        for a in range(width):
            self.state_values[a] += sum(gain[a][j] * innovations[j] for j in range(self.size))
        updated = [
            [
                self.covariance[a][b] - sum(gain[a][i] * ph[b][i] for i in range(self.size))
                for b in range(width)
            ]
            for a in range(width)
        ]
        self.covariance = [
            [0.5 * (updated[a][b] + updated[b][a]) for b in range(width)] for a in range(width)
        ]
        self.seen += 1
        self.existence = min(1.0, self.existence + (1.0 - self.existence) * 0.5)
        return innovations[0]


def _transpose(matrix: list[list[float]]) -> list[list[float]]:
    return [list(row) for row in zip(*matrix, strict=True)]


def _gaussian(innovations: list[float], s: list[list[float]]) -> float:
    """Multivariate Gaussian log density of the innovations under `S`.

    By Cholesky, because the determinant and the quadratic form come out of
    the same factorisation and a separate inverse would be both slower and
    less stable.
    """
    size = len(innovations)
    lower = [[0.0] * size for _ in range(size)]
    for i in range(size):
        for j in range(i + 1):
            total = s[i][j] - sum(lower[i][k] * lower[j][k] for k in range(j))
            if i == j:
                if total <= 0:
                    return 0.0
                lower[i][j] = math.sqrt(total)
            else:
                lower[i][j] = total / lower[j][j]
    # Solve L y = innovation by forward substitution; |y|^2 is the quadratic.
    y = [0.0] * size
    for i in range(size):
        y[i] = (innovations[i] - sum(lower[i][k] * y[k] for k in range(i))) / lower[i][i]
    quadratic = sum(v * v for v in y)
    log_det = 2.0 * sum(math.log(lower[i][i]) for i in range(size))
    return -0.5 * (size * math.log(2.0 * math.pi) + log_det + quadratic)
