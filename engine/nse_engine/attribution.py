"""The "why did it move" engine.

Deterministic attribution built from evidence, not prose. Three questions, in
descending order of how much they explain:

1. Did the whole *market* move? (breadth + median move across all names)
2. Did the whole *sector* move? (median move across industry peers)
3. Did the *company* disclose something? (NSE corporate filings on those dates)

Whatever is left over after 1 and 2 is the stock-specific excess. Only that
excess needs a company-specific explanation, and only then do the filings
matter. Getting this order right is what separates a real answer from
"here are some headlines, you figure it out".
"""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

from . import config
from .http import NSEClient, YahooClient
from .screener import Hit
from .sector import MarketContext

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Filing taxonomy
# --------------------------------------------------------------------------
# NSE's `desc` field is a controlled vocabulary, which makes keyword matching
# far more reliable here than it would be on free text.
#
# The three buckets exist because they mean opposite things to a long-term
# investor. Treating every filing as "news that explains the rise" would turn
# an exchange surveillance warning into an apparent buy signal.

CATALYST_PATTERNS: List[Tuple[str, str]] = [
    (r"\border\b|\bcontract\b|\bwin\b|\bbagg?ed\b|letter of (award|intent)|\bLoA\b",
     "Order or contract win"),
    (r"financial result|\bearnings\b|quarterly result|audited result",
     "Results announcement"),
    (r"credit rating", "Credit rating action"),
    (r"\bacquisition\b|\bacquire\b|\bmerger\b|amalgamation|\bstake\b|joint venture|\bJV\b",
     "M&A or stake transaction"),
    (r"capacity|expansion|commission|new plant|greenfield|brownfield",
     "Capacity or expansion update"),
    (r"\bdividend\b|\bbonus\b|stock split|\bbuyback\b", "Shareholder return action"),
    (r"fund ?rais|preferential|\bQIP\b|allotment|debenture|\bNCD\b",
     "Fundraising or allotment"),
    (r"\bapproval\b|\blicence\b|\blicense\b|regulatory clearance|\bUSFDA\b|\bCDSCO\b",
     "Regulatory approval"),
    (r"investor present|analyst.*meet|earnings call|con\. ?call",
     "Investor communication"),
]

CAUTION_PATTERNS: List[Tuple[str, str]] = [
    (r"spurt in volume|spurt in price|price movement|unusual",
     "Exchange surveillance query on unusual price or volume"),
    (r"\bASM\b|\bGSM\b|additional surveillance|graded surveillance",
     "Placed under exchange surveillance framework"),
    (r"price band", "Price band revised by the exchange"),
    (r"\bpledge\b|encumbr", "Promoter share pledge or encumbrance"),
    (r"\binsolvency\b|\bNCLT\b|\bIBC\b|winding up|\bdefault\b|\bdelay\b in payment",
     "Insolvency, default or payment delay"),
    (r"\bresignation\b|\bcessation\b.*(director|officer|CFO|CEO|auditor)|auditor resign",
     "Senior management or auditor departure"),
    (r"\bsearch\b|\braid\b|\bsummons\b|show cause|penalt|\bfine\b|adjudicat",
     "Regulatory action or penalty"),
]

NEUTRAL_HINT = "Routine or administrative disclosure"


@dataclass
class Filing:
    date: str            # YYYY-MM-DD
    time: str            # HH:MM
    category: str        # NSE's own `desc` value
    summary: str         # NSE's `attchmntText`
    pdf_url: str
    bucket: str          # "catalyst" | "caution" | "neutral"
    label: str           # human-readable classification

    @property
    def is_catalyst(self) -> bool:
        return self.bucket == "catalyst"

    @property
    def is_caution(self) -> bool:
        return self.bucket == "caution"


@dataclass
class Headline:
    title: str
    source: str
    published: str
    url: str


@dataclass
class Attribution:
    """The structured answer to 'why did this move?'."""

    verdict: str                 # short machine-readable code
    headline: str                # one-line human summary
    explanation: List[str]       # ordered evidence bullets
    stock_streak_pct: float
    sector_streak_pct: Optional[float]
    market_streak_pct: float
    excess_vs_sector_pct: Optional[float]
    sector_breadth_pct: Optional[float]
    volume_ratio: Optional[float]
    filings: List[Filing] = field(default_factory=list)
    headlines: List[Headline] = field(default_factory=list)
    cautions: List[str] = field(default_factory=list)

    @property
    def catalysts(self) -> List[Filing]:
        return [f for f in self.filings if f.is_catalyst]


# --------------------------------------------------------------------------
# Filing retrieval and classification
# --------------------------------------------------------------------------

