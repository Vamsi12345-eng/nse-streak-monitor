"""The streak detector: N consecutive sessions each gaining >= X%."""
from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional

from .config import ScreenConfig
from .prices import Series
from .universe import Stock

log = logging.getLogger(__name__)

#: Tolerance for the daily-gain comparison. Large enough to absorb binary
#: floating-point error on a price ratio, far too small to admit a move the
#: user would not consider a match.
GAIN_EPSILON = 1e-9


@dataclass
class StreakDay:
    date: str
    close: float
    gain_pct: float
    volume: int


@dataclass
class Hit:
    """A stock that satisfied the streak condition."""

    stock: Stock
    days: List[StreakDay]
    cumulative_pct: float
    median_turnover_cr: float
    volume_ratio: Optional[float]
    pct_from_52w_high: Optional[float]
    return_1m: Optional[float]
    return_3m: Optional[float]
    return_1y: Optional[float]
    last_close: float
    #: True when the streak ends on the market's latest session. False means
    #: the feed is lagging for this name and the streak is a session or two
    #: old - still real, but the UI should say so rather than imply "today".
    is_current: bool = True

    @property
    def symbol(self) -> str:
        return self.stock.symbol

    @property
    def start_date(self) -> str:
        return self.days[0].date

    @property
    def end_date(self) -> str:
        return self.days[-1].date


def _reference_session(
    series_by_symbol: Dict[str, Series],
    index_series: Optional[Series] = None,
) -> Optional[str]:
    """The date of the most recent completed session, by majority vote.

    Suspended or halted stocks go stale silently - Yahoo keeps serving their
    last good bars with no error - and a week-old streak must not fire as
    though it happened today. So we need a reference date to compare against.

    An index looks like the obvious source, but Yahoo publishes index series on
    a slower cadence than the constituents: the Nifty 500 series has been
    observed a full session behind the stocks inside it, which would flag every
    up-to-date stock as stale and silently empty the scan. The modal last-bar
    date across hundreds of names is the far sturdier signal - genuinely
    suspended names are always the minority.
    """
    dates = [s.bars[-1].date for s in series_by_symbol.values() if s.bars]
    if not dates:
        return None
    modal, count = Counter(dates).most_common(1)[0]

    if index_series and index_series.bars:
        index_date = index_series.bars[-1].date
        if index_date != modal:
            log.info(
                "index last bar (%s) lags the constituent consensus (%s, %d/%d names); "
                "trusting the consensus",
                index_date, modal, count, len(dates),
            )
    return modal


def find_hits(
    universe: List[Stock],
    series_by_symbol: Dict[str, Series],
    cfg: ScreenConfig,
    index_series: Optional[Series] = None,
) -> List[Hit]:
    """Return every stock whose last ``cfg.streak_days`` sessions each gained
    at least ``cfg.daily_gain_pct``, ranked by cumulative move."""
    ref_date = _reference_session(series_by_symbol, index_series)
    hits: List[Hit] = []
    skipped_stale = 0
    skipped_illiquid = 0

    by_symbol = {s.symbol: s for s in universe}

    for yahoo_sym, series in series_by_symbol.items():
        symbol = yahoo_sym[:-3] if yahoo_sym.endswith(".NS") else yahoo_sym
        stock = by_symbol.get(symbol)
        if stock is None:
            continue

        # Need streak_days returns, which needs streak_days + 1 closes.
        if len(series) < cfg.streak_days + 1:
            continue

        # Reject series that have gone quiet for long enough to look suspended.
        # A one-session lag is normal Yahoo backfill behaviour, not suspension,
        # so we tolerate it and report the streak's real end date instead.
        last_date = series.bars[-1].date
        if ref_date and _days_between(last_date, ref_date) > cfg.max_lag_days:
            skipped_stale += 1
            continue

        rets = series.returns_pct()
        window = rets[-cfg.streak_days:]
        if len(window) < cfg.streak_days:
            continue
        # Compared with a tolerance because binary floating point cannot hold
        # an exact 3%: a 103.00 close against a 100.00 base evaluates to
        # 2.9999999999999964, which a strict >= would silently reject.
        if not all(r >= cfg.daily_gain_pct - GAIN_EPSILON for r in window):
            continue

        turnover = series.median_turnover_cr()
        if turnover < cfg.min_median_turnover_cr:
            skipped_illiquid += 1
            continue

        streak_bars = series.bars[-cfg.streak_days:]
        days = [
            StreakDay(date=b.date, close=b.close, gain_pct=round(r, 2), volume=b.volume)
            for b, r in zip(streak_bars, window)
        ]

        # Compound the daily moves rather than summing them.
        cumulative = 1.0
        for r in window:
            cumulative *= 1 + r / 100.0
        cumulative_pct = (cumulative - 1) * 100.0

        hits.append(
            Hit(
                stock=stock,
                days=days,
                cumulative_pct=round(cumulative_pct, 2),
                median_turnover_cr=round(turnover, 1),
                volume_ratio=round(series.volume_ratio(), 2) if series.volume_ratio() else None,
                pct_from_52w_high=(
                    round(series.pct_from_52w_high(), 1)
                    if series.pct_from_52w_high() is not None else None
                ),
                return_1m=_rounded(series.return_over(21)),
                return_3m=_rounded(series.return_over(63)),
                return_1y=_rounded(series.return_over(250)),
                last_close=series.bars[-1].close,
                is_current=(last_date == ref_date) if ref_date else True,
            )
        )

    if skipped_stale:
        log.info("skipped %d symbols with stale price data", skipped_stale)
    if skipped_illiquid:
        log.info("skipped %d symbols below the liquidity floor", skipped_illiquid)

    hits.sort(key=lambda h: h.cumulative_pct, reverse=True)
    return hits


def _rounded(value: Optional[float]) -> Optional[float]:
    return round(value, 1) if value is not None else None


def _days_between(earlier: str, later: str) -> int:
    """Calendar days between two YYYY-MM-DD strings, clamped at zero."""
    try:
        d0 = date.fromisoformat(earlier)
        d1 = date.fromisoformat(later)
    except ValueError:
        return 0
    return max((d1 - d0).days, 0)
