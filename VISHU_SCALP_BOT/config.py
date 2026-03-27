"""
VISHU SCALP BOT — Configuration
Strategy : 15M bias + 1M EMA cross entry during kill zones
Capital  : Designed for $50–$200 live accounts
Pairs    : ETHUSD, BTCUSD (min lot affordable at $50)
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
# XAUUSD excluded — 0.01 lot = $1/point move, too big for $50 account
# ETH: 0.1 lot = $0.10/point — perfect for $50
# BTC: 0.01 lot = $0.01/point — safe for $50
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
}

# ── Risk ───────────────────────────────────────────────────────────
RISK_PERCENT     = 1.0    # 1% per trade on live — DO NOT increase on $50
DAILY_LOSS_LIMIT = -3.0   # stop at -3% today (3 losing trades max)
MAX_TRADES_DAY   = 8      # max scalp trades per day across all symbols
RR_RATIO         = 1.5    # 1.5:1 RR — quicker TP for scalping
MAX_OPEN         = 1      # only 1 trade open at a time (no stacking on $50)

# ── Scalp Indicators ───────────────────────────────────────────────
ATR_PERIOD    = 10        # 1M ATR — shorter period for scalping
ATR_SL_MULT   = 1.2      # SL = 1.2 × 1M ATR (tighter than swing bots)
EMA_FAST      = 5
EMA_SLOW      = 20
RSI_PERIOD    = 14
RSI_BUY_MAX   = 65        # no BUY if RSI > 65 (overbought)
RSI_SELL_MIN  = 35        # no SELL if RSI < 35 (oversold)

# ── Trade Manager ──────────────────────────────────────────────────
BREAKEVEN_PCT = 0.5       # move SL to entry when 50% of TP reached
TRAIL_PCT     = 0.75      # start trailing at 75% of TP
TRAIL_MULT    = 0.6       # trail distance = 60% of original SL (tight)

# ── Kill Zones (UTC) — scalp ONLY during high-volume windows ───────
KILL_ZONES = [
    {"name": "London Open",  "start": (7,  0),  "end": (9,  30)},  # 12:30–15:00 IST
    {"name": "NY Open",      "start": (12, 0),  "end": (15, 0)},   # 17:30–20:30 IST
    {"name": "London Close", "start": (15, 0),  "end": (16, 30)},  # 20:30–22:00 IST
]

# ── Safety ─────────────────────────────────────────────────────────
MAGIC_NUMBER     = 20260327  # unique — different from all other bots
LOOP_INTERVAL    = 15        # scan every 15 seconds (scalping speed)
LOG_FILE         = "scalp_bot.log"
