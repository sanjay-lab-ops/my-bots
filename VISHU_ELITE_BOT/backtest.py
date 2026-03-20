"""
VISHU ELITE BOT — Single-Day Backtest
=======================================
Simulates the full strategy on historical MT5 data for a specific date.

Usage:
  python backtest.py                   ← backtests TODAY
  Set BACKTEST_DATE below for any past date (format: YYYY-MM-DD)

What it does:
  1. Connects to MT5 (must be open + logged in)
  2. Fetches 4H, 1H, 15M, 1M candles
  3. Applies triple-TF bias check (VWAP/PVWAP + EMA20 slope + EMA cross)
  4. Scans 1M candles inside session windows for EMA cross + RSI entry signals
  5. Simulates SL/TP hits with realistic P&L calculation
  6. Prints trade-by-trade report + session summary

Change BACKTEST_DATE to replay any previous day.
"""

import sys
import logging
from datetime import datetime, timezone, timedelta, date
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.WARNING)   # quiet during backtest output

import math
import pandas as pd

from mt5_conn    import connect, disconnect, get_candles
from indicators  import (add_emas, add_vwap, add_pvwap, get_atr_value,
                          get_rsi_value, crossover, crossunder, atr, ema, ema_slope)
from config      import SYMBOLS, SESSIONS, ATR_PERIOD, ATR_SL_MULT, RR_RATIO, MAGIC_NUMBER

# ── BACKTEST SETTINGS — Change these ─────────────────────────────
BACKTEST_DATE     = ""          # Leave blank for today. Or set: "2026-03-15"
STARTING_BALANCE  = 100.0       # Your account balance for P&L calculation
MAX_TRADES_PAIR   = 2           # Maximum trades per pair (mirrors live bot)
# ─────────────────────────────────────────────────────────────────

EMA_FAST = 5
EMA_SLOW = 20
RSI_LOW  = 30
RSI_HIGH = 70


def parse_target_date() -> date:
    """Return the target backtest date."""
    if BACKTEST_DATE:
        return datetime.strptime(BACKTEST_DATE, "%Y-%m-%d").date()
    return datetime.now(timezone.utc).date()


def _in_session(ts_utc, symbol: str) -> bool:
    """Return True if timestamp falls within any session window for symbol."""
    h, m  = ts_utc.hour, ts_utc.minute
    total = h * 60 + m
    for sess in SESSIONS.get(symbol, []):
        sh, sm = sess["start_utc"]
        eh, em = sess["end_utc"]
        if (sh * 60 + sm) <= total <= (eh * 60 + em):
            return True
    return False


def _session_label(ts_utc, symbol: str) -> str:
    """Return session label for timestamp, or empty string."""
    h, m  = ts_utc.hour, ts_utc.minute
    total = h * 60 + m
    for sess in SESSIONS.get(symbol, []):
        sh, sm = sess["start_utc"]
        eh, em = sess["end_utc"]
        if (sh * 60 + sm) <= total <= (eh * 60 + em):
            return sess["label"]
    return ""


