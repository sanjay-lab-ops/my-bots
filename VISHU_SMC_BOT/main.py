"""
VISHU SMC BOT — Main Loop
Institutional Smart Money Concepts Trading Bot

How this differs from retail:
  RETAIL: Buys when price is high, chases breakouts, gets stopped out by institutions
  THIS BOT: Identifies where institutions placed orders (Order Blocks), places LIMIT
            orders there at the SAME price as BlackRock, then rides the institutional move.

Runs 24/7 — no session limits. Trades all 4 pairs whenever a valid signal appears.
Compounds capital automatically — 1.5% risk grows with every winning trade.
"""

import time
import logging
import sys
import json
import os
from datetime import datetime, timezone, timedelta

# Cross-bot race prevention
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cross_bot_lock import claim as _cb_claim, confirm as _cb_confirm, release as _cb_release

_PLACED_FILE     = os.path.join(os.path.dirname(__file__), "placed_today.json")
_MILESTONE_FILE  = os.path.join(os.path.dirname(__file__), "milestones_today.json")

def _load_milestones() -> set:
    """Load today's already-sent milestone levels. Resets daily."""
    try:
        with open(_MILESTONE_FILE) as f:
            data = json.load(f)
        if data.get("date") == datetime.now(timezone.utc).strftime("%Y-%m-%d"):
            return set(data.get("levels", []))
    except Exception:
        pass
    return set()

