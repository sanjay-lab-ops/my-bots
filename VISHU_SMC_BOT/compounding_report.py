"""
Compound Growth Report — shows day-by-day balance growth.
Run this any time to see your progress.
"""

import json
from pathlib import Path
from config import BALANCE_FILE, RISK_PERCENT


def run():
    path = Path(BALANCE_FILE)
    if not path.exists():
        print("  No balance file yet. Start the bot first.")
        return

    data    = json.loads(path.read_text())
    history = data.get("history", [])
    start   = data.get("start_balance", 0)
    current = data.get("current_balance", start)
    s_date  = data.get("start_date", "?")

    total_pnl = current - start
    total_pct = total_pnl / start * 100 if start > 0 else 0

    sep = "═" * 60
    print(f"\n{sep}")
    print(f"  VISHU SMC BOT — COMPOUND GROWTH REPORT")
    print(sep)
    print(f"  Start date    : {s_date}")
    print(f"  Start balance : ${start:.2f}")
    print(f"  Current balance: ${current:.2f}")
    sign = "+" if total_pnl >= 0 else ""
    print(f"  Total gain    : {sign}{total_pnl:.2f} USD  ({sign}{total_pct:.1f}%)")
    print(f"  Risk per trade: {RISK_PERCENT}% (compounding)")

    if history:
        print(f"\n{'─'*60}")
        print(f"  {'Date':<12} {'End Balance':>12} {'Day P&L':>9} {'Trades':>7} {'Win%':>6}")
        print(f"{'─'*60}")
        for h in history:
            end_bal = h.get("end_balance", start)
            day_pnl = h.get("day_pnl", 0)
            trades  = h.get("trades", 0)
            wins    = h.get("wins", 0)
            wr      = f"{wins/trades*100:.0f}%" if trades > 0 else "—"
            sign2   = "+" if day_pnl >= 0 else ""
            print(f"  {h['date']:<12} ${end_bal:>10.2f} {sign2}{day_pnl:>8.2f} {trades:>7} {wr:>6}")

    # Projections
    trading_days = len(history)
    if trading_days > 0 and start > 0:
        daily_growth = (current / start) ** (1 / trading_days) - 1
        print(f"\n{'─'*60}")
        print(f"  PROJECTIONS (at current {daily_growth*100:.2f}%/day rate)")
        print(f"{'─'*60}")
        for weeks in [1, 2, 4, 8, 12]:
            projected = current * (1 + daily_growth) ** (weeks * 5)
            print(f"  {weeks} week{'s' if weeks > 1 else '':<2}: ${projected:.2f}")

    print(sep)


if __name__ == "__main__":
    run()
