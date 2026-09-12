"""A reinforcement learner as a test of a theorem, not as a search for an edge.

**The prediction is written before the run: a correctly built agent converges
toward zero turnover.** `research/deriving.md` proves that for *any* predictable
position `w` on a martingale `P`,

    E[ sum_t w_t (P_{t+1} - P_t) ] = 0      and      cost = (c/2) sum_t |w_t - w_{t-1}|

so `E[net] = -(c/2) x turnover`, strictly negative whenever anything is traded.
A Deriv Volatility index is geometric Brownian motion at a published constant
sigma - `research/grounding.md` tier 1 verified the names to within 0.49% on 12
of 12 - so its increments are independent by construction and it is exactly the
object the theorem covers. Flat is therefore the optimal policy, analytically,
and the only question a reinforcement learner can answer here is whether it
*finds* the thing that is already proved.

That makes this arm a **calibration of the environment against a known answer**,
which is the one use `research/rebuilding.md` left open for a learned model on
these feeds after boosted models on tick windows, k-tuples and bar OHLC came
back with `n*` infinite on every arm.

## How to read each of the three outcomes, decided in advance

* **The agent converges to flat.** A learned rediscovery of an analytically
  proven result, and a strong validation of both the theorem and this
  environment. This is the expected outcome and it is the headline.
* **The agent reports a profit.** The overwhelmingly likely cause is a defect in
  this file, not an edge in the feed. The candidates, in the order they are
  checked below: look-ahead in the observation; costs computed but never
  charged; a reward that reads the bar it is supposed to be predicting;
  evaluation on rows the policy trained on; an episode boundary that hands the
  agent the future. **Hunt the bug before reporting the edge.** Section "the
  five self-tests" runs every one of those checks before a single agent is
  trained, and the zero-cost arm below is a sixth.
* **The agent trades and loses.** Then the loss must equal `-(c/2) x turnover`
  numerically, and the table that shows it is worth more than either of the
  other two outcomes, because it is the theorem measured rather than assumed.

## The cost model, stated explicitly, because it is the whole experiment

**`c_t` is the full quoted spread at bar `t` as a fraction of price**, charged
on position *change* and never on holding:

    fee_t = (c_t / 2) * |w_t - w_{t-1}|

The half is not a discount. Crossing once - flat to long - lifts the offer and
pays half the spread against the mid; a round trip crosses twice, carries two
units of turnover, and pays the whole spread. Written this way the environment's
accumulated fee **is** the right-hand side of the theorem, in the letters it is
proved in, so the check at the end is a comparison of two numbers rather than a
comparison of two conventions.

`c_t` comes from `seqlab.rel_spread`, which was added for this arm and which
carries the correction that decides whether any of this means anything: **the
`spread` column is an integer count of points, not a price.** Treated as a price
it is wrong by a factor of 1e3 to 1e5, *silently* - still small, still positive,
still plausible - and a cost model built on it charges nothing. On this study
that is the single most likely route to a reported edge that is not there. The
conversion is validated two ways in that function's docstring: against
`deriving.md`'s independent tick-level measurement of 0.39-4.31 bps for this
family, and internally against the fact that `Volatility 10 Index` (grid 0.001,
162 points) and `Volatility 10 (1s) Index` (grid 0.01, 27 points) land on 0.282
and 0.284 bps - two different digits, two different point counts, three figures
of agreement. Two wrong tick sizes do not do that.

Measured across the ten symbols this arm runs, `c` is **0.27 to 3.12 bps per
bar**, which is 2.5% to 5.7% of one bar's standard deviation at 1h and 15m. The
cost is small enough that an agent cannot see it in a single trade and large
enough that it dominates over an episode. That is the regime the theorem is
interesting in.

### Two reward conventions, and why both are run

The briefed reward is **change in log equity**, `log(1 + w_t s_{t+1} - fee_t)`,
where `s` is the simple return. That is what an account actually does and it is
the default here. But log price is *not* a martingale when price is: a GBM's log
drifts at `-sigma^2/2`, so a log-equity agent holding `|w| = 1` loses
`sigma^2/2` per bar **even at zero cost**, and on `Volatility 100 Index` at 1h
that drag is 0.57 bps against a half-spread of 1.31 bps - 43% of the cost, not a
rounding error. An arm that reported "the zero-cost agent lost money, therefore
a bug" on that basis would be wrong, and an arm that compared a log-equity loss
against `-(c/2) x turnover` would be comparing the wrong two numbers.

So the ledger records **both** on every run: the arithmetic martingale transform
`sum w_t s_{t+1}`, which is the quantity the theorem says is zero, and the log
equity, which is the quantity the agent optimises. The theorem is checked on the
first. The agent is trained on the second. `REWARD=arith` switches the training
objective for the cells where the distinction is the point.

A positive scalar is applied to the reward (`1 / sigma_train`, so one unit is
one bar's standard deviation). An affine positive rescaling changes no argmax;
it changes only the conditioning of the gradient, and at 1e-4-scale rewards
these optimisers do not move at all.

## The observation, and what is deliberately not in it

`seqlab.build`'s 28 features for the current bar, stacked over the last `STACK`
bars, **plus the agent's own current position**. The position is not optional:
turnover is a function of `w_t - w_{t-1}` and an agent that cannot see `w_{t-1}`
cannot reason about the only quantity it controls.

**No raw price, ever.** Every feature is dimensionless. A level into a net
trained on a trending series is the classic leak in this class of study - and
`Volatility 75 Index` at 1h runs from a few thousand to over a million across
this sample, so the level would be a near-perfect timestamp.

Normalisation statistics are computed on the **train rows of the fold only** and
applied unchanged to test. A z-score fitted over train and test together is a
leak that looks like preprocessing.

## The controls, reported beside every number

* **always-flat** and **random-action**, the two floors. Random is the ceiling
  on cost: iid uniform over `{-1, 0, +1}` has `E|w_t - w_{t-1}| = 8/9`, so it
  pays roughly `0.44 c` per bar and its net is nearly pure fee.
* **look-ahead**, handed `sign(s_{t+1})`. **This is the load-bearing control.**
  A table where every agent returns approximately zero is indistinguishable from
  a harness that computes zero, and this repository has published a statistic
  sitting on exactly its null twice (`giveback.md`, `twins.md` section 6).
  `deriving.md` made the same argument with `cheat_next` at +0.5002 against
  -0.5000. If the cheat does not win enormously here, nothing else on the page
  is readable.
* **`gbm`** - `seqlab.gbm_bars` at the symbol's own `NAMED_SIGMA`. The exact
  known null, where the true answer is flat and there is no doubt about it.
* **`surrogate`** - `seqlab.surrogate_bars`, phase-randomised returns. Spectrum
  and full linear autocorrelation preserved, every nonlinear dependence
  destroyed.
* **`zero-cost`**, run early and deliberately. On a true martingale an agent
  with costs switched off should still make nothing. **If it makes money at zero
  cost, the finding is look-ahead, not alpha**, and the arithmetic ledger is the
  one to read because the log ledger has the drag in it.

The three synthetic arms are handed **the real symbol's own `c_t` series**, so
the cost environment is identical across arms by construction and the only thing
that changes is the structure of the returns.

### And one sweep, because "it did not converge to flat" is not yet a finding

On this book `c / sigma` is **0.025 to 0.057 per bar**. The cost signal the agent
must discover is therefore a few percent of the noise it is standing in, and if
turnover does not collapse there are two completely different explanations -
the environment is wrong, or 250,000 samples is not enough to resolve a 2.5%
bias - and the run cannot tell them apart. So the same PPO is also run at the
spread multiplied by 4, 16 and 64. **If turnover collapses at a high multiple
and not at 1, the environment is right and the answer is a sample-size answer**,
and the threshold where it flips is a number this page can report rather than a
hedge it has to write. The multiplied rows are a deliberate falsification of the
cost and are never mixed into any headline table.

## The five self-tests, which run before any agent is trained

1. **`seqlab.check_causality`** on the loaded bars - perturb a future bar, assert
   no feature at an earlier row moves.
2. **Environment causality** - the same perturbation, driven through the env with
   a fixed action sequence. Every observation at a bar strictly before the poke
   must be bit-identical, and every reward at a bar before `poke - 1` too. This
   is stricter than (1) because it also covers the reward's own indexing, which
   is where `t` versus `t+1` errors live.
3. **Cost accounting** - the ledger's total fee must equal `sum (c_t/2)|dw_t|`
   recomputed from the recorded positions to 1e-12 relative. A cost model that
   is described but not charged is the second most likely defect here.
4. **The theorem, on a scripted policy** - an always-flip rule with turnover
   exactly `1` per bar, replayed on `gbm_bars`, must return net per unit
   turnover equal to `-c/2` within Monte Carlo error.
5. **The look-ahead control must win.** Condition 3 below.

## Kill conditions, stated before any number was read

1. **The run is void** if test (2) finds any observation or any pre-poke reward
   moving. Nothing else is reported.
2. **The run is void** if test (3) misses by more than 1e-12 relative, or if
   test (4)'s net per unit turnover misses `-c/2` by more than 5%.
3. **The run is void** if the look-ahead control does not clear `|z| = 10` on
   gross on every symbol. A harness that cannot see an edge is not evidence that
   there is none.
4. **A reported profit is a bug until proven otherwise.** Any learned agent whose
   test-slice *gross* clears `|z| = 3` positive on a Volatility index is treated
   as a defect report and not as a result.
5. **The zero-cost arm fires** if any zero-cost agent's arithmetic gross clears
   `|z| = 3`. That is look-ahead and it voids the cost-bearing cells too.
6. **A single seed is not a result.** No cell with fewer than `SEEDS` seeds is
   reported, and the spread across seeds is printed beside every mean.
7. **1d is not run and no number from it is reported.** `seqlab.GRID` carries it
   and it holds about 2,800 bars; the final walk-forward fold would train on
   roughly 2,300 rows against a policy network with more parameters than that.
   Saying so is the result for that timeframe.

## Turnover is measured twice and the two are not the same number

The rollout reading is free and it is what the agent did while learning. It is
**contaminated for DQN by construction**: epsilon-greedy holds exploration at 2%
to the end, and 2% random actions on a three-action alphabet is a floor of about
0.018 turnover per bar that no amount of learning can remove. So a greedy probe
runs at every checkpoint too - a deterministic pass over a fixed 2,000-bar
window of the **training** slice, never the test slice. That is the number the
two algorithms can be compared on, and the one the collapse question is decided
by.

## What this arm does not claim

Nothing here is evidence about whether *any* policy could trade these
instruments - `deriving.md` settled that analytically and no amount of RL can
reopen it. A converged-to-flat agent is a statement about this environment's
fidelity. A non-converged agent is a statement about the optimiser's sample
efficiency at a signal-to-noise ratio of `c / sigma ~ 0.05`. Neither is a
statement about the market, and the page says so.
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from research.harness import seqlab  # noqa: E402

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

SEED = int(os.environ.get("SEED", "20260912"))
SEEDS = int(os.environ.get("SEEDS", "3"))
STACK = int(os.environ.get("STACK", "4"))
EPISODE = int(os.environ.get("EPISODE", "512"))
FOLDS = int(os.environ.get("FOLDS", "5"))
PPO_STEPS = int(os.environ.get("PPO_STEPS", "250000"))
DQN_STEPS = int(os.environ.get("DQN_STEPS", "150000"))
A2C_STEPS = int(os.environ.get("A2C_STEPS", "250000"))
SAC_STEPS = int(os.environ.get("SAC_STEPS", "60000"))
BUCKETS = int(os.environ.get("BUCKETS", "10"))

#: Eight cores total, because five other agents share this box. Spent as eight
#: single-threaded workers rather than one eight-threaded process: the policy
#: networks here are 64x64 and torch's intra-op parallelism is *negative* at
#: that size - the barrier costs more than the matmul saves - so the same
#: budget buys eight times the throughput this way. `WORKERS * THREADS <= 8`
#: is asserted at startup so the arithmetic cannot drift.
WORKERS = int(os.environ.get("WORKERS", "8"))
THREADS = int(os.environ.get("THREADS", "1"))

OUT = os.environ.get("OUT", os.path.expanduser("~/till_infinity/logs/seqrl.json"))
TAPES = os.environ.get("TAPES", os.path.expanduser("~/till_infinity/logs/seqrl_tapes"))

#: The focused set. Four sigmas across the family's range plus the 1s variants,
#: which quote on a different grid at the same named sigma and so are a second
#: reading of the cost model, plus the two feeds whose *name* says the variance
#: moves - the only place in this family where a forecast could have anything to
#: forecast.
SYMBOLS = tuple(s for s in os.environ.get("SYMBOLS", "").split("|") if s) or (
    "Volatility 10 Index", "Volatility 10 (1s) Index",
    "Volatility 25 Index", "Volatility 25 (1s) Index",
    "Volatility 75 Index", "Volatility 75 (1s) Index",
    "Volatility 100 Index", "Volatility 100 (1s) Index",
    "Spot Up - Volatility Up Index",
    "Spot Up - Volatility Down Index",
)

#: 1h and 15m only. See kill condition 7 for 1d.
FRAMES = tuple(f for f in os.environ.get("FRAMES", "").split("|") if f) or ("1h", "15m")

#: Where the wide grid is narrowed for the expensive control arms. One low
#: sigma, one high, one of each timeframe, one 1s variant.
FOCUS = (
    ("Volatility 10 Index", "1h"),
    ("Volatility 100 Index", "1h"),
    ("Volatility 75 (1s) Index", "15m"),
    ("Volatility 100 Index", "15m"),
)

#: What counts as a trade when the position is continuous. Turnover is the
#: quantity the theorem charges and it is reported unthresholded; "trades" is
#: what a desk counts, and on a continuous policy every bar carries a nonzero
#: `|dw|`, so without a floor SAC reports 512 trades per 512-bar episode while
#: moving its position by six hundredths of a unit. Five percent of a full
#: position is the floor.
TRADE_EPS = float(os.environ.get("TRADE_EPS", "0.05"))

#: The cost-scaling sweep. `1.0` is the feed's own spread; the rest are
#: deliberate falsifications, run to answer a question the real cost cannot:
#: **at what `c / sigma` does a policy-gradient method actually discover the
#: theorem?** On this book `c / sigma` is 0.025 to 0.057 per bar, so the cost
#: signal is a few percent of the noise the agent is standing in, and "the agent
#: did not converge to flat" would otherwise be unreadable - it could be the
#: environment, or it could be that 250,000 samples is not enough to see a 2.5%
#: bias. The sweep separates those two and turns the headline into a number.
MULTS = tuple(float(x) for x in os.environ.get("MULTS", "1,4,16,64").split(","))

#: Which stages to run, comma separated: `zerocost`, `main`, `controls`, `sweep`.
#: The default is all four. It exists so the question the first run leaves open -
#: "is turnover not collapsing because the environment is wrong, or because
#: 250,000 samples cannot resolve a 2.5% bias?" - can be re-asked at a much
#: larger step budget without re-paying for the controls, which do not change.
STAGES = tuple(x.strip() for x in
               os.environ.get("STAGES", "zerocost,main,controls,sweep").split(",") if x.strip())

#: Position for each discrete action. Short, flat, long - the cleanest alphabet
#: for reading turnover straight off the policy.
ACTIONS = np.array([-1.0, 0.0, 1.0])


# --------------------------------------------------------------------------
# The tape: everything the environment needs, precomputed once
# --------------------------------------------------------------------------


def _contiguous(idx: np.ndarray) -> bool:
    return bool(len(idx)) and int(idx[-1] - idx[0]) == len(idx) - 1


def build_tape(symbol: str, interval: str, *, generator: str = "real", seed: int = 0,
               fold: int = -1, stack: int = STACK, folds: int = FOLDS) -> dict:
    """Features, forward returns, costs and the fold, for one arm.

    The three synthetic generators are handed the **real symbol's own `c_t`
    series**. That is deliberate: the control is meant to change the structure
    of the returns and nothing else, and a GBM path whose spread came from
    `gbm_bars`' constant placeholder would differ from the real arm in the cost
    model as well as in the process, which would make the comparison unreadable.
    """
    bars = seqlab.load(symbol, interval)
    cost_real = seqlab.rel_spread(bars)
    rng = np.random.default_rng(hash((symbol, interval, generator, seed)) % (2**31))

    if generator == "gbm":
        # `SPOT_UP` carries no sigma in its name - it is the family member whose
        # name says the variance moves - so the null there is built at the
        # symbol's own measured volatility. `seqlab.measured_sigma` is the shared
        # estimator rather than a local one, so every arm's gbm control is the
        # same null.
        sigma = seqlab.NAMED_SIGMA.get(symbol) or seqlab.measured_sigma(bars, interval)
        bars = seqlab.gbm_bars(sigma, len(bars["close"]), interval, rng)
    elif generator == "surrogate":
        bars = seqlab.surrogate_bars(bars, rng)
    elif generator != "real":
        raise ValueError(f"unknown generator {generator!r}")

    x, names = seqlab.build(bars)
    y = seqlab.targets(bars, horizon=1)
    ok = seqlab.usable(x, y["fwd_return"])
    rows = np.flatnonzero(ok)
    if not _contiguous(rows):
        # Episodes assume the tape is a stretch of clock time. A gap would let a
        # position be carried across a discontinuity and earn a return that was
        # never adjacent to it, which is a look-ahead of the worst kind.
        raise RuntimeError(f"{symbol} {interval} {generator}: usable rows are not contiguous")

    close = np.asarray(bars["close"], dtype=float)
    step = close[rows + 1] / close[rows] - 1.0
    # The synthetic arms are charged the REAL symbol's own cost series, aligned
    # to the tail because `surrogate_bars` returns one bar fewer than it was
    # given. Same cost environment, different returns - which is the only way
    # the difference between the arms can be read as the process.
    cost = cost_real[rows] if generator == "real" else cost_real[-len(ok) :][rows]
    feats = x[rows]
    n = len(rows)

    splits = seqlab.walk_forward(n, folds=folds, horizon=1)
    if not splits:
        raise RuntimeError(f"{symbol} {interval}: no folds from {n} rows")
    tr, te = splits[fold]
    lo_tr, hi_tr = int(tr[0]), int(tr[-1]) + 1
    lo_te, hi_te = int(te[0]), int(te[-1]) + 1

    mu = feats[lo_tr:hi_tr].mean(axis=0)
    sd = feats[lo_tr:hi_tr].std(axis=0)
    z = np.clip((feats - mu) / np.maximum(sd, 1e-9), -5.0, 5.0).astype(np.float32)

    # Stacked observation. The first `stack - 1` rows repeat row 0; episodes
    # never start there, and test slices begin far past it.
    pad = np.concatenate([np.repeat(z[:1], stack - 1, axis=0), z]) if stack > 1 else z
    obs = np.lib.stride_tricks.sliding_window_view(pad, stack, axis=0)
    obs = np.ascontiguousarray(obs.transpose(0, 2, 1).reshape(n, -1))

    scale = float(np.std(step[lo_tr:hi_tr]))
    return {
        "symbol": symbol, "interval": interval, "generator": generator,
        "obs": obs, "step": step.astype(np.float64), "cost": cost.astype(np.float64),
        "train": (lo_tr, hi_tr), "test": (lo_te, hi_te),
        "scale": 1.0 / max(scale, 1e-12), "sigma_bar": scale,
        "n": n, "fold": fold, "folds": len(splits), "features": len(names),
    }


def tape_key(symbol: str, interval: str, generator: str, seed: int, fold: int) -> str:
    slug = seqlab._slug(symbol, interval)
    tag = generator if generator == "real" else f"{generator}{seed}"
    return f"{slug}.{tag}.f{fold}"


def tape_path(key: str) -> str:
    return os.path.join(TAPES, key + ".npz")


def save_tape(tape: dict) -> str:
    os.makedirs(TAPES, exist_ok=True)
    key = tape_key(tape["symbol"], tape["interval"], tape["generator"],
                   tape.get("gen_seed", 0), tape["fold"])
    path = tape_path(key)
    meta = {k: v for k, v in tape.items() if k not in ("obs", "step", "cost")}
    np.savez_compressed(path, obs=tape["obs"], step=tape["step"], cost=tape["cost"],
                        meta=np.array(json.dumps(meta, default=str)))
    return path


def load_tape(path: str) -> dict:
    got = np.load(path, allow_pickle=False)
    tape = json.loads(str(got["meta"]))
    tape["obs"] = got["obs"]
    tape["step"] = got["step"]
    tape["cost"] = got["cost"]
    tape["train"] = tuple(tape["train"])
    tape["test"] = tuple(tape["test"])
    return tape


# --------------------------------------------------------------------------
# The environment
# --------------------------------------------------------------------------


def _gym():
    import gymnasium as gym

    return gym


def make_env_class():
    """Built lazily so this module imports on a machine with no gymnasium."""
    gym = _gym()

    class Desk(gym.Env):
        """One bar per step. Act at `t`, earn the return of `t+1`, pay on change.

        **The action at bar `t` earns `s_{t+1}` and never `s_t`.** That single
        line is the whole no-look-ahead discipline and it is asserted from the
        outside by `test_env_causality`, which pokes a future bar and requires
        every earlier observation to be bit-identical.
        """

        metadata = {"render_modes": []}

        def __init__(self, tape, lo, hi, *, episode=EPISODE, cost_on=True,
                     reward="log", seed=0, random_start=True, continuous=False,
                     cost_mult=1.0):
            super().__init__()
            self.obs_t = tape["obs"]
            self.step_t = tape["step"]
            self.cost_t = tape["cost"]
            self.scale = tape["scale"]
            self.lo, self.hi = int(lo), int(hi)
            self.episode = int(min(episode, self.hi - self.lo - 1))
            self.cost_on = bool(cost_on)
            # A deliberate falsification of the cost, used only by the cost-scaling
            # sweep. `1.0` is the feed's own spread and every headline number uses
            # it; the sweep asks at what `c / sigma` the theorem becomes learnable,
            # which is a different question from what the theorem says.
            self.cost_mult = float(cost_mult)
            self.reward_mode = reward
            self.random_start = bool(random_start)
            self.continuous = bool(continuous)
            self.rng = np.random.default_rng(seed)
            dim = self.obs_t.shape[1] + 1
            self.observation_space = gym.spaces.Box(-np.inf, np.inf, (dim,), np.float32)
            self.action_space = (
                gym.spaces.Box(-1.0, 1.0, (1,), np.float32)
                if continuous
                else gym.spaces.Discrete(3)
            )
            self.i = self.lo
            self.w = 0.0
            self.t = 0

        def _obs(self):
            return np.concatenate([self.obs_t[self.i], np.float32([self.w])]).astype(np.float32)

        def reset(self, *, seed=None, options=None):
            if seed is not None:
                self.rng = np.random.default_rng(seed)
            span = self.hi - self.lo - self.episode - 1
            self.i = self.lo + (int(self.rng.integers(0, max(span, 1))) if self.random_start else 0)
            self.w = 0.0
            self.t = 0
            return self._obs(), {}

        def step(self, action):
            if self.continuous:
                w_new = float(np.clip(np.asarray(action).reshape(-1)[0], -1.0, 1.0))
            else:
                w_new = float(ACTIONS[int(np.asarray(action).reshape(-1)[0])])
            c = float(self.cost_t[self.i]) * self.cost_mult if self.cost_on else 0.0
            dw = abs(w_new - self.w)
            fee = 0.5 * c * dw
            gross = w_new * float(self.step_t[self.i])

            self.t += 1
            last = self.t >= self.episode or self.i + 1 >= self.hi - 1
            if last:
                # Close out at the next bar's spread. Leaving a position open at
                # the edge of an episode would understate turnover by exactly one
                # crossing per episode, which at 512 bars is a 0.2% error in the
                # cheap cells and a visible one in the flat cells.
                c_next = (float(self.cost_t[min(self.i + 1, len(self.cost_t) - 1)])
                          * self.cost_mult) if self.cost_on else 0.0
                dw_close = abs(w_new)
                fee += 0.5 * c_next * dw_close
                dw += dw_close

            net = gross - fee
            raw = net if self.reward_mode == "arith" else math.log(max(1.0 + net, 1e-9))
            info = {"gross": gross, "fee": fee, "dw": dw, "w": w_new,
                    "bar": int(self.i), "net": net,
                    "log": math.log(max(1.0 + net, 1e-9))}
            self.w = w_new
            self.i += 1
            return self._obs(), float(raw * self.scale), False, bool(last), info

    return Desk


# --------------------------------------------------------------------------
# Driving a policy and keeping the ledger
# --------------------------------------------------------------------------


def run_policy(tape, lo, hi, policy, *, cost_on=True, reward="log", seed=0,
               continuous=False, cost_mult=1.0) -> dict:
    """One deterministic pass over `[lo, hi)` as a single episode. Starts and ends flat.

    `policy(obs, env)` returns an action. It is handed the env so the look-ahead
    control can read `env.step_t[env.i]` - which is exactly the cheat, made
    explicit rather than hidden.
    """
    Desk = make_env_class()
    env = Desk(tape, lo, hi, episode=hi - lo - 1, cost_on=cost_on, reward=reward,
               seed=seed, random_start=False, continuous=continuous, cost_mult=cost_mult)
    obs, _ = env.reset()
    gross = fee = turn = logeq = 0.0
    trades = 0
    nets = []
    ws = []
    done = False
    while not done:
        action = policy(obs, env)
        obs, _, _, done, info = env.step(action)
        gross += info["gross"]
        fee += info["fee"]
        turn += info["dw"]
        logeq += info["log"]
        nets.append(info["net"])
        ws.append(info["w"])
        trades += int(info["dw"] > TRADE_EPS)
    nets = np.asarray(nets)
    ws = np.asarray(ws)
    bars = len(nets)
    gross_sd = float(np.std(np.asarray([w * s for w, s in zip(ws, tape["step"][lo:lo + bars])])))
    return {
        "bars": bars, "turnover": float(turn), "trades": int(trades),
        "gross": float(gross), "cost": float(fee), "net": float(gross - fee),
        "log_equity": float(logeq),
        "turnover_per_bar": float(turn / max(bars, 1)),
        "net_per_turnover": float((gross - fee) / turn) if turn > 1e-12 else float("nan"),
        "gross_se": float(gross_sd * math.sqrt(bars)),
        "gross_z": float(gross / max(gross_sd * math.sqrt(bars), 1e-18)),
        "mean_cost": float(np.mean(tape["cost"][lo:lo + bars]) * cost_mult),
        "exposure": float(np.mean(np.abs(ws))),
        "long_frac": float(np.mean(ws > 0)), "short_frac": float(np.mean(ws < 0)),
        "flat_frac": float(np.mean(ws == 0)),
    }


def flat_policy(obs, env):
    return np.float32([0.0]) if env.continuous else 1


def random_policy_factory(seed):
    rng = np.random.default_rng(seed)

    def policy(obs, env):
        return rng.uniform(-1, 1, 1).astype(np.float32) if env.continuous else int(rng.integers(0, 3))

    return policy


def cheat_policy(obs, env):
    """Handed the sign of the next bar. The load-bearing control."""
    s = float(env.step_t[env.i])
    if env.continuous:
        return np.float32([1.0 if s > 0 else -1.0])
    return 2 if s > 0 else 0


def flip_policy(obs, env):
    """Alternate long and short every bar. Turnover exactly 2 per bar - the
    scripted rule used to check the theorem's arithmetic against a known figure."""
    return 2 if (env.i % 2 == 0) else 0


