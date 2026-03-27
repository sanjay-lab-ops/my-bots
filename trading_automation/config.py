"""
Central configuration — edit these values to tune the bot.
All times stored in UTC (IST = UTC + 5h30m).
"""

import os
from dotenv import load_dotenv
load_dotenv()

# ── MT5 Credentials (loaded from .env) ──────────────────────────
MT5_LOGIN    = int(os.getenv("MT5_LOGIN", "0"))
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
MT5_SERVER   = os.getenv("MT5_SERVER", "")

# ── Telegram (loaded from .env) ──────────────────────────────────
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ── Instruments ─────────────────────────────────────────────────
SYMBOLS = {
    "BTCUSD": {
        "mt5_symbol": "BTCUSDm",
        "pip_value": 1.0,
        "contract_size": 1,
        "min_lot": 0.01,
        "max_lot": 1.0,
        "lot_step": 0.01,
    },
    "ETHUSD": {
        "mt5_symbol": "ETHUSDm",
        "pip_value": 1.0,
        "contract_size": 1,
        "min_lot": 0.1,
        "max_lot": 10.0,
        "lot_step": 0.1,
    },
    "XAUUSD": {
        "mt5_symbol": "XAUUSDm",
        "pip_value": 1.0,
        "contract_size": 100,
        "min_lot": 0.01,
        "max_lot": 50.0,
        "lot_step": 0.01,
    },
    "XAGUSD": {
        "mt5_symbol": "XAGUSDm",
        "pip_value": 1.0,
        "contract_size": 5000,
        "min_lot": 0.01,
        "max_lot": 50.0,
        "lot_step": 0.01,
    },
}

# ── Session Windows (UTC times) ──────────────────────────────────
SESSIONS = {
    "BTCUSD": [
        {"start_utc": (3, 30),  "end_utc": (6,  0),  "label": "BTC Morning (09:00–11:30 IST)"},
        {"start_utc": (12, 0),  "end_utc": (16, 0),  "label": "BTC Evening (17:30–21:30 IST)"},
    ],
    "ETHUSD": [
        {"start_utc": (3, 30),  "end_utc": (6,  0),  "label": "ETH Morning (09:00–11:30 IST)"},
        {"start_utc": (12, 0),  "end_utc": (16, 0),  "label": "ETH Evening (17:30–21:30 IST)"},
    ],
    "XAUUSD": [
        {"start_utc": (5, 0),   "end_utc": (8, 30),  "label": "Gold Morning (10:30–14:00 IST)"},
        {"start_utc": (13, 30), "end_utc": (16, 0),  "label": "Gold Evening (19:00–21:30 IST)"},
    ],
    "XAGUSD": [
        {"start_utc": (5, 0),   "end_utc": (8, 30),  "label": "Silver Morning (10:30–14:00 IST)"},
        {"start_utc": (13, 30), "end_utc": (16, 0),  "label": "Silver Evening (19:00–21:30 IST)"},
    ],
}

# ── UTBot (ATR Trailing Stop) Parameters ────────────────────────
UTBOT_KEY_VALUE  = 3      # sensitivity — matches your TradingView script
UTBOT_ATR_PERIOD = 10

# ── EMA Periods ─────────────────────────────────────────────────
EMA_FAST   = 5
EMA_MID    = 20
EMA_SLOW   = 200
EMA_ELDER  = 13           # used in Elder Impulse + your indicator code

# ── MACD Parameters (matches your TradingView code) ─────────────
MACD_FAST   = 12
MACD_SLOW   = 26
MACD_SIGNAL = 9

# ── VWAP ─────────────────────────────────────────────────────────
VWAP_TIMEFRAME = "M15"    # base timeframe for VWAP calculation

# ── Risk Management ──────────────────────────────────────────────
#
# RISK_MODE options:
#   "conservative"  → 1% per trade  — safe for live accounts
#   "moderate"      → 2% per trade  — good for demo testing
#   "aggressive"    → 5% per trade  — max speed for demo month-run
#
# For a $50 demo account trying to grow fast → use "aggressive"
# For a $500+ live account                   → use "conservative"
#
RISK_MODE         = "moderate"    # ← change this: conservative / moderate / aggressive

RISK_PERCENT_MAP  = {
    "conservative": 1.0,
    "moderate":     2.0,
    "aggressive":   5.0,
}
RISK_PERCENT      = RISK_PERCENT_MAP[RISK_MODE]

