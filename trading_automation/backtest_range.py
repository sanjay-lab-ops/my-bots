"""
Date range backtest — runs strategy over multiple days and shows
full P&L summary with per-day and per-pair breakdown.

Edit START_DATE and END_DATE below, then run:
  python backtest_range.py
"""

import logging
import sys
from datetime import datetime, timezone, timedelta, date
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.WARNING)

import pandas as pd
import numpy as np

from mt5_connector import connect, disconnect, get_candles
from indicators    import full_analysis, add_emas, crossover, crossunder
from risk_engine   import calculate_lot, calculate_sl_tp
from config        import SYMBOLS, SESSIONS, UTBOT_ATR_PERIOD, \
                           TRAILING_STOP_ENABLED, BREAKEVEN_AT_PCT, TRAIL_START_PCT, TRAIL_ATR_MULT, \
                           CARRY_TO_LAST_SESSION, LAST_SESSION_END

# ── Date range to backtest ───────────────────────────────────────
START_DATE = date(2026, 3, 19)   # Thursday 19 Mar (testing starts)
END_DATE   = date(2026, 3, 31)   # Monday 31 Mar
# Change these to any dates you want

STARTING_BALANCE = 50.0


def get_date_range(start: date, end: date):
    dates = []
    d = start
    while d <= end:
        dates.append(d)   # include ALL days — weekends needed for BTC
        d += timedelta(days=1)
    return dates


