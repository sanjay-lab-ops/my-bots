"""
VISHU SCALP BOT — Configuration
Strategy : 1H + 15M bias agreement → 1M EMA cross entry
Pairs    : ETHUSD, BTCUSD, XAUUSD, XAGUSD
"""

import os
from dotenv import load_dotenv
load_dotenv()

# ── MT5 Credentials ────────────────────────────────────────────────
MT5_LOGIN    = int(os.getenv("MT5_LOGIN", "0"))
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
MT5_SERVER   = os.getenv("MT5_SERVER", "")

# ── Telegram ───────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ── Symbols ────────────────────────────────────────────────────────
SYMBOLS = {
    "ETHUSD": {
        "mt5_symbol":    "ETHUSDm",
        "contract_size": 1,
        "min_lot":       0.1,
        "lot_step":      0.1,
        "max_lot":       2.0,
        "digits":        2,
        "min_balance":   30,
    },
    "BTCUSD": {
        "mt5_symbol":    "BTCUSDm",
        "contract_size": 1,
        "min_lot":       0.01,
        "lot_step":      0.01,
        "max_lot":       0.1,
        "digits":        2,
        "min_balance":   30,
    },
    "XAUUSD": {
        "mt5_symbol":    "XAUUSDm",
        "contract_size": 100,
        "min_lot":       0.01,
        "lot_step":      0.01,
        "max_lot":       0.01,   # capped at min lot — gold too expensive per point
        "digits":        2,
        "min_balance":   30,
        "force_min_lot": True,   # always use min lot regardless of calc
    },
    "XAGUSD": {
        "mt5_symbol":    "XAGUSDm",
        "contract_size": 5000,
        "min_lot":       0.01,
        "lot_step":      0.01,
        "max_lot":       0.01,   # capped at min lot
        "digits":        3,
        "min_balance":   30,
        "force_min_lot": True,
    },
}

# ── Risk ───────────────────────────────────────────────────────────
RISK_PERCENT      = 1.0     # 1% per trade
DAILY_LOSS_LIMIT  = -6.0    # stop at -6% for the day
MAX_TRADES_DAY    = 9999    # no limit — trades as many signals as appear
MAX_OPEN          = 1       # only 1 open trade at a time (safety on $50)
RR_RATIO          = 1.5     # 1.5:1 RR — quick scalp TP

# ── Loss Lock ──────────────────────────────────────────────────────
# After ANY losing trade, bot pauses this many minutes before next entry.
# Prevents chasing losses and revenge trading.
LOCK_AFTER_LOSS_MINUTES = 30

# ── Indicators ─────────────────────────────────────────────────────
ATR_PERIOD    = 10
ATR_SL_MULT   = 1.2      # tight SL for scalping
EMA_FAST      = 5
EMA_SLOW      = 20
RSI_PERIOD    = 14
RSI_BUY_MAX   = 63        # stricter — no buy if RSI overbought
RSI_SELL_MIN  = 37        # stricter — no sell if RSI oversold

# ── Confirmation — BOTH timeframes must agree for entry ────────────
# 1H EMA bias + 15M EMA bias must point same direction
# Eliminates low-confidence trades — only takes high-probability setups
REQUIRE_1H_CONFIRM = True

# ── Trade Manager ──────────────────────────────────────────────────
BREAKEVEN_PCT = 0.5
TRAIL_PCT     = 0.75
TRAIL_MULT    = 0.6

# ── Kill Zones (UTC) ───────────────────────────────────────────────
KILL_ZONES = [
    {"name": "London Open",  "start": (7,  0),  "end": (9,  30)},  # 12:30–15:00 IST
    {"name": "NY Open",      "start": (12, 0),  "end": (15, 0)},   # 17:30–20:30 IST
    {"name": "London Close", "start": (15, 0),  "end": (16, 30)},  # 20:30–22:00 IST
]

# ── Bot ────────────────────────────────────────────────────────────
MAGIC_NUMBER  = 20260327
LOOP_INTERVAL = 15
LOG_FILE      = "scalp_bot.log"