def _classify(text: str) -> Tuple[str, str]:
    """Bucket a filing from its description and summary text."""
    blob = text.lower()
    # Caution is checked first: a surveillance notice about a stock that also
    # announced an order win is still, first and foremost, a warning.
    for pattern, label in CAUTION_PATTERNS:
        if re.search(pattern, blob, re.IGNORECASE):
            return "caution", label
    for pattern, label in CATALYST_PATTERNS:
        if re.search(pattern, blob, re.IGNORECASE):
            return "catalyst", label
    return "neutral", NEUTRAL_HINT


def _parse_nse_datetime(raw: str) -> Tuple[str, str]:
    """NSE returns '28-Aug-2026 08:47:55'. Split into ISO date and HH:MM."""
    try:
        dt = datetime.strptime(raw.strip(), "%d-%b-%Y %H:%M:%S")
        return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")
    except (ValueError, AttributeError):
        return raw[:11], ""


def fetch_filings(
    client: NSEClient,
    symbol: str,
    start: str,
    end: str,
    lookback_days: int = 4,
) -> List[Filing]:
    """Corporate filings around a streak window.

    The window is padded backwards because a disclosure made after Friday's
    close is what moves Monday's price - the filing that explains a move often
    predates the first qualifying session.
    """
    try:
        d_start = date.fromisoformat(start) - timedelta(days=lookback_days)
        d_end = date.fromisoformat(end) + timedelta(days=1)
    except ValueError:
        return []

    payload = client.get_json(
        config.NSE_ANNOUNCEMENTS,
        params={
            "index": "equities",
            "symbol": symbol,
            "from_date": d_start.strftime("%d-%m-%Y"),
            "to_date": d_end.strftime("%d-%m-%Y"),
        },
    )
    if not isinstance(payload, list):
        return []

    filings: List[Filing] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        desc = (row.get("desc") or "").strip()
        summary = (row.get("attchmntText") or "").strip()
        iso_date, hhmm = _parse_nse_datetime(row.get("an_dt") or "")
        bucket, label = _classify(f"{desc} {summary}")
        filings.append(
            Filing(
                date=iso_date,
                time=hhmm,
                category=desc,
                summary=summary,
                pdf_url=(row.get("attchmntFile") or "").strip(),
                bucket=bucket,
                label=label,
            )
        )
    filings.sort(key=lambda f: (f.date, f.time), reverse=True)
    return filings


# --------------------------------------------------------------------------
# News headlines (secondary evidence)
# --------------------------------------------------------------------------

def fetch_headlines(
    client: YahooClient, company: str, symbol: str, limit: int = 6
) -> List[Headline]:
    """Google News RSS for the company.

    Deliberately secondary to filings: headlines are noisy, frequently
    syndicated duplicates, and often SEO pages that merely restate the price
    move we already measured. Useful colour, never the primary evidence.
    """
    query = f'"{company}" OR "{symbol}" share price NSE'
    xml_text = client.get_text(
        config.GOOGLE_NEWS_RSS,
        params={"q": query, "hl": "en-IN", "gl": "IN", "ceid": "IN:en"},
    )
    if not xml_text:
        return []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    out: List[Headline] = []
    for item in root.iterfind(".//item"):
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        source_el = item.find("source")
        out.append(
            Headline(
                title=title,
                source=(source_el.text or "").strip() if source_el is not None else "",
                published=(item.findtext("pubDate") or "").strip(),
                url=(item.findtext("link") or "").strip(),
            )
        )
        if len(out) >= limit:
            break
    return out


# --------------------------------------------------------------------------
# The verdict
# --------------------------------------------------------------------------

#: A sector needs to have moved at least this much over the streak window
#: before "the sector carried it" is a credible explanation.
SECTOR_MOVE_FLOOR = 2.0
#: Excess above the sector below which the move is essentially the sector's.
SECTOR_EXPLAINS_BAND = 2.0
#: Breadth above which a sector move looks genuinely broad rather than driven
#: by a couple of members.
BROAD_BREADTH = 60.0


