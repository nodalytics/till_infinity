"""An echo state network on the Deriv Volatility grid: the one architecture that is defensible at 2,800 samples.

**Why a reservoir and not a trained net.** `seqlab.GRID` runs from 3m to 1d and
the sample collapses across it - 1h holds 50,000 bars, 4h about 16,900, 1d under
2,800. A gradient-trained recurrent net at the top of that grid has more
parameters than it has rows and will memorise; whatever it scores there is a
statement about its capacity, not about the feed. An echo state network moves the
entire nonlinearity into a **fixed random reservoir** and trains one linear
readout by ridge regression, so the only thing fitted is a ridge solve whose
effective degrees of freedom are `sum_j s_j/(s_j + lambda)` and therefore *known*
rather than hoped for. That is why this arm owns the 1d/12h/8h end of the study
and why it is separate from the LSTM arm rather than a variant of it.

**What is being asked, and what the answer is expected to be.**
`research/deriving.md` proves `E[net] = -(c/2) x turnover` for any predictable
position on a martingale and `research/rebuilding.md` confirmed boosted models
find nothing on these feeds. A Volatility index is geometric Brownian motion at a
published constant sigma. So **direction here is a null calibration, not a hunt**:
it is expected at AUC 0.50, and an AUC above it is first evidence of a leak in
this file. The open question is **magnitude**. `seqlab.main()` gives, on
Volatility 75 Index at 1h, naive srel 0.8802 against unconditional-mean srel
0.6691, with a simulated GBM at the named sigma returning 0.8809/0.6642 - the
real feed and the simulated null are indistinguishable at three decimal places.
This harness asks whether a reservoir beats the unconditional mean on `logvol`
where the last realised value cannot. The prediction, written before the run:
**it cannot on the constant-sigma members**, and `seqlab.SPOT_UP` - the two
instruments whose names say the variance moves - is the only place in the family
where it could.

## Two arms, and the second is the one with value

### Arm 1 - the sweep, as a null calibration with a floor under it

Spectral radius, leak rate, reservoir size, input scaling and ridge lambda, over
the grid. This is cheap in a way a trained net is not: **one state sweep and one
matrix solve per configuration**, and because the Gram matrix `Phi^T Phi` does
not depend on the target, every target and every shuffled control on the same
reservoir is free once the Gram exists. The lambda axis is free for the same
reason - one symmetric eigendecomposition of the Gram serves every lambda.

Four models are scored **on identical rows**, which is the whole point of the
arrangement: the unconditional mean, the naive last-realised value, a HAR linear
regression on the log of the three realised volatilities, a **plain ridge on the
28 `seqlab` features with no reservoir at all**, and the ESN. The static ridge is
the one that decides the question this arm exists to answer, because the ESN's
readout reads `[features, state]` and therefore contains the static ridge as a
subspace. Any gap between them is recurrence and nothing else.

### Arm 2 - memory capacity, which is the measurement rather than the score

`groundgru.py` ran a recurrent net as a **system-identification instrument** -
the eigenvalues of its Jacobian against the Ulam transfer-operator spectrum - and
found that what the net's spectrum reports is its own training horizon rather
than the process's relaxation time. An ESN admits the same question with none of
that confound, because **its dynamics are not trained**: the Jacobian around
`h = 0` is `(1-a)I + aW` in closed form, its spectrum is known before any data is
seen, and the only fitted object is a linear map out of the state.

That makes Jaeger's memory capacity directly measurable. `MC_k` is the squared
correlation between `u_{t-k}` and the best linear readout of `h_t`; `MC` is the
sum over `k`. Driven by an iid input it is a property of the reservoir alone and
is bounded by the reservoir size - which is the implementation check below.
Driven by **the feed's own signal** it becomes a property of the feed: it is how
much of that feed's past a fixed random nonlinear compression retains, and it is
measured against **a simulated GBM at the same sigma on the same reservoir with
the same row count**. If a real Volatility feed needs more memory than pure GBM
at its own named sigma, that gap is a finding about the generator, and it is one
no score on this page could give.

The phase surrogate sits between them and is what makes the gap interpretable. It
preserves the drive's entire power spectrum and therefore its entire linear
autocorrelation, and destroys everything else. `MC(real) > MC(gbm)` with
`MC(real) ~ MC(surrogate)` is linear memory - volatility clustering a HAR already
has. `MC(real) > MC(surrogate)` is memory no linear model can reach.

## The leak boundary, restated because it is where this class of study dies

Features and targets come from `seqlab` and nowhere else - `seqlab.build`,
`seqlab.targets`, `seqlab.walk_forward`, `seqlab.gbm_bars`,
`seqlab.phase_surrogate`, `seqlab.shuffle_target`. `seqlab.check_causality` runs
in the `check` stage before any score is printed.

Three places where a reservoir could leak that a static model cannot, and what is
done about each:

1. **The state trajectory is global.** `h_t` is a function of `u_0..u_t` only, so
   running it once over the whole series and slicing per fold is causal. It is
   also the only correct way to do it: resetting at a fold boundary would hand
   the test block a cold reservoir that the training block never had.
2. **Input scaling is a fitted statistic.** Columns entering the reservoir are
   standardised on the **first fold's training block alone** - the earliest rows
   in the series - so every test row is scaled by numbers computed strictly
   before it. Per-fold rescaling is not possible here without recomputing the
   trajectory per fold, and would buy nothing: the fold-0 block precedes
   everything.
3. **Ridge centring is per fold and exact.** The Gram is accumulated forward
   through the expanding windows and centred analytically at each fold end
   (`G_c = G - n mu mu^T`), so the intercept is the training block's own mean and
   never the test block's.

The washout is discarded from the head of the trajectory, which - with expanding
walk-forward windows - is the only washout that exists: every training block
starts at row 0, so a per-fold washout would discard the same rows twice. The
`check` stage measures the thing the washout is for directly, by running the
reservoir from two different random initial states on the same input and
reporting how far apart they are afterwards.

## What would count as failure, written before any number was read

1. **The run is void** if `seqlab.check_causality` reports any leaking feature.
2. **The implementation is wrong** if in-sample memory capacity on a *linear*
   reservoir driven by iid input exceeds the reservoir size. Jaeger's bound is
   `MC <= N` and it is exact, so a measured `MC` above `N` is an overfitting
   artefact in the readout and not a property of anything.
3. **The echo state property is not established** if two trajectories from
   different random initial states on the same input have not converged to 1e-9
   by the end of a 5,000-step run at `rho < 1`. The `rho > 1` rows are in the
   sweep precisely to find where that stops being true, and they are expected to
   fail it - a reservoir that has not forgotten its initial state is not reading
   the data. **The threshold is applied at the end of the run and not at the
   washout**, which is a correction to the first version of this condition: a
   reservoir at `leak = 0.05` contracts at roughly `1 - 0.05(1 - rho)` per step,
   so a gap still at 1e-4 a hundred steps in is a slow reservoir rather than a
   broken one, and the measurement that distinguishes them is whether the gap is
   still falling geometrically.
4. **The harness is leaking** if the direction arm clears AUC 0.52 on
   `seqlab.gbm_bars`, where the true answer is exactly 0.50 by construction.
5. **The reservoir is not reaching the readout** if the ESN and the static ridge
   return the same number to more digits than their fold spread allows.
6. **Every null on this page is void** if the harness does not find volatility
   clustering on a GARCH(1,1) built at the same per-bar variance as the null.
   `seqlab`'s own docstring names this: "if this harness cannot find volatility
   clustering on gold, *we found nothing on synthetics* is a statement about the
   harness and not about the synthetics." The simulated version of that control
   runs before any cell is scored, and the real one - `seqlab.REAL` - is carried
   through the full grid in its own table.
7. **A null without its power is not a result.** A sensitivity ladder runs
   GARCH(1,1) at six persistences against the row counts the real grid actually
   has, so every reported null comes with the amount of clustering that would
   have been caught at that sample size.
8. **The reservoir buys nothing** if its `logvol` out-of-sample R-squared against
   the training-block mean does not clear the same quantity on the simulated GBM
   null by more than the family-wise max-of-k null supports. That is a reportable
   result, not a failure of the run - and it is the predicted one.
9. **No claim from a single cell.** 22 symbols x 8 timeframes x several
   configurations is several thousand chances to see 0.53. `seqlab.max_of_k` is
   applied to the best cell against the best of the matched nulls, and the
   per-cell number is never the headline.

## The condition that fired, and what it changed

**Condition 3 fired on `rho = 1.4, leak = 0.05`, exactly where it was aimed** -
and the consequence reached further than the sweep. The first full run selected
the ridge penalty by GCV, a training-block criterion, and GCV **ranked that
configuration best in the entire 5,040-cell sweep** while its mean out-of-sample
R-squared was -30,545. Two causes, both properties of reservoirs rather than of
this implementation: a Gram with a condition number near 1e17, whose bottom
eigen-directions carry no training variance and therefore leave their weights
unconstrained; and a reservoir that has not forgotten its initial state, whose
state distribution drifts so that the test block is drawn from somewhere the
training block was not. **No training-block criterion can see the second.**

So the penalty is now chosen by walk-forward validation on a block that precedes
the test block, the eigen-spectrum is truncated rather than merely penalised, and
the penalty ladder is stated relative to the leading eigenvalue rather than
absolutely. All three selectors - minimum validation error, the
one-standard-error rule, and GCV - are reported side by side on every cell,
because which one is used turned out to matter more than any hyperparameter in
the sweep.

    ./.secrets/lab.sh run research/harness/seqesn.py STAGE=check OMP_NUM_THREADS=1
"""

from __future__ import annotations

import os

# Before numpy. Five other agents share this box; the footprint of this harness
# is WORKERS processes of one BLAS thread each, and a nested thread pool inside
# a process pool is how a 64-core machine becomes unusable for everyone on it.
for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
             "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_var, "1")

import json  # noqa: E402
import math  # noqa: E402
import time  # noqa: E402
from concurrent.futures import ProcessPoolExecutor  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
import scipy.sparse as sp  # noqa: E402
import scipy.sparse.linalg as spla  # noqa: E402

from research.harness import seqlab  # noqa: E402

STAGE = os.environ.get("STAGE", "check")
SEED = int(os.environ.get("SEED", "20260912"))
WORKERS = int(os.environ.get("WORKERS", "10"))
OUTDIR = Path(os.environ.get("OUTDIR", str(Path.home() / "till_infinity" / "logs")))
WASHOUT = int(os.environ.get("WASHOUT", "100"))
FOLDS = int(os.environ.get("NFOLDS", "5"))
HORIZON = int(os.environ.get("HORIZON", "1"))

#: Rows the sweep is allowed to use. The sweep measures the *shape* of the
#: hyperparameter surface, not a headline, and 20,000 rows is enough to see a
#: surface. The grid stage uses every row there is.
SWEEP_ROWS = int(os.environ.get("SWEEP_ROWS", "12000"))

#: Nonzeros per row of the reservoir matrix, held fixed rather than a density.
#: The cost of one state step is then independent of reservoir size, which is
#: what makes a 2,000-unit reservoir affordable on a 50,000-bar series.
IN_DEGREE = 10

#: Ridge penalties, **relative to the Gram's own leading eigenvalue** rather than
#: absolute. An absolute ladder was tried first and it is what broke the first
#: run of this harness: the Gram scales with the number of training rows and with
#: the reservoir's collinearity, so a fixed 1e-4 is severe regularisation on one
#: cell and none at all on the next. Free either way - one eigendecomposition of
#: the Gram serves every entry.
ALPHAS = 10.0 ** np.arange(-10.0, 4.5, 0.5)

#: Eigen-directions below this fraction of the leading one are dropped rather
#: than penalised. A reservoir at leak 0.05 has a Gram with a condition number
#: around 1e17, and the directions at the bottom of that spectrum are float64
#: noise: they carry no training variance, so ridge leaves their weights
#: unconstrained, and any test row with a component along them produces a
#: prediction of arbitrary size. **This is what produced out-of-sample
#: R-squared of -30,000 in the first sweep**, and truncation is the fix, not a
#: larger penalty.
RANK_EPS = 1e-10

#: Training rows the lognormal smearing factor is estimated from. A mean of
#: exponentials does not need 50,000 rows, and taking every one of them made the
#: train-block re-fit the most expensive line in the harness.
SMEAR_ROWS = 4_000

#: The sweep axes.
RHOS = (0.5, 0.7, 0.9, 0.95, 1.0, 1.05, 1.2, 1.4)
LEAKS = (0.05, 0.15, 0.4, 0.7, 1.0)
IN_SCALES = (0.05, 0.2, 0.8)
SIZES = (100, 300, 800)

#: The shortlist the full-grid stage carries. Chosen off the sweep by mean GCV -
#: a training-block criterion - and never by a test score.
SHORTLIST: tuple[tuple[int, float, float, float], ...] = (
    (100, 0.90, 0.40, 0.20),
    (300, 0.90, 0.15, 0.20),
    (300, 0.95, 0.40, 0.80),
    (300, 1.05, 0.70, 0.20),
    (600, 0.90, 0.15, 0.05),
    (600, 0.70, 1.00, 0.20),
)

#: Symbols the sweep runs on. Two constant-sigma members at opposite ends of the
#: family, one 1s variant, both Spot Up instruments, and a simulated null.
SWEEP_SYMBOLS = (
    "Volatility 25 Index",
    "Volatility 75 Index",
    "Volatility 100 (1s) Index",
    "Spot Up - Volatility Up Index",
    "Spot Up - Volatility Down Index",
)
SWEEP_TFS = ("1h", "4h", "1d")

