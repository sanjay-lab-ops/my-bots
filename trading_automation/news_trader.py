"""
News-Driven Trading Engine
===========================
Instead of only BLOCKING trades on news — this module TRADES the news direction.

Logic:
  1. Detects high-impact economic events from headlines
  2. Determines expected market direction for Gold and BTC
  3. Returns a trade signal with direction + confidence
  4. Uses wider SL (news = more volatile) + smaller lot (more risk)

News → Expected Impact:
  Fed rate CUT     → USD weak  → Gold UP ↑  BTC UP ↑
  Fed rate HIKE    → USD strong→ Gold DOWN↓  BTC DOWN↓
  Fed HOLD dovish  → rate cut coming → Gold UP ↑
  Fed HOLD hawkish → no cuts soon    → Gold DOWN↓
  NFP beats        → USD UP   → Gold DOWN↓
  NFP misses       → USD DOWN → Gold UP ↑
  CPI high         → inflation → Gold UP ↑  (safe haven)
  CPI low          → rate cuts → Gold UP ↑  BTC UP ↑
  War/conflict     → fear      → Gold UP ↑  BTC DOWN↓
  Ceasefire/peace  → risk on   → Gold DOWN↓ BTC UP ↑
  GDP beats        → USD UP    → Gold DOWN↓
  GDP misses       → USD DOWN  → Gold UP ↑
"""

import os
import logging
import requests
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("news_trader")

NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")

# ── News event rules ─────────────────────────────────────────────
# Each rule: (keywords_that_trigger, gold_direction, btc_direction, confidence, label)
NEWS_RULES = [
    # Fed cuts rates
    (["rate cut", "cuts rates", "lowers rates", "dovish", "rate reduction",
      "pivot", "easing", "quantitative easing", "qe"],
     "buy", "buy", 85, "Fed dovish/rate cut"),

    # Fed hikes or holds hawkish
    (["rate hike", "raises rates", "hawkish", "tightening", "quantitative tightening",
      "higher for longer", "no rate cut"],
     "sell", "sell", 80, "Fed hawkish/rate hike"),

    # NFP beats (good jobs = USD strong)
    (["nonfarm payroll beats", "jobs beat", "strong jobs", "better than expected jobs",
      "employment surges", "unemployment falls"],
     "sell", "neutral", 75, "NFP beats expectations"),

    # NFP misses (bad jobs = USD weak)
    (["nonfarm payroll miss", "jobs miss", "weak jobs", "fewer jobs than expected",
      "unemployment rises", "layoffs surge"],
     "buy", "neutral", 75, "NFP misses expectations"),

    # CPI high (inflation = gold hedge)
    (["inflation surges", "cpi rises", "cpi beats", "higher inflation",
      "inflation higher than expected", "prices surge"],
     "buy", "buy", 70, "CPI high — inflation hedge"),

    # CPI low (rate cuts expected)
    (["inflation falls", "cpi drops", "cpi misses", "lower inflation",
      "disinflation", "deflation"],
     "buy", "buy", 70, "CPI low — rate cut hopes"),

    # War / conflict / geopolitical shock
    (["war", "invasion", "military strike", "attack", "missile", "bomb",
      "conflict escalates", "troops deployed", "nuclear threat", "crisis"],
     "buy", "sell", 90, "Geopolitical shock — safe haven"),

    # Ceasefire / peace / de-escalation
    (["ceasefire", "peace deal", "de-escalation", "troops withdraw",
      "peace agreement", "conflict ends", "truce"],
     "sell", "buy", 75, "De-escalation — risk on"),

    # GDP beats
    (["gdp beats", "gdp surges", "strong growth", "economy grows faster",
      "gdp higher than expected"],
     "sell", "buy", 65, "GDP beats — USD strong"),

    # GDP misses
    (["gdp misses", "gdp falls", "recession", "economic contraction",
      "gdp lower than expected", "growth slows"],
     "buy", "sell", 70, "GDP miss — safe haven demand"),

    # Banking/financial crisis
    (["bank collapse", "bank run", "bank failure", "financial crisis",
      "credit crisis", "systemic risk"],
     "buy", "sell", 85, "Financial crisis — gold safe haven"),

    # Debt/default
    (["debt ceiling", "default", "sovereign debt", "credit downgrade",
      "us downgrade"],
     "buy", "neutral", 80, "Debt risk — gold safe haven"),

    # OPEC / oil shock (inflation = gold up)
    (["opec cuts", "oil embargo", "oil surge", "energy crisis"],
     "buy", "sell", 65, "Oil shock — inflation risk"),

    # Dollar strengthens sharply
    (["dollar surges", "usd rally", "dollar index rises", "dxy up"],
     "sell", "sell", 70, "USD strength — gold pressure"),

    # Dollar weakens
    (["dollar falls", "usd drops", "dollar weakens", "dxy down"],
     "buy", "buy", 70, "USD weakness — gold boost"),
]


