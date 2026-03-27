"""
Core strategy logic.

Rules (in order):
  1. Must be inside an allowed trading session (IST times from config).
  2. 4H bias: price above VWAP & PVWAP → bullish / below → bearish.
  3. 4H UTBot: must confirm bias direction.
  4. Elder Impulse on 4H: green = bull confirms, red = bear confirms.
  5. 1H UTBot + Elder Impulse: must match 4H bias.
  6. 15M UTBot + Elder Impulse: must match 4H bias.
     (at least 2 of the 3 timeframes = MIN_TIMEFRAME_CONFIRMATIONS).
  7. 1M EMA5 crosses above/below EMA20 → final entry trigger.
  8. Price relative to EMA200 on 4H for extra bias filter.

Returns a Signal object with:
  action      = 'buy' | 'sell' | 'skip'
  reason      = human-readable explanation
  entry_price = float
  atr_4h      = float (used by risk engine for SL/TP)
"""

import logging
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from config import (
    SESSIONS, MIN_TIMEFRAME_CONFIRMATIONS,
    UTBOT_ATR_PERIOD, UTBOT_KEY_VALUE,
)
from indicators import full_analysis, ema_cross_signal, atr, add_emas

logger = logging.getLogger("strategy")


@dataclass
class Signal:
    action:      str   = "skip"   # 'buy' | 'sell' | 'skip'
    reason:      str   = ""
    entry_price: float = 0.0
    atr_4h:      float = 0.0
    confirmations: list = field(default_factory=list)


# ────────────────────────────────────────────────────────────────
# Session check
# ────────────────────────────────────────────────────────────────

def in_session(symbol: str) -> bool:
    """Return True if current UTC time is within any session window for symbol."""
    now_utc = datetime.now(timezone.utc)
    h, m    = now_utc.hour, now_utc.minute
    total_m = h * 60 + m

    for sess in SESSIONS.get(symbol, []):
        sh, sm = sess["start_utc"]
        eh, em = sess["end_utc"]
        start_m = sh * 60 + sm
        end_m   = eh * 60 + em
        if start_m <= total_m <= end_m:
            return True
    return False


def _session_just_opened(symbol: str, wait_minutes: int = 15) -> bool:
    """
    Return True if we are within `wait_minutes` of any session opening for this symbol.
    Prevents entering trades at the exact session open when institutions sweep
    liquidity in both directions before the real move begins (London open trap).
    Gold: 05:00 UTC (London open) is the most dangerous — wait 15 min.
    BTC/ETH: 03:30 and 12:00 UTC — wait 15 min for direction to establish.
    """
    now_utc = datetime.now(timezone.utc)
    h, m    = now_utc.hour, now_utc.minute
    total_m = h * 60 + m

    for sess in SESSIONS.get(symbol, []):
        sh, sm  = sess["start_utc"]
        start_m = sh * 60 + sm
        if start_m <= total_m < start_m + wait_minutes:
            return True
    return False


def session_just_ended(symbol: str, window_minutes: int = 30) -> bool:
    """
    Returns True if a session ended within the last `window_minutes` for this symbol.
    Used to close open positions at session end rather than carry overnight.
    """
    now_utc = datetime.now(timezone.utc)
    h, m    = now_utc.hour, now_utc.minute
    total_m = h * 60 + m

    for sess in SESSIONS.get(symbol, []):
        eh, em  = sess["end_utc"]
        end_m   = eh * 60 + em
        sh, sm  = sess["start_utc"]
        start_m = sh * 60 + sm
        # We are past session end but within window, and not inside a new session
        if end_m < total_m <= end_m + window_minutes:
            # Make sure we're not still inside another session
            if not in_session(symbol):
                return True
    return False


def current_session_label(symbol: str) -> str:
    now_utc = datetime.now(timezone.utc)
    h, m    = now_utc.hour, now_utc.minute
    total_m = h * 60 + m

    for sess in SESSIONS.get(symbol, []):
        sh, sm = sess["start_utc"]
        eh, em = sess["end_utc"]
        if (sh * 60 + sm) <= total_m <= (eh * 60 + em):
            return sess["label"]
    return ""


# ────────────────────────────────────────────────────────────────
# Single-timeframe bias
# ────────────────────────────────────────────────────────────────

def _tf_bias(df: pd.DataFrame) -> str:
    """
    Returns 'bull', 'bear', or 'neutral' for the latest candle in df.
    df must already have utbot / ema / elder columns.
    """
    last = df.iloc[-1]

    utbot_bull = last.get("utbot_pos", 0) == 1
    utbot_bear = last.get("utbot_pos", 0) == -1
    elder      = last.get("elder_color", "blue")

    if utbot_bull and elder == "green":
        return "bull"
    if utbot_bear and elder == "red":
        return "bear"
    return "neutral"


# ────────────────────────────────────────────────────────────────
# Main strategy evaluation
# ────────────────────────────────────────────────────────────────

