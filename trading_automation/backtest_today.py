"""
Today's backtest — runs your full strategy on today's historical data
from MT5 and prints a trade-by-trade report.

Run: python backtest_today.py
"""

import logging
import sys
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.WARNING)   # quiet during backtest

import MetaTrader5 as mt5
import pandas as pd

from mt5_connector import connect, disconnect, get_candles
from indicators import full_analysis, add_emas, crossover, crossunder
from risk_engine import calculate_lot, calculate_sl_tp
from config import SYMBOLS, SESSIONS, UTBOT_ATR_PERIOD, ATR_SL_MULTIPLIER, RR_RATIO

STARTING_BALANCE  = 50.0   # change to your demo balance
BACKTEST_DAYS_AGO = 0      # 0 = today, 1 = yesterday, 2 = 2 days ago


def session_bars(df: pd.DataFrame, symbol: str) -> list:
    """Return indices of bars that fall inside session windows (UTC)."""
    result = []
    for i, ts in enumerate(df.index):
        h   = ts.hour
        m   = ts.minute
        tot = h * 60 + m
        for sess in SESSIONS.get(symbol, []):
            sh, sm = sess["start_utc"]
            eh, em = sess["end_utc"]
            if (sh * 60 + sm) <= tot <= (eh * 60 + em):
                result.append(i)
                break
    return result


