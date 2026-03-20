"""
Elite Execution Module — Top 1% Institutional Techniques
=========================================================
Shared across all 3 Vishu bots. Copy to each bot's folder.

What this adds:
  1. Kill Zone Filter     — trade only during high-volume institutional windows
  2. Structural SL        — SL at last swing high/low (tighter → same risk → MORE LOTS)
  3. OTE Entry Zone       — Fibonacci 61.8–79% retracement after Break of Structure
  4. DXY Correlation      — Gold/Silver SELL only when USD bullish, BUY when bearish
  5. Liquidity Sweep      — detect stop hunts → enter the reversal
  6. Market State         — TRENDING / CONSOLIDATING / VOLATILE — adapt lot size
  7. Cross-Asset Correlation — BTC move confirms ETH entry, Gold move confirms Silver
  8. Volume Imbalance     — institutional order flow direction from tick volume
  9. Spread Guard         — skip entry if bid-ask spread is abnormally wide (thin liquidity)

RULE: This module NEVER blocks a trade. It only improves SL, lot, and entry timing.
      If any function fails → log warning, return safe default, continue trading.
"""

import math
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple

import MetaTrader5 as mt5

logger = logging.getLogger("elite_execution")

IST = timedelta(hours=5, minutes=30)

# ── Kill Zones (UTC) ─────────────────────────────────────────────────────────
# Windows where institutional volume is highest — best entries happen here.
# Outside these windows trades still fire but are marked as suboptimal timing.

KILL_ZONES_UTC = {
    "GOLD": [
        {"name": "London Open",  "start": (2,  0), "end": (5,  0)},   # 7:30–10:30 IST
        {"name": "NY Open",      "start": (8,  0), "end": (10, 0)},   # 1:30–3:30 PM IST
        {"name": "London Close", "start": (10, 0), "end": (12, 0)},   # 3:30–5:30 PM IST
    ],
    "SILVER": [
        {"name": "London Open",  "start": (2,  0), "end": (5,  0)},
        {"name": "NY Open",      "start": (8,  0), "end": (10, 0)},
        {"name": "London Close", "start": (10, 0), "end": (12, 0)},
    ],
    "BTC": [
        {"name": "Asian Close",  "start": (0,  0),  "end": (2,  0)},  # 5:30–7:30 IST
        {"name": "London Open",  "start": (2,  0),  "end": (5,  0)},  # 7:30–10:30 IST
        {"name": "NYSE Open",    "start": (13, 30), "end": (16, 0)},  # 7:00–9:30 PM IST
    ],
    "ETH": [
        {"name": "Asian Close",  "start": (0,  0),  "end": (2,  0)},
        {"name": "London Open",  "start": (2,  0),  "end": (5,  0)},
        {"name": "NYSE Open",    "start": (13, 30), "end": (16, 0)},
    ],
}

SYMBOL_CATEGORY = {
    "XAUUSD": "GOLD",   "XAUUSDm": "GOLD",
    "XAGUSD": "SILVER", "XAGUSDm": "SILVER",
    "BTCUSD": "BTC",    "BTCUSDm": "BTC",
    "ETHUSD": "ETH",    "ETHUSDm": "ETH",
}

# DXY symbols to try in order (broker-specific)
_DXY_CANDIDATES = ["USIDX", "USDIXm", "DXY", "DX-Y.NYB"]


# ─────────────────────────────────────────────────────────────────────────────
# 1. KILL ZONE
# ─────────────────────────────────────────────────────────────────────────────

def is_kill_zone(symbol: str) -> Tuple[bool, str]:
    """
    Returns (True, zone_name) if currently inside a high-volume kill zone.
    Returns (False, "") if outside — trade still fires, just flagged as suboptimal.
    RULE: Unknown symbol → True (never block).
    """
    try:
        now_utc  = datetime.now(timezone.utc)
        now_m    = now_utc.hour * 60 + now_utc.minute
        category = SYMBOL_CATEGORY.get(symbol, "")
        if not category:
            return True, "Kill zone N/A"
        for z in KILL_ZONES_UTC.get(category, []):
            s = z["start"][0] * 60 + z["start"][1]
            e = z["end"][0]   * 60 + z["end"][1]
            if s <= now_m <= e:
                return True, z["name"]
        ist_now = (now_utc + IST).strftime("%H:%M IST")
        logger.info("[%s] Outside kill zones at %s — trade fires anyway", symbol, ist_now)
        return False, ""
    except Exception as exc:
        logger.error("is_kill_zone error: %s", exc)
        return True, ""


