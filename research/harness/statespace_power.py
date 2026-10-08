"""Power curve for `statespace.py`: quantum-generated series at rising signal strength.

S2 in `statespace.py` is one strength (oracle AUC 0.574). Here the generator's regime means are
scaled so the *oracle* - the true model filtering its own series - spans roughly 0.55 to 0.70,
and every filter is fitted on the first 60% and scored on the last 40%. The question is not how
high the synthetic can go (that is set by us) but whether the fitted filters track the oracle as
the signal grows, on AUC, log score and regime accuracy - and at which strength each sample size
could have seen it. Two lengths: 30,000 bars (a 15m or 1h series) and 2,800 (V75 daily).

Run on the lab, beside `statespace.py`:
  OUT=<out>.json python research/harness/statespace_power.py
"""

from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from scipy.linalg import expm
from scipy.stats import norm

sys.path.insert(0, str(Path(__file__).parent))
import statespace as ss

OUT = Path(os.environ.get("OUT", "statespace_power.json"))
SEPS = (0.4, 0.6, 0.8, 1.0, 1.3)  # regime-mean spacing; S2 in statespace.py is 0.4
LENGTHS = (30000, 2800)


def generate(n, sep, seed):
    rng = np.random.default_rng(seed)
    H = ss.herm(rng.normal(0, 0.15, 9))
    U, V = expm(-1j * H), expm(-1j * ss.herm(rng.normal(0, 0.8, 9)))
    mu, sd = np.array([-sep, 0.0, sep]), np.array([1.0, 0.6, 1.0])
    rho = np.eye(3, dtype=complex) / 3
    y, s = np.empty(n), np.empty(n, int)
    for t in range(n):
        rp = U @ rho @ U.conj().T
        w = np.clip(np.real(np.diag(V.conj().T @ rp @ V)), 0, None)
        k = rng.choice(3, p=w / w.sum())
        y[t], s[t] = mu[k] + sd[k] * rng.standard_normal(), k
        f = np.array([norm.pdf(y[t], mu[i], sd[i]) for i in range(3)])
        M = V @ np.diag(np.sqrt(f)) @ V.conj().T
        rho = M @ rp @ M.conj().T
        rho /= np.real(np.trace(rho))
    return y, s, (U, V, mu, sd)


def cell(args):
    n, sep = args
    y, s, (U, V, mu, sd) = generate(n, sep, 43)
    tr = int(n * ss.TRAIN)
    res, info = ss.run_all(y[:, None], tr)
    te = np.arange(n) >= tr
    up = (y[te] > 0).astype(int)
    p, l_, st = np.empty(n), np.empty(n), np.empty(n, np.int64)
    ss.q_run(y[:, None], U, V, mu[:, None], sd[:, None], 0.0, p, l_, st)
    rw = res["rw"][1][te]
    out = {"oracle": dict(auc=ss.auc(up, p[te]), logscore_mnats=1000 * float(np.mean(l_[te] - rw)),
                          regime=ss.regime_acc(s[te], st[te]))}
    for m in ss.MODELS:
        pm, lm, sm = res[m]
        out[m] = dict(auc=ss.auc(up, pm[te]), logscore_mnats=1000 * float(np.mean(lm[te] - rw)),
                      regime=ss.regime_acc(s[te], sm[te]) if sm is not None else None)
    out["gamma"] = {k: v["gamma"] for k, v in info.items() if k.startswith("q")}
    return n, sep, out


if __name__ == "__main__":
    jobs = [(n, sep) for n in LENGTHS for sep in SEPS]
    results = []
    with ProcessPoolExecutor(len(jobs)) as ex:
        for n, sep, out in ex.map(cell, jobs):
            results.append(dict(n=n, sep=sep, **out))
            print("done", n, sep, {k: round(v["auc"], 3) for k, v in out.items() if k != "gamma"}, flush=True)
            OUT.write_text(json.dumps(ss.clean(results), indent=1))