#: Where the effort goes. `seqlab.GRID` is run in full, but these carry the
#: argument: they are the timeframes where a gradient-trained net cannot be run
#: honestly and a ridge readout can.
HEADLINE_TFS = ("4h", "6h", "8h", "12h", "1d")


# ==========================================================================
# The reservoir
# ==========================================================================


def _spectral_radius(mat) -> float:
    """Largest eigenvalue modulus, dense for small matrices and Arnoldi above."""
    n = mat.shape[0]
    if n <= 400:
        dense = mat.toarray() if sp.issparse(mat) else mat
        return float(np.max(np.abs(np.linalg.eigvals(dense))))
    try:
        val = spla.eigs(mat.astype(float), k=1, which="LM",
                        return_eigenvectors=False, maxiter=10_000, tol=1e-6)
        return float(np.abs(val[0]))
    except Exception:  # noqa: BLE001 - Arnoldi not converging is a real outcome
        # Power iteration on |W|, which bounds the radius from below and is
        # never silently wrong in a way that changes the sign of a conclusion.
        v = np.ones(n) / math.sqrt(n)
        absw = abs(mat)
        est = 0.0
        for _ in range(300):
            v = absw @ v
            est = float(np.linalg.norm(v))
            if est <= 0:
                return 1e-12
            v /= est
        return est


class Reservoir:
    """A fixed random recurrent map and nothing trained inside it.

    `h_t = (1-a) h_{t-1} + a f(W_in u_t + b + W h_{t-1})`, with `f` tanh by
    default and the identity when the linear memory-capacity bound is being
    checked. `W` is sparse with a fixed in-degree and rescaled to the requested
    spectral radius; `W_in` is dense because the input is 28 columns wide and a
    sparse 28-wide matrix saves nothing.
    """

    def __init__(self, n_in: int, size: int, rho: float, leak: float,
                 in_scale: float, rng: np.random.Generator, *,
                 activation: str = "tanh", bias_scale: float = 0.1):
        rows = np.repeat(np.arange(size), IN_DEGREE)
        cols = rng.integers(0, size, size * IN_DEGREE)
        vals = rng.normal(0.0, 1.0, size * IN_DEGREE)
        mat = sp.csr_matrix((vals, (rows, cols)), shape=(size, size))
        radius = _spectral_radius(mat)
        mat = mat * (rho / max(radius, 1e-12))
        # A dense matvec beats a sparse one below a few hundred units, where the
        # scipy call overhead dominates the arithmetic.
        self.w = mat.toarray() if size <= 256 else mat.tocsr()
        self.w_in = rng.uniform(-1.0, 1.0, (size, n_in)) * in_scale
        self.bias = rng.uniform(-1.0, 1.0, size) * bias_scale
        self.size, self.leak, self.rho = size, leak, rho
        self.activation = activation

    def run(self, u: np.ndarray, h0: np.ndarray | None = None) -> np.ndarray:
        """The state trajectory. Row `t` is a function of `u[0..t]` and nothing later."""
        u = np.atleast_2d(u.T).T if u.ndim == 1 else u
        n = len(u)
        drive = u @ self.w_in.T + self.bias
        out = np.empty((n, self.size))
        h = np.zeros(self.size) if h0 is None else h0.astype(float).copy()
        a, w = self.leak, self.w
        linear = self.activation == "linear"
        for t in range(n):
            pre = drive[t] + w @ h
            h = (1.0 - a) * h + a * (pre if linear else np.tanh(pre))
            out[t] = h
        return out


def esp_gap(res: Reservoir, u: np.ndarray, rng: np.random.Generator,
            washout: int = WASHOUT) -> dict:
    """How far apart two trajectories from different initial states stay.

    This is the echo state property measured rather than assumed. The reported
    quantity is not a single threshold at an arbitrary step: a leaky reservoir at
    `leak = 0.05` contracts at roughly `1 - 0.05(1 - rho)` per step, so a gap
    that is still 1e-4 after a hundred steps is a slow reservoir rather than a
    broken one. What matters is that the gap keeps falling geometrically, so both
    ends are reported along with the implied per-step contraction, and the
    condition is applied at the end of the run.
    """
    a = res.run(u, h0=rng.uniform(-0.5, 0.5, res.size))
    b = res.run(u, h0=rng.uniform(-0.5, 0.5, res.size))
    diff = np.abs(a - b).max(axis=1)
    at_wash = float(diff[min(washout, len(diff) - 1)])
    at_end = float(diff[-1])
    steps = max(len(diff) - washout - 1, 1)
    rate = float((max(at_end, 1e-300) / max(at_wash, 1e-300)) ** (1.0 / steps))
    return {"at_washout": at_wash, "at_end": at_end, "rate": rate}


# ==========================================================================
# Ridge over expanding windows, with every lambda free
# ==========================================================================


def _eig_block(gram: np.ndarray):
    """One truncated symmetric eigendecomposition, reused by every target and penalty."""
    s, vecs = np.linalg.eigh(gram)
    s = np.maximum(s, 0.0)
    top = float(s.max()) if s.size else 0.0
    keep = s > top * RANK_EPS
    if not keep.any():
        keep = s >= 0
    return s[keep], vecs[:, keep], top


def _ridge_path(eigs, bvec: np.ndarray):
    """Weights at every penalty on the ladder, from one decomposition."""
    s, vecs, top = eigs
    beta = vecs.T @ bvec
    return [(vecs @ (beta / (s + a * top)), a * top) for a in ALPHAS], beta


def _gcv_path(eigs, beta: np.ndarray, yc2: float, n_tr: int):
    """GCV at every penalty, from the eigenvalues alone.

    `RSS(l) = |y|^2 - sum_j beta_j^2 (s_j + 2l)/(s_j + l)^2` and
    `tr(H) = sum_j s_j/(s_j + l)`, so this costs nothing once the decomposition
    exists. **It is reported rather than used**, and the reason is the first
    sweep: ranked by mean GCV, the best configuration in the whole 5,040-cell
    sweep was N800 / rho 1.4 / leak 0.05, whose mean out-of-sample R-squared is
    -30,545. A training-block criterion cannot see the one failure that matters
    here - a reservoir without the echo state property is non-stationary, so its
    test states are drawn from a different distribution than its training states,
    and no amount of in-sample accounting reveals that.
    """
    s, _, top = eigs
    b2 = beta * beta
    out = []
    for a in ALPHAS:
        lam = a * top
        denom = s + lam
        rss = max(yc2 - float(np.sum(b2 * (s + 2.0 * lam) / (denom * denom))), 0.0)
        edf = float(np.sum(s / denom))
        slack = 1.0 - edf / n_tr
        out.append(((rss / n_tr) / (slack * slack) if slack > 1e-6 else np.inf, edf, rss / n_tr))
    return out


class FoldRidge:
    """Expanding-window ridge with the penalty chosen on a block the fit has not seen.

    Two things are accumulated forward through the series, each exactly once: the
    Gram `Phi^T Phi` and the cross-products `Phi^T y`. The Gram does not depend on
    the target, so every target and every shuffled control on one reservoir costs
    one extra matrix-by-vector rather than a second fit. That is why this arm can
    carry its controls beside every number instead of on a sample of cells.

    **The penalty is selected by walk-forward validation, not by GCV.** Each fold
    is fitted twice: once on rows `[0, inner)` and scored on the validation block
    `[inner + horizon, train_end)` to choose the penalty, then once on the whole
    of `[0, train_end)` at that penalty to predict the test block. Every row used
    to choose the penalty lies strictly before the test block, so the selection is
    causal - and unlike GCV it is computed on rows the fit did not see, which is
    the only way to notice that a reservoir's state distribution has drifted
    between the training block and the test block.

    Both breakpoints per fold are visited in one ascending pass, so the second fit
    costs no second traversal of the data.
    """

    def __init__(self, phi: np.ndarray, targets: dict[str, np.ndarray],
                 folds: list[tuple[np.ndarray, np.ndarray]], blocks: dict[str, slice],
                 *, horizon: int = 1, val_frac: float = 0.25):
        self.phi, self.targets, self.folds, self.blocks = phi, targets, folds, blocks
        self.horizon, self.val_frac = horizon, val_frac

    def _plan(self):
        """Breakpoints in ascending order, each tagged with what happens there."""
        plan: dict[int, list[tuple[str, int]]] = {}
        inner = {}
        for i, (tr, _) in enumerate(self.folds):
            end = int(tr[-1]) + 1
            cut = max(60, int(end * (1.0 - self.val_frac)) - self.horizon)
            cut = min(cut, end - 30)
            if cut < 40:
                cut = 0
            inner[i] = cut
            if cut:
                plan.setdefault(cut, []).append(("val", i))
            plan.setdefault(end, []).append(("fit", i))
        return sorted(plan.items()), inner

    def run(self) -> dict[str, dict[str, list]]:
        """One ascending pass; every slice of the design taken once, not once per target.

        The first working version of this method sliced the design inside the
        target loop - `self.phi[test][:, block] - mu[block]` - which is fancy
        indexing and therefore a **copy**, sixteen of them per fold, each the size
        of the block. On a 20,000-row series with an 800-unit reservoir that is
        about ten gigabytes of memory traffic per configuration, and the sweep
        went from arithmetic-bound to bandwidth-bound: the estimate went to three
        hours and the machine's load average to 44. Everything that depends only
        on (block, fold) is now hoisted above the target loop.
        """
        d = self.phi.shape[1]
        gram = np.zeros((d, d))
        psum = np.zeros(d)
        keys = list(self.targets)
        xy = {k: np.zeros(d) for k in keys}
        ysum = dict.fromkeys(keys, 0.0)
        yy = dict.fromkeys(keys, 0.0)
        out: dict[str, dict[str, list]] = {
            f"{blk}|{k}": {"pred": [], "truth": [], "rows": [], "gcv": [], "lam": [],
                           "edf": [], "trmean": [], "s2": [], "expfit": [],
                           "alpha": [], "gcv_pred": [], "se_pred": [],
                           "val_mse": [], "val_var": []}
            for blk in self.blocks for k in keys
        }
        picked: dict[tuple[int, str, str], tuple[int, int]] = {}
        steps, _ = self._plan()
        prev = 0
        for point, actions in steps:
            chunk = self.phi[prev:point]
            gram += chunk.T @ chunk
            psum += chunk.sum(axis=0)
            for k in keys:
                yk = self.targets[k][prev:point]
                xy[k] += chunk.T @ yk
                ysum[k] += float(yk.sum())
                yy[k] += float(yk @ yk)
            prev = point
            n_tr = point
            mu = psum / n_tr
            gram_c = gram - n_tr * np.outer(mu, mu)
            # The training rows the smearing factor is estimated on. A mean of
            # exponentials converges long before 20,000 rows, and taking every row
            # made this the most expensive line in the harness.
            fit_rows = (np.arange(point) if point <= SMEAR_ROWS
                        else np.linspace(0, point - 1, SMEAR_ROWS).astype(int))
            for name, sl in self.blocks.items():
                eigs = _eig_block(gram_c[sl, sl])
                shift = mu[sl]
                slices = {}
                for kind, i in actions:
                    if kind == "val":
                        rows = np.arange(point + self.horizon, int(self.folds[i][0][-1]) + 1)
                        slices[(kind, i)] = (rows, self.phi[rows][:, sl] - shift
                                             if len(rows) >= 20 else None)
                    else:
                        te = self.folds[i][1]
                        slices[(kind, i)] = (te, self.phi[te][:, sl] - shift)
                fit_block = self.phi[fit_rows][:, sl] - shift
                for k in keys:
                    ybar = ysum[k] / n_tr
                    bvec = xy[k][sl] - ysum[k] * mu[sl]
                    yc2 = yy[k] - ysum[k] * ybar
                    path, beta = _ridge_path(eigs, bvec)
                    gcvs = _gcv_path(eigs, beta, yc2, n_tr)
                    for kind, i in actions:
                        rows, block = slices[(kind, i)]
                        if kind == "val":
                            if block is None:
                                picked[(i, name, k)] = (-1, -1)
                                continue
                            truth = self.targets[k][rows]
                            errs = np.array([
                                float(np.mean((truth - (block @ w + ybar)) ** 2))
                                for w, _ in path])
                            best = float(errs.min())
                            # One-standard-error rule, in the direction the prior
                            # points: among penalties whose validation error is
                            # not distinguishable from the best, take the most
                            # regularised. The prior on these feeds is that there
                            # is nothing to find, so the tie-break is stated here
                            # rather than chosen after seeing which way it helps.
                            tol = best * (1.0 + 1.0 / math.sqrt(max(len(rows), 1)))
                            arg1 = int(np.max(np.flatnonzero(errs <= tol)))
                            picked[(i, name, k)] = (int(np.argmin(errs)), arg1)
                            rec = out[f"{name}|{k}"]
                            rec["val_mse"].append(best)
                            rec["val_var"].append(float(np.var(truth)))
                        else:
                            gcv_arg = int(np.argmin([g for g, _, _ in gcvs]))
                            arg, arg1 = picked.get((i, name, k), (-1, -1))
                            if arg < 0:
                                arg = arg1 = gcv_arg
                            w, lam = path[arg]
                            rec = out[f"{name}|{k}"]
                            rec["pred"].append(block @ w + ybar)
                            rec["gcv_pred"].append(block @ path[gcv_arg][0] + ybar)
                            rec["se_pred"].append(block @ path[arg1][0] + ybar)
                            rec["truth"].append(self.targets[k][rows])
                            rec["rows"].append(len(rows))
                            rec["gcv"].append(float(gcvs[arg][0]))
                            rec["lam"].append(float(lam))
                            rec["alpha"].append(float(ALPHAS[arg]))
                            rec["edf"].append(float(gcvs[arg][1]))
                            rec["trmean"].append(float(ybar))
                            rec["s2"].append(float(gcvs[arg][2]))
                            rec["expfit"].append(float(np.mean(np.exp(
                                np.clip(fit_block @ w + ybar, -40.0, 5.0)))))
        return out


