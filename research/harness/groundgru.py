"""A recurrent net as a system-identification instrument, with the transfer operator as its control.

**Not a predictor, and the distinction is the whole design.**
`research/deriving.md` proves a predictable position on a martingale has
expectancy `-(c/2) x turnover`, so no architecture can trade these instruments;
`research/rebuilding.md` confirmed it empirically - boosted models on tick
windows, k-tuples and bar OHLC found nothing on the seven fine-resolution
Volatility feeds, `n*` infinite on every arm. That question is closed and this
harness does not re-open it.

What is open is **identification**. A learned model has paid twice on this
project already and both times the value was a feature importance rather than a
score: `frac_zero` at AUC 0.686 led to the quote-lattice question, and
`n_distinct` exposed a float-precision artefact and then a real defect in the
published grind specification. **A model that beats its floor is a map of what a
specification is missing.**

## Two arms, and the first is the one that belongs to this page

### Arm A: does a learned latent state-space model find the spectrum the operator finds?

A recurrent net's hidden state **is** a learned state-space model, and the
eigenvalues of its recurrent Jacobian `dh_{t+1}/dh_t` are its relaxation modes -
the same object `groundlib.ulam_rates` estimates, approached from the other side.
One is a nonparametric bin count on the observed state; the other is a
gradient-trained latent. They have no arithmetic in common.

So they are run **against each other on processes whose spectrum is known
exactly** - a reflecting box at `(k pi/W)^2 D` and an Ornstein-Uhlenbeck at
`k theta` - and the question is whether the net's Jacobian spectrum lands where
the truth is. If it does, that is a genuine convergence of two unrelated
estimators on one object. If the net finds modes the operator does not, the gap
is the finding. If it finds nothing, the net is an expensive way to get a number
Ulam already has, and this page says so.

The ground truth is the point. `research/rebuilding.md`'s own conclusion about
learned models here is that they are only worth anything when there is something
to check them against, and a simulated generator is the one place in this
folder where "is the learned object right" is a measurement.

### Arm B: Boom 500, which is the family still separating

`research/rebuilding.md`'s discriminator loop drove the largest univariate
feature down from 0.186 over floor to 0.012 on the Volatility family, and stopped
there. **Boom and Crash did not close**: `n_distinct` reads AUC 0.601 on
`boom_500_index` and 0.308 on `crash_500_index` - a feature separating in *both*
directions, which is not one defect - and `n* = 120` on the Boom 500 k-tuple arm,
which is 960 ticks.

Boom is also the family where **order** matters most, and order is exactly what
the boosted arms cannot see: they are fed engineered windows, which are summary
statistics that average order away. Grind and jump interleave; the grind is a
gamma the published two moments do not pin; the spread is a second process nobody
specified. A sequence model is the right shape for that and a window is not.

So arm B asks one question: **does a GRU over the raw increment sequence beat a
boosted window arm at telling a real Boom 500 from a rebuilt one?** If it does
not, the window features already capture what is there, which is a clean result.

## The floors, which are the part that decides whether any of it is readable

* **Real against real.** The same architecture, the same sample size, the same
  training budget, with both halves drawn from the *real* feed. Whatever it
  scores there is what this classifier reads on data with no difference in it.
  `research/rebuilding.md` found a naive pooled split scoring **0.96** on feed
  identity alone, so this is not a formality.
* **Rebuild against rebuild**, the Monte Carlo floor, for the same reason.
* **A logistic regression on the same raw sequence**, which is the linear
  baseline `research/models.md` found beating trees, forests, cosine similarity
  and an MLP on this project's other classification problem.
* **Equal rows per class and equal sequence composition**, because
  `research/rebuilding.md` names three inflation bugs that each produced a
  confident false positive, and unequal rows was one of them.
* **`n*` beside every AUC at the floor**, so a null says at what sample it would
  separate rather than pretending the question is settled.

## What would count as failure

Written before any number was read.

1. **The implementation is wrong** if the analytic BPTT gradient does not match a
   finite-difference gradient to 1e-6 relative. Checked first, on random weights,
   before any data is loaded. A hand-written recurrent net that is not gradient
   checked is a random number generator with a loss curve.

   **This fired on the first run and the cause was the check rather than the
   gradient**, which is recorded here rather than edited away. At a step of 1e-6
   the worst relative error was 1.15e-05; at 1e-5 it is 6.6e-07 and at 1e-4 it is
   8.2e-07. **The error falls as the step grows**, which is the signature of
   float64 cancellation in the loss difference rather than of a wrong
   derivative - at the worst coordinate the two agree to 6.021336e-06 against
   6.021406e-06, seven parts in 1e11 absolute. A central difference has roundoff
   error of order `machine_eps / step`, so 1e-6 is past the point where this loss
   can be differenced at all. The step is set to **1e-5**, where the check is best
   conditioned, and the threshold stays at 1e-6.
2. **The net is dead** if, on a simulated Ornstein-Uhlenbeck whose rate is known,
   the leading Jacobian eigenvalue's implied rate misses the truth by more than a
   factor of two.
3. **Arm A is notation** if the net's implied rates land no closer to the truth
   than `groundlib.ulam_rates` on the identical series. The operator is the
   control and it is cheap; a net that merely matches it has bought nothing.
4. **Arm B is void** if the real-against-real floor is not within 0.02 of 0.5, or
   if the two classes carry different row counts or different sequence lengths.
5. **Arm B finds nothing** if the GRU's AUC does not clear the boosted window arm
   and its own floor. That is a reportable result and not a failure of the run.
6. **The run is void** if any AUC lands on exactly 0.5000, or if the GRU and the
   logistic regression return the same score to more digits than their bootstrap
   interval allows.
7. **No claim from a saliency map** unless the feature it points at is then
   *measured* on the feed directly. `research/rebuilding.md`'s loop is read the
   largest feature, measure it, add one term, re-run - not read the largest
   feature and write a paragraph.
"""

