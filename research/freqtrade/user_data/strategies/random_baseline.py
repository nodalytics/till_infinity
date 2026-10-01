"""The null every crypto idea here must beat: random entries, random side, same exits.

Seeded per pair and candle, so a run is reproducible. A strategy that does not beat this on the
same pairs, period, fees and funding has no edge (research/docs/triage.md's standard).
"""
from __future__ import annotations

import zlib

import numpy as np
from pandas import DataFrame

from freqtrade.strategy import IStrategy


class RandomBaseline(IStrategy):
    INTERFACE_VERSION = 3
    can_short = True
    timeframe = "15m"
    minimal_roi = {"0": 100}  # exits by stop or time only
    stoploss = -0.02
    rate = 0.02  # share of candles that enter
    hold = 16  # candles

    def populate_indicators(self, df: DataFrame, metadata: dict) -> DataFrame:
        seed = zlib.crc32(metadata["pair"].encode())  # hash() is salted per process
        rng = np.random.default_rng(seed)
        df["draw"] = rng.random(len(df))
        df["side"] = rng.random(len(df)) < 0.5
        return df

    def populate_entry_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        go = df["draw"] < self.rate
        df.loc[go & df["side"], "enter_long"] = 1
        df.loc[go & ~df["side"], "enter_short"] = 1
        return df

    def populate_exit_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        return df

    def custom_exit(self, pair, trade, current_time, current_rate, current_profit, **kwargs):
        if (current_time - trade.open_date_utc).total_seconds() >= self.hold * 15 * 60:
            return "time"
        return None
