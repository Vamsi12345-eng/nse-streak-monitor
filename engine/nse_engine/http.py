"""Shared HTTP plumbing.

Two providers need special handling:

* **Yahoo** rotates a ``crumb`` token that must accompany every quoteSummary
  call, and it is bound to the cookies issued alongside it. The chart endpoint
  does not need it. We fetch the pair lazily and refresh once on a 401.
* **NSE** rejects any request that has not first been "warmed up" against the
  homepage. The warmup itself frequently returns 403 while still setting the
  cookies we need, so its status code is deliberately ignored.
"""
from __future__ import annotations

import logging
import random
import threading
import time
from typing import Any, Dict, Optional

import requests

from . import config

log = logging.getLogger(__name__)

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

DEFAULT_TIMEOUT = 25
MAX_ATTEMPTS = 4


class TransientHTTPError(RuntimeError):
    """Raised when a request failed in a way that is worth retrying."""


def _sleep_backoff(attempt: int) -> None:
    """Exponential backoff with jitter, so parallel workers desynchronise."""
    time.sleep(min(2 ** attempt * 0.4, 8.0) + random.uniform(0, 0.4))


class YahooClient:
    """Thread-safe Yahoo Finance client with lazy crumb acquisition."""

    def __init__(self) -> None:
        self._session = requests.Session()
        # Deliberately browser-shaped, not API-shaped. Sending
        # "Accept: application/json" makes the crumb endpoint answer 406, which
        # then fails every quoteSummary call downstream - and the chart
        # endpoint keeps working, so the breakage looks like missing
        # fundamentals rather than an auth problem. This header set also seeds
        # three cookies instead of one.
        self._session.headers.update(
            {
                "User-Agent": BROWSER_UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
        self._crumb: Optional[str] = None
        self._lock = threading.Lock()

    # -- crumb ------------------------------------------------------------
    def _acquire_crumb(self, force: bool = False) -> Optional[str]:
        with self._lock:
            if self._crumb and not force:
                return self._crumb
            try:
                # Seeds the A1/A3 cookies. Returns 404 by design - we only
                # care about the Set-Cookie headers that ride along with it.
                self._session.get(config.YAHOO_COOKIE_SEED, timeout=DEFAULT_TIMEOUT)
                resp = self._session.get(config.YAHOO_CRUMB, timeout=DEFAULT_TIMEOUT)
                crumb = resp.text.strip()
                # A valid crumb is a short opaque token; an HTML error page is not.
                if resp.ok and crumb and "<" not in crumb and len(crumb) < 32:
                    self._crumb = crumb
                    log.debug("acquired yahoo crumb")
                else:
                    self._crumb = None
                    log.warning("could not acquire yahoo crumb (status=%s)", resp.status_code)
            except requests.RequestException as exc:
                self._crumb = None
                log.warning("crumb acquisition failed: %s", exc)
            return self._crumb

    # -- requests ---------------------------------------------------------
    def get_json(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        needs_crumb: bool = False,
    ) -> Optional[dict]:
        """GET a JSON document, retrying transient failures.

        Returns ``None`` when the resource is genuinely unavailable (404, or a
        payload the endpoint refuses to serve) rather than raising, because a
        single delisted or renamed symbol should never abort a 500-name scan.
        """
        params = dict(params or {})
        for attempt in range(MAX_ATTEMPTS):
            if needs_crumb:
                crumb = self._acquire_crumb(force=attempt > 0)
                if not crumb:
                    return None
                params["crumb"] = crumb
            try:
                resp = self._session.get(url, params=params, timeout=DEFAULT_TIMEOUT)
            except requests.RequestException as exc:
                log.debug("network error on %s: %s", url, exc)
                _sleep_backoff(attempt)
                continue

            if resp.status_code == 200:
                try:
                    return resp.json()
                except ValueError:
                    log.debug("non-JSON body from %s", url)
                    return None
            if resp.status_code in (401, 403) and needs_crumb:
                # Stale crumb: force a refresh on the next attempt.
                self._crumb = None
                _sleep_backoff(attempt)
                continue
            if resp.status_code == 404:
                return None
            if resp.status_code in (429, 500, 502, 503, 504):
                _sleep_backoff(attempt)
                continue
            log.debug("unexpected status %s from %s", resp.status_code, url)
            return None
        return None

    def get_text(self, url: str, params: Optional[Dict[str, Any]] = None) -> Optional[str]:
        for attempt in range(MAX_ATTEMPTS):
            try:
                resp = self._session.get(url, params=params, timeout=DEFAULT_TIMEOUT)
                if resp.status_code == 200:
                    return resp.text
                if resp.status_code == 404:
                    return None
            except requests.RequestException:
                pass
            _sleep_backoff(attempt)
        return None


class NSEClient:
    """NSE client that keeps a warmed-up cookie jar alive."""

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": BROWSER_UA,
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
            }
        )
        self._warm = False
        self._lock = threading.Lock()

    def _warmup(self, force: bool = False) -> None:
        with self._lock:
            if self._warm and not force:
                return
            try:
                # Status is ignored on purpose: NSE commonly answers 403 here
                # while still handing back the cookies the API endpoints want.
                self._session.get(config.NSE_HOME, timeout=DEFAULT_TIMEOUT)
                self._warm = True
            except requests.RequestException as exc:
                log.warning("NSE warmup failed: %s", exc)
                self._warm = False

    def get_json(self, url: str, params: Optional[Dict[str, Any]] = None) -> Optional[Any]:
        for attempt in range(MAX_ATTEMPTS):
            self._warmup(force=attempt > 0)
            try:
                resp = self._session.get(url, params=params, timeout=DEFAULT_TIMEOUT)
            except requests.RequestException:
                _sleep_backoff(attempt)
                continue
            if resp.status_code == 200:
                try:
                    return resp.json()
                except ValueError:
                    return None
            if resp.status_code in (401, 403):
                self._warm = False
            _sleep_backoff(attempt)
        return None

    def get_text(self, url: str) -> Optional[str]:
        for attempt in range(MAX_ATTEMPTS):
            self._warmup(force=attempt > 0)
            try:
                resp = self._session.get(url, timeout=DEFAULT_TIMEOUT)
                if resp.status_code == 200:
                    return resp.text
            except requests.RequestException:
                pass
            _sleep_backoff(attempt)
        return None
