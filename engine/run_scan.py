#!/usr/bin/env python3
"""CLI entry point for the NSE streak scanner.

    python run_scan.py                       # scan, print a report
    python run_scan.py --json out/scan.json  # also write the app's data file
    python run_scan.py --gain 2 --days 4     # different streak definition
    python run_scan.py --symbol NSLNISP      # explain one stock, ignore the screen
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

from nse_engine.config import ScreenConfig
from nse_engine.pipeline import run_scan

# Windows terminals default to cp1252, which cannot encode the rupee sign that
# arrives in news headlines. Without this the whole run dies on a print().
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

RULE = "=" * 78


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Scan the Nifty 500 for consecutive-gain streaks.")
    p.add_argument("--gain", type=float, default=3.0, help="minimum daily gain %% (default 3)")
    p.add_argument("--days", type=int, default=3, help="consecutive sessions required (default 3)")
    p.add_argument("--min-turnover", type=float, default=5.0,
                   help="minimum median 20-day turnover in INR crore (default 5)")
    p.add_argument("--watchlist", type=str, default="",
                   help="comma-separated extra symbols to always include")
    p.add_argument("--json", type=str, default="", help="write the result document here")
    p.add_argument("--state", type=str, default="",
                   help="notification state file, for suppressing repeats")
    p.add_argument("--no-enrich", action="store_true",
                   help="skip filings/fundamentals (fast, screen only)")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args()


def _new_alerts(result: Dict[str, Any], state_path: str) -> List[Dict[str, Any]]:
    """Hits not already notified.

    Keyed by symbol + streak end date, so an ongoing streak that extends to a
    new session legitimately alerts again, while a re-run on the same data
    stays quiet.
    """
    if not state_path:
        return result["hits"]
    path = Path(state_path)
    seen = set()
    if path.exists():
        try:
            seen = set(json.loads(path.read_text(encoding="utf-8")).get("notified", []))
        except (json.JSONDecodeError, OSError):
            seen = set()

    fresh, keys = [], set(seen)
    for hit in result["hits"]:
        key = f"{hit['symbol']}@{hit['end_date']}"
        if key not in seen:
            fresh.append(hit)
        keys.add(key)

    path.parent.mkdir(parents=True, exist_ok=True)
    # Keep the tail bounded so the state file cannot grow without limit.
    path.write_text(
        json.dumps({"notified": sorted(keys)[-4000:]}, indent=2), encoding="utf-8"
    )
    return fresh


def _print_report(result: Dict[str, Any], fresh: List[Dict[str, Any]]) -> None:
    m = result["market"]
    print(RULE)
    print(f"NSE STREAK SCAN   session {result['session']}   generated {result['generated_at']}")
    cfg = result["config"]
    print(f"Rule: >= {cfg['daily_gain_pct']}% on each of {cfg['streak_days']} consecutive sessions")
    print(f"Market: median {m['median_day_pct']:+.2f}% on the day, "
          f"{m['breadth_pct']:.0f}% of {m['names']} names advancing")
    print(RULE)

    hits = result["hits"]
    if not hits:
        print("\nNo stocks matched. Sector medians for the session:\n")
        for s in result["sectors"][:6]:
            print(f"   {s['industry']:34s} {s['median_day_pct']:+6.2f}%  "
                  f"breadth {s['breadth_pct']:3.0f}%")
        print(f"   ... and {max(len(result['sectors']) - 6, 0)} more sectors")
        return

    fresh_keys = {f"{h['symbol']}@{h['end_date']}" for h in fresh}
    print(f"\n{len(hits)} match(es), {len(fresh)} not previously alerted\n")

    for h in hits:
        is_new = f"{h['symbol']}@{h['end_date']}" in fresh_keys
        flag = " *NEW*" if is_new else ""
        stale = "" if h.get("is_current", True) else "  [feed lagging one session]"
        print(RULE)
        print(f"{h['name']} ({h['symbol']}){flag}{stale}")
        print(f"  {h['cumulative_pct']:+.1f}% over {len(h['days'])} sessions "
              f"({h['start_date']} to {h['end_date']}), last close Rs {h['last_close']:,.2f}")
        print("  Daily: " + ", ".join(f"{d['gain_pct']:+.2f}%" for d in h["days"]))
        print(f"  Sector: {h['industry']}   Turnover: Rs {h['median_turnover_cr']:,.1f} cr"
              f"   Volume: {h.get('volume_ratio') or '?'}x normal")

        a = h.get("attribution")
        if a:
            print(f"\n  WHY -- {a['headline']}")
            for line in a["explanation"]:
                print(f"    - {line}")
            if a["cautions"]:
                print("\n  CAUTION:")
                for c in a["cautions"]:
                    print(f"    ! {c}")

        sc = h.get("scorecard")
        if sc:
            print(f"\n  ONE-YEAR VIEW ({sc['bull_count']} bull / {sc['bear_count']} bear factors)")
            for b in sc["bull_case"][:4]:
                print(f"    + {b}")
            for b in sc["bear_case"][:4]:
                print(f"    - {b}")
            if sc["invalidators"]:
                print("    Would invalidate the thesis:")
                for iv in sc["invalidators"][:3]:
                    print(f"      ! {iv}")
        print()

    print(RULE)
    print("Not investment advice. Evidence for your own judgement -- verify every "
          "filing before acting.")
    print(RULE)


def main() -> int:
    args = _parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    cfg = ScreenConfig(
        daily_gain_pct=args.gain,
        streak_days=args.days,
        min_median_turnover_cr=args.min_turnover,
    )
    watchlist = [s for s in args.watchlist.split(",") if s.strip()]

    try:
        result = run_scan(cfg, watchlist=watchlist, enrich=not args.no_enrich)
    except RuntimeError as exc:
        print(f"scan failed: {exc}", file=sys.stderr)
        return 1

    fresh = _new_alerts(result, args.state)
    result["new_alerts"] = [f"{h['symbol']}@{h['end_date']}" for h in fresh]

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"wrote {out} ({out.stat().st_size:,} bytes)\n")

    _print_report(result, fresh)

    # Surfaced for the GitHub Actions step that decides whether to notify.
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as fh:
            fh.write(f"hit_count={len(result['hits'])}\n")
            fh.write(f"new_count={len(fresh)}\n")
            fh.write(f"session={result['session']}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