def run_backtest(symbol: str):
    mt5_symbol = SYMBOLS[symbol]["mt5_symbol"]

    from datetime import timedelta
    target_date = (datetime.now(timezone.utc) - timedelta(days=BACKTEST_DAYS_AGO)).date()
    label = "TODAY" if BACKTEST_DAYS_AGO == 0 else f"YESTERDAY ({target_date})" if BACKTEST_DAYS_AGO == 1 else str(target_date)

    print(f"\n{'═'*55}")
    print(f"  BACKTEST: {symbol}  |  {label}")
    print(f"  Starting balance: ${STARTING_BALANCE:.2f}")
    print(f"{'═'*55}")

    # Fetch enough history to cover target date
    df_4h  = get_candles(mt5_symbol, "H4",  200)
    df_1h  = get_candles(mt5_symbol, "H1",  200)
    df_15m = get_candles(mt5_symbol, "M15", 500)
    df_1m  = get_candles(mt5_symbol, "M1",  2000)

    if df_1m.empty:
        print(f"  No data for {mt5_symbol}. Check symbol name in config.py")
        return

    # Run indicators
    df_4h  = full_analysis(df_4h)
    df_1h  = full_analysis(df_1h)
    df_15m = full_analysis(df_15m)
    df_1m  = add_emas(df_1m)

    # Filter target date's 1m candles
    from datetime import timedelta
    target_date = (datetime.now(timezone.utc) - timedelta(days=BACKTEST_DAYS_AGO)).date()
    df_1m_today = df_1m[df_1m.index.date == target_date]

    if df_1m_today.empty:
        print(f"  No 1-minute data for {target_date}. Market may have been closed.")
        return

    # 4H bias — use last 4H candle before/on target date
    df_4h_filtered = df_4h[df_4h.index.date <= target_date]
    if df_4h_filtered.empty:
        print("  No 4H data for target date.")
        return
    last_4h = df_4h_filtered.iloc[-1]
    vwap    = last_4h.get("vwap", float("nan"))
    pvwap   = last_4h.get("pvwap", float("nan"))
    price_4h = last_4h["close"]

    import math
    if math.isnan(vwap) or math.isnan(pvwap):
        print("  VWAP not ready. Run bot on a live session instead.")
        return

    if price_4h > vwap and price_4h > pvwap:
        bias = "buy"
    elif price_4h < vwap and price_4h < pvwap:
        bias = "sell"
    else:
        bias = "neutral"
        print(f"  4H bias is NEUTRAL (price between VWAP and PVWAP). No trades today.")
        return

    from indicators import atr as calc_atr
    atr_series = calc_atr(df_4h, UTBOT_ATR_PERIOD)
    true_atr   = atr_series.iloc[-1]

    bias_arrow = "▲ ONLY BUY ALLOWED" if bias == "buy" else "▼ ONLY SELL ALLOWED"
    print(f"  4H Bias : {bias.upper()}  ←  {bias_arrow}")
    print(f"  VWAP    : {vwap:.2f}   PVWAP: {pvwap:.2f}   Price: {price_4h:.2f}")
    print(f"  ATR(4H) : {true_atr:.2f}")
    print(f"  ⚠  Any trade opposite to bias = guaranteed higher risk of loss")
    print()

    # Simulate 1m signals
    trades = []
    balance = STARTING_BALANCE
    in_trade = False
    entry_price = sl = tp = 0.0
    trade_lot     = calculate_lot(balance, symbol, atr_4h=atr_val)
    contract_size = SYMBOLS[symbol].get("contract_size", 1)
    from indicators import atr as calc_atr
    atr_val = calc_atr(df_4h, UTBOT_ATR_PERIOD).iloc[-1]

    buy_cross_series  = crossover(df_1m_today["ema5"], df_1m_today["ema20"])
    sell_cross_series = crossunder(df_1m_today["ema5"], df_1m_today["ema20"])

    for i in range(len(df_1m_today)):
        ts    = df_1m_today.index[i]
        h, m  = ts.hour, ts.minute
        tot   = h * 60 + m

        # Check session
        in_session = False
        for sess in SESSIONS.get(symbol, []):
            sh, sm = sess["start_utc"]
            eh, em = sess["end_utc"]
            if (sh * 60 + sm) <= tot <= (eh * 60 + em):
                in_session = True
                break

        if not in_session:
            continue

        row   = df_1m_today.iloc[i]
        price = row["close"]

        if not in_trade:
            # Look for entry
            triggered = (bias == "buy"  and buy_cross_series.iloc[i]) or \
                        (bias == "sell" and sell_cross_series.iloc[i])

            if triggered:
                entry_price = price
                sl, tp      = calculate_sl_tp(bias, entry_price, atr_val, symbol)
                in_trade    = True
                trades.append({
                    "Entry Time": ts.strftime("%H:%M UTC"),
                    "Action":     bias.upper(),
                    "Entry":      entry_price,
                    "SL":         sl,
                    "TP":         tp,
                    "Lot":        trade_lot,
                    "Exit Time":  "—",
                    "Exit Price": "—",
                    "Result":     "open",
                    "Profit":     0.0,
                })
        else:
            # Check SL/TP hit
            high = row["high"]
            low  = row["low"]

            if bias == "buy":
                if low <= sl:
                    pnl = (sl - entry_price) * trade_lot * contract_size
                    trades[-1].update({"Exit Time": ts.strftime("%H:%M"), "Exit Price": sl,
                                       "Result": "LOSS", "Profit": round(pnl, 2)})
                    balance += pnl
                    in_trade = False
                elif high >= tp:
                    pnl = (tp - entry_price) * trade_lot * contract_size
                    trades[-1].update({"Exit Time": ts.strftime("%H:%M"), "Exit Price": tp,
                                       "Result": "WIN", "Profit": round(pnl, 2)})
                    balance += pnl
                    in_trade = False
            else:  # sell
                if high >= sl:
                    pnl = (entry_price - sl) * trade_lot * contract_size
                    trades[-1].update({"Exit Time": ts.strftime("%H:%M"), "Exit Price": sl,
                                       "Result": "LOSS", "Profit": round(pnl, 2)})
                    balance += pnl
                    in_trade = False
                elif low <= tp:
                    pnl = (entry_price - tp) * trade_lot * contract_size
                    trades[-1].update({"Exit Time": ts.strftime("%H:%M"), "Exit Price": tp,
                                       "Result": "WIN", "Profit": round(pnl, 2)})
                    balance += pnl
                    in_trade = False

    if not trades:
        print("  No entry signals fired during today's sessions.")
        return

    # Drop trades still open (not yet hit SL or TP) — only show closed results
    closed_trades = [t for t in trades if t["Result"] != "open"]
    if not closed_trades:
        print("  Signals fired but no trades closed yet (session still active).")
        print("  Run again after session ends to see final results.")
        return
    trades = closed_trades

    # For still-open trades, calculate unrealized P&L using end-of-day close
    last_close = df_1m_today["close"].iloc[-1]
    last_high  = df_1m_today["high"].max()
    last_low   = df_1m_today["low"].min()

    for t in trades:
        if t["Result"] == "open":
            ep = t["Entry"]
            if t["Action"] == "BUY":
                unrealized = (last_close - ep) * t["Lot"] * 100
                max_profit = (last_high - ep) * t["Lot"] * 100
                max_loss   = (last_low  - ep) * t["Lot"] * 100
            else:
                unrealized = (ep - last_close) * t["Lot"] * 100
                max_profit = (ep - last_low)   * t["Lot"] * 100
                max_loss   = (ep - last_high)  * t["Lot"] * 100
            t["Exit Time"]  = "EOD"
            t["Exit Price"] = round(last_close, 2)
            t["Profit"]     = round(unrealized, 2)
            t["Result"]     = f"OPEN ({'+' if unrealized>=0 else ''}{unrealized:.2f})"
            t["Max Profit"] = round(max_profit, 2)
            t["Max Loss"]   = round(max_loss, 2)
        else:
            t["Max Profit"] = "—"
            t["Max Loss"]   = "—"

    df_trades = pd.DataFrame(trades)
    wins      = df_trades["Result"].str.startswith("WIN").sum()
    losses    = df_trades["Result"].str.startswith("LOSS").sum()
    total_pnl = df_trades["Profit"].sum()
    win_rate  = wins / len(df_trades) * 100 if len(df_trades) else 0

    print(df_trades[[
        "Entry Time","Action","Entry","SL","TP","Lot","Exit Time","Exit Price","Result","Profit","Max Profit","Max Loss"
    ]].to_string(index=False))

    sep = "─" * 55
    print(f"\n{sep}")
    print(f"  Total signals  : {len(df_trades)}")
    print(f"  Wins           : {wins}   Losses: {losses}   Still open: {(df_trades['Result'].str.startswith('OPEN')).sum()}")
    print(f"  Win rate       : {win_rate:.1f}%")
    print(f"  Net P&L        : ${total_pnl:+.2f}")
    print(f"  End-of-day px  : {last_close:.2f}")
    print(f"  Day High       : {last_high:.2f}   Day Low: {last_low:.2f}")
    print(f"  Ending balance : ${balance + total_pnl:.2f}")
    print(f"{sep}")
    print(f"  HOW TO VERIFY MANUALLY:")
    print(f"  Open TradingView → set chart to 1min → go to {target_date}")
    print(f"  Check if price moved from entry toward TP or SL")
    print(f"{sep}\n")


if __name__ == "__main__":
    print("\n  Connecting to MT5...")
    if not connect():
        print("  Cannot connect to MT5. Make sure MT5 is open and your .env is filled in.")
        sys.exit(1)

    for sym in ["BTCUSD", "XAUUSD"]:
        run_backtest(sym)

    disconnect()
