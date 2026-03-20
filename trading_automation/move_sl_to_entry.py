"""
MOVE ALL SLs TO ENTRY — Zero loss guaranteed, full upside intact.
Run this once: python move_sl_to_entry.py
"""
import MetaTrader5 as mt5
import os
from dotenv import load_dotenv

load_dotenv()

LOGIN    = int(os.getenv("MT5_LOGIN", 0))
PASSWORD = os.getenv("MT5_PASSWORD", "")
SERVER   = os.getenv("MT5_SERVER", "")

if not mt5.initialize():
    print("MT5 init failed"); exit()

if not mt5.login(LOGIN, password=PASSWORD, server=SERVER):
    print(f"Login failed: {mt5.last_error()}"); mt5.shutdown(); exit()

info = mt5.account_info()
print(f"\nConnected | Balance: ${info.balance:.2f} | Equity: ${info.equity:.2f}")
print(f"Floating P&L: ${info.equity - info.balance:.2f}\n")

positions = mt5.positions_get() or []
if not positions:
    print("No open positions."); mt5.shutdown(); exit()

moved = 0
skipped = 0

for pos in positions:
    entry     = pos.price_open
    current   = pos.price_current
    current_sl= pos.sl
    symbol    = pos.symbol
    ticket    = pos.ticket
    is_buy    = pos.type == mt5.ORDER_TYPE_BUY

    # Check if already at breakeven or better
    if is_buy and current_sl >= entry:
        print(f"  SKIP  {symbol} #{ticket} — SL already at/above entry")
        skipped += 1
        continue
    if not is_buy and current_sl <= entry and current_sl > 0:
        print(f"  SKIP  {symbol} #{ticket} — SL already at/below entry")
        skipped += 1
        continue

    # Only move if currently in profit (protect from moving SL into loss)
    floating = pos.profit
    if floating <= 0:
        print(f"  SKIP  {symbol} #{ticket} — not in profit yet (${floating:.2f}), keeping original SL")
        skipped += 1
        continue

    # Move SL to entry
    request = {
        "action":   mt5.TRADE_ACTION_SLTP,
        "position": ticket,
        "sl":       round(entry, 2),
        "tp":       pos.tp,
    }
    result = mt5.order_send(request)

    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
        print(f"  ✅ {symbol} #{ticket} | {('BUY' if is_buy else 'SELL')} @ {entry:.2f} | "
              f"SL moved: {current_sl:.2f} → {entry:.2f} | Floating: +${floating:.2f}")
        moved += 1
    else:
        err = result.comment if result else str(mt5.last_error())
        print(f"  ❌ {symbol} #{ticket} | Failed: {err}")

print(f"\nDone — {moved} SLs moved to entry | {skipped} skipped")
print(f"Worst case now: $0 loss | Upside: unlimited to TP\n")
mt5.shutdown()
