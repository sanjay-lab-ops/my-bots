"""
VISHU ELITE BOT — Main Loop
============================
Run: python main.py

Loop runs every 60 seconds:
  1. Check daily loss limit → if hit, sleep and skip
  2. Check active sessions → if none, skip
  3. Check news filter → if blocked, skip
  4. Get triple-TF bias → if NEUTRAL, skip
  5. Check if already have a trade for this pair this session → if yes, skip
  6. Check entry signal → if triggered, place trade
  7. Run trade manager to apply breakeven/trailing on open trades

Auto-stops after all sessions end for the day (16:00 UTC / 21:30 IST).
Sends daily summary Telegram at end of last session.
"""

import os
import sys
import time
import logging
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

# Cross-bot race prevention
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cross_bot_lock import claim as _cb_claim, confirm as _cb_confirm, release as _cb_release

load_dotenv()

# ── Logging setup ─────────────────────────────────────────────────
from config import LOG_FILE, LOOP_INTERVAL_SECONDS, TRADE_MANAGER_INTERVAL, SYMBOLS, MAX_TRADES_DAY, MAX_TRADES_PAIR, MAGIC_NUMBER, MANUAL_MODE, MIN_BALANCE_TO_TRADE
import telegram_commands
from telegram_commands import load_forced_bias

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("main")

# ── Module imports ────────────────────────────────────────────────
from mt5_conn       import (connect, disconnect, reconnect, is_connected,
                             get_balance, get_account_info, get_day_pnl, get_candles,
                             get_bot_positions, get_open_positions)
from bias           import get_bias
from entry          import check_entry
from risk           import get_lot_size, calculate_sl_tp, is_daily_loss_limit_hit, check_trade_risk
from news_filter    import is_news_blocked, get_next_news_event
from executor       import open_trade, close_all_for_symbol, close_all_positions_eod
from trade_manager  import run_trade_manager
from session        import (is_session_active, get_active_session_label, any_session_active,
                             all_sessions_done_for_day, get_session_key, get_ist_time_label,
                             session_just_opened)
import telegram_notify as tg
from elite_execution import elite_filter
from telegram_commands import is_paused


# ── Global State ──────────────────────────────────────────────────
# trades_today[symbol] = count of trades taken today for that symbol
trades_today: dict = {sym: 0 for sym in SYMBOLS}

# session_traded[session_key] = True if a trade was already taken in that session window
session_traded: dict = {}

# ── Persist session_traded across restarts ────────────────────────
import json as _json
from pathlib import Path as _Path
_SESSION_TRADED_FILE = _Path(__file__).parent / "session_traded.json"

def _load_session_traded() -> dict:
    """Load session_traded from disk — survives bot restarts."""
    if not _SESSION_TRADED_FILE.exists():
        return {}
    try:
        data = _json.loads(_SESSION_TRADED_FILE.read_text())
        # Only keep entries from today (UTC date)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return {k: v for k, v in data.items() if k.startswith(today)}
    except Exception:
        return {}

def _save_session_traded(st: dict) -> None:
    try:
        _SESSION_TRADED_FILE.write_text(_json.dumps(st))
    except Exception:
        pass

# Total trade count across all pairs today
total_trades_today: int = 0

# Daily P&L cache (updated each loop)
day_pnl_cache: float = 0.0

# Flag: was daily loss limit notification sent already?
loss_limit_notified: bool = False

# SL-to-entry alert thresholds — notify once per level per session
_sl_alert_sent: set  = set()   # tracks which % levels already alerted today
_profit_trail_active: bool = False  # True once 150% level hit — start tracking peak

# Daily peak balance — for account drawdown protection
_daily_peak_balance: float = 0.0
_account_protected:  bool  = False   # True = stop all new trades (30% drawdown hit)
_capital_sl_done:    bool  = False   # True = SL→entry already moved at 30% profit

_PEAK_FILE = os.path.join(os.path.dirname(__file__), "peak_floating.txt")