def evaluate(
    symbol:   str,
    df_4h:    pd.DataFrame,
    df_1h:    pd.DataFrame,
    df_15m:   pd.DataFrame,
    df_1m:    pd.DataFrame,
    bid_price: float,
) -> Signal:
    """
    Evaluate all strategy rules and return a Signal.
    All DataFrames must be raw MT5 candle data (open/high/low/close/tick_volume).
    """
    sig = Signal(entry_price=bid_price)

    # ── 0. Session gate ─────────────────────────────────────────
    if not in_session(symbol):
        sig.reason = "Outside trading session"
        return sig

    # ── 0b. Session open delay — wait 15 min after open ─────────
    # London open (Gold 05:00 UTC) and crypto opens are prime manipulation windows.
    # Institutions sweep liquidity both ways before the real move. Never enter first 15 min.
    if _session_just_opened(symbol, wait_minutes=15):
        sig.reason = "Session just opened — waiting 15 min for direction to establish (avoid open trap)"
        return sig

    # ── 1. Run indicators on all timeframes ─────────────────────
    df_4h  = full_analysis(df_4h)
    df_1h  = full_analysis(df_1h)
    df_15m = full_analysis(df_15m)
    df_1m  = add_emas(df_1m)        # only need EMAs on 1m for cross trigger

    last_4h  = df_4h.iloc[-1]
    last_15m = df_15m.iloc[-1]

    # ── 2. VWAP / PVWAP bias from 15M (more data points than 4H) ─
    # BUG FIX: config says VWAP_TIMEFRAME=M15 but code was using 4H.
    # At session open, 4H VWAP only has 1-2 candles — meaningless.
    # 15M VWAP has 20+ candles by London open and gives a real intraday anchor.
    vwap  = last_15m.get("vwap",  float("nan"))
    pvwap = last_15m.get("pvwap", float("nan"))
    price = bid_price   # compare live price against intraday VWAP

    import math
    if math.isnan(vwap) or math.isnan(pvwap):
        sig.reason = "VWAP/PVWAP not ready (insufficient data)"
        return sig

    if price > vwap and price > pvwap:
        vwap_bias = "bull"
    elif price < vwap and price < pvwap:
        vwap_bias = "bear"
    else:
        sig.reason = f"Price ${price:.2f} between VWAP {vwap:.2f} and PVWAP {pvwap:.2f} — no clear bias"
        return sig

    sig.confirmations.append(f"VWAP bias: {vwap_bias} (price={price:.2f}, vwap={vwap:.2f}, pvwap={pvwap:.2f})")

    # ── 3. 4H EMA200 filter ──────────────────────────────────────
    ema200_4h = last_4h.get("ema200", float("nan"))
    if not math.isnan(ema200_4h):
        ema200_bias = "bull" if price > ema200_4h else "bear"
        if ema200_bias == vwap_bias:
            sig.confirmations.append(f"EMA200 confirms {vwap_bias} (ema200={ema200_4h:.2f})")
        else:
            sig.confirmations.append(f"EMA200 conflicts — price {'above' if price > ema200_4h else 'below'} EMA200")

    # ── 4. Multi-timeframe UTBot + Elder confirmations ───────────
    bias_4h  = _tf_bias(df_4h)
    bias_1h  = _tf_bias(df_1h)
    bias_15m = _tf_bias(df_15m)

    tf_results = {
        "4H":  bias_4h,
        "1H":  bias_1h,
        "15M": bias_15m,
    }

    matching = {tf: b for tf, b in tf_results.items() if b == vwap_bias}
    non_matching = {tf: b for tf, b in tf_results.items() if b != vwap_bias}

    for tf, bias in tf_results.items():
        icon = "✓" if bias == vwap_bias else "✗"
        sig.confirmations.append(f"UTBot+Elder {tf}: {bias} {icon}")

    if len(matching) < MIN_TIMEFRAME_CONFIRMATIONS:
        sig.reason = (
            f"Only {len(matching)}/{len(tf_results)} timeframes confirm {vwap_bias} bias "
            f"(need {MIN_TIMEFRAME_CONFIRMATIONS}). "
            f"Non-matching: {non_matching}"
        )
        return sig

    sig.confirmations.append(
        f"Timeframe confirmation: {len(matching)}/{len(tf_results)} match {vwap_bias}"
    )

    # ── 5. 1M EMA5/EMA20 crossover trigger ──────────────────────
    # Fires on: (a) exact cross on last bar, OR
    #           (b) cross happened within last 5 bars (recent, not stale)
    from indicators import crossover, crossunder
    ema5_1m  = df_1m["ema5"]
    ema20_1m = df_1m["ema20"]
    LOOKBACK = 5  # bars — recent cross window

    buy_cross  = crossover(ema5_1m,  ema20_1m).iloc[-LOOKBACK:].any()
    sell_cross = crossunder(ema5_1m, ema20_1m).iloc[-LOOKBACK:].any()

    # Extra check: EMA5 must still be on the correct side right now
    ema5_above = ema5_1m.iloc[-1] > ema20_1m.iloc[-1]

    if vwap_bias == "bull" and not (buy_cross and ema5_above):
        sig.reason = "Waiting for 1M EMA5 to cross above EMA20 (buy trigger not fired yet)"
        return sig
    if vwap_bias == "bear" and not (sell_cross and not ema5_above):
        sig.reason = "Waiting for 1M EMA5 to cross below EMA20 (sell trigger not fired yet)"
        return sig

    sig.confirmations.append(
        f"1M trigger: EMA5 crossed {'above' if vwap_bias == 'bull' else 'below'} EMA20 ✓"
    )

    # ── 6. ATR for SL/TP ────────────────────────────────────────
    from indicators import atr as calc_atr
    atr_series = calc_atr(df_4h, UTBOT_ATR_PERIOD)
    sig.atr_4h = atr_series.iloc[-1]

    # ── All checks passed ────────────────────────────────────────
    sig.action = "buy" if vwap_bias == "bull" else "sell"
    sig.reason = (
        f"{symbol} {sig.action.upper()} | Session: {current_session_label(symbol)} | "
        f"{len(matching)} TF confirmations | 1M EMA cross triggered"
    )
    return sig
