"""
News & major event filter.
Blocks trading 15 minutes before and after any high-impact event.

Sources:
  1. NewsAPI (free 100 req/day) -- scans headlines for trigger words
  2. Hardcoded recurring calendar (FOMC, NFP, CPI etc.)
"""

import os
import logging
import requests
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("news_filter")

NEWS_API_KEY  = os.getenv("NEWS_API_KEY", "")
BLOCK_MINUTES = 15   # minutes to block before and after an event

# -- Cache -- only call NewsAPI once every 30 minutes --------------
_news_cache        = {"blocked": False, "reason": "", "fetched_at": None}
NEWS_CACHE_MINUTES = 30

# -- Failure backoff -- skip retrying when API is unreachable ------
_api_fail_count    = 0
_api_retry_after   = None   # datetime after which we try again
API_BACKOFF_MINUTES = 60    # after 3 failures, pause for 60 min

# -- High-impact keywords -----------------------------------------
BLOCK_KEYWORDS = [
    # Fed / central banks
    "federal reserve", "fed rate", "fomc", "rate decision", "rate hike",
    "rate cut", "interest rate", "ecb rate", "boe rate", "boj rate",
    "powell", "lagarde", "bailey",
    # Economic data
    "non-farm payroll", "nfp", "cpi", "inflation report", "gdp",
    "ppi", "unemployment", "jobless claims", "ism manufacturing", "pce",
    "retail sales", "jobs report",
    # Geopolitical / macro shocks
    "war", "invasion", "nuclear", "military strike", "ceasefire",
    "sanctions", "default", "debt ceiling",
    "bank collapse", "market crash", "black swan",
    # Crypto-specific
    "sec ruling", "crypto ban", "btc etf", "exchange hack",
    # Gold / commodity
    "opec", "oil embargo", "strait of hormuz",
    # Trade / deals
    "trade deal", "trade war", "tariff", "treaty signed",
]

# -- Recurring calendar events (approximate UTC hour) ------------
# Format: (month, day, utc_hour_approx, label)
# These are dates/times that repeat every year or every meeting.
# We use approximate detection -- the bot will look BLOCK_MINUTES around them.
# You should update this list monthly or subscribe to a proper calendar API.
CALENDAR_EVENTS_2026 = [
    # FOMC meetings 2026 (approximate -- check federalreserve.gov for exact dates)
    (1, 28, 19, "FOMC January 2026"),
    (3, 18, 18, "FOMC March 2026"),       # TODAY -- already in progress
    (5, 6,  18, "FOMC May 2026"),
    (6, 17, 18, "FOMC June 2026"),
    (7, 29, 18, "FOMC July 2026"),
    (9, 16, 18, "FOMC September 2026"),
    (11, 4, 18, "FOMC November 2026"),
    (12, 16, 18, "FOMC December 2026"),

    # US NFP -- first Friday of each month at 12:30 UTC
    (1,  2, 12, "NFP January 2026"),
    (2,  6, 12, "NFP February 2026"),
    (3,  6, 12, "NFP March 2026"),
    (4,  3, 12, "NFP April 2026"),
    (5,  1, 12, "NFP May 2026"),
    (6,  5, 12, "NFP June 2026"),
    (7,  3, 12, "NFP July 2026"),
    (8,  7, 12, "NFP August 2026"),
    (9,  4, 12, "NFP September 2026"),
    (10, 2, 12, "NFP October 2026"),
    (11, 6, 12, "NFP November 2026"),
    (12, 4, 12, "NFP December 2026"),

    # US CPI -- roughly 2nd Tuesday each month at 12:30 UTC
    (1, 13, 13, "CPI January 2026"),
    (2, 10, 13, "CPI February 2026"),
    (3, 11, 13, "CPI March 2026"),
    (4, 10, 13, "CPI April 2026"),
    (5, 13, 13, "CPI May 2026"),
    (6, 10, 13, "CPI June 2026"),
    (7, 14, 13, "CPI July 2026"),
    (8, 11, 13, "CPI August 2026"),
    (9, 10, 13, "CPI September 2026"),
    (10, 14, 13, "CPI October 2026"),
    (11, 10, 13, "CPI November 2026"),
    (12, 9, 13, "CPI December 2026"),
]


def _check_calendar() -> tuple:
    """Check if now is within BLOCK_MINUTES of a hardcoded calendar event."""
    now = datetime.now(timezone.utc)
    for month, day, hour_utc, label in CALENDAR_EVENTS_2026:
        event_dt = datetime(now.year, month, day, hour_utc, 0, 0, tzinfo=timezone.utc)
        delta = abs((now - event_dt).total_seconds() / 60)
        if delta <= BLOCK_MINUTES:
            return True, label
    return False, ""


