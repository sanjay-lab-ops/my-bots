"""
Pure technical indicator calculations -- no MT5 dependency.
All functions take pandas Series or DataFrames, return Series.
"""

import numpy as np
import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range."""
    high  = df["high"]
    low   = df["low"]
    close = df["close"]
    prev  = close.shift(1)
    tr    = pd.concat([
        high - low,
        (high - prev).abs(),
        (low  - prev).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta  = series.diff()
    gain   = delta.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
    loss   = (-delta.clip(upper=0)).ewm(com=period - 1, adjust=False).mean()
    rs     = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def vwap(df: pd.DataFrame) -> pd.Series:
    """Session VWAP -- resets at start of dataframe (use daily slice)."""
    typical = (df["high"] + df["low"] + df["close"]) / 3
    vol     = df["tick_volume"].replace(0, 1)
    cum_tp  = (typical * vol).cumsum()
    cum_vol = vol.cumsum()
    return cum_tp / cum_vol


def swing_highs(df: pd.DataFrame, lookback: int = 10) -> pd.Series:
    """
    Returns a Series with swing high prices where detected, NaN elsewhere.
    A swing high = candle whose high is the highest in [i-lookback : i+lookback].
    """
    highs  = df["high"]
    result = pd.Series(np.nan, index=df.index)
    for i in range(lookback, len(df) - lookback):
        window = highs.iloc[i - lookback: i + lookback + 1]
        if highs.iloc[i] == window.max():
            result.iloc[i] = highs.iloc[i]
    return result


def swing_lows(df: pd.DataFrame, lookback: int = 10) -> pd.Series:
    """
    Returns a Series with swing low prices where detected, NaN elsewhere.
    """
    lows   = df["low"]
    result = pd.Series(np.nan, index=df.index)
    for i in range(lookback, len(df) - lookback):
        window = lows.iloc[i - lookback: i + lookback + 1]
        if lows.iloc[i] == window.min():
            result.iloc[i] = lows.iloc[i]
    return result


def crossover(fast: pd.Series, slow: pd.Series) -> pd.Series:
    """True where fast crosses above slow."""
    return (fast > slow) & (fast.shift(1) <= slow.shift(1))


def crossunder(fast: pd.Series, slow: pd.Series) -> pd.Series:
    """True where fast crosses below slow."""
    return (fast < slow) & (fast.shift(1) >= slow.shift(1))


def anchored_vwap(df: pd.DataFrame, anchor_pos: int) -> float:
    """
    Compute VWAP anchored to bar at integer position anchor_pos.
    Returns the current (last) VWAP value from that anchor point.
    Used for fair-value confluence: price near AVWAP = institutional interest zone.
    """
    if anchor_pos < 0 or anchor_pos >= len(df):
        return float("nan")
    sub     = df.iloc[anchor_pos:]
    typical = (sub["high"] + sub["low"] + sub["close"]) / 3
    vol     = sub["tick_volume"].replace(0, 1)
    avwap   = (typical * vol).cumsum() / vol.cumsum()
    return float(avwap.iloc[-1])


def volume_average(df: pd.DataFrame, period: int = 20) -> float:
    """Simple moving average of tick_volume over last `period` bars."""
    n = min(period, len(df))
    return float(df["tick_volume"].iloc[-n:].mean()) if n > 0 else 1.0
