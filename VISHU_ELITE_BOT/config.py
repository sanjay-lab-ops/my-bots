"""
VISHU ELITE BOT — Central Configuration
All times in UTC. IST = UTC + 5:30
Edit this file to tune the bot. Do NOT hardcode credentials here — use .env
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── MT5 Credentials (loaded from .env) ───────────────────────────
MT5_LOGIN    = int(os.getenv("MT5_LOGIN", "0"))
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
MT5_SERVER   = os.getenv("MT5_SERVER", "")

# ── Instruments ──────────────────────────────────────────────────
SYMBOLS = {
    "BTCUSD": {
        "mt5_symbol":    "BTCUSDm",
        "contract_size": 1,
        "min_lot":       0.01,
        "max_lot":       1.0,
        "lot_step":      0.01,
        "pip_value":     1.0,
        "atr_min":       200,
    },
    "ETHUSD": {
        "mt5_symbol":    "ETHUSDm",
        "contract_size": 1,
        "min_lot":       0.1,
        "max_lot":       10.0,
        "lot_step":      0.1,
        "pip_value":     1.0,
        "atr_min":       10,
    },
    "XAUUSD": {
        "mt5_symbol":    "XAUUSDm",
        "contract_size": 100,
        "min_lot":       0.01,
        "max_lot":       50.0,
        "lot_step":      0.01,
        "pip_value":     1.0,
        "atr_min":       20,
    },
    "XAGUSD": {
        "mt5_symbol":    "XAGUSDm",
        "contract_size": 5000,
        "min_lot":       0.01,
        "max_lot":       50.0,
        "lot_step":      0.01,
        "pip_value":     1.0,
        "atr_min":       0.1,
    },
}

# ── Session Windows (UTC) ─────────────────────────────────────────
SESSIONS = {
    "BTCUSD": [
        {"start_utc": (2,  0),  "end_utc": (4,  0),  "label": "BTC Asian Close (07:30–09:30 IST)"},
        {"start_utc": (9,  0),  "end_utc": (11, 30), "label": "BTC Pre-NY (14:30–17:00 IST)"},
        {"start_utc": (13, 30), "end_utc": (16, 0),  "label": "BTC NY Open (19:00–21:30 IST)"},
    ],
    "ETHUSD": [
        {"start_utc": (2,  0),  "end_utc": (4,  0),  "label": "ETH Asian Close (07:30–09:30 IST)"},
        {"start_utc": (9,  0),  "end_utc": (11, 30), "label": "ETH Pre-NY (14:30–17:00 IST)"},
        {"start_utc": (13, 30), "end_utc": (16, 0),  "label": "ETH NY Open (19:00–21:30 IST)"},
    ],
    "XAUUSD": [
        {"start_utc": (5, 0),   "end_utc": (8, 30),  "label": "Gold Pre-London+London (10:30–14:00 IST)"},
        {"start_utc": (13, 30), "end_utc": (16, 0),  "label": "Gold NY Open (19:00–21:30 IST)"},
    ],
    "XAGUSD": [
        {"start_utc": (5, 0),   "end_utc": (8, 30),  "label": "Silver Pre-London+London (10:30–14:00 IST)"},
        {"start_utc": (13, 30), "end_utc": (16, 0),  "label": "Silver NY Open (19:00–21:30 IST)"},
    ],
}

# Last session end time per symbol (UTC) — used for daily summary and auto-stop
LAST_SESSION_END = {
    "BTCUSD": (16, 0),
    "ETHUSD": (16, 0),
    "XAUUSD": (16, 0),
    "XAGUSD": (16, 0),
}

# ── Indicator Periods ─────────────────────────────────────────────
ATR_PERIOD  = 14
RSI_PERIOD  = 14
EMA_FAST    = 5
EMA_SLOW    = 20

# ── Risk Parameters ───────────────────────────────────────────────
ATR_SL_MULT      = 1.5    # SL = ATR × 1.5
RR_RATIO         = 2.0    # TP = SL × 2.0  (2:1 R:R)
DAILY_LOSS_LIMIT = -9999.0   # Disabled — let trades run freely
MAX_TRADES_DAY   = 4      # total across both pairs per day
MAX_TRADES_PAIR  = 2      # per pair per day

# ── Manual Mode ───────────────────────────────────────────────────
# True  → bot sends Telegram SIGNAL ALERT but does NOT auto-execute
# False → bot auto-executes as normal (default)
MANUAL_MODE      = False  # Auto-execute trades directly

# ── Trade Manager ─────────────────────────────────────────────────
BREAKEVEN_ATR_MULT = 1.5  # move SL to entry when profit reaches 1.5× SL distance
TRAIL_ATR_MULT     = 1.5  # start trailing when profit > 1.5× SL distance
TRAIL_DISTANCE_MULT = 1.0 # trail SL at 1× ATR below/above price

# ── Telegram ──────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ── Candle Counts ─────────────────────────────────────────────────
CANDLE_COUNT_4H  = 200
CANDLE_COUNT_1H  = 200
CANDLE_COUNT_15M = 300
CANDLE_COUNT_1M  = 120

# ── Bot Loop ──────────────────────────────────────────────────────
LOOP_INTERVAL_SECONDS  = 60
TRADE_MANAGER_INTERVAL = 30   # seconds between trade manager checks

# ── Logging ───────────────────────────────────────────────────────
LOG_FILE = "elite_bot.log"

# ── Minimum balance required to trade each symbol ────────────────
MIN_BALANCE_TO_TRADE = {
    "ETHUSD": 50,    # safe from $50
    "BTCUSD": 50,    # safe from $50
    "XAUUSD": 50,    # safe from $50
    "XAGUSD": 200,   # Silver blocked until $200 balance
}

# ── Magic Number (unique bot identifier in MT5) ───────────────────
MAGIC_NUMBER = 20260319

# ── Forced Bias Override ──────────────────────────────────────────
# Set to "buy", "sell", or "auto" per symbol.
# "auto" = bot uses its own analysis (default)
# "buy"  = bot only takes BUY trades for that symbol today
# "sell" = bot only takes SELL trades for that symbol today
FORCED_BIAS = {
    "BTCUSD": "auto",
    "ETHUSD": "auto",
    "XAUUSD": "auto",
    "XAGUSD": "auto",
}