def run_single_day(symbol: str, target_date: date, df_4h, df_1h, df_15m, df_1m_all, balance: float):
    """
    Run strategy for one symbol on one date.
    Returns list of trade dicts.
    """
    from day_filter import get_day_info
    mt5_symbol = SYMBOLS[symbol]["mt5_symbol"]

    # Day filter — for backtest we still run to see signals, but mark the day
    should_trade, day_lot_mult, day_reason = get_day_info(target_date, symbol=symbol)
    if not should_trade:
        # For XAUUSD on weekends, truly skip (no market data exists)
        import calendar
        weekday = target_date.weekday()
        if symbol == "XAUUSD" and weekday in {5, 6}:
            return []
        # For Monday (day_filter skip): run with half lot so we can see signals
        day_lot_mult = 0.5

    # Filter 1m candles for this date
    df_1m_day = df_1m_all[df_1m_all.index.date == target_date]
    if df_1m_day.empty:
        return []

    # 4H bias — last candle on or before target date
    df_4h_filtered = df_4h[df_4h.index.date <= target_date]
    if df_4h_filtered.empty:
        return []
    last_4h  = df_4h_filtered.iloc[-1]

    import math
    vwap     = last_4h.get("vwap",  float("nan"))
    pvwap    = last_4h.get("pvwap", float("nan"))
    price_4h = last_4h["close"]

    if math.isnan(vwap) or math.isnan(pvwap):
        return []

    if price_4h > vwap and price_4h > pvwap:
        bias = "buy"
    elif price_4h < vwap and price_4h < pvwap:
        bias = "sell"
    else:
        return []   # neutral — no trade

    from indicators import atr as calc_atr
    atr_val = calc_atr(df_4h_filtered, UTBOT_ATR_PERIOD).iloc[-1]

    trade_lot     = calculate_lot(balance, symbol, atr_4h=atr_val)
    contract_size = SYMBOLS[symbol].get("contract_size", 1)

    df_1m_day = add_emas(df_1m_day)
    buy_cross  = crossover(df_1m_day["ema5"], df_1m_day["ema20"])
    sell_cross = crossunder(df_1m_day["ema5"], df_1m_day["ema20"])

    trades   = []
    in_trade = False
    entry_price = sl = tp = 0.0
    trail_sl    = None   # active trailing SL (None = not yet triggered)
    breakeven_done = False

    for i in range(len(df_1m_day)):
        ts  = df_1m_day.index[i]
        h   = ts.hour
        m   = ts.minute
        tot = h * 60 + m

        # ── Determine session state ───────────────────────────────
        in_session  = False
        current_sess_end = None
        for sess in SESSIONS.get(symbol, []):
            sh, sm = sess["start_utc"]
            eh, em = sess["end_utc"]
            if (sh * 60 + sm) <= tot <= (eh * 60 + em):
                in_session = True
                current_sess_end = eh * 60 + em
                break

        # Last session end for this symbol today
        lh, lm   = LAST_SESSION_END.get(symbol, (23, 59))
        last_end = lh * 60 + lm
        is_last_close = (tot == last_end)

        row   = df_1m_day.iloc[i]
        price = row["close"]
        high  = row["high"]
        low   = row["low"]

        # ── Close logic ───────────────────────────────────────────
        if in_trade and trades:
            if CARRY_TO_LAST_SESSION:
                # Close only at last session end of the day
                if is_last_close:
                    if bias == "buy":
                        pnl = (price - entry_price) * trade_lot * contract_size
                    else:
                        pnl = (entry_price - price) * trade_lot * contract_size
                    trades[-1].update({
                        "Exit Time": ts.strftime("%H:%M"),
                        "Exit":      round(price, 2),
                        "Result":    "DAY-END",
                        "Profit":    round(pnl, 2),
                    })
                    in_trade = False
                    continue
            else:
                # Original: close at end of each session
                if in_session and tot == current_sess_end:
                    if bias == "buy":
                        pnl = (price - entry_price) * trade_lot * contract_size
                    else:
                        pnl = (entry_price - price) * trade_lot * contract_size
                    trades[-1].update({
                        "Exit Time": ts.strftime("%H:%M"),
                        "Exit":      round(price, 2),
                        "Result":    "SES-END",
                        "Profit":    round(pnl, 2),
                    })
                    in_trade = False
                    continue

        # ── Only look for new entries during a session ────────────
        if not in_session:
            continue

        if not in_trade:
            triggered = (bias == "buy"  and buy_cross.iloc[i]) or \
                        (bias == "sell" and sell_cross.iloc[i])
            if triggered:
                entry_price = price
                sl, tp = calculate_sl_tp(bias, entry_price, atr_val, symbol)
                in_trade = True
                trail_sl = None
                breakeven_done = False
                weekday    = target_date.weekday()
                day_names  = ["MON*", "TUE", "WED", "THU", "FRI~", "SAT~", "SUN~"]
                day_label  = day_names[weekday]
                trades.append({
                    "Date":       str(target_date),
                    "Day":        day_label,
                    "Pair":       symbol,
                    "Bias":       bias.upper(),
                    "Entry Time": ts.strftime("%H:%M UTC"),
                    "Action":     bias.upper(),
                    "Entry":      round(entry_price, 2),
                    "SL":         round(sl, 2),
                    "TP":         round(tp, 2),
                    "Lot":        trade_lot,
                    "Exit Time":  "—",
                    "Exit":       "—",
                    "Result":     "open",
                    "Profit":     0.0,
                })
        else:
            tp_distance = abs(tp - entry_price)

            # ── Trailing stop logic ──────────────────────────────
            if TRAILING_STOP_ENABLED and tp_distance > 0:
                if bias == "buy":
                    moved = high - entry_price
                else:
                    moved = entry_price - low

                pct_to_tp = moved / tp_distance if tp_distance > 0 else 0

                # Step 1: move SL to breakeven at 50% of TP
                if not breakeven_done and pct_to_tp >= BREAKEVEN_AT_PCT:
                    sl = entry_price
                    breakeven_done = True

                # Step 2: start trailing at 75% of TP
                if pct_to_tp >= TRAIL_START_PCT:
                    trail_dist = atr_val * TRAIL_ATR_MULT
                    if bias == "buy":
                        new_trail = high - trail_dist
                        if trail_sl is None or new_trail > trail_sl:
                            trail_sl = new_trail
                        sl = max(sl, trail_sl)   # SL only moves up for buys
                    else:
                        new_trail = low + trail_dist
                        if trail_sl is None or new_trail < trail_sl:
                            trail_sl = new_trail
                        sl = min(sl, trail_sl)   # SL only moves down for sells

            # ── Check SL / TP hits ───────────────────────────────
            if bias == "buy":
                if low <= sl:
                    pnl = (sl - entry_price) * trade_lot * contract_size
                    result_label = "TRAIL" if (breakeven_done or trail_sl) else "LOSS"
                    trades[-1].update({"Exit Time": ts.strftime("%H:%M"), "Exit": round(sl, 2),
                                       "Result": result_label, "Profit": round(pnl, 2)})
                    in_trade = False
                elif high >= tp:
                    pnl = (tp - entry_price) * trade_lot * contract_size
                    trades[-1].update({"Exit Time": ts.strftime("%H:%M"), "Exit": tp,
                                       "Result": "WIN", "Profit": round(pnl, 2)})
                    in_trade = False
            else:
                if high >= sl:
                    pnl = (entry_price - sl) * trade_lot * contract_size
                    result_label = "TRAIL" if (breakeven_done or trail_sl) else "LOSS"
                    trades[-1].update({"Exit Time": ts.strftime("%H:%M"), "Exit": round(sl, 2),
                                       "Result": result_label, "Profit": round(pnl, 2)})
                    in_trade = False
                elif low <= tp:
                    pnl = (entry_price - tp) * trade_lot * contract_size
                    trades[-1].update({"Exit Time": ts.strftime("%H:%M"), "Exit": tp,
                                       "Result": "WIN", "Profit": round(pnl, 2)})
                    in_trade = False

    # Any trade still open means it ran past session end without being caught
    # (e.g. no 1m candle exactly at session end) — close at last available price
    if in_trade and trades:
        last_close = df_1m_day["close"].iloc[-1]
        if bias == "buy":
            pnl = (last_close - entry_price) * trade_lot * contract_size
        else:
            pnl = (entry_price - last_close) * trade_lot * contract_size
        label = "DAY-END" if CARRY_TO_LAST_SESSION else "SES-END"
        trades[-1].update({
            "Exit Time": label,
            "Exit":      round(last_close, 2),
            "Result":    label,
            "Profit":    round(pnl, 2),
        })

    return trades