from __future__ import annotations

import json
import math
import os

from concurrent.futures import ProcessPoolExecutor

import numpy as np

import groundlib as G

SEED = int(os.environ.get("SEED", "20260912"))
OUT = os.environ.get("OUT", os.path.join(G.LOGS, "groundgru.json"))
HID = int(os.environ.get("HID", "16"))
SEQ = int(os.environ.get("SEQ", "64"))
EPOCHS = int(os.environ.get("EPOCHS", "12"))
BATCH = int(os.environ.get("BATCH", "128"))
LR = float(os.environ.get("LR", "0.02"))
NROW = int(os.environ.get("NROW", "8000"))
WORKERS = int(os.environ.get("WORKERS", "12"))


# --------------------------------------------------------------------------
# A one-layer GRU with hand-written BPTT
# --------------------------------------------------------------------------


def _sig(x):
    return 0.5 * (1.0 + np.tanh(0.5 * x))


class GRU:
    """One layer, scalar input, linear readout. numpy and manual BPTT.

    There is no torch on the lab, which is also why `rebuildgen.py` carries a
    hand-written gradient booster. The cost of that is that the gradient has to
    be checked rather than trusted, and condition 1 does it before anything else
    runs.
    """

    def __init__(self, nin: int, nh: int, nout: int, rng):
        s = 1.0 / math.sqrt(nh)
        self.nh, self.nin, self.nout = nh, nin, nout
        self.p = {
            "Wz": rng.normal(0, s, (nin, nh)), "Uz": rng.normal(0, s, (nh, nh)),
            "bz": np.zeros(nh),
            "Wr": rng.normal(0, s, (nin, nh)), "Ur": rng.normal(0, s, (nh, nh)),
            "br": np.zeros(nh),
            "Wn": rng.normal(0, s, (nin, nh)), "Un": rng.normal(0, s, (nh, nh)),
            "bn": np.zeros(nh),
            "V": rng.normal(0, s, (nh, nout)), "c": np.zeros(nout),
        }

    def forward(self, x):
        """`x` is (batch, time, nin). Returns the readout and the tape."""
        p = self.p
        b, t, _ = x.shape
        h = np.zeros((b, self.nh))
        tape = []
        for i in range(t):
            xi = x[:, i, :]
            z = _sig(xi @ p["Wz"] + h @ p["Uz"] + p["bz"])
            r = _sig(xi @ p["Wr"] + h @ p["Ur"] + p["br"])
            uh = h @ p["Un"]
            n = np.tanh(xi @ p["Wn"] + r * uh + p["bn"])
            hn = (1.0 - z) * n + z * h
            tape.append((xi, h, z, r, n, uh))
            h = hn
        return h @ p["V"] + p["c"], tape, h

    def backward(self, tape, h_last, dout):
        p = self.p
        g = {k: np.zeros_like(v) for k, v in p.items()}
        g["V"] += h_last.T @ dout
        g["c"] += dout.sum(axis=0)
        dh = dout @ p["V"].T
        for xi, h, z, r, n, uh in reversed(tape):
            dz = dh * (h - n)
            dn = dh * (1.0 - z)
            dh_prev = dh * z
            an = dn * (1.0 - n * n)
            g["Wn"] += xi.T @ an
            g["bn"] += an.sum(axis=0)
            g["Un"] += h.T @ (an * r)
            dh_prev += (an * r) @ p["Un"].T
            dr = an * uh
            ar = dr * r * (1.0 - r)
            g["Wr"] += xi.T @ ar
            g["br"] += ar.sum(axis=0)
            g["Ur"] += h.T @ ar
            dh_prev += ar @ p["Ur"].T
            az = dz * z * (1.0 - z)
            g["Wz"] += xi.T @ az
            g["bz"] += az.sum(axis=0)
            g["Uz"] += h.T @ az
            dh_prev += az @ p["Uz"].T
            dh = dh_prev
        return g

    def jacobian(self, h0: np.ndarray, x0: np.ndarray, eps: float = 1e-5) -> np.ndarray:
        """`dh_{t+1}/dh_t` at one state, by central differences.

        Numerical rather than analytic on purpose: the point of this matrix is to
        be compared against an independent estimator, and a hand-derived Jacobian
        that shares an algebra error with the backward pass would agree with
        itself and with nothing else.
        """
        nh = self.nh
        j = np.zeros((nh, nh))
        for k in range(nh):
            for sgn, col in ((+1.0, 0), (-1.0, 1)):
                hp = h0.copy()
                hp[0, k] += sgn * eps
                _, tape, hn = self.forward_one(hp, x0)
                j[k, :] += sgn * hn[0] / (2.0 * eps)
        return j

    def forward_one(self, h, xi):
        p = self.p
        z = _sig(xi @ p["Wz"] + h @ p["Uz"] + p["bz"])
        r = _sig(xi @ p["Wr"] + h @ p["Ur"] + p["br"])
        uh = h @ p["Un"]
        n = np.tanh(xi @ p["Wn"] + r * uh + p["bn"])
        return None, None, (1.0 - z) * n + z * h


