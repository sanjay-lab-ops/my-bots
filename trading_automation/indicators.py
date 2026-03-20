"""
All technical indicator calculations.
Replicates your TradingView Pine Script logic in Python.

Indicators included:
  - UTBot  (ATR Trailing Stop — your main Buy/Sell signal)
  - EMA 5, 20, 200, 13 (Elder)
  - MACD (12, 26, 9)
  - Elder Impulse  (EMA13 direction + MACD histogram direction)
  - VWAP  (intraday, resets each day)
  - PVWAP (previous day VWAP closing value)
"""

import numpy as np
import pandas as pd
from config import (
    UTBOT_KEY_VALUE, UTBOT_ATR_PERIOD,
    EMA_FAST, EMA_MID, EMA_SLOW, EMA_ELDER,
    MACD_FAST, MACD_SLOW, MACD_SIGNAL,
)


# ────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────

def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def atr(df: pd.DataFrame, period: int) -> pd.Series:
    """Average True Range."""
    high, low, close_prev = df["high"], df["low"], df["close"].shift(1)
    tr = pd.concat([
        high - low,
        (high - close_prev).abs(),
        (low  - close_prev).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def crossover(s1: pd.Series, s2: pd.Series) -> pd.Series:
    """True on the bar where s1 crosses above s2."""
    return (s1 > s2) & (s1.shift(1) <= s2.shift(1))


def crossunder(s1: pd.Series, s2: pd.Series) -> pd.Series:
    """True on the bar where s1 crosses below s2."""
    return (s1 < s2) & (s1.shift(1) >= s2.shift(1))


# ────────────────────────────────────────────────────────────────
# UTBot — ATR Trailing Stop (your primary signal)
# Exact port of your Pine Script
# ────────────────────────────────────────────────────────────────

def utbot(df: pd.DataFrame,
          key_value: float = UTBOT_KEY_VALUE,
          atr_period: int  = UTBOT_ATR_PERIOD) -> pd.DataFrame:
    """
    Returns df with added columns:
        utbot_stop  — trailing stop level
        utbot_pos   — 1 = long trend, -1 = short trend
        utbot_buy   — True on bullish crossover bar
        utbot_sell  — True on bearish crossunder bar
    """
    src    = df["close"].copy()
    n_loss = key_value * atr(df, atr_period)

    stop = pd.Series(np.nan, index=df.index)

    for i in range(1, len(df)):
        prev_stop = stop.iloc[i - 1] if not np.isnan(stop.iloc[i - 1]) else 0.0
        cur  = src.iloc[i]
        prev = src.iloc[i - 1]
        nl   = n_loss.iloc[i]

        if cur > prev_stop and prev > prev_stop:
            stop.iloc[i] = max(prev_stop, cur - nl)
        elif cur < prev_stop and prev < prev_stop:
            stop.iloc[i] = min(prev_stop, cur + nl)
        elif cur > prev_stop:
            stop.iloc[i] = cur - nl
        else:
            stop.iloc[i] = cur + nl

    # Position
    pos = pd.Series(0, index=df.index)
    for i in range(1, len(df)):
        prev_stop = stop.iloc[i - 1] if not np.isnan(stop.iloc[i - 1]) else 0.0
        if src.iloc[i - 1] < prev_stop and src.iloc[i] > prev_stop:
            pos.iloc[i] = 1
        elif src.iloc[i - 1] > prev_stop and src.iloc[i] < prev_stop:
            pos.iloc[i] = -1
        else:
            pos.iloc[i] = pos.iloc[i - 1]

    df = df.copy()
    df["utbot_stop"] = stop
    df["utbot_pos"]  = pos
    df["utbot_buy"]  = crossover(src, stop)
    df["utbot_sell"] = crossunder(src, stop)
    return df


# ────────────────────────────────────────────────────────────────
# EMA indicators (matches your Pine Script exactly)
# ────────────────────────────────────────────────────────────────

def add_emas(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ema5"]   = ema(df["close"], EMA_FAST)
    df["ema20"]  = ema(df["close"], EMA_MID)
    df["ema200"] = ema(df["close"], EMA_SLOW)
    df["ema13"]  = ema(df["close"], EMA_ELDER)
    return df


# ────────────────────────────────────────────────────────────────
# MACD (matches your Pine Script)
# ────────────────────────────────────────────────────────────────

def add_macd(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    fast_ema  = ema(df["close"], MACD_FAST)
    slow_ema  = ema(df["close"], MACD_SLOW)
    macd_line = fast_ema - slow_ema
    signal    = ema(macd_line, MACD_SIGNAL)
    histogram = macd_line - signal
    df["macd_line"]  = macd_line
    df["macd_signal"] = signal
    df["macd_hist"]  = histogram
    return df


# ────────────────────────────────────────────────────────────────
# Elder Impulse System (matches your Pine Script barcolor logic)
# ────────────────────────────────────────────────────────────────

def add_elder_impulse(df: pd.DataFrame) -> pd.DataFrame:
    """
    elder_bull  = EMA13 rising AND MACD histogram rising  → green bar
    elder_bear  = EMA13 falling AND MACD histogram falling → red bar
    elder_color = 'green' / 'red' / 'blue'
    """
    df = df.copy()
    if "ema13" not in df.columns:
        df = add_emas(df)
    if "macd_hist" not in df.columns:
        df = add_macd(df)

    ema13_rising = df["ema13"] > df["ema13"].shift(1)
    hist_rising  = df["macd_hist"] > df["macd_hist"].shift(1)

    df["elder_bull"]  = ema13_rising & hist_rising
    df["elder_bear"]  = (~ema13_rising) & (~hist_rising)
    df["elder_color"] = np.where(
        df["elder_bull"], "green",
        np.where(df["elder_bear"], "red", "blue")
    )
    return df


# ────────────────────────────────────────────────────────────────
# VWAP — resets each calendar day
# ────────────────────────────────────────────────────────────────

def add_vwap(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds 'vwap' column.
    Uses typical price × tick_volume / cumulative volume, reset daily.
    """
    df = df.copy()
    typical = (df["high"] + df["low"] + df["close"]) / 3
    vol     = df["tick_volume"].replace(0, 1)  # avoid div-by-zero

    # Group by date
    date_key = df.index.date
    df["_tp_vol"] = typical * vol
    df["vwap"]    = np.nan

    for date in np.unique(date_key):
        mask = np.array(date_key) == date
        cum_tpv = df["_tp_vol"][mask].cumsum()
        cum_vol = vol[mask].cumsum()
        df.loc[df.index[mask], "vwap"] = cum_tpv.values / cum_vol.values

    df.drop(columns=["_tp_vol"], inplace=True)
    return df


# ────────────────────────────────────────────────────────────────
# PVWAP — previous day's final VWAP value
# ────────────────────────────────────────────────────────────────

def add_pvwap(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds 'pvwap' column = previous day's last VWAP value (constant intraday).
    Requires 'vwap' column already in df.
    """
    if "vwap" not in df.columns:
        df = add_vwap(df)

    df = df.copy()
    date_key = df.index.date
    dates    = sorted(np.unique(date_key))

    df["pvwap"] = np.nan
    prev_vwap   = None

    for date in dates:
        mask = np.array(date_key) == date
        if prev_vwap is not None:
            df.loc[df.index[mask], "pvwap"] = prev_vwap
        # Last VWAP of this day becomes pvwap for next day
        prev_vwap = df.loc[df.index[mask], "vwap"].iloc[-1]

    return df


# ────────────────────────────────────────────────────────────────
# EMA5 / EMA20 crossover signal on 1-minute candles
# ────────────────────────────────────────────────────────────────

def ema_cross_signal(df_1m: pd.DataFrame) -> str:
    """
    Checks the latest 1m candle for EMA5/EMA20 crossover.
    Returns 'buy', 'sell', or 'none'.
    """
    df = add_emas(df_1m)
    last_buy  = df["utbot_buy"].iloc[-1]  if "utbot_buy"  in df.columns else False
    last_sell = df["utbot_sell"].iloc[-1] if "utbot_sell" in df.columns else False

    buy_cross  = crossover(df["ema5"], df["ema20"]).iloc[-1]
    sell_cross = crossunder(df["ema5"], df["ema20"]).iloc[-1]

    if buy_cross:
        return "buy"
    if sell_cross:
        return "sell"
    return "none"


# ────────────────────────────────────────────────────────────────
# Full indicator pack — run everything on a single df
# ────────────────────────────────────────────────────────────────

def full_analysis(df: pd.DataFrame) -> pd.DataFrame:
    """Run all indicators on df and return enriched DataFrame."""
    df = utbot(df)
    df = add_emas(df)
    df = add_macd(df)
    df = add_elder_impulse(df)
    df = add_vwap(df)
    df = add_pvwap(df)
    return df
