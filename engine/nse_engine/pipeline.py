"""End-to-end scan orchestration and JSON emission."""
from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from . import attribution as attr
from . import fundamentals as fx
from . import prices, sector
from .config import ScreenConfig
from .http import NSEClient, YahooClient
from .prompt import build_research_prompt
from .screener import Hit, find_hits
from .universe import Stock, load_universe

log = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

#: Enriching a hit costs roughly one NSE call, one RSS call and one Yahoo call
#: per industry peer. A pathological market day could flag dozens of names, so
#: the enrichment is capped and the rest are still reported, just without the
#: deep detail.
MAX_ENRICHED = 25


class ScanResult(dict):
    """The JSON document the app consumes. A dict subclass so it serialises
    directly while still reading as a named type at the call sites."""


def _hit_to_dict(hit: Hit) -> Dict[str, Any]:
    return {
        "symbol": hit.symbol,
        "name": hit.stock.name,
        "industry": hit.stock.industry,
        "isin": hit.stock.isin,
        "last_close": round(hit.last_close, 2),
        "cumulative_pct": hit.cumulative_pct,
        "start_date": hit.start_date,
        "end_date": hit.end_date,
        "is_current": hit.is_current,
        "median_turnover_cr": hit.median_turnover_cr,
        "volume_ratio": hit.volume_ratio,
        "pct_from_52w_high": hit.pct_from_52w_high,
        "returns": {
            "m1": hit.return_1m,
            "m3": hit.return_3m,
            "y1": hit.return_1y,
        },
        "days": [asdict(d) for d in hit.days],
    }


def _attr_to_dict(a: attr.Attribution) -> Dict[str, Any]:
    return {
        "verdict": a.verdict,
        "headline": a.headline,
        "explanation": a.explanation,
        "stock_streak_pct": a.stock_streak_pct,
        "sector_streak_pct": a.sector_streak_pct,
        "market_streak_pct": a.market_streak_pct,
        "excess_vs_sector_pct": a.excess_vs_sector_pct,
        "sector_breadth_pct": a.sector_breadth_pct,
        "volume_ratio": a.volume_ratio,
        "cautions": a.cautions,
        "filings": [asdict(f) for f in a.filings],
        "headlines": [asdict(h) for h in a.headlines],
    }


def run_scan(
    cfg: Optional[ScreenConfig] = None,
    watchlist: Optional[List[str]] = None,
    enrich: bool = True,
) -> ScanResult:
    """Run a full scan and return the result document."""
    cfg = cfg or ScreenConfig()
    yahoo = YahooClient()
    nse = NSEClient()

    universe = load_universe(nse, extra_symbols=watchlist)
    series = prices.fetch_many(yahoo, [s.yahoo for s in universe], cfg.history_days)
    if not series:
        raise RuntimeError("no price data retrieved; aborting scan")

    hits = find_hits(universe, series, cfg)
    session = _consensus_session(series)
    context = sector.build_context(universe, series, session, cfg.streak_days)

    log.info("scan found %d hit(s) for session %s", len(hits), session)

    stocks_by_industry: Dict[str, List[Stock]] = {}
    for s in universe:
        stocks_by_industry.setdefault(s.industry, []).append(s)

    # Peer fundamentals are fetched once per industry, not once per hit, so two
    # hits in the same sector share the work.
    peer_cache: Dict[str, Dict[str, fx.Fundamentals]] = {}
    hit_docs: List[Dict[str, Any]] = []

    for i, hit in enumerate(hits):
        doc = _hit_to_dict(hit)
        if enrich and i < MAX_ENRICHED:
            doc.update(_enrich(hit, context, yahoo, nse, stocks_by_industry, peer_cache, cfg))
        hit_docs.append(doc)

    return ScanResult(
        {
            "schema_version": 1,
            "generated_at": datetime.now(IST).isoformat(timespec="seconds"),
            "session": session,
            "config": cfg.as_dict(),
            "market": {
                "median_day_pct": context.market.median_return_pct,
                "median_streak_pct": context.market.median_streak_return_pct,
                "breadth_pct": round(context.market.breadth_pct, 1),
                "names": context.market.members,
            },
            "sectors": [
                {
                    "industry": m.industry,
                    "median_day_pct": m.median_return_pct,
                    "median_streak_pct": m.median_streak_return_pct,
                    "breadth_pct": round(m.breadth_pct, 1),
                    "members": m.members,
                    "reliable": m.is_reliable,
                }
                for m in sorted(
                    context.sectors.values(),
                    key=lambda x: x.median_return_pct,
                    reverse=True,
                )
            ],
            "hits": hit_docs,
            "stats": {
                "universe": len(universe),
                "with_prices": len(series),
                "hits": len(hits),
                "enriched": min(len(hits), MAX_ENRICHED) if enrich else 0,
            },
        }
    )


def _enrich(
    hit: Hit,
    context: sector.MarketContext,
    yahoo: YahooClient,
    nse: NSEClient,
    stocks_by_industry: Dict[str, List[Stock]],
    peer_cache: Dict[str, Dict[str, fx.Fundamentals]],
    cfg: ScreenConfig,
) -> Dict[str, Any]:
    """Gather filings, headlines, fundamentals and the research prompt."""
    industry = hit.stock.industry

    filings = attr.fetch_filings(nse, hit.symbol, hit.start_date, hit.end_date)
    headlines = attr.fetch_headlines(yahoo, hit.stock.name, hit.symbol)
    attribution = attr.explain(hit, context, filings, headlines)

    if industry not in peer_cache:
        peers = stocks_by_industry.get(industry, [])
        peer_cache[industry] = fx.fetch_many(yahoo, [p.yahoo for p in peers])
    funds_by_symbol = peer_cache[industry]

    fund = funds_by_symbol.get(hit.symbol)
    benchmark = fx.build_benchmark(
        industry, {k: v for k, v in funds_by_symbol.items() if k != hit.symbol}
    )
    scorecard = (
        fx.build_scorecard(hit.stock, fund, benchmark, hit.pct_from_52w_high, hit.return_1y)
        if fund
        else None
    )

    out: Dict[str, Any] = {
        "attribution": _attr_to_dict(attribution),
        "fundamentals": asdict(fund) if fund else None,
        "benchmark": asdict(benchmark),
        "scorecard": (
            {
                "factors": [asdict(f) for f in scorecard.factors],
                "bull_case": scorecard.bull_case,
                "bear_case": scorecard.bear_case,
                "invalidators": scorecard.invalidators,
                "data_gaps": scorecard.data_gaps,
                "bull_count": scorecard.bull_count,
                "bear_count": scorecard.bear_count,
            }
            if scorecard
            else None
        ),
        "research_prompt": build_research_prompt(
            hit, attribution, fund, benchmark, scorecard
        ),
    }

    # Applied here rather than in the screen itself: market cap needs a
    # fundamentals call, and paying for 500 of those to filter a universe that
    # is already large-cap by construction would be wasteful.
    if (
        cfg.min_market_cap_cr
        and fund
        and fund.market_cap_cr is not None
        and fund.market_cap_cr < cfg.min_market_cap_cr
    ):
        out["below_market_cap_floor"] = True
    return out


def _consensus_session(series_by_symbol: Dict[str, prices.Series]) -> str:
    from collections import Counter

    dates = [s.bars[-1].date for s in series_by_symbol.values() if s.bars]
    return Counter(dates).most_common(1)[0][0] if dates else ""
