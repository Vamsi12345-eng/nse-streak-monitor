"""Fundamentals and the one-year research scorecard.

This is the "does it have room to run?" half of the app, and the half most
likely to be misread, so two rules shape the design:

* **Every number is quoted against its sector peers.** A PE of 25 means
  nothing on its own; a PE of 25 against a sector median of 40 means
  something. Peer medians are computed from the Nifty 500 members of the same
  NSE industry, fetched on demand.
* **The output is a bull case, a bear case, and what would break the thesis -
  never a verdict.** A screener cannot know the user's horizon, tax position
  or risk appetite, and a confident "BUY" would be worth less than the
  evidence it was built from.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from statistics import median
from typing import Any, Dict, List, Optional, Sequence

from . import config
from .http import YahooClient
from .universe import Stock

log = logging.getLogger(__name__)

CRORE = 1e7
MODULES = "defaultKeyStatistics,financialData,summaryDetail,summaryProfile"


def _num(node: Any) -> Optional[float]:
    """Yahoo wraps numbers as {"raw": 1.23, "fmt": "1.23"} - or omits them."""
    if isinstance(node, dict):
        raw = node.get("raw")
        return float(raw) if isinstance(raw, (int, float)) else None
    if isinstance(node, (int, float)):
        return float(node)
    return None


def _pct(node: Any) -> Optional[float]:
    """Yahoo returns ratios as fractions; the app displays percentages."""
    v = _num(node)
    return round(v * 100.0, 2) if v is not None else None


@dataclass
class Fundamentals:
    symbol: str
    market_cap_cr: Optional[float] = None
    trailing_pe: Optional[float] = None
    forward_pe: Optional[float] = None
    price_to_book: Optional[float] = None
    roe_pct: Optional[float] = None
    debt_to_equity: Optional[float] = None
    revenue_growth_pct: Optional[float] = None
    earnings_growth_pct: Optional[float] = None
    operating_margin_pct: Optional[float] = None
    profit_margin_pct: Optional[float] = None
    promoter_holding_pct: Optional[float] = None
    institutional_holding_pct: Optional[float] = None
    dividend_yield_pct: Optional[float] = None
    current_ratio: Optional[float] = None
    beta: Optional[float] = None
    target_mean: Optional[float] = None
    target_low: Optional[float] = None
    target_high: Optional[float] = None
    analyst_count: Optional[int] = None
    current_price: Optional[float] = None
    business_summary: str = ""

    @property
    def target_upside_pct(self) -> Optional[float]:
        if self.target_mean and self.current_price:
            return round(((self.target_mean - self.current_price) / self.current_price) * 100, 1)
        return None


def _parse(symbol: str, payload: dict) -> Optional[Fundamentals]:
    try:
        result = (payload.get("quoteSummary") or {}).get("result") or []
        if not result:
            return None
        node = result[0]
    except AttributeError:
        return None

    ks = node.get("defaultKeyStatistics") or {}
    fd = node.get("financialData") or {}
    sd = node.get("summaryDetail") or {}
    sp = node.get("summaryProfile") or {}

    mc = _num(sd.get("marketCap")) or _num(ks.get("enterpriseValue"))
    return Fundamentals(
        symbol=symbol,
        market_cap_cr=round(mc / CRORE, 0) if mc else None,
        trailing_pe=_num(sd.get("trailingPE")),
        forward_pe=_num(ks.get("forwardPE")),
        price_to_book=_num(ks.get("priceToBook")),
        roe_pct=_pct(fd.get("returnOnEquity")),
        debt_to_equity=_num(fd.get("debtToEquity")),
        revenue_growth_pct=_pct(fd.get("revenueGrowth")),
        earnings_growth_pct=_pct(fd.get("earningsGrowth")),
        operating_margin_pct=_pct(fd.get("operatingMargins")),
        profit_margin_pct=_pct(fd.get("profitMargins")),
        promoter_holding_pct=_pct(ks.get("heldPercentInsiders")),
        institutional_holding_pct=_pct(ks.get("heldPercentInstitutions")),
        dividend_yield_pct=_pct(sd.get("dividendYield")),
        current_ratio=_num(fd.get("currentRatio")),
        beta=_num(ks.get("beta")),
        target_mean=_num(fd.get("targetMeanPrice")),
        target_low=_num(fd.get("targetLowPrice")),
        target_high=_num(fd.get("targetHighPrice")),
        analyst_count=int(_num(fd.get("numberOfAnalystOpinions")) or 0) or None,
        current_price=_num(fd.get("currentPrice")),
        business_summary=(sp.get("longBusinessSummary") or "").strip(),
    )


def fetch_one(client: YahooClient, yahoo_symbol: str) -> Optional[Fundamentals]:
    payload = client.get_json(
        config.YAHOO_QUOTESUMMARY.format(symbol=yahoo_symbol),
        params={"modules": MODULES},
        needs_crumb=True,
    )
    if not payload:
        return None
    symbol = yahoo_symbol[:-3] if yahoo_symbol.endswith(".NS") else yahoo_symbol
    return _parse(symbol, payload)


def fetch_many(
    client: YahooClient, yahoo_symbols: Sequence[str], max_workers: int = 6
) -> Dict[str, Fundamentals]:
    out: Dict[str, Fundamentals] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(fetch_one, client, s): s for s in yahoo_symbols}
        for fut in as_completed(futures):
            try:
                f = fut.result()
            except Exception as exc:  # noqa: BLE001
                log.debug("fundamentals failed for %s: %s", futures[fut], exc)
                continue
            if f:
                out[f.symbol] = f
    return out


# --------------------------------------------------------------------------
# Peer benchmarking
# --------------------------------------------------------------------------

#: Below this many peers a median is noise, and the scorecard says so rather
#: than quoting a comparison it cannot support.
MIN_PEERS = 4


@dataclass
class PeerBenchmark:
    industry: str
    peers: int
    trailing_pe: Optional[float] = None
    price_to_book: Optional[float] = None
    roe_pct: Optional[float] = None
    debt_to_equity: Optional[float] = None
    revenue_growth_pct: Optional[float] = None
    profit_margin_pct: Optional[float] = None

    @property
    def is_reliable(self) -> bool:
        return self.peers >= MIN_PEERS


def _median_of(values: List[Optional[float]]) -> Optional[float]:
    clean = [v for v in values if v is not None]
    return round(median(clean), 2) if clean else None


def build_benchmark(industry: str, peer_funds: Dict[str, Fundamentals]) -> PeerBenchmark:
    vals = list(peer_funds.values())
    return PeerBenchmark(
        industry=industry,
        peers=len(vals),
        trailing_pe=_median_of([f.trailing_pe for f in vals]),
        price_to_book=_median_of([f.price_to_book for f in vals]),
        roe_pct=_median_of([f.roe_pct for f in vals]),
        debt_to_equity=_median_of([f.debt_to_equity for f in vals]),
        revenue_growth_pct=_median_of([f.revenue_growth_pct for f in vals]),
        profit_margin_pct=_median_of([f.profit_margin_pct for f in vals]),
    )


# --------------------------------------------------------------------------
# The scorecard
# --------------------------------------------------------------------------


@dataclass
class Factor:
    name: str
    value: str
    peer_value: str
    stance: str      # "bull" | "bear" | "neutral" | "unknown"
    note: str


@dataclass
class Scorecard:
    symbol: str
    factors: List[Factor] = field(default_factory=list)
    bull_case: List[str] = field(default_factory=list)
    bear_case: List[str] = field(default_factory=list)
    invalidators: List[str] = field(default_factory=list)
    data_gaps: List[str] = field(default_factory=list)

    @property
    def bull_count(self) -> int:
        return sum(1 for f in self.factors if f.stance == "bull")

    @property
    def bear_count(self) -> int:
        return sum(1 for f in self.factors if f.stance == "bear")


def _fmt(value: Optional[float], suffix: str = "", dp: int = 1) -> str:
    return f"{value:.{dp}f}{suffix}" if value is not None else "n/a"


def build_scorecard(
    stock: Stock,
    fund: Fundamentals,
    bench: PeerBenchmark,
    pct_from_52w_high: Optional[float],
    return_1y: Optional[float],
) -> Scorecard:
    """Turn raw fundamentals into a peer-relative bull/bear brief."""
    card = Scorecard(symbol=stock.symbol)
    reliable = bench.is_reliable
    if not reliable:
        card.data_gaps.append(
            f"Only {bench.peers} {stock.industry} peers had usable fundamentals, so "
            f"peer medians below are indicative rather than reliable."
        )

    def compare(
        name: str,
        value: Optional[float],
        peer: Optional[float],
        higher_is_better: bool,
        suffix: str = "",
        bull_note: str = "",
        bear_note: str = "",
    ) -> None:
        if value is None:
            card.factors.append(Factor(name, "n/a", _fmt(peer, suffix), "unknown",
                                       "Not reported by the data source."))
            card.data_gaps.append(f"{name} unavailable")
            return
        if peer is None or not reliable:
            card.factors.append(Factor(name, _fmt(value, suffix), "n/a", "neutral",
                                       "No trustworthy peer median to compare against."))
            return
        better = value > peer if higher_is_better else value < peer
        # Within 10% of the peer median is a tie, not an edge.
        if peer and abs(value - peer) / abs(peer) < 0.10:
            stance, note = "neutral", "In line with the sector."
        elif better:
            stance, note = "bull", bull_note
        else:
            stance, note = "bear", bear_note
        card.factors.append(Factor(name, _fmt(value, suffix), _fmt(peer, suffix), stance, note))

    compare("Trailing P/E", fund.trailing_pe, bench.trailing_pe, False,
            bull_note="Cheaper than the typical peer on trailing earnings.",
            bear_note="More expensive than the typical peer, so more of the growth is already priced in.")
    compare("Price / Book", fund.price_to_book, bench.price_to_book, False,
            bull_note="Trades at a lower multiple of book value than peers.",
            bear_note="Trades at a premium to peer book value.")
    compare("Return on Equity", fund.roe_pct, bench.roe_pct, True, "%",
            bull_note="Converts shareholder capital into profit better than peers.",
            bear_note="Earns less on shareholder capital than peers do.")
    compare("Debt / Equity", fund.debt_to_equity, bench.debt_to_equity, False,
            bull_note="Carries less leverage than peers, so less earnings risk if rates rise.",
            bear_note="More leveraged than peers, which amplifies any downturn.")
    compare("Revenue growth (yoy)", fund.revenue_growth_pct, bench.revenue_growth_pct, True, "%",
            bull_note="Growing the top line faster than the sector.",
            bear_note="Growing more slowly than the sector.")
    compare("Net margin", fund.profit_margin_pct, bench.profit_margin_pct, True, "%",
            bull_note="Keeps more of every rupee of revenue than peers.",
            bear_note="Thinner margins than peers.")

    # -- narrative assembly ------------------------------------------------
    for f in card.factors:
        if f.stance == "bull":
            card.bull_case.append(f"{f.name} {f.value} vs sector {f.peer_value}. {f.note}")
        elif f.stance == "bear":
            card.bear_case.append(f"{f.name} {f.value} vs sector {f.peer_value}. {f.note}")

    if fund.earnings_growth_pct is not None:
        if fund.earnings_growth_pct > 15:
            card.bull_case.append(
                f"Earnings grew {fund.earnings_growth_pct:.0f}% year on year, which is what "
                f"has to keep happening for a re-rating to hold."
            )
        elif fund.earnings_growth_pct < 0:
            card.bear_case.append(
                f"Earnings fell {abs(fund.earnings_growth_pct):.0f}% year on year, so the "
                f"price move is running ahead of profits."
            )

    if fund.promoter_holding_pct is not None:
        if fund.promoter_holding_pct >= 50:
            card.bull_case.append(
                f"Promoters hold {fund.promoter_holding_pct:.0f}%, so their interests stay "
                f"tied to the share price."
            )
        elif fund.promoter_holding_pct < 26:
            card.bear_case.append(
                f"Promoter holding is only {fund.promoter_holding_pct:.0f}%, which offers "
                f"little downside alignment and leaves control contestable."
            )

    if fund.target_upside_pct is not None and fund.analyst_count:
        direction = "above" if fund.target_upside_pct > 0 else "below"
        line = (
            f"{fund.analyst_count} analysts publish a mean target of "
            f"{fund.target_mean:.0f}, {abs(fund.target_upside_pct):.0f}% {direction} "
            f"the current price."
        )
        (card.bull_case if fund.target_upside_pct > 0 else card.bear_case).append(line)
        if fund.analyst_count < 5:
            card.data_gaps.append(
                f"Only {fund.analyst_count} analysts cover this name, so the consensus "
                f"target is thin and moves easily."
            )

    if pct_from_52w_high is not None:
        if pct_from_52w_high > -5:
            card.bear_case.append(
                f"Sitting within {abs(pct_from_52w_high):.0f}% of its 52-week high, so "
                f"you are buying after the move, not before it."
            )
        elif pct_from_52w_high < -30:
            card.bull_case.append(
                f"Still {abs(pct_from_52w_high):.0f}% below its 52-week high, leaving "
                f"recovery room if the business itself is intact."
            )

    # -- what would break the thesis ---------------------------------------
    card.invalidators.append(
        "Two consecutive quarters of revenue or margin decline would remove the growth "
        "premise this rests on."
    )
    if fund.debt_to_equity and fund.debt_to_equity > 100:
        card.invalidators.append(
            f"Debt/equity of {fund.debt_to_equity:.0f} means a rate rise or a refinancing "
            f"squeeze hits earnings before it hits peers."
        )
    if return_1y is not None and return_1y > 80:
        card.invalidators.append(
            f"The stock is already up {return_1y:.0f}% over a year; that pace normally "
            f"needs earnings to catch up, or the multiple contracts."
        )
    if fund.trailing_pe and bench.trailing_pe and reliable and fund.trailing_pe > bench.trailing_pe * 1.5:
        card.invalidators.append(
            "Trading at a large premium to the sector - any earnings miss tends to be "
            "punished harder from a premium multiple."
        )
    card.invalidators.append(
        "A promoter pledge increase or a fresh exchange surveillance action would change "
        "the risk profile regardless of the fundamentals."
    )
    return card