def explain(
    hit: Hit,
    context: MarketContext,
    filings: List[Filing],
    headlines: List[Headline],
) -> Attribution:
    """Combine the evidence into a ranked explanation."""
    sector = context.sector_for(hit.stock.industry)
    stock_move = hit.cumulative_pct
    sector_move = sector.median_streak_return_pct if sector else None
    market_move = context.market.median_streak_return_pct
    excess = round(stock_move - sector_move, 2) if sector_move is not None else None
    breadth = sector.breadth_pct if sector else None

    catalysts = [f for f in filings if f.is_catalyst]
    cautions = [f for f in filings if f.is_caution]
    bullets: List[str] = []

    # 1. Market and sector framing always comes first.
    falling = stock_move < 0
    window_desc = (
        f"the session {hit.end_date}" if len(hit.days) == 1
        else f"the {len(hit.days)} sessions {hit.start_date} to {hit.end_date}"
    )
    bullets.append(
        f"The stock {'fell' if falling else 'gained'} {stock_move:+.1f}% over {window_desc}."
    )
    if sector_move is not None and sector is not None:
        bullets.append(
            f"Its sector ({hit.stock.industry}) moved {sector_move:+.1f}% over the same "
            f"window, with {breadth:.0f}% of its {sector.members} Nifty 500 members "
            f"advancing on the last session."
        )
    else:
        bullets.append(
            f"No reliable sector benchmark: {hit.stock.industry} has too few Nifty 500 "
            f"members to produce a trustworthy median."
        )
    bullets.append(
        f"The broad market (median of {context.market.members} Nifty 500 names) moved "
        f"{market_move:+.1f}% over the window, with {context.market.breadth_pct:.0f}% "
        f"advancing on the last session."
    )

    # 2. Decide what actually drove it.
    # Symmetric in direction. A stock down 8% whose sector fell 7% has been
    # carried by the sector just as surely as one up 8% in a sector up 7%, so
    # every test below compares magnitudes and requires the sector to have moved
    # the same way. Breadth flips too: a broad sell-off shows *few* advancers.
    same_direction = sector_move is not None and (sector_move < 0) == falling
    breadth_confirms = (
        (breadth is not None) and
        ((100.0 - breadth) >= BROAD_BREADTH if falling else breadth >= BROAD_BREADTH)
    )
    sector_carried = (
        sector_move is not None
        and same_direction
        and abs(sector_move) >= SECTOR_MOVE_FLOOR
        and excess is not None
        and abs(excess) <= SECTOR_EXPLAINS_BAND
        and breadth_confirms
    )

    if sector_carried:
        verdict = "sector_wide"
        moved = "sold off" if falling else "rallied"
        headline_txt = f"Sector-wide move - {hit.stock.industry} {moved} as a group"
        bullets.append(
            f"Because the sector moved {sector_move:+.1f}% and this stock differed by only "
            f"{excess:+.1f}pp, the move is best read as sector-wide rather than anything "
            f"specific to the company."
        )
    elif catalysts:
        verdict = "company_catalyst"
        top = catalysts[0]
        headline_txt = f"Company-specific - {top.label.lower()} disclosed to the exchange"
        if excess is not None:
            verb = "lagged" if excess < 0 else "outpaced"
            bullets.append(
                f"The stock {verb} its sector by {abs(excess):.1f} percentage points, so "
                f"the move is company-specific rather than sector-wide."
            )
        for f in catalysts[:3]:
            bullets.append(
                f"NSE filing {f.date}{' ' + f.time if f.time else ''} - {f.label}: "
                f"{f.category}."
            )
    else:
        verdict = "unexplained"
        headline_txt = "Company-specific, but nothing disclosed to explain it"
        # No wording change needed for direction: the bullets carry it.
        if excess is not None:
            verb = "lagged" if excess < 0 else "outpaced"
            bullets.append(
                f"The stock {verb} its sector by {abs(excess):.1f} percentage points, yet "
                f"filed no disclosure in the window that would account for it."
            )
        bullets.append(
            "An unexplained move away from the sector is worth more caution, not less - "
            "it can reflect speculation, a leaked development, or an operator-driven move."
        )

    # 3. Volume corroboration.
    if hit.volume_ratio:
        if hit.volume_ratio >= 3:
            bullets.append(
                f"Volume ran {hit.volume_ratio:.1f}x its 20-day median, so real "
                f"institutional-scale money participated rather than thin-book drift."
            )
        elif hit.volume_ratio < 1.2:
            bullets.append(
                f"Volume was only {hit.volume_ratio:.1f}x its 20-day median - a large "
                f"price move on unremarkable volume is easier to reverse."
            )

    # 4. Cautions are surfaced last so they are the final thing read.
    caution_msgs = [f"{c.label} (filed {c.date})" for c in cautions]
    if hit.median_turnover_cr < 25:
        caution_msgs.append(
            f"Thin liquidity - median daily turnover is only Rs {hit.median_turnover_cr:.0f} crore"
        )

    return Attribution(
        verdict=verdict,
        headline=headline_txt,
        explanation=bullets,
        stock_streak_pct=stock_move,
        sector_streak_pct=sector_move,
        market_streak_pct=market_move,
        excess_vs_sector_pct=excess,
        sector_breadth_pct=round(breadth, 0) if breadth is not None else None,
        volume_ratio=hit.volume_ratio,
        filings=filings,
        headlines=headlines,
        cautions=caution_msgs,
    )
