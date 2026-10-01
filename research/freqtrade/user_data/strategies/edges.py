"""Three pre-registered crypto perpetual strategies (research/docs/ideas.md), each with its null.

Pre-registered 2026-10-01, before any run. Bybit linear perps, 12 pairs, 15m, 2024-01 to 2026-10,
taker fee 0.055% a side, funding charged by freqtrade at each stamp. No take-profit anywhere.

  FundingFade    (D3 / C2) after a funding stamp whose rate is in the top or bottom 5% of its own
                 last 270 stamps (90 days), take the side that receives funding: short when longs
                 pay, long when shorts pay. Stop 3 ATR(14) from entry, exit after 96 bars (24h).
  CoilBreakout   (B1, close-confirmed: freqtrade cannot rest stop orders in a backtest) the 14-bar
                 smoothed true range at or below the 20th percentile of its last 1,500 bars on the
                 previous bar, and this bar closes beyond the previous 16-bar box: enter that way.
                 Stop at the opposite box edge, trailed 2 sigma behind the best price; 96 bars at most.
  FundingStamp   (D10) one hour before each 8-hourly stamp, if the *previous* stamp's rate was in the
                 top or bottom 5%, take the side that receives funding; exit one hour after the stamp.
                 (The coming stamp's own rate is not known in the data until it prints.)

Nulls (`...Coin`): the same bars, the same exits, the side by a seeded coin. A strategy has an edge
only if it beats its own coin, in both halves (2024, and 2025 on).
"""
from __future__ import annotations

import zlib
from datetime import timedelta

import numpy as np
import pandas as pd
from pandas import DataFrame

from freqtrade.strategy import IStrategy, stoploss_from_absolute

BAR = timedelta(minutes=15)


