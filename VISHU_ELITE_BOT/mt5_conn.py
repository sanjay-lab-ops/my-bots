"""
VISHU ELITE BOT — MT5 Connection & Data Fetching
Handles all MetaTrader5 connection, login, candle fetch, and tick data.
"""

import logging
import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime, timezone
from config import MT5_LOGIN, MT5_PASSWORD, MT5_SERVER, MAGIC_NUMBER

logger = logging.getLogger("mt5_conn")

# ── Timeframe map ─────────────────────────────────────────────────
TF_MAP = {
    "M1":  mt5.TIMEFRAME_M1,
    "M5":  mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1":  mt5.TIMEFRAME_H1,
    "H4":  mt5.TIMEFRAME_H4,
    "D1":  mt5.TIMEFRAME_D1,
}


def connect() -> bool:
    """Initialize MT5 and login. Returns True on success."""
    if not mt5.initialize():
        logger.error("MT5 initialize() failed: %s", mt5.last_error())
        return False

    if not mt5.login(MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER):
        logger.error("MT5 login failed: %s", mt5.last_error())
        mt5.shutdown()
        return False

    info = mt5.account_info()
    logger.info(
        "Connected to MT5 | Login: %s | Balance: %.2f %s | Server: %s",
        info.login, info.balance, info.currency, MT5_SERVER,
    )
    return True


def disconnect():
    """Shutdown MT5 connection."""
    mt5.shutdown()
    logger.info("MT5 disconnected.")


def reconnect(max_attempts: int = 3) -> bool:
    """Attempt to reconnect to MT5 up to max_attempts times."""
    for attempt in range(1, max_attempts + 1):
        logger.info("Reconnect attempt %d/%d ...", attempt, max_attempts)
        mt5.shutdown()
        if connect():
            logger.info("Reconnected successfully.")
            return True
    logger.error("All reconnect attempts failed.")
    return False


def is_connected() -> bool:
    """Check if MT5 is currently connected."""
    info = mt5.account_info()
    return info is not None


def get_balance() -> float:
    """Return current account balance."""
    info = mt5.account_info()
    return info.balance if info else 0.0


def get_equity() -> float:
    """Return current account equity."""
    info = mt5.account_info()
    return info.equity if info else 0.0


def get_account_info() -> dict:
    """Return dict of key account fields."""
    info = mt5.account_info()
    if info is None:
        return {}
    return {
        "login":    info.login,
        "balance":  info.balance,
        "equity":   info.equity,
        "margin":   info.margin,
        "currency": info.currency,
        "server":   info.server,
        "leverage": info.leverage,
    }


def get_candles(symbol: str, timeframe: str, count: int) -> pd.DataFrame:
    """
    Fetch 'count' candles for symbol/timeframe.
    Returns DataFrame with index=time(UTC), columns: open/high/low/close/tick_volume.
    Returns empty DataFrame on failure.
    """
    tf = TF_MAP.get(timeframe.upper())
    if tf is None:
        logger.error("Unknown timeframe: %s", timeframe)
        return pd.DataFrame()

    # Ensure symbol is available
    if not mt5.symbol_info(symbol):
        mt5.symbol_select(symbol, True)

    rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)
    if rates is None or len(rates) == 0:
        logger.warning("No candle data for %s %s: %s", symbol, timeframe, mt5.last_error())
        return pd.DataFrame()

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df.set_index("time", inplace=True)
    return df


def get_current_price(symbol: str) -> tuple:
    """Return (bid, ask) for symbol. Returns (0.0, 0.0) on failure."""
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return (0.0, 0.0)
    return (tick.bid, tick.ask)


def get_open_positions(symbol: str = None) -> list:
    """Return list of open MT5 position objects, optionally filtered by symbol."""
    positions = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
    return list(positions) if positions else []


def get_bot_positions(symbol: str = None) -> list:
    """Return only positions opened by this bot (matching MAGIC_NUMBER)."""
    positions = get_open_positions(symbol)
    return [p for p in positions if p.magic == MAGIC_NUMBER]


def get_symbol_info(symbol: str):
    """Return MT5 symbol_info object, enabling the symbol if needed."""
    info = mt5.symbol_info(symbol)
    if info is None:
        mt5.symbol_select(symbol, True)
        info = mt5.symbol_info(symbol)
    return info


def get_day_pnl() -> float:
    """
    Calculate today's realized P&L from closed trades.
    Returns sum of profit for all deals closed today (UTC).
    """
    today = datetime.now(timezone.utc).date()
    from datetime import datetime as dt
    import time

    # Get deals from today
    utc_from = dt(today.year, today.month, today.day, 0, 0, 0, tzinfo=timezone.utc)
    utc_to   = dt(today.year, today.month, today.day, 23, 59, 59, tzinfo=timezone.utc)

    deals = mt5.history_deals_get(utc_from, utc_to)
    if not deals:
        return 0.0

    # Also include unrealized P&L from open positions
    open_pnl = sum(p.profit for p in get_open_positions())

    # Sum realized P&L from closed deals (entry deals have in/out flag)
    realized = sum(
        d.profit for d in deals
        if d.magic == MAGIC_NUMBER and d.entry == mt5.DEAL_ENTRY_OUT
    )
    return realized + open_pnl
