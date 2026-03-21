# VISHU TRADING SYSTEM — 3 Bots

Automated trading system for BTCUSD, ETHUSD, XAUUSD, XAGUSD on Exness MT5.

---

## 3 Bots Overview

| Bot | Strategy | Schedule | Magic |
|-----|----------|----------|-------|
| **Bot 1** (trading_automation) | UTBot + VWAP + EMA | Session-based IST windows | 20260318 |
| **Bot 2** (VISHU_ELITE_BOT) | Triple TF Confluence | Session-based IST windows | 20260319 |
| **Bot 3** (VISHU_SMC_BOT) | SMC Order Blocks + FVG | 24/7 — EOD close 21:30 IST | 20260320 |

---

## Quick Start

### Install (first time only)
```
cd C:\BAS_AUTOMATION\my-bots
# copy your .env file into each bot folder (see .env section below)
cd trading_automation && pip install -r requirements.txt
cd ..\VISHU_ELITE_BOT  && pip install -r requirements.txt
cd ..\VISHU_SMC_BOT    && pip install -r requirements.txt
```

### Start All 3 Bots
```
Double-click: START_3_BOTS.bat
```
Make sure MetaTrader 5 is open and logged in first.

### Update from GitHub (on personal laptop)
```
cd C:\BAS_AUTOMATION\my-bots
git pull
```
No reinstall needed — just pull and restart bots.

---

## .env File (required in each bot folder)

Create `.env` inside `trading_automation/`, `VISHU_ELITE_BOT/`, and `VISHU_SMC_BOT/`:

```
MT5_LOGIN=your_login_here
MT5_PASSWORD=your_password_here
MT5_SERVER=Exness-MT5Trial17
TELEGRAM_TOKEN=your_telegram_token
TELEGRAM_CHAT_ID=your_chat_id
```

> **Never commit .env files** — they are gitignored.

---

## Lot Sizes — Auto Detection

Lot sizes are fully automatic. No manual changes needed.

| Balance | BTCUSD | XAUUSD | XAGUSD (Silver) |
|---------|--------|--------|-----------------|
| $50+    | 0.01   | 0.01   | Blocked         |
| $200+   | 0.01   | 0.01   | **Unlocks** 0.01 |
| $500    | 0.02   | 0.01   | 0.01            |
| $5000   | 0.25   | 0.05   | auto formula    |

- **Bot 3** uses compounding formula: `lot = (balance × 1.5%) ÷ (SL_distance × contract_size)`
- Balance is read live from MT5 every 60 seconds — lot adjusts automatically as you grow

---

## Session Schedule (IST)

```
Bot 1  BTC/ETH     : 09:00–11:30   17:30–21:30
Bot 1  Gold/Silver : 10:30–14:00   19:00–21:30
Bot 2  BTC/ETH     : 07:30–09:30   14:30–17:00   19:00–21:30
Bot 2  Gold/Silver : 10:30–14:00   19:00–21:30
Bot 3  All pairs   : 24/7 — H4 candles close at 01:30 05:30 09:30 13:30 17:30 21:30 IST
```

### Bot 3 — 9:30 PM IST Close (EOD)
Bot 3 runs 24/7 but has a forced End-of-Day close at **21:30 IST (9:30 PM)**:
- All open positions closed at market price
- All pending limit orders cancelled
- Daily P&L summary sent to Telegram
- Bot sleeps 1 hour, resumes scanning from ~10:30 PM

---

## Telegram Commands (Bot 3)

```
/setbias BTCUSD buy    — force BUY direction only
/setbias XAUUSD sell   — force SELL direction only
/bias                  — show current overrides
/clearbias             — reset all to auto
```

---

## Risk Settings (config.py)

**Bot 1 / Bot 2** — edit `trading_automation/config.py`:
```python
RISK_MODE = "moderate"     # conservative=1%  moderate=2%  aggressive=5%
```

**Bot 3** — edit `VISHU_SMC_BOT/config.py`:
```python
RISK_PERCENT = 1.5         # % of balance per trade (auto-compounds)
```

---

## Days Bot Trades

| Day | Status |
|-----|--------|
| Monday | SKIP (no trades) |
| Tue / Wed / Thu | FULL LOT (best days) |
| Friday | HALF LOT (weekend risk) |
| Saturday / Sunday | BTC only, half lot |

---

## File Structure

```
my-bots/
├── START_3_BOTS.bat          ← Start all 3 bots at once
├── cross_bot_lock.py         ← Prevents duplicate trades across bots
├── trading_automation/       ← Bot 1: UTBot + VWAP
│   ├── main.py
│   ├── config.py
│   └── ...
├── VISHU_ELITE_BOT/          ← Bot 2: Triple TF Confluence
│   ├── main.py
│   └── ...
└── VISHU_SMC_BOT/            ← Bot 3: SMC 24/7
    ├── main.py
    ├── config.py
    ├── compounding.py
    └── ...
```

---

*Built for Sanjay | Vishu Trading System | 2026*
