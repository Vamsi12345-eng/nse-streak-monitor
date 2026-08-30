#!/usr/bin/env python3
"""Measures the physical work one app refresh performs.

Battery drain itself cannot be measured off-device - an emulator models
neither the cellular radio nor Doze nor One UI's power manager. What *can* be
measured anywhere is the work that causes the drain: bytes moved, requests
made, CPU spent parsing, and how often the app wakes. Those feed a power model
to give an honest estimate, which the on-device `dumpsys batterystats` run
later either confirms or corrects.
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# --------------------------------------------------------------------------
# Android power model constants.
#
# These are order-of-magnitude figures for a modern flagship (S24 Ultra class,
# Snapdragon 8 Gen 3, 5000 mAh). They are used only to show that the app's
# consumption is negligible by a wide margin - the conclusion holds even if
# each figure is off by 3-5x, which is the point of stating them explicitly.
# --------------------------------------------------------------------------
BATTERY_MAH = 5000
BATTERY_MWH = BATTERY_MAH * 3.85          # nominal cell voltage
WIFI_TRANSFER_MW = 350                     # active wifi transfer
RADIO_TAIL_S = 6                           # radio stays awake after a transfer
CPU_ACTIVE_MW = 900                        # one big core busy
WAKE_OVERHEAD_S = 0.4                      # scheduler + process warmup


def measure(scan_path: Path, iterations: int = 200) -> dict:
    raw = scan_path.read_bytes()
    size = len(raw)
    text = raw.decode("utf-8")

    # Parse cost. Python's json is a reasonable proxy for kotlinx.serialization
    # on a phone: both are optimised native-ish parsers, and the phone's big
    # core is comparable to this laptop's. Good to a factor of ~2, which is
    # ample for the conclusion.
    timings = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        json.loads(text)
        timings.append(time.perf_counter() - t0)
    parse_ms = statistics.median(timings) * 1000

    doc = json.loads(text)
    return {
        "bytes": size,
        "kb": size / 1024,
        "parse_ms": parse_ms,
        "hits": len(doc.get("hits", [])),
        "universe": doc.get("stats", {}).get("universe", 0),
    }


def energy_per_refresh(m: dict) -> dict:
    """Energy for one poll: transfer + radio tail + parse + wake overhead."""
    # Assume a pessimistic 1 Mbps effective throughput so transfer time is
    # dominated by latency rather than bandwidth - the realistic case for a
    # small file.
    transfer_s = max(m["bytes"] * 8 / 1_000_000, 0.25)
    radio_s = transfer_s + RADIO_TAIL_S
    cpu_s = m["parse_ms"] / 1000 + WAKE_OVERHEAD_S

    radio_mwh = WIFI_TRANSFER_MW * radio_s / 3600
    cpu_mwh = CPU_ACTIVE_MW * cpu_s / 3600
    total = radio_mwh + cpu_mwh
    return {
        "radio_s": radio_s,
        "cpu_s": cpu_s,
        "radio_mwh": radio_mwh,
        "cpu_mwh": cpu_mwh,
        "total_mwh": total,
        "pct_of_battery": total / BATTERY_MWH * 100,
    }


def main() -> int:
    scan = Path(__file__).resolve().parents[1] / "engine" / "out" / "scan.json"
    if not scan.exists():
        print(f"No scan at {scan}. Run: cd engine && python run_scan.py --json out/scan.json")
        return 1

    m = measure(scan)
    e = energy_per_refresh(m)

    print("=" * 68)
    print("APP RESOURCE COST  (measured, not guessed)")
    print("=" * 68)
    print(f"  Feed payload             {m['kb']:.1f} KB  ({m['bytes']:,} bytes)")
    print(f"  Hits carried             {m['hits']}  (from {m['universe']} stocks scanned)")
    print(f"  JSON parse (median)      {m['parse_ms']:.2f} ms")
    print()
    print("  Per refresh:")
    print(f"    radio awake            {e['radio_s']:.1f} s   -> {e['radio_mwh']:.3f} mWh")
    print(f"    cpu awake              {e['cpu_s']:.2f} s   -> {e['cpu_mwh']:.3f} mWh")
    print(f"    TOTAL                  {e['total_mwh']:.3f} mWh"
          f"  ({e['pct_of_battery']:.5f}% of a {BATTERY_MAH} mAh cell)")
    print()

    print("=" * 68)
    print("PROJECTED DAILY DRAIN BY REFRESH INTERVAL")
    print("=" * 68)
    print(f"  {'interval':>10} {'wakes/day':>10} {'mWh/day':>10} {'%batt/day':>11} "
          f"{'%batt/month':>12}")
    for hours in (1, 3, 6, 12, 24):
        wakes = 24 / hours
        daily = e["total_mwh"] * wakes
        pct = daily / BATTERY_MWH * 100
        marker = "   <-- current setting" if hours == 6 else ""
        print(f"  {hours:>8}h {wakes:>10.0f} {daily:>10.3f} {pct:>10.4f}% "
              f"{pct * 30:>11.3f}%{marker}")

    print()
    print("=" * 68)
    print("READ THIS")
    print("=" * 68)
    daily_pct = e["total_mwh"] * 4 / BATTERY_MWH * 100
    print(f"  At the 6-hour interval the app costs about {daily_pct:.4f}% of the")
    print(f"  battery per day - roughly {daily_pct * 30:.2f}% per month.")
    print()
    print("  For scale, a single minute of screen-on time costs about 0.3% of")
    print("  the battery. The app's entire monthly background cost is therefore")
    print(f"  under {daily_pct * 30 / 0.3:.1f} seconds of looking at the screen.")
    print()
    print("  The dominant term is the radio tail (the seconds the modem stays")
    print("  awake after any transfer), not the payload. Making the JSON smaller")
    print("  would change almost nothing; polling less often is the only lever")
    print("  that matters - and 6h is already far below the point of diminishing")
    print("  returns, since the data only changes once a day after the close.")
    print()
    print("  Caveat: these are power-model estimates. Real numbers need")
    print("  `adb shell dumpsys batterystats` on the phone - see devtools/README.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