# ─────────────────────────────────────────────────────────────────────────────
# 2. SWING POINT DETECTION
# ─────────────────────────────────────────────────────────────────────────────

def _find_swings(df, lookback: int = 30) -> Tuple[list, list]:
    """
    Find swing highs and lows in 4H OHLC data.
    Returns (highs, lows) as lists of float prices.
    """
    highs, lows = [], []
    try:
        n = min(len(df) - 3, lookback + 3)
        for i in range(3, n):
            idx = len(df) - 1 - i
            if idx < 3 or idx >= len(df) - 3:
                continue
            h = df["high"].iloc[idx]
            l = df["low"].iloc[idx]
            lh = df["high"].iloc[idx - 3: idx]
            rh = df["high"].iloc[idx + 1: idx + 4]
            ll = df["low"].iloc[idx - 3: idx]
            rl = df["low"].iloc[idx + 1: idx + 4]
            if len(lh) and len(rh) and h > lh.max() and h > rh.max():
                highs.append(h)
            if len(ll) and len(rl) and l < ll.min() and l < rl.min():
                lows.append(l)
    except Exception as exc:
        logger.error("_find_swings error: %s", exc)
    return highs, lows


# ─────────────────────────────────────────────────────────────────────────────
# 3. STRUCTURAL SL
# ─────────────────────────────────────────────────────────────────────────────

def get_structural_sl(df_4h, direction: str, entry_price: float,
                      atr_val: float, symbol: str) -> Tuple[float, float]:
    """
    Place SL at the nearest swing high/low instead of ATR × 1.5.
    Tighter SL = same % risk = more lots = more profit.

    Returns (sl_price, sl_distance).
    Falls back to ATR × 1.5 if no valid swing found.
    """
    atr_sl_dist = atr_val * 1.5
    try:
        highs, lows = _find_swings(df_4h, lookback=30)
        is_sell     = direction.upper() in ("SELL", "sell")

        if is_sell and highs:
            # SL = nearest swing high ABOVE entry
            candidates = [h for h in highs if h > entry_price]
            if candidates:
                swing = min(candidates)                          # closest one
                buffer   = swing * 0.001                        # 0.1% buffer
                sl_price = swing + buffer
                sl_dist  = sl_price - entry_price
                # Sanity: must be at least 0.3× ATR and at most 3× ATR
                if atr_val * 0.3 <= sl_dist <= atr_val * 3.0:
                    tighter_pct = max(0, (atr_sl_dist - sl_dist) / atr_sl_dist * 100)
                    logger.info(
                        "[%s] STRUCTURAL SL SELL @ %.5f | swing_high=%.5f | %.0f%% tighter than ATR SL",
                        symbol, sl_price, swing, tighter_pct,
                    )
                    return sl_price, sl_dist

        elif not is_sell and lows:
            # SL = nearest swing low BELOW entry
            candidates = [l for l in lows if l < entry_price]
            if candidates:
                swing    = max(candidates)
                buffer   = swing * 0.001
                sl_price = swing - buffer
                sl_dist  = entry_price - sl_price
                if atr_val * 0.3 <= sl_dist <= atr_val * 3.0:
                    tighter_pct = max(0, (atr_sl_dist - sl_dist) / atr_sl_dist * 100)
                    logger.info(
                        "[%s] STRUCTURAL SL BUY @ %.5f | swing_low=%.5f | %.0f%% tighter than ATR SL",
                        symbol, sl_price, swing, tighter_pct,
                    )
                    return sl_price, sl_dist

    except Exception as exc:
        logger.error("get_structural_sl error for %s: %s", symbol, exc)

    # Fallback: ATR-based
    logger.info("[%s] Structural SL not found — falling back to ATR SL (dist=%.2f)", symbol, atr_sl_dist)
    if direction.upper() in ("SELL", "sell"):
        return entry_price + atr_sl_dist, atr_sl_dist
    return entry_price - atr_sl_dist, atr_sl_dist


# ─────────────────────────────────────────────────────────────────────────────
# 4. OTE ZONE (Optimal Trade Entry — Fibonacci 61.8–79%)
# ─────────────────────────────────────────────────────────────────────────────