# ==========================================================================
# Scoring
# ==========================================================================


def score_logvol(rec: dict[str, list], realised: np.ndarray,
                 folds: list[tuple[np.ndarray, np.ndarray]],
                 field: str = "pred") -> dict:
    """R-squared against the training-block mean, and srel on the realised scale.

    **R-squared here is literally the question.** The baseline subtracted is the
    training block's own mean of `logvol`, so `r2 = 0` is "exactly the
    unconditional mean" and anything positive is the reservoir beating it out of
    sample. The mean baseline therefore scores exactly 0.0000 by construction,
    which is the point: it is the axis, not a competitor.

    srel is carried beside it so this page can be read against
    `research/forecasting.md` and against `seqlab.main()`, which score on srel.
    **The conversion back to the volatility scale is not `exp(yhat)`**, and the
    correction is not cosmetic: `exp` of a predicted log is a conditional
    *geometric* mean while both of those pages report arithmetic means of
    realised volatility, so the raw exponential hands every model a systematic
    low bias that then looks like skill wherever the residual spread differs
    between models. The factor applied is Duan's smearing estimator in ratio
    form, `c = mean(rv_train) / mean(exp(yhat_train))`, computed on the
    **training block only** and applied identically to the mean baseline, to
    naive and to every fitted model. A parametric `exp(s2/2)` was tried first and
    is wrong here: it assumes the prediction is a conditional mean of the log
    with Gaussian residuals, which the naive predictor is not, and it inflated
    naive srel from 0.88 to 1.16 on a simulated null where `seqlab.main()`
    measures 0.8809.
    """
    sse = sst = 0.0
    preds, truths = [], []
    for i, (_, te) in enumerate(folds):
        p = np.asarray(rec[field][i], float)
        t = np.asarray(rec["truth"][i], float)
        sse += float(np.sum((t - p) ** 2))
        sst += float(np.sum((t - rec["trmean"][i]) ** 2))
        tr = folds[i][0]
        smear = float(np.mean(realised[tr])) / max(rec["expfit"][i], 1e-30)
        preds.append(np.exp(np.clip(p, -40.0, 5.0)) * smear)
        truths.append(realised[te])
    pred = np.concatenate(preds)
    truth = np.concatenate(truths)
    return {"r2": float(1.0 - sse / max(sst, 1e-30)),
            "srel": seqlab.srel(pred, truth),
            "rows": int(len(pred)),
            "lam": float(np.median(rec["lam"])),
            "edf": float(np.median(rec["edf"]))}


def score_direction(rec: dict[str, list], field: str = "pred") -> dict:
    """Row-weighted AUC across folds.

    Per fold rather than pooled: the readout's scale differs between folds
    because each is fitted on a different training block, and pooling scores
    across differently-calibrated folds turns a scale shift into a rank signal.
    """
    aucs, rows = [], []
    for i in range(len(rec[field])):
        p = np.asarray(rec[field][i], float)
        t = np.asarray(rec["truth"][i], float)
        if len(np.unique(t)) < 2:
            continue
        a = seqlab.auc(p, t.astype(int))
        if np.isfinite(a):
            aucs.append(a)
            rows.append(len(t))
    if not aucs:
        return {"auc": float("nan"), "rows": 0, "nstar": float("inf")}
    w = np.array(rows, float)
    a = float(np.sum(np.array(aucs) * w) / w.sum())
    return {"auc": a, "rows": int(w.sum()),
            "nstar": seqlab.nstar(a, 0.5, int(w.sum())),
            "lam": float(np.median(rec["lam"])), "edf": float(np.median(rec["edf"]))}


# ==========================================================================
# One cell: bars in, every model on identical rows out
# ==========================================================================


def prepare(bars: dict[str, np.ndarray], *, rows_cap: int = 0) -> dict:
    """Features, targets, folds - all from `seqlab`, all on one row set.

    Rows usable for `logvol` and for `direction` are intersected so that every
    model and every target is scored on the *same* rows. A model compared on a
    different row set than its baseline is the oldest way to manufacture a gap.
    """
    x, names = seqlab.build(bars)
    y = seqlab.targets(bars, horizon=HORIZON)
    ok = (np.isfinite(x).all(axis=1) & np.isfinite(y["logvol"])
          & np.isfinite(y["direction"]) & np.isfinite(y["realised"]))
    idx = np.flatnonzero(ok)
    if rows_cap and len(idx) > rows_cap:
        idx = idx[-rows_cap:]
    xs = x[idx]
    tgt = {k: v[idx] for k, v in y.items()}
    # The washout comes off the head of the trajectory. With expanding windows
    # every training block starts at row 0, so this is the only washout there is.
    n_avail = len(idx) - WASHOUT
    folds = seqlab.walk_forward(n_avail, folds=FOLDS, horizon=HORIZON)
    folds = [(tr + WASHOUT, te + WASHOUT) for tr, te in folds]
    zero_frac = float(np.mean(tgt["realised"] <= 1e-11))
    return {"x": xs, "names": names, "y": tgt, "folds": folds,
            "n": len(idx), "zero_rv_frac": zero_frac}


def design(prep: dict, res: Reservoir | None, *, pre_end: int) -> tuple[np.ndarray, dict]:
    """`[HAR(3) | features(28) | state(size)]`, every block a contiguous slice.

    Contiguity is not cosmetic: it means the HAR baseline, the static ridge, the
    state-only readout and the full ESN are **sub-blocks of one Gram matrix**, so
    all four are fitted from a single accumulation over the data. They are
    therefore guaranteed to be on identical rows by construction rather than by
    a convention someone has to keep.

    Input columns are standardised on rows `0..pre_end`, the first fold's own
    training block, so every test row is scaled by statistics computed strictly
    before it.
    """
    x, names = prep["x"], prep["names"]
    rv1 = np.log(np.maximum(x[:, names.index("rv1")], 1e-12))
    rv5 = np.log(np.maximum(x[:, names.index("rv5")], 1e-12))
    rv22 = np.log(np.maximum(x[:, names.index("rv22")], 1e-12))
    har = np.column_stack([rv1, rv5, rv22])

    mu = x[:pre_end].mean(axis=0)
    sd = x[:pre_end].std(axis=0)
    sd = np.where(sd > 1e-12, sd, 1.0)
    u = np.clip((x - mu) / sd, -12.0, 12.0)

    if res is None:
        phi = np.column_stack([har, u])
        return phi, {"har": slice(0, 3), "static": slice(3, phi.shape[1])}
    h = res.run(u)
    hm = h[:pre_end].mean(axis=0)
    hs = h[:pre_end].std(axis=0)
    hs = np.where(hs > 1e-9, hs, 1.0)
    phi = np.column_stack([har, u, (h - hm) / hs])
    p = 3 + u.shape[1]
    return phi, {"har": slice(0, 3), "static": slice(3, p),
                 "state": slice(p, phi.shape[1]), "esn": slice(3, phi.shape[1])}


def closed_form_baselines(prep: dict) -> dict:
    """The two baselines that are not a fit: the training mean and the last value.

    Both are computed on the same folds and the same rows as everything else, and
    both carry their own training-block residual variance so that the srel
    conversion back to the volatility scale is the same arithmetic for them as
    for the fitted models.
    """
    x, names, y, folds = prep["x"], prep["names"], prep["y"], prep["folds"]
    rv1 = np.log(np.maximum(x[:, names.index("rv1")], 1e-12))
    sign = x[:, names.index("sign")]
    lv = y["logvol"]
    out = {}

    def blank():
        return {"pred": [], "truth": [], "rows": [], "lam": [], "edf": [],
                "trmean": [], "gcv": [], "s2": [], "expfit": [], "alpha": [],
                "gcv_pred": [], "se_pred": [], "val_mse": [], "val_var": []}

    rec = blank()
    for tr, te in folds:
        rec["pred"].append(rv1[te])
        rec["gcv_pred"].append(rec["pred"][-1])
        rec["se_pred"].append(rec["pred"][-1])
        rec["alpha"].append(0.0)
        rec["truth"].append(lv[te])
        rec["rows"].append(len(te))
        rec["lam"].append(0.0)
        rec["edf"].append(0.0)
        rec["gcv"].append(float("nan"))
        rec["trmean"].append(float(lv[tr].mean()))
        resid = lv[tr] - rv1[tr]
        rec["s2"].append(float(np.mean(resid * resid)))
        rec["expfit"].append(float(np.mean(np.exp(np.clip(rv1[tr], -40.0, 5.0)))))
    out["naive|logvol"] = rec

    rec = blank()
    for tr, te in folds:
        mean_tr = float(lv[tr].mean())
        rec["pred"].append(np.full(len(te), mean_tr))
        rec["gcv_pred"].append(rec["pred"][-1])
        rec["se_pred"].append(rec["pred"][-1])
        rec["alpha"].append(0.0)
        rec["truth"].append(lv[te])
        rec["rows"].append(len(te))
        rec["lam"].append(0.0)
        rec["edf"].append(0.0)
        rec["gcv"].append(float("nan"))
        rec["trmean"].append(mean_tr)
        rec["s2"].append(float(np.var(lv[tr])))
        rec["expfit"].append(float(math.exp(min(mean_tr, 5.0))))
    out["mean|logvol"] = rec

    rec = blank()
    for tr, te in folds:
        rec["pred"].append(sign[te])
        rec["gcv_pred"].append(rec["pred"][-1])
        rec["se_pred"].append(rec["pred"][-1])
        rec["alpha"].append(0.0)
        rec["truth"].append(y["direction"][te])
        rec["rows"].append(len(te))
        rec["lam"].append(0.0)
        rec["edf"].append(0.0)
        rec["gcv"].append(float("nan"))
        rec["trmean"].append(0.0)
        rec["s2"].append(0.0)
        rec["expfit"].append(1.0)
        _ = tr
    out["naive|direction"] = rec
    return out


def evaluate(prep: dict, config: tuple[int, float, float, float], seed: int,
             *, with_shuffle: bool = True, light: bool = False) -> dict:
    """Every model on one cell at one reservoir configuration.

    `light` drops the state-only readout, which is the second large
    eigendecomposition per fold and is redundant wherever the question is
    "reservoir against static features" rather than "how much does the
    passthrough contribute". The sweep runs light; the grid does not.
    """
    size, rho, leak, in_scale = config
    folds = prep["folds"]
    if not folds:
        return {}
    pre_end = int(folds[0][0][-1]) + 1
    rng = np.random.default_rng(seed)
    res = Reservoir(prep["x"].shape[1], size, rho, leak, in_scale, rng)
    phi, blocks = design(prep, res, pre_end=pre_end)
    if light:
        blocks = {k: v for k, v in blocks.items() if k != "state"}

    y = prep["y"]
    targets = {"logvol": y["logvol"], "direction": y["direction"]}
    if with_shuffle:
        srng = np.random.default_rng(seed + 999)
        targets["logvol_shuffled"] = seqlab.shuffle_target(y["logvol"].copy(), srng)
        targets["direction_shuffled"] = seqlab.shuffle_target(y["direction"].copy(), srng)

    recs = FoldRidge(phi, targets, folds, blocks, horizon=HORIZON).run()
    recs.update(closed_form_baselines(prep))

    scored: dict[str, dict] = {}
    for key, rec in recs.items():
        if not rec["pred"]:
            continue
        model, tgt = key.split("|")
        if tgt.startswith("logvol"):
            scored[key] = score_logvol(rec, y["realised"], folds)
        else:
            scored[key] = score_direction(rec)
    # Three selectors on one fitted path, so the choice of selector is a
    # measurement on this page rather than a guess. `esn` is the minimum
    # validation error; `@1se` is the most-regularised penalty indistinguishable
    # from it; `@gcv` is the training-block criterion that broke the first run.
    scored["esn|logvol@gcv"] = score_logvol(recs["esn|logvol"], y["realised"], folds,
                                            field="gcv_pred")
    scored["esn|direction@gcv"] = score_direction(recs["esn|direction"], field="gcv_pred")
    scored["esn|logvol@1se"] = score_logvol(recs["esn|logvol"], y["realised"], folds,
                                            field="se_pred")
    scored["esn|direction@1se"] = score_direction(recs["esn|direction"], field="se_pred")
    # Configuration is selected on this: the walk-forward validation R-squared of
    # the ESN readout, averaged over folds. Every row behind it precedes the test
    # block it will be used on.
    ref = recs["esn|logvol"]
    val = float(np.mean([1.0 - m / max(v, 1e-30)
                         for m, v in zip(ref["val_mse"], ref["val_var"], strict=False)])
                ) if ref["val_mse"] else float("-inf")
    scored["_meta"] = {"size": size, "rho": rho, "leak": leak, "in_scale": in_scale,
                       "n": prep["n"], "folds": len(folds), "pre_end": pre_end,
                       "zero_rv_frac": prep["zero_rv_frac"],
                       "alpha": float(np.median(recs["esn|logvol"]["alpha"])),
                       "val_r2": val,
                       "gcv_esn_logvol": float(np.mean(recs["esn|logvol"]["gcv"]))}
    return scored


