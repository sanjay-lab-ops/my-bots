"""
VISHU SCALP BOT
===============
Strategy : 15M EMA bias → 1M EMA5×EMA20 crossover entry
Capital  : $50–$200 live account
Risk     : 1% per trade | -3% daily stop | 1.5 RR | max 1 open trade

Entry rules:
  1. 15M EMA5 > EMA20  → BUY bias    | 15M EMA5 < EMA20 → SELL bias
  2. 1M EMA5 crosses EMA20 in bias direction
  3. RSI not overbought (BUY) / not oversold (SELL)
  4. Only inside kill zones (London Open, NY Open, London Close)
  5. No trade open already on that symbol

Exit rules:
  - SL: 1.2 × 1M ATR
  - TP: 1.5 × SL (1.5 RR)
  - Breakeven: when 50% of TP distance reached
  - Trail: when 75% of TP reached, trail at 60% of SL distance
"""

import time
import logging
import requests
import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from config import *

# ── Logging ────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger()

IST = timedelta(hours=5, minutes=30)


def ist_now() -> str:
    return (datetime.now(timezone.utc) + IST).strftime("%H:%M IST")


# ── MT5 Connection ─────────────────────────────────────────────────
def connect_mt5() -> bool:
    if not mt5.initialize():
        log.error("MT5 init failed: %s", mt5.last_error())
        return False
    if not mt5.login(MT5_LOGIN, MT5_PASSWORD, MT5_SERVER):
        log.error("MT5 login failed: %s", mt5.last_error())
        return False
    info = mt5.account_info()
    log.info("Connected | Login=%d | Balance=%.2f | Server=%s",
             info.login, info.balance, info.server)
    return True


def get_balance() -> float:
    info = mt5.account_info()
    return info.balance if info else 0.0