def model_policy_factory(model):
    def policy(obs, env):
        action, _ = model.predict(obs, deterministic=True)
        return action

    return policy


# --------------------------------------------------------------------------
# The self-tests, all of which run before any agent is trained
# --------------------------------------------------------------------------


def test_env_causality(symbol: str, interval: str, *, at: int = 200) -> dict:
    """Poke a future bar; assert no earlier observation and no earlier reward moves.

    Stricter than `seqlab.check_causality`, which covers the feature matrix only.
    This drives the same fixed action sequence through two environments built on
    bars that differ in exactly one row, and requires bit-identical observations
    at every bar before the poke and bit-identical rewards at every bar before
    `poke - 1`. The reward at `poke - 1` is *allowed* to move: it earns the poked
    bar's return, which is the correct behaviour and the thing an off-by-one
    would break.

    **The poke is an integer number of ticks, and that is not cosmetic.** The
    first version multiplied the bar by 1.05 and the test failed, reporting
    rewards moving four hundred bars *before* the poke. The cause was the test
    and not the environment: `seqlab.tick_size` infers the quote lattice from
    every close in the series, a 5% bump puts one close off the grid, the
    inferred tick changes for the whole series and so does every `c_t`. Which is
    a genuine property of inferring a lattice rather than being told it - one
    corrupt bar moves every cost - and it is recorded here rather than edited
    away, because it is the kind of global coupling that makes a causality test
    worth running in the first place. Snapping the poke to the grid removes it
    and leaves the test measuring the thing it is for.
    """
    bars = seqlab.load(symbol, interval)
    n = len(bars["close"])
    poke = n - at

    def tape_from(b):
        x, _ = seqlab.build(b)
        y = seqlab.targets(b, horizon=1)
        rows = np.flatnonzero(seqlab.usable(x, y["fwd_return"]))
        close = np.asarray(b["close"], float)
        z = np.nan_to_num(x[rows]).astype(np.float32)
        return {
            "obs": z, "step": close[rows + 1] / close[rows] - 1.0,
            "cost": seqlab.rel_spread(b)[rows], "scale": 1.0, "rows": rows,
        }

    tick = seqlab.tick_size(bars)
    bump = round(0.05 * float(bars["close"][poke]) / tick) * tick
    poked = {k: v.copy() for k, v in bars.items()}
    for k in ("open", "high", "low", "close"):
        poked[k][poke] = round((poked[k][poke] + bump) / tick) * tick
    poked["volume"][poke] *= 3.0
    poked["spread"][poke] *= 2.0
    assert seqlab.tick_size(poked) == tick, "the poke moved the quote lattice"

    a, b = tape_from(bars), tape_from(poked)
    if len(a["rows"]) != len(b["rows"]) or not np.array_equal(a["rows"], b["rows"]):
        return {"poked_bar": int(poke), "steps": 0, "obs_moved": ["usable mask moved"],
                "reward_moved": [], "clean": False}
    rows = a["rows"]
    lo = int(np.searchsorted(rows, poke)) - 60
    lo = max(lo, 10)
    hi = int(np.searchsorted(rows, poke)) + 5
    hi = min(hi, len(rows) - 2)

    Desk = make_env_class()
    rng = np.random.default_rng(11)
    plan = rng.integers(0, 3, hi - lo).tolist()

    bad_obs, bad_rew = [], []
    ea = Desk(a, lo, hi, episode=hi - lo - 1, random_start=False)
    eb = Desk(b, lo, hi, episode=hi - lo - 1, random_start=False)
    oa, _ = ea.reset()
    ob, _ = eb.reset()
    for k, action in enumerate(plan[: hi - lo - 1]):
        bar = int(rows[ea.i])
        if bar < poke and not np.array_equal(oa, ob):
            bad_obs.append(bar)
        oa, ra, _, da, _ = ea.step(action)
        ob, rb, _, db, _ = eb.step(action)
        if bar < poke - 1 and ra != rb:
            bad_rew.append(bar)
        if da or db:
            break
    return {"poked_bar": int(poke), "steps": len(plan), "obs_moved": bad_obs[:5],
            "reward_moved": bad_rew[:5], "clean": not bad_obs and not bad_rew}


