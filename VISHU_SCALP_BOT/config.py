"""
VISHU SCALP BOT — High Frequency Config
Enter fast, exit in seconds, repeat all day
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
        "force_min_lot": False,
    },
    "BTCUSD": {
        "mt5_symbol":    "BTCUSDm",
        "contract_size": 1,
        "min_lot":       0.01,
        "lot_step":      0.01,
        "max_lot":       0.1,
        "digits":        2,
        "min_balance":   30,
        "force_min_lot": False,
    },
    "XAUUSD": {
        "mt5_symbol":    "XAUUSDm",
        "contract_size": 100,
        "min_lot":       0.01,
        "lot_step":      0.01,
        "max_lot":       0.01,
        "digits":        2,
        "min_balance":   30,
        "force_min_lot": True,
    },
    "XAGUSD": {
        "mt5_symbol":    "XAGUSDm",
        "contract_size": 5000,
        "min_lot":       0.01,
        "lot_step":      0.01,
        "max_lot":       0.01,
        "digits":        3,
        "min_balance":   30,
        "force_min_lot": True,
    },
}

# ── Risk ───────────────────────────────────────────────────────────
RISK_PERCENT     = 1.0    # 1% per trade
DAILY_LOSS_LIMIT = -6.0   # stop at -6% for the day
MAX_OPEN         = 2      # 2 trades open at once across all symbols
RR_RATIO         = 1.0    # 1:1 RR — small TP hit fast in seconds

# ── Scalp Speed Settings ───────────────────────────────────────────
ATR_PERIOD      = 5       # very short ATR — reacts to latest price action
ATR_SL_MULT     = 1.0    # SL = 1.0 × ATR — enough to clear broker min distance
EMA_FAST        = 3       # faster EMA cross signals
EMA_SLOW        = 8       # faster EMA slow
RSI_PERIOD      = 7
# RSI logic — only enter when price has ROOM to move in direction:
# BUY  → RSI must be LOW  (20–45) — oversold, room to bounce UP
# SELL → RSI must be HIGH (55–80) — overbought, room to fall DOWN
RSI_BUY_MIN     = 20      # don't buy if RSI below 20 (too crashed, wait)
RSI_BUY_MAX     = 45      # only buy when RSI < 45 (oversold zone)
RSI_SELL_MIN    = 55      # only sell when RSI > 55 (overbought zone)
RSI_SELL_MAX    = 80      # don't sell if RSI above 80 (too spiked, wait)

# ── Time Exit — close trade after N minutes if TP/SL not hit ──────
# Prevents trades sitting open for hours eating spread
MAX_TRADE_MINUTES = 5     # close trade after 5 minutes regardless

# ── Breakeven + Trail ──────────────────────────────────────────────
BREAKEVEN_PCT   = 0.5
TRAIL_PCT       = 0.8
TRAIL_MULT      = 0.5

# ── Dual TF confirm ────────────────────────────────────────────────
REQUIRE_1H_CONFIRM = True   # 1H + 15M must agree

# ── Sessions (label only — no blocking, bot runs 24/7) ────────────
KILL_ZONES = [
    {"name": "Asian Open",   "start": (0,  0),  "end": (2,  0)},
    {"name": "London Open",  "start": (7,  0),  "end": (9,  30)},
    {"name": "NY Open",      "start": (12, 0),  "end": (15, 0)},
    {"name": "London Close", "start": (15, 0),  "end": (16, 30)},
]

# ── Bot Speed ──────────────────────────────────────────────────────
MAGIC_NUMBER    = 20260327
LOOP_INTERVAL   = 5        # scan every 5 seconds — high frequency
LOG_FILE        = "scalp_bot.log"