def _load_peak() -> float:
    try:
        with open(_PEAK_FILE) as f: return float(f.read().strip())
    except: return 0.0

def _save_peak(v: float):
    try:
        with open(_PEAK_FILE, "w") as f: f.write(str(v))
    except: pass

_peak_floating: float = _load_peak()   # survives restarts

# Trade manager timing
last_trade_manager_run: float = 0.0

# Daily summary sent flag
daily_summary_sent: bool = False


def _get_next_session_info() -> str:
    """Return a human-readable string showing when the next session starts."""
    from config import SESSIONS
    now_utc = datetime.now(timezone.utc)
    now_m   = now_utc.hour * 60 + now_utc.minute
    best    = None
    best_diff = 9999
    for sym, sessions in SESSIONS.items():
        for sess in sessions:
            sh, sm = sess["start_utc"]
            start_m = sh * 60 + sm
            diff = start_m - now_m
            if diff < 0:
                diff += 1440  # next day
            if diff < best_diff:
                best_diff = diff
                best = (sym, sess["label"], sh, sm)
    if best:
        sym, label, sh, sm = best
        ist_h = (sh + 5) % 24
        ist_m = sm + 30
        if ist_m >= 60:
            ist_m -= 60
            ist_h  = (ist_h + 1) % 24
        return f"{label} at {ist_h:02d}:{ist_m:02d} IST (in {best_diff} min)"
    return "No upcoming sessions found"


def reset_daily_state():
    """Reset all per-day counters at midnight UTC."""
    global trades_today, session_traded, total_trades_today
    global loss_limit_notified, daily_summary_sent, day_pnl_cache
    trades_today       = {sym: 0 for sym in SYMBOLS}
    session_traded     = {}
    total_trades_today = 0
    _save_session_traded({})
    loss_limit_notified = False
    daily_summary_sent  = False
    day_pnl_cache       = 0.0
    _sl_alert_sent.clear()
    _peak_floating       = 0.0
    _profit_trail_active = False
    logger.info("Daily state reset — counters cleared for new trading day")


def fetch_candles_for_symbol(symbol: str) -> dict:
    """Fetch all required timeframes for a symbol. Returns dict of DataFrames."""
    from config import CANDLE_COUNT_4H, CANDLE_COUNT_1H, CANDLE_COUNT_15M, CANDLE_COUNT_1M
    mt5_sym = SYMBOLS[symbol]["mt5_symbol"]
    return {
        "4H":  get_candles(mt5_sym, "H4",  CANDLE_COUNT_4H),
        "1H":  get_candles(mt5_sym, "H1",  CANDLE_COUNT_1H),
        "15M": get_candles(mt5_sym, "M15", CANDLE_COUNT_15M),
        "1M":  get_candles(mt5_sym, "M1",  CANDLE_COUNT_1M),
    }


