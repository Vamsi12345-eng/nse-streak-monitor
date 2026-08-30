"""Loads the tradable universe (Nifty 500) with its NSE industry labels."""
from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
from typing import List, Optional

from . import config
from .http import NSEClient

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Stock:
    symbol: str          # NSE symbol, e.g. "RELIANCE"
    name: str            # "Reliance Industries Ltd."
    industry: str        # NSE industry label, e.g. "Oil Gas & Consumable Fuels"
    isin: str

    @property
    def yahoo(self) -> str:
        """Yahoo ticker for the NSE listing."""
        return f"{self.symbol}.NS"


def _parse_nifty500(text: str) -> List[Stock]:
    # NSE ships these CSVs with a BOM, which would otherwise become part of the
    # first column name and break the header lookup.
    reader = csv.DictReader(io.StringIO(text))
    stocks: List[Stock] = []
    for row in reader:
        clean = {(k or "").strip().lstrip("﻿"): (v or "").strip() for k, v in row.items()}
        symbol = clean.get("Symbol", "")
        if not symbol:
            continue
        stocks.append(
            Stock(
                symbol=symbol,
                name=clean.get("Company Name", symbol),
                industry=clean.get("Industry", "Diversified"),
                isin=clean.get("ISIN Code", ""),
            )
        )
    return stocks


def load_universe(
    client: Optional[NSEClient] = None,
    extra_symbols: Optional[List[str]] = None,
) -> List[Stock]:
    """Fetch the Nifty 500 constituents.

    ``extra_symbols`` appends personal watchlist names that fall outside the
    index; they get a "Diversified" industry, which maps to the broad-market
    index for attribution.
    """
    client = client or NSEClient()
    text = client.get_text(config.NIFTY500_CSV)
    if not text:
        raise RuntimeError("could not download the Nifty 500 constituent list")

    stocks = _parse_nifty500(text)
    if len(stocks) < 400:
        raise RuntimeError(f"Nifty 500 list looks truncated ({len(stocks)} rows)")

    known = {s.symbol for s in stocks}
    for sym in extra_symbols or []:
        sym = sym.strip().upper()
        if sym and sym not in known:
            stocks.append(Stock(symbol=sym, name=sym, industry="Diversified", isin=""))
            known.add(sym)

    log.info("universe: %d symbols", len(stocks))
    return stocks
