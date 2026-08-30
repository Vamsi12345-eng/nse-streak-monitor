"""Sector and breadth statistics, computed from constituents.

Yahoo publishes the NSE sector indices on an unreliable cadence - most of them
have been observed six weeks stale while the stocks inside them were current.
Attribution built on those numbers would silently compare today's move against
a stale index level and state the conclusion with total confidence, which is
the worst possible failure mode for this app.

So we never ask for a sector index. We already hold daily bars for every Nifty
500 name tagged with its NSE industry, so the sector move is derived directly
from them. That is always exactly as fresh as the price data, costs no extra
requests, and equal-weighting answers "did the whole sector move?" better than
a cap-weighted index would - under cap weighting two heavyweights can carry a
sector that most of its members sat out.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from statistics import median
from typing import Dict, List, Optional

from .prices import Series
from .universe import Stock

log = logging.getLogger(__name__)

#: An industry needs at least this many usable members before its median is
#: worth quoting. "Diversified" has only 3 names in the Nifty 500, and a
#: 3-stock median is not a sector signal.
MIN_MEMBERS = 5


@dataclass
class SectorMove:
    industry: str
    median_return_pct: float      # median 1-day return of members
    median_streak_return_pct: float  # median return over the streak window
    members: int
    advancing: int                # members up on the session

    @property
    def breadth_pct(self) -> float:
        return (self.advancing / self.members) * 100.0 if self.members else 0.0

    @property
    def is_reliable(self) -> bool:
        return self.members >= MIN_MEMBERS


@dataclass
class MarketContext:
    """Everything needed to say whether a move was stock-specific."""

    session: str
    sectors: Dict[str, SectorMove]
    market: SectorMove              # all names pooled, as the broad benchmark

    def sector_for(self, industry: str) -> Optional[SectorMove]:
        move = self.sectors.get(industry)
        return move if move and move.is_reliable else None


def _window_return(series: Series, sessions: int) -> Optional[float]:
    return series.return_over(sessions)


def build_context(
    universe: List[Stock],
    series_by_symbol: Dict[str, Series],
    session: str,
    streak_days: int = 3,
) -> MarketContext:
    """Aggregate per-industry and whole-market moves for ``session``.

    Only series whose last bar is ``session`` contribute, so a stock that has
    not printed today cannot drag a sector median toward a stale value.
    """
    industry_of = {s.symbol: s.industry for s in universe}

    daily: Dict[str, List[float]] = defaultdict(list)
    streak: Dict[str, List[float]] = defaultdict(list)
    all_daily: List[float] = []
    all_streak: List[float] = []

    for yahoo_sym, series in series_by_symbol.items():
        if not series.bars or series.bars[-1].date != session:
            continue
        symbol = yahoo_sym[:-3] if yahoo_sym.endswith(".NS") else yahoo_sym
        industry = industry_of.get(symbol)
        if not industry:
            continue

        rets = series.returns_pct()
        if not rets:
            continue
        day_ret = rets[-1]
        win_ret = _window_return(series, streak_days)

        daily[industry].append(day_ret)
        all_daily.append(day_ret)
        if win_ret is not None:
            streak[industry].append(win_ret)
            all_streak.append(win_ret)

    sectors: Dict[str, SectorMove] = {}
    for industry, values in daily.items():
        sectors[industry] = SectorMove(
            industry=industry,
            median_return_pct=round(median(values), 2),
            median_streak_return_pct=(
                round(median(streak[industry]), 2) if streak.get(industry) else 0.0
            ),
            members=len(values),
            advancing=sum(1 for v in values if v > 0),
        )

    market = SectorMove(
        industry="_market",
        median_return_pct=round(median(all_daily), 2) if all_daily else 0.0,
        median_streak_return_pct=round(median(all_streak), 2) if all_streak else 0.0,
        members=len(all_daily),
        advancing=sum(1 for v in all_daily if v > 0),
    )

    log.info(
        "market context for %s: %d names, median day %+.2f%%, breadth %.0f%% advancing",
        session, market.members, market.median_return_pct, market.breadth_pct,
    )
    return MarketContext(session=session, sectors=sectors, market=market)