def run_for_balance(dates, candle_data, starting_balance):
    """Run full backtest for one starting balance. candle_data = {symbol: (df_4h,df_1h,df_15m,df_1m)}"""
    all_trades = []
    balance    = starting_balance

    for symbol in ["BTCUSD", "XAUUSD"]:
        if symbol not in candle_data:
            continue
        df_4h, df_1h, df_15m, df_1m = candle_data[symbol]
        for d in dates:
            day_trades = run_single_day(symbol, d, df_4h, df_1h, df_15m, df_1m, balance)
            for t in day_trades:
                balance += t["Profit"]
            all_trades.extend(day_trades)

    return all_trades


def print_results(all_trades, starting_balance, dates):
    if not all_trades:
        print("  No trades found.")
        return

    df  = pd.DataFrame(all_trades)
    sep = "═" * 76

    print(sep)
    print(f"  TRADE-BY-TRADE  |  Start: ${starting_balance:.0f}  |  {START_DATE} to {END_DATE}")
    print(sep)
    print("  * MON = live bot SKIPS   ~ FRI/SAT/SUN = half lot")
    print()
    print(df[["Date","Day","Pair","Action","Entry Time","Entry","SL","TP","Lot",
              "Exit Time","Exit","Result","Profit"]].to_string(index=False))

    print(f"\n  DAILY SUMMARY")
    print("  " + "─" * 74)
    day_quality = {0:"MON[SKIP]", 1:"TUE[BEST]", 2:"WED[BEST]",
                   3:"THU[GOOD]", 4:"FRI[HALF]", 5:"SAT[BTC]", 6:"SUN[BTC]"}
    for d in dates:
        day_df  = df[df["Date"] == str(d)]
        quality = day_quality[d.weekday()]
        if day_df.empty:
            print(f"  {d} {quality:10} | No signals")
            continue
        pnl    = day_df["Profit"].sum()
        wins    = (day_df["Result"] == "WIN").sum()
        losses  = (day_df["Result"] == "LOSS").sum()
        trails  = (day_df["Result"] == "TRAIL").sum()
        dayend  = (day_df["Result"] == "DAY-END").sum()
        sesend  = (day_df["Result"] == "SES-END").sum()
        print(f"  {d} {quality:10} | T:{len(day_df)} W:{wins} L:{losses} Trail:{trails} DayEnd:{dayend+sesend} | P&L: ${pnl:+.2f}")

    total_pnl = df["Profit"].sum()
    wins      = (df["Result"] == "WIN").sum()
    losses    = (df["Result"] == "LOSS").sum()
    trails    = (df["Result"] == "TRAIL").sum()
    day_ends  = (df["Result"].isin(["DAY-END","SES-END"])).sum()
    closed    = wins + losses + trails
    win_rate  = (wins + trails) / closed * 100 if closed else 0
    carry_mode = "CARRY (holds till day end)" if CARRY_TO_LAST_SESSION else "SESSION-CLOSE (closes each session)"

    print(f"\n  Mode: {carry_mode}")
    print(f"  OVERALL  |  Trades:{len(df)}  Wins:{wins}  Trails:{trails}  Losses:{losses}  DayEnd:{day_ends}")
    print(f"  Win+Trail rate : {win_rate:.1f}%")
    print(f"  Total P&L      : ${total_pnl:+.2f}")
    print(f"  Start balance  : ${starting_balance:.2f}")
    print(f"  End balance    : ${starting_balance + total_pnl:.2f}  ({total_pnl/starting_balance*100:+.1f}%)")
    print(sep)