ATR_SL_MULTIPLIER = 1.5   # SL = 1.5 × ATR
RR_RATIO          = 2.0   # TP = SL × 2 (2:1 R:R) — let price run, trailing stop protects
MAX_TRADES_PER_DAY = 4    # max 4 trades total across both pairs per day
DAILY_LOSS_LIMIT  = -6.0     # Stop trading today if down 6% (3 losses at 2% each)

# ── Minimum balance required to trade each symbol ────────────────
# Protects live accounts from oversized risk on small balances.
# All set to 0 for DEMO — change these when going LIVE.
#
# Recommended live values (for $200+ account):
#   "ETHUSD": 20,    "BTCUSD": 100,
#   "XAUUSD": 200,   "XAGUSD": 150,
#
MIN_BALANCE_TO_TRADE = {
    "ETHUSD": 50,    # safe from $50
    "BTCUSD": 50,    # safe from $50
    "XAUUSD": 50,    # Hard risk cap enforced in risk_engine.py — blocks trade if min lot > 50% balance
    "XAGUSD": 200,   # Silver blocked until $200 balance
}

# ── Demo / Live Mode ──────────────────────────────────────────────
# True  → Demo account: full lot on holidays
# False → Live account: holiday half-lot active
DEMO_MODE          = False  # holidays → half lot (0.01 = minimum anyway)

# ── Manual Mode ───────────────────────────────────────────────────
# True  → bot sends Telegram SIGNAL ALERT but does NOT auto-execute
# False → bot auto-executes as normal (default)
MANUAL_MODE        = False  # Auto-execute trades directly

# ── Trailing Stop Settings ────────────────────────────────────────
# How it works:
#   1. Trade opens, original SL is set (1.5 × ATR away)
#   2. Price reaches BREAKEVEN_AT_PCT of TP → SL moves to entry (zero loss guaranteed)
#   3. Price reaches TRAIL_START_PCT of TP  → SL trails TRAIL_ATR_MULT × ATR behind price
#   4. If price hits TP → full 2:1 win. If reversal → exits at trail stop (partial profit)
#
# Example BTC: Entry=73684, TP=77146 (+3462 pts), SL=71954
#   At 50% of TP (75415) → SL moves to 73684 (breakeven)
#   At 75% of TP (76230) → SL trails 1153 pts behind price
#   This matches what you see: morning run peaks at ~10:30 AM, then reversal caught by trail
#
TRAILING_STOP_ENABLED = True
BREAKEVEN_AT_PCT  = 0.5   # move SL to entry when price reaches 50% of TP distance
TRAIL_START_PCT   = 0.75  # start trailing when price reaches 75% of TP distance
TRAIL_ATR_MULT    = 1.0   # trail distance = 1.0 × ATR (tighter than SL which is 1.5)

# ── Carry trade to last session of the day ────────────────────────
# When True:  trade stays open across sessions, closes at LAST session end
#   BTC:  opens 04:00 UTC, closes at 13:30 UTC (9.5 hours)
#   Gold: opens 06:00 UTC, closes at 15:30 UTC (9.5 hours)
# When False: trade closes at end of session it was opened in (1.5 hours)
#
# SAFE because trailing stop moves SL to breakeven during carry
# — worst case is zero loss, best case is full 2:1 TP hit
#
CARRY_TO_LAST_SESSION = True

# Last session end per symbol (UTC hours, minutes) — close all carries here
LAST_SESSION_END = {
    "BTCUSD": (16, 0),   # end of evening BTC session (21:30 IST)
    "ETHUSD": (16, 0),
    "XAUUSD": (16, 0),   # end of Gold/Silver session (21:30 IST)
    "XAGUSD": (16, 0),
}

# ── Confirmation Thresholds ──────────────────────────────────────
# How many timeframes must agree before entry
# 4H bias + 1H confirm + 15m confirm = minimum 2 of these 3
MIN_TIMEFRAME_CONFIRMATIONS = 2

# ── Candle counts to fetch ───────────────────────────────────────
CANDLE_COUNT_4H  = 100
CANDLE_COUNT_1H  = 100
CANDLE_COUNT_15M = 150
CANDLE_COUNT_1M  = 60

# ── Bot loop interval (seconds) ─────────────────────────────────
LOOP_INTERVAL_SECONDS = 60

# ── Logging ──────────────────────────────────────────────────────
LOG_FILE = "bot.log"