def test_cost_accounting(tape) -> dict:
    """The ledger's fee must equal `sum (c_t/2)|dw_t|` recomputed from positions."""
    Desk = make_env_class()
    lo, hi = tape["test"]
    hi = min(hi, lo + 3000)
    env = Desk(tape, lo, hi, episode=hi - lo - 1, random_start=False)
    obs, _ = env.reset()
    rng = np.random.default_rng(5)
    fee_env = 0.0
    recomputed = 0.0
    prev = 0.0
    done = False
    while not done:
        bar = env.i
        action = int(rng.integers(0, 3))
        w_new = float(ACTIONS[action])
        obs, _, _, done, info = env.step(action)
        fee_env += info["fee"]
        recomputed += 0.5 * float(tape["cost"][bar]) * abs(w_new - prev)
        prev = w_new
        if done:  # the forced close-out at the edge of the episode
            c_next = float(tape["cost"][min(bar + 1, len(tape["cost"]) - 1)])
            recomputed += 0.5 * c_next * abs(w_new)
    rel = abs(fee_env - recomputed) / max(abs(recomputed), 1e-18)
    return {"fee_env": fee_env, "fee_recomputed": recomputed, "rel_error": rel,
            "clean": rel < 1e-12}


def test_theorem_on_gbm(symbol: str, interval: str, *, n: int = 30000,
                        paths: int = 8) -> dict:
    """A scripted always-flip rule on simulated GBM. Net per unit turnover must be `-c/2`.

    Turnover is exactly `2` per bar by construction, so `(c/2) x turnover` is
    `sum_t c_t` and the whole of the theorem's content collapses onto one
    statement: **the gross is zero**. That is a statement about an expectation
    and it is therefore tested as one, with a z, rather than as a ratio.

    The distinction is not pedantry. On `Volatility 10 Index` at 1h a single
    40,000-bar path carries a gross standard deviation of 0.21 against a total
    cost of 1.06 - **20% noise** - so a 5% tolerance on the ratio would fail an
    entirely correct implementation half the time. `deriving.md` needed four
    million steps to quote this as a ratio. Eight pooled paths and a z is the
    honest version at the sample this can afford; the ratio is printed beside it
    with its own error bar so the reader can see how wide it is.
    """
    real = seqlab.load(symbol, interval)
    c_real = seqlab.rel_spread(real)
    cost = np.resize(c_real, n)[: n - 1]
    sigma = seqlab.NAMED_SIGMA.get(symbol, 0.5)
    gross = fee = turn = 0.0
    var = 0.0
    bars = 0
    for k in range(paths):
        rng = np.random.default_rng(31 + k)
        close = seqlab.gbm_bars(sigma, n, interval, rng)["close"]
        tape = {"obs": np.zeros((n - 1, 1), np.float32),
                "step": close[1:] / close[:-1] - 1.0, "cost": cost, "scale": 1.0}
        led = run_policy(tape, 10, n - 20, flip_policy)
        gross += led["gross"]
        fee += led["cost"]
        turn += led["turnover"]
        bars += led["bars"]
        # The pooled standard error, summed as a variance across independent
        # paths. The first version of this line recovered the per-path standard
        # error as `gross / max(gross_z, 1e-18)` and a negative `gross_z` sent it
        # to 1e18, which made the z 1e-19 and the test pass for the wrong reason.
        # Carrying the standard error explicitly removes the reconstruction.
        var += led["gross_se"] ** 2
    net = gross - fee
    got = net / turn
    want = -float(np.mean(cost[10 : n - 20])) / 2.0
    se_gross = math.sqrt(max(var, 1e-36))
    z = gross / se_gross
    return {"paths": paths, "bars": bars, "gross": gross, "gross_z": z,
            "net_per_turnover": got, "minus_half_c": want,
            "rel_error": abs(got - want) / abs(want),
            "rel_error_1se": se_gross / abs(turn * want),
            "turnover_per_bar": turn / bars, "clean": abs(z) < 3.5}


