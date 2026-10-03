"""The default grammar is the desk's qualified zone: on generated walks, every origin that
`research/ideas/zone_events.py` records (those that broke structure and were returned to) is a
MCFL ZONE exactly when zone_events calls it V = 1."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ideas"))
import prims as P
import zone_events as ze
from mcfl import synth
from mcfl.parse import parse


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_same_qualified_zones(seed):
    for gen in (synth.walk, synth.garch):
        df = gen(2500, seed=seed)
        dft = df.assign(ts=np.arange(len(df)) * 3600)
        a = P.atr(dft, 14)
        ch = parse(df)
        ours = {(z.at, z.dir.value) for z in ch.of("ZONE")}
        n = 0
        for side, frame in ((1, dft), (-1, ze.flip(dft))):
            d = "UP" if side > 0 else "DOWN"
            for p, V in {r["p"]: r["V"] for r in ze.events(frame, a, side, 0.0, None, None, 3600)}.items():
                assert ((p, d) in ours) == V, (gen.__name__, d, p, V)
                n += 1
        assert n > 100