# ── Indicators ─────────────────────────────────────────────────────
def calc_rsi(series: pd.Series, period: int) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def calc_atr(df: pd.DataFrame, period: int) -> pd.Series:
    hi, lo, pc = df["high"], df["low"], df["close"].shift(1)
    tr = pd.concat([(hi - lo), (hi - pc).abs(), (lo - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def get_candles(symbol: str, tf: int, count: int) -> pd.DataFrame | None:
    rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)
    if rates is None or len(rates) < 30:
        return None
    df = pd.DataFrame(rates)
    df["ema_fast"] = df["close"].ewm(span=EMA_FAST, adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=EMA_SLOW, adjust=False).mean()
    df["rsi"]      = calc_rsi(df["close"], RSI_PERIOD)
    df["atr"]      = calc_atr(df, ATR_PERIOD)
    return df


# ── Kill Zone ──────────────────────────────────────────────────────
def in_kill_zone() -> tuple[bool, str]:
    now   = datetime.now(timezone.utc)
    now_m = now.hour * 60 + now.minute
    for kz in KILL_ZONES:
        s = kz["start"][0] * 60 + kz["start"][1]
        e = kz["end"][0]   * 60 + kz["end"][1]
        if s <= now_m <= e:
            return True, kz["name"]
    return False, ""


def next_kill_zone_str() -> str:
    now   = datetime.now(timezone.utc)
    now_m = now.hour * 60 + now.minute
    for kz in KILL_ZONES:
        s = kz["start"][0] * 60 + kz["start"][1]
        if s > now_m:
            mins  = s - now_m
            utc_h = kz["start"][0]
            utc_m = kz["start"][1]
            ist_h = (utc_h + 5) % 24
            ist_m = utc_m + 30
            if ist_m >= 60:
                ist_h += 1
                ist_m -= 60
            return f"{kz['name']} at {ist_h:02d}:{ist_m:02d} IST (in {mins}m)"
    return "London Open tomorrow"


def is_friday_cutoff() -> bool:
    now = datetime.now(timezone.utc)
    return now.weekday() == 4 and now.hour >= 16  # Fri after 16:00 UTC


# ── Signal ─────────────────────────────────────────────────────────
def get_bias_15m(mt5_sym: str) -> str | None:
    df = get_candles(mt5_sym, mt5.TIMEFRAME_M15, 60)
    if df is None:
        return None
    last = df.iloc[-1]
    if last["ema_fast"] > last["ema_slow"]:
        return "BUY"
    if last["ema_fast"] < last["ema_slow"]:
        return "SELL"
    return None


def get_1m_entry(mt5_sym: str, bias: str) -> tuple:
    """Returns (direction, sl, tp) or (None, None, None)"""
    df = get_candles(mt5_sym, mt5.TIMEFRAME_M1, 40)
    if df is None:
        return None, None, None

    prev = df.iloc[-2]
    last = df.iloc[-1]

    cross_bull = (prev["ema_fast"] <= prev["ema_slow"] and
                  last["ema_fast"] >  last["ema_slow"])
    cross_bear = (prev["ema_fast"] >= prev["ema_slow"] and
                  last["ema_fast"] <  last["ema_slow"])

    tick = mt5.symbol_info_tick(mt5_sym)
    if not tick:
        return None, None, None

    price = tick.ask if bias == "BUY" else tick.bid
    atr   = last["atr"]
    rsi   = last["rsi"]

    if bias == "BUY" and cross_bull and rsi < RSI_BUY_MAX:
        sl = price - atr * ATR_SL_MULT
        tp = price + atr * ATR_SL_MULT * RR_RATIO
        return "BUY", sl, tp

    if bias == "SELL" and cross_bear and rsi > RSI_SELL_MIN:
        sl = price + atr * ATR_SL_MULT
        tp = price - atr * ATR_SL_MULT * RR_RATIO
        return "SELL", sl, tp

    return None, None, None


# ── Lot Calculation ────────────────────────────────────────────────
def calc_lot(balance: float, sl_pts: float, cfg: dict) -> float:
    risk_amt = balance * (RISK_PERCENT / 100)
    raw      = risk_amt / (sl_pts * cfg["contract_size"])
    step     = cfg["lot_step"]
    lot      = round(round(raw / step) * step, 2)
    return max(cfg["min_lot"], min(lot, cfg["max_lot"]))


# ── Open Trade Check ───────────────────────────────────────────────
def open_trade_count() -> int:
    positions = mt5.positions_get()
    if not positions:
        return 0
    return sum(1 for p in positions if p.magic == MAGIC_NUMBER)


def has_position(mt5_sym: str) -> bool:
    positions = mt5.positions_get(symbol=mt5_sym)
    if not positions:
        return False
    return any(p.magic == MAGIC_NUMBER for p in positions)


# ── Order Placement ────────────────────────────────────────────────
def place_market_order(mt5_sym: str, direction: str, lot: float,
                       sl: float, tp: float) -> int | None:
    tick = mt5.symbol_info_tick(mt5_sym)
    if not tick:
        return None

    price     = tick.ask if direction == "BUY" else tick.bid
    order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL

    info = mt5.symbol_info(mt5_sym)
    filling = mt5.ORDER_FILLING_IOC
    if info and info.filling_mode & mt5.ORDER_FILLING_FOK:
        filling = mt5.ORDER_FILLING_FOK

    request = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       mt5_sym,
        "volume":       lot,
        "type":         order_type,
        "price":        price,
        "sl":           round(sl, info.digits if info else 2),
        "tp":           round(tp, info.digits if info else 2),
        "deviation":    20,
        "magic":        MAGIC_NUMBER,
        "comment":      "SCALP",
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": filling,
    }

    result = mt5.order_send(request)
    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
        log.info("✅ FILLED | %s %s | Lot=%.2f | Entry=%.2f | SL=%.2f | TP=%.2f | #%d",
                 direction, mt5_sym, lot, result.price, sl, tp, result.order)
        return result.order
    else:
        code = result.retcode if result else "N/A"
        log.error("❌ Order failed | %s %s | Code=%s", direction, mt5_sym, code)
        return None


# ── Trade Manager (Breakeven + Trail) ─────────────────────────────
def manage_open_trades():
    positions = mt5.positions_get()
    if not positions:
        return

    for pos in positions:
        if pos.magic != MAGIC_NUMBER:
            continue

        sl_dist = abs(pos.price_open - pos.sl) if pos.sl else 0
        tp_dist = abs(pos.price_open - pos.tp) if pos.tp else 0
        if sl_dist == 0 or tp_dist == 0:
            continue

        is_long   = pos.type == mt5.ORDER_TYPE_BUY
        cur_price = pos.price_current
        profit_dist = (cur_price - pos.price_open) if is_long else (pos.price_open - cur_price)
        progress    = profit_dist / tp_dist if tp_dist > 0 else 0

        if progress <= 0:
            continue  # trade going wrong, don't adjust

        new_sl = None

        # Breakeven
        if progress >= BREAKEVEN_PCT:
            be_target = pos.price_open + 0.1 if is_long else pos.price_open - 0.1
            if (is_long  and pos.sl < pos.price_open) or \
               (not is_long and pos.sl > pos.price_open):
                new_sl = be_target
                log.info("🔒 BREAKEVEN | %s #%d | SL → %.2f", pos.symbol, pos.ticket, new_sl)

        # Trail stop
        if progress >= TRAIL_PCT:
            trail_dist = sl_dist * TRAIL_MULT
            tick = mt5.symbol_info_tick(pos.symbol)
            if tick:
                if is_long:
                    candidate = tick.bid - trail_dist
                    if candidate > pos.sl and (new_sl is None or candidate > new_sl):
                        new_sl = candidate
                else:
                    candidate = tick.ask + trail_dist
                    if candidate < pos.sl and (new_sl is None or candidate < new_sl):
                        new_sl = candidate
                if new_sl != be_target:
                    log.info("📈 TRAIL SL | %s #%d | SL → %.2f", pos.symbol, pos.ticket, new_sl)

        if new_sl and abs(new_sl - pos.sl) > 0.01:
            info = mt5.symbol_info(pos.symbol)
            req  = {
                "action":   mt5.TRADE_ACTION_SLTP,
                "position": pos.ticket,
                "sl":       round(new_sl, info.digits if info else 2),
                "tp":       pos.tp,
            }
            mt5.order_send(req)


# ── Telegram ───────────────────────────────────────────────────────
def tg(msg: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": msg},
            timeout=5,
        )
    except Exception:
        pass


# ── Main Loop ──────────────────────────────────────────────────────
def run():
    log.info("=" * 60)
    log.info("  VISHU SCALP BOT — LIVE $50 ACCOUNT")
    log.info("  Pairs  : ETHUSD, BTCUSD")
    log.info("  Risk   : %.1f%% per trade | -%.1f%% daily stop", RISK_PERCENT, abs(DAILY_LOSS_LIMIT))
    log.info("  RR     : 1 : %.1f | Max trades/day: %d", RR_RATIO, MAX_TRADES_DAY)
    log.info("=" * 60)

    if not connect_mt5():
        return

    balance_start = get_balance()
    today_date    = datetime.now(timezone.utc).date()
    trades_today  = 0

    tg(
        f"🚀 SCALP BOT STARTED\n"
        f"Balance: ${balance_start:.2f}\n"
        f"Risk: {RISK_PERCENT}%/trade | Daily stop: {DAILY_LOSS_LIMIT}%\n"
        f"Max trades: {MAX_TRADES_DAY}/day | RR: 1:{RR_RATIO}"
    )

    while True:
        try:
            now = datetime.now(timezone.utc)

            # ── Daily reset ────────────────────────────────────────
            if now.date() != today_date:
                balance_start = get_balance()
                today_date    = now.date()
                trades_today  = 0
                log.info("── New day | Balance=$%.2f ──", balance_start)
                tg(f"🌅 New day\nBalance: ${balance_start:.2f}\nBot scanning...")

            balance = get_balance()

            # ── Daily loss guard ───────────────────────────────────
            if balance_start > 0:
                daily_pct = (balance - balance_start) / balance_start * 100
                if daily_pct <= DAILY_LOSS_LIMIT:
                    log.warning("🛑 Daily loss limit %.1f%% — stopped for today", daily_pct)
                    tg(f"🛑 DAILY STOP\nDown {daily_pct:.1f}% today\nBot paused until tomorrow")
                    time.sleep(3600)
                    continue

            # ── Friday cutoff ──────────────────────────────────────
            if is_friday_cutoff():
                log.info("Friday close — no new scalps")
                time.sleep(300)
                continue

            # ── Daily trade cap ────────────────────────────────────
            if trades_today >= MAX_TRADES_DAY:
                log.info("Max %d trades reached today — resting", MAX_TRADES_DAY)
                time.sleep(60)
                continue

            # ── Kill zone gate ─────────────────────────────────────
            in_kz, kz_name = in_kill_zone()
            if not in_kz:
                log.info("[%s] ⏳ No kill zone — next: %s", ist_now(), next_kill_zone_str())
                time.sleep(60)
                continue

            # ── Manage existing trades ─────────────────────────────
            manage_open_trades()

            # ── Max open trades gate ───────────────────────────────
            if open_trade_count() >= MAX_OPEN:
                time.sleep(LOOP_INTERVAL)
                continue

            # ── Scan symbols ───────────────────────────────────────
            for symbol, cfg in SYMBOLS.items():
                mt5_sym = cfg["mt5_symbol"]

                if balance < cfg["min_balance"]:
                    log.info("%s: Balance $%.2f below min $%d — skip",
                             symbol, balance, cfg["min_balance"])
                    continue

                if has_position(mt5_sym):
                    continue

                # 15M bias
                bias = get_bias_15m(mt5_sym)
                if not bias:
                    log.info("%s: No clear 15M bias — skip", symbol)
                    continue

                # 1M signal
                direction, sl, tp = get_1m_entry(mt5_sym, bias)
                if not direction:
                    continue

                # Lot size
                tick = mt5.symbol_info_tick(mt5_sym)
                if not tick:
                    continue
                entry_price = tick.ask if direction == "BUY" else tick.bid
                sl_pts = abs(entry_price - sl)
                if sl_pts <= 0:
                    continue

                lot = calc_lot(balance, sl_pts, cfg)

                log.info("[%s] 🎯 SIGNAL | %s %s | Bias=%s | KZ=%s | Lot=%.2f | SL_dist=%.2f",
                         ist_now(), direction, symbol, bias, kz_name, lot, sl_pts)

                # Place order
                ticket = place_market_order(mt5_sym, direction, lot, sl, tp)
                if ticket:
                    trades_today += 1
                    risk_usd = sl_pts * lot * cfg["contract_size"]
                    reward_usd = risk_usd * RR_RATIO
                    tg(
                        f"⚡ SCALP #{trades_today}\n"
                        f"{direction} {symbol}\n"
                        f"Lot: {lot} | KZ: {kz_name}\n"
                        f"Risk: ${risk_usd:.2f} → Reward: ${reward_usd:.2f}\n"
                        f"Balance: ${balance:.2f}"
                    )
                    time.sleep(10)  # pause briefly after entry

            time.sleep(LOOP_INTERVAL)

        except KeyboardInterrupt:
            log.info("Bot stopped by user")
            balance = get_balance()
            pnl     = balance - balance_start
            pct     = (pnl / balance_start * 100) if balance_start > 0 else 0
            summary = (
                f"⏹ SCALP BOT STOPPED\n"
                f"Final: ${balance:.2f}\n"
                f"P&L: ${pnl:+.2f} ({pct:+.1f}%)\n"
                f"Trades today: {trades_today}"
            )
            log.info(summary)
            tg(summary)
            break
        except Exception as e:
            log.error("Loop error: %s", e, exc_info=True)
            time.sleep(30)

    mt5.shutdown()


if __name__ == "__main__":
    run()
