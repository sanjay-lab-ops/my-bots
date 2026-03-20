"""
Vishu Trading Bot — Main Entry Point
=====================================
Run this file to start the bot: python main.py

What happens every 60 seconds:
  1. Check if we're inside a trading session
  2. Check news filter — skip if high-impact event
  3. Fetch candles for all timeframes
  4. Run full strategy (UTBot + Elder Impulse + VWAP + EMA cross)
  5. If signal fires → calculate lot size + SL/TP → execute trade
  6. Print daily report at midnight UTC
"""

import os
import sys
import time
import logging
import schedule
from datetime import datetime, timezone
from dotenv import load_dotenv

# Cross-bot race prevention
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cross_bot_lock import claim as _cb_claim, confirm as _cb_confirm, release as _cb_release, release_all as _cb_release_all

load_dotenv()

# ── Logging setup ────────────────────────────────────────────────
from config import LOG_FILE, LOOP_INTERVAL_SECONDS, SYMBOLS, MAX_TRADES_PER_DAY, MANUAL_MODE, RISK_PERCENT, RR_RATIO, MIN_BALANCE_TO_TRADE

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("main")

# ── Imports ──────────────────────────────────────────────────────
import MetaTrader5 as mt5
from mt5_connector    import connect, disconnect, get_candles, get_balance, get_open_positions, get_current_price
from strategy         import evaluate, in_session, current_session_label, session_just_ended
from config           import CARRY_TO_LAST_SESSION, LAST_SESSION_END
from risk_engine      import calculate_lot, calculate_sl_tp
from executor         import open_trade, close_all_for_symbol
from trade_manager    import manage_open_positions, snapshot_positions, detect_closed_positions
from telegram_notify  import notify_trade_closed as _notify_closed
from news_filter      import is_blocked
from news_trader      import news_trade_allowed
from day_filter       import get_day_info, weekly_summary
from report           import daily_report, account_summary
from telegram_notify  import (
    notify_bot_started, notify_trade_opened, notify_skipped,
    notify_news_block, notify_daily_report, notify_signal,
)
from elite_execution  import elite_filter
import telegram_commands as tg_commands
from telegram_commands import is_paused
from config           import (
    CANDLE_COUNT_4H, CANDLE_COUNT_1H, CANDLE_COUNT_15M, CANDLE_COUNT_1M, SYMBOLS,
)

NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")

# ── State ────────────────────────────────────────────────────────
trades_today      = {sym: 0 for sym in SYMBOLS}
open_tickets      = {}   # {symbol: {"ticket": int, "lot": float, "action": str}}
last_4h_scanned   = None  # datetime of last 4H candle close we scanned
_last_signal_time = {}    # symbol → timestamp of last signal sent (30 min cooldown)


