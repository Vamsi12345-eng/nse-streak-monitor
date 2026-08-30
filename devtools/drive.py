#!/usr/bin/env python3
"""Drive the app on a connected device or emulator, by text rather than pixels.

Tapping raw coordinates is unreliable here: the emulator renders in software,
so a fling can still be settling when a screenshot is taken, and any
coordinate read a moment earlier is then stale. Every action below re-reads the
view hierarchy immediately before acting on it.

    python devtools/drive.py launch
    python devtools/drive.py tap "Open in Claude"
    python devtools/drive.py shot home.png
    python devtools/drive.py find Claude
    python devtools/drive.py scroll down 3
    python devtools/drive.py text          # everything readable on screen
"""
from __future__ import annotations

import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Optional, Tuple

ADB = r"D:\Android\Sdk\platform-tools\adb.exe"
PKG = "com.nseanalysis.app"
ACTIVITY = f"{PKG}/.MainActivity"
TMP = Path(r"C:\gtmp")

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def adb(*args: str, timeout: int = 120) -> str:
    out = subprocess.run(
        [ADB, "-s", device(), *args],
        capture_output=True, text=True, timeout=timeout,
        encoding="utf-8", errors="replace",
    )
    return (out.stdout or "") + (out.stderr or "")


_device: Optional[str] = None


def device() -> str:
    global _device
    if _device:
        return _device
    out = subprocess.run([ADB, "devices"], capture_output=True, text=True).stdout
    for line in out.splitlines()[1:]:
        if "\tdevice" in line:
            _device = line.split("\t")[0]
            return _device
    raise SystemExit("no device/emulator attached (run: adb devices)")


def dump() -> ET.Element:
    """Fetch the current view hierarchy."""
    # The remote path must not be translated by MSYS; calling adb directly
    # (not through a shell) avoids that entirely.
    for attempt in range(3):
        adb("shell", "uiautomator", "dump", "/sdcard/_drive.xml")
        local = TMP / "_drive.xml"
        adb("pull", "/sdcard/_drive.xml", str(local))
        if local.exists():
            try:
                return ET.parse(local).getroot()
            except ET.ParseError:
                pass
        time.sleep(1)
    raise SystemExit("could not read the view hierarchy")


def nodes_matching(root: ET.Element, needle: str) -> List[Tuple[str, Tuple[int, int]]]:
    found = []
    low = needle.lower()
    for n in root.iter("node"):
        label = (n.get("text") or "") + " " + (n.get("content-desc") or "")
        if low in label.lower():
            m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", n.get("bounds", ""))
            if not m:
                continue
            x1, y1, x2, y2 = map(int, m.groups())
            found.append((label.strip(), ((x1 + x2) // 2, (y1 + y2) // 2)))
    return found


def foreground() -> str:
    out = adb("shell", "dumpsys", "window", "displays")
    m = re.search(r"mCurrentFocus=Window\{\S+ \S+ (\S+)\}", out)
    return m.group(1) if m else "?"


def ensure_running() -> None:
    if PKG not in foreground():
        adb("shell", "am", "start", "-n", ACTIVITY)
        time.sleep(4)


def cmd_launch() -> None:
    adb("shell", "am", "start", "-n", ACTIVITY)
    time.sleep(4)
    print("foreground:", foreground())


def cmd_tap(needle: str) -> None:
    ensure_running()
    hits = nodes_matching(dump(), needle)
    if not hits:
        print(f"no element matching {needle!r}. On screen:")
        cmd_text()
        raise SystemExit(1)
    label, (x, y) = hits[0]
    print(f"tapping {label[:60]!r} at ({x},{y})")
    adb("shell", "input", "tap", str(x), str(y))
    time.sleep(2.5)
    print("foreground:", foreground())


def cmd_find(needle: str) -> None:
    for label, (x, y) in nodes_matching(dump(), needle):
        print(f"  ({x:>5},{y:>5})  {label[:70]}")


def cmd_text() -> None:
    root = dump()
    for n in root.iter("node"):
        t = (n.get("text") or "").strip()
        if t:
            print("  " + t[:90])


def cmd_scroll(direction: str, times: int) -> None:
    # Swipe distances are conservative so a fling does not overshoot past the
    # content we are trying to land on.
    for _ in range(times):
        if direction == "down":
            adb("shell", "input", "swipe", "720", "2200", "720", "900", "250")
        else:
            adb("shell", "input", "swipe", "720", "900", "720", "2200", "250")
        time.sleep(1.2)
    time.sleep(1.5)


def cmd_shot(name: str) -> None:
    raw = subprocess.run(
        [ADB, "-s", device(), "exec-out", "screencap", "-p"],
        capture_output=True, timeout=120,
    ).stdout
    out = TMP / name
    out.write_bytes(raw)
    try:
        from PIL import Image
        im = Image.open(out)
        size = im.size
        im.thumbnail((430, 940))
        small = out.with_name(out.stem + "_small.png")
        im.save(small)
        print(f"{out}  ({size[0]}x{size[1]})\n{small}")
    except ImportError:
        print(out)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    cmd, *rest = sys.argv[1:]
    if cmd == "launch":
        cmd_launch()
    elif cmd == "tap":
        cmd_tap(" ".join(rest))
    elif cmd == "find":
        cmd_find(" ".join(rest))
    elif cmd == "text":
        cmd_text()
    elif cmd == "scroll":
        cmd_scroll(rest[0] if rest else "down", int(rest[1]) if len(rest) > 1 else 1)
    elif cmd == "shot":
        cmd_shot(rest[0] if rest else "shot.png")
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