def is_in_ote_zone(df_4h, current_price: float, direction: str) -> Tuple[bool, str]:
    """
    Returns (True, reason) if price is in the 61.8–79% Fibonacci retracement zone.
    This is where institutions re-enter after a Break of Structure.
    RULE: Returns (True, "") if can't calculate — don't block trade.
    """
    try:
        highs, lows = _find_swings(df_4h, lookback=20)
        if not highs or not lows:
            return True, ""

        sh = max(highs)   # most prominent recent swing high
        sl = min(lows)    # most prominent recent swing low
        rng = sh - sl
        if rng <= 0:
            return True, ""

        is_sell = direction.upper() in ("SELL", "sell")
        if is_sell:
            # Expecting price to sell from high → OTE is 61.8–79% down from high
            ote_low  = sh - rng * 0.786
            ote_high = sh - rng * 0.618
        else:
            # Expecting price to buy from low → OTE is 61.8–79% up from low
            ote_low  = sl + rng * 0.618
            ote_high = sl + rng * 0.786

        if ote_low <= current_price <= ote_high:
            return True, f"OTE zone {ote_low:.2f}–{ote_high:.2f}"

        logger.info(
            "Price %.2f outside OTE zone (%.2f–%.2f) for %s — suboptimal entry",
            current_price, ote_low, ote_high, direction,
        )
        return False, f"Outside OTE ({ote_low:.2f}–{ote_high:.2f})"

    except Exception as exc:
        logger.error("is_in_ote_zone error: %s", exc)
        return True, ""


# ─────────────────────────────────────────────────────────────────────────────
# 5. DXY CORRELATION (Gold & Silver only)
# ─────────────────────────────────────────────────────────────────────────────

def get_dxy_bias() -> str:
    """
    Returns "bullish", "bearish", or "neutral" for the US Dollar Index.
    Gold/Silver SELL → best when DXY bullish (inverse correlation).
    Gold/Silver BUY  → best when DXY bearish.
    RULE: Returns "neutral" if DXY unavailable — don't block trade.
    """
    try:
        import pandas as pd
        dxy_sym = None
        for sym in _DXY_CANDIDATES:
            if mt5.symbol_info(sym) is not None:
                dxy_sym = sym
                break
        if dxy_sym is None:
            return "neutral"

        rates = mt5.copy_rates_from_pos(dxy_sym, mt5.TIMEFRAME_H4, 0, 50)
        if rates is None or len(rates) == 0:
            return "neutral"

        df     = pd.DataFrame(rates)
        ema20  = df["close"].ewm(span=20).mean()
        cur    = df["close"].iloc[-1]
        ema    = ema20.iloc[-1]

        if cur > ema * 1.001:
            logger.info("DXY BULLISH (%.4f > EMA20 %.4f) — confirms Gold SELL", cur, ema)
            return "bullish"
        if cur < ema * 0.999:
            logger.info("DXY BEARISH (%.4f < EMA20 %.4f) — confirms Gold BUY", cur, ema)
            return "bearish"
        return "neutral"

    except Exception as exc:
        logger.error("get_dxy_bias error: %s", exc)
        return "neutral"


# ─────────────────────────────────────────────────────────────────────────────
# 6. LIQUIDITY SWEEP DETECTION
# ─────────────────────────────────────────────────────────────────────────────

def detect_liquidity_sweep(df_1h, direction: str, symbol: str) -> Tuple[bool, str]:
    """
    Detect if price just grabbed liquidity (stop hunt) and reversed.
    For SELL: price briefly broke above swing high then closed back below.
    For BUY:  price briefly broke below swing low then closed back above.
    This is the highest-probability entry — institutions just trapped retail.
    """
    try:
        if df_1h is None or len(df_1h) < 10:
            return False, ""

        highs, lows = _find_swings(df_1h.iloc[:-2], lookback=20)
        last_high   = df_1h["high"].iloc[-1]
        last_low    = df_1h["low"].iloc[-1]
        last_close  = df_1h["close"].iloc[-1]
        prev_close  = df_1h["close"].iloc[-2]

        is_sell = direction.upper() in ("SELL", "sell")

        if is_sell and highs:
            ref = max(highs)
            if last_high > ref and last_close < ref:
                msg = f"LIQUIDITY SWEEP SELL: spiked above {ref:.3f} → closed {last_close:.3f}"
                logger.info("[%s] %s", symbol, msg)
                return True, msg

        elif not is_sell and lows:
            ref = min(lows)
            if last_low < ref and last_close > ref:
                msg = f"LIQUIDITY SWEEP BUY: spiked below {ref:.3f} → closed {last_close:.3f}"
                logger.info("[%s] %s", symbol, msg)
                return True, msg

    except Exception as exc:
        logger.error("detect_liquidity_sweep error for %s: %s", symbol, exc)
    return False, ""