def get_4h_candle_close() -> datetime:
    """Return the datetime (UTC) of the most recently closed 4H candle."""
    now = datetime.now(timezone.utc)
    h   = (now.hour // 4) * 4
    return now.replace(hour=h, minute=0, second=0, microsecond=0)


def new_4h_candle_available() -> bool:
    """Return True if a 4H candle just closed and we haven't scanned it yet."""
    global last_4h_scanned
    close_time = get_4h_candle_close()
    now        = datetime.now(timezone.utc)
    mins_since = (now - close_time).total_seconds() / 60
    # Scan within first 3 minutes after a new 4H candle opens
    if mins_since <= 3 and close_time != last_4h_scanned:
        return True
    return False


def any_session_active() -> bool:
    """Return True if ANY symbol has an active session right now."""
    from strategy import in_session
    return any(in_session(sym) for sym in SYMBOLS)


def session_ends_soon() -> bool:
    """Return True if all sessions for today are finished (after 9:00 PM IST = 15:30 UTC)."""
    now_utc = datetime.now(timezone.utc)
    # Last session ends at 15:30 UTC (9:00 PM IST) — bot shuts down after that
    return now_utc.hour > 15 or (now_utc.hour == 15 and now_utc.minute >= 30)


def reset_daily_state():
    global trades_today
    trades_today = {sym: 0 for sym in SYMBOLS}
    logger.info("Daily trade counter reset.")


def bot_tick(bypass_session: bool = False):
    """
    Called every 60s (session-based) AND at every 4H candle close (all pairs, no session filter).
    bypass_session=True → skip the in_session check, scan all pairs regardless of time.
    """
    trigger = "4H-CLOSE" if bypass_session else "SESSION"
    logger.info("─── Bot tick [%s] | UTC %s ───", trigger, datetime.now(timezone.utc).strftime("%H:%M:%S"))

    # ── Manage open positions first (breakeven + trailing stop) ──
    from mt5_connector import get_candles as _gc
    from indicators    import atr as _atr
    from config        import UTBOT_ATR_PERIOD
    atr_map = {}
    for _sym in SYMBOLS:
        _mt5 = SYMBOLS[_sym]["mt5_symbol"]
        _df  = _gc(_mt5, "H4", 50)
        if not _df.empty:
            atr_map[_sym] = float(_atr(_df, UTBOT_ATR_PERIOD).iloc[-1])
    # ── Detect SL/TP closes ──────────────────────────────────────────────────
    _cur_tickets = {p.ticket for sym in SYMBOLS
                    for p in (mt5.positions_get(symbol=SYMBOLS[sym]["mt5_symbol"]) or [])
                    if p.magic == 20260318}
    detect_closed_positions(_cur_tickets, notify_closed_fn=_notify_closed)
    for _sym in SYMBOLS:
        _mt5s = SYMBOLS[_sym]["mt5_symbol"]
        snapshot_positions(_sym, [p for p in (mt5.positions_get(symbol=_mt5s) or [])
                                  if p.magic == 20260318])

    manage_open_positions(atr_map)

    if is_paused():
        logger.info("Bot PAUSED — managing open positions only, skipping new trade scan")
        return

    for symbol in SYMBOLS:
        mt5_sym = SYMBOLS[symbol]["mt5_symbol"]

        # ── Day filter — per symbol (Gold closed weekends, BTC open) ─
        should_trade, day_lot_mult, day_reason = get_day_info(symbol=symbol)
        if not should_trade:
            logger.info("DAY FILTER [%s]: %s", symbol, day_reason)
            continue

        # ── Session check (skipped on 4H candle close scan) ──────
        if not bypass_session and not in_session(symbol):
            label = current_session_label(symbol) or "waiting for next session"
            logger.info("%s: Outside session — %s", symbol, label)
            continue

        # ── Daily trade limit ────────────────────────────────────
        if trades_today[symbol] >= MAX_TRADES_PER_DAY:
            logger.info("%s: max trades/day reached (%d)", symbol, MAX_TRADES_PER_DAY)
            continue

        # ── Cross-bot: skip if ANY bot has a position on this symbol ─
        positions = get_open_positions(mt5_sym)   # all magics
        if positions:
            logger.info("%s: position already open (any bot, ticket %d) — skip",
                        symbol, positions[0].ticket)
            continue

        # ── Min balance check ────────────────────────────────────
        _min_bal = MIN_BALANCE_TO_TRADE.get(symbol, 0)
        if _min_bal > 0:
            _bal = get_balance()
            if _bal < _min_bal:
                logger.info("SKIP %s — balance $%.2f below minimum $%.2f", symbol, _bal, _min_bal)
                continue

        # ── News filter ──────────────────────────────────────────
        blocked, reason = is_blocked()
        if blocked:
            logger.warning("SKIP %s — %s", symbol, reason)
            notify_news_block(symbol, reason)
            continue

        # ── Fetch candles ────────────────────────────────────────
        df_4h  = get_candles(mt5_sym, "H4",  CANDLE_COUNT_4H)
        df_1h  = get_candles(mt5_sym, "H1",  CANDLE_COUNT_1H)
        df_15m = get_candles(mt5_sym, "M15", CANDLE_COUNT_15M)
        df_1m  = get_candles(mt5_sym, "M1",  CANDLE_COUNT_1M)

        if df_4h.empty or df_1m.empty:
            logger.warning("%s: insufficient candle data", symbol)
            continue

        # ── Get current price ────────────────────────────────────
        bid, ask = get_current_price(mt5_sym)
        if bid == 0:
            continue

        # ── Evaluate strategy ────────────────────────────────────
        signal = evaluate(symbol, df_4h, df_1h, df_15m, df_1m, bid)

        logger.info("%s signal: %s | %s", symbol, signal.action.upper(), signal.reason)
        for conf in signal.confirmations:
            logger.info("  └ %s", conf)

        # ── News-driven trade override ────────────────────────────
        # If technical signal skips but a strong news event fires → trade news
        if signal.action == "skip" and NEWS_API_KEY:
            news_sig = news_trade_allowed(symbol, min_confidence=75)
            if news_sig.action != "skip":
                logger.info(
                    "📰 NEWS TRADE | %s %s | %d%% confidence | %s",
                    symbol, news_sig.action.upper(), news_sig.confidence, news_sig.reason
                )
                signal.action  = news_sig.action
                signal.atr_4h  = signal.atr_4h if signal.atr_4h > 0 else (
                    df_4h["high"].iloc[-1] - df_4h["low"].iloc[-1])  # use last candle range
                # News trades: wider SL, smaller lot
                news_sl_mult = news_sig.sl_multiplier
                news_lot_mult = news_sig.lot_multiplier
            else:
                continue
        elif signal.action == "skip":
            continue
        else:
            news_sl_mult  = 1.0
            news_lot_mult = 1.0

        # ── Calculate lot + SL/TP ────────────────────────────────
        balance = get_balance()
        raw_lot = calculate_lot(balance, symbol, atr_4h=signal.atr_4h,
                                day_lot_multiplier=day_lot_mult)
        if raw_lot == 0:
            logger.warning("SKIP %s — min lot risk too high for current balance, trade blocked.", symbol)
            continue
        lot = round(raw_lot * news_lot_mult, 2)
        lot = max(SYMBOLS[symbol].get("min_lot", 0.01), lot)
        atr_adjusted = signal.atr_4h * news_sl_mult
        sl, tp = calculate_sl_tp(signal.action, signal.entry_price, atr_adjusted, symbol)

        # ── Elite execution enhancement ───────────────────────────
        try:
            elite = elite_filter(
                symbol, signal.action, signal.entry_price,
                df_4h, df_1h, signal.atr_4h, balance,
                risk_pct=RISK_PERCENT, rr_ratio=RR_RATIO,
            )
            for note in elite.get("notes", []):
                logger.info("  ELITE [%s]: %s", symbol, note)
            # Use structural SL + elite lot if meaningfully tighter
            if elite.get("use_elite_sl") and elite.get("elite_lot", 0) > 0:
                sl   = elite["structural_sl"]
                tp   = elite["tp_price"] if elite.get("tp_price", 0) > 0 else tp
                lot  = max(SYMBOLS[symbol].get("min_lot", 0.01), elite["elite_lot"])
                logger.info(
                    "ELITE UPGRADE [%s]: SL %.2f | Lot %.2f | State=%s",
                    symbol, sl, lot, elite["market_state"],
                )
        except Exception as _e:
            logger.warning("Elite filter error (non-critical) [%s]: %s", symbol, _e)

        # ── Cross-bot position check (signal-only mode) ──────────
        # Skip signal if any bot already has a position on this pair
        if MANUAL_MODE:
            mt5_sym = SYMBOLS[symbol].get("mt5_symbol", symbol + "m")
            existing = mt5.positions_get(symbol=mt5_sym) or []
            if existing:
                logger.info("[%s] Cross-bot: position already open (ticket #%s) — skipping signal.",
                            symbol, existing[0].ticket)
                continue

        # ── Signal alert — notify phone BEFORE auto-trade ────────
        rr = abs(tp - sl * 0 + sl - sl) if sl == tp else abs(tp - signal.entry_price) / max(abs(signal.entry_price - sl), 0.01)
        notify_signal(symbol, signal.action, signal.entry_price, sl, tp, rr,
                      reason=f"BOT1 UTBot+VWAP+EMA | ATR={signal.atr_4h:.1f}",
                      manual_mode=MANUAL_MODE)

        # ── Execute trade (skipped in MANUAL_MODE) ───────────────
        if MANUAL_MODE:
            import time as _t
            _now = _t.time()
            if _now - _last_signal_time.get(symbol, 0) < 1800:
                logger.info("MANUAL_MODE: [%s] Signal cooldown — already sent within 30 min.", symbol)
                continue
            logger.info("MANUAL_MODE: Signal sent — NOT executing. Master bot executes.")
            _last_signal_time[symbol] = _now
            trades_today[symbol] += 1
            continue

        if not _cb_claim(symbol, "BOT1"):
            logger.info("SKIP %s — cross-bot lock active (another bot placing right now)", symbol)
            continue

        result = open_trade(symbol, signal.action, lot, sl, tp)

        if result["success"]:
            trades_today[symbol] += 1
            entry_px = result.get("entry_price", signal.entry_price)
            _cb_confirm(symbol, result["ticket"], "BOT1")
            logger.info(
                "✅ TRADE OPENED | %s %s | Lot=%.2f | Entry=%.2f | SL=%.2f | TP=%.2f | Ticket=%s",
                signal.action.upper(), symbol, lot, entry_px, sl, tp, result["ticket"],
            )
            notify_trade_opened(symbol, signal.action, lot, entry_px, sl, tp)
        else:
            _cb_release(symbol)
            logger.error("❌ TRADE FAILED | %s | %s", symbol, result["message"])

    # ── Session/Day-end close ─────────────────────────────────────
    now_utc = datetime.now(timezone.utc)
    for symbol in SYMBOLS:
        mt5_sym = SYMBOLS[symbol]["mt5_symbol"]
        positions = get_open_positions(mt5_sym)
        bot_positions = [p for p in positions if p.magic == 20260318]
        if not bot_positions:
            continue

        if CARRY_TO_LAST_SESSION:
            # Close only at the last session end of the day
            lh, lm  = LAST_SESSION_END.get(symbol, (23, 59))
            at_last = (now_utc.hour == lh and abs(now_utc.minute - lm) <= 1)
            if at_last:
                logger.info("DAY END [%s] — closing %d position(s)", symbol, len(bot_positions))
                close_all_for_symbol(symbol)
                # Cancel any pending orders for this symbol
                _pending = mt5.orders_get(symbol=mt5_sym) or []
                for _ord in _pending:
                    mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": _ord.ticket})
                    logger.info("DAY END CANCEL | Pending #%d for %s", _ord.ticket, symbol)
        else:
            # Close at end of each session
            if session_just_ended(symbol, window_minutes=30):
                logger.info("SESSION END [%s] — closing %d position(s)", symbol, len(bot_positions))
                close_all_for_symbol(symbol)


def run():
    logger.info("=" * 60)
    logger.info("  VISHU TRADING BOT STARTING")
    logger.info("  Symbols : %s", list(SYMBOLS.keys()))
    logger.info("=" * 60)

    if not connect():
        logger.error("Cannot connect to MT5. Check .env credentials and MT5 terminal.")
        sys.exit(1)

    balance = get_balance()
    logger.info(account_summary())
    logger.info(weekly_summary())

    # Day filter check at startup — show status per pair
    session_status = []
    for sym in SYMBOLS:
        ok, mult, reason = get_day_info(symbol=sym)
        status = f"✅ TRADE (lot ×{mult})" if ok else "❌ SKIP"
        logger.info("TODAY [%s]: %s — %s", sym, status, reason)
        session_status.append((sym, ok, reason))

    from config import RISK_MODE
    notify_bot_started(balance, risk_mode=RISK_MODE, session_status=session_status)
    # Command listener disabled — Bot 2 handles all Telegram commands
    # tg_commands.start()

    # Schedule — session-based scans every 60s
    schedule.every(LOOP_INTERVAL_SECONDS).seconds.do(bot_tick)
    schedule.every().day.at("00:01").do(reset_daily_state)
    schedule.every().day.at("22:00").do(lambda: notify_daily_report(0, 0, 0, get_balance()))

    # Run once immediately
    bot_tick()

    logger.info("Bot running 24/7 — scans every 60s during sessions + at every 4H candle close.")
    logger.info("4H candle closes (UTC): 00:00 | 04:00 | 08:00 | 12:00 | 16:00 | 20:00")
    logger.info("Press Ctrl+C to stop manually.")
    try:
        while True:
            schedule.run_pending()
            time.sleep(1)

            # ── 4H candle close scan — runs regardless of session ──
            if new_4h_candle_available():
                close_time = get_4h_candle_close()
                ist_h = (close_time.hour + 5) % 24
                ist_m = close_time.minute + 30
                if ist_m >= 60:
                    ist_m -= 60
                    ist_h = (ist_h + 1) % 24
                logger.info(
                    "━━━ 4H CANDLE CLOSE DETECTED [%02d:%02d UTC / %02d:%02d IST] — scanning all pairs ━━━",
                    close_time.hour, close_time.minute, ist_h, ist_m,
                )
                bot_tick(bypass_session=True)
                global last_4h_scanned
                last_4h_scanned = close_time

    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
        daily_report()
    finally:
        disconnect()
        logger.info("Bot closed.")


if __name__ == "__main__":
    run()
