"""Would a third state earn anything? I5, computed rather than argued.

## What it said, 2026-10-10, eurusd 4h, 534 held-out points

    observability condition number at dt = 4h
      2-state reverting     2.483e+00
      3-state two-factor    4.084e+01
      3-state white jerk    3.724e+01

    held out
      2-state reverting     -1009.55   best
      3-state two-factor    -1083.48   -0.138 per point
      3-state white jerk    -1453.26   -0.831 per point

**Observability is not the blocker**, which matters because it is the argument
I5 reaches for. A condition number of 40 is nowhere near the ~1e8 where a state
stops being numerically identifiable: a third state is perfectly estimable from
price alone at this sampling rate.

**It loses anyway, and the fit declined it.** Offered a slow and a fast drift
component, the search set the fast one's noise to **zero** - a two-state model
with extra machinery. The reason is in the two-state fit: its best `theta` is a
3.5-hour half-life, so the rate retains 45% of itself across one 4h bar. A
second drift component would have to be more persistent than that to add
anything, and two time scales cannot be resolved in a quantity that barely
survives one sampling interval.

**The asymmetry is the finding.** Three states with white jerk lose 0.83 a point
and three states with reverting drift lose 0.14, so almost all of the gap was
the *instability* rather than the state count. Stability is worth about 0.7 nats
a point; the extra state is worth -0.14. The spec's suggested order puts I5
second and treats I3 as conditional on it - I5's answer turned out not to gate
I3 at all.

Measured on closes rather than touches, so it sets the direction and none of
the constants.


Two questions, and they are different:

1. **Is a third state identifiable at all** from price-only measurements at this
   sampling rate? That is observability, and it is a condition number.
2. **Does it win held out** on real bars, against the two-state model that
   currently does?

The three-state variant tested is a **two-factor drift**: the rate is the sum of
a slow and a fast Ornstein-Uhlenbeck component, so a level's drift can have two
time scales instead of one. That is the generalisation that keeps the stability
I3 is about - moving the reversion up a derivative instead would leave the rate
random-walking and reintroduce the defect one level higher.
"""

from __future__ import annotations

import csv
import math
import sys

import numpy as np
from scipy.linalg import expm

HOUR = 3600.0
NOISE = 0.40**2


def van_loan(A, Qc, dt):
    n = A.shape[0]
    M = np.zeros((2 * n, 2 * n))
    M[:n, :n] = A * dt
    M[:n, n:] = Qc * dt
    M[n:, n:] = -A.T * dt
    E = expm(M)
    F = E[:n, :n]
    Q = E[:n, n:] @ F.T
    return F, (Q + Q.T) / 2.0


def two_state(sigma2, theta):
    A = np.array([[0.0, 1.0], [0.0, -theta]])
    Qc = np.zeros((2, 2))
    Qc[1, 1] = sigma2
    return A, Qc


def three_state(s_slow, s_fast, th_slow, th_fast):
    # value' = slow + fast ; each component its own OU
    A = np.array([[0.0, 1.0, 1.0], [0.0, -th_slow, 0.0], [0.0, 0.0, -th_fast]])
    Qc = np.zeros((3, 3))
    Qc[1, 1] = s_slow
    Qc[2, 2] = s_fast
    return A, Qc


def jerk_state(q):
    A = np.array([[0.0, 1.0, 0.0], [0.0, 0.0, 1.0], [0.0, 0.0, 0.0]])
    Qc = np.zeros((3, 3))
    Qc[2, 2] = q
    return A, Qc


def run(A, Qc, times, meas, r, burn=3):
    n = A.shape[0]
    x = np.zeros(n)
    P = np.eye(n) * 1e6
    H = np.zeros((1, n))
    H[0, 0] = 1.0
    ll, scored, skipped = 0.0, 0, 0
    for i, (t, m) in enumerate(zip(times, meas)):
        if i:
            F, Q = van_loan(A, Qc, (t - times[i - 1]) / HOUR)
            x = F @ x
            P = F @ P @ F.T + Q
        S = float(P[0, 0] + r)
        if not np.isfinite(S) or S <= 0:
            skipped += 1
            continue
        y = float(m - x[0])
        if i >= burn:
            ll += -0.5 * (math.log(2 * math.pi * S) + y * y / S)
            scored += 1
        K = (P @ H.T / S).ravel()
        x = x + K * y
        P = P - np.outer(K, P[0, :])
    return ll, scored, skipped