def coin(df: DataFrame, pair: str) -> np.ndarray:
    """A seeded coin per bar, fixed by pair and bar time, so cutting history changes nothing."""
    seed = zlib.crc32(pair.encode())
    t = (df["date"].astype("int64") // 10**9).to_numpy()
    return ((t * 2654435761 + seed) % 2**32) % 2 == 0


def atr(df: DataFrame, n: int = 14) -> pd.Series:
    prev = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(), (df["low"] - prev).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


class _Base(IStrategy):
    INTERFACE_VERSION = 3
    can_short = True
    timeframe = "15m"
    minimal_roi = {"0": 100}
    stoploss = -0.99
    use_custom_stoploss = True
    startup_candle_count = 1600
    hold = 96
    process_only_new_candles = True

    def _row(self, pair: str, trade) -> pd.Series | None:
        """The signal candle: the last one closed before the trade opened, looked up once a trade."""
        cache = self.__dict__.setdefault("_rows", {})
        key = (pair, trade.open_date_utc)
        if key not in cache:
            df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            at = df["date"].searchsorted(trade.open_date_utc - BAR, side="right") - 1
            cache[key] = None if at < 0 else df.iloc[at]
        return cache[key]

    def custom_exit(self, pair, trade, current_time, current_rate, current_profit, **kwargs):
        if current_time - trade.open_date_utc >= self.hold * BAR:
            return "time"
        return None

    def populate_exit_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        return df


# ---------------------------------------------------------------------------------- FundingFade


class FundingFade(_Base):
    coin_side = False

    def informative_pairs(self):
        return [(p, "1h", "funding_rate") for p in self.dp.current_whitelist()]

    def populate_indicators(self, df: DataFrame, metadata: dict) -> DataFrame:
        fr = self.dp.get_pair_dataframe(metadata["pair"], "1h", candle_type="funding_rate")
        fr = fr[["date", "open"]].rename(columns={"open": "funding"}).sort_values("date")
        fr["pct"] = fr["funding"].rolling(270, min_periods=90).rank(pct=True)
        fr["stamp"] = fr["date"]
        df = pd.merge_asof(df.sort_values("date"), fr, on="date", direction="backward")
        # the first bar at or after each stamp
        df["fresh"] = df["stamp"].ne(df["stamp"].shift())
        df["atr"] = atr(df)
        return df

    def populate_entry_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        hot = df["fresh"] & (df["pct"] >= 0.95)
        cold = df["fresh"] & (df["pct"] <= 0.05)
        if self.coin_side:
            heads = coin(df, metadata["pair"])
            any_ = hot | cold
            df.loc[any_ & heads, "enter_long"] = 1
            df.loc[any_ & ~heads, "enter_short"] = 1
        else:
            df.loc[cold, "enter_long"] = 1  # shorts pay: be long and receive
            df.loc[hot, "enter_short"] = 1  # longs pay: be short and receive
        return df

    def custom_stoploss(self, pair, trade, current_time, current_rate, current_profit, after_fill, **kwargs):
        row = self._row(pair, trade)
        if row is None or not row["atr"] > 0:
            return None
        stop = trade.open_rate + (3 * row["atr"] if trade.is_short else -3 * row["atr"])
        return stoploss_from_absolute(stop, current_rate, is_short=trade.is_short, leverage=trade.leverage)


class FundingFadeCoin(FundingFade):
    coin_side = True


# --------------------------------------------------------------------------------- CoilBreakout


class CoilBreakout(_Base):
    coin_side = False

    def populate_indicators(self, df: DataFrame, metadata: dict) -> DataFrame:
        lh, ll, lc = np.log(df["high"]), np.log(df["low"]), np.log(df["close"])
        prev = lc.shift()
        tr = pd.concat([lh - ll, (lh - prev).abs(), (ll - prev).abs()], axis=1).max(axis=1)
        slow = tr.ewm(alpha=1 / 14, adjust=False).mean()
        df["sigma"] = slow
        df["pct"] = slow.rolling(1500, min_periods=300).rank(pct=True)
        df["box_hi"] = df["high"].rolling(16).max().shift()
        df["box_lo"] = df["low"].rolling(16).min().shift()
        df["armed"] = df["pct"].shift() <= 0.2
        return df

    def populate_entry_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        up = df["armed"] & (df["close"] > df["box_hi"])
        dn = df["armed"] & (df["close"] < df["box_lo"])
        if self.coin_side:
            heads = coin(df, metadata["pair"])
            df.loc[(up | dn) & heads, "enter_long"] = 1
            df.loc[(up | dn) & ~heads, "enter_short"] = 1
        else:
            df.loc[up, "enter_long"] = 1
            df.loc[dn, "enter_short"] = 1
        return df

    def custom_stoploss(self, pair, trade, current_time, current_rate, current_profit, after_fill, **kwargs):
        row = self._row(pair, trade)
        if row is None or np.isnan(row["box_hi"]):
            return None
        sig_px = row["sigma"] * trade.open_rate
        if trade.is_short:
            first = row["box_hi"]
            trail = (trade.min_rate or trade.open_rate) + 2 * sig_px
            stop = min(first, trail)
        else:
            first = row["box_lo"]
            trail = (trade.max_rate or trade.open_rate) - 2 * sig_px
            stop = max(first, trail)
        return stoploss_from_absolute(stop, current_rate, is_short=trade.is_short, leverage=trade.leverage)


class CoilBreakoutCoin(CoilBreakout):
    coin_side = True


# --------------------------------------------------------------------------------- FundingStamp


class FundingStamp(FundingFade):
    hold = 8  # one hour before the stamp to one hour after

    def populate_entry_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        t = df["date"]
        # one hour (4 bars) before the next 8-hourly stamp at 00, 08, 16 UTC
        before = (t.dt.hour % 8 == 7) & (t.dt.minute == 0)
        hot = before & (df["pct"] >= 0.95)
        cold = before & (df["pct"] <= 0.05)
        if self.coin_side:
            heads = coin(df, metadata["pair"])
            df.loc[(hot | cold) & heads, "enter_long"] = 1
            df.loc[(hot | cold) & ~heads, "enter_short"] = 1
        else:
            df.loc[cold, "enter_long"] = 1
            df.loc[hot, "enter_short"] = 1
        return df


class FundingStampCoin(FundingStamp):
    coin_side = True
