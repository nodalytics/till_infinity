"""What a run earned, in R and in money, with the desk's checks: both halves and a day bootstrap."""

from __future__ import annotations

import numpy as np
import pandas as pd


def day_bootstrap(trades: pd.DataFrame, col: str = "R", draws: int = 2000, seed: int = 11):
    """95% CI of the mean, resampling whole days so same-day trades stay together."""
    if trades.empty:
        return (np.nan, np.nan)
    day = trades["entry_time"].dt.floor("D")
    groups = [g[col].to_numpy() for _, g in trades.groupby(day)]
    rng = np.random.default_rng(seed)
    means = []
    for _ in range(draws):
        pick = rng.integers(0, len(groups), len(groups))
        x = np.concatenate([groups[k] for k in pick])
        means.append(x.mean())
    return tuple(np.percentile(means, [2.5, 97.5]))


def max_drawdown(trades: pd.DataFrame, start: float) -> float:
    if trades.empty:
        return 0.0
    eq = start + trades.sort_values("exit_ts")["net"].cumsum().to_numpy()
    eq = np.r_[start, eq]
    peak = np.maximum.accumulate(eq)
    return float(((eq - peak) / peak).min())


def summary(trades: pd.DataFrame, refused: pd.DataFrame | None = None, start: float = 10_000.0,
            null: pd.DataFrame | None = None) -> dict:
    if trades.empty:
        return dict(trades=0, refused=0 if refused is None else len(refused))
    t = trades.sort_values("entry_ts")
    half = len(t) // 2
    first, second = t.iloc[:half], t.iloc[half:]
    lo, hi = day_bootstrap(t)
    risk = t["risk_money"]
    out = dict(
        trades=len(t),
        refused=0 if refused is None else len(refused),
        refused_why=({} if refused is None or refused.empty
                     else refused["why"].value_counts().head(5).to_dict()),
        span=f"{t['entry_time'].min():%Y-%m-%d} .. {t['exit_time'].max():%Y-%m-%d}",
        mean_R=t["R"].mean(),
        ci95_R=(lo, hi),
        first_half_R=first["R"].mean(),
        second_half_R=second["R"].mean(),
        hit=(t["net"] > 0).mean(),
        gross_R=(t["gross"] / risk).mean(),
        spread_R=(t["spread_cost"] / risk).mean(),
        swap_R=(t["swap_cost"] / risk).mean(),
        commission_R=(t["commission"] / risk).mean(),
        net_money=t["net"].sum(),
        max_drawdown=max_drawdown(t, start),
        exits=t["reason"].value_counts().to_dict(),
        fills=t["fill"].value_counts().to_dict() if "fill" in t else {},
    )
    if null is not None and len(null):
        m = null["mean_R"].dropna()
        out["null_mean_R"] = m.mean()
        out["beats_null_share"] = float((out["mean_R"] > m).mean())
    return out


def show(s: dict) -> str:
    lines = []
    for k, v in s.items():
        if isinstance(v, float):
            v = f"{v:+.4f}" if k.endswith("R") or k in ("max_drawdown",) else f"{v:.4f}"
        elif isinstance(v, tuple):
            v = "[" + ", ".join(f"{x:+.4f}" for x in v) + "]"
        lines.append(f"  {k:18s} {v}")
    return "\n".join(lines)