# ---------------------------------------------------------- 1. observability
print("=== 1. is a third state identifiable from price alone, at 4h? ===")
print("Observability matrix condition number - how badly a state is pinned down.")
print("Higher is worse; past ~1e8 the state is numerically unidentified.\n")
for label, (A, _Qc) in (
    ("2-state reverting", two_state(0.18, 0.5)),
    ("3-state two-factor", three_state(0.1, 0.1, 0.1, 2.0)),
    ("3-state white jerk", jerk_state(1e-3)),
):
    n = A.shape[0]
    for dt in (4.0, 1.0, 0.25):
        F, _ = van_loan(A, np.zeros((n, n)), dt)
        H = np.zeros((1, n))
        H[0, 0] = 1.0
        O = np.vstack([H @ np.linalg.matrix_power(F, k) for k in range(n)])
        print(f"  {label:<20} dt={dt:>5}h  cond = {np.linalg.cond(O):.3e}")
    print()

# ---------------------------------------------------------- 2. held out, real bars
rows = []
with open(sys.argv[1]) as fh:
    for row in csv.DictReader(fh):
        if row["venue"] == "FOREXCOM" and row["close"]:
            rows.append((int(row["ts"]), float(row["close"])))
rows.sort()
closes = [c for _t, c in rows]
alpha = 1.0 - 0.5 ** (1.0 / 60.0)
ma = 0.0
for i in range(1, len(closes)):
    mv = abs(closes[i] - closes[i - 1]) / closes[i - 1] * 10_000
    ma = mv if i == 1 else ma + alpha * (mv - ma)
bps = max(ma, 0.25)
times = [float(t) for t, _c in rows]
meas = [(c / closes[0] - 1.0) * 10_000 / bps for c in closes]
half = len(meas) // 2

print(f"=== 2. held out on {len(meas)} real eurusd 4h bars, fitted on {half} ===\n")


def fit(make, grid, label):
    best = (-math.inf, None)
    for params in grid:
        A, Qc = make(*params)
        ll, scored, skipped = run(A, Qc, times[:half], meas[:half], NOISE)
        if skipped or not math.isfinite(ll):
            continue
        if ll > best[0]:
            best = (ll, params)
    if best[1] is None:
        print(f"  {label}: no candidate could score the training half")
        return None
    A, Qc = make(*best[1])
    ll, scored, skipped = run(A, Qc, times[half:], meas[half:], NOISE)
    print(
        f"  {label:<20} held out {ll:9.2f} over {scored} pts  params {tuple(round(float(v), 4) for v in best[1])}"
    )
    return ll, scored


e = np.arange(-6, 1.01, 0.5)
res = {}
res["2-state"] = fit(
    two_state,
    [(10**a, th) for a in e for th in (0.05, 0.1, 0.2, 0.5, 1.0, 2.0)],
    "2-state reverting",
)
res["3-factor"] = fit(
    three_state,
    [
        (10**a, 10**b, ts, tf)
        for a in np.arange(-5, 0.01, 1.0)
        for b in np.arange(-5, 0.01, 1.0)
        for ts in (0.02, 0.1, 0.5)
        for tf in (1.0, 3.0, 10.0)
    ],
    "3-state two-factor",
)
res["3-jerk"] = fit(jerk_state, [(10**a,) for a in e], "3-state white jerk")

print()
got = {k: v for k, v in res.items() if v}
if len(got) > 1:
    counts = {v[1] for v in got.values()}
    if len(counts) > 1:
        print("  !! NOT COMPARABLE - different observation counts")
    else:
        best = max(got, key=lambda k: got[k][0])
        print(f"  best: {best}")
        for k, v in sorted(got.items(), key=lambda kv: -kv[1][0]):
            print(
                f"    {k:<10} {v[0]:9.2f}  ({(v[0] - got[best][0]) / v[1]:+.4f} per point vs best)"
            )
