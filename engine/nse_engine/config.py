"""Tunable knobs for the NSE screener.

Everything the user is likely to want to change lives here. The Android app
mirrors these as settings; the CLI can override them with flags.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict, Tuple

# --------------------------------------------------------------------------
# Screener thresholds
# --------------------------------------------------------------------------


@dataclass
class ScreenConfig:
    #: A day "counts" toward the streak when the close-to-close return >= this.
    daily_gain_pct: float = 3.0
    #: How many consecutive qualifying days constitute a hit.
    streak_days: int = 3
    #: Reject names whose 20-day median traded value is below this (INR crore).
    #: Filters out illiquid counters where a 3% move means almost nothing.
    min_median_turnover_cr: float = 5.0
    #: Reject names below this market cap (INR crore). 0 disables the check.
    #: Applied after the screen, during enrichment, so we don't pay 500 extra
    #: requests to filter a universe that is already large-cap by construction.
    min_market_cap_cr: float = 1000.0
    #: Trading days of history to pull. Needs to cover the 20d volume window
    #: plus the 52-week context used in the fundamentals scorecard.
    history_days: int = 260
    #: How many top gainers and losers to surface per session.
    top_movers: int = 3
    #: How far behind the market consensus a stock's last bar may be before we
    #: treat it as suspended rather than merely late. Yahoo routinely backfills
    #: a third of the NSE universe a session late, so demanding an exact match
    #: silently drops those names; genuinely suspended stocks go stale for
    #: weeks and are still excluded.
    max_lag_days: int = 5

    def as_dict(self) -> Dict:
        return asdict(self)


# --------------------------------------------------------------------------
# Sector index mapping
# --------------------------------------------------------------------------
# Maps the NSE "Industry" label (as it appears in ind_nifty500list.csv) to the
# Yahoo ticker for the matching sector index, plus a quality flag.
#
#   "direct" - the index really does track this industry.
#   "proxy"  - related but imperfect; say so in the attribution text.
#   "broad"  - no sector index exists; we fall back to Nifty 500.
#
# The flag exists so the app can be honest. Claiming "Nifty Chemicals rose 2%"
# when no such index exists would be worse than admitting we only know the
# broad market moved.

SectorMap = Dict[str, Tuple[str, str]]

INDUSTRY_TO_INDEX: SectorMap = {
    "Financial Services":             ("NIFTY_FIN_SERVICE.NS", "direct"),
    "Information Technology":         ("^CNXIT",               "direct"),
    "Healthcare":                     ("^CNXPHARMA",           "direct"),
    "Automobile and Auto Components": ("^CNXAUTO",             "direct"),
    "Fast Moving Consumer Goods":     ("^CNXFMCG",             "direct"),
    "Metals & Mining":                ("^CNXMETAL",            "direct"),
    "Oil Gas & Consumable Fuels":     ("^CNXENERGY",           "direct"),
    "Realty":                         ("^CNXREALTY",           "direct"),
    "Media Entertainment & Publication": ("^CNXMEDIA",         "direct"),
    "Consumer Services":              ("^CNXCONSUM",           "proxy"),
    "Consumer Durables":              ("^CNXCONSUM",           "proxy"),
    "Services":                       ("^CNXSERVICE",          "proxy"),
    "Power":                          ("^CNXENERGY",           "proxy"),
    "Construction":                   ("^CNXINFRA",            "proxy"),
    "Construction Materials":         ("^CNXINFRA",            "proxy"),
    "Capital Goods":                  ("^CNXINFRA",            "proxy"),
    "Chemicals":                      ("^CRSLDX",              "broad"),
    "Telecommunication":              ("^CRSLDX",              "broad"),
    "Textiles":                       ("^CRSLDX",              "broad"),
    "Diversified":                    ("^CRSLDX",              "broad"),
}

BROAD_MARKET_INDEX = "^CRSLDX"   # Nifty 500
HEADLINE_INDEX = "^NSEI"         # Nifty 50


def index_for_industry(industry: str) -> Tuple[str, str]:
    """Return (yahoo_ticker, quality) for an NSE industry label."""
    return INDUSTRY_TO_INDEX.get(industry.strip(), (BROAD_MARKET_INDEX, "broad"))


def all_index_tickers() -> list[str]:
    """Every index ticker the pipeline needs to fetch, deduplicated."""
    tickers = {BROAD_MARKET_INDEX, HEADLINE_INDEX}
    tickers.update(t for t, _ in INDUSTRY_TO_INDEX.values())
    return sorted(tickers)


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------

NIFTY500_CSV = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"
EQUITY_MASTER_CSV = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
YAHOO_QUOTESUMMARY = "https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
YAHOO_CRUMB = "https://query1.finance.yahoo.com/v1/test/getcrumb"
YAHOO_COOKIE_SEED = "https://fc.yahoo.com/"
NSE_HOME = "https://www.nseindia.com/"
NSE_ANNOUNCEMENTS = "https://www.nseindia.com/api/corporate-announcements"
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"

IST_OFFSET_HOURS = 5.5
