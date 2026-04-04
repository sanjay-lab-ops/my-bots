"""
VISHU SMC BOT -- Single Day Backtest

Change BACKTEST_DATE to test any day.
Shows: OB detected, limit order level, whether TP/SL was hit, P&L.
"""

import sys
import logging
from datetime import date, datetime, timezone, timedelta

logging.basicConfig(level=logging.WARNING)

from config import SYMBOLS, RR_RATIO, SL_BUFFER_PCT, ATR_PERIOD
from mt5_conn import connect, disconnect, get_candles
from indicators import atr as calc_atr
from market_structure import analyze_structure
from order_blocks import find_order_blocks, find_nearest_ob
from fvg import find_fvgs, find_nearest_fvg
from liquidity import find_liquidity_pools, find_tp_target
from compounding import calculate_lot

# -- Change this to backtest any date ------------------------------
BACKTEST_DATE    = date(2026, 3, 18)   # YYYY, M, D
STARTING_BALANCE = 20.0
# -----------------------------------------------------------------


def run_backtest():
    print(f"\n{'='*64}")
    print(f"  VISHU SMC BOT -- BACKTEST: {BACKTEST_DATE}")
    print(f"  Starting balance: ${STARTING_BALANCE:.2f}")
    print(f"{'='*64}")

    if not connect():
        print("  Cannot connect to MT5.")
        sys.exit(1)

    all_trades = []
    balance    = STARTING_BALANCE

    for symbol in ["BTCUSD", "ETHUSD", "XAUUSD", "XAGUSD"]:
        cfg     = SYMBOLS[symbol]
        mt5_sym = cfg["mt5_symbol"]

        print(f"\n  Analysing {symbol}...")

        df_h4 = get_candles(mt5_sym, "H4",  200)
        df_h1 = get_candles(mt5_sym, "H1",  300)
        df_1m = get_candles(mt5_sym, "M1",  2000)  # intraday for execution

        if df_h4 is None or df_h4.empty:
            print(f"    No H4 data for {mt5_sym}")
            continue

        atr_val = calc_atr(df_h4, ATR_PERIOD).iloc[-1]
        if atr_val < cfg["atr_min"]:
            print(f"    ATR {atr_val:.2f} < min {cfg['atr_min']} -- skip")
            continue

        structure = analyze_structure(df_h4)
        trend     = structure["trend"]
        if trend == "ranging":
            print(f"    Ranging market -- no trade")
            continue

        direction = "buy" if trend == "bullish" else "sell"
        print(f"    Structure: {trend.upper()} | {structure['structure_note']}")

        obs     = find_order_blocks(df_h4, trend)
        ob      = find_nearest_ob(obs, df_h4["close"].iloc[-1], direction)
        fvgs    = find_fvgs(df_h1) if df_h1 is not None else []
        fvg     = find_nearest_fvg(fvgs, df_h1["close"].iloc[-1] if df_h1 is not None else 0, direction)

        entry_price = None
        entry_reason = ""
        ob_top = ob_bottom = None

        if ob:
            entry_price  = ob["mid"]
            ob_top       = ob["top"]
            ob_bottom    = ob["bottom"]
            entry_reason = f"OB str={ob['strength']}"
        elif fvg:
            entry_price  = fvg["mid"]
            ob_top       = fvg["top"]
            ob_bottom    = fvg["bottom"]
            entry_reason = "FVG"
        else:
            print(f"    No OB or FVG near price -- no trade")
            continue

        if direction == "buy":
            sl      = ob_bottom * (1 - SL_BUFFER_PCT / 100)
            sl_dist = entry_price - sl
        else:
            sl      = ob_top * (1 + SL_BUFFER_PCT / 100)
            sl_dist = sl - entry_price

        if sl_dist <= 0:
            print(f"    Invalid SL -- skip")
            continue

        liq = find_liquidity_pools(df_h4)
        tp  = find_tp_target(liq, direction, entry_price)
        if not tp:
            tp = (entry_price + sl_dist * RR_RATIO
                  if direction == "buy"
                  else entry_price - sl_dist * RR_RATIO)

        lot = calculate_lot(balance, sl_dist, symbol)
        if lot <= 0:
            print(f"    Lot = 0, skip")
            continue

        print(f"    OB/FVG: {entry_price:.3f} | SL={sl:.3f} | TP={tp:.3f} | Lot={lot} | {entry_reason}")

        # Simulate on 1m data for BACKTEST_DATE
        result = "open"
        pnl    = 0.0
        exit_p = entry_price
        exit_t = "--"

        if df_1m is not None and not df_1m.empty:
            day_1m  = df_1m[df_1m.index.date == BACKTEST_DATE]
            touched = False

            for i, (ts, row) in enumerate(day_1m.iterrows()):
                if not touched:
                    # Check if price returned to OB (limit fill)
                    if direction == "buy" and row["low"] <= entry_price:
                        touched = True
                    elif direction == "sell" and row["high"] >= entry_price:
                        touched = True
                    continue

                # In trade -- check SL/TP
                if direction == "buy":
                    if row["low"] <= sl:
                        pnl    = (sl - entry_price) * lot * cfg["contract_size"]
                        result = "LOSS"
                        exit_p = sl
                        exit_t = ts.strftime("%H:%M")
                        break
                    elif row["high"] >= tp:
                        pnl    = (tp - entry_price) * lot * cfg["contract_size"]
                        result = "WIN"
                        exit_p = tp
                        exit_t = ts.strftime("%H:%M")
                        break
                else:
                    if row["high"] >= sl:
                        pnl    = (entry_price - sl) * lot * cfg["contract_size"]
                        result = "LOSS"
                        exit_p = sl
                        exit_t = ts.strftime("%H:%M")
                        break
                    elif row["low"] <= tp:
                        pnl    = (entry_price - tp) * lot * cfg["contract_size"]
                        result = "WIN"
                        exit_p = tp
                        exit_t = ts.strftime("%H:%M")
                        break

            if result == "open" and touched:
                last_close = day_1m["close"].iloc[-1] if not day_1m.empty else entry_price
                if direction == "buy":
                    pnl = (last_close - entry_price) * lot * cfg["contract_size"]
                else:
                    pnl = (entry_price - last_close) * lot * cfg["contract_size"]
                result = "EOD"
                exit_p = last_close
                exit_t = "EOD"
            elif not touched:
                result = "NO FILL"
                print(f"    Price never returned to OB -- no fill on {BACKTEST_DATE}")

        balance += pnl
        trade = {
            "Pair":    symbol,
            "Action":  direction.upper(),
            "Reason":  entry_reason,
            "Limit@":  entry_price,
            "SL":      sl,
            "TP":      tp,
            "Lot":     lot,
            "Exit":    exit_p,
            "ExitT":   exit_t,
            "Result":  result,
            "P&L":     round(pnl, 2),
        }
        all_trades.append(trade)

    disconnect()

    if not all_trades:
        print("\n  No trades found.")
        return

    sep = "=" * 64
    print(f"\n{sep}")
    print(f"  RESULTS -- {BACKTEST_DATE}")
    print(sep)
    for t in all_trades:
        emoji = "" if t["Result"] == "WIN" else ("" if t["Result"] == "LOSS" else "")
        sign  = "+" if t["P&L"] >= 0 else ""
        print(f"  {emoji} {t['Pair']:8} {t['Action']:5} | "
              f"Limit@{t['Limit@']:.2f} SL={t['SL']:.2f} TP={t['TP']:.2f} | "
              f"Lot={t['Lot']} | Exit={t['Exit']:.2f}({t['ExitT']}) | "
              f"{t['Result']:8} | P&L: {sign}${t['P&L']:.2f}")

    total_pnl = sum(t["P&L"] for t in all_trades)
    wins      = sum(1 for t in all_trades if t["Result"] == "WIN")
    losses    = sum(1 for t in all_trades if t["Result"] == "LOSS")
    print(f"\n  {'-'*50}")
    sign = "+" if total_pnl >= 0 else ""
    print(f"  Total P&L  : {sign}${total_pnl:.2f}")
    print(f"  Wins/Losses: {wins}/{losses}")
    print(f"  End balance: ${STARTING_BALANCE + total_pnl:.2f}")
    print(sep)


if __name__ == "__main__":
    run_backtest()