def bot_tick():
    """Execute one full iteration of the bot loop."""
    global trades_today, session_traded, total_trades_today
    global day_pnl_cache, loss_limit_notified, last_trade_manager_run
    global _sl_alert_sent, _peak_floating, _profit_trail_active
    global _daily_peak_balance, _account_protected, _capital_sl_done

    now_utc  = datetime.now(timezone.utc)
    ist_time = get_ist_time_label()

    logger.info("── Bot tick | UTC %s | %s ──", now_utc.strftime("%H:%M:%S"), ist_time)

    # ── 0. MT5 connectivity check ─────────────────────────────────
    if not is_connected():
        logger.warning("MT5 disconnected — attempting reconnect...")
        tg.notify_reconnect(1)
        if not reconnect(max_attempts=3):
            logger.error("Reconnect failed — skipping tick")
            tg.notify_reconnect_failed()
            return
        logger.info("MT5 reconnected successfully")

    # ── 1. Daily loss limit check ─────────────────────────────────
    day_pnl_cache = get_day_pnl()
    if is_daily_loss_limit_hit(day_pnl_cache, get_balance()):
        if not loss_limit_notified:
            tg.notify_daily_loss_limit(day_pnl_cache, get_balance())
            loss_limit_notified = True
        logger.warning("🛑 Daily loss limit reached — halting trading for today")
        import time as _time; _time.sleep(3600)
        return

    # ── 1b. Capital protection + floating profit monitor ─────────────
    try:
        from mt5_conn import get_equity
        from executor import close_trade
        import MetaTrader5 as _mt5
        _balance  = get_balance()
        _equity   = get_equity()
        _floating = _equity - _balance

        # Track daily peak balance
        if _balance > _daily_peak_balance:
            _daily_peak_balance = _balance
            logger.info("Daily peak balance updated: $%.2f", _daily_peak_balance)

        # ── Account drawdown protection: if balance drops 30% from daily peak → stop trading ──
        if (_daily_peak_balance > 0 and not _account_protected
                and _balance < _daily_peak_balance * 0.70):
            _account_protected = True
            logger.warning("ACCOUNT PROTECTION: balance $%.2f dropped 30%% from peak $%.2f — no new trades",
                           _balance, _daily_peak_balance)
            tg.notify_account_protection(_balance, _daily_peak_balance)

        # ── Capital profit protection: if profit >= 30% of starting balance → SL to entry ──
        if not _capital_sl_done and _daily_peak_balance > 0:
            _start_bal = _daily_peak_balance  # use peak as reference
            _capital_profit_pct = ((_balance - _start_bal) / _start_bal) * 100
            if _balance > _start_bal * 1.30:   # 30% profit on capital
                _capital_sl_done = True
                _moved = 0
                for _pos in (_mt5.positions_get() or []):
                    if _pos.profit <= 0: continue
                    _new_sl = round(_pos.price_open, 2)
                    _is_buy = _pos.type == _mt5.ORDER_TYPE_BUY
                    if _is_buy and _pos.sl >= _pos.price_open: continue
                    if not _is_buy and _pos.sl <= _pos.price_open and _pos.sl > 0: continue
                    _res = _mt5.order_send({"action": _mt5.TRADE_ACTION_SLTP,
                                            "position": _pos.ticket, "sl": _new_sl, "tp": _pos.tp})
                    if _res and _res.retcode == _mt5.TRADE_RETCODE_DONE:
                        _moved += 1
                logger.info("CAPITAL 30%% PROFIT: SL→entry on %d positions", _moved)
                tg.notify_capital_sl_to_entry(_balance, _start_bal, _moved)

        if _balance > 0 and _floating > 0:
            _pct = (_floating / _balance) * 100

            # ── Update peak tracking ──────────────────────────────
            if _profit_trail_active and _floating > _peak_floating:
                _peak_floating = _floating
                _save_peak(_peak_floating)
                logger.info("New peak floating: $%.2f", _peak_floating)

            # ── Profit trail: close all if floating drops 20% from peak ──
            if (_profit_trail_active and _peak_floating > 0
                    and _floating < _peak_floating * 0.80):
                _closed = 0
                _locked = 0.0
                for _pos in (_mt5.positions_get() or []):
                    if _pos.profit > 0:
                        if close_trade(_pos.ticket, _pos.symbol):
                            _closed += 1
                            _locked += _pos.profit
                            logger.info("PROFIT TRAIL CLOSE | %s #%d | locked $%.2f",
                                        _pos.symbol, _pos.ticket, _pos.profit)
                tg.notify_profit_trail_close(_locked, _closed, _peak_floating, _floating)
                logger.info("Profit trail triggered | peak=%.2f | now=%.2f | locked=%.2f",
                            _peak_floating, _floating, _locked)
                _peak_floating       = 0.0
                _save_peak(0.0)
                _profit_trail_active = False
                _sl_alert_sent.clear()

            else:
                # ── Threshold alerts ─────────────────────────────
                for _threshold in [100, 150, 300]:
                    if _pct >= _threshold and _threshold not in _sl_alert_sent:
                        _sl_alert_sent.add(_threshold)

                        if _threshold >= 150:
                            _profit_trail_active = True
                            if _floating > _peak_floating:
                                _peak_floating = _floating
                                _save_peak(_peak_floating)

                        if _threshold == 300:
                            # Auto move all profitable SLs to entry
                            _moved = 0
                            for _pos in (_mt5.positions_get() or []):
                                if _pos.profit <= 0:
                                    continue
                                _new_sl = round(_pos.price_open, 2)
                                _is_buy = _pos.type == _mt5.ORDER_TYPE_BUY
                                if _is_buy  and _pos.sl >= _pos.price_open: continue
                                if not _is_buy and _pos.sl <= _pos.price_open and _pos.sl > 0: continue
                                _res = _mt5.order_send({
                                    "action":   _mt5.TRADE_ACTION_SLTP,
                                    "position": _pos.ticket,
                                    "sl":       _new_sl,
                                    "tp":       _pos.tp,
                                })
                                if _res and _res.retcode == _mt5.TRADE_RETCODE_DONE:
                                    _moved += 1
                                    logger.info("AUTO SL→ENTRY | %s #%d | %.2f → %.2f",
                                                _pos.symbol, _pos.ticket, _pos.sl, _new_sl)
                            tg.notify_sl_to_entry_alert(_floating, _balance, _equity, _pct,
                                                        auto_executed=True, moved=_moved)
                            logger.info("AUTO SL→entry | moved=%d | pct=%.0f%%", _moved, _pct)
                        else:
                            tg.notify_sl_to_entry_alert(_floating, _balance, _equity, _pct)
                            logger.info("SL-to-entry alert sent | floating=%.2f | pct=%.0f%%",
                                        _floating, _pct)
                        break

    except Exception as _e:
        logger.debug("Floating alert check error (non-critical): %s", _e)

    # ── 2. Account protection gate — no new trades if balance dropped 30% ──
    if _account_protected:
        logger.warning("ACCOUNT PROTECTED — skipping new trades. Balance below daily peak -30%%.")
        return

    # ── 3. Session check — any symbol active? ────────────────────
    if is_paused():
        logger.info("Bot PAUSED — skipping new trade scan (managing open positions only)")
        return

    if not any_session_active():
        next_sess = _get_next_session_info()
        logger.info("No sessions active now. Next: %s", next_sess)
        return

    # ── 3. News filter ────────────────────────────────────────────
    news_blocked, news_reason = is_news_blocked()

    # ── 4. Per-symbol evaluation ──────────────────────────────────
    # ETH/BTC and XAG/XAU correlation trackers
    _btc_elite_bias = None
    _xau_elite_bias = None

    for symbol in SYMBOLS:
        mt5_sym = SYMBOLS[symbol]["mt5_symbol"]

        # Skip if not in session for this specific symbol
        if not is_session_active(symbol):
            continue

        # Session open delay — wait 15 min after open (London open manipulation trap)
        if session_just_opened(symbol, wait_minutes=15):
            logger.info("[%s] Session just opened — waiting 15 min for direction (avoid open trap)", symbol)
            continue

        # Balance protection — skip if account too small for this symbol
        min_bal = MIN_BALANCE_TO_TRADE.get(symbol, 0)
        if _balance < min_bal:
            logger.info("[%s] Skip — balance $%.2f < $%d minimum (protect live account)", symbol, _balance, min_bal)
            continue

        session_label = get_active_session_label(symbol)

        # ── 4a. Daily trade limit ─────────────────────────────────
        if total_trades_today >= MAX_TRADES_DAY:
            logger.info(
                "[%s] Skip — total daily limit reached (%d/%d)",
                symbol, total_trades_today, MAX_TRADES_DAY,
            )
            continue

        if trades_today.get(symbol, 0) >= MAX_TRADES_PAIR:
            logger.info(
                "[%s] Skip — pair daily limit reached (%d/%d)",
                symbol, trades_today[symbol], MAX_TRADES_PAIR,
            )
            continue

        # ── 4b. One trade per session window ─────────────────────
        sess_key = get_session_key(symbol)
        if sess_key and session_traded.get(sess_key, False):
            logger.info("[%s] Skip — already traded in this session (%s)", symbol, sess_key)
            continue

        # ── 4c. Cross-bot: skip if ANY bot has a position on this symbol ──
        open_pos = get_bot_positions(mt5_sym)   # bot trades only, ignore manual trades
        if open_pos:
            logger.info(
                "[%s] Skip — bot position already open (ticket=%d)",
                symbol, open_pos[0].ticket,
            )
            continue

        # ── 4d. News filter ───────────────────────────────────────
        if news_blocked:
            logger.warning("[%s] Skip — news block: %s", symbol, news_reason)
            tg.notify_news_block(symbol, news_reason)
            continue

        # ── 4e. Fetch candle data ─────────────────────────────────
        candles = fetch_candles_for_symbol(symbol)
        if candles["4H"].empty or candles["1M"].empty:
            logger.warning("[%s] Skip — insufficient candle data", symbol)
            continue

        # ── 4f. Bias — triple timeframe confluence ────────────────
        forced = load_forced_bias().get(symbol, "auto").lower()
        if forced != "auto":
            bias = forced.upper()
            logger.info("[%s] FORCED_BIAS override: %s (skipping auto analysis)", symbol, bias)
        else:
            bias, bias_confirmations = get_bias(candles["4H"], candles["1H"], candles["15M"])
            for conf in bias_confirmations:
                logger.info("[%s] %s", symbol, conf)
            if bias == "NEUTRAL":
                logger.info("[%s] NEUTRAL bias — no trade", symbol)
                continue

        logger.info("[%s] Bias: %s", symbol, bias)

        # ── ETH/BTC and XAG/XAU correlation filters ──────────────
        if symbol == "BTCUSD" and bias != "NEUTRAL":
            _btc_elite_bias = bias
        elif symbol == "ETHUSD" and _btc_elite_bias and bias != "NEUTRAL":
            if bias != _btc_elite_bias:
                logger.info(
                    "[ETHUSD] CORRELATION SKIP: BTC=%s but ETH=%s — skipping",
                    _btc_elite_bias, bias,
                )
                continue
        _xag_elite_divergence = False
        if symbol == "XAUUSD" and bias != "NEUTRAL":
            _xau_elite_bias = bias
        elif symbol == "XAGUSD" and _xau_elite_bias and bias != "NEUTRAL":
            if bias != _xau_elite_bias:
                _xag_elite_divergence = True
                logger.info(
                    "[XAGUSD] DIVERGENCE: XAU=%s but XAG=%s — trading min lot 0.01",
                    _xau_elite_bias, bias,
                )

        # ── 4g. Entry signal — 1M EMA cross + RSI + ATR filter ───
        signal, atr_val, entry_reason = check_entry(
            symbol, bias, candles["1M"], candles["4H"]
        )

        logger.info("[%s] Entry check: %s — %s", symbol, signal, entry_reason)

        if signal == "NONE":
            continue

        # ── 4h. Risk calculation ──────────────────────────────────
        balance = get_balance()
        lot     = get_lot_size(symbol, balance)
        # XAG divergence from XAU — cap at minimum lot to limit risk
        if symbol == "XAGUSD" and _xag_elite_divergence:
            lot = SYMBOLS[symbol].get("min_lot", 0.01)
            logger.info("[XAGUSD] DIVERGENCE LOT CAP: using min lot %.2f", lot)

        if not check_trade_risk(symbol, balance, lot, atr_val):
            logger.warning("[%s] Skip — risk check failed (account too small for ATR risk)", symbol)
            continue

        import MetaTrader5 as mt5
        tick = mt5.symbol_info_tick(mt5_sym)
        if tick is None:
            logger.warning("[%s] Skip — cannot get current tick", symbol)
            continue

        entry_price = tick.ask if signal == "BUY" else tick.bid
        sl, tp      = calculate_sl_tp(signal, entry_price, atr_val, symbol)

        # ── Elite execution enhancement ───────────────────────────
        try:
            from config import RR_RATIO as _RR
            elite = elite_filter(
                symbol, signal, entry_price,
                candles["4H"], candles["1H"], atr_val, balance,
                risk_pct=1.5, rr_ratio=_RR,
            )
            for note in elite.get("notes", []):
                logger.info("  ELITE [%s]: %s", symbol, note)
            if elite.get("use_elite_sl") and elite.get("elite_lot", 0) > 0:
                sl  = elite["structural_sl"]
                tp  = elite["tp_price"] if elite.get("tp_price", 0) > 0 else tp
                lot = max(SYMBOLS[symbol].get("min_lot", 0.01), elite["elite_lot"])
                logger.info(
                    "ELITE UPGRADE [%s]: SL %.2f | Lot %.2f | State=%s",
                    symbol, sl, lot, elite["market_state"],
                )
        except Exception as _e:
            logger.warning("Elite filter error (non-critical) [%s]: %s", symbol, _e)

        # ── 4i. Execute trade ─────────────────────────────────────
        logger.info(
            "[%s] PLACING %s | Lot=%.2f | Entry=%.2f | SL=%.2f | TP=%.2f",
            symbol, signal, lot, entry_price, sl, tp,
        )

        # ── Cross-bot position check (signal-only mode) ──────────
        if MANUAL_MODE:
            import MetaTrader5 as _mt5c
            _mt5sym = symbol + "m"
            _existing = _mt5c.positions_get(symbol=_mt5sym) or []
            if _existing:
                logger.info("[%s] Cross-bot: position already open — skipping signal.", symbol)
                continue

        # ── Signal alert to phone BEFORE auto-trade ──────────────
        rr = abs(tp - entry_price) / max(abs(entry_price - sl), 0.01)
        tg.notify_signal(symbol, signal, entry_price, sl, tp, rr,
                         reason="BOT2 Triple TF confluence",
                         manual_mode=MANUAL_MODE)

        # ── Execute trade (skipped in MANUAL_MODE) ───────────────
        if MANUAL_MODE:
            logger.info("MANUAL_MODE: Signal sent — NOT executing. Master bot executes.")
            # Mark session as traded so same signal isn't sent every 60s
            trades_today[symbol]  = trades_today.get(symbol, 0) + 1
            total_trades_today   += 1
            if sess_key:
                session_traded[sess_key] = True
                _save_session_traded(session_traded)
            continue

        if not _cb_claim(symbol, "BOT2"):
            logger.info("[%s] SKIP — cross-bot lock active (another bot placing right now)", symbol)
            continue

        result = open_trade(symbol, signal, lot, sl, tp)

        if result["success"]:
            actual_entry = result.get("entry_price", entry_price)
            ticket       = result.get("ticket", 0)
            _cb_confirm(symbol, ticket, "BOT2")

            logger.info(
                "TRADE OPENED | %s %s | Lot=%.2f | Entry=%.2f | SL=%.2f | TP=%.2f | Ticket=%d",
                signal, symbol, lot, actual_entry, sl, tp, ticket,
            )

            tg.notify_trade_opened(symbol, signal, lot, actual_entry, sl, tp, ticket=ticket)

            # Update counters
            trades_today[symbol]  = trades_today.get(symbol, 0) + 1
            total_trades_today   += 1
            if sess_key:
                session_traded[sess_key] = True
                _save_session_traded(session_traded)

        else:
            _cb_release(symbol)
            logger.error("[%s] Trade failed: %s", symbol, result["message"])

    # ── 5. Run trade manager (every TRADE_MANAGER_INTERVAL seconds) ──
    _maybe_run_trade_manager()