def _get_triple_tf_bias(df_4h: pd.DataFrame, df_1h: pd.DataFrame,
                         df_15m: pd.DataFrame, target_date) -> tuple:
    """
    Run triple-TF confluence check for a specific date.
    Returns (bias: str, atr_val: float, details: list[str]).
    """
    details = []

    # ── 4H: VWAP / PVWAP ─────────────────────────────────────────
    df4 = add_vwap(df_4h)
    df4 = add_pvwap(df4)
    df4_day = df4[df4.index.date <= target_date]
    if df4_day.empty:
        return "NEUTRAL", 0.0, ["No 4H data for target date"]

    last_4h   = df4_day.iloc[-1]
    vwap      = float(last_4h.get("vwap",  float("nan")))
    pvwap     = float(last_4h.get("pvwap", float("nan")))
    price_4h  = float(last_4h["close"])

    if math.isnan(vwap) or math.isnan(pvwap):
        return "NEUTRAL", 0.0, ["VWAP/PVWAP not ready — need more 4H history"]

    if price_4h > vwap and price_4h > pvwap:
        bias_4h = "BUY"
    elif price_4h < vwap and price_4h < pvwap:
        bias_4h = "SELL"
    else:
        bias_4h = "NEUTRAL"

    details.append(
        f"4H VWAP bias: {bias_4h} | price={price_4h:.2f}, VWAP={vwap:.2f}, PVWAP={pvwap:.2f}"
    )

    if bias_4h == "NEUTRAL":
        return "NEUTRAL", 0.0, details

    # ── 1H: EMA20 slope ──────────────────────────────────────────
    df1h      = add_emas(df_1h, fast=EMA_FAST, slow=EMA_SLOW)
    df1h_day  = df1h[df1h.index.date <= target_date]
    if df1h_day.empty:
        details.append("1H: No data")
        return "NEUTRAL", 0.0, details

    ema20_s   = df1h_day["ema20"]
    slope_1h  = ema_slope(ema20_s, lookback=3)
    bias_1h   = "BUY" if slope_1h == "rising" else ("SELL" if slope_1h == "falling" else "NEUTRAL")
    details.append(f"1H EMA20 slope: {slope_1h} → bias={bias_1h}")

    if bias_1h != bias_4h:
        return "NEUTRAL", 0.0, details

    # ── 15M: EMA5 vs EMA20 ───────────────────────────────────────
    df15      = add_emas(df_15m, fast=EMA_FAST, slow=EMA_SLOW)
    df15_day  = df15[df15.index.date <= target_date]
    if df15_day.empty:
        details.append("15M: No data")
        return "NEUTRAL", 0.0, details

    last_15m  = df15_day.iloc[-1]
    ema5_15m  = float(last_15m["ema5"])
    ema20_15m = float(last_15m["ema20"])
    bias_15m  = "BUY" if ema5_15m > ema20_15m else "SELL"
    details.append(f"15M EMA5={ema5_15m:.2f} vs EMA20={ema20_15m:.2f} → bias={bias_15m}")

    if bias_15m != bias_4h:
        return "NEUTRAL", 0.0, details

    # ── ATR for SL/TP ─────────────────────────────────────────────
    atr_val = get_atr_value(df4_day, ATR_PERIOD)
    details.append(f"All 3 TF agree: {bias_4h} | 4H ATR={atr_val:.2f}")

    return bias_4h, atr_val, details


