"""
MT5 connection and data fetching for VISHU SMC BOT.
"""

import os, logging, time
import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from config import MT5_LOGIN, MT5_PASSWORD, MT5_SERVER, MAGIC_NUMBER

load_dotenv()
logger = logging.getLogger("mt5_conn")

TF_MAP = {
    "M1":  mt5.TIMEFRAME_M1,
    "M5":  mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1":  mt5.TIMEFRAME_H1,
    "H4":  mt5.TIMEFRAME_H4,
    "D1":  mt5.TIMEFRAME_D1,
    "W1":  mt5.TIMEFRAME_W1,
}


def connect() -> bool:
    """Initialize MT5 and login. Retries up to 3 times."""
    for attempt in range(1, 4):
        if not mt5.initialize():
            logger.error("MT5 initialize() failed (attempt %d): %s", attempt, mt5.last_error())
            time.sleep(5)
            continue
        if not mt5.login(MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER):
            logger.error("MT5 login failed (attempt %d): %s", attempt, mt5.last_error())
            mt5.shutdown()
            time.sleep(5)
            continue
        info = mt5.account_info()
        logger.info("Connected | Login: %s | Balance: %.2f | Server: %s",
                    info.login, info.balance, MT5_SERVER)
        return True
    return False


def disconnect():
    mt5.shutdown()
    logger.info("MT5 disconnected.")


def reconnect() -> bool:
    """Disconnect and reconnect."""
    mt5.shutdown()
    time.sleep(3)
    return connect()


def get_candles(symbol: str, timeframe: str, count: int) -> pd.DataFrame:
    """Fetch historical candles. Returns DataFrame indexed by UTC time."""
    tf = TF_MAP.get(timeframe.upper())
    if tf is None:
        logger.error("Unknown timeframe: %s", timeframe)
        return pd.DataFrame()

    # Ensure symbol is selected
    if not mt5.symbol_select(symbol, True):
        logger.warning("Cannot select symbol %s", symbol)

    rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)
    if rates is None or len(rates) == 0:
        logger.warning("No candles for %s %s: %s", symbol, timeframe, mt5.last_error())
        return pd.DataFrame()

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df.set_index("time", inplace=True)
    return df


def get_account_balance() -> float:
    info = mt5.account_info()
    return info.balance if info else 0.0


def get_account_equity() -> float:
    info = mt5.account_info()
    return info.equity if info else 0.0


def get_current_price(symbol: str) -> tuple:
    """Returns (bid, ask)."""
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return (0.0, 0.0)
    return (tick.bid, tick.ask)


def get_open_positions(magic: int = MAGIC_NUMBER) -> list:
    """Return all open positions placed by this bot."""
    all_pos = mt5.positions_get() or []
    return [
        {
            "ticket":    p.ticket,
            "symbol":    p.symbol,
            "type":      p.type,   # 0=buy, 1=sell
            "volume":    p.volume,
            "open_price": p.price_open,
            "sl":        p.sl,
            "tp":        p.tp,
            "profit":    p.profit,
            "comment":   p.comment,
            "time":      datetime.fromtimestamp(p.time, tz=timezone.utc),
        }
        for p in all_pos if p.magic == magic
    ]


def get_pending_orders(magic: int = MAGIC_NUMBER) -> list:
    """Return all pending limit/stop orders placed by this bot."""
    orders = mt5.orders_get() or []
    return [
        {
            "ticket":  o.ticket,
            "symbol":  o.symbol,
            "type":    o.type,
            "volume":  o.volume_initial,
            "price":   o.price_open,
            "sl":      o.sl,
            "tp":      o.tp,
            "comment": o.comment,
            "time":    datetime.fromtimestamp(o.time_setup, tz=timezone.utc),
        }
        for o in orders if o.magic == magic
    ]


def get_day_pnl(magic: int = MAGIC_NUMBER) -> float:
    """Sum of profit from closed trades today (UTC day)."""
    today_utc = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    deals = mt5.history_deals_get(today_utc, datetime.now(timezone.utc))
    if not deals:
        return 0.0
    return sum(d.profit for d in deals if d.magic == magic and d.entry == 1)  # entry=1 = close deal


def get_symbol_digits(symbol: str) -> int:
    info = mt5.symbol_info(symbol)
    return info.digits if info else 2