def _maybe_run_trade_manager():
    """Run trade manager if enough time has elapsed since last run."""
    global last_trade_manager_run
    now = time.time()
    if now - last_trade_manager_run >= TRADE_MANAGER_INTERVAL:
        run_trade_manager()
        last_trade_manager_run = now


def check_midnight_reset():
    """Reset daily counters if it's a new UTC day."""
    global _last_reset_day
    today = datetime.now(timezone.utc).date()
    if today != _last_reset_day:
        logger.info("New UTC day detected — resetting daily state")
        reset_daily_state()
        _last_reset_day = today


def send_daily_summary_if_needed():
    """Send daily summary Telegram message once all sessions are done."""
    global daily_summary_sent
    if daily_summary_sent:
        return
    if all_sessions_done_for_day():
        balance     = get_balance()
        day_pnl     = get_day_pnl()
        wins        = sum(1 for sym in SYMBOLS for p in get_bot_positions(SYMBOLS[sym]["mt5_symbol"])
                          if p.profit > 0)
        losses      = total_trades_today - wins
        next_event  = get_next_news_event()

        logger.info(
            "DAILY SUMMARY | P&L=%.2f | Wins=%d | Losses=%d | Balance=%.2f",
            day_pnl, wins, losses, balance,
        )
        tg.notify_daily_summary(day_pnl, wins, losses, balance, next_event)
        daily_summary_sent = True