# ─────────────────────────────────────────────────────────────────────────────
# 7. MARKET STATE (Trending / Consolidating / Volatile)
# ─────────────────────────────────────────────────────────────────────────────

def get_market_state(df_4h, symbol: str) -> Tuple[str, float]:
    """
    Determine if market is TRENDING, CONSOLIDATING, or VOLATILE.
    Returns (state, atr_ratio) where atr_ratio = current ATR / avg ATR.

    TRENDING     → atr_ratio 0.8–1.5, price moving in one direction (ADX-like)
    CONSOLIDATING→ atr_ratio < 0.7, price going sideways
    VOLATILE     → atr_ratio > 1.5, sudden spike (news, event)

    Lot size multiplier:
      TRENDING      → ×1.0  (normal — ride the move)
      CONSOLIDATING → ×0.7  (reduce size — choppier, wider stops needed)
      VOLATILE      → ×1.2  (bigger moves possible — institution moving market)
    """
    try:
        if df_4h is None or len(df_4h) < 20:
            return "TRENDING", 1.0

        highs = df_4h["high"]
        lows  = df_4h["low"]
        tr    = (highs - lows).abs()
        atr_now = tr.iloc[-5:].mean()       # last 5 candles
        atr_avg = tr.iloc[-20:].mean()      # last 20 candles

        if atr_avg == 0:
            return "TRENDING", 1.0

        ratio = atr_now / atr_avg

        # Direction consistency — last 5 closes all same direction?
        closes   = df_4h["close"].iloc[-6:]
        moves    = closes.diff().dropna()
        same_dir = (moves > 0).sum() >= 4 or (moves < 0).sum() >= 4

        if ratio > 1.5:
            state = "VOLATILE"
        elif ratio < 0.7:
            state = "CONSOLIDATING"
        elif same_dir:
            state = "TRENDING"
        else:
            state = "CONSOLIDATING"

        logger.info(
            "[%s] Market state: %s | ATR ratio: %.2f (now=%.2f avg=%.2f)",
            symbol, state, ratio, atr_now, atr_avg,
        )
        return state, round(ratio, 2)

    except Exception as exc:
        logger.error("get_market_state error for %s: %s", symbol, exc)
        return "TRENDING", 1.0


_STATE_LOT_MULT = {
    "TRENDING":      1.0,
    "CONSOLIDATING": 0.7,
    "VOLATILE":      1.2,
}


# ─────────────────────────────────────────────────────────────────────────────
# 8. ELITE LOT SIZE
# ─────────────────────────────────────────────────────────────────────────────

def elite_lot_size(balance: float, sl_dist: float, symbol: str,
                   risk_pct: float = 1.5, state_mult: float = 1.0) -> float:
    """
    Calculate lot size using structural SL distance.
    Formula: lot = (balance × risk%) / (sl_dist × contract_size)

    Tighter SL → same dollar risk → more lots.
    state_mult: from get_market_state() — adjust for market condition.
    """
    _default = {
        "BTCUSD":  (0.01, 1.0,  0.01, 1),
        "BTCUSDm": (0.01, 1.0,  0.01, 1),
        "ETHUSD":  (0.1,  10.0, 0.1,  1),
        "ETHUSDm": (0.1,  10.0, 0.1,  1),
        "XAUUSD":  (0.01, 50.0, 0.01, 100),
        "XAUUSDm": (0.01, 50.0, 0.01, 100),
        "XAGUSD":  (0.01, 50.0, 0.01, 5000),
        "XAGUSDm": (0.01, 50.0, 0.01, 5000),
    }
    try:
        min_lot, max_lot, lot_step, contract_size = _default.get(
            symbol, (0.01, 1.0, 0.01, 1)
        )
        if sl_dist <= 0 or balance <= 0:
            return min_lot
        risk_amt = balance * (risk_pct / 100)
        sl_usd   = sl_dist * contract_size
        raw      = risk_amt / sl_usd if sl_usd > 0 else min_lot
        raw      = raw * state_mult
        raw      = max(min_lot, min(max_lot, raw))
        lot      = round(math.floor(raw / lot_step) * lot_step, 2)

        actual_risk = lot * sl_usd
        logger.info(
            "ELITE LOT [%s]: $%.2f balance | SL dist=%.5f | state×%.1f | lot=%.2f | risk=$%.2f (%.1f%%)",
            symbol, balance, sl_dist, state_mult, lot, actual_risk,
            (actual_risk / balance * 100) if balance > 0 else 0,
        )
        return lot
    except Exception as exc:
        logger.error("elite_lot_size error for %s: %s", symbol, exc)
        return _default.get(symbol, (0.01,))[0]