# ==========================================================================
# Memory capacity - Arm 2
# ==========================================================================


def memory_capacity(drive: np.ndarray, config: tuple[int, float, float, float],
                    seed: int, *, kmax: int = 0, activation: str = "tanh",
                    train_frac: float = 0.7, lam: float = 1e-3) -> dict:
    """Jaeger's MC on a one-dimensional drive, in sample and out of sample.

    `MC_k = corr^2(u_{t-k}, readout_k(h_t))`. The in-sample number is the
    textbook one and is what the `MC <= N` bound applies to; **the out-of-sample
    number is the one that is compared between feeds**, because with a reservoir
    wider than the training block the in-sample figure is a statement about
    degrees of freedom rather than about memory.

    The readout is fitted once per lag from one shared eigendecomposition of the
    state Gram, so a 300-lag profile costs one solve and 300 matrix-vector
    products.
    """
    size = config[0]
    kmax = kmax or min(2 * size, 400)
    rng = np.random.default_rng(seed)
    u = np.asarray(drive, float)
    u = (u - u.mean()) / max(u.std(), 1e-12)
    res = Reservoir(1, size, config[1], config[2], config[3], rng, activation=activation)
    h = res.run(u[:, None])

    lo = WASHOUT + kmax
    n = len(u)
    if n - lo < 4 * size or n - lo < 200:
        return {"mc_in": float("nan"), "mc_out": float("nan"), "n": int(n - lo),
                "profile": [], "half": float("nan")}
    cut = lo + int((n - lo) * train_frac)
    tr = np.arange(lo, cut)
    te = np.arange(cut, n)

    mu, sd = h[tr].mean(axis=0), np.maximum(h[tr].std(axis=0), 1e-12)
    a = (h[tr] - mu) / sd
    b = (h[te] - mu) / sd
    gram = a.T @ a
    s, vecs = np.linalg.eigh(gram)
    s = np.maximum(s, 0.0)
    scale = lam * max(float(np.mean(s)), 1e-12) * 1.0

    mc_in = mc_out = 0.0
    profile = []
    for k in range(1, kmax + 1):
        ytr = u[tr - k]
        yte = u[te - k]
        ybar = ytr.mean()
        bvec = a.T @ (ytr - ybar)
        w = vecs @ ((vecs.T @ bvec) / (s + scale))
        p_in = a @ w + ybar
        p_out = b @ w + ybar
        ci = _corr2(p_in, ytr)
        co = _corr2(p_out, yte)
        mc_in += ci
        mc_out += co
        profile.append(co)
    prof = np.array(profile)
    total = max(prof.sum(), 1e-12)
    half = int(np.searchsorted(np.cumsum(prof), 0.5 * total) + 1)
    return {"mc_in": float(mc_in), "mc_out": float(mc_out), "n": int(n - lo),
            "kmax": kmax, "profile": [float(v) for v in prof[:60]],
            "half": float(half), "size": size}


