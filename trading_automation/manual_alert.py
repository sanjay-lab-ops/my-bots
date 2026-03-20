"""
Manual Trade Alert — Decision Engine
Analyzes your trade idea and returns YES / CAUTION / NO before sending to Telegram.
"""

import os
import requests
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
IST     = timedelta(hours=5, minutes=30)

SYMBOL_MAP = {
    "BTC": "BTCUSDm", "BTCUSD": "BTCUSDm", "BTCUSDM": "BTCUSDm",
    "ETH": "ETHUSDm", "ETHUSD": "ETHUSDm", "ETHUSDM": "ETHUSDm",
    "XAU": "XAUUSDm", "XAUUSD": "XAUUSDm", "XAUUSDM": "XAUUSDm", "GOLD": "XAUUSDm",
    "XAG": "XAGUSDm", "XAGUSD": "XAGUSDm", "XAGUSDM": "XAGUSDm", "SILVER": "XAGUSDm",
}

CONTRACT = {
    "BTCUSDm": 1,
    "ETHUSDm": 1,
    "XAUUSDm": 100,
    "XAGUSDm": 5000,
}

# Sessions in IST (hour, minute, hour, minute)
SESSIONS = {
    "BTCUSDm": [
        ("BTC Asia Open",    9, 30, 11,  0),
        ("BTC London Open", 14, 30, 17,  0),
        ("BTC NY Open",     19,  0, 21, 30),
    ],
    "ETHUSDm": [
        ("ETH Asia Open",    9, 30, 11,  0),
        ("ETH London Open", 14, 30, 17,  0),
        ("ETH NY Open",     19,  0, 21, 30),
    ],
    "XAUUSDm": [
        ("Gold London",     13, 30, 16, 30),
        ("Gold NY",         18, 30, 21,  0),
    ],
    "XAGUSDm": [
        ("Silver London",   13, 30, 16, 30),
        ("Silver NY",       18, 30, 21,  0),
    ],
}


def ist_now():
    return datetime.now(timezone.utc) + IST


def send(msg: str):
    if not TOKEN or not CHAT_ID:
        print("  Telegram not configured in .env")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=5,
        )
    except Exception as e:
        print(f"  Telegram error: {e}")




def check_session(mt5_sym):
    now     = ist_now()
    now_min = now.hour * 60 + now.minute
    for name, sh, sm, eh, em in SESSIONS.get(mt5_sym, []):
        if (sh * 60 + sm) <= now_min <= (eh * 60 + em):
            return True, name
    # find next session
    upcoming = []
    for name, sh, sm, eh, em in SESSIONS.get(mt5_sym, []):
        start = sh * 60 + sm
        if start > now_min:
            upcoming.append((start, name, sh, sm))
    if upcoming:
        upcoming.sort()
        _, next_name, nh, nm = upcoming[0]
        return False, f"next: {next_name} at {nh:02d}:{nm:02d} IST"
    return False, "no session today"


def auto_tp(entry, sl, direction, rr=2.0):
    dist = abs(entry - sl)
    return round(entry + dist * rr if direction == "BUY" else entry - dist * rr, 3)