# ─────────────────────────────────────────────────────────────────────────────
# 8. CROSS-ASSET CORRELATION (Tower Research style — directional only)
# ─────────────────────────────────────────────────────────────────────────────

# Pairs that move together — if primary fires, check correlated asset confirms
_CORRELATIONS = {
    "BTCUSD":  {"partner": "ETHUSDm",  "same_direction": True},   # BTC up → ETH up
    "BTCUSDm": {"partner": "ETHUSDm",  "same_direction": True},
    "ETHUSD":  {"partner": "BTCUSDm",  "same_direction": True},   # ETH up → BTC up
    "ETHUSDm": {"partner": "BTCUSDm",  "same_direction": True},
    "XAUUSD":  {"partner": "XAGUSDm",  "same_direction": True},   # Gold down → Silver down
    "XAUUSDm": {"partner": "XAGUSDm",  "same_direction": True},
    "XAGUSD":  {"partner": "XAUUSDm",  "same_direction": True},   # Silver down → Gold down
    "XAGUSDm": {"partner": "XAUUSDm",  "same_direction": True},
}


def get_correlation_score(symbol: str, direction: str) -> Tuple[float, str]:
    """
    Check if the correlated asset confirms the trade direction.

    BTC SELL + ETH also bearish (EMA5 < EMA20 on 1H) → score = 1.0 (confirmed)
    BTC SELL + ETH bullish                             → score = 0.8 (no confirm — trade anyway)
    No correlated asset found                          → score = 1.0

    Returns (score, reason).
    score 1.0 = confirmed → lot ×1.0 (normal)
    score 1.2 = strongly confirmed → lot ×1.2 (bigger)
    score 0.8 = conflicting → lot ×0.8 (smaller, less conviction)
    """
    try:
        info = _CORRELATIONS.get(symbol)
        if not info:
            return 1.0, ""

        partner_sym = info["partner"]
        rates = mt5.copy_rates_from_pos(partner_sym, mt5.TIMEFRAME_H1, 0, 25)
        if rates is None or len(rates) < 20:
            return 1.0, f"Correlation: {partner_sym} data unavailable"

        import pandas as pd
        df      = pd.DataFrame(rates)
        closes  = df["close"]
        ema5    = closes.ewm(span=5).mean().iloc[-1]
        ema20   = closes.ewm(span=20).mean().iloc[-1]

        is_sell    = direction.upper() in ("SELL", "sell")
        partner_bearish = ema5 < ema20
        partner_bullish = ema5 > ema20

        if is_sell and partner_bearish:
            logger.info("CORRELATION [%s]: %s also bearish → STRONG CONFIRM → lot ×1.2", symbol, partner_sym)
            return 1.2, f"✅ {partner_sym} also bearish — strong confirm"
        elif not is_sell and partner_bullish:
            logger.info("CORRELATION [%s]: %s also bullish → STRONG CONFIRM → lot ×1.2", symbol, partner_sym)
            return 1.2, f"✅ {partner_sym} also bullish — strong confirm"
        elif is_sell and partner_bullish:
            logger.info("CORRELATION [%s]: %s bullish but we SELL — weaker signal → lot ×0.8", symbol, partner_sym)
            return 0.8, f"⚠️ {partner_sym} bullish conflicts SELL — lot reduced"
        elif not is_sell and partner_bearish:
            logger.info("CORRELATION [%s]: %s bearish but we BUY — weaker signal → lot ×0.8", symbol, partner_sym)
            return 0.8, f"⚠️ {partner_sym} bearish conflicts BUY — lot reduced"
        return 1.0, f"{partner_sym} neutral"

    except Exception as exc:
        logger.error("get_correlation_score error for %s: %s", symbol, exc)
        return 1.0, ""