@dataclass
class NewsSignal:
    symbol:     str   = ""
    action:     str   = "skip"   # 'buy', 'sell', 'skip'
    confidence: int   = 0        # 0–100
    reason:     str   = ""
    headline:   str   = ""
    sl_multiplier: float = 2.0   # wider SL for news trades
    lot_multiplier: float = 0.5  # smaller lot for news trades


def _fetch_headlines() -> list:
    """Fetch latest financial headlines from NewsAPI."""
    if not NEWS_API_KEY:
        return []
    try:
        url = (
            "https://newsapi.org/v2/everything"
            "?q=gold+OR+bitcoin+OR+fed+OR+inflation+OR+economy"
            "&sortBy=publishedAt&pageSize=30"
            f"&apiKey={NEWS_API_KEY}"
        )
        resp = requests.get(url, timeout=5)
        if resp.status_code != 200:
            return []
        articles = resp.json().get("articles", [])
        # Only articles from last 30 minutes
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
        fresh  = []
        for a in articles:
            pub = a.get("publishedAt", "")
            try:
                pub_dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                if pub_dt >= cutoff:
                    fresh.append(a)
            except Exception:
                pass
        return fresh
    except Exception as e:
        logger.warning("NewsAPI fetch failed: %s", e)
        return []


def _match_rules(text: str) -> tuple:
    """
    Match text against all news rules.
    Returns (gold_dir, btc_dir, confidence, label, matched_rule) or None.
    """
    text_lower = text.lower()
    best_match = None
    best_conf  = 0

    for keywords, gold_dir, btc_dir, conf, label in NEWS_RULES:
        for kw in keywords:
            if kw in text_lower:
                if conf > best_conf:
                    best_conf  = conf
                    best_match = (gold_dir, btc_dir, conf, label)
                break

    return best_match


def get_news_signal(symbol: str) -> NewsSignal:
    """
    Analyse latest headlines and return a trade signal for the given symbol.
    Returns NewsSignal with action='skip' if no actionable news found.
    """
    sig = NewsSignal(symbol=symbol)
    articles = _fetch_headlines()

    if not articles:
        return sig

    for article in articles:
        title = (article.get("title") or "").lower()
        desc  = (article.get("description") or "").lower()
        text  = title + " " + desc

        match = _match_rules(text)
        if not match:
            continue

        gold_dir, btc_dir, confidence, label = match

        if symbol == "XAUUSD":
            direction = gold_dir
        elif symbol == "BTCUSD":
            direction = btc_dir
        else:
            continue

        if direction == "neutral":
            continue

        if confidence > sig.confidence:
            sig.action     = direction
            sig.confidence = confidence
            sig.reason     = label
            sig.headline   = article.get("title", "")[:80]

    if sig.action != "skip":
        logger.info(
            "NEWS TRADE SIGNAL | %s | %s | Confidence: %d%% | %s",
            symbol, sig.action.upper(), sig.confidence, sig.reason
        )

    return sig


def news_trade_allowed(symbol: str, min_confidence: int = 70) -> NewsSignal:
    """
    Returns NewsSignal only if confidence >= min_confidence.
    Use this before entering a news-driven trade.
    """
    sig = get_news_signal(symbol)
    if sig.confidence < min_confidence:
        sig.action = "skip"
    return sig
