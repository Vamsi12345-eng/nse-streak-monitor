"""Builds the hand-off prompt for a deep dive in the Claude app.

The app deliberately does not call an LLM API. Instead every stock detail
screen carries a fully-populated research prompt that the user drops into the
Claude app on their phone - which is what a Claude subscription is actually
for: interactive use, with a human in the loop.

Because the prompt already carries every number the engine gathered, the
deep dive starts from evidence instead of from a ticker symbol, and does not
depend on the model looking anything up correctly.
"""
from __future__ import annotations

from typing import List, Optional

from .attribution import Attribution
from .fundamentals import Fundamentals, PeerBenchmark, Scorecard
from .screener import Hit


def _line(label: str, value: Optional[object], suffix: str = "") -> Optional[str]:
    if value is None or value == "":
        return None
    return f"- {label}: {value}{suffix}"


def build_research_prompt(
    hit: Hit,
    attribution: Attribution,
    fundamentals: Optional[Fundamentals],
    benchmark: Optional[PeerBenchmark],
    scorecard: Optional[Scorecard],
) -> str:
    """Assemble a self-contained research prompt for one stock."""
    s = hit.stock
    parts: List[str] = []

    parts.append(
        f"I'm a long-term retail investor in Indian equities (NSE). My screener flagged "
        f"{s.name} ({s.symbol}) because it gained at least 3% on each of "
        f"{len(hit.days)} consecutive sessions. I want your independent read - "
        f"please push back on my screener rather than agreeing with it."
    )

    parts.append("\n## What my screener measured\n")
    parts.append(f"- Streak: {hit.start_date} to {hit.end_date}, "
                 f"{hit.cumulative_pct:+.1f}% cumulative")
    parts.append("- Daily gains: " + ", ".join(f"{d.date} {d.gain_pct:+.2f}%" for d in hit.days))
    parts.append(f"- Last close: Rs {hit.last_close:,.2f}")
    parts.append(f"- Sector: {s.industry}")
    for line in [
        _line("Median 20-day turnover", f"Rs {hit.median_turnover_cr:,.1f} crore"),
        _line("Volume vs 20-day median", hit.volume_ratio, "x"),
        _line("Distance from 52-week high", hit.pct_from_52w_high, "%"),
        _line("Return 1M / 3M / 1Y",
              f"{hit.return_1m}% / {hit.return_3m}% / {hit.return_1y}%"),
    ]:
        if line:
            parts.append(line)

    parts.append("\n## Attribution my engine computed\n")
    parts.append(f"- Verdict: {attribution.verdict} - {attribution.headline}")
    parts.append(f"- Stock over the window: {attribution.stock_streak_pct:+.1f}%")
    if attribution.sector_streak_pct is not None:
        parts.append(f"- Sector median over the same window: "
                     f"{attribution.sector_streak_pct:+.1f}%")
        parts.append(f"- Excess vs sector: {attribution.excess_vs_sector_pct:+.1f} pp")
    parts.append(f"- Broad market median: {attribution.market_streak_pct:+.1f}%")

    if attribution.filings:
        parts.append("\n### NSE filings in the window\n")
        for f in attribution.filings:
            parts.append(f"- {f.date} [{f.bucket}] {f.category} - {f.label}")
            if f.summary:
                parts.append(f"  {f.summary[:180]}")
    else:
        parts.append("\n- No NSE corporate filings in the window.")

    if attribution.cautions:
        parts.append("\n### Caution flags my engine raised\n")
        parts.extend(f"- {c}" for c in attribution.cautions)

    if attribution.headlines:
        parts.append("\n### Recent headlines (unverified, from Google News)\n")
        parts.extend(f"- {h.title}" for h in attribution.headlines[:6])

    if fundamentals:
        parts.append("\n## Fundamentals\n")
        f = fundamentals
        for line in [
            _line("Market cap", f"Rs {f.market_cap_cr:,.0f} crore" if f.market_cap_cr else None),
            _line("Trailing P/E", f.trailing_pe),
            _line("Forward P/E", f.forward_pe),
            _line("Price/Book", f.price_to_book),
            _line("Return on equity", f.roe_pct, "%"),
            _line("Debt/Equity", f.debt_to_equity),
            _line("Revenue growth (yoy)", f.revenue_growth_pct, "%"),
            _line("Earnings growth (yoy)", f.earnings_growth_pct, "%"),
            _line("Operating margin", f.operating_margin_pct, "%"),
            _line("Net margin", f.profit_margin_pct, "%"),
            _line("Promoter holding", f.promoter_holding_pct, "%"),
            _line("Institutional holding", f.institutional_holding_pct, "%"),
            _line("Dividend yield", f.dividend_yield_pct, "%"),
            _line("Analyst count", f.analyst_count),
            _line("Mean target price", f.target_mean),
        ]:
            if line:
                parts.append(line)

    if benchmark and benchmark.is_reliable:
        parts.append(f"\n### Sector medians ({benchmark.industry}, "
                     f"{benchmark.peers} Nifty 500 peers)\n")
        for line in [
            _line("Trailing P/E", benchmark.trailing_pe),
            _line("Price/Book", benchmark.price_to_book),
            _line("Return on equity", benchmark.roe_pct, "%"),
            _line("Debt/Equity", benchmark.debt_to_equity),
            _line("Revenue growth", benchmark.revenue_growth_pct, "%"),
            _line("Net margin", benchmark.profit_margin_pct, "%"),
        ]:
            if line:
                parts.append(line)

    if scorecard and scorecard.data_gaps:
        parts.append("\n### Data my engine could not get\n")
        parts.extend(f"- {g}" for g in scorecard.data_gaps)

    parts.append(
        "\n## What I want from you\n\n"
        "1. **Why did it actually move?** My engine only sees exchange filings and "
        "price action. Check whether there is a real catalyst it missed - sector news, "
        "a peer's results, a policy change, an index inclusion, a block deal.\n"
        "2. **Is my engine's attribution wrong?** Say so directly if the evidence "
        "points elsewhere.\n"
        "3. **The one-year view.** Build a bull case and a bear case from the business, "
        "not from the chart. What has to be true for this to work, and what would break "
        "it? Be concrete about which numbers to watch.\n"
        "4. **What would you check that I have not?** Name the specific filings, "
        "segments or metrics.\n\n"
        "Please flag anything above that looks stale or wrong, and tell me plainly if "
        "this looks like a speculative move rather than an investable one. I am not "
        "asking you to tell me whether to buy - I want the reasoning so I can decide."
    )

    return "\n".join(p for p in parts if p is not None)