def run_backtest_for_symbol(symbol: str, target_date) -> dict:
    """
    Simulate one day of trading for a symbol.
    Returns summary dict.
    """
    sym_cfg       = SYMBOLS.get(symbol, {})
    mt5_sym       = sym_cfg["mt5_symbol"]
    contract_size = sym_cfg["contract_size"]
    atr_min       = sym_cfg.get("atr_min", 0)

    print(f"\n{'═' * 60}")
    print(f"  BACKTEST: {symbol}  |  {target_date}")
    print(f"  MT5 Symbol: {mt5_sym}")
    print(f"  Starting balance: ${STARTING_BALANCE:.2f}")
    print(f"{'═' * 60}")

    # Fetch data — fetch extra history to build valid VWAP/indicators
    df_4h  = get_candles(mt5_sym, "H4",  300)
    df_1h  = get_candles(mt5_sym, "H1",  300)
    df_15m = get_candles(mt5_sym, "M15", 500)
    df_1m  = get_candles(mt5_sym, "M1",  2000)

    if df_1m.empty:
        print(f"  ERROR: No 1M data for {mt5_sym}. Check symbol name in config.py")
        return {"symbol": symbol, "trades": [], "total_pnl": 0.0}

    # Filter 1M data for target date
    df_1m_day = df_1m[df_1m.index.date == target_date]
    if df_1m_day.empty:
        print(f"  No 1M data for {target_date}. Market may have been closed (weekend/holiday).")
        return {"symbol": symbol, "trades": [], "total_pnl": 0.0}

    # Add EMAs to 1M data for cross detection
    df_1m_day = add_emas(df_1m_day, fast=EMA_FAST, slow=EMA_SLOW)

    # ── Triple TF Bias ────────────────────────────────────────────
    bias, atr_val, details = _get_triple_tf_bias(df_4h, df_1h, df_15m, target_date)

    for d in details:
        print(f"  {d}")

    if bias == "NEUTRAL":
        print(f"\n  RESULT: NEUTRAL bias — no trades taken today")
        print(f"{'─' * 60}")
        return {"symbol": symbol, "trades": [], "total_pnl": 0.0}

    # ATR filter
    if atr_val < atr_min:
        print(f"\n  RESULT: ATR={atr_val:.2f} < min={atr_min} — choppy market, skipping")
        print(f"{'─' * 60}")
        return {"symbol": symbol, "trades": [], "total_pnl": 0.0}

    arrow = "BUY ONLY" if bias == "BUY" else "SELL ONLY"
    print(f"\n  Bias    : {bias} ({arrow})")
    print(f"  4H ATR  : {atr_val:.2f}")

    # Lot size from tiers
    balance = STARTING_BALANCE
    if symbol == "BTCUSD":
        if balance <= 100:    lot = 0.01
        elif balance <= 300:  lot = 0.02
        elif balance <= 600:  lot = 0.05
        else:                 lot = 0.10
    else:  # XAUUSD
        if balance <= 200:    lot = 0.01
        elif balance <= 500:  lot = 0.02
        elif balance <= 1000: lot = 0.05
        else:                 lot = 0.10

    print(f"  Lot     : {lot}")
    print()

    # SL/TP distances
    sl_dist = atr_val * ATR_SL_MULT
    tp_dist = sl_dist * RR_RATIO

    # ── Simulate 1M signal scanning ───────────────────────────────
    trades    = []
    in_trade  = False
    trades_count = 0

    buy_cross_s  = crossover(df_1m_day["ema5"], df_1m_day["ema20"])
    sell_cross_s = crossunder(df_1m_day["ema5"], df_1m_day["ema20"])

    for i in range(len(df_1m_day)):
        ts  = df_1m_day.index[i]
        row = df_1m_day.iloc[i]

        # Session check
        if not _in_session(ts, symbol):
            # Close trade if out of session and profitable
            if in_trade:
                current_price = float(row["close"])
                if bias == "BUY":
                    pnl = (current_price - entry_price) * lot * contract_size
                else:
                    pnl = (entry_price - current_price) * lot * contract_size
                if pnl > 0:
                    trades[-1].update({
                        "Exit Time":  ts.strftime("%H:%M UTC"),
                        "Exit Price": round(current_price, 2),
                        "Result":     "SESSION END",
                        "Profit":     round(pnl, 2),
                    })
                    balance  += pnl
                    in_trade  = False
            continue

        sess_label = _session_label(ts, symbol)
        price = float(row["close"])

        if not in_trade:
            if trades_count >= MAX_TRADES_PAIR:
                continue

            # Check RSI filter
            rsi_val = get_rsi_value(df_1m_day.iloc[:i+1], period=14)

            triggered = (
                (bias == "BUY"  and bool(buy_cross_s.iloc[i])  and RSI_LOW <= rsi_val <= RSI_HIGH) or
                (bias == "SELL" and bool(sell_cross_s.iloc[i]) and RSI_LOW <= rsi_val <= RSI_HIGH)
            )

            if triggered:
                entry_price = price
                decimals    = 2 if "XAU" in symbol else 1
                if bias == "BUY":
                    sl = round(entry_price - sl_dist, decimals)
                    tp = round(entry_price + tp_dist, decimals)
                else:
                    sl = round(entry_price + sl_dist, decimals)
                    tp = round(entry_price - tp_dist, decimals)

                in_trade      = True
                trades_count += 1

                trades.append({
                    "Session":    sess_label,
                    "Entry Time": ts.strftime("%H:%M UTC"),
                    "Action":     bias,
                    "Entry":      round(entry_price, 2),
                    "SL":         sl,
                    "TP":         tp,
                    "Lot":        lot,
                    "RSI":        round(rsi_val, 1),
                    "Exit Time":  "—",
                    "Exit Price": "—",
                    "Result":     "open",
                    "Profit":     0.0,
                })
                print(
                    f"  ENTRY {bias} @ {entry_price:.2f} | {ts.strftime('%H:%M UTC')} | "
                    f"RSI={rsi_val:.1f} | SL={sl:.2f} | TP={tp:.2f}"
                )

        else:
            # Check SL/TP
            high = float(row["high"])
            low  = float(row["low"])

            if bias == "BUY":
                if low <= sl:
                    pnl = (sl - entry_price) * lot * contract_size
                    trades[-1].update({
                        "Exit Time":  ts.strftime("%H:%M UTC"),
                        "Exit Price": sl,
                        "Result":     "LOSS",
                        "Profit":     round(pnl, 2),
                    })
                    balance  += pnl
                    in_trade  = False
                    print(f"  SL HIT @ {sl:.2f} | {ts.strftime('%H:%M UTC')} | P&L={pnl:+.2f}")
                elif high >= tp:
                    pnl = (tp - entry_price) * lot * contract_size
                    trades[-1].update({
                        "Exit Time":  ts.strftime("%H:%M UTC"),
                        "Exit Price": tp,
                        "Result":     "WIN",
                        "Profit":     round(pnl, 2),
                    })
                    balance  += pnl
                    in_trade  = False
                    print(f"  TP HIT @ {tp:.2f} | {ts.strftime('%H:%M UTC')} | P&L=+{pnl:.2f}")

            else:  # SELL
                if high >= sl:
                    pnl = (entry_price - sl) * lot * contract_size
                    trades[-1].update({
                        "Exit Time":  ts.strftime("%H:%M UTC"),
                        "Exit Price": sl,
                        "Result":     "LOSS",
                        "Profit":     round(pnl, 2),
                    })
                    balance  += pnl
                    in_trade  = False
                    print(f"  SL HIT @ {sl:.2f} | {ts.strftime('%H:%M UTC')} | P&L={pnl:+.2f}")
                elif low <= tp:
                    pnl = (entry_price - tp) * lot * contract_size
                    trades[-1].update({
                        "Exit Time":  ts.strftime("%H:%M UTC"),
                        "Exit Price": tp,
                        "Result":     "WIN",
                        "Profit":     round(pnl, 2),
                    })
                    balance  += pnl
                    in_trade  = False
                    print(f"  TP HIT @ {tp:.2f} | {ts.strftime('%H:%M UTC')} | P&L=+{pnl:.2f}")

    # If still in trade at EOD, mark as open
    if in_trade and trades:
        last_price = float(df_1m_day["close"].iloc[-1])
        if bias == "BUY":
            pnl = (last_price - entry_price) * lot * contract_size
        else:
            pnl = (entry_price - last_price) * lot * contract_size
        trades[-1].update({
            "Exit Time":  "EOD (open)",
            "Exit Price": round(last_price, 2),
            "Result":     f"OPEN ({'+' if pnl >= 0 else ''}{pnl:.2f})",
            "Profit":     round(pnl, 2),
        })

    # ── Print Summary ─────────────────────────────────────────────
    total_pnl = sum(t["Profit"] for t in trades)
    wins      = sum(1 for t in trades if t["Result"] == "WIN")
    losses    = sum(1 for t in trades if t["Result"] == "LOSS")
    open_cnt  = sum(1 for t in trades if str(t["Result"]).startswith("OPEN"))

    if not trades:
        print(f"\n  No entry signals fired during session windows.")
    else:
        print(f"\n{'─' * 60}")
        df_trades = pd.DataFrame(trades)
        cols = ["Session", "Entry Time", "Action", "Entry", "SL", "TP",
                "Lot", "RSI", "Exit Time", "Exit Price", "Result", "Profit"]
        print(df_trades[cols].to_string(index=False))
        print(f"\n{'─' * 60}")

    print(f"  Trades     : {len(trades)}")
    print(f"  Wins       : {wins}   Losses: {losses}   Open: {open_cnt}")
    win_rate = (wins / len(trades) * 100) if trades else 0
    print(f"  Win Rate   : {win_rate:.1f}%")
    print(f"  Net P&L    : ${total_pnl:+.2f}")
    print(f"  End Balance: ${STARTING_BALANCE + total_pnl:.2f}")
    print(f"{'═' * 60}")

    return {"symbol": symbol, "trades": trades, "total_pnl": total_pnl}