def _save_milestones(levels: set):
    try:
        with open(_MILESTONE_FILE, "w") as f:
            json.dump({"date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                       "levels": list(levels)}, f)
    except Exception:
        pass

def _load_placed() -> set:
    """Load today's placed symbols from disk. Returns empty set if file is stale or missing."""
    try:
        with open(_PLACED_FILE) as f:
            data = json.load(f)
        if data.get("date") == datetime.now(timezone.utc).strftime("%Y-%m-%d"):
            return set(data.get("symbols", []))
    except Exception:
        pass
    return set()

def _save_placed(placed: set):
    """Persist placed symbols to disk with today's date."""
    try:
        with open(_PLACED_FILE, "w") as f:
            json.dump({"date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                       "symbols": list(placed)}, f)
    except Exception:
        pass

logging.basicConfig(
    filename="smc_bot.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

from config import SYMBOLS, DAILY_LOSS_LIMIT, RR_RATIO, SL_BUFFER_PCT, ATR_PERIOD, MANUAL_MODE, SESSIONS, MIN_BALANCE_TO_TRADE
import telegram_commands
from telegram_commands import load_forced_bias, is_paused

def _in_session(symbol: str, now_utc: datetime) -> bool:
    """Return True if current UTC time falls within any session window for this symbol."""
    windows = SESSIONS.get(symbol, [])
    h, m = now_utc.hour, now_utc.minute
    now_mins = h * 60 + m
    for w in windows:
        s = w["start_utc"]; e = w["end_utc"]
        start_mins = s[0] * 60 + s[1]
        end_mins   = e[0] * 60 + e[1]
        if start_mins <= now_mins < end_mins:
            return True
    return False
from mt5_conn import (connect, disconnect, reconnect, get_candles,
                      get_account_balance, get_day_pnl, get_open_positions, get_pending_orders)
from indicators import atr as calc_atr
from market_structure import analyze_structure
from order_blocks import find_order_blocks, find_nearest_ob
from fvg import find_fvgs, find_nearest_fvg
from liquidity import find_liquidity_pools, find_tp_target
from compounding import (load_balance, save_balance, calculate_lot,
                          update_after_trade, get_compound_stats)
from executor import place_limit_order, place_market_order, cancel_pending_order
from trade_manager import manage_trades, cancel_stale_pending_orders, snapshot_positions, detect_closed_positions
from news_filter import is_news_window, is_pre_news_accumulation
import telegram_notify as tg
from elite_execution import elite_filter, get_market_state, is_kill_zone, detect_liquidity_sweep

IST = timedelta(hours=5, minutes=30)
logger = logging.getLogger("main")


def ist_time() -> str:
    return (datetime.now(timezone.utc) + IST).strftime("%H:%M IST")


def print_header(balance: float, stats: dict):
    now_ist = (datetime.now(timezone.utc) + IST).strftime("%d %b %Y %H:%M IST")
    sep = "═" * 64
    print(f"\n{sep}")
    print(f"  VISHU SMC BOT — Smart Money Concepts")
    print(f"  {now_ist}")
    print(f"  Balance : ${balance:.2f}  |  Total growth: +{stats.get('total_pnl_pct', 0):.1f}%")
    print(f"  Pairs   : BTC · ETH · XAU · XAG  |  Running 24/7")
    print(sep)


def run():
    print("\n  Connecting to MT5...")
    if not connect():
        print("  Cannot connect to MT5. Check .env credentials.")
        sys.exit(1)

    balance    = load_balance() or get_account_balance()
    stats      = get_compound_stats()
    last_saved = get_account_balance()

    # If no compound file yet, initialise it
    if not stats:
        save_balance(balance)
        stats = get_compound_stats()

    print_header(balance, stats)
    # Command listener disabled — Bot 2 handles all Telegram commands
    # telegram_commands.start()
    tg.bot_started(balance, stats.get("total_pnl_pct", 0))

    last_day        = datetime.now(timezone.utc).date()
    day_trades      = 0
    placed_this_run = _load_placed()   # persists across restarts — survives crashes
    prev_milestones = _load_milestones()  # persists across restarts — no duplicate alerts

    while True:
        try:
            now_utc   = datetime.now(timezone.utc)
            now_ist   = now_utc + IST

            # ── Midnight UTC reset ───────────────────────────────────
            if now_utc.date() != last_day:
                # Sync balance from MT5 at day start
                balance        = get_account_balance()
                save_balance(balance)
                stats          = get_compound_stats()
                day_pnl        = get_day_pnl()
                day_trades     = 0
                placed_this_run.clear()
                _save_placed(placed_this_run)
                prev_milestones.clear()
                _save_milestones(prev_milestones)
                logger.info("Midnight reset — placed_this_run + milestones cleared")
                last_day      = now_utc.date()

                tg.daily_summary(
                    day_pnl=day_pnl,
                    balance=balance,
                    total_pct=stats.get("total_pnl_pct", 0),
                    win_rate=stats.get("win_rate", 0),
                    trades=stats.get("total_trades", 0),
                )
                print(f"\n  [{ist_time()}] New day — balance ${balance:.2f}")

            # ── EOD close at 16:00 UTC (21:30 IST) — close all, cancel all pending ──
            if now_utc.hour == 16 and now_utc.minute == 0:
                import MetaTrader5 as _mt5eod
                print(f"\n  [{ist_time()}] EOD 21:30 IST — closing all positions and pending orders")
                _all_pos = _mt5eod.positions_get() or []
                for _pos in _all_pos:
                    _dir_type = _mt5eod.ORDER_TYPE_SELL if _pos.type == 0 else _mt5eod.ORDER_TYPE_BUY
                    _tick = _mt5eod.symbol_info_tick(_pos.symbol)
                    if _tick:
                        _price = _tick.bid if _pos.type == 0 else _tick.ask
                        _req = {
                            "action":    _mt5eod.TRADE_ACTION_DEAL,
                            "position":  _pos.ticket,
                            "symbol":    _pos.symbol,
                            "volume":    _pos.volume,
                            "type":      _dir_type,
                            "price":     _price,
                            "deviation": 30,
                            "magic":     _pos.magic,
                            "comment":   "EOD-close",
                            "type_time": _mt5eod.ORDER_TIME_GTC,
                            "type_filling": _mt5eod.ORDER_FILLING_IOC,
                        }
                        _res = _mt5eod.order_send(_req)
                        if _res and _res.retcode == _mt5eod.TRADE_RETCODE_DONE:
                            print(f"    EOD CLOSED | {_pos.symbol} | P&L={_pos.profit:.2f}")
                _all_orders = _mt5eod.orders_get() or []
                for _ord in _all_orders:
                    _mt5eod.order_send({"action": _mt5eod.TRADE_ACTION_REMOVE, "order": _ord.ticket})
                    print(f"    EOD CANCELLED | Pending #{_ord.ticket}")
                tg.daily_summary(
                    day_pnl=get_day_pnl(), balance=get_account_balance(),
                    total_pct=stats.get("total_pnl_pct", 0),
                    win_rate=stats.get("win_rate", 0),
                    trades=stats.get("total_trades", 0),
                )
                print(f"  [{ist_time()}] EOD done — sleeping until midnight.")
                time.sleep(3600)
                continue

            # ── Daily loss limit check ───────────────────────────────
            day_pnl = get_day_pnl()
            balance  = get_account_balance()

            if day_pnl <= -(balance * abs(DAILY_LOSS_LIMIT)):
                print(f"  [{ist_time()}] ⚠️ Daily loss limit reached (${day_pnl:.2f}) — DEMO MODE: continuing anyway.")
                tg.daily_loss_limit(balance)
                # Demo mode: log warning but do NOT stop trading

            # ── Compound milestone check ─────────────────────────────
            total_pct = stats.get("total_pnl_pct", 0)
            for milestone in [10, 25, 50, 100, 200, 500]:
                if total_pct >= milestone and milestone not in prev_milestones:
                    tg.compound_milestone(balance, total_pct)
                    prev_milestones.add(milestone)
                    _save_milestones(prev_milestones)

            # ── Detect SL/TP closes from last tick ──────────────────
            all_open = get_open_positions()
            current_tickets = {p["ticket"] for p in all_open}
            sl_hit = detect_closed_positions(current_tickets, tg=tg)
            for sym in sl_hit:
                if sym in placed_this_run:
                    placed_this_run.discard(sym)
                    _save_placed(placed_this_run)
                    logger.info("SL hit on %s — re-entry unlocked for today", sym)
                    print(f"    {sym}: SL hit — re-entry unlocked")
            for sym in ["BTCUSD", "ETHUSD", "XAUUSD", "XAGUSD"]:
                mt5s = SYMBOLS[sym]["mt5_symbol"]
                snapshot_positions(sym, [p for p in all_open if p["symbol"] == mt5s])

            # ── Cancel stale pending orders ──────────────────────────
            cancel_stale_pending_orders(max_age_minutes=240)

            # ── Pre-news accumulation check ──────────────────────────
            pre_news, pre_news_event, hrs_to = is_pre_news_accumulation()
            if pre_news:
                print(f"  [{ist_time()}] PRE-NEWS WINDOW: {pre_news_event} in {hrs_to}h "
                      f"— scanning aggressively like institutions")
                atr_relax = 0.5   # relax ATR minimum by 50% — institutions accumulate quietly
            else:
                atr_relax = 1.0   # normal ATR filter

            # ── Pause check ──────────────────────────────────────────
            if is_paused():
                print(f"  [{ist_time()}] ⏸ Bot PAUSED — managing open positions only")
                continue

            # ── Scan each pair ───────────────────────────────────────
            print(f"\n  [{ist_time()}] Scanning 4 pairs... Balance=${balance:.2f}")

            # ETH/BTC and XAG/XAU correlation trackers
            _btc_smc_direction = None
            _xau_smc_direction = None

            for symbol in ["BTCUSD", "ETHUSD", "XAUUSD", "XAGUSD"]:
                cfg     = SYMBOLS[symbol]
                mt5_sym = cfg["mt5_symbol"]

                # Bot 3 is 24/7 — no session filter, SMC scans all hours

                # Balance protection — skip if account too small for this symbol
                min_bal = MIN_BALANCE_TO_TRADE.get(symbol, 0)
                if balance < min_bal:
                    print(f"    {symbol}: Balance ${balance:.2f} < ${min_bal} minimum — skipping (protect live account)")
                    continue

                # News filter
                news_blocked, news_reason = is_news_window(symbol)
                if news_blocked:
                    print(f"    {symbol}: News — {news_reason}")
                    continue

                # Cross-bot: check if ANY bot has a position on this symbol
                import MetaTrader5 as _mt5x
                all_pos_sym = _mt5x.positions_get(symbol=mt5_sym) or []
                if all_pos_sym:
                    # Cancel any of our own pending orders for this symbol
                    _pend = [o for o in get_pending_orders() if o["symbol"] == mt5_sym]
                    for _po in _pend:
                        cancel_pending_order(_po["ticket"])
                        print(f"    {symbol}: Cancelled pending #{_po['ticket']} — live position exists")
                    # Manage if it's our own position
                    open_pos = [p for p in get_open_positions() if p["symbol"] == mt5_sym]
                    if open_pos:
                        df_h4 = get_candles(mt5_sym, "H4", 30)
                        if df_h4 is not None and not df_h4.empty:
                            atr_v  = calc_atr(df_h4, ATR_PERIOD).iloc[-1]
                            pos    = open_pos[0]
                            direct = "buy" if pos["type"] == 0 else "sell"
                            manage_trades(symbol, atr_v, direct, tg=tg,
                                         balance_ref=[balance])
                        print(f"    {symbol}: Managing open position (P&L: ${open_pos[0]['profit']:.2f})")
                    else:
                        print(f"    {symbol}: Cross-bot position open — skipping")
                    continue

                # Already placed for this symbol in this run session?
                if symbol in placed_this_run:
                    continue

                # Already have a pending limit order for this symbol?
                pending = [o for o in get_pending_orders() if o["symbol"] == mt5_sym]
                if pending:
                    import MetaTrader5 as _mt5_mod
                    tick    = _mt5_mod.symbol_info_tick(mt5_sym)
                    cur     = tick.bid if tick else 0
                    o       = pending[0]
                    gap     = abs(cur - o["price"])
                    gap_pct = (gap / cur * 100) if cur else 0
                    order_type = "BUY LIMIT" if o["type"] == 2 else "SELL LIMIT"
                    age_m   = int((datetime.now(timezone.utc) - o["time"]).total_seconds() / 60)
                    print(f"    {symbol}: ⏳ {order_type} @ {o['price']:.3f} | "
                          f"Current={cur:.3f} | Gap={gap:.2f} ({gap_pct:.1f}% away) | "
                          f"SL={o['sl']:.3f} TP={o['tp']:.3f} | Age={age_m}min")
                    continue

                # ── Fetch data ───────────────────────────────────────
                df_h4  = get_candles(mt5_sym, "H4",  300)   # 300 = ~50 days, enough for swing detection
                df_h1  = get_candles(mt5_sym, "H1",  200)

                if df_h4 is None or df_h4.empty or df_h1 is None or df_h1.empty:
                    print(f"    {symbol}: No data — check symbol name in config.py")
                    continue

                atr_val = calc_atr(df_h4, ATR_PERIOD).iloc[-1]

                # ATR volatility filter (relaxed during pre-news accumulation window)
                atr_threshold = cfg["atr_min"] * atr_relax
                if atr_val < atr_threshold:
                    print(f"    {symbol}: ATR {atr_val:.2f} < {atr_threshold:.2f} — too choppy"
                          + (" (pre-news relaxed)" if pre_news else ""))
                    continue

                # ── Market structure ─────────────────────────────────
                structure = analyze_structure(df_h4)
                trend     = structure["trend"]

                if trend == "ranging":
                    print(f"    {symbol}: Ranging — no trade ({structure['structure_note']})")
                    continue

                # Skip if CHoCH detected — structure is breaking, wait for clarity
                if structure["choch"]:
                    print(f"    {symbol}: CHoCH detected — waiting for new structure")
                    continue

                direction = "buy" if trend == "bullish" else "sell"
                forced = load_forced_bias().get(symbol, "auto").lower()
                if forced != "auto":
                    direction = forced
                    print(f"    {symbol}: FORCED_BIAS={forced.upper()} override applied")
                else:
                    print(f"    {symbol}: {trend.upper()} | {structure['structure_note']}")

                # ETH/BTC and XAG/XAU correlation filters
                if symbol == "BTCUSD":
                    _btc_smc_direction = direction
                elif symbol == "ETHUSD" and _btc_smc_direction and direction != _btc_smc_direction:
                    print(f"    ETHUSD: CORRELATION SKIP — BTC={_btc_smc_direction.upper()} "
                          f"but ETH={direction.upper()} — skipping")
                    continue
                _xag_smc_divergence = False
                if symbol == "XAUUSD":
                    _xau_smc_direction = direction
                elif symbol == "XAGUSD" and _xau_smc_direction and direction != _xau_smc_direction:
                    _xag_smc_divergence = True
                    print(f"    XAGUSD: DIVERGENCE — XAU={_xau_smc_direction.upper()} "
                          f"but XAG={direction.upper()} — trading min lot 0.01")

                # ── Counter-trend bounce check ───────────────────────
                # When price sweeps a major swing low/high (liquidity grab),
                # a bounce trade in the opposite direction (fixed 0.01 lot only)
                # can capture the move back to the OB before the trend resumes.
                import MetaTrader5 as _mt5chk
                _tick       = _mt5chk.symbol_info_tick(mt5_sym)
                _cur_price  = _tick.bid if _tick else df_h4["close"].iloc[-1]
                _swing_low  = structure.get("last_sl", 0) or 0
                _swing_high = structure.get("last_sh", 0) or 0
                _bounce_dir = None

                # BULLISH trend: if price swept above swing high → bounce SELL
                if direction == "buy" and _swing_high > 0:
                    sweep_dist_up = _cur_price - _swing_high
                    if 0 < sweep_dist_up < atr_val * 1.0:
                        _bear_obs = find_order_blocks(df_h4, "bearish")
                        _bear_ob  = find_nearest_ob(_bear_obs, _cur_price, "sell")
                        if _bear_ob and abs(_bear_ob["mid"] - _cur_price) < atr_val * 3:
                            _bounce_sl2   = _cur_price + atr_val * 0.8
                            _bounce_tp2   = _bear_ob["mid"]
                            _bounce_rr2   = abs(_cur_price - _bounce_tp2) / abs(_bounce_sl2 - _cur_price)
                            if _bounce_rr2 >= 1.5:
                                print(f"    {symbol}: BOUNCE SELL detected | "
                                      f"Entry={_cur_price:.2f} SL={_bounce_sl2:.2f} "
                                      f"TP={_bounce_tp2:.2f} RR=1:{_bounce_rr2:.1f} | Lot=0.01 (fixed)")
                                _b2 = place_market_order(symbol, "sell", 0.01,
                                                         _bounce_sl2, _bounce_tp2,
                                                         comment="SMC-BOUNCE")
                                if _b2:
                                    tg.trade_opened(symbol, "SELL (BOUNCE)", 0.01,
                                                    _cur_price, _bounce_sl2, _bounce_tp2)
                                    print(f"    {symbol}: ✅ Bounce SELL #{_b2} filled")

                # BEARISH trend: if price swept below swing low by > 0.5× ATR → bounce BUY
                if direction == "sell" and _swing_low > 0:
                    sweep_dist = _swing_low - _cur_price
                    if 0 < sweep_dist < atr_val * 1.0:   # swept low, not too far
                        # Find bullish OB above current price as bounce target
                        _bull_obs = find_order_blocks(df_h4, "bullish")
                        _bull_ob  = find_nearest_ob(_bull_obs, _cur_price, "buy")
                        if _bull_ob and abs(_bull_ob["mid"] - _cur_price) < atr_val * 3:
                            _bounce_dir    = "buy"
                            _bounce_entry  = _cur_price
                            _bounce_sl     = _cur_price - atr_val * 0.8
                            _bounce_tp     = _bull_ob["mid"]
                            _bounce_rr     = abs(_bounce_tp - _bounce_entry) / abs(_bounce_entry - _bounce_sl)
                            if _bounce_rr >= 1.5:
                                print(f"    {symbol}: BOUNCE BUY detected | "
                                      f"Entry={_bounce_entry:.2f} SL={_bounce_sl:.2f} "
                                      f"TP={_bounce_tp:.2f} RR=1:{_bounce_rr:.1f} | Lot=0.01 (fixed)")
                                _b_ticket = place_market_order(symbol, "buy", 0.01,
                                                               _bounce_sl, _bounce_tp,
                                                               comment="SMC-BOUNCE")
                                if _b_ticket:
                                    tg.trade_opened(symbol, "BUY (BOUNCE)", 0.01,
                                                    _bounce_entry, _bounce_sl, _bounce_tp)
                                    print(f"    {symbol}: ✅ Bounce BUY #{_b_ticket} filled")

                # ── Order block detection ────────────────────────────
                obs        = find_order_blocks(df_h4, trend)
                nearest_ob = find_nearest_ob(obs, df_h4["close"].iloc[-1], direction)

                # ── FVG detection (H1 for precision) ─────────────────
                fvgs       = find_fvgs(df_h1)
                nearest_fvg = find_nearest_fvg(fvgs, df_h1["close"].iloc[-1], direction)

                # ── Select entry level ───────────────────────────────
                entry_price = None
                entry_reason = ""
                ob_top = ob_bottom = None

                if nearest_ob:
                    entry_price  = nearest_ob["mid"]
                    ob_top       = nearest_ob["top"]
                    ob_bottom    = nearest_ob["bottom"]
                    entry_reason = f"OB strength {nearest_ob['strength']}/3"
                elif nearest_fvg:
                    entry_price  = nearest_fvg["mid"]
                    ob_top       = nearest_fvg["top"]
                    ob_bottom    = nearest_fvg["bottom"]
                    entry_reason = "FVG fill"
                else:
                    print(f"    {symbol}: No OB or FVG near current price — skip")
                    continue

                # ── SL/TP ────────────────────────────────────────────
                if direction == "buy":
                    sl = ob_bottom * (1 - SL_BUFFER_PCT / 100) if ob_bottom else entry_price - atr_val * 1.5
                    sl_dist = entry_price - sl
                else:
                    sl = ob_top * (1 + SL_BUFFER_PCT / 100) if ob_top else entry_price + atr_val * 1.5
                    sl_dist = sl - entry_price

                if sl_dist <= 0:
                    print(f"    {symbol}: Invalid SL distance — skip")
                    continue

                # TP: nearest liquidity pool, fallback to ATR-based RR
                liquidity = find_liquidity_pools(df_h4)
                tp        = find_tp_target(liquidity, direction, entry_price)

                # Validate RR — if liquidity TP gives poor RR, use ATR-based target instead
                if tp:
                    actual_rr = abs(tp - entry_price) / sl_dist if sl_dist > 0 else 0
                    if actual_rr < 1.5:
                        # Override with ATR-based TP for minimum 2.5:1
                        tp = (entry_price + sl_dist * RR_RATIO
                              if direction == "buy"
                              else entry_price - sl_dist * RR_RATIO)
                        print(f"    {symbol}: Liquidity TP RR too low — using ATR TP {tp:.3f}")
                else:
                    tp = (entry_price + sl_dist * RR_RATIO
                          if direction == "buy"
                          else entry_price - sl_dist * RR_RATIO)

                actual_rr = abs(tp - entry_price) / sl_dist if sl_dist > 0 else 0

                # ── Lot size (compounding) ───────────────────────────
                lot = calculate_lot(balance, sl_dist, symbol)
                if lot <= 0:
                    print(f"    {symbol}: Account too small — skip")
                    continue
                # XAG divergence from XAU — cap at min lot to limit risk
                if symbol == "XAGUSD" and _xag_smc_divergence:
                    lot = cfg.get("min_lot", 0.01)
                    print(f"    {symbol}: DIVERGENCE LOT CAP → 0.01 (XAU disagreement)")

                # ── Elite: Kill zone + Market state + Sweep check ────────
                try:
                    in_kz, kz_name = is_kill_zone(mt5_sym)
                    state, s_ratio = get_market_state(df_h4, symbol)
                    sweep, sw_msg  = detect_liquidity_sweep(df_h1, direction, symbol)
                    state_emoji    = {"TRENDING": "📈", "CONSOLIDATING": "↔️", "VOLATILE": "⚡"}.get(state, "")
                    print(f"    {symbol}: {state_emoji} {state} | "
                          f"{'✅ KZ:'+kz_name if in_kz else '⚠️ Outside KZ'} | "
                          f"{'🎯 SWEEP ENTRY' if sweep else 'Limit entry'}")
                    if sweep:
                        print(f"    {symbol}: {sw_msg}")

                    # ── Kill zone gate — no new trades in dead zones ──────
                    # Dead zones: 05:00-07:00 UTC, 12:00-13:00 UTC, 17:00-24:00 UTC
                    # Trades placed in dead zones get caught by bank manipulation at next open.
                    # Only allow entry during kill zones OR if a liquidity sweep is detected.
                    if not in_kz and not sweep:
                        print(f"    {symbol}: ⏳ Outside kill zone — waiting for KZ (no dead zone entries)")
                        continue

                    # Adjust lot for market state
                    state_mult = {"TRENDING": 1.0, "CONSOLIDATING": 0.7, "VOLATILE": 1.2}.get(state, 1.0)
                    lot = round(lot * state_mult, 2)
                    lot = max(cfg.get("min_lot", 0.01), lot)
                except Exception as _elite_e:
                    logger.warning("Elite check error (non-critical): %s", _elite_e)

                # ── Smart entry: OB pullback vs momentum market entry ───
                import MetaTrader5 as _mt5mod
                tick        = _mt5mod.symbol_info_tick(mt5_sym)
                current_px  = tick.bid if tick else entry_price
                ob_distance = abs(entry_price - current_px)
                use_market  = False

                # If OB is more than 2× ATR away AND price is already moving
                # strongly in the right direction → enter at market (momentum entry)
                if ob_distance > atr_val * 2:
                    if direction == "sell" and current_px < entry_price:
                        use_market   = True
                        entry_reason += " [MOMENTUM — OB too far, market entry]"
                    elif direction == "buy" and current_px > entry_price:
                        use_market   = True
                        entry_reason += " [MOMENTUM — OB too far, market entry]"

                if use_market:
                    # Recalculate SL/TP from current price for market entry
                    if direction == "sell":
                        sl = current_px + atr_val * 1.5
                        tp = current_px - atr_val * 1.5 * RR_RATIO
                    else:
                        sl = current_px - atr_val * 1.5
                        tp = current_px + atr_val * 1.5 * RR_RATIO
                    sl_dist   = abs(current_px - sl)
                    actual_rr = abs(tp - current_px) / sl_dist if sl_dist > 0 else 0
                    lot       = calculate_lot(balance, sl_dist, symbol)
                    if lot <= 0:
                        print(f"    {symbol}: Account too small for market entry — skip")
                        continue
                    print(f"    {symbol}: {direction.upper()} MARKET @ {current_px:.3f} | "
                          f"SL={sl:.3f} TP={tp:.3f} | Lot={lot} | RR=1:{actual_rr:.1f} | {entry_reason}")
                    if MANUAL_MODE:
                        # Cross-bot check — skip if any position already open
                        import MetaTrader5 as _mt5c
                        _existing = _mt5c.positions_get(symbol=symbol+"m") or []
                        if _existing:
                            print(f"    {symbol}: Cross-bot position open — skipping signal")
                            continue
                        tg.notify_bot_signal(symbol, direction, current_px, sl, tp, lot, f"BOT3 SMC | {entry_reason}")
                        placed_this_run.add(symbol); _save_placed(placed_this_run)
                        print(f"    {symbol}: ⏳ Signal sent to Telegram (MANUAL_MODE)")
                        continue
                    if not _cb_claim(symbol, "BOT3"):
                        print(f"    {symbol}: SKIP — cross-bot lock active (another bot placing)")
                        continue
                    ticket = place_market_order(symbol, direction, lot, sl, tp,
                                                comment="SMC-MOMENTUM")
                    if ticket:
                        _cb_confirm(symbol, ticket, "BOT3")
                        # Cancel any pending limit orders for this symbol now that market order is live
                        _pend2 = [o for o in get_pending_orders() if o["symbol"] == mt5_sym]
                        for _po2 in _pend2:
                            cancel_pending_order(_po2["ticket"])
                            print(f"    {symbol}: Cancelled pending #{_po2['ticket']} — market order filled")
                        tg.trade_opened(symbol, direction.upper(), lot, current_px, sl, tp)
                        day_trades += 1
                        placed_this_run.add(symbol); _save_placed(placed_this_run)
                        print(f"    {symbol}: ✅ Market order #{ticket} filled")
                    else:
                        _cb_release(symbol)
                        print(f"    {symbol}: ❌ Market order failed")
                else:
                    print(f"    {symbol}: {direction.upper()} LIMIT @ {entry_price:.3f} | "
                          f"SL={sl:.3f} TP={tp:.3f} | Lot={lot} | RR=1:{actual_rr:.1f} | {entry_reason}")
                    if MANUAL_MODE:
                        # Cross-bot check — skip if any position already open
                        import MetaTrader5 as _mt5c
                        _existing = _mt5c.positions_get(symbol=symbol+"m") or []
                        if _existing:
                            print(f"    {symbol}: Cross-bot position open — skipping signal")
                            continue
                        tg.notify_bot_signal(symbol, direction, entry_price, sl, tp, lot, f"BOT3 SMC LIMIT | {entry_reason}")
                        placed_this_run.add(symbol); _save_placed(placed_this_run)
                        print(f"    {symbol}: ⏳ Signal sent to Telegram (MANUAL_MODE)")
                        continue
                    if not _cb_claim(symbol, "BOT3"):
                        print(f"    {symbol}: SKIP — cross-bot lock active (another bot placing)")
                        continue
                    ticket = place_limit_order(
                        symbol, direction, lot,
                        entry_price, sl, tp,
                        comment=f"SMC-{entry_reason[:8]}"
                    )
                    if ticket:
                        _cb_confirm(symbol, ticket, "BOT3")
                        tg.limit_order_placed(symbol, direction, lot, entry_price, sl, tp, entry_reason)
                        day_trades += 1
                        placed_this_run.add(symbol); _save_placed(placed_this_run)
                        print(f"    {symbol}: ✅ Limit order #{ticket} placed")
                    else:
                        _cb_release(symbol)
                        print(f"    {symbol}: ❌ Limit order failed")

            # ── Update balance from MT5 after each scan ──────────────
            mt5_balance = get_account_balance()
            if abs(mt5_balance - balance) > 0.01:
                profit_diff = mt5_balance - balance
                balance     = mt5_balance
                save_balance(balance)
                stats       = get_compound_stats()

            time.sleep(60)

        except KeyboardInterrupt:
            print("\n  Bot stopped.")
            balance = get_account_balance()
            stats   = get_compound_stats()
            tg.daily_summary(
                day_pnl=get_day_pnl(),
                balance=balance,
                total_pct=stats.get("total_pnl_pct", 0),
                win_rate=stats.get("win_rate", 0),
                trades=stats.get("total_trades", 0),
            )
            break

        except Exception as e:
            logger.error("Main loop error: %s", e, exc_info=True)
            print(f"  Error: {e} — reconnecting...")
            try:
                reconnect()
            except Exception:
                pass
            time.sleep(30)

    disconnect()


if __name__ == "__main__":
    run()