def _check_newsapi() -> tuple:
    """Search recent headlines for block keywords via NewsAPI.
    Result is cached for 30 minutes to stay within free tier (100 req/day).
    After 3 consecutive failures, backs off for 60 minutes to avoid log spam."""
    global _api_fail_count, _api_retry_after

    if not NEWS_API_KEY or NEWS_API_KEY == "your_newsapi_key_here":
        return False, ""

    now = datetime.now(timezone.utc)

    # Backoff: if API repeatedly failing, stop retrying until backoff expires
    if _api_retry_after and now < _api_retry_after:
        return _news_cache["blocked"], _news_cache["reason"]

    # Return cached result if fresh
    if _news_cache["fetched_at"] is not None:
        age = (now - _news_cache["fetched_at"]).total_seconds() / 60
        if age < NEWS_CACHE_MINUTES:
            return _news_cache["blocked"], _news_cache["reason"]

    try:
        url = (
            "https://newsapi.org/v2/everything"
            f"q=gold+OR+bitcoin+OR+forex+OR+fed"
            f"&sortBy=publishedAt&pageSize=20"
            f"&apiKey={NEWS_API_KEY}"
        )
        resp = requests.get(url, timeout=5)
        if resp.status_code != 200:
            _api_fail_count += 1
            return False, ""

        # Success -- reset failure count
        _api_fail_count  = 0
        _api_retry_after = None

        articles = resp.json().get("articles", [])
        for article in articles:
            title = (article.get("title") or "").lower()
            desc  = (article.get("description") or "").lower()
            text  = title + " " + desc

            for kw in BLOCK_KEYWORDS:
                if kw in text:
                    # Only block if article is recent (< 30 min)
                    pub = article.get("publishedAt", "")
                    if pub:
                        try:
                            pub_dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                            age_min = (datetime.now(timezone.utc) - pub_dt).total_seconds() / 60
                            if age_min < 30:
                                return True, f"Recent headline: {article.get('title', '')[:60]}"
                        except Exception:
                            pass
    except Exception as e:
        _api_fail_count += 1
        if _api_fail_count == 1:
            logger.warning("NewsAPI unavailable: %s", e)
        elif _api_fail_count >= 3:
            _api_retry_after = now + timedelta(minutes=API_BACKOFF_MINUTES)
            logger.info("NewsAPI down -- pausing checks for %d min (calendar protection still active)",
                        API_BACKOFF_MINUTES)
            _api_fail_count = 0
        return _news_cache["blocked"], _news_cache["reason"]

    # Update cache
    _news_cache["blocked"]    = False
    _news_cache["reason"]     = ""
    _news_cache["fetched_at"] = datetime.now(timezone.utc)
    return False, ""


def is_blocked() -> tuple:
    """
    Returns (blocked: bool, reason: str).
    Call this before every trade decision.
    """
    blocked_cal, reason_cal = _check_calendar()
    if blocked_cal:
        logger.warning("NEWS BLOCK (calendar): %s", reason_cal)
        return True, f"High-impact calendar event: {reason_cal}"

    blocked_news, reason_news = _check_newsapi()
    if blocked_news:
        logger.warning("NEWS BLOCK (headlines): %s", reason_news)
        return True, f"Breaking news detected: {reason_news}"

    return False, ""


# -- Aliases for Bot 2 (VISHU_ELITE_BOT) -------------------------
def is_news_blocked(symbol: str = "") -> tuple:
    return is_blocked()

def get_next_news_event() -> str:
    now = datetime.now(timezone.utc)
    upcoming = []
    for month, day, hour_utc, label in CALENDAR_EVENTS_2026:
        event_dt = datetime(now.year, month, day, hour_utc, 0, 0, tzinfo=timezone.utc)
        if event_dt > now:
            mins_away = (event_dt - now).total_seconds() / 60
            upcoming.append((mins_away, label))
    if not upcoming:
        return ""
    upcoming.sort()
    mins, label = upcoming[0]
    return f"{label} in {int(mins)} min" if mins < 1440 else ""

# -- Aliases for Bot 3 (VISHU_SMC_BOT) ---------------------------
def is_news_window(symbol: str = "") -> tuple:
    return is_blocked()

def is_pre_news_accumulation(symbol: str = "") -> tuple:
    now = datetime.now(timezone.utc)
    for month, day, hour_utc, label in CALENDAR_EVENTS_2026:
        event_dt = datetime(now.year, month, day, hour_utc, 0, 0, tzinfo=timezone.utc)
        mins_to_event = (event_dt - now).total_seconds() / 60
        if 0 < mins_to_event <= 120:
            return True, label, round(mins_to_event / 60, 2)
    return False, "", 0.0