def main():
    target_date = parse_target_date()

    print(f"\n{'█' * 60}")
    print(f"  VISHU ELITE BOT — BACKTEST")
    print(f"  Date: {target_date}")
    print(f"  Strategy: 4H VWAP/PVWAP + 1H EMA20 slope + 15M EMA cross")
    print(f"  Entry: 1M EMA5/EMA20 cross + RSI[30-70] filter")
    print(f"{'█' * 60}")

    print("\nConnecting to MT5...")
    if not connect():
        print("ERROR: Cannot connect to MT5. Make sure:")
        print("  1. MetaTrader 5 is open and logged in")
        print("  2. Your .env file has correct MT5_LOGIN, MT5_PASSWORD, MT5_SERVER")
        sys.exit(1)

    results = []
    for symbol in SYMBOLS:
        result = run_backtest_for_symbol(symbol, target_date)
        results.append(result)

    # ── Overall summary ───────────────────────────────────────────
    total_all   = sum(r["total_pnl"] for r in results)
    total_trades = sum(len(r["trades"]) for r in results)
    print(f"\n{'█' * 60}")
    print(f"  OVERALL BACKTEST RESULT — {target_date}")
    print(f"  Total trades : {total_trades}")
    print(f"  Combined P&L : ${total_all:+.2f}")
    print(f"  Start balance: ${STARTING_BALANCE:.2f}")
    print(f"  End balance  : ${STARTING_BALANCE + total_all:.2f}")
    print(f"{'█' * 60}")

    print("\n  HOW TO VERIFY:")
    print("  Open TradingView → set chart to 1-minute")
    print(f"  Navigate to {target_date}")
    print("  Look for EMA5/EMA20 crossovers during session windows")
    print("  Compare entry/exit prices with what bot found\n")

    disconnect()


if __name__ == "__main__":
    main()