def adam_fit(net, x, y, *, task, epochs=EPOCHS, batch=BATCH, lr=LR, rng=None, quiet=True):
    """Adam on either a logistic loss (classify) or a squared loss (predict)."""
    rng = rng or np.random.default_rng(0)
    m = {k: np.zeros_like(v) for k, v in net.p.items()}
    v = {k: np.zeros_like(val) for k, val in net.p.items()}
    step = 0
    n = len(x)
    for _ in range(epochs):
        order = rng.permutation(n)
        for s in range(0, n, batch):
            idx = order[s : s + batch]
            xb, yb = x[idx], y[idx]
            out, tape, hl = net.forward(xb)
            if task == "classify":
                pr = _sig(out[:, 0])
                dout = ((pr - yb) / len(idx))[:, None]
            else:
                dout = (2.0 * (out[:, 0] - yb) / len(idx))[:, None]
            g = net.backward(tape, hl, dout)
            step += 1
            for k in net.p:
                m[k] = 0.9 * m[k] + 0.1 * g[k]
                v[k] = 0.999 * v[k] + 0.001 * g[k] ** 2
                mh = m[k] / (1 - 0.9**step)
                vh = v[k] / (1 - 0.999**step)
                net.p[k] -= lr * mh / (np.sqrt(vh) + 1e-8)
    return net


def auc(score, label) -> float:
    score = np.asarray(score, dtype=float)
    label = np.asarray(label)
    order = np.argsort(score)
    ranks = np.empty(len(score))
    ranks[order] = np.arange(1, len(score) + 1)
    np1 = float((label == 1).sum())
    np0 = float((label == 0).sum())
    if np1 == 0 or np0 == 0:
        return float("nan")
    return float((ranks[label == 1].sum() - np1 * (np1 + 1) / 2.0) / (np1 * np0))