def run():
    """Main entry point — connect MT5 and start the bot loop."""
    global _last_reset_day, session_traded, daily_summary_sent
    _last_reset_day = datetime.now(timezone.utc).date()
    session_traded  = _load_session_traded()   # restore from disk on restart

    logger.info("=" * 65)
    logger.info("  VISHU ELITE BOT — STARTING")
    logger.info("  Symbols  : %s", list(SYMBOLS.keys()))
    logger.info("  Strategy : 4H VWAP+PVWAP | 1H EMA20 slope | 15M EMA cross | 1M entry")
    logger.info("=" * 65)

    # ── Connect MT5 ───────────────────────────────────────────────
    if not connect():
        logger.error("FATAL: Cannot connect to MT5. Check .env credentials and MT5 terminal.")
        sys.exit(1)

    acct = get_account_info()
    balance = acct.get("balance", 0.0)
    server  = acct.get("server", "")
    logger.info(
        "Account | Login=%s | Balance=$%.2f %s | Server=%s | Leverage=1:%s",
        acct.get("login"), balance, acct.get("currency", "USD"),
        server, acct.get("leverage", "?"),
    )

    tg.notify_bot_started(balance, server=server)
    telegram_commands.start()   # background thread: listens for /setbias /bias /clearbias

    logger.info("Bot running. Press Ctrl+C to stop manually.")
    logger.info("Auto-stops after all sessions end (16:00 UTC / 21:30 IST).")

    try:
        while True:
            try:
                # Midnight reset
                check_midnight_reset()

                # Main loop iteration
                bot_tick()

                # Daily summary + auto-stop
                send_daily_summary_if_needed()
                if all_sessions_done_for_day() and daily_summary_sent:
                    logger.info("All sessions complete — closing all positions and pending orders.")
                    close_all_positions_eod()
                    # Sleep until tomorrow's first session (02:00 UTC = 07:30 IST) instead of shutting down
                    now_utc = datetime.now(timezone.utc)
                    next_start = now_utc.replace(hour=2, minute=0, second=0, microsecond=0)
                    if next_start <= now_utc:
                        next_start = next_start + timedelta(days=1)
                    sleep_secs = int((next_start - now_utc).total_seconds())
                    logger.info("EOD done — sleeping %.0f min until 02:00 UTC (07:30 IST) for next session.", sleep_secs / 60)
                    time.sleep(sleep_secs)
                    daily_summary_sent = False   # reset for new day

            except Exception as exc:
                logger.exception("Unhandled exception in bot tick: %s", exc)
                # Don't crash the bot on unexpected errors — log and continue
                time.sleep(5)

            time.sleep(LOOP_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        logger.info("Bot stopped by user (Ctrl+C).")

    finally:
        disconnect()
        logger.info("MT5 disconnected. Bot closed.")


if __name__ == "__main__":
    run()
