"""Tests for the screening and attribution logic.

Everything here runs offline on synthetic bars. The cases were chosen from
failures actually hit while building the engine, not invented afterwards -
notably the stale-feed regression, which silently emptied a live scan.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nse_engine.attribution import _classify, explain
from nse_engine.config import ScreenConfig
from nse_engine.prices import Bar, Series
from nse_engine.screener import find_hits
from nse_engine.sector import MarketContext, SectorMove
from nse_engine.universe import Stock


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def make_series(symbol: str, daily_returns, start_price=100.0, volume=1_000_000,
                end=date(2026, 8, 28), gap_days=0):
    """Build a Series whose close-to-close returns match ``daily_returns``."""
    prices = [start_price]
    for r in daily_returns:
        prices.append(prices[-1] * (1 + r / 100.0))

    bars = []
    # Walk backwards from ``end`` so the final bar lands on the session we want.
    d = end - timedelta(days=gap_days)
    dates = []
    for _ in prices:
        while d.weekday() >= 5:      # skip weekends
            d -= timedelta(days=1)
        dates.append(d)
        d -= timedelta(days=1)
    dates.reverse()

    for dt, px in zip(dates, prices):
        bars.append(Bar(date=dt.isoformat(), open=px, high=px, low=px,
                        close=px, adj_close=px, volume=volume))
    return Series(symbol=symbol, bars=bars)


STOCK = Stock(symbol="TEST", name="Test Ltd", industry="Metals & Mining", isin="X")


def universe_of(*symbols):
    return [Stock(symbol=s, name=f"{s} Ltd", industry="Metals & Mining", isin="")
            for s in symbols]


# --------------------------------------------------------------------------
# streak detection
# --------------------------------------------------------------------------

def test_detects_three_day_streak():
    series = {"TEST.NS": make_series("TEST.NS", [0.1, -0.5, 3.5, 4.0, 3.2])}
    hits = find_hits(universe_of("TEST"), series, ScreenConfig())
    assert len(hits) == 1
    assert [d.gain_pct for d in hits[0].days] == [3.5, 4.0, 3.2]


def test_exactly_at_threshold_counts():
    """>= 3.0 must include 3.0 itself, not just values above it."""
    series = {"TEST.NS": make_series("TEST.NS", [0.0, 3.0, 3.0, 3.0])}
    assert len(find_hits(universe_of("TEST"), series, ScreenConfig())) == 1


def test_just_below_threshold_rejected():
    series = {"TEST.NS": make_series("TEST.NS", [0.0, 3.0, 2.99, 3.0])}
    assert find_hits(universe_of("TEST"), series, ScreenConfig()) == []


def test_broken_streak_rejected():
    """A big move four days ago does not rescue a flat final session."""
    series = {"TEST.NS": make_series("TEST.NS", [9.0, 9.0, 9.0, 0.2])}
    assert find_hits(universe_of("TEST"), series, ScreenConfig()) == []


def test_insufficient_history_rejected():
    series = {"TEST.NS": make_series("TEST.NS", [5.0, 5.0])}
    assert find_hits(universe_of("TEST"), series, ScreenConfig()) == []


def test_cumulative_return_compounds():
    """Three 10% days compound to 33.1%, not 30%."""
    series = {"TEST.NS": make_series("TEST.NS", [0.0, 10.0, 10.0, 10.0])}
    hit = find_hits(universe_of("TEST"), series, ScreenConfig())[0]
    assert hit.cumulative_pct == pytest.approx(33.1, abs=0.05)


# --------------------------------------------------------------------------
# staleness - the regression that silently emptied a live scan
# --------------------------------------------------------------------------

def test_suspended_stock_excluded():
    """A month-old streak must not fire as though it happened today."""
    fresh = make_series("FRESH.NS", [0.0, 0.1, 0.1, 0.1])
    stale = make_series("STALE.NS", [0.0, 5.0, 5.0, 5.0], gap_days=40)
    hits = find_hits(universe_of("FRESH", "STALE"),
                     {"FRESH.NS": fresh, "STALE.NS": stale}, ScreenConfig())
    assert hits == []


def test_one_session_lag_still_reported():
    """Yahoo routinely backfills part of the universe a session late. Those
    names must still be screened, flagged as lagging rather than dropped."""
    current = {f"C{i}.NS": make_series(f"C{i}.NS", [0.0, 0.1, 0.1, 0.1]) for i in range(5)}
    lagging = make_series("LAG.NS", [0.0, 4.0, 4.0, 4.0], gap_days=1)
    universe = universe_of(*[f"C{i}" for i in range(5)], "LAG")
    hits = find_hits(universe, {**current, "LAG.NS": lagging}, ScreenConfig())
    assert len(hits) == 1
    assert hits[0].symbol == "LAG"
    assert hits[0].is_current is False


# --------------------------------------------------------------------------
# liquidity filter
# --------------------------------------------------------------------------

def test_illiquid_name_filtered_out():
    thin = make_series("THIN.NS", [0.0, 5.0, 5.0, 5.0], start_price=10.0, volume=100)
    hits = find_hits(universe_of("THIN"), {"THIN.NS": thin},
                     ScreenConfig(min_median_turnover_cr=5.0))
    assert hits == []


def test_liquidity_floor_can_be_disabled():
    thin = make_series("THIN.NS", [0.0, 5.0, 5.0, 5.0], start_price=10.0, volume=100)
    hits = find_hits(universe_of("THIN"), {"THIN.NS": thin},
                     ScreenConfig(min_median_turnover_cr=0.0))
    assert len(hits) == 1


# --------------------------------------------------------------------------
# filing classification
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("Spurt in Volume", "caution"),
    ("Awarded a Letter of Award for a new order", "catalyst"),
    ("Financial Results for the quarter ended", "catalyst"),
    ("Moved to Additional Surveillance Measure ASM framework", "caution"),
    ("Promoter has created a pledge over shares", "caution"),
    ("Copy of Newspaper Publication", "neutral"),
    ("Credit Rating- Revision", "catalyst"),
    ("Cessation of Mr X as Director", "caution"),
])
def test_filing_buckets(text, expected):
    assert _classify(text)[0] == expected


def test_caution_outranks_catalyst():
    """A surveillance notice about a company that also won an order is still,
    first and foremost, a warning."""
    bucket, _ = _classify("Spurt in Volume following a new order win")
    assert bucket == "caution"


# --------------------------------------------------------------------------
# attribution verdicts
# --------------------------------------------------------------------------

def _context(sector_streak, breadth, market_streak=0.0):
    move = SectorMove("Metals & Mining", 1.0, sector_streak, members=20,
                      advancing=int(20 * breadth / 100))
    market = SectorMove("_market", 0.0, market_streak, members=400, advancing=200)
    return MarketContext(session="2026-08-28", sectors={"Metals & Mining": move},
                         market=market)


def _hit(cum_pct):
    series = {"TEST.NS": make_series("TEST.NS", [0.0, 3.5, 3.5, 3.5])}
    hit = find_hits([STOCK], series, ScreenConfig(min_median_turnover_cr=0.0))[0]
    hit.cumulative_pct = cum_pct
    return hit


def test_sector_wide_move_is_not_called_company_specific():
    """The whole sector rallying is the explanation - do not invent one."""
    a = explain(_hit(11.0), _context(sector_streak=10.0, breadth=85.0), [], [])
    assert a.verdict == "sector_wide"


def test_large_excess_without_filing_is_unexplained():
    a = explain(_hit(22.0), _context(sector_streak=1.0, breadth=50.0), [], [])
    assert a.verdict == "unexplained"
    assert a.excess_vs_sector_pct == pytest.approx(21.0)


def test_narrow_breadth_blocks_the_sector_explanation():
    """A sector median dragged up by two heavyweights, with most members flat,
    does not explain an individual stock's move."""
    a = explain(_hit(11.0), _context(sector_streak=10.0, breadth=25.0), [], [])
    assert a.verdict != "sector_wide"


def test_thin_liquidity_raises_a_caution():
    hit = _hit(22.0)
    hit.median_turnover_cr = 4.0
    a = explain(hit, _context(1.0, 50.0), [], [])
    assert any("liquidity" in c.lower() for c in a.cautions)