# ─────────────────────────────────────────────────────────────────────────────
# 9. VOLUME IMBALANCE (simplified order flow — HRT principle)
# ─────────────────────────────────────────────────────────────────────────────

def get_volume_imbalance(df_4h, direction: str, symbol: str) -> Tuple[str, float, str]:
    """
    Check if institutional order flow (tick volume) confirms trade direction.

    How it works:
      - Look at last 5 candles' tick volume
      - UP candles (close > open) = buying pressure
      - DOWN candles (close < open) = selling pressure
      - If 70%+ of total volume is in trade direction → CONFIRMED
      - If < 40% → CONFLICTING

    Returns (verdict, score, reason)
      verdict : "CONFIRMED" / "NEUTRAL" / "CONFLICTING"
      score   : lot multiplier (1.1 / 1.0 / 0.9)
    """
    try:
        if df_4h is None or len(df_4h) < 5:
            return "NEUTRAL", 1.0, ""

        recent   = df_4h.iloc[-5:]
        is_sell  = direction.upper() in ("SELL", "sell")

        up_vol   = recent.loc[recent["close"] >= recent["open"], "tick_volume"].sum()
        down_vol = recent.loc[recent["close"] <  recent["open"], "tick_volume"].sum()
        total    = up_vol + down_vol

        if total == 0:
            return "NEUTRAL", 1.0, ""

        sell_pct = down_vol / total * 100
        buy_pct  = up_vol   / total * 100

        if is_sell:
            if sell_pct >= 70:
                return "CONFIRMED",   1.1, f"✅ Volume: {sell_pct:.0f}% selling pressure confirms SELL"
            elif sell_pct < 40:
                return "CONFLICTING", 0.9, f"⚠️ Volume: {buy_pct:.0f}% buying vs SELL setup"
            return "NEUTRAL", 1.0, f"Volume: {sell_pct:.0f}% sell / {buy_pct:.0f}% buy"
        else:
            if buy_pct >= 70:
                return "CONFIRMED",   1.1, f"✅ Volume: {buy_pct:.0f}% buying pressure confirms BUY"
            elif buy_pct < 40:
                return "CONFLICTING", 0.9, f"⚠️ Volume: {sell_pct:.0f}% selling vs BUY setup"
            return "NEUTRAL", 1.0, f"Volume: {buy_pct:.0f}% buy / {sell_pct:.0f}% sell"

    except Exception as exc:
        logger.error("get_volume_imbalance error for %s: %s", symbol, exc)
        return "NEUTRAL", 1.0, ""


# ─────────────────────────────────────────────────────────────────────────────
# 10. SPREAD GUARD (execution quality — never enter thin liquidity)
# ─────────────────────────────────────────────────────────────────────────────

# Max acceptable spread per symbol (in price units)
_MAX_SPREAD = {
    "BTCUSDm":  80.0,   # BTC: normal ~5–15, max 80 (news spike)
    "ETHUSDm":  5.0,    # ETH: normal ~0.5–2, max 5
    "XAUUSDm":  1.0,    # Gold: normal ~0.2–0.4, max 1.0
    "XAGUSDm":  0.08,   # Silver: normal ~0.02–0.04, max 0.08
}


def check_spread(symbol: str, mt5_symbol: str) -> Tuple[bool, float, str]:
    """
    Check if current bid-ask spread is within acceptable limits.
    Wide spread = thin liquidity = bad fill = extra slippage eating your profit.

    Returns (is_ok, spread_value, reason).
    RULE: If spread data unavailable → return True (don't block trade).
    """
    try:
        tick = mt5.symbol_info_tick(mt5_symbol)
        if tick is None:
            return True, 0.0, "Spread data unavailable"

        spread    = tick.ask - tick.bid
        max_ok    = _MAX_SPREAD.get(mt5_symbol, 999.0)

        if spread <= 0:
            return True, 0.0, ""

        if spread > max_ok:
            msg = f"⚠️ SPREAD {spread:.4f} > max {max_ok} — thin liquidity, entering anyway"
            logger.warning("[%s] %s", symbol, msg)
            return False, spread, msg

        return True, spread, f"Spread OK: {spread:.4f} (max {max_ok})"

    except Exception as exc:
        logger.error("check_spread error for %s: %s", symbol, exc)
        return True, 0.0, ""