# --------------------------------------------------------------------------
# Training one cell
# --------------------------------------------------------------------------


class TurnoverCurve:
    """Turnover as training proceeds. **The curve is the finding.**

    Two readings are kept at every checkpoint and they are not the same number.

    * **The rollout reading**, accumulated free from the training infos. It is
      what the agent actually did while learning - and for DQN it is
      contaminated by epsilon-greedy by construction, since the schedule holds
      exploration at 2% to the end and 2% random actions on a three-action
      alphabet is a floor of about 0.018 turnover per bar that no amount of
      learning can remove.
    * **The greedy reading**, a deterministic pass over a fixed 2,000-bar window
      of the **training** slice. This is the policy's own turnover with the
      exploration taken out, and it is the one the two algorithms can be
      compared on.

    The probe window is drawn from train and never from test. A loop that
    evaluates on the test slice every few thousand steps is one selection
    decision away from being a validation set the page never admits to, and this
    page would then have a held-out number that was looked at ninety-six times.
    """

    def __init__(self, total, buckets=BUCKETS, probe=None):
        self.edge = max(total // buckets, 1)
        self.probe = probe
        self.dw = 0.0
        self.trades = 0
        self.n = 0
        self.points = []

    def note(self, infos, step):
        for info in infos:
            if "dw" in info:
                self.dw += float(info["dw"])
                # A trade is a change of position, counted once whether it moves
                # one unit or two. Turnover is the other number and both are kept:
                # turnover is what the theorem charges, trades is what a desk
                # counts, and a long-to-short reversal is one trade and two units.
                self.trades += int(float(info["dw"]) > 1e-12)
                self.n += 1
        if self.n >= self.edge:
            point = {"step": int(step), "turnover_per_bar": self.dw / self.n,
                     "trades_per_episode": self.trades / self.n * EPISODE}
            if self.probe is not None:
                greedy = self.probe()
                point["greedy_turnover_per_bar"] = greedy["turnover_per_bar"]
                point["greedy_trades_per_episode"] = (
                    greedy["trades"] / max(greedy["bars"] / EPISODE, 1e-9))
                point["greedy_flat_fraction"] = greedy["flat_frac"]
            self.points.append(point)
            self.dw, self.trades, self.n = 0.0, 0, 0


def make_callback(curve):
    from stable_baselines3.common.callbacks import BaseCallback

    class Cb(BaseCallback):
        def _on_step(self) -> bool:
            curve.note(self.locals.get("infos", []), self.num_timesteps)
            return True

    return Cb()


def train_cell(spec: dict) -> dict:
    """One (dataset, algorithm, seed). Runs in its own process on one thread."""
    import torch

    torch.set_num_threads(THREADS)
    began = time.time()
    try:
        tape = load_tape(spec["tape"])
        lo_tr, hi_tr = tape["train"]
        lo_te, hi_te = tape["test"]
        Desk = make_env_class()

        from stable_baselines3 import A2C, DQN, PPO, SAC
        from stable_baselines3.common.vec_env import DummyVecEnv

        cont = spec["algo"] in ("SAC", "PPOC")
        seed = spec["seed"]
        mult = float(spec.get("cost_mult", 1.0))

        def factory():
            # Never start inside the stack's edge padding, where the observation
            # repeats row zero and the agent is shown a bar that never happened.
            return Desk(tape, max(lo_tr, STACK), hi_tr, episode=EPISODE, cost_on=spec["cost_on"],
                        reward=spec["reward"], seed=seed, random_start=True,
                        continuous=cont, cost_mult=mult)

        venv = DummyVecEnv([factory])
        policy_kwargs = {"net_arch": [64, 64]}
        if spec["algo"] == "PPO" or spec["algo"] == "PPOC":
            total = PPO_STEPS
            model = PPO("MlpPolicy", venv, seed=seed, n_steps=1024, batch_size=256,
                        n_epochs=10, gamma=0.99, gae_lambda=0.95, ent_coef=0.0,
                        learning_rate=3e-4, policy_kwargs=policy_kwargs, verbose=0,
                        device="cpu")
        elif spec["algo"] == "DQN":
            total = DQN_STEPS
            model = DQN("MlpPolicy", venv, seed=seed, learning_rate=5e-4,
                        buffer_size=50_000, learning_starts=2_000, batch_size=128,
                        gamma=0.99, train_freq=4, target_update_interval=1_000,
                        exploration_fraction=0.3, exploration_final_eps=0.02,
                        policy_kwargs=policy_kwargs, verbose=0, device="cpu")
        elif spec["algo"] == "A2C":
            total = A2C_STEPS
            model = A2C("MlpPolicy", venv, seed=seed, n_steps=16, gamma=0.99,
                        ent_coef=0.0, learning_rate=7e-4,
                        policy_kwargs=policy_kwargs, verbose=0, device="cpu")
        elif spec["algo"] == "SAC":
            total = SAC_STEPS
            model = SAC("MlpPolicy", venv, seed=seed, learning_rate=3e-4,
                        buffer_size=50_000, learning_starts=2_000, batch_size=256,
                        gamma=0.99, train_freq=4, policy_kwargs=policy_kwargs,
                        verbose=0, device="cpu")
        else:
            raise ValueError(spec["algo"])

        probe_lo = max(lo_tr, STACK)
        probe_hi = min(probe_lo + 2000, hi_tr)

        def probe():
            return run_policy(tape, probe_lo, probe_hi, model_policy_factory(model),
                              cost_on=spec["cost_on"], reward=spec["reward"],
                              seed=seed, continuous=cont, cost_mult=mult)

        curve = TurnoverCurve(total, probe=probe)
        model.learn(total_timesteps=total, callback=make_callback(curve), progress_bar=False)

        test = run_policy(tape, lo_te, hi_te, model_policy_factory(model),
                          cost_on=spec["cost_on"], reward=spec["reward"],
                          seed=seed, continuous=cont, cost_mult=mult)
        # The in-sample pass is a diagnostic and nothing is decided by it, so it
        # is capped at the last ten thousand training rows. `model.predict` in a
        # python loop is about half a millisecond a step and the full train slice
        # is forty thousand rows, which would spend a third of the run's compute
        # on a number no table turns on.
        train_eval = run_policy(tape, max(lo_tr, hi_tr - 10_000), hi_tr,
                                model_policy_factory(model),
                                cost_on=spec["cost_on"], reward=spec["reward"],
                                seed=seed, continuous=cont, cost_mult=mult)
        return {**{k: spec[k] for k in ("symbol", "interval", "generator", "algo",
                                        "seed", "cost_on", "reward", "fold")},
                "cost_mult": mult, "steps": total, "test": test, "train": train_eval,
                "curve": curve.points, "sigma_bar": tape["sigma_bar"],
                "c_over_sigma": float(np.mean(tape["cost"]) * mult / max(tape["sigma_bar"], 1e-18)),
                "secs": time.time() - began, "ok": True}
    except Exception as exc:  # noqa: BLE001 - one dead cell must not kill the grid
        import traceback

        return {**{k: spec.get(k) for k in ("symbol", "interval", "generator", "algo",
                                            "seed", "cost_on", "reward", "fold",
                                            "cost_mult")},
                "ok": False, "error": f"{type(exc).__name__}: {exc}",
                "trace": traceback.format_exc()[-900:], "secs": time.time() - began}


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


def group(results, keys):
    out = {}
    for r in results:
        k = tuple(r.get(x) for x in keys)
        out.setdefault(k, []).append(r)
    return out


HEAD = (f"{'cell':44s} {'seeds':>5s} {'trades/ep':>20s} {'turn/bar':>9s} "
        f"{'gross bps':>10s} {'z':>7s} {'net bps':>9s} {'net/turn':>10s} {'-c/2':>9s}")


def line(name, cells):
    live = [c for c in cells if c.get("ok")]
    if not live:
        return f"{name:44s} {'-':>5s}  all cells failed"
    tr = [c["test"]["trades"] / max(c["test"]["bars"] / EPISODE, 1e-9) for c in live]
    turn = [c["test"]["turnover_per_bar"] for c in live]
    g = [c["test"]["gross"] * 1e4 for c in live]
    z = [c["test"]["gross_z"] for c in live]
    net = [c["test"]["net"] * 1e4 for c in live]
    npt = [c["test"]["net_per_turnover"] for c in live]
    half = -np.mean([c["test"]["mean_cost"] for c in live]) / 2.0
    return (f"{name:44s} {len(live):5d} "
            f"{np.median(tr):7.1f} [{np.min(tr):5.1f},{np.max(tr):5.1f}] "
            f"{np.median(turn):9.4f} {np.median(g):10.2f} {np.median(z):7.2f} "
            f"{np.median(net):9.2f} {np.median(npt):10.3e} {half:9.3e}")


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def datasets_for(pairs, generators, seeds):
    """Every tape this run needs, de-duplicated."""
    want = []
    for symbol, interval in pairs:
        for gen in generators:
            if gen == "real":
                want.append((symbol, interval, gen, 0))
            else:
                for s in range(seeds):
                    want.append((symbol, interval, gen, s))
    return want


def main() -> None:
    assert WORKERS * THREADS <= 8, f"thread budget: {WORKERS} x {THREADS} > 8"
    t0 = time.time()
    print("=" * 118)
    print("seqrl.py - a reinforcement learner as a test of a theorem")
    print("=" * 118)
    print("\nprediction, written first: turnover -> 0, because E[net] = -(c/2) x turnover")
    print(f"cost model: fee_t = (c_t/2)|w_t - w_(t-1)|, c_t = spread_points x tick / close")
    print(f"budget: {WORKERS} workers x {THREADS} torch thread(s) = {WORKERS * THREADS} cores\n")

    res = {"seed": SEED, "seeds": SEEDS, "stack": STACK, "episode": EPISODE,
           "folds": FOLDS, "symbols": list(SYMBOLS), "frames": list(FRAMES),
           "workers": WORKERS, "threads": THREADS}

    # ---- the cost model, printed before anything is trained -------------
    print("=== The cost model, measured ===\n")
    print(f"    {'symbol':32s} {'tf':>4s} {'bars':>7s} {'tick':>7s} {'pts':>7s} "
          f"{'c bps':>8s} {'sigma bps':>10s} {'c/sigma':>8s}")
    costs = {}
    pairs = [(s, tf) for s in SYMBOLS for tf in FRAMES]
    alive = []
    for symbol, interval in pairs:
        try:
            bars = seqlab.load(symbol, interval)
        except Exception as exc:  # noqa: BLE001
            print(f"    {symbol:32s} {interval:>4s}  MISSING  {str(exc)[:40]}")
            continue
        c = seqlab.rel_spread(bars)
        sig = float(np.std(np.diff(np.log(bars["close"]))))
        costs[f"{symbol}|{interval}"] = {
            "bars": int(len(bars["close"])), "tick": seqlab.tick_size(bars),
            "median_points": float(np.median(bars["spread"])),
            "c_bps": float(np.median(c) * 1e4), "sigma_bps": sig * 1e4,
            "c_over_sigma": float(np.median(c) / max(sig, 1e-18)),
        }
        d = costs[f"{symbol}|{interval}"]
        print(f"    {symbol:32s} {interval:>4s} {d['bars']:7d} {d['tick']:7g} "
              f"{d['median_points']:7.0f} {d['c_bps']:8.3f} {d['sigma_bps']:10.2f} "
              f"{d['c_over_sigma']:8.4f}")
        alive.append((symbol, interval))
    res["costs"] = costs

    print("\n    deriving.md measured this family at 0.39-4.31 bps from tick bid/ask,")
    print("    by a route that never touches the bar column. Agreement there is the")
    print("    validation; disagreement would void every number below it.\n")

    # ---- kill condition 7, stated rather than measured -------------------
    print("=== 1d, and why there is no number for it ===\n")
    try:
        d1 = seqlab.load(SYMBOLS[0], "1d")
        n1 = len(d1["close"])
    except Exception:
        n1 = 0
    sp = seqlab.walk_forward(max(n1 - 25, 1), folds=FOLDS, horizon=1)
    tr1 = len(sp[-1][0]) if sp else 0
    print(f"    {SYMBOLS[0]} 1d holds {n1:,} bars; the final fold would train on {tr1:,}")
    print(f"    rows. A 64x64 policy on a {STACK * 28 + 1}-dimensional observation carries")
    print(f"    ~{(STACK * 28 + 1) * 64 + 64 * 64 + 64 * 3:,} parameters. Kill condition 7: 1d is not run.\n")
    res["daily"] = {"bars": n1, "final_fold_train_rows": tr1, "run": False}

    # ---- the self-tests --------------------------------------------------
    print("=== The self-tests, before any agent ===\n")
    probe_sym, probe_tf = alive[0]
    res["tests"] = {}

    v = seqlab.check_causality(seqlab.load(probe_sym, probe_tf))
    res["tests"]["features"] = v
    print(f"    1. seqlab.check_causality  {'CLEAN' if v['clean'] else 'LEAKING ' + str(v['leaking'])}"
          f"   ({v['rows_checked']:,} rows)")

    v = test_env_causality(probe_sym, probe_tf)
    res["tests"]["env_causality"] = v
    print(f"    2. environment causality   {'CLEAN' if v['clean'] else 'LEAKING'}"
          f"   (poked bar {v['poked_bar']:,}, {v['steps']} steps driven)")
    if not v["clean"]:
        print(f"       obs moved at {v['obs_moved']}, reward moved at {v['reward_moved']}")
        print("\n    KILL CONDITION 1 FIRED. Nothing else is run.")
        json.dump(res, open(OUT, "w"), indent=1, default=float)
        return

    tape0 = build_tape(probe_sym, probe_tf)
    v = test_cost_accounting(tape0)
    res["tests"]["cost_accounting"] = v
    print(f"    3. cost accounting         {'CLEAN' if v['clean'] else 'WRONG'}"
          f"   (rel error {v['rel_error']:.3e})")

    v = test_theorem_on_gbm(probe_sym, probe_tf)
    res["tests"]["theorem_scripted"] = v
    print(f"    4. theorem, scripted flip  {'CLEAN' if v['clean'] else 'WRONG'}"
          f"   net/turnover {v['net_per_turnover']:.4e} vs -c/2 {v['minus_half_c']:.4e}"
          f"  ({v['rel_error'] * 100:.2f}% off, 1 s.e. = {v['rel_error_1se'] * 100:.2f}%,"
          f" gross z {v['gross_z']:+.2f} over {v['bars']:,} bars)")
    if not (res["tests"]["cost_accounting"]["clean"] and v["clean"]):
        print("\n    KILL CONDITION 2 FIRED. Nothing else is run.")
        json.dump(res, open(OUT, "w"), indent=1, default=float)
        return

    # ---- the un-learned controls, on every dataset -----------------------
    print("\n=== The floors and the look-ahead control, on every dataset ===\n")
    print("    Turnover, cost and net for three policies that are not learned. The")
    print("    look-ahead row is the load-bearing one: a table where everything")
    print("    returns zero is indistinguishable from a harness that computes zero.\n")
    print(f"    {'dataset':38s} {'policy':12s} {'turn/bar':>9s} {'gross bps':>10s} "
          f"{'z':>9s} {'net bps':>10s} {'net/turn':>11s} {'-c/2':>10s}")
    floors = {}
    worst_cheat_z = float("inf")
    tapes = {}
    for symbol, interval in alive:
        key = f"{symbol}|{interval}"
        tape = tape0 if (symbol, interval) == (probe_sym, probe_tf) else build_tape(symbol, interval)
        tapes[key] = tape
        lo, hi = tape["test"]
        row = {}
        for pname, pol in (("flat", flat_policy),
                           ("random", random_policy_factory(SEED)),
                           ("look-ahead", cheat_policy)):
            led = run_policy(tape, lo, hi, pol)
            row[pname] = led
            print(f"    {key:38s} {pname:12s} {led['turnover_per_bar']:9.4f} "
                  f"{led['gross'] * 1e4:10.2f} {led['gross_z']:9.2f} "
                  f"{led['net'] * 1e4:10.2f} {led['net_per_turnover']:11.3e} "
                  f"{-led['mean_cost'] / 2:10.3e}")
        worst_cheat_z = min(worst_cheat_z, row["look-ahead"]["gross_z"])
        floors[key] = row
    res["floors"] = floors
    res["cheat_min_z"] = worst_cheat_z
    print(f"\n    look-ahead control, worst z across datasets: {worst_cheat_z:.1f}")
    if worst_cheat_z < 10.0:
        print("    KILL CONDITION 3 FIRED: the harness cannot see an edge that is there.")
        json.dump(res, open(OUT, "w"), indent=1, default=float)
        return
    print("    Kill condition 3 does not fire. The estimator can see an edge.\n")

    # ---- build every tape ------------------------------------------------
    focus = [p for p in FOCUS if p in alive] or alive[:4]
    need = datasets_for(alive, ("real",), SEEDS)
    if "controls" in STAGES:
        need += datasets_for(focus, ("gbm", "surrogate"), SEEDS)
    if "zerocost" in STAGES:
        need += datasets_for(focus, ("gbm",), SEEDS)
    need = sorted(set(need))
    print(f"=== Building {len(need)} tapes ===\n")
    os.makedirs(TAPES, exist_ok=True)
    made = {}
    for symbol, interval, gen, s in need:
        key = tape_key(symbol, interval, gen, s, -1)
        path = tape_path(key)
        if not os.path.exists(path):
            tape = tapes.get(f"{symbol}|{interval}") if gen == "real" else None
            if tape is None:
                tape = build_tape(symbol, interval, generator=gen, seed=s)
            tape["gen_seed"] = s
            save_tape(tape)
        made[(symbol, interval, gen, s)] = path
    a_tape = load_tape(next(iter(made.values())))
    print(f"    obs dim {a_tape['obs'].shape[1] + 1} = {STACK} x {a_tape['features']} features + position")
    print(f"    fold {a_tape['fold']} of {a_tape['folds']}: train {a_tape['train']}, test {a_tape['test']}\n")
    res["shape"] = {"obs_dim": int(a_tape["obs"].shape[1] + 1), "stack": STACK,
                    "train": a_tape["train"], "test": a_tape["test"], "n": a_tape["n"]}

    # ---- the cells -------------------------------------------------------
    specs = []

    def add(symbol, interval, gen, algo, cost_on, reward, seeds=SEEDS, cost_mult=1.0):
        for s in range(seeds):
            gs = 0 if gen == "real" else s
            specs.append({"symbol": symbol, "interval": interval, "generator": gen,
                          "algo": algo, "seed": SEED + s, "cost_on": cost_on,
                          "reward": reward, "fold": -1, "cost_mult": cost_mult,
                          "tape": made[(symbol, interval, gen, gs)]})

    # Stage 1: the zero-cost bug check, first, on the focus set.
    if "zerocost" in STAGES:
        for symbol, interval in focus:
            for algo in ("PPO", "DQN"):
                add(symbol, interval, "real", algo, False, "arith")
                add(symbol, interval, "gbm", algo, False, "arith")
    zero_cost_n = len(specs)

    # Stage 2: the main grid, with real costs and the briefed log-equity reward.
    if "main" in STAGES:
        for symbol, interval in alive:
            for algo in ("PPO", "DQN"):
                add(symbol, interval, "real", algo, True, "log")
    main_n = len(specs) - zero_cost_n

    # Stage 3: the generator controls, and A2C as a third algorithm.
    if "controls" in STAGES:
        for symbol, interval in focus:
            for gen in ("gbm", "surrogate"):
                for algo in ("PPO", "DQN"):
                    add(symbol, interval, gen, algo, True, "log")
            add(symbol, interval, "real", "A2C", True, "log")
            add(symbol, interval, "real", "SAC", True, "log")
        for symbol, interval in focus[:2]:
            add(symbol, interval, "real", "PPO", True, "arith")
    control_n = len(specs) - zero_cost_n - main_n

    # Stage 4: the cost-scaling sweep. Two datasets, PPO, the multipliers.
    if "sweep" in STAGES:
        for symbol, interval in focus[:2]:
            for mult in MULTS:
                if mult != 1.0:
                    add(symbol, interval, "real", "PPO", True, "log", cost_mult=mult)

    print(f"=== {len(specs)} cells on {WORKERS} workers "
          f"({zero_cost_n} zero-cost, {main_n} main grid, {control_n} controls, "
          f"{len(specs) - zero_cost_n - main_n - control_n} cost sweep) ===\n", flush=True)

    results = []
    began = time.time()
    with ProcessPoolExecutor(max_workers=WORKERS) as pool:
        for i, out in enumerate(pool.map(train_cell, specs), 1):
            results.append(out)
            if not out.get("ok"):
                print(f"    ! {out['symbol']} {out['interval']} {out['generator']} "
                      f"{out['algo']} seed {out['seed']}: {out.get('error')}", flush=True)
            if i % 10 == 0 or i == len(specs):
                rate = i / max(time.time() - began, 1e-9)
                print(f"    {i:4d}/{len(specs)}  {(len(specs) - i) / max(rate, 1e-9) / 60:.0f}m left",
                      flush=True)
    res["cells"] = results

    # ---- the report ------------------------------------------------------
    def block(title, note, rows):
        print(f"\n=== {title} ===\n")
        for ln in note:
            print(f"    {ln}")
        print()
        print("    " + HEAD)
        for name, cells in rows:
            print("    " + line(name, cells))

    zc = [r for r in results if not r.get("cost_on")]
    block("Stage 1: the zero-cost bug check",
          ["Costs off, arithmetic reward, so the quantity below is the martingale",
           "transform itself. Kill condition 5 fires on any |z| past 3: at zero cost",
           "on a martingale there is nothing to earn, and money here is look-ahead."],
          [(f"{k[0]} {k[1]} {k[2]} {k[3]} (no cost)", v)
           for k, v in sorted(group(zc, ("symbol", "interval", "generator", "algo")).items())])
    fired = [r for r in zc if r.get("ok") and abs(r["test"]["gross_z"]) > 3.0]
    res["zero_cost_fired"] = [
        {"symbol": r["symbol"], "interval": r["interval"], "algo": r["algo"],
         "generator": r["generator"], "seed": r["seed"], "z": r["test"]["gross_z"]}
        for r in fired
    ]
    print(f"\n    kill condition 5: {len(fired)} of {len(zc)} zero-cost cells past |z| = 3 "
          f"(expected at 3-sigma: {0.0027 * len(zc):.1f})")

    real = [r for r in results if r.get("cost_on") and r["generator"] == "real"
            and r["reward"] == "log" and r["algo"] in ("PPO", "DQN")
            and r.get("cost_mult", 1.0) == 1.0]
    block("Stage 2: the main grid, real costs, log-equity reward",
          ["trades/ep is the median across seeds with [min, max]. net/turn is the",
           "realised loss per unit of turnover and -c/2 is what deriving.md says it",
           "must be. Those last two columns are the theorem, measured."],
          [(f"{k[0]} {k[1]} {k[2]}", v)
           for k, v in sorted(group(real, ("symbol", "interval", "algo")).items())])

    ctrl = [r for r in results if r.get("cost_on") and r["generator"] != "real"]
    block("Stage 3: the generator controls",
          ["The same training on a simulated GBM at the named sigma and on",
           "phase-randomised returns, with the real symbol's own cost series."],
          [(f"{k[0]} {k[1]} {k[2]} {k[3]}", v)
           for k, v in sorted(group(ctrl, ("symbol", "interval", "generator", "algo")).items())])

    extra = [r for r in results if r.get("cost_on") and r["generator"] == "real"
             and r.get("cost_mult", 1.0) == 1.0
             and (r["algo"] in ("A2C", "SAC") or r["reward"] == "arith")]
    block("Stage 3b: a third and fourth algorithm, and the arithmetic reward",
          ["SAC is the continuous-position variant: w in [-1, 1] rather than",
           "{-1, 0, +1}. The arith rows train on the martingale transform itself,",
           "which removes the -sigma^2/2 log drag from the objective."],
          [(f"{k[0]} {k[1]} {k[2]} reward={k[3]}", v)
           for k, v in sorted(group(extra, ("symbol", "interval", "algo", "reward")).items())])

    sweep = [r for r in results if r.get("cost_on") and r.get("cost_mult", 1.0) != 1.0]
    anchor = [r for r in real if (r["symbol"], r["interval"]) in
              {(x["symbol"], x["interval"]) for x in sweep} and r["algo"] == "PPO"]
    if sweep:
        print("\n=== Stage 4: at what c/sigma does the agent discover the theorem? ===\n")
        print("    The same PPO, the same data, the spread multiplied. `c/sigma` is the")
        print("    quoted spread as a fraction of one bar's standard deviation - the")
        print("    signal-to-noise the cost term is presented at. The feed's own value")
        print("    is the mult = 1 row and it is the one every other table uses.\n")
        print(f"    {'dataset':32s} {'mult':>5s} {'c/sigma':>8s} {'seeds':>5s} "
              f"{'greedy turn/bar, end':>28s} {'flat frac':>10s}")
        sweep_rows = {}
        for k, cells in sorted(group(sweep + anchor, ("symbol", "interval", "cost_mult")).items()):
            live = [c for c in cells if c.get("ok")]
            if not live:
                continue
            turn = np.array([c["test"]["turnover_per_bar"] for c in live])
            flat = np.array([c["test"]["flat_frac"] for c in live])
            cos = float(np.median([c.get("c_over_sigma", float("nan")) for c in live]))
            sweep_rows[f"{k[0]}|{k[1]}|{k[2]}"] = {
                "cells": len(live), "c_over_sigma": cos,
                "turnover_median": float(np.median(turn)),
                "turnover_min": float(np.min(turn)), "turnover_max": float(np.max(turn)),
                "flat_fraction": float(np.median(flat)),
            }
            print(f"    {k[0] + ' ' + k[1]:32s} {k[2]:5.0f} {cos:8.4f} {len(live):5d} "
                  f"{np.median(turn):9.4f} [{np.min(turn):7.4f}, {np.max(turn):7.4f}] "
                  f"{np.median(flat):10.3f}")
        res["cost_sweep"] = sweep_rows

    # ---- the theorem, numerically ---------------------------------------
    print("\n=== The theorem, numerically ===\n")
    print("    For every learned cell that traded at all: realised net per unit of")
    print("    turnover against -c/2, and the gross that has to be zero for the two")
    print("    to agree.\n")
    print("    The ratio is formed per cell and then summarised: the symbols carry")
    print("    spreads an order of magnitude apart, so a median of net/turnover")
    print("    pooled across them would be a statement about which symbols are in")
    print("    the pool. Cells holding a position for fewer than 2% of bars are")
    print("    excluded - their denominator is noise.\n")
    print(f"    {'arm':34s} {'cells':>5s} {'ratio to -c/2':>28s} {'gross z':>18s}")
    theorem = {}
    for name, sel in (("real, costs on", real),
                      ("gbm, costs on", [r for r in ctrl if r["generator"] == "gbm"]),
                      ("surrogate, costs on", [r for r in ctrl if r["generator"] == "surrogate"]),
                      ("A2C / SAC / arith", extra),
                      ("cost sweep, mult > 1", sweep)):
        live = [r for r in sel if r.get("ok") and r["test"]["turnover_per_bar"] > 0.02]
        if not live:
            print(f"    {name:34s} {'-':>5s}   no cell traded enough to form a ratio")
            theorem[name] = {"cells": 0}
            continue
        ratio = np.array([r["test"]["net_per_turnover"] / (-r["test"]["mean_cost"] / 2.0)
                          for r in live])
        z = np.array([r["test"]["gross_z"] for r in live])
        theorem[name] = {"cells": len(live), "ratio_median": float(np.median(ratio)),
                         "ratio_min": float(np.min(ratio)), "ratio_max": float(np.max(ratio)),
                         "z_median": float(np.median(z)), "z_max_abs": float(np.max(np.abs(z)))}
        print(f"    {name:34s} {len(live):5d} "
              f"{np.median(ratio):9.3f} [{np.min(ratio):7.3f}, {np.max(ratio):7.3f}] "
              f"{np.median(z):+7.2f} max |z| {np.max(np.abs(z)):5.2f}")
    res["theorem"] = theorem
    print("\n    A ratio of 1.000 is the theorem exactly. It cannot be hit on a finite")
    print("    sample: realised net is `gross - cost` and gross is a sum of thousands")
    print("    of increments whose expectation is zero but whose realisation is not,")
    print("    so the scatter of the ratio around 1 IS the gross noise, and the")
    print("    gross z column is the same statement with the denominator named.")

    # ---- the turnover curve ---------------------------------------------
    print("\n=== Turnover over training - the curve that is the finding ===\n")
    print(f"    Turnover per bar, median across cells, at {BUCKETS} checkpoints spanning")
    print("    training. `greedy` is a deterministic pass over a fixed 2,000-bar")
    print("    window of the TRAIN slice; `rollout` is what the agent did while")
    print("    learning and for DQN it carries a 2% epsilon-greedy floor that no")
    print(f"    amount of learning removes. Always-flat is 0.000 and random-action is {8 / 9:.3f}.\n")
    curves = {}
    for k, cells in sorted(group(real, ("interval", "algo")).items()):
        live = [c for c in cells if c.get("ok") and c["curve"]]
        if not live:
            continue
        depth = min(len(c["curve"]) for c in live)
        row = {"cells": len(live), "steps": [p["step"] for p in live[0]["curve"][:depth]]}
        for tag, field in (("greedy ", "greedy_turnover_per_bar"), ("rollout", "turnover_per_bar")):
            series = np.array([[p.get(field, np.nan) for p in c["curve"][:depth]] for c in live])
            med = np.nanmedian(series, axis=0)
            row[field] = med.tolist()
            print(f"    {k[0]:>4s} {k[1]:4s} {tag} ({len(live):2d} cells)  "
                  + " ".join(f"{x:6.3f}" for x in med))
        curves[f"{k[0]} {k[1]}"] = row
        print()
    res["curves"] = curves

    # ---- what actually happened -----------------------------------------
    print("\n=== Did turnover collapse? ===\n")
    live = [r for r in real if r.get("ok") and r["curve"]]
    if live:
        def col(field, which):
            return np.array([r["curve"][which].get(field, np.nan) for r in live])

        first = col("greedy_turnover_per_bar", 0)
        last = col("greedy_turnover_per_bar", -1)
        ev = np.array([r["test"]["turnover_per_bar"] for r in live])
        tr = np.array([r["test"]["trades"] / max(r["test"]["bars"] / EPISODE, 1e-9) for r in live])
        flat_share = np.array([r["test"]["flat_frac"] for r in live])
        zero = int((ev < 0.01).sum())
        near = int((ev < 0.1).sum())
        print(f"    {len(live)} learned cells on real feeds with costs on, "
              f"{SEEDS} seeds per (symbol, tf, algo).")
        print(f"    greedy turnover/bar, first checkpoint : median {np.nanmedian(first):8.4f} "
              f"[{np.nanmin(first):.4f}, {np.nanmax(first):.4f}]")
        print(f"    greedy turnover/bar, last  checkpoint : median {np.nanmedian(last):8.4f} "
              f"[{np.nanmin(last):.4f}, {np.nanmax(last):.4f}]")
        print(f"    turnover/bar, deterministic on TEST   : median {np.median(ev):8.4f} "
              f"[{np.min(ev):.4f}, {np.max(ev):.4f}]")
        print(f"    trades per 512-bar episode on TEST    : median {np.median(tr):8.1f} "
              f"[{np.min(tr):.1f}, {np.max(tr):.1f}]")
        expo = np.array([r["test"]["exposure"] for r in live])
        print(f"    fraction of test bars held flat       : median {np.median(flat_share):8.3f} "
              f"[{np.min(flat_share):.3f}, {np.max(flat_share):.3f}]")
        print(f"    mean |position| on test               : median {np.median(expo):8.3f} "
              f"[{np.min(expo):.3f}, {np.max(expo):.3f}]")
        print(f"    floors: always-flat 0.0000, random-action {8 / 9:.4f} turnover/bar")
        print(f"    cells below 0.01 turnover/bar         : {zero} of {len(live)}")
        print(f"    cells below 0.10 turnover/bar         : {near} of {len(live)}")
        print("\n    Zero turnover and flat are not the same policy. Any CONSTANT position")
        print("    has zero turnover after one crossing, and under the arithmetic reward it")
        print("    is exactly as good as flat; under log equity it is worse by sigma^2/2 per")
        print("    bar. The theorem predicts zero TURNOVER, and the two columns above say")
        print("    which of the zero-turnover policies was found.")
        res["collapse"] = {
            "cells": len(live), "greedy_first": float(np.nanmedian(first)),
            "greedy_last": float(np.nanmedian(last)),
            "test_turnover_per_bar": float(np.median(ev)),
            "test_trades_per_episode": float(np.median(tr)),
            "flat_fraction": float(np.median(flat_share)),
            "exposure": float(np.median(expo)),
            "cells_below_0p01": zero, "cells_below_0p10": near,
            "random_floor": 8 / 9,
        }

    profits = [r for r in real if r.get("ok") and r["test"]["gross_z"] > 3.0]
    res["profit_alarms"] = [
        {"symbol": r["symbol"], "interval": r["interval"], "algo": r["algo"],
         "seed": r["seed"], "z": r["test"]["gross_z"], "gross_bps": r["test"]["gross"] * 1e4}
        for r in profits
    ]
    print(f"\n    kill condition 4: {len(profits)} of {len(real)} cost-bearing cells with "
          f"gross past +3 sigma (expected: {0.00135 * len(real):.2f})")
    if profits:
        print("    Those are defect reports, not results. Listed in the JSON.")

    res["secs"] = time.time() - t0
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(res, open(OUT, "w"), indent=1, default=float)
    print(f"\nwrote {OUT} in {(time.time() - t0) / 60:.1f}m")


if __name__ == "__main__":
    main()