def nstar(a: float, floor: float, n: int, se: float = 0.01) -> float:
    """At what sample would this gap separate. Infinite when there is no gap."""
    gap = abs(a - floor)
    return float("inf") if gap <= 1e-9 else float(n * (1.96 * 2 * se / gap) ** 2)


# --------------------------------------------------------------------------
# Condition 1: the gradient check, before anything else
# --------------------------------------------------------------------------


def gradient_check() -> dict:
    rng = np.random.default_rng(11)
    net = GRU(1, 5, 1, rng)
    x = rng.normal(0, 1, (4, 7, 1))
    y = (rng.random(4) > 0.5).astype(float)
    out, tape, hl = net.forward(x)
    pr = _sig(out[:, 0])
    dout = ((pr - y) / 4.0)[:, None]
    g = net.backward(tape, hl, dout)

    def loss():
        o, _, _ = net.forward(x)
        q = _sig(o[:, 0])
        return float(-np.mean(y * np.log(q + 1e-12) + (1 - y) * np.log(1 - q + 1e-12)))

    worst, where = 0.0, ""
    # See condition 1: 1e-6 is past the point where this loss can be differenced
    # in float64 and the check fails on its own roundoff.
    eps = 1e-5
    for k in net.p:
        flat = net.p[k].ravel()
        for i in range(min(flat.size, 12)):
            old = flat[i]
            flat[i] = old + eps
            lp = loss()
            flat[i] = old - eps
            lm = loss()
            flat[i] = old
            num = (lp - lm) / (2 * eps)
            ana = g[k].ravel()[i]
            rel = abs(num - ana) / max(abs(num), abs(ana), 1e-8)
            if rel > worst:
                worst, where = rel, f"{k}[{i}]"
    print(f"    worst relative gradient error {worst:.3e} at {where}")
    return {"worst_rel": worst, "where": where, "passes": bool(worst < 1e-6)}


# --------------------------------------------------------------------------
# Arm A: the net's Jacobian spectrum against the transfer operator's
# --------------------------------------------------------------------------


def windows(x: np.ndarray, seq: int, nrow: int, rng) -> tuple[np.ndarray, np.ndarray]:
    starts = rng.choice(len(x) - seq - 1, size=min(nrow, len(x) - seq - 1), replace=False)
    xs = np.stack([x[s : s + seq] for s in starts])[:, :, None]
    ys = np.array([x[s + seq] for s in starts])
    return xs, ys


def _one_arm_a(args) -> dict:
    kind, tau1, seed, seq = args
    rng = np.random.default_rng(seed)
    lam1 = 1.0 / tau1
    dvar = 1.0
    if kind == "box":
        # (pi/W)^2 * dvar/2 = lam1
        width = math.pi * math.sqrt(dvar / (2.0 * lam1))
        x, ep = G.sim_box(120000, width, dvar, 1e9, rng)
        true_ratio = 4.0
    else:
        x, ep = G.sim_ou(120000, lam1, dvar / 2.0 / lam1, 1e9, rng)
        true_ratio = 2.0
    xs = (x - x.mean()) / x.std()
    ur, _ = G.ulam_rates(xs, ep, max(2, int(round(0.5 * tau1))), nbin=96)
    net = GRU(1, HID, 1, rng)
    xw, yw = windows(xs, seq, NROW, rng)
    adam_fit(net, xw, yw, task="predict", rng=rng)
    _, _, hstates = net.forward(xw[:512])
    h0 = hstates.mean(axis=0, keepdims=True)
    ev = np.abs(np.linalg.eigvals(net.jacobian(h0, np.zeros((1, 1)))))
    ev = np.sort(ev)[::-1]
    ev = ev[(ev > 0) & (ev < 1.0)]
    rates = -np.log(ev[:3]) if ev.size else np.array([np.nan])
    sv = np.linalg.svd(hstates - hstates.mean(axis=0), compute_uv=False)
    return {
        "kind": kind, "tau1": tau1, "seq": seq,
        "true_l1": lam1, "ulam_l1": float(ur[0]), "gru_l1": float(rates[0]),
        "gru_tau1": 1.0 / float(rates[0]) if rates[0] > 0 else float("inf"),
        "gru_ladder": float(rates[1] / rates[0]) if rates.size > 1 and rates[0] > 0 else float("nan"),
        "true_ladder": true_ratio,
        "effective_rank": float((sv.sum() ** 2) / max((sv**2).sum(), 1e-12)),
    }


