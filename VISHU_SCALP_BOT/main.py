"""
VISHU SCALP BOT — Live $50 Account
====================================
Entry  : 1H bias + 15M bias BOTH agree → 1M EMA5×EMA20 cross
Filter : RSI not extreme | Kill zone only
Exit   : 1.5 RR | Breakeven at 50% | Trail at 75%
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


# ── MT5 ────────────────────────────────────────────────────────────
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
    now_m = datetime.now(timezone.utc)
    m     = now_m.hour * 60 + now_m.minute
    for kz in KILL_ZONES:
        s = kz["start"][0] * 60 + kz["start"][1]
        e = kz["end"][0]   * 60 + kz["end"][1]
        if s <= m <= e:
            return True, kz["name"]
    return False, ""


def next_kz_str() -> str:
    now   = datetime.now(timezone.utc)
    now_m = now.hour * 60 + now.minute
    for kz in KILL_ZONES:
        s = kz["start"][0] * 60 + kz["start"][1]
        if s > now_m:
            mins  = s - now_m
            ist_h = (kz["start"][0] + 5) % 24
            ist_m = kz["start"][1] + 30
            if ist_m >= 60:
                ist_h += 1
                ist_m -= 60
            return f"{kz['name']} at {ist_h:02d}:{ist_m:02d} IST (in {mins}m)"
    return "London Open tomorrow"


def is_friday_cutoff() -> bool:
    now = datetime.now(timezone.utc)
    return now.weekday() == 4 and now.hour >= 16


# ── Bias ───────────────────────────────────────────────────────────
def get_bias(mt5_sym: str, tf: int, count: int = 60) -> str | None:
    df = get_candles(mt5_sym, tf, count)
    if df is None:
        return None
    last = df.iloc[-1]
    if last["ema_fast"] > last["ema_slow"]:
        return "BUY"
    if last["ema_fast"] < last["ema_slow"]:
        return "SELL"
    return None


def get_confirmed_bias(mt5_sym: str) -> str | None:
    """Both 1H and 15M must agree. Returns direction or None."""
    bias_1h  = get_bias(mt5_sym, mt5.TIMEFRAME_H1,  80)
    bias_15m = get_bias(mt5_sym, mt5.TIMEFRAME_M15, 60)
    if not bias_1h or not bias_15m:
        return None
    if bias_1h == bias_15m:
        return bias_1h   # both agree — high confidence
    return None          # disagreement — skip this symbol


# ── 1M Entry Signal ────────────────────────────────────────────────
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


# ── Lot ────────────────────────────────────────────────────────────
def calc_lot(balance: float, sl_pts: float, cfg: dict) -> float:
    if cfg.get("force_min_lot"):
        return cfg["min_lot"]
    risk_amt = balance * (RISK_PERCENT / 100)
    raw      = risk_amt / (sl_pts * cfg["contract_size"])
    step     = cfg["lot_step"]
    lot      = round(round(raw / step) * step, 2)
    return max(cfg["min_lot"], min(lot, cfg["max_lot"]))


# ── Position Checks ────────────────────────────────────────────────
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
def place_order(mt5_sym: str, direction: str, lot: float,
                sl: float, tp: float) -> int | None:
    tick = mt5.symbol_info_tick(mt5_sym)
    if not tick:
        return None

    info       = mt5.symbol_info(mt5_sym)
    price      = tick.ask if direction == "BUY" else tick.bid
    order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL
    filling    = mt5.ORDER_FILLING_IOC
    if info and info.filling_mode & mt5.ORDER_FILLING_FOK:
        filling = mt5.ORDER_FILLING_FOK
    digits = info.digits if info else 2

    request = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       mt5_sym,
        "volume":       lot,
        "type":         order_type,
        "price":        price,
        "sl":           round(sl, digits),
        "tp":           round(tp, digits),
        "deviation":    20,
        "magic":        MAGIC_NUMBER,
        "comment":      "SCALP",
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": filling,
    }

    result = mt5.order_send(request)
    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
        log.info("✅ FILLED | %s %s | Lot=%.2f | Entry=%.5f | SL=%.5f | TP=%.5f | #%d",
                 direction, mt5_sym, lot, result.price, sl, tp, result.order)
        return result.order
    else:
        code = result.retcode if result else "N/A"
        log.error("❌ Order failed | %s %s | Code=%s", direction, mt5_sym, code)
        return None


# ── Trade Manager ──────────────────────────────────────────────────
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

        is_long     = pos.type == mt5.ORDER_TYPE_BUY
        profit_dist = (pos.price_current - pos.price_open) if is_long else (pos.price_open - pos.price_current)
        progress    = profit_dist / tp_dist if tp_dist > 0 else 0

        if progress <= 0:
            continue

        info   = mt5.symbol_info(pos.symbol)
        digits = info.digits if info else 2
        new_sl = None

        # Breakeven
        if progress >= BREAKEVEN_PCT:
            be = pos.price_open + 0.1 if is_long else pos.price_open - 0.1
            if (is_long and pos.sl < pos.price_open) or (not is_long and pos.sl > pos.price_open):
                new_sl = be
                log.info("🔒 BREAKEVEN | %s #%d", pos.symbol, pos.ticket)

        # Trail
        if progress >= TRAIL_PCT:
            tick = mt5.symbol_info_tick(pos.symbol)
            if tick:
                trail_dist = sl_dist * TRAIL_MULT
                candidate  = (tick.bid - trail_dist) if is_long else (tick.ask + trail_dist)
                if is_long and candidate > pos.sl and (new_sl is None or candidate > new_sl):
                    new_sl = candidate
                    log.info("📈 TRAIL | %s #%d | SL → %.5f", pos.symbol, pos.ticket, new_sl)
                elif not is_long and candidate < pos.sl and (new_sl is None or candidate < new_sl):
                    new_sl = candidate
                    log.info("📉 TRAIL | %s #%d | SL → %.5f", pos.symbol, pos.ticket, new_sl)

        if new_sl and abs(new_sl - pos.sl) > 0.001:
            mt5.order_send({
                "action":   mt5.TRADE_ACTION_SLTP,
                "position": pos.ticket,
                "sl":       round(new_sl, digits),
                "tp":       pos.tp,
            })


# ── Time-based Exit — close trades open too long ───────────────────
def _close_stale_trades():
    """Close any bot trade open longer than MAX_TRADE_MINUTES — grab what we have."""
    positions = mt5.positions_get()
    if not positions:
        return
    now = datetime.now(timezone.utc)
    for pos in positions:
        if pos.magic != MAGIC_NUMBER:
            continue
        open_time = datetime.fromtimestamp(pos.time, tz=timezone.utc)
        age_mins  = (now - open_time).total_seconds() / 60
        if age_mins >= MAX_TRADE_MINUTES:
            tick = mt5.symbol_info_tick(pos.symbol)
            if not tick:
                continue
            close_price = tick.bid if pos.type == mt5.ORDER_TYPE_BUY else tick.ask
            req = {
                "action":       mt5.TRADE_ACTION_DEAL,
                "symbol":       pos.symbol,
                "volume":       pos.volume,
                "type":         mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY,
                "price":        close_price,
                "position":     pos.ticket,
                "deviation":    20,
                "magic":        MAGIC_NUMBER,
                "comment":      "SCALP_TIMEOUT",
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            result = mt5.order_send(req)
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                log.info("⏱ TIMEOUT CLOSE | %s #%d | P&L=$%.2f | Age=%.1fmin",
                         pos.symbol, pos.ticket, pos.profit, age_mins)
                tg(f"⏱ TIMEOUT EXIT\n{pos.symbol} #{pos.ticket}\n"
                   f"P&L: ${pos.profit:.2f} | Was open {age_mins:.1f}min")


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


# ── Main ───────────────────────────────────────────────────────────
def run():
    log.info("=" * 60)
    log.info("  VISHU SCALP BOT — ALL 4 PAIRS")
    log.info("  ETH | BTC | XAU | XAG")
    log.info("  Confirm: 1H + 15M bias must agree")
    log.info("=" * 60)

    if not connect_mt5():
        return

    balance_start = get_balance()
    today_date    = datetime.now(timezone.utc).date()
    trades_today  = 0

    tg(
        f"🚀 SCALP BOT STARTED — ALL 4 PAIRS\n"
        f"Balance: ${balance_start:.2f}\n"
        f"Risk: {RISK_PERCENT}%/trade | Daily stop: {DAILY_LOSS_LIMIT}%\n"
        f"RR: 1:{RR_RATIO} | Confirmation: 1H + 15M agree"
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
                tg(f"🌅 New day | Balance: ${balance_start:.2f}")

            balance = get_balance()

            # ── Daily loss guard ───────────────────────────────────
            if balance_start > 0:
                daily_pct = (balance - balance_start) / balance_start * 100
                if daily_pct <= DAILY_LOSS_LIMIT:
                    log.warning("🛑 Daily loss limit %.1f%% hit — stopped for today", daily_pct)
                    tg(f"🛑 DAILY STOP\nDown {daily_pct:.1f}% today\nPaused until tomorrow")
                    time.sleep(3600)
                    continue

            # ── Kill zone label (for logging only — no blocking) ───────
            in_kz, kz_name = in_kill_zone()
            kz_label = kz_name if in_kz else "24/7"

            # ── Manage existing trades ─────────────────────────────
            manage_open_trades()

            # ── Max open trades gate ───────────────────────────────
            if open_trade_count() >= MAX_OPEN:
                time.sleep(LOOP_INTERVAL)
                continue

            # ── Time-based exit — close stale trades ───────────────
            _close_stale_trades()

            # ── Scan all 4 symbols — full analysis every tick ──────────
            log.info("── SCAN [%s] | %s | Balance: $%.2f ──",
                     ist_now(), kz_label, balance)
            for symbol, cfg in SYMBOLS.items():
                mt5_sym = cfg["mt5_symbol"]

                # Balance check
                if balance < cfg["min_balance"]:
                    log.info("  %s: balance $%.2f below min — skip", symbol, balance)
                    continue

                # Already in trade
                if has_position(mt5_sym):
                    pos = mt5.positions_get(symbol=mt5_sym)
                    if pos:
                        p = pos[0]
                        log.info("  %s: OPEN trade #%d | P&L: $%.2f | Price: %.5f",
                                 symbol, p.ticket, p.profit, p.price_current)
                    continue

                # Get raw bias per timeframe
                bias_1h  = get_bias(mt5_sym, mt5.TIMEFRAME_H1,  80)
                bias_15m = get_bias(mt5_sym, mt5.TIMEFRAME_M15, 60)

                # Get indicator values for analysis
                df1h  = get_candles(mt5_sym, mt5.TIMEFRAME_H1,  80)
                df15m = get_candles(mt5_sym, mt5.TIMEFRAME_M15, 60)
                df1m  = get_candles(mt5_sym, mt5.TIMEFRAME_M1,  40)

                tick = mt5.symbol_info_tick(mt5_sym)
                price = tick.ask if tick else 0

                if df1h is not None and df15m is not None and df1m is not None:
                    rsi_val  = df1m.iloc[-1]["rsi"]
                    atr_val  = df1m.iloc[-1]["atr"]
                    e5_1h    = df1h.iloc[-1]["ema_fast"]
                    e20_1h   = df1h.iloc[-1]["ema_slow"]
                    e5_15m   = df15m.iloc[-1]["ema_fast"]
                    e20_15m  = df15m.iloc[-1]["ema_slow"]
                    e5_1m    = df1m.iloc[-1]["ema_fast"]
                    e20_1m   = df1m.iloc[-1]["ema_slow"]
                    cross_1m = "↑CROSS" if (df1m.iloc[-2]["ema_fast"] <= df1m.iloc[-2]["ema_slow"]
                                             and e5_1m > e20_1m) else \
                               "↓CROSS" if (df1m.iloc[-2]["ema_fast"] >= df1m.iloc[-2]["ema_slow"]
                                             and e5_1m < e20_1m) else "no cross"

                    log.info("  %s | Price=%.5f | RSI=%.1f | ATR=%.5f",
                             symbol, price, rsi_val, atr_val)
                    log.info("    1H  EMA5=%.5f EMA20=%.5f → %s",
                             e5_1h, e20_1h, bias_1h or "NEUTRAL")
                    log.info("    15M EMA5=%.5f EMA20=%.5f → %s",
                             e5_15m, e20_15m, bias_15m or "NEUTRAL")
                    log.info("    1M  EMA5=%.5f EMA20=%.5f → %s",
                             e5_1m, e20_1m, cross_1m)

                # Dual confirmation check
                if not bias_1h or not bias_15m:
                    log.info("    ❌ SKIP — no clear bias on 1H or 15M")
                    continue
                if bias_1h != bias_15m:
                    log.info("    ❌ SKIP — 1H=%s vs 15M=%s (conflict)", bias_1h, bias_15m)
                    continue

                bias = bias_1h
                log.info("    ✅ BIAS CONFIRMED — both 1H+15M = %s", bias)

                # 1M entry signal
                direction, sl, tp = get_1m_entry(mt5_sym, bias)
                if not direction:
                    log.info("    ⏳ WAITING — no 1M cross yet (bias ready, watching...)")
                    continue

                # RSI check result
                if df1m is not None:
                    rsi_val = df1m.iloc[-1]["rsi"]
                    log.info("    RSI=%.1f — %s", rsi_val,
                             "OK" if (direction == "BUY" and rsi_val < RSI_BUY_MAX) or
                                     (direction == "SELL" and rsi_val > RSI_SELL_MIN)
                             else "BLOCKED by RSI")

                if not tick:
                    continue
                entry_price = tick.ask if direction == "BUY" else tick.bid
                sl_pts      = abs(entry_price - sl)
                if sl_pts <= 0:
                    continue

                lot = calc_lot(balance, sl_pts, cfg)
                risk_usd   = sl_pts * lot * cfg["contract_size"]
                reward_usd = risk_usd * RR_RATIO

                log.info("    🎯 ENTRY | %s | Lot=%.2f | Entry=%.5f | SL=%.5f | TP=%.5f",
                         direction, lot, entry_price, sl, tp)
                log.info("    💰 Risk=$%.2f → Target=$%.2f (1:%.1f RR)",
                         risk_usd, reward_usd, RR_RATIO)

                ticket = place_order(mt5_sym, direction, lot, sl, tp)
                if ticket:
                    trades_today += 1
                    tg(
                        f"⚡ SCALP #{trades_today} — {direction} {symbol}\n"
                        f"Entry: {entry_price:.5f} | Lot: {lot}\n"
                        f"SL: {sl:.5f} | TP: {tp:.5f}\n"
                        f"Risk: ${risk_usd:.2f} → Target: ${reward_usd:.2f}\n"
                        f"1H: {bias_1h} | 15M: {bias_15m} | RSI: {rsi_val:.1f}\n"
                        f"Session: {kz_label} | Balance: ${balance:.2f}"
                    )
                    break  # placed — continue scanning other symbols next tick

            time.sleep(LOOP_INTERVAL)

        except KeyboardInterrupt:
            balance = get_balance()
            pnl     = balance - balance_start
            pct     = (pnl / balance_start * 100) if balance_start > 0 else 0
            msg     = (f"⏹ SCALP BOT STOPPED\n"
                       f"Final: ${balance:.2f} | P&L: ${pnl:+.2f} ({pct:+.1f}%)\n"
                       f"Trades: {trades_today}")
            log.info(msg)
            tg(msg)
            break
        except Exception as e:
            log.error("Loop error: %s", e, exc_info=True)
            time.sleep(30)

    mt5.shutdown()


if __name__ == "__main__":
    run()