def _corr2(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    va, vb = a.var(), b.var()
    if va <= 1e-30 or vb <= 1e-30:
        return 0.0
    c = float(np.mean((a - a.mean()) * (b - b.mean())))
    return float(min(max(c * c / (va * vb), 0.0), 1.0))


#: The one reservoir every timescale and memory-capacity comparison runs on.
#: Held fixed across feeds on purpose - it is the data that is being compared,
#: and a reservoir that changed with the cell would confound the two.
TAU_CONFIG = (300, 0.95, 0.30, 0.50)


def readout_timescales(prep: dict, config: tuple[int, float, float, float],
                       seed: int) -> dict:
    """Which relaxation times the readout actually spends its weight on.

    The ESN analogue of `groundgru.py`'s Jacobian spectrum, and free of its one
    confound. A trained GRU's Jacobian is a property of the training horizon as
    much as of the process - that page's own finding. Here the dynamics are
    **not** trained: linearised at `h = 0` the state map is `(1-a)I + aW`, whose
    eigenvalues `mu_i` are fixed before any data arrives and give relaxation
    times `tau_i = -1/log|mu_i|`. The only fitted object is the readout, so
    projecting its weights onto that eigenbasis asks a clean question: **given a
    reservoir that offers every timescale, which ones does the ridge pay for?**

    Reported as the weight-energy-weighted median `tau`. A feed whose readout
    buys longer timescales than a GBM null's does at the same sigma is carrying
    memory the null has not got.
    """
    size, rho, leak, in_scale = config
    if size > 600:
        return {}
    folds = prep["folds"]
    if not folds:
        return {}
    pre_end = int(folds[0][0][-1]) + 1
    rng = np.random.default_rng(seed)
    res = Reservoir(prep["x"].shape[1], size, rho, leak, in_scale, rng)
    phi, blocks = design(prep, res, pre_end=pre_end)
    sl = blocks["state"]

    wmat = res.w if isinstance(res.w, np.ndarray) else res.w.toarray()
    jac = (1.0 - leak) * np.eye(size) + leak * wmat
    vals, vecs = np.linalg.eig(jac)
    mods = np.abs(vals)
    keep = (mods > 1e-9) & (mods < 0.999999)
    tau = np.full(size, np.inf)
    tau[keep] = -1.0 / np.log(mods[keep])

    tr, te = folds[-1]
    sub = phi[:, sl]
    mu = sub[tr].mean(axis=0)
    a = sub[tr] - mu
    yv = prep["y"]["logvol"][tr]
    gram = a.T @ a
    s, evecs = np.linalg.eigh(gram)
    s = np.maximum(s, 0.0)
    bvec = a.T @ (yv - yv.mean())
    lam = 1e-2 * max(float(np.mean(s)), 1e-12)
    w = evecs @ ((evecs.T @ bvec) / (s + lam))

    # Mode coordinates of the state, and the readout's weight on each mode.
    sample = a[-min(1500, len(a)):].T
    try:
        coords = np.linalg.solve(vecs, sample)
    except np.linalg.LinAlgError:
        coords = np.linalg.lstsq(vecs, sample, rcond=None)[0]
    amp = np.abs(coords).std(axis=1)
    energy = np.abs(vecs.T @ w) * amp
    good = np.isfinite(tau) & (energy > 0)
    if not good.any():
        return {}
    order = np.argsort(tau[good])
    t_sorted = tau[good][order]
    e_sorted = energy[good][order]
    cum = np.cumsum(e_sorted) / max(e_sorted.sum(), 1e-30)
    med = float(t_sorted[int(np.searchsorted(cum, 0.5))])
    p90 = float(t_sorted[min(int(np.searchsorted(cum, 0.9)), len(t_sorted) - 1)])
    # The reservoir's own spectrum, unweighted. Printed beside the weighted
    # median so a reader can see whether the readout moved off the middle of what
    # the reservoir offered at all - on a null it has no reason to, and the two
    # numbers coinciding is the null result rather than a missing measurement.
    flat = float(np.median(t_sorted))
    return {"tau_median": med, "tau_p90": p90, "tau_flat": flat,
            "tau_max_available": float(np.max(t_sorted)),
            "modes": int(good.sum()), "rows": int(len(te))}


def feature_weights(prep: dict, target: str = "logvol") -> dict[str, float]:
    """The static readout's coefficients on the 28 named features, standardised.

    The one part of an ESN that is directly interpretable without apology. The
    reservoir's own weights are random and its state coordinates mean nothing in
    particular, but the passthrough block is `seqlab.NAMES` in order, and the
    ridge coefficient on a standardised column is how many target standard
    deviations the readout moves per feature standard deviation.

    **This is a diagnostic and not a claim.** `research/rebuilding.md`'s loop is
    read the largest feature, *measure it on the feed*, add one term, re-run - not
    read the largest feature and write a paragraph. What it is for here is the
    same thing it was for twice before on this project: `frac_zero` at AUC 0.686
    opened the quote-lattice question and `n_distinct` exposed a float-precision
    artefact and then a real defect in a published specification. A coefficient
    that is large on a real feed and small on the matched GBM null is a place to
    point the next measurement, which is why it is always printed beside the
    null's.
    """
    folds = prep["folds"]
    if not folds:
        return {}
    tr = folds[-1][0]
    x = prep["x"][tr]
    y = prep["y"][target][tr]
    mu, sd = x.mean(axis=0), np.maximum(x.std(axis=0), 1e-12)
    a = (x - mu) / sd
    yc = (y - y.mean()) / max(float(np.std(y)), 1e-12)
    gram = a.T @ a
    s, vecs, top = _eig_block(gram)
    beta = vecs.T @ (a.T @ yc)
    w = vecs @ (beta / (s + 1e-2 * top))
    # The univariate correlation beside the ridge coefficient, because these 28
    # columns are heavily collinear - rv1, rv5, rv22, parkinson and garman_klass
    # are five estimates of one quantity - and a ridge coefficient under
    # collinearity is unstable enough that it flips sign between a feed and its
    # own null. A correlation cannot do that, so it is the column to read and the
    # coefficient is what is checked against it.
    corr = {}
    for i, name in enumerate(prep["names"]):
        col = a[:, i]
        v = float(np.std(col))
        corr[name] = float(np.mean(col * yc) / max(v, 1e-12))
    return {"coef": {name: float(w[i]) for i, name in enumerate(prep["names"])},
            "corr": corr}


# ==========================================================================
# Feed helpers
# ==========================================================================


def garch_bars(sigma: float, n: int, interval: str, rng: np.random.Generator,
               *, alpha: float = 0.10, beta: float = 0.88,
               start: float = 1000.0) -> dict[str, np.ndarray]:
    """**The positive control**: a series whose volatility really does cluster.

    `seqlab`'s own docstring names the reason this exists. If this harness cannot
    find conditional heteroskedasticity where it is present by construction, then
    "the reservoir found nothing on the Volatility family" is a statement about
    the harness and not about the family, and every null on this page is void.

    A GARCH(1,1) at `alpha + beta = 0.98` is persistent enough that the last
    realised value carries real information about the next one - which is exactly
    the property `seqlab.main()` measures the absence of when it finds naive srel
    0.88 against unconditional-mean srel 0.67 on both the real feed and a
    simulated GBM. The unconditional variance is pinned to the same per-bar
    variance a GBM at `sigma` would have, so the control differs from the null in
    one property only: the conditional variance moves.

    Bars are built from a Brownian bridge at each step's own sigma, the same
    construction `seqlab.gbm_bars` uses, so the candle-shape features are
    comparable across the null, the surrogate and this.
    """
    per = seqlab.PER_YEAR[interval]
    var = (sigma / math.sqrt(per)) ** 2
    omega = var * max(1.0 - alpha - beta, 1e-6)
    sub = 24
    s2 = var
    sig = np.empty(n)
    ret = np.empty(n)
    z = rng.normal(0.0, 1.0, n)
    for t in range(n):
        sig[t] = math.sqrt(s2)
        ret[t] = sig[t] * z[t]
        s2 = omega + alpha * ret[t] * ret[t] + beta * s2
    inc = rng.normal(0.0, 1.0, (n, sub)) * (sig / math.sqrt(sub))[:, None]
    walk = np.cumsum(inc, axis=1)
    ramp = np.arange(1, sub + 1) / sub
    bridge = walk - walk[:, -1][:, None] * ramp[None, :] + ret[:, None] * ramp[None, :]
    log_open = math.log(start) + np.concatenate(([0.0], np.cumsum(ret)[:-1]))
    grid = np.exp(log_open[:, None] + bridge)
    o = np.exp(log_open)
    # **The open is part of the bar's path and belongs in both extrema.** This
    # generator inherited its construction from `seqlab.gbm_bars` before that was
    # fixed, and with it the same defect: taking the high as the maximum of the
    # sub-points alone put 11% of simulated bars at `high < max(open, close)`,
    # which is impossible on a traded bar and hands any feed-versus-simulation
    # classifier the answer from the sign of one wick feature. A positive control
    # that is trivially distinguishable from the feed is not a control.
    return {"time": np.arange(n, dtype=float) * (365 * 86400.0 / per),
            "open": o,
            "high": np.maximum(grid.max(axis=1), o),
            "low": np.minimum(grid.min(axis=1), o),
            "close": grid[:, -1], "volume": rng.poisson(1800, n).astype(float),
            "spread": np.full(n, 2.0), "true_sigma": sig}


def sigma_for(symbol: str, bars: dict[str, np.ndarray], interval: str) -> float:
    """The named sigma where there is one, the measured one where there is not.

    `seqlab.measured_sigma` rather than a local estimator, deliberately: six arms
    each fitting their own sigma would build six slightly different GBM nulls,
    and the null is the only thing that makes any arm's positive readable.
    """
    named = seqlab.NAMED_SIGMA.get(symbol)
    if named:
        return float(named)
    return float(seqlab.measured_sigma(bars, interval))


#: The quote grid a simulated null falls back to when there is no feed to copy
#: one from. 1e-2 against `seqlab.gbm_bars`'s start of 1000 is 1 basis point,
#: which is the middle of the 0.27-3.12 bps the family actually quotes.
FALLBACK_TICK = 1e-2


def quantise(bars: dict[str, np.ndarray], tick: float) -> dict[str, np.ndarray]:
    """Put a simulated series on a quote lattice, because the feed is on one.

    **Two reasons, and the second one is now a hard requirement.**

    The first is that it makes the null a better null. `research/quantising.md`
    exists because these feeds quote on a discrete grid, and `seqlab.build`
    carries `frac_zero` and `n_distinct` on the record that both of them have
    paid: `frac_zero` at AUC 0.686 opened the quote-lattice question and
    `n_distinct` exposed a float-precision artefact and then a real defect in a
    published specification. A continuous simulated null has `frac_zero` exactly
    zero and `n_distinct` exactly 1.0 on every row, where the feed has neither -
    which is the same class of free discriminator as the impossible-bar defect
    that was just fixed in `seqlab.gbm_bars`, and a larger one.

    The second is arithmetic. `seqlab.tick_size` recovers the grid as the
    coarsest decimal lattice containing every close, and a continuous float
    series lies on no decimal lattice at all, so it returns NaN - which
    propagates through `rel_spread` into `spread_rel` and makes **every row of a
    simulated null unusable**, silently, by way of `seqlab.usable`. Found here
    when the check stage came back with zero folds on a 20,000-bar null.

    Rounding can push a high half a tick below `max(open, close)`, so the extrema
    are re-clamped afterwards rather than assumed.
    """
    if not np.isfinite(tick) or tick <= 0:
        tick = FALLBACK_TICK
    out = dict(bars)
    for key in ("open", "high", "low", "close"):
        out[key] = np.round(np.asarray(bars[key], float) / tick) * tick
    out["high"] = np.maximum(out["high"], np.maximum(out["open"], out["close"]))
    out["low"] = np.minimum(out["low"], np.minimum(out["open"], out["close"]))
    return out


def gbm_like(bars: dict[str, np.ndarray], symbol: str, interval: str,
             rng: np.random.Generator) -> dict[str, np.ndarray]:
    """A simulated null matched to this cell in sigma, row count *and* quote grid."""
    sim = seqlab.gbm_bars(sigma_for(symbol, bars, interval), len(bars["close"]),
                          interval, rng)
    # The grid is taken from the feed and rescaled by the price ratio, because
    # the simulation starts at 1000 and the feed does not: a lattice copied
    # verbatim onto a series two orders of magnitude away is a different lattice.
    tick = seqlab.tick_size(bars)
    ratio = float(np.nanmedian(sim["close"])) / max(float(np.nanmedian(bars["close"])), 1e-12)
    return quantise(sim, tick * ratio if np.isfinite(tick) else FALLBACK_TICK)


# ==========================================================================
# Stage: check
# ==========================================================================


def stage_check() -> dict:
    """Conditions 1, 2, 3 and 4, before any cell is scored."""
    global WASHOUT  # noqa: PLW0603 - the washout sensitivity check at the end rebinds it
    print("=" * 104)
    print("seqesn.py - an echo state network on the Volatility grid")
    print("=" * 104)
    out: dict = {}
    rng = np.random.default_rng(SEED)

    print("\n=== Condition 1: causality, from seqlab's own assertion ===\n")
    bars = seqlab.load("Volatility 75 Index", "1h")
    verdict = seqlab.check_causality(bars)
    print(f"    Volatility 75 Index 1h: {len(bars['close']):,} bars")
    print(f"    {'CLEAN' if verdict['clean'] else 'LEAKING ' + str(verdict['leaking'])}"
          f"  ({verdict['rows_checked']:,} rows checked)")
    out["causality"] = verdict

    print("\n=== Condition 2: MC <= N on a linear reservoir with iid input ===\n")
    print("    Jaeger's bound is exact. A measured MC above N is an overfitting")
    print("    artefact in the readout, not a property of the reservoir.\n")
    print(f"    {'N':>5s} {'rho':>6s} {'rows':>7s} {'MC in-sample':>13s} {'MC/N':>7s} "
          f"{'MC out':>8s} {'half-life':>10s}")
    rows = []
    iid = rng.uniform(-1.0, 1.0, 30_000)
    for size in (25, 50, 100):
        for rho in (0.5, 0.9, 0.99):
            mc = memory_capacity(iid, (size, rho, 1.0, 0.5), SEED,
                                 kmax=min(3 * size, 200), activation="linear",
                                 lam=1e-8)
            rows.append({"size": size, "rho": rho, **mc})
            print(f"    {size:5d} {rho:6.2f} {mc['n']:7d} {mc['mc_in']:13.3f} "
                  f"{mc['mc_in'] / size:7.3f} {mc['mc_out']:8.3f} {mc['half']:10.0f}")
    worst = max(r["mc_in"] / r["size"] for r in rows)
    print(f"\n    worst MC/N = {worst:.3f}; condition 2 fired: {worst > 1.02}")
    out["mc_bound"] = {"rows": rows, "worst_ratio": worst, "fired": bool(worst > 1.02)}

    print("\n=== Condition 3: the echo state property, measured not assumed ===\n")
    print("    Two trajectories from different random initial states on the same")
    print("    input. A reservoir that has not forgotten its initial condition is")
    print("    reporting that condition and not the data.\n")
    print(f"    {'rho':>6s} {'leak':>6s} {'gap at washout':>15s} {'gap at 5000':>12s} "
          f"{'per-step':>9s} {'forgets':>9s}")
    esp = []
    drive = rng.normal(0, 1, (5000, 4))
    for rho in (0.5, 0.9, 0.95, 1.0, 1.05, 1.2, 1.4):
        for leak in (0.05, 0.15, 1.0):
            res = Reservoir(4, 200, rho, leak, 0.2, np.random.default_rng(SEED + 3))
            got = esp_gap(res, drive, np.random.default_rng(SEED + 4))
            got.update({"rho": rho, "leak": leak})
            esp.append(got)
            print(f"    {rho:6.2f} {leak:6.2f} {got['at_washout']:15.2e} "
                  f"{got['at_end']:12.2e} {got['rate']:9.6f} "
                  f"{str(got['at_end'] < 1e-9):>9s}")
    bad = [e for e in esp if e["rho"] < 1.0 and e["at_end"] >= 1e-9]
    slow = [e for e in esp if e["rho"] < 1.0 and e["at_washout"] >= 1e-6]
    print(f"\n    condition 3 fired (rho<1 still remembering at step 5000): {len(bad)}")
    print(f"    rho<1 configurations still above 1e-6 at the {WASHOUT}-step washout: "
          f"{len(slow)} of {len([e for e in esp if e['rho'] < 1.0])}")
    out["esp"] = {"rows": esp, "fired": bool(bad), "slow_at_washout": len(slow)}

    print("\n=== Condition 4: the direction arm on a known null ===\n")
    print("    seqlab.gbm_bars at the named sigma. The true AUC is 0.5000 by")
    print("    construction, so anything above 0.52 here is a leak in this file.\n")
    sim = quantise(seqlab.gbm_bars(seqlab.NAMED_SIGMA["Volatility 75 Index"],
                                   20_000, "1h", rng), FALLBACK_TICK)
    prep = prepare(sim)
    res4 = []
    print(f"    {'config':>26s} {'rows':>7s} {'AUC dir':>8s} {'AUC shuf':>9s} "
          f"{'r2 logvol':>10s} {'r2 shuf':>9s}")
    for cfg in ((100, 0.9, 0.4, 0.2), (300, 0.95, 0.15, 0.2)):
        got = evaluate(prep, cfg, SEED)
        tag = f"N{cfg[0]} rho{cfg[1]} a{cfg[2]} i{cfg[3]}"
        print(f"    {tag:>26s} {got['esn|direction']['rows']:7d} "
              f"{got['esn|direction']['auc']:8.4f} "
              f"{got['esn|direction_shuffled']['auc']:9.4f} "
              f"{got['esn|logvol']['r2']:10.4f} "
              f"{got['esn|logvol_shuffled']['r2']:9.4f}")
        res4.append({"config": cfg, "auc": got["esn|direction"]["auc"],
                     "r2": got["esn|logvol"]["r2"]})
    fired = any(abs(r["auc"] - 0.5) > 0.02 for r in res4)
    print(f"\n    condition 4 fired (AUC off 0.50 by more than 0.02): {fired}")
    out["gbm_null"] = {"rows": res4, "fired": bool(fired)}

    print("\n=== Condition 5: the positive control, where clustering is real ===\n")
    print("    A GARCH(1,1) at alpha+beta = 0.98, same per-bar variance as the null")
    print("    above. If the reservoir cannot find clustering here it cannot find it")
    print("    anywhere, and every null on this page would be about the harness.\n")
    print(f"    {'config':>26s} {'rows':>7s} {'r2 esn':>8s} {'r2 static':>10s} "
          f"{'r2 har':>8s} {'r2 naive':>9s} {'r2 shuf':>8s} {'srel esn':>9s} "
          f"{'srel mean':>10s}")
    pos = []
    gar = quantise(garch_bars(seqlab.NAMED_SIGMA["Volatility 75 Index"], 20_000, "1h",
                              np.random.default_rng(SEED + 77)), FALLBACK_TICK)
    gprep = prepare(gar)
    for cfg in ((100, 0.9, 0.4, 0.2), (300, 0.95, 0.15, 0.2), (300, 0.9, 0.4, 0.8)):
        got = evaluate(gprep, cfg, SEED)
        tag = f"N{cfg[0]} rho{cfg[1]} a{cfg[2]} i{cfg[3]}"
        print(f"    {tag:>26s} {got['esn|logvol']['rows']:7d} "
              f"{got['esn|logvol']['r2']:+8.4f} {got['static|logvol']['r2']:+10.4f} "
              f"{got['har|logvol']['r2']:+8.4f} {got['naive|logvol']['r2']:+9.4f} "
              f"{got['esn|logvol_shuffled']['r2']:+8.4f} "
              f"{got['esn|logvol']['srel']:9.4f} {got['mean|logvol']['srel']:10.4f}")
        pos.append({"config": cfg, "r2_esn": got["esn|logvol"]["r2"],
                    "r2_har": got["har|logvol"]["r2"],
                    "r2_static": got["static|logvol"]["r2"],
                    "r2_shuf": got["esn|logvol_shuffled"]["r2"]})
    blind = max(r["r2_esn"] for r in pos) < 0.01
    print(f"\n    condition 5 fired (no configuration clears r2 = 0.01 where the")
    print(f"    clustering is real): {blind}")
    out["positive_control"] = {"rows": pos, "fired": bool(blind)}

    out["sensitivity"] = sensitivity_ladder()

    print("\n=== Washout sensitivity, on the same null ===\n")
    print("    The washout is the only free parameter that is not swept, so its")
    print("    irrelevance is checked rather than asserted.\n")
    keep = WASHOUT
    sens = []
    for wash in (25, 100, 400):
        WASHOUT = wash
        p = prepare(sim)
        g = evaluate(p, (300, 0.95, 0.15, 0.2), SEED, with_shuffle=False)
        sens.append({"washout": wash, "r2": g["esn|logvol"]["r2"],
                     "auc": g["esn|direction"]["auc"], "rows": g["esn|logvol"]["rows"]})
        print(f"    washout {wash:4d}: rows {g['esn|logvol']['rows']:6d}  "
              f"r2 {g['esn|logvol']['r2']:+.4f}  auc {g['esn|direction']['auc']:.4f}")
    WASHOUT = keep
    out["washout"] = sens
    return out


#: Persistence settings for the sensitivity ladder, each one a different amount
#: of real volatility clustering.
PERSIST = ((0.02, 0.90), (0.04, 0.92), (0.06, 0.90), (0.08, 0.90),
           (0.10, 0.88), (0.06, 0.93))

#: Row counts that match the real grid: 1d, 8h, 4h and 1h on these feeds.
POWER_ROWS = (2_800, 8_400, 16_900, 50_000)


def _power_job(args):
    alpha, beta, n = args
    raw = garch_bars(0.75, n, "1h", np.random.default_rng(SEED + 91 + n),
                     alpha=alpha, beta=beta)
    spread = float(np.std(np.log(raw["true_sigma"])))
    bars = quantise(raw, FALLBACK_TICK)
    prep = prepare(bars)
    if not prep["folds"]:
        return None
    got = evaluate(prep, (100, 0.9, 0.4, 0.2), SEED)
    return {"alpha": alpha, "beta": beta, "n": n, "sd_log_sigma": spread,
            "rows": got["esn|logvol"]["rows"],
            "r2_esn": got["esn|logvol"]["r2"],
            "r2_esn_1se": got["esn|logvol@1se"]["r2"],
            "r2_esn_gcv": got["esn|logvol@gcv"]["r2"],
            "r2_static": got["static|logvol"]["r2"],
            "r2_har": got["har|logvol"]["r2"],
            "r2_shuf": got["esn|logvol_shuffled"]["r2"],
            "srel_esn": got["esn|logvol"]["srel"],
            "srel_mean": got["mean|logvol"]["srel"]}


def sensitivity_ladder() -> list[dict]:
    """At what level of real clustering would this harness have seen it?

    A null is worth reading only with this table beside it. `research/deriving.md`
    and `research/rebuilding.md` both report `n*` for the same reason: "we found
    nothing" is a claim about power until the power is measured. Here the
    generator is GARCH(1,1) at a known persistence and the row counts are the real
    ones from `seqlab.GRID` - 2,800 at 1d through 50,000 at 1h - so the answer
    reads directly onto the cells this page reports.
    """
    print("\n=== Sensitivity: the clustering this harness would have caught ===\n")
    print("    GARCH(1,1) at the same per-bar variance as the null, at the row")
    print("    counts the real grid actually has. Read down a column to see what")
    print("    1d can resolve and what it cannot.\n")
    jobs = [(a, b, n) for a, b in PERSIST for n in POWER_ROWS]
    with ProcessPoolExecutor(max_workers=min(WORKERS, len(jobs))) as pool:
        rows = [r for r in pool.map(_power_job, jobs) if r]
    print(f"    {'alpha':>6s} {'beta':>6s} {'sd log sigma':>13s} {'rows':>7s} "
          f"{'r2 esn':>8s} {'@1se':>8s} {'@gcv':>10s} {'r2 static':>10s} "
          f"{'r2 har':>8s} {'r2 shuf':>8s} {'srel esn':>9s} {'srel mean':>10s}")
    for r in sorted(rows, key=lambda v: (v["alpha"], v["beta"], v["n"])):
        g = r["r2_esn_gcv"]
        print(f"    {r['alpha']:6.2f} {r['beta']:6.2f} {r['sd_log_sigma']:13.4f} "
              f"{r['rows']:7d} {r['r2_esn']:+8.4f} {r['r2_esn_1se']:+8.4f} "
              f"{(f'{g:+10.4f}' if abs(g) < 1e4 else f'{g:10.1e}')} "
              f"{r['r2_static']:+10.4f} "
              f"{r['r2_har']:+8.4f} {r['r2_shuf']:+8.4f} {r['srel_esn']:9.4f} "
              f"{r['srel_mean']:10.4f}")
    for n in POWER_ROWS:
        sel = [r for r in rows if r["n"] == n and r["r2_esn"] > 0.005]
        floor = min((r["sd_log_sigma"] for r in sel), default=float("nan"))
        print(f"    at {n:,} rows the smallest sd(log sigma) the ESN resolves "
              f"(r2 > 0.005) is {floor:.4f}")
    return rows


# ==========================================================================
# Stage: sweep
# ==========================================================================


def _sweep_job(args):
    """One (symbol, timeframe, reservoir size); every radius, leak and input scale inside.

    The unit of work is deliberately not one configuration. `seqlab.build` carries
    two Python loops over the series - the run-length accumulator and the
    distinct-close count - so rebuilding the feature matrix per configuration
    would spend more core time on features than on reservoirs. Built once, used
    120 times.
    """
    symbol, tf, size = args
    try:
        if symbol == "__gbm__":
            rng = np.random.default_rng(SEED + 5)
            bars = quantise(seqlab.gbm_bars(0.75, min(SWEEP_ROWS + 400, 20_400),
                                            tf, rng), FALLBACK_TICK)
        else:
            bars = seqlab.load(symbol, tf)
        prep = prepare(bars, rows_cap=SWEEP_ROWS)
        if not prep["folds"]:
            return []
    except seqlab.Thin:
        return []
    except Exception as exc:  # noqa: BLE001 - one bad cell must not kill the sweep
        return [{"symbol": symbol, "tf": tf, "config": [size, 0, 0, 0],
                 "error": str(exc)[:120]}]

    out = []
    for rho in RHOS:
        for leak in LEAKS:
            for in_scale in IN_SCALES:
                cfg = (size, rho, leak, in_scale)
                try:
                    got = evaluate(prep, cfg, SEED, light=True)
                except Exception as exc:  # noqa: BLE001
                    out.append({"symbol": symbol, "tf": tf, "config": list(cfg),
                                "error": str(exc)[:120]})
                    continue
                out.append({
                    "symbol": symbol, "tf": tf, "config": list(cfg),
                    "n": prep["n"], "rows": got["esn|logvol"]["rows"],
                    "gcv": got["_meta"]["gcv_esn_logvol"],
                    "val_r2": got["_meta"]["val_r2"],
                    "alpha": got["_meta"]["alpha"],
                    "r2_esn_gcv": got["esn|logvol@gcv"]["r2"],
                    "r2_esn": got["esn|logvol"]["r2"],
                    "r2_static": got["static|logvol"]["r2"],
                    "r2_har": got["har|logvol"]["r2"],
                    "r2_naive": got["naive|logvol"]["r2"],
                    "r2_shuf": got["esn|logvol_shuffled"]["r2"],
                    "srel_esn": got["esn|logvol"]["srel"],
                    "srel_naive": got["naive|logvol"]["srel"],
                    "srel_mean": got["mean|logvol"]["srel"],
                    "auc_esn": got["esn|direction"]["auc"],
                    "auc_static": got["static|direction"]["auc"],
                    "auc_shuf": got["esn|direction_shuffled"]["auc"],
                    "edf": got["esn|logvol"]["edf"], "lam": got["esn|logvol"]["lam"],
                })
    return out


def stage_sweep() -> dict:
    """The hyperparameter surface, with its shuffled control on every cell."""
    print("=" * 104)
    print("seqesn sweep - spectral radius, leak, size, input scaling, ridge lambda")
    print("=" * 104)
    print(f"\n    {len(RHOS)} radii x {len(LEAKS)} leaks x {len(IN_SCALES)} input scales")
    print(f"    x {len(SIZES)} sizes = {len(RHOS) * len(LEAKS) * len(IN_SCALES) * len(SIZES)}"
          f" configurations, {len(ALPHAS)} ridge penalties each (free).")
    print(f"    Rows capped at {SWEEP_ROWS:,} - the sweep measures the shape of the")
    print("    surface, the grid stage uses every row there is.\n")

    jobs = [(sym, tf, size) for sym in (*SWEEP_SYMBOLS, "__gbm__")
            for tf in SWEEP_TFS for size in SIZES]
    per = len(RHOS) * len(LEAKS) * len(IN_SCALES)
    print(f"    {len(jobs)} jobs of {per} configurations on {WORKERS} workers\n", flush=True)

    began = time.time()
    rows, done = _resume("sweep", lambda r: (r.get("symbol"), r.get("tf"),
                                             (r.get("config") or [0])[0]))
    jobs = [j for j in jobs if j not in done]
    print(f"    {len(jobs)} jobs to run\n", flush=True)
    with ProcessPoolExecutor(max_workers=WORKERS) as pool:
        for i, got in enumerate(pool.map(_sweep_job, jobs, chunksize=1), 1):
            rows.extend(got)
            rate = i / max(time.time() - began, 1e-9)
            print(f"      job {i}/{len(jobs)}  {len(rows):,} rows  "
                  f"{(len(jobs) - i) / rate / 60:.1f}m left", flush=True)
            if i % 3 == 0:
                _checkpoint("sweep", rows)
    _checkpoint("sweep", rows)
    ok = [r for r in rows if "error" not in r]
    print(f"\n    {len(ok):,} scored, {len(rows) - len(ok):,} errored, "
          f"{(time.time() - began) / 60:.1f}m\n")

    _sweep_tables(ok)
    return {"rows": rows}


def _sweep_tables(rows: list[dict]) -> None:
    """The surface, with the simulated null held out of every average.

    The `__gbm__` cell is a symbol in the sweep and it is **excluded from the
    per-axis means and printed on its own line**. Averaging a known null into the
    mean of the real feeds is how a table stops being able to answer the question
    it was built for.
    """
    def agg(sel, key):
        vals = [r[key] for r in sel if np.isfinite(r.get(key, np.nan))]
        return float(np.mean(vals)) if vals else float("nan")

    for tf in SWEEP_TFS:
        here = [r for r in rows if r["tf"] == tf and "error" not in r]
        real = [r for r in here if r["symbol"] != "__gbm__"]
        null = [r for r in here if r["symbol"] == "__gbm__"]
        if not real:
            continue
        print(f"\n--- {tf}: mean over {len({r['symbol'] for r in real})} real symbols, "
              f"the simulated null on its own line ---\n")
        print(f"    {'axis':>18s} {'r2 esn':>8s} {'r2 @gcv':>10s} {'r2 shuf':>8s} "
              f"{'r2 static':>10s} {'r2 har':>8s} {'auc esn':>8s} {'auc shuf':>9s} "
              f"{'edf':>7s} {'cells':>6s}")

        def line(label, sel):
            g = agg(sel, "r2_esn_gcv")
            print(f"    {label:>18s} {agg(sel, 'r2_esn'):+8.4f} "
                  f"{(f'{g:+10.4f}' if abs(g) < 1e4 else f'{g:10.1e}')} "
                  f"{agg(sel, 'r2_shuf'):+8.4f} {agg(sel, 'r2_static'):+10.4f} "
                  f"{agg(sel, 'r2_har'):+8.4f} {agg(sel, 'auc_esn'):8.4f} "
                  f"{agg(sel, 'auc_shuf'):9.4f} {agg(sel, 'edf'):7.1f} {len(sel):6d}")

        for label, key, values in (("spectral radius", 1, RHOS), ("leak rate", 2, LEAKS),
                                   ("input scale", 3, IN_SCALES), ("size", 0, SIZES)):
            for v in values:
                sel = [r for r in real if r["config"][key] == v]
                if sel:
                    line(f"{label}={v}", sel)
        if null:
            line("SIMULATED NULL", null)

    print("\n--- best cell per symbol and timeframe, with its matched controls ---\n")
    print("    'best' is the maximum over 360 reservoir configurations, so it is a")
    print("    maximum of 360 draws and the shuffled column beside it is the same")
    print("    maximum taken on a permuted target. Read them as a pair.\n")
    print(f"    {'symbol':32s} {'tf':>4s} {'rows':>7s} {'best r2':>8s} {'config':>22s} "
          f"{'best shuf':>10s} {'static':>8s} {'har':>7s} {'auc':>7s}")
    for sym in sorted({r["symbol"] for r in rows}):
        for tf in SWEEP_TFS:
            sel = [r for r in rows if r["symbol"] == sym and r["tf"] == tf
                   and np.isfinite(r.get("r2_esn", np.nan))]
            if not sel:
                continue
            best = max(sel, key=lambda r: r["r2_esn"])
            worst_shuf = max(r["r2_shuf"] for r in sel if np.isfinite(r["r2_shuf"]))
            cfg = best["config"]
            tag = f"N{cfg[0]} r{cfg[1]} a{cfg[2]} i{cfg[3]}"
            print(f"    {sym[:32]:32s} {tf:>4s} {best['rows']:7d} {best['r2_esn']:+8.4f} "
                  f"{tag:>22s} {worst_shuf:+10.4f} {best['r2_static']:+8.4f} "
                  f"{best['r2_har']:+7.4f} {best['auc_esn']:7.4f}")

    print("\n--- family-wise, over the whole sweep ---\n")
    real = [r for r in rows if r.get("symbol") != "__gbm__" and np.isfinite(r.get("r2_esn", np.nan))]
    null = [r for r in rows if np.isfinite(r.get("r2_shuf", np.nan))]
    if real and null:
        best = max(r["r2_esn"] for r in real)
        draws = np.array([r["r2_shuf"] for r in null])
        print(f"    best real cell {best:+.4f} over {len(real):,} cells; the best of "
              f"{len(draws):,} shuffled cells is {draws.max():+.4f}")
        print(f"    max-of-k p = {seqlab.max_of_k(best, draws):.4f}")
        gnull = np.array([r["r2_esn"] for r in rows
                          if r.get("symbol") == "__gbm__" and np.isfinite(r.get("r2_esn", np.nan))])
        if len(gnull):
            print(f"    best of {len(gnull):,} simulated-GBM cells {gnull.max():+.4f}, "
                  f"max-of-k p = {seqlab.max_of_k(best, gnull):.4f}")

    print("\n--- shortlist by mean walk-forward validation R-squared ---\n")
    print("    The criterion is the validation block, not the test block and not")
    print("    GCV. The GCV column is printed beside it as the record of what a")
    print("    training-block criterion would have chosen instead.\n")
    by_cfg: dict[tuple, list[dict]] = {}
    for r in rows:
        if np.isfinite(r.get("val_r2", np.nan)):
            by_cfg.setdefault(tuple(r["config"]), []).append(r)
    ranked = sorted(by_cfg.items(),
                    key=lambda kv: -float(np.mean([v["val_r2"] for v in kv[1]])))
    print(f"    {'configuration':38s} {'mean val r2':>12s} {'mean test r2':>13s} "
          f"{'mean gcv-sel':>13s} {'cells':>6s}")
    for cfg, sel in ranked[:14]:
        tag = f"N{cfg[0]:<4d} rho {cfg[1]:<5} leak {cfg[2]:<5} in {cfg[3]:<5}"
        g = float(np.mean([v["r2_esn_gcv"] for v in sel]))
        print(f"    {tag:38s} {np.mean([v['val_r2'] for v in sel]):+12.5f} "
              f"{np.mean([v['r2_esn'] for v in sel]):+13.5f} "
              f"{(f'{g:+13.5f}' if abs(g) < 1e4 else f'{g:13.1e}')} {len(sel):6d}")
    print("\n    worst by the same criterion:")
    for cfg, sel in ranked[-6:]:
        tag = f"N{cfg[0]:<4d} rho {cfg[1]:<5} leak {cfg[2]:<5} in {cfg[3]:<5}"
        g = float(np.mean([v["r2_esn_gcv"] for v in sel]))
        print(f"    {tag:38s} {np.mean([v['val_r2'] for v in sel]):+12.5f} "
              f"{np.mean([v['r2_esn'] for v in sel]):+13.5f} "
              f"{(f'{g:+13.5f}' if abs(g) < 1e4 else f'{g:13.1e}')} {len(sel):6d}")


# ==========================================================================
# Stage: grid
# ==========================================================================


def _grid_job(args):
    symbol, tf = args
    try:
        bars = seqlab.load(symbol, tf)
    except seqlab.Thin as exc:
        return {"symbol": symbol, "tf": tf, "skipped": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"symbol": symbol, "tf": tf, "skipped": f"load: {str(exc)[:80]}"}
    try:
        prep = prepare(bars)
        if not prep["folds"]:
            return {"symbol": symbol, "tf": tf, "skipped": f"no folds at n={prep['n']}"}
        # Configuration is chosen by the walk-forward validation R-squared, whose
        # rows all precede the test block. Selecting it by the test score is
        # exactly how a grid this size produces a 0.53, and selecting it by GCV is
        # what the first sweep proved does not work.
        best, seen = None, []
        for cfg in SHORTLIST:
            got = evaluate(prep, cfg, SEED)
            if not got:
                continue
            seen.append(got["esn|logvol"]["r2"])
            val = got["_meta"]["val_r2"]
            if best is None or val > best[0]:
                best = (val, cfg, got)
        if best is None:
            return {"symbol": symbol, "tf": tf, "skipped": "no config solved"}
        _, cfg, got = best
        # The best of the shortlist by test score, carried only so the family-wise
        # control has something to be applied to. It is never the headline: with
        # 176 cells and six reservoirs each it is a maximum of 1,056 draws.
        oracle = max([v for v in seen if np.isfinite(v)], default=float("nan"))

        rng = np.random.default_rng(SEED + 11)
        sigma = sigma_for(symbol, bars, tf)
        gprep = prepare(gbm_like(bars, symbol, tf, rng))
        ggot = evaluate(gprep, cfg, SEED, with_shuffle=False) if gprep["folds"] else {}
        sprep = prepare(seqlab.surrogate_bars(bars, rng))
        sgot = evaluate(sprep, cfg, SEED, with_shuffle=False) if sprep["folds"] else {}
        # Fixed reservoir, not the selected one: the timescale comparison is
        # between feeds, so the reservoir offering the timescales has to be the
        # same object in every cell or the comparison is between reservoirs.
        ts = readout_timescales(prep, TAU_CONFIG, SEED)
        tsg = readout_timescales(gprep, TAU_CONFIG, SEED) if gprep["folds"] else {}
        wts = feature_weights(prep)
        wtsg = feature_weights(gprep) if gprep["folds"] else {}
        wtsd = feature_weights(prep, "direction")
    except Exception as exc:  # noqa: BLE001
        return {"symbol": symbol, "tf": tf, "skipped": f"eval: {str(exc)[:120]}"}

    def pick(d, key, field):
        return float(d.get(key, {}).get(field, float("nan"))) if d else float("nan")

    return {
        "symbol": symbol, "tf": tf, "n": prep["n"], "sigma": sigma,
        "rows": got["esn|logvol"]["rows"], "config": list(cfg),
        "zero_rv_frac": prep["zero_rv_frac"],
        "r2": {
            "esn": pick(got, "esn|logvol", "r2"),
            "state": pick(got, "state|logvol", "r2"),
            "static": pick(got, "static|logvol", "r2"),
            "har": pick(got, "har|logvol", "r2"),
            "naive": pick(got, "naive|logvol", "r2"),
            "mean": pick(got, "mean|logvol", "r2"),
            "shuffled": pick(got, "esn|logvol_shuffled", "r2"),
            "gbm": pick(ggot, "esn|logvol", "r2"),
            "surrogate": pick(sgot, "esn|logvol", "r2"),
            "oracle": float(oracle),
            "gcv_selected": pick(got, "esn|logvol@gcv", "r2"),
            "one_se": pick(got, "esn|logvol@1se", "r2"),
        },
        "srel": {
            "esn": pick(got, "esn|logvol", "srel"),
            "har": pick(got, "har|logvol", "srel"),
            "naive": pick(got, "naive|logvol", "srel"),
            "mean": pick(got, "mean|logvol", "srel"),
            "gbm_esn": pick(ggot, "esn|logvol", "srel"),
            "gbm_naive": pick(ggot, "naive|logvol", "srel"),
            "gbm_mean": pick(ggot, "mean|logvol", "srel"),
        },
        "auc": {
            "esn": pick(got, "esn|direction", "auc"),
            "static": pick(got, "static|direction", "auc"),
            "har": pick(got, "har|direction", "auc"),
            "naive": pick(got, "naive|direction", "auc"),
            "shuffled": pick(got, "esn|direction_shuffled", "auc"),
            "gbm": pick(ggot, "esn|direction", "auc"),
            "surrogate": pick(sgot, "esn|direction", "auc"),
            "nstar": pick(got, "esn|direction", "nstar"),
        },
        "edf": pick(got, "esn|logvol", "edf"),
        "val_r2": float(got["_meta"]["val_r2"]),
        "tau": ts, "tau_gbm": tsg,
        "weights": wts, "weights_gbm": wtsg, "weights_dir": wtsd,
    }


def stage_grid() -> dict:
    """Every symbol, every timeframe, with all four controls beside every number."""
    print("=" * 104)
    print("seqesn grid - VOLATILITY + SPOT_UP across seqlab.GRID")
    print("=" * 104)
    symbols = (*seqlab.VOLATILITY, *seqlab.SPOT_UP, *seqlab.REAL)
    jobs = [(s, tf) for s in symbols for tf in seqlab.GRID]
    print(f"\n    {len(symbols)} symbols x {len(seqlab.GRID)} timeframes = {len(jobs)} cells")
    print(f"    {len(seqlab.REAL)} of the symbols are real markets, carried as the")
    print("    positive control and reported in their own table - a null on the")
    print("    synthetics means nothing if the same harness finds nothing on gold.")
    print(f"    shortlist of {len(SHORTLIST)} reservoirs, selected per cell by GCV on the")
    print("    training block; controls are shuffle, phase surrogate and GBM at the")
    print("    symbol's own sigma, every one on the selected configuration.\n", flush=True)

    began = time.time()
    rows, done = _resume("grid", lambda r: (r.get("symbol"), r.get("tf")))
    jobs = [j for j in jobs if j not in done]
    print(f"    {len(jobs)} cells to run\n", flush=True)
    with ProcessPoolExecutor(max_workers=WORKERS) as pool:
        for i, got in enumerate(pool.map(_grid_job, jobs, chunksize=1), 1):
            rows.append(got)
            rate = i / max(time.time() - began, 1e-9)
            print(f"      {i}/{len(jobs)} {got['symbol'][:26]:26s} {got['tf']:>4s}  "
                  f"{(len(jobs) - i) / rate / 60:.1f}m left", flush=True)
            if i % 10 == 0:
                _checkpoint("grid", rows)
    _checkpoint("grid", rows)
    print(f"\n    {(time.time() - began) / 60:.1f}m\n")
    print("#" * 104)
    print("# The Volatility family and Spot Up")
    print("#" * 104)
    _grid_tables(rows, only="synthetic")
    print("\n" + "#" * 104)
    print("# The positive control: real markets, where volatility clustering is a fact")
    print("#" * 104)
    _grid_tables(rows, only="real")
    return {"rows": rows}


def _grid_tables(rows: list[dict], *, only: str = "synthetic") -> None:
    real = set(seqlab.REAL)
    if only == "synthetic":
        rows = [r for r in rows if r["symbol"] not in real]
    elif only == "real":
        rows = [r for r in rows if r["symbol"] in real]
    live = [r for r in rows if "skipped" not in r]
    dead = [r for r in rows if "skipped" in r]
    print(f"--- {len(live)} cells scored, {len(dead)} skipped ---")
    for r in dead[:20]:
        print(f"    skip {r['symbol'][:30]:30s} {r['tf']:>4s}  {r['skipped']}")

    print("\n--- logvol: does the reservoir beat the unconditional mean? ---\n")
    print("    r2 is against the training block's own mean, so 0.0000 IS the")
    print("    unconditional mean and positive is beating it out of sample.\n")
    print(f"    {'symbol':30s} {'tf':>4s} {'rows':>7s} {'esn':>8s} {'static':>8s} "
          f"{'har':>8s} {'naive':>8s} {'shuf':>8s} {'gbm':>8s} {'surr':>8s} {'edf':>6s}")
    for r in sorted(live, key=lambda v: (seqlab.GRID.index(v["tf"]), v["symbol"])):
        q = r["r2"]
        print(f"    {r['symbol'][:30]:30s} {r['tf']:>4s} {r['rows']:7d} "
              f"{q['esn']:+8.4f} {q['static']:+8.4f} {q['har']:+8.4f} {q['naive']:+8.4f} "
              f"{q['shuffled']:+8.4f} {q['gbm']:+8.4f} {q['surrogate']:+8.4f} {r['edf']:6.1f}")

    print("\n--- selector contrast, on identical rows and identical reservoirs ---\n")
    print("    esn(val) is the headline: penalty chosen by minimum error on a")
    print("    validation block that precedes the test block. esn(1se) is the same")
    print("    path at the most-regularised penalty indistinguishable from it.")
    print("    esn(gcv) is the training-block criterion. best-of-6 is the maximum")
    print("    over the shortlist, carried only for the family-wise control.\n")
    print(f"    {'symbol':30s} {'tf':>4s} {'esn(val)':>9s} {'esn(1se)':>9s} "
          f"{'esn(gcv)':>12s} {'best-of-6':>10s} {'val r2':>9s} {'config':>22s}")
    for r in sorted(live, key=lambda v: (seqlab.GRID.index(v["tf"]), v["symbol"])):
        g = r["r2"].get("gcv_selected", float("nan"))
        cfg = r["config"]
        tag = f"N{cfg[0]} r{cfg[1]} a{cfg[2]} i{cfg[3]}"
        print(f"    {r['symbol'][:30]:30s} {r['tf']:>4s} {r['r2']['esn']:+9.4f} "
              f"{r['r2'].get('one_se', float('nan')):+9.4f} "
              f"{(f'{g:+12.4f}' if abs(g) < 1e4 else f'{g:12.1e}')} "
              f"{r['r2']['oracle']:+10.4f} {r.get('val_r2', float('nan')):+9.4f} "
              f"{tag:>22s}")

    print("\n--- direction: the null calibration ---\n")
    print(f"    {'symbol':30s} {'tf':>4s} {'rows':>7s} {'esn':>7s} {'static':>7s} "
          f"{'naive':>7s} {'shuf':>7s} {'gbm':>7s} {'surr':>7s} {'n*':>12s}")
    for r in sorted(live, key=lambda v: (seqlab.GRID.index(v["tf"]), v["symbol"])):
        q = r["auc"]
        ns = q["nstar"]
        print(f"    {r['symbol'][:30]:30s} {r['tf']:>4s} {r['rows']:7d} "
              f"{q['esn']:7.4f} {q['static']:7.4f} {q['naive']:7.4f} {q['shuffled']:7.4f} "
              f"{q['gbm']:7.4f} {q['surrogate']:7.4f} "
              f"{('inf' if not np.isfinite(ns) else f'{ns:,.0f}'):>12s}")

    print("\n--- srel on the realised scale, against seqlab.main's own numbers ---\n")
    print(f"    {'symbol':30s} {'tf':>4s} {'esn':>8s} {'har':>8s} {'naive':>8s} "
          f"{'mean':>8s} | {'gbm esn':>8s} {'gbm naive':>9s} {'gbm mean':>9s}")
    for r in sorted(live, key=lambda v: (seqlab.GRID.index(v["tf"]), v["symbol"])):
        q = r["srel"]
        print(f"    {r['symbol'][:30]:30s} {r['tf']:>4s} {q['esn']:8.4f} {q['har']:8.4f} "
              f"{q['naive']:8.4f} {q['mean']:8.4f} | {q['gbm_esn']:8.4f} "
              f"{q['gbm_naive']:9.4f} {q['gbm_mean']:9.4f}")

    print("\n--- per timeframe, averaged over symbols ---\n")
    print(f"    {'tf':>4s} {'cells':>6s} {'rows':>8s} {'r2 esn':>8s} {'r2 static':>10s} "
          f"{'r2 har':>8s} {'r2 gbm':>8s} {'r2 shuf':>8s} {'auc esn':>8s} {'auc gbm':>8s}")
    for tf in seqlab.GRID:
        sel = [r for r in live if r["tf"] == tf]
        if not sel:
            continue

        def m(key, field, s=sel):
            vals = [x[key][field] for x in s if np.isfinite(x[key][field])]
            return float(np.mean(vals)) if vals else float("nan")

        print(f"    {tf:>4s} {len(sel):6d} {int(np.mean([r['rows'] for r in sel])):8d} "
              f"{m('r2', 'esn'):+8.4f} {m('r2', 'static'):+10.4f} {m('r2', 'har'):+8.4f} "
              f"{m('r2', 'gbm'):+8.4f} {m('r2', 'shuffled'):+8.4f} "
              f"{m('auc', 'esn'):8.4f} {m('auc', 'gbm'):8.4f}")

    print("\n--- family-wise: the best real cell against the best matched null ---\n")
    print(f"    {len(live)} cells x {len(SHORTLIST)} reservoirs is "
          f"{len(live) * len(SHORTLIST):,} draws; the null columns get the same")
    print("    maximum taken on them, which is what makes the comparison fair.\n")
    for label, field, better in (("logvol r2", "r2", max), ("direction AUC", "auc", max)):
        obs = [r[field]["esn"] for r in live if np.isfinite(r[field]["esn"])]
        nulls = np.array([r[field][k] for r in live for k in ("gbm", "shuffled", "surrogate")
                          if np.isfinite(r[field].get(k, np.nan))])
        if not obs or not len(nulls):
            continue
        best = better(obs)
        p = seqlab.max_of_k(best, nulls)
        print(f"    {label:16s} best real {best:+.4f}   "
              f"best null {nulls.max():+.4f}   {len(nulls)} null cells   "
              f"max-of-k p = {p:.4f}")

    print("\n--- readout coefficients on the 28 named features, against the null ---\n")
    print("    Mean absolute standardised coefficient across cells, logvol target,")
    print("    beside the same quantity on each cell's own simulated GBM. A feature")
    print("    that separates is where the next measurement goes; it is not itself")
    print("    a finding.\n")
    have = [r for r in live if r.get("weights", {}).get("corr")]
    if have:
        def mean_abs(rows, key, field, nm):
            v = np.array([abs(r.get(key, {}).get(field, {}).get(nm, np.nan)) for r in rows])
            v = v[np.isfinite(v)]
            return float(v.mean()) if len(v) else float("nan")

        rowsw = []
        for nm in list(have[0]["weights"]["corr"]):
            rowsw.append((nm,
                          mean_abs(have, "weights", "corr", nm),
                          mean_abs(have, "weights_gbm", "corr", nm),
                          mean_abs(have, "weights", "coef", nm),
                          mean_abs(have, "weights_dir", "corr", nm)))
        rowsw.sort(key=lambda v: -(v[1] - v[2] if np.isfinite(v[2]) else v[1]))
        print(f"    {'feature':16s} {'|corr| real':>12s} {'|corr| gbm':>11s} "
              f"{'real - gbm':>11s} {'|coef| real':>12s} {'|corr| direction':>17s}")
        for nm, a, b, c, d in rowsw[:16]:
            print(f"    {nm:16s} {a:12.4f} {b:11.4f} {a - b:+11.4f} {c:12.4f} {d:17.4f}")

    print("\n--- readout timescales: which relaxation times the ridge pays for ---\n")
    print(f"    {'symbol':30s} {'tf':>4s} {'tau median':>11s} {'tau p90':>9s} "
          f"{'gbm median':>11s} {'gbm p90':>9s} {'unweighted':>11s} {'longest':>9s}")
    for r in sorted(live, key=lambda v: (seqlab.GRID.index(v["tf"]), v["symbol"])):
        t, g = r.get("tau") or {}, r.get("tau_gbm") or {}
        if not t:
            continue
        print(f"    {r['symbol'][:30]:30s} {r['tf']:>4s} {t['tau_median']:11.2f} "
              f"{t['tau_p90']:9.2f} {g.get('tau_median', float('nan')):11.2f} "
              f"{g.get('tau_p90', float('nan')):9.2f} {t.get('tau_flat', float('nan')):11.2f} "
              f"{t['tau_max_available']:9.2f}")


# ==========================================================================
# Stage: memory
# ==========================================================================

MEM_CONFIG = TAU_CONFIG

#: Independent draws of each simulated control arm. One draw per null puts the
#: null's own sampling noise straight into every reported gap.
NULL_DRAWS = int(os.environ.get("NULL_DRAWS", "3"))
MEM_TFS = ("1h", "4h", "12h", "1d")


def _mem_job(args):
    symbol, tf = args
    try:
        bars = seqlab.load(symbol, tf)
    except Exception as exc:  # noqa: BLE001
        return {"symbol": symbol, "tf": tf, "skipped": str(exc)[:90]}
    rng = np.random.default_rng(SEED + 21)
    c = bars["close"]
    ret = np.diff(np.log(np.maximum(c, 1e-12)))
    ret = ret[np.isfinite(ret)]
    n = len(ret)
    if n < 1200:
        return {"symbol": symbol, "tf": tf, "skipped": f"{n} returns"}
    sigma = sigma_for(symbol, bars, tf)
    # **Each control arm is drawn more than once.** The quantity being read is a
    # difference between a feed and a null, and with one draw per null the
    # difference carries the null's own sampling noise - which the first
    # end-to-end run measured at about one unit of MC, the same order as a gap
    # worth reporting. Every draw uses the same reservoir, so only the series
    # varies.
    tag = abs(hash(symbol)) % 9973
    sret, sur, gret = [], [], []
    for d in range(NULL_DRAWS):
        sim = seqlab.gbm_bars(sigma, n + 2, tf, np.random.default_rng(SEED + 21 + d))
        sret.append(np.diff(np.log(sim["close"]))[:n])
        sur.append(seqlab.phase_surrogate(ret, np.random.default_rng(SEED + 61 + d))[:n])
        gar = garch_bars(sigma, n + 2, tf,
                         np.random.default_rng(SEED + 41 + d + tag),
                         alpha=0.08, beta=0.90)
        gret.append(np.diff(np.log(gar["close"]))[:n])

    def logrv(r):
        """`log(|r| + eps)` with a floor at 1% of the series' own mean |r|.

        Not `log|r|`, and the difference decides whether this measurement is
        about volatility memory or about the quote lattice. These feeds are
        quantised - `frac_zero` and `n_distinct` are features in `seqlab` on
        exactly that record - so a real feed has exact zero returns where a
        simulated GBM has none, and `log|r|` turns each one into a -27.6 spike.
        A reservoir would then be recalling the positions of lattice events and
        the gap against the null would be a measurement of quantisation. The
        floor is a fraction of each series' *own* mean absolute return, so the
        transform is identical in form on all four arms and cannot manufacture a
        difference between them.
        """
        a = np.abs(r)
        return np.log(a + 0.01 * max(float(np.mean(a)), 1e-15))

    out = {"symbol": symbol, "tf": tf, "n": n, "sigma": sigma,
           "zero_frac": float(np.mean(ret == 0.0))}
    kmax = min(2 * MEM_CONFIG[0], 300)
    for drive_name, prep_fn in (("ret", lambda v: v), ("logrv", logrv)):
        arms = {"real": [ret], "surrogate": sur, "gbm": sret, "garch": gret}
        for arm, series in arms.items():
            got = [memory_capacity(prep_fn(v), MEM_CONFIG, SEED + 31, kmax=kmax)
                   for v in series]
            keep = [g for g in got if np.isfinite(g["mc_out"])]
            base = dict(got[0])
            if keep:
                base["mc_out"] = float(np.mean([g["mc_out"] for g in keep]))
                base["mc_in"] = float(np.mean([g["mc_in"] for g in keep]))
                base["half"] = float(np.mean([g["half"] for g in keep]))
                base["spread"] = float(np.std([g["mc_out"] for g in keep]))
                base["draws"] = len(keep)
            out[f"{drive_name}_{arm}"] = base
        # The linear yardstick the reservoir has to beat to mean anything.
        y = prep_fn(ret)
        out[f"{drive_name}_acf"] = [
            float(np.corrcoef(y[:-k], y[k:])[0, 1]) for k in (1, 2, 5, 10, 20)]
    return out


def stage_memory() -> dict:
    """Arm 2: how much of its own past does each feed leave in a fixed reservoir?"""
    print("=" * 104)
    print("seqesn memory - Jaeger's MC on each feed against a GBM null at its own sigma")
    print("=" * 104)
    print(f"\n    reservoir N={MEM_CONFIG[0]} rho={MEM_CONFIG[1]} leak={MEM_CONFIG[2]} "
          f"input={MEM_CONFIG[3]}, identical seed on every series, rows matched.")
    print("    MC is out of sample: the readout is fitted on the first 70% of rows")
    print("    and MC_k is the squared correlation on the last 30%. In sample a")
    print("    300-unit reservoir reconstructs anything and the number is a")
    print("    statement about degrees of freedom.\n")

    symbols = (*seqlab.VOLATILITY, *seqlab.SPOT_UP)
    jobs = [(s, tf) for s in symbols for tf in MEM_TFS]
    began = time.time()
    rows, done = _resume("memory", lambda r: (r.get("symbol"), r.get("tf")))
    jobs = [j for j in jobs if j not in done]
    print(f"    {len(jobs)} cells to run\n", flush=True)
    with ProcessPoolExecutor(max_workers=WORKERS) as pool:
        for i, got in enumerate(pool.map(_mem_job, jobs, chunksize=1), 1):
            rows.append(got)
            rate = i / max(time.time() - began, 1e-9)
            print(f"      {i}/{len(jobs)} {got['symbol'][:26]:26s} {got['tf']:>4s}  "
                  f"{(len(jobs) - i) / rate / 60:.1f}m left", flush=True)
            if i % 10 == 0:
                _checkpoint("memory", rows)
    _checkpoint("memory", rows)
    print(f"\n    {(time.time() - began) / 60:.1f}m\n")

    live = [r for r in rows if "skipped" not in r]
    for drive in ("ret", "logrv"):
        title = ("returns" if drive == "ret"
                 else "log realised volatility - the drive that matters")
        print(f"\n--- drive: {title} ---\n")
        print(f"    {'symbol':30s} {'tf':>4s} {'rows':>7s} {'zero':>6s} {'MC real':>8s} "
              f"{'MC surr':>8s} {'MC gbm':>8s} {'MC garch':>9s} {'real-gbm':>9s} "
              f"{'garch-gbm':>10s} {'half':>5s} {'acf1':>7s} {'acf5':>7s}")
        for r in sorted(live, key=lambda v: (MEM_TFS.index(v["tf"]), v["symbol"])):
            a, u, g = r[f"{drive}_real"], r[f"{drive}_surrogate"], r[f"{drive}_gbm"]
            c = r[f"{drive}_garch"]
            acf = r[f"{drive}_acf"]
            print(f"    {r['symbol'][:30]:30s} {r['tf']:>4s} {a['n']:7d} "
                  f"{r['zero_frac']:6.3f} "
                  f"{a['mc_out']:8.3f} {u['mc_out']:8.3f} {g['mc_out']:8.3f} "
                  f"{c['mc_out']:9.3f} {a['mc_out'] - g['mc_out']:+9.3f} "
                  f"{c['mc_out'] - g['mc_out']:+10.3f} {a['half']:5.0f} "
                  f"{acf[0]:+7.4f} {acf[2]:+7.4f}")
        for tag in ("real", "surrogate", "garch"):
            gaps = np.array([r[f"{drive}_{tag}"]["mc_out"] - r[f"{drive}_gbm"]["mc_out"]
                             for r in live])
            gaps = gaps[np.isfinite(gaps)]
            if len(gaps):
                print(f"    {tag:9s} minus gbm: mean {gaps.mean():+.4f}  sd {gaps.std():.4f}"
                      f"  min {gaps.min():+.4f}  max {gaps.max():+.4f}  over {len(gaps)} cells")
        for tf in MEM_TFS:
            sel = [r for r in live if r["tf"] == tf]
            if not sel:
                continue
            gr = np.array([r[f"{drive}_real"]["mc_out"] - r[f"{drive}_gbm"]["mc_out"]
                           for r in sel])
            gc = np.array([r[f"{drive}_garch"]["mc_out"] - r[f"{drive}_gbm"]["mc_out"]
                           for r in sel])
            print(f"      {tf:>4s}: real-gbm {gr.mean():+.4f} +- {gr.std():.4f}   "
                  f"garch-gbm {gc.mean():+.4f} +- {gc.std():.4f}   ({len(sel)} symbols, "
                  f"{int(np.mean([r['n'] for r in sel])):,} rows each)")
    return {"rows": rows}


# ==========================================================================


def _checkpoint(stage: str, rows: list) -> None:
    """Partial results to disk as they arrive.

    The research box went down mid-sweep and took forty minutes of completed
    cells with it, then came back for fifteen minutes and went down again. On a
    machine that behaves like that a checkpoint is not a nicety - it is the only
    way a run that takes longer than an uptime ever finishes.
    """
    OUTDIR.mkdir(parents=True, exist_ok=True)
    with open(OUTDIR / f"seqesn_{stage}_partial.json", "w") as fh:
        json.dump({"rows": rows}, fh, default=float)


def _resume(stage: str, key) -> tuple[list, set]:
    """Rows already computed by an earlier attempt, and the jobs they cover.

    Paired with `_checkpoint`, this makes a relaunch cumulative rather than a
    restart. `key` maps a stored row back to the job tuple that produced it.
    """
    path = OUTDIR / f"seqesn_{stage}_partial.json"
    if not path.exists():
        return [], set()
    try:
        with open(path) as fh:
            rows = json.load(fh).get("rows", [])
    except Exception:  # noqa: BLE001 - a truncated checkpoint is not worth dying over
        return [], set()
    rows = [r for r in rows if isinstance(r, dict)]
    done = {key(r) for r in rows}
    if rows:
        print(f"    resuming: {len(rows)} cells already on disk from an earlier attempt",
              flush=True)
    return rows, done


def main() -> None:
    OUTDIR.mkdir(parents=True, exist_ok=True)
    began = time.time()
    stages = {"check": stage_check, "sweep": stage_sweep,
              "grid": stage_grid, "memory": stage_memory}
    todo = list(stages) if STAGE == "all" else [s.strip() for s in STAGE.split(",")]
    result: dict = {"seed": SEED, "washout": WASHOUT, "folds": FOLDS,
                    "horizon": HORIZON, "stages": todo}
    for name in todo:
        if name not in stages:
            print(f"unknown stage {name}")
            continue
        result[name] = stages[name]()
        path = OUTDIR / f"seqesn_{name}.json"
        with open(path, "w") as fh:
            json.dump(result[name], fh, default=float)
        print(f"\nwrote {path}", flush=True)
    print(f"\ntotal {(time.time() - began) / 60:.1f}m")


if __name__ == "__main__":
    main()
