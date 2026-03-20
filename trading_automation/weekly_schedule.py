"""
Shows this week's trading schedule — which days to trade, which to skip.
Run: python weekly_schedule.py
"""
from dotenv import load_dotenv
load_dotenv()
from day_filter import weekly_summary, get_day_info, MARKET_HOLIDAYS_2026
from datetime import date, timedelta

print("\n" + "="*55)
print("  VISHU BOT — WEEKLY TRADING SCHEDULE")
print("="*55)
print(weekly_summary())

print("\n  UPCOMING MARKET HOLIDAYS (2026):")
print("  " + "─"*45)
today = date.today()
shown = 0
for month, day, label in MARKET_HOLIDAYS_2026:
    hol_date = date(2026, month, day)
    if hol_date >= today and shown < 5:
        days_away = (hol_date - today).days
        print(f"  {hol_date.strftime('%d %b %Y')} — {label} (in {days_away} days)")
        shown += 1

print("\n  TRADING RULES SUMMARY:")
print("  " + "─"*45)
print("  Monday    → SKIP  (choppy, gap fills)")
print("  Tuesday   → FULL lot  (best day)")
print("  Wednesday → FULL lot  (best day)")
print("  Thursday  → FULL lot  (strong moves)")
print("  Friday    → HALF lot  (weekend risk)")
print("  Saturday  → SKIP  (closed)")
print("  Sunday    → SKIP  (closed)")
print("  Holidays  → SKIP  (no liquidity)")
print("  India hol → HALF lot  (unattended)")
print("="*55 + "\n")
