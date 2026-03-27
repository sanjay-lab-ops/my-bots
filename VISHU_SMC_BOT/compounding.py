"""
Compounding Capital Manager

Tracks running balance across days and adjusts lot sizes automatically.
Every winning trade increases the balance → next trade lot is slightly larger.
This is how $20 can grow into meaningful capital over weeks/months.

Monthly projection (at 1.5% risk, 2.5:1 RR, 55% win rate):
  Expected value per trade = 0.55 × 2.5 - 0.45 × 1 = 0.925 risk units
  ~3 trades/day × 0.925 × 1.5% = ~4.2% expected daily growth
  $20 × 1.042^20 trading days = ~$44 in one month (conservative)
  On good months with trending markets: $20 → $80–$120 is realistic
"""

import json
import math
import logging
from datetime import datetime, timezone
from pathlib import Path
from config import BALANCE_FILE, RISK_PERCENT, SYMBOLS

logger = logging.getLogger("compounding")


def load_balance() -> float | None:
    """Load current balance from JSON tracker. Returns None if file missing."""
    path = Path(BALANCE_FILE)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return float(data.get("current_balance", 0)) or None
    except Exception:
        return None


def save_balance(balance: float):
    """Save updated balance to tracker file."""
    path    = Path(BALANCE_FILE)
    today   = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if path.exists():
        try:
            data = json.loads(path.read_text())
        except Exception:
            data = {}
    else:
        data = {}

    if "start_balance" not in data:
        data["start_balance"] = balance
        data["start_date"]    = today
        data["history"]       = []

    data["current_balance"] = round(balance, 2)
    data["last_updated"]    = datetime.now(timezone.utc).isoformat()

    # Update today's entry in history
    history = data.get("history", [])
    today_entry = next((h for h in history if h["date"] == today), None)
    if today_entry:
        today_entry["end_balance"] = round(balance, 2)
    else:
        history.append({"date": today, "end_balance": round(balance, 2)})

    data["history"] = history
    path.write_text(json.dumps(data, indent=2))
    logger.info("Balance saved: $%.2f", balance)


def update_after_trade(pnl: float, current_balance: float):
    """Update balance after a trade closes."""
    new_balance = current_balance + pnl
    save_balance(new_balance)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path  = Path(BALANCE_FILE)
    if path.exists():
        data    = json.loads(path.read_text())
        history = data.get("history", [])
        entry   = next((h for h in history if h["date"] == today), None)
        if entry:
            entry["day_pnl"]     = round(entry.get("day_pnl", 0) + pnl, 2)
            entry["end_balance"] = round(new_balance, 2)
            entry["trades"]      = entry.get("trades", 0) + 1
            entry["wins"]        = entry.get("wins", 0) + (1 if pnl > 0 else 0)
        data["history"] = history
        path.write_text(json.dumps(data, indent=2))

    return new_balance


def calculate_lot(balance: float, sl_distance: float, symbol: str) -> float:
    """
    ATR-based compounding lot size.

    Formula: lot = (balance × RISK%) ÷ (sl_distance × contract_size)

    This means if balance grows from $20 → $40, the lot automatically doubles.
    """
    cfg           = SYMBOLS.get(symbol, {})
    min_lot       = cfg.get("min_lot", 0.01)
    max_lot       = cfg.get("max_lot", 1.0)
    lot_step      = cfg.get("lot_step", 0.01)
    contract_size = cfg.get("contract_size", 1)

    if sl_distance <= 0 or balance <= 0:
        return min_lot

    risk_amount = balance * (RISK_PERCENT / 100)
    sl_dollar   = sl_distance * contract_size
    raw_lot     = risk_amount / sl_dollar

    # For gold/silver the formula gives tiny lots (sl_dollar is huge due to contract_size=100).
    # Use balance tiers as a floor so lot sizes are meaningful at higher balances.
    if "XAU" in symbol:
        if balance <= 500:    tier_floor = 0.01
        elif balance <= 800:  tier_floor = 0.02
        elif balance <= 1200: tier_floor = 0.03
        else:                 tier_floor = 0.05   # max 0.05 — safe for all balance levels
        raw_lot = max(raw_lot, tier_floor)
    elif "XAG" in symbol:  # Silver — contract_size=5000, very sensitive, keep lots tiny
        if balance <= 2000:   tier_floor = 0.01
        else:                 tier_floor = 0.02   # max 0.02 — 0.05 risks $800+ at small SL
        raw_lot = max(raw_lot, tier_floor)
    elif "BTC" in symbol:
        if balance <= 100:    tier_floor = 0.01
        elif balance <= 300:  tier_floor = 0.02
        elif balance <= 600:  tier_floor = 0.05
        elif balance <= 1000: tier_floor = 0.10
        elif balance <= 2000: tier_floor = 0.20
        else:                 tier_floor = 0.50
        raw_lot = max(raw_lot, tier_floor)
    elif "ETH" in symbol:
        if balance <= 100:    tier_floor = 0.1
        elif balance <= 300:  tier_floor = 0.2
        elif balance <= 600:  tier_floor = 0.3
        elif balance <= 1000: tier_floor = 0.5
        elif balance <= 2000: tier_floor = 1.0
        else:                 tier_floor = 2.0
        raw_lot = max(raw_lot, tier_floor)

    # Clamp to valid range
    raw_lot = max(min_lot, min(max_lot, raw_lot))
    lot     = round(math.floor(raw_lot / lot_step) * lot_step, 2)

    # Hard risk cap — block trade if minimum lot risks > 50% of balance
    # Gold 0.01 lot = $94-160 risk. At $50 balance that is 188%+ — account wipe guaranteed.
    # Returns 0 → main.py sees lot=0 and skips the trade entirely.
    min_risk_pct = (min_lot * sl_dollar / balance) * 100
    if min_risk_pct > 50:
        logger.warning(
            "TRADE BLOCKED [%s]: min lot risks %.1f%% of $%.2f — skipping to protect account",
            symbol, min_risk_pct, balance,
        )
        return 0   # signals main.py to skip this trade

    logger.info("Lot [%s]: $%.2f balance × %.1f%% risk / $%.2f SL = %.2f lots",
                symbol, balance, RISK_PERCENT, sl_dollar, lot)
    return lot


def get_compound_stats() -> dict:
    """Return full growth statistics from history file."""
    path = Path(BALANCE_FILE)
    if not path.exists():
        return {}

    try:
        data    = json.loads(path.read_text())
        history = data.get("history", [])

        start_bal = data.get("start_balance", 0)
        cur_bal   = data.get("current_balance", start_bal)
        total_pnl = cur_bal - start_bal
        total_pct = (total_pnl / start_bal * 100) if start_bal > 0 else 0

        all_wins   = sum(h.get("wins", 0) for h in history)
        all_trades = sum(h.get("trades", 0) for h in history)
        win_rate   = (all_wins / all_trades * 100) if all_trades > 0 else 0

        day_pnls  = [h.get("day_pnl", 0) for h in history if "day_pnl" in h]
        best_day  = max(day_pnls) if day_pnls else 0
        worst_day = min(day_pnls) if day_pnls else 0

        return {
            "start_balance":  start_bal,
            "current_balance": cur_bal,
            "total_pnl":      round(total_pnl, 2),
            "total_pnl_pct":  round(total_pct, 2),
            "trading_days":   len(history),
            "total_trades":   all_trades,
            "win_rate":       round(win_rate, 1),
            "best_day":       round(best_day, 2),
            "worst_day":      round(worst_day, 2),
            "start_date":     data.get("start_date", ""),
        }
    except Exception as e:
        logger.error("Error reading compound stats: %s", e)
        return {}
