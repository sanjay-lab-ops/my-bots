"""
Daily PnL report — prints and logs a summary of today's closed trades.
"""

import logging
import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("report")

BOT_MAGIC = 20260318


def daily_report() -> str:
    """Generate and return a formatted daily PnL report string."""
    now     = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    history = mt5.history_deals_get(day_start, now)
    if not history:
        return "No closed trades today."

    deals = [d for d in history if d.magic == BOT_MAGIC and d.entry == mt5.DEAL_ENTRY_OUT]

    if not deals:
        return "No bot trades closed today."

    rows = []
    for d in deals:
        rows.append({
            "Time":   datetime.utcfromtimestamp(d.time).strftime("%H:%M"),
            "Symbol": d.symbol,
            "Type":   "BUY" if d.type == mt5.DEAL_TYPE_BUY else "SELL",
            "Lot":    d.volume,
            "Profit": round(d.profit, 2),
        })

    df = pd.DataFrame(rows)
    total_pnl = df["Profit"].sum()
    wins       = (df["Profit"] > 0).sum()
    losses     = (df["Profit"] <= 0).sum()
    win_rate   = wins / len(df) * 100 if len(df) else 0

    sep   = "─" * 48
    lines = [
        "",
        "╔══════════════════════════════════════════════╗",
        "║        VISHU BOT — DAILY REPORT              ║",
        f"║  Date: {now.strftime('%Y-%m-%d')}  UTC                    ║",
        "╚══════════════════════════════════════════════╝",
        sep,
        df.to_string(index=False),
        sep,
        f"  Total trades : {len(df)}",
        f"  Wins         : {wins}   Losses: {losses}",
        f"  Win rate     : {win_rate:.1f}%",
        f"  Total P&L    : ${total_pnl:+.2f}",
        sep,
    ]

    report = "\n".join(lines)
    logger.info(report)
    print(report)
    return report


def account_summary() -> str:
    info = mt5.account_info()
    if not info:
        return "Cannot fetch account info."
    return (
        f"\n  Balance : ${info.balance:.2f}"
        f"\n  Equity  : ${info.equity:.2f}"
        f"\n  Margin  : ${info.margin:.2f}"
        f"\n  Free M  : ${info.margin_free:.2f}"
    )
