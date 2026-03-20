"""
Handles all MetaTrader 5 connection and data-fetching.
"""

import os
import logging
import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("mt5_connector")

# ── Timeframe map ────────────────────────────────────────────────
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
    """Initialize and login to MT5. Returns True on success."""
    login    = int(os.getenv("MT5_LOGIN", 0))
    password = os.getenv("MT5_PASSWORD", "")
    server   = os.getenv("MT5_SERVER", "")

    if not mt5.initialize():
        logger.error("MT5 initialize() failed: %s", mt5.last_error())
        return False

    if not mt5.login(login, password=password, server=server):
        logger.error("MT5 login failed: %s", mt5.last_error())
        mt5.shutdown()
        return False

    info = mt5.account_info()
    logger.info(
        "Connected to MT5 | Login: %s | Balance: %.2f %s | Server: %s",
        info.login, info.balance, info.currency, server,
    )
    return True


def disconnect():
    mt5.shutdown()
    logger.info("MT5 disconnected.")


def get_balance() -> float:
    info = mt5.account_info()
    return info.balance if info else 0.0


def get_candles(symbol: str, timeframe: str, count: int) -> pd.DataFrame:
    """
    Fetch 'count' candles for symbol/timeframe.
    Returns DataFrame with columns: time, open, high, low, close, tick_volume.
    """
    tf = TF_MAP.get(timeframe.upper())
    if tf is None:
        raise ValueError(f"Unknown timeframe: {timeframe}")

    rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)
    if rates is None or len(rates) == 0:
        logger.warning("No data for %s %s: %s", symbol, timeframe, mt5.last_error())
        return pd.DataFrame()

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df.set_index("time", inplace=True)
    return df


def get_symbol_info(symbol: str):
    """Return MT5 symbol info object (or None)."""
    info = mt5.symbol_info(symbol)
    if info is None:
        # Try enabling the symbol first
        mt5.symbol_select(symbol, True)
        info = mt5.symbol_info(symbol)
    return info


def get_open_positions(symbol: str = None):
    """Return list of open positions, optionally filtered by symbol."""
    positions = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
    return positions if positions else []


def get_current_price(symbol: str) -> tuple:
    """Return (bid, ask) for symbol."""
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return (0.0, 0.0)
    return (tick.bid, tick.ask)
