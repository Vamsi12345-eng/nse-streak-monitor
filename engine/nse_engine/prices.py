"""Daily OHLCV retrieval and the derived series the screener needs."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Dict, List, Optional, Sequence

from . import config
from .http import YahooClient

log = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

# Yahoo throttles aggressively above roughly a dozen concurrent connections.
# 8 keeps a 500-name scan comfortably under two minutes without tripping 429s.
MAX_WORKERS = 8


@dataclass(frozen=True)
class Bar:
    date: str         # YYYY-MM-DD in IST
    open: float
    high: float
    low: float
    close: float      # raw close, for display
    adj_close: float  # split/dividend adjusted, for return maths
    volume: int


@dataclass
class Series:
    symbol: str
    bars: List[Bar]

    def __len__(self) -> int:
        return len(self.bars)

    @property
    def closes(self) -> List[float]:
        # Adjusted, so a 1:2 bonus issue does not read as a 50% crash.
        return [b.adj_close for b in self.bars]

    def returns_pct(self) -> List[float]:
        """Close-to-close percentage change, aligned to ``bars[1:]``."""
        c = self.closes
        out: List[float] = []
        for prev, cur in zip(c, c[1:]):
            out.append(((cur - prev) / prev) * 100.0 if prev else 0.0)
        return out

    def median_turnover_cr(self, window: int = 20) -> float:
        """Median daily traded value over ``window`` sessions, in INR crore.

        Median rather than mean, so a single block deal cannot make an
        otherwise illiquid counter look tradable.
        """
        recent = self.bars[-window:]
        if not recent:
            return 0.0
        values = [b.close * b.volume / 1e7 for b in recent]  # 1 crore = 1e7
        return float(median(values))

    def volume_ratio(self, window: int = 20) -> Optional[float]:
        """Latest session volume divided by the prior ``window``-day median."""
        if len(self.bars) < window + 1:
            return None
        prior = [b.volume for b in self.bars[-window - 1:-1]]
        base = median(prior)
        if not base:
            return None
        return self.bars[-1].volume / base

    def pct_from_52w_high(self) -> Optional[float]:
        window = self.bars[-252:]
        if not window:
            return None
        high = max(b.adj_close for b in window)
        return ((self.bars[-1].adj_close - high) / high) * 100.0 if high else None

    def return_over(self, sessions: int) -> Optional[float]:
        """Total percentage return across the last ``sessions`` sessions."""
        if len(self.bars) <= sessions:
            return None
        start = self.bars[-sessions - 1].adj_close
        end = self.bars[-1].adj_close
        return ((end - start) / start) * 100.0 if start else None


def _parse_chart(symbol: str, payload: dict) -> Optional[Series]:
    try:
        result = (payload.get("chart") or {}).get("result") or []
        if not result:
            return None
        node = result[0]
        stamps: Sequence[int] = node.get("timestamp") or []
        indicators = node.get("indicators") or {}
        quote = (indicators.get("quote") or [{}])[0]
        adj_list = indicators.get("adjclose") or []
        adj = adj_list[0].get("adjclose") if adj_list else None

        opens, highs = quote.get("open") or [], quote.get("high") or []
        lows, closes = quote.get("low") or [], quote.get("close") or []
        vols = quote.get("volume") or []
    except (AttributeError, IndexError, TypeError):
        return None

    bars: List[Bar] = []
    for i, ts in enumerate(stamps):
        def at(seq, idx=i):
            return seq[idx] if idx < len(seq) else None

        o, h, l, c, v = at(opens), at(highs), at(lows), at(closes), at(vols)
        # Holidays and trading halts come back as nulls interleaved with real
        # sessions. Dropping them keeps the consecutive-day logic honest.
        if None in (o, h, l, c):
            continue
        a = at(adj) if adj else None
        bars.append(
            Bar(
                date=datetime.fromtimestamp(ts, IST).strftime("%Y-%m-%d"),
                open=float(o),
                high=float(h),
                low=float(l),
                close=float(c),
                adj_close=float(a) if a is not None else float(c),
                volume=int(v or 0),
            )
        )
    return Series(symbol=symbol, bars=bars) if bars else None


def fetch_series(client: YahooClient, yahoo_symbol: str, days: int) -> Optional[Series]:
    """Fetch daily bars for one Yahoo ticker."""
    rng = "1y" if days > 180 else ("6mo" if days > 90 else "3mo")
    payload = client.get_json(
        config.YAHOO_CHART.format(symbol=yahoo_symbol),
        params={"range": rng, "interval": "1d", "events": "div,split"},
    )
    if not payload:
        return None
    return _parse_chart(yahoo_symbol, payload)


def fetch_many(
    client: YahooClient,
    yahoo_symbols: Sequence[str],
    days: int,
    max_workers: int = MAX_WORKERS,
) -> Dict[str, Series]:
    """Fetch many tickers concurrently. Failures are logged and skipped."""
    out: Dict[str, Series] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(fetch_series, client, sym, days): sym for sym in yahoo_symbols
        }
        for fut in as_completed(futures):
            sym = futures[fut]
            try:
                series = fut.result()
            except Exception as exc:  # noqa: BLE001 - one bad symbol must not abort a 500-name scan
                log.debug("fetch failed for %s: %s", sym, exc)
                continue
            if series:
                out[sym] = series
    missing = len(yahoo_symbols) - len(out)
    if missing:
        log.info("price fetch: %d/%d ok, %d missing", len(out), len(yahoo_symbols), missing)
    return out
