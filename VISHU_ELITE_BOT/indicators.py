"""
VISHU ELITE BOT — Technical Indicators
Provides EMA, RSI, ATR, VWAP, PVWAP calculations used across bias, entry, and risk modules.
All functions accept pandas DataFrames with OHLCV columns.
"""

import numpy as np
import pandas as pd
from config import ATR_PERIOD, RSI_PERIOD, EMA_FAST, EMA_SLOW


# ── Core Calculation Helpers ──────────────────────────────────────

def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average."""
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    """
    Relative Strength Index.
    Uses Wilder's smoothing (same as TradingView default).
    """
    delta = series.diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)

    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> pd.Series:
    """
    Average True Range using Wilder's smoothing.
    Matches TradingView ATR behaviour.
    """
    high       = df["high"]
    low        = df["low"]
    close_prev = df["close"].shift(1)

    tr = pd.concat([
        high - low,
        (high - close_prev).abs(),
        (low  - close_prev).abs(),
    ], axis=1).max(axis=1)

    return tr.ewm(alpha=1 / period, adjust=False).mean()


def crossover(s1: pd.Series, s2: pd.Series) -> pd.Series:
    """True on the bar where s1 crosses ABOVE s2."""
    return (s1 > s2) & (s1.shift(1) <= s2.shift(1))


def crossunder(s1: pd.Series, s2: pd.Series) -> pd.Series:
    """True on the bar where s1 crosses BELOW s2."""
    return (s1 < s2) & (s1.shift(1) >= s2.shift(1))


# ── EMA Functions ─────────────────────────────────────────────────

def add_emas(df: pd.DataFrame, fast: int = EMA_FAST, slow: int = EMA_SLOW) -> pd.DataFrame:
    """Add EMA fast and slow columns to DataFrame."""
    df = df.copy()
    df[f"ema{fast}"]  = ema(df["close"], fast)
    df[f"ema{slow}"]  = ema(df["close"], slow)
    return df


def ema_slope(series: pd.Series, lookback: int = 3) -> str:
    """
    Determine if EMA is rising or falling over last `lookback` bars.
    Returns 'rising', 'falling', or 'flat'.
    """
    if len(series) < lookback + 1:
        return "flat"
    recent = series.iloc[-1]
    past   = series.iloc[-lookback - 1]
    diff   = recent - past
    if diff > 0:
        return "rising"
    elif diff < 0:
        return "falling"
    return "flat"


# ── VWAP (resets each calendar day) ──────────────────────────────

def add_vwap(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add intraday VWAP column. Resets at start of each UTC day.
    Uses typical price × tick_volume for weighting.
    """
    df = df.copy()
    typical = (df["high"] + df["low"] + df["close"]) / 3
    vol     = df["tick_volume"].replace(0, 1)   # avoid div-by-zero

    date_key = df.index.date
    df["_tp_vol"] = typical * vol
    df["vwap"]    = np.nan

    for date in np.unique(date_key):
        mask    = np.array(date_key) == date
        cum_tpv = df["_tp_vol"][mask].cumsum()
        cum_vol = vol[mask].cumsum()
        df.loc[df.index[mask], "vwap"] = cum_tpv.values / cum_vol.values

    df.drop(columns=["_tp_vol"], inplace=True)
    return df


def add_pvwap(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add PVWAP (previous day's final VWAP value) column.
    Requires 'vwap' column already present.
    Constant within each day — changes only at day boundary.
    """
    if "vwap" not in df.columns:
        df = add_vwap(df)

    df = df.copy()
    date_key  = df.index.date
    dates     = sorted(np.unique(date_key))
    df["pvwap"] = np.nan
    prev_vwap   = None

    for date in dates:
        mask = np.array(date_key) == date
        if prev_vwap is not None:
            df.loc[df.index[mask], "pvwap"] = prev_vwap
        # Last VWAP of this day becomes pvwap for next day
        day_vwap_vals = df.loc[df.index[mask], "vwap"].dropna()
        if not day_vwap_vals.empty:
            prev_vwap = day_vwap_vals.iloc[-1]

    return df


# ── RSI Helper ────────────────────────────────────────────────────

def get_rsi_value(df: pd.DataFrame, period: int = RSI_PERIOD) -> float:
    """Return the latest RSI value from a DataFrame."""
    if len(df) < period + 1:
        return 50.0   # neutral default if not enough data
    rsi_series = rsi(df["close"], period)
    return float(rsi_series.iloc[-1])


# ── ATR Helper ────────────────────────────────────────────────────

def get_atr_value(df: pd.DataFrame, period: int = ATR_PERIOD) -> float:
    """Return the latest ATR value from a DataFrame."""
    if len(df) < period + 1:
        return 0.0
    atr_series = atr(df, period)
    return float(atr_series.iloc[-1])


# ── Full Indicator Pack ───────────────────────────────────────────

def full_indicators(df: pd.DataFrame, fast: int = EMA_FAST, slow: int = EMA_SLOW,
                    atr_period: int = ATR_PERIOD) -> pd.DataFrame:
    """
    Run all indicators on a DataFrame and return enriched result.
    Adds: ema_fast, ema_slow, vwap, pvwap, atr, rsi.
    """
    df = add_emas(df, fast, slow)
    df = add_vwap(df)
    df = add_pvwap(df)
    df[f"atr{atr_period}"] = atr(df, atr_period)
    df["rsi"]              = rsi(df["close"], RSI_PERIOD)
    return df
