#!/usr/bin/env python3
"""Prepare turn-based datasets for sequence experiments.

This script synthesises a small dataset if no live market data is available.
It writes per-instrument .npz files under .data/research/sequence_baseline/.

Each file contains:
- X: (T, F) feature matrix per turn
- y_hold: (T,) binary label whether the level held (1) or not (0)
- y_push: (T,) continuous expected_push (float)
- meta: dict with instrument name and timestamps

The features are simple engineered ones to act as a baseline.
"""
import os
import numpy as np
import time
from pathlib import Path

OUT = Path('.data/research/sequence_baseline')
OUT.mkdir(parents=True, exist_ok=True)

INSTRUMENTS = [
    ('gold', 'XAUUSD'),
    ('btc', 'BTCUSD'),
    ('v75', 'Volatility 75 Index'),
    ('v100', 'Volatility 100 Index'),
]

# Settings for synthetic generation
SEED = 42
N_TURNS = 2000
np.random.seed(SEED)


def synth_instrument(seed: int, n: int = N_TURNS):
    rng = np.random.RandomState(seed)
    # price random walk
    returns = rng.normal(loc=0.0, scale=0.001, size=n)
    price = 1000.0 + np.cumsum(returns)
    # local volatility estimate
    vol = np.abs(rng.normal(loc=0.5, scale=0.2, size=n)) + 0.1
    # turn strength (proxy)
    strength = rng.random(n)
    # push (what a level expects), synthetic as positive right-skew
    push = np.abs(rng.normal(loc=1.0, scale=0.8, size=n))
    # whether level held: correlated with strength and low vol
    hold_prob = 0.2 + 0.6 * strength - 0.3 * (vol - vol.mean()) / (vol.std() + 1e-9)
    hold = (rng.rand(n) < np.clip(hold_prob, 0.02, 0.98)).astype(float)

    # features per turn: price, ret, vol, strength, recent mean ret, recent vol
    window = 5
    recent_ret = np.convolve(returns, np.ones(window) / window, mode='same')
    recent_vol = np.convolve(np.abs(returns), np.ones(window) / window, mode='same')

    X = np.vstack([price, returns, vol, strength, recent_ret, recent_vol]).T
    return X.astype(np.float32), hold.astype(np.float32), push.astype(np.float32)


def main():
    for i, (slug, name) in enumerate(INSTRUMENTS):
        X, y_hold, y_push = synth_instrument(SEED + i, n=N_TURNS)
        out = OUT / f'{slug}.npz'
        np.savez_compressed(out, X=X, y_hold=y_hold, y_push=y_push, meta={'slug': slug, 'name': name, 'n': len(y_hold), 'seed': SEED + i, 'created': time.time()})
        print(f'Wrote {out} with {len(y_hold)} turns')


if __name__ == '__main__':
    main()