# ─────────────────────────────────────────────────────────────────────────────
# 11. MAIN ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def elite_filter(
    symbol:      str,
    direction:   str,
    entry_price: float,
    df_4h,
    df_1h,
    atr_val:     float,
    balance:     float,
    risk_pct:    float = 1.5,
    rr_ratio:    float = 2.5,
) -> dict:
    """
    Run all elite checks and return a dict with enhanced trade parameters.

    Returns:
      in_kill_zone   : bool   — is timing optimal?
      kill_zone_name : str
      structural_sl  : float  — SL price (tighter than ATR)
      sl_distance    : float  — distance entry → SL
      elite_lot      : float  — lot using structural SL + market state
      tp_price       : float  — TP at rr_ratio × sl_distance
      in_ote         : bool   — is price in OTE zone?
      ote_reason     : str
      dxy_bias       : str    — bullish/bearish/neutral (Gold/Silver only)
      sweep_detected : bool   — liquidity sweep confirmation
      sweep_reason   : str
      market_state   : str    — TRENDING / CONSOLIDATING / VOLATILE
      state_mult     : float  — lot multiplier based on market state
      use_elite_sl   : bool   — True if structural SL is tighter than ATR SL
      notes          : list   — human-readable summary

    RULE: Never crashes. If any check fails → safe default, continue trading.
    """
    notes  = []
    atr_sl = atr_val * 1.5
    is_sell = direction.upper() in ("SELL", "sell")

    result = {
        "in_kill_zone":   True,
        "kill_zone_name": "",
        "structural_sl":  entry_price + atr_sl if is_sell else entry_price - atr_sl,
        "sl_distance":    atr_sl,
        "elite_lot":      0.0,
        "tp_price":       entry_price - atr_sl * rr_ratio if is_sell else entry_price + atr_sl * rr_ratio,
        "in_ote":         True,
        "ote_reason":     "",
        "dxy_bias":       "neutral",
        "sweep_detected": False,
        "sweep_reason":   "",
        "market_state":   "TRENDING",
        "state_mult":     1.0,
        "use_elite_sl":   False,
        "corr_score":     1.0,
        "corr_reason":    "",
        "vol_verdict":    "NEUTRAL",
        "vol_score":      1.0,
        "spread_ok":      True,
        "spread_val":     0.0,
        "notes":          notes,
    }

    try:
        # ── 1. Kill Zone ──────────────────────────────────────────────
        try:
            in_kz, kz_name = is_kill_zone(symbol)
            result["in_kill_zone"]   = in_kz
            result["kill_zone_name"] = kz_name
            notes.append(f"KZ: {'✅ ' + kz_name if in_kz else '⚠️ Outside kill zones'}")
        except Exception as e:
            logger.error("Kill zone check error: %s", e)

        # ── 2. Market State ───────────────────────────────────────────
        try:
            state, ratio = get_market_state(df_4h, symbol)
            mult          = _STATE_LOT_MULT.get(state, 1.0)
            result["market_state"] = state
            result["state_mult"]   = mult
            state_emoji = {"TRENDING": "📈", "CONSOLIDATING": "↔️", "VOLATILE": "⚡"}.get(state, "")
            notes.append(f"Market: {state_emoji} {state} (ATR ratio={ratio:.2f} → lot ×{mult})")
        except Exception as e:
            logger.error("Market state error: %s", e)

        # ── 3. Structural SL ──────────────────────────────────────────
        try:
            sl_price, sl_dist = get_structural_sl(df_4h, direction, entry_price, atr_val, symbol)
            use_elite = sl_dist < atr_sl * 0.95   # at least 5% tighter to switch
            result["structural_sl"] = sl_price
            result["sl_distance"]   = sl_dist
            result["use_elite_sl"]  = use_elite

            if use_elite:
                pct_tighter = (atr_sl - sl_dist) / atr_sl * 100
                tp_price    = entry_price - sl_dist * rr_ratio if is_sell else entry_price + sl_dist * rr_ratio
                result["tp_price"] = tp_price
                notes.append(f"SL: ✅ Structural {sl_dist:.2f} vs ATR {atr_sl:.2f} ({pct_tighter:.0f}% tighter)")
            else:
                notes.append(f"SL: ATR-based {atr_sl:.2f} (structural not tighter)")
        except Exception as e:
            logger.error("Structural SL error: %s", e)

        # ── 4. Elite Lot ──────────────────────────────────────────────
        try:
            lot = elite_lot_size(
                balance, result["sl_distance"], symbol,
                risk_pct, result["state_mult"]
            )
            result["elite_lot"] = lot
            notes.append(f"Lot: {lot}")
        except Exception as e:
            logger.error("Elite lot error: %s", e)

        # ── 5. OTE Zone ───────────────────────────────────────────────
        try:
            in_ote, ote_reason = is_in_ote_zone(df_4h, entry_price, direction)
            result["in_ote"]    = in_ote
            result["ote_reason"] = ote_reason
            notes.append(f"OTE: {'✅ ' + ote_reason if in_ote and ote_reason else ('✅ In zone' if in_ote else '⚠️ ' + ote_reason)}")
        except Exception as e:
            logger.error("OTE error: %s", e)

        # ── 6. DXY (Gold/Silver only) ─────────────────────────────────
        try:
            if symbol.upper().startswith(("XAU", "XAG")):
                dxy = get_dxy_bias()
                result["dxy_bias"] = dxy
                if (dxy == "bullish" and is_sell) or (dxy == "bearish" and not is_sell):
                    notes.append(f"DXY: ✅ {dxy} — confirms {direction.upper()}")
                elif dxy == "neutral":
                    notes.append("DXY: neutral")
                else:
                    notes.append(f"DXY: ⚠️ {dxy} conflicts with {direction.upper()} — trading anyway")
            else:
                result["dxy_bias"] = "N/A"
        except Exception as e:
            logger.error("DXY error: %s", e)

        # ── 7. Liquidity Sweep ────────────────────────────────────────
        try:
            if df_1h is not None:
                sweep, reason = detect_liquidity_sweep(df_1h, direction, symbol)
                result["sweep_detected"] = sweep
                result["sweep_reason"]   = reason
                if sweep:
                    notes.append(f"Sweep: ✅ {reason}")
        except Exception as e:
            logger.error("Sweep error: %s", e)

        # ── 8. Cross-Asset Correlation ────────────────────────────
        try:
            corr_score, corr_reason = get_correlation_score(symbol, direction)
            result["corr_score"]  = corr_score
            result["corr_reason"] = corr_reason
            if corr_reason:
                notes.append(f"Corr: {corr_reason}")
            # Apply correlation score to lot
            if result.get("elite_lot", 0) > 0:
                min_lot = 0.01
                result["elite_lot"] = max(min_lot, round(result["elite_lot"] * corr_score, 2))
        except Exception as e:
            logger.error("Correlation error: %s", e)

        # ── 9. Volume Imbalance ───────────────────────────────────
        try:
            vol_verdict, vol_score, vol_reason = get_volume_imbalance(df_4h, direction, symbol)
            result["vol_verdict"] = vol_verdict
            result["vol_score"]   = vol_score
            if vol_reason:
                notes.append(f"Vol: {vol_reason}")
            if result.get("elite_lot", 0) > 0:
                min_lot = 0.01
                result["elite_lot"] = max(min_lot, round(result["elite_lot"] * vol_score, 2))
        except Exception as e:
            logger.error("Volume imbalance error: %s", e)

        # ── 10. Spread Guard ──────────────────────────────────────
        try:
            # Guess mt5_symbol from symbol name
            mt5_sym_guess = symbol + "m" if not symbol.endswith("m") else symbol
            spread_ok, spread_val, spread_reason = check_spread(symbol, mt5_sym_guess)
            result["spread_ok"]  = spread_ok
            result["spread_val"] = spread_val
            if spread_reason:
                notes.append(f"Spread: {spread_reason}")
        except Exception as e:
            logger.error("Spread guard error: %s", e)

    except Exception as top_exc:
        logger.error("elite_filter top-level error for %s: %s", symbol, top_exc)

    # Summary log
    logger.info(
        "ELITE [%s %s] KZ=%s | State=%s | SL=%s | Lot=%.2f | OTE=%s | DXY=%s | Sweep=%s | Corr=%.1f | Vol=%s | Spread=%.4f",
        direction.upper(), symbol,
        result["kill_zone_name"] or "OUT",
        result["market_state"],
        "STRUCT" if result["use_elite_sl"] else "ATR",
        result["elite_lot"],
        "✅" if result["in_ote"] else "⚠️",
        result["dxy_bias"],
        "✅" if result["sweep_detected"] else "—",
        result["corr_score"],
        result["vol_verdict"],
        result["spread_val"],
    )
    return result