def run():
    print("\n  Connecting to MT5...")
    if not connect():
        print("  Cannot connect to MT5.")
        sys.exit(1)

    dates = get_date_range(START_DATE, END_DATE)
    print(f"\n  Fetching candle data for {START_DATE} to {END_DATE}...")

    # Fetch candles once — reused for all 3 balance runs
    candle_data = {}
    for symbol in ["BTCUSD", "XAUUSD"]:
        mt5_sym = SYMBOLS[symbol]["mt5_symbol"]
        df_4h  = full_analysis(get_candles(mt5_sym, "H4",  300))
        df_1h  = full_analysis(get_candles(mt5_sym, "H1",  300))
        df_15m = full_analysis(get_candles(mt5_sym, "M15", 800))
        df_1m  = get_candles(mt5_sym, "M1", 4000)
        if df_1m.empty:
            print(f"  No data for {mt5_sym}")
            continue
        candle_data[symbol] = (df_4h, df_1h, df_15m, df_1m)

    disconnect()

    if not candle_data:
        print("  No candle data fetched. Check MT5 connection.")
        return

    # ── Run for all 3 starting balances ──────────────────────────
    BIG_SEP = "█" * 76
    for bal in [50.0, 200.0, 500.0]:
        print(f"\n\n{BIG_SEP}")
        print(f"  STARTING BALANCE: ${bal:.0f}")
        print(BIG_SEP)
        trades = run_for_balance(dates, candle_data, bal)
        print_results(trades, bal, dates)

    # ── Final comparison summary ──────────────────────────────────
    print(f"\n\n{'═'*76}")
    print(f"  COMPARISON SUMMARY  |  {START_DATE} to {END_DATE}")
    print(f"{'═'*76}")
    print(f"  {'Balance':>10}  {'End Balance':>12}  {'Profit':>10}  {'Return':>8}  {'Gold traded?':>14}")
    print(f"  {'─'*10}  {'─'*12}  {'─'*10}  {'─'*8}  {'─'*14}")
    for bal in [50.0, 200.0, 500.0]:
        trades = run_for_balance(dates, candle_data, bal)
        if not trades:
            print(f"  ${bal:>9.0f}  {'No trades':>12}")
            continue
        total_pnl   = sum(t["Profit"] for t in trades)
        gold_traded = any(t["Pair"] == "XAUUSD" and t["Lot"] > 0 for t in trades)
        ret_pct     = total_pnl / bal * 100
        print(f"  ${bal:>9.0f}  ${bal+total_pnl:>11.2f}  ${total_pnl:>+9.2f}  {ret_pct:>+7.1f}%  {'YES' if gold_traded else 'NO (need $335+)':>14}")
    print(f"{'═'*76}")


if __name__ == "__main__":
    run()