def run_decision(pair_input, direction, entry, sl, tp_raw, lots):
    mt5_sym  = SYMBOL_MAP.get(pair_input.upper(), pair_input.upper() + "m")
    contract = CONTRACT.get(mt5_sym, 1)

    # TP — auto if not given
    use_auto_tp = not tp_raw or tp_raw.lower() in ("auto", "you decide", "-", "a", "")
    tp = auto_tp(entry, sl, direction) if use_auto_tp else float(tp_raw)

    sl_dist  = abs(entry - sl)
    tp_dist  = abs(tp - entry)
    rr_ratio = tp_dist / sl_dist if sl_dist > 0 else 0
    risk_usd = lots * contract * sl_dist

    # Live balance from .env (your live account, not demo)
    balance = float(os.getenv("LIVE_BALANCE", "0") or 0)

    # Session
    in_session, sess_info = check_session(mt5_sym)

    # Risk %
    risk_pct = (risk_usd / balance * 100) if balance > 0 else None

    # SL quality — is SL distance sensible for this pair?
    SL_RANGE = {
        "BTCUSDm": (100,  3000),
        "ETHUSDm": (10,   300),
        "XAUUSDm": (8,    150),
        "XAGUSDm": (0.10, 2.5),
    }
    sl_min, sl_max = SL_RANGE.get(mt5_sym, (0, 999999))
    sl_quality = "good" if sl_min <= sl_dist <= sl_max else ("tight" if sl_dist < sl_min else "wide")

    # ── SCORING ──────────────────────────────────────────────────────
    score = 0
    flags = []

    # 1. RR ratio (30 pts)
    if rr_ratio >= 2.0:
        score += 30
        flags.append(("✅", f"RR Ratio    : {rr_ratio:.1f}:1  (good)"))
    elif rr_ratio >= 1.5:
        score += 15
        flags.append(("⚠️ ", f"RR Ratio    : {rr_ratio:.1f}:1  (acceptable, prefer 2+)"))
    else:
        flags.append(("❌", f"RR Ratio    : {rr_ratio:.1f}:1  (too low — min 1.5)"))

    # 2. Risk % of live account (35 pts)
    if risk_pct is not None:
        if risk_pct <= 5:
            score += 35
            flags.append(("✅", f"Risk        : ${risk_usd:.2f} ({risk_pct:.1f}% of ${balance:.2f})  ✓"))
        elif risk_pct <= 15:
            score += 18
            flags.append(("⚠️ ", f"Risk        : ${risk_usd:.2f} ({risk_pct:.1f}% of ${balance:.2f})  high"))
        else:
            flags.append(("❌", f"Risk        : ${risk_usd:.2f} ({risk_pct:.1f}% of ${balance:.2f})  TOO HIGH"))
    else:
        score += 15
        flags.append(("⚠️ ", f"Risk        : ${risk_usd:.2f}  (set LIVE_BALANCE in .env for % check)"))

    # 3. Session window (25 pts)
    if in_session:
        score += 25
        flags.append(("✅", f"Session     : {sess_info} active  ✓"))
    else:
        score += 5
        flags.append(("⚠️ ", f"Session     : Outside window ({sess_info})"))

    # 4. SL quality (10 pts)
    if sl_quality == "good":
        score += 10
        flags.append(("✅", f"SL Distance : {sl_dist:.2f} pts  (healthy range)"))
    elif sl_quality == "tight":
        score += 3
        flags.append(("⚠️ ", f"SL Distance : {sl_dist:.2f} pts  (tight — risk of noise stop-out)"))
    else:
        score += 3
        flags.append(("⚠️ ", f"SL Distance : {sl_dist:.2f} pts  (wide — reduces lot size significantly)"))

    # ── VERDICT ──────────────────────────────────────────────────────
    if score >= 80:
        verdict = "✅  YES — TAKE IT"
    elif score >= 50:
        verdict = "⚠️   CAUTION — YOUR CALL"
    else:
        verdict = "❌  NO — SKIP THIS"

    return {
        "mt5_sym":    mt5_sym,
        "tp":         tp,
        "auto_tp":    use_auto_tp,
        "rr_ratio":   rr_ratio,
        "risk_usd":   risk_usd,
        "risk_pct":   risk_pct,
        "balance":    balance,
        "score":      score,
        "flags":      flags,
        "verdict":    verdict,
    }


def main():
    print("\n══════════════════════════════════════")
    print("   MANUAL TRADE — DECISION ENGINE")
    print("══════════════════════════════════════")

    pair      = input("  Pair   (BTC / XAU / XAG / ETH) : ").strip()
    direction = input("  Direction  (BUY / SELL)         : ").strip().upper()
    entry     = float(input("  Entry price                     : ").strip())
    sl        = float(input("  Stop Loss                       : ").strip())
    tp_raw    = input("  TP  (Enter = auto 2:1)          : ").strip()
    lots      = float(input("  Lot size                        : ").strip())
    reason    = input("  Reason (optional)               : ").strip()

    r = run_decision(pair, direction, entry, sl, tp_raw, lots)

    print(f"\n  ───────────────────────────────────────")
    print(f"  {direction} {pair.upper()} @ {entry}  |  SL {sl}  |  TP {r['tp']}{' [auto 2:1]' if r['auto_tp'] else ''}")
    print(f"  Lots: {lots}")
    print(f"  ───────────────────────────────────────")
    for icon, text in r["flags"]:
        print(f"  {icon}  {text}")
    print(f"  ───────────────────────────────────────")
    print(f"  Score  : {r['score']}/100")
    print(f"  ══ {r['verdict']} ══")
    print(f"  ───────────────────────────────────────")

    # If NO, ask override
    if r["score"] < 50:
        ov = input("\n  Override and send anyway? (y/n) : ").strip().lower()
        if ov != "y":
            print("  Trade skipped.\n")
            return

    # Send to Telegram
    emoji   = "🟢" if direction == "BUY" else "🔴"
    now_str = ist_now().strftime("%H:%M IST")
    risk_str = f"${r['risk_usd']:.2f}" + (f" ({r['risk_pct']:.1f}%)" if r["risk_pct"] else "")

    msg = (
        f"👤 <b>[MANUAL TRADE]</b>\n"
        f"{emoji} <b>{direction} {pair.upper()}</b>\n"
        f"Entry  : {entry}\n"
        f"SL     : {sl}\n"
        f"TP     : {r['tp']}{' (auto)' if r['auto_tp'] else ''}\n"
        f"Lots   : {lots}\n"
        f"RR     : {r['rr_ratio']:.1f}:1\n"
        f"Risk   : {risk_str}\n"
        f"Score  : {r['score']}/100 — {r['verdict']}\n"
        f"Time   : {now_str}"
    )
    if reason:
        msg += f"\nReason : {reason}"

    send(msg)
    print(f"\n  ✅ Alert sent at {now_str}")
    print("══════════════════════════════════════\n")


if __name__ == "__main__":
    main()
