"""
VISHU SMC BOT — Central Configuration
Smart Money Concepts | Institutional Execution | Compounding Capital
Pairs: BTCUSD, ETHUSD, XAUUSD, XAGUSD
"""

import os
from dotenv import load_dotenv
load_dotenv()

# ── MT5 Credentials ───────────────────────────────────────────────
MT5_LOGIN    = int(os.getenv("MT5_LOGIN", "0"))
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
MT5_SERVER   = os.getenv("MT5_SERVER", "")

# ── Trading Pairs ─────────────────────────────────────────────────
SYMBOLS = {
    "BTCUSD": {
        "mt5_symbol":    "BTCUSDm",
        "contract_size": 1,
        "min_lot":       0.01,
        "max_lot":       1.0,
        "lot_step":      0.01,
        "atr_min":       200,    # skip if 4H ATR below this (too choppy)
        "digits":        2,
    },
    "ETHUSD": {
        "mt5_symbol":    "ETHUSDm",
        "contract_size": 1,
        "min_lot":       0.1,
        "max_lot":       10.0,
        "lot_step":      0.1,
        "atr_min":       10,
        "digits":        2,
    },
    "XAUUSD": {
        "mt5_symbol":    "XAUUSDm",
        "contract_size": 100,
        "min_lot":       0.01,
        "max_lot":       50.0,
        "lot_step":      0.01,
        "atr_min":       5,
        "digits":        2,
    },
    "XAGUSD": {
        "mt5_symbol":    "XAGUSDm",
        "contract_size": 5000,   # 5000 oz per lot on Exness
        "min_lot":       0.01,
        "max_lot":       50.0,
        "lot_step":      0.01,
        "atr_min":       0.1,
        "digits":        3,
    },
}

# ── Risk / Compounding ────────────────────────────────────────────
RISK_PERCENT     = 1.5     # % of CURRENT balance per trade — compounds automatically
DAILY_LOSS_LIMIT = -6.0      # Stop trading today if down 6% (3 losses at 2% each)
RR_RATIO         = 2.5     # 2.5:1 reward:risk (institutional standard)

# ── Manual Mode ───────────────────────────────────────────────────
# True  → bot sends Telegram SIGNAL ALERT but does NOT auto-execute
# False → bot auto-executes as normal (default)
MANUAL_MODE      = False  # Auto-execute trades directly

# ── SMC Parameters ────────────────────────────────────────────────
OB_LOOKBACK     = 60       # candles back to search for order blocks
FVG_MIN_RATIO   = 0.25     # FVG gap must be > 25% of ATR to be valid
SWING_LOOKBACK  = 10       # candles each side to confirm swing high/low
LIQUIDITY_EQ    = 0.05     # % tolerance for "equal" highs/lows
SL_BUFFER_PCT   = 0.10     # SL placed 0.10% beyond OB boundary

# ── Session Windows (UTC) — Bot 3 is 24/7 (OBs/FVGs form at any time)
# Kill Zones below define highest-probability entry windows within each scan
SESSIONS = {
    "BTCUSD": [{"start_utc": (0, 0), "end_utc": (23, 59)}],
    "ETHUSD": [{"start_utc": (0, 0), "end_utc": (23, 59)}],
    "XAUUSD": [{"start_utc": (0, 0), "end_utc": (23, 59)}],
    "XAGUSD": [{"start_utc": (0, 0), "end_utc": (23, 59)}],
}

# ── Kill Zones (UTC) — highest institutional volume ───────────────
KILL_ZONES = {
    "Asian Open":   {"start": (0,  0), "end": (2,  0)},  # 5:30–7:30 AM IST
    "London Open":  {"start": (2,  0), "end": (5,  0)},  # 7:30–10:30 AM IST
    "NY Open":      {"start": (7,  0), "end": (10, 0)},  # 12:30–3:30 PM IST
    "London Close": {"start": (10, 0), "end": (12, 0)},  # 3:30–5:30 PM IST
    "NY Session":   {"start": (13, 0), "end": (17, 0)},  # 6:30–10:30 PM IST
}

# ── Compounding tracker file ──────────────────────────────────────
BALANCE_FILE = "running_balance.json"

# ── Indicators ───────────────────────────────────────────────────
ATR_PERIOD = 14

# ── Telegram ─────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ── MT5 Bot Identifier ───────────────────────────────────────────
MAGIC_NUMBER = 20260320   # Bot 3 SMC — unique, different from Bot 2 (20260319)

# ── Minimum balance required to trade each symbol ────────────────
# Protects small live accounts from oversized risk.
# Bot skips a symbol until balance grows above its threshold.
# ETH is cheapest (0.1 lot, tight SL) — safe from $20.
# BTC/Gold/Silver need larger balance due to wide SLs.
MIN_BALANCE_TO_TRADE = {
    "ETHUSD": 50,    # safe from $50
    "BTCUSD": 50,    # safe from $50
    "XAUUSD": 50,    # Hard risk cap enforced in compounding.py — blocks trade if min lot > 50% balance
    "XAGUSD": 200,   # Silver blocked until $200 balance
}

# ── Forced Bias Override ──────────────────────────────────────────
# Set to "buy", "sell", or "auto" per symbol.
# "auto" = bot uses SMC analysis (default)
# "buy"  = bot only takes BUY setups (OB/FVG must still confirm)
# "sell" = bot only takes SELL setups (OB/FVG must still confirm)
FORCED_BIAS = {
    "BTCUSD": "auto",
    "ETHUSD": "auto",
    "XAUUSD": "auto",
    "XAGUSD": "auto",
}