#: Relaxation times to scan, in steps, against a training window of SEQ.
TAUS = (4.0, 10.0, 25.0, 60.0, 150.0, 400.0)


def arm_a() -> dict:
    """Does the net's Jacobian spectrum find the truth, and when does it stop?

    The first run of this section asked the question at one timescale -
    `tau_1 = 292` steps against a 64-step training window - and the net returned
    an implied `tau_1` of 6.5. Both conditions fired. That is a real answer but a
    cheap one, because a one-step-ahead loss over a 64-step window has no
    gradient pressure to represent a mode that decays over 292 steps and
    backpropagation through time cannot see past its own window anyway.

    So the net is given a fair chance instead: the same architecture, the same
    budget, and the process's relaxation time scanned from a sixteenth of the
    training window to six times it. **If the net tracks the truth while the
    timescale fits and saturates near the window when it does not, then its
    Jacobian spectrum is reporting its training horizon** - which is the same
    failure `quantising.md`'s free-walk control found for a binned estimator and
    section six found for a delay embedding, arriving a third time by a third
    route.
    """
    print("\n=== Arm A: a learned latent state-space model against Ulam's method ===\n")
    print("    Both estimate one object - the relaxation spectrum - and they share no")
    print(f"    arithmetic. Training window is {SEQ} steps throughout; the process's")
    print("    relaxation time is scanned across it.\n")
    jobs = [(k, t, SEED + 17 * i, SEQ) for i, t in enumerate(TAUS) for k in ("spring", "box")]
    with ProcessPoolExecutor(max_workers=min(WORKERS, len(jobs))) as ex:
        rows = list(ex.map(_one_arm_a, jobs))
    print(
        f"    {'truth':7s} {'true tau1':>10s} {'tau1/SEQ':>9s} {'Ulam tau1':>10s} "
        f"{'GRU tau1':>9s} {'Ulam/true':>10s} {'GRU/true':>9s} {'GRU l2/l1':>10s} "
        f"{'true':>5s} {'rank':>5s}"
    )
    for r in sorted(rows, key=lambda v: (v["kind"], v["tau1"])):
        ut = 1.0 / r["ulam_l1"] if r["ulam_l1"] > 0 else float("inf")
        print(
            f"    {r['kind']:7s} {r['tau1']:10.0f} {r['tau1'] / r['seq']:9.2f} {ut:10.1f} "
            f"{r['gru_tau1']:9.1f} {ut / r['tau1']:10.3f} {r['gru_tau1'] / r['tau1']:9.3f} "
            f"{r['gru_ladder']:10.3f} {r['true_ladder']:5.1f} {r['effective_rank']:5.2f}"
        )
    fired = {}
    for r in rows:
        key = f"{r['kind']}_tau{r['tau1']:g}"
        ratio = r["gru_tau1"] / r["tau1"]
        c2 = not (0.5 <= ratio <= 2.0)
        c3 = abs(math.log(max(ratio, 1e-12))) >= abs(
            math.log(max((1.0 / r["ulam_l1"]) / r["tau1"], 1e-12))
        )
        fired[key] = {**r, "cond2_fired": bool(c2), "cond3_fired": bool(c3)}
    n2 = sum(v["cond2_fired"] for v in fired.values())
    n3 = sum(v["cond3_fired"] for v in fired.values())
    print(f"\n    condition 2 (GRU misses the truth by over 2x): fired {n2}/{len(fired)}")
    print(f"    condition 3 (GRU no closer than Ulam):          fired {n3}/{len(fired)}")
    return fired


def main() -> None:
    print("=" * 100)
    print("groundgru.py - a recurrent net as an identification instrument")
    print("=" * 100)
    res = {"seed": SEED, "hid": HID, "seq": SEQ, "epochs": EPOCHS}
    print("\n=== Condition 1: the gradient, before any data ===\n")
    res["gradient"] = gradient_check()
    if not res["gradient"]["passes"]:
        print("\n    Condition 1 FIRED. Nothing else is run: a hand-written recurrent")
        print("    net whose gradient is wrong is a random number generator with a")
        print("    loss curve, and every number below it would be decoration.")
        with open(OUT, "w") as fh:
            json.dump(res, fh, indent=1, default=float)
        return
    res["arm_a"] = arm_a()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(res, fh, indent=1, default=float)
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
