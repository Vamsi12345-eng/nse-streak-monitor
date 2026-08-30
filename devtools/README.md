# devtools

Testing aids that run before anything touches the phone.

## `build-apk.sh` / `build-apk.ps1` — build the APK locally

```bash
bash devtools/build-apk.sh              # assembleDebug
bash devtools/build-apk.sh lintDebug    # any other Gradle task
```

```powershell
.\devtools\build-apk.ps1
.\devtools\build-apk.ps1 -Task lintDebug
```

Use these rather than calling `gradle` directly — see *Why a wrapper is needed* below.
Output lands at `app/app/build/outputs/apk/debug/app-debug.apk` (~18 MB debug build).

Current status: **`assembleDebug` succeeds.** `lintDebug` reports 34 warnings and 0
errors, all of them "a newer version is available" — none about correctness, wakelocks,
or battery.

## `preview.py` — see the app screens on a desktop

```bash
python devtools/preview.py --open
```

Regenerates `preview.html` from `engine/out/scan.json` and opens it. All four screens
(notification, home, detail, settings) render from the same JSON the Android app parses,
so wrong numbers, missing fields, bad formatting and broken empty states show up exactly
as they would on the phone. The device frame has its own light/dark toggle, independent
of your system theme.

**Catches:** data bugs, empty states, text overflow, both themes.
**Cannot catch:** Compose rendering, touch targets, scroll physics.

To check the empty state, run a scan with a threshold nothing meets and regenerate:

```bash
cd engine && python run_scan.py --gain 15 --json out/empty.json && cd .. && python devtools/preview.py --scan engine/out/empty.json
```

## `measure_cost.py` — what the app costs to run

```bash
python devtools/measure_cost.py
```

Measures the real work per refresh (payload bytes, parse time) and projects battery drain
across polling intervals.

Result at the shipped 6-hour interval: **~0.0147% of a 5000 mAh battery per day, ~0.44%
per month.** The radio tail — the seconds the modem stays awake after any transfer —
dominates completely, so shrinking the JSON would change almost nothing. Polling frequency
is the only meaningful lever, and 6h is already well past diminishing returns because the
data changes once a day, after the close.

These are power-model estimates. Real numbers need the phone (below).

---

## Real battery measurement, on the phone

Estimates are not measurements. Once the APK is installed, this gives actual figures.
`adb` ships with platform-tools, already installed at `D:\Android\Sdk\platform-tools`.

Enable **Developer options** (Settings → About phone → Software information → tap *Build
number* seven times), then **USB debugging**, and connect over USB.

```bash
adb devices
```

Reset the counters, then leave the phone unplugged and idle so WorkManager actually runs
a few cycles:

```bash
adb shell dumpsys batterystats --reset
```

Unplug. After ~24 hours of normal use, plug back in and pull the stats:

```bash
adb shell dumpsys batterystats --charged com.nseanalysis.app > batterystats.txt
```

What to look for in that file:

| Line | Meaning |
|---|---|
| `Wake lock ... realtime` | total time the app held the CPU awake — expect a few seconds/day |
| `Mobile radio active` / `Wifi radio` | radio time attributed to the app |
| `Total wakelock time` | minutes rather than seconds means something is wrong |
| `Jobs: ... times` | how often WorkManager actually fired — expect ~4/day |

That last row matters most on a Samsung. If it shows far fewer than 4 runs a day, One UI
is deep-sleeping the app and the battery exemption in the app's Settings screen has not
been applied.

For a readable view, upload `batterystats.txt` to
[Battery Historian](https://developer.android.com/topic/performance/power/setup-battery-historian).

Verify the background job is actually scheduled:

```bash
adb shell dumpsys jobscheduler | grep -A 12 nseanalysis
```

---

## `drive.py` — run the real app on the emulator

The AVD `s24ultra` matches the device: 1440x3120, density 560, Android 15 (API 35).

```bash
D:/Android/Sdk/emulator/emulator.exe -avd s24ultra        # if not already running
bash devtools/build-apk.sh assembleDebug -PfeedUrl=http://10.0.2.2:8765/scan.json
D:/Android/Sdk/platform-tools/adb.exe install -r -g app/app/build/outputs/apk/debug/app-debug.apk
```

`10.0.2.2` is how the emulator reaches this machine's loopback, so serve the scan there:

```bash
cd engine/out && python -m http.server 8765 --bind 127.0.0.1
```

Cleartext HTTP is permitted for `10.0.2.2` / `localhost` only, via
`app/src/main/res/xml/network_security_config.xml`. The production feed is https and is
unaffected.

Then drive the UI by text rather than pixels:

```bash
python devtools/drive.py launch
python devtools/drive.py scroll down 6
python devtools/drive.py tap "Open in Claude"
python devtools/drive.py shot detail.png
python devtools/drive.py text
```

Tapping by text matters here: the emulator renders in software, so a fling can still be
settling when a screenshot is taken, and any coordinate read a moment earlier is stale.
`drive.py` re-reads the view hierarchy immediately before every tap. Note also that
`LazyColumn` only composes what is on screen, so an element must be scrolled into view
before it can be found at all.

### Testing notifications on demand

The shipped worker is *periodic*, and WorkManager refuses to run periodic work ahead of
its interval - forcing it with `cmd jobscheduler run` only logs *"being executed before
schedule"* and reschedules. Debug builds therefore carry a broadcast receiver that
enqueues an equivalent one-time run:

```bash
adb shell am broadcast -a com.nseanalysis.app.RUN_SCAN_NOW -p com.nseanalysis.app
```

It works on the phone too, which makes it the fastest way to confirm alerts survive One
UI's battery management: trigger it with the screen off and the app backgrounded. The
receiver lives in `src/debug`, so release builds contain neither it nor its manifest entry.

To see an alert you need a hit the device has not seen yet - newness is tracked per
device, so serve a narrower feed first, open the app, then widen it:

```bash
adb shell dumpsys notification --noredact | grep -E "android.title=|android.text="
```

Verified this way: with the app having seen only NSLNISP and the feed then widened to four
hits, the notification read **"3 stocks on a 3-day streak"** - correctly suppressing the
one already seen.

Note that a fresh install can notify about streaks that were already in the feed, because
the periodic worker's first run may land before the UI marks them seen. That is a product
decision rather than a defect; suppressing it is a one-line change in `MainActivity`.

### Measured on the emulator

| Metric | Value | Note |
|---|---|---|
| Jank during scrolling | **2.29%** (5 of 218 frames) | target is under 5% |
| Frame times | p50 17ms, p90 18ms, p99 25ms | 0 missed vsync, 0 slow UI-thread frames |
| Warm start | **231 ms** | |
| Cold start | ~3.0-3.2 s | see below |
| Memory | 110 MB PSS | |
| WorkManager | `Worker result SUCCESS` | background refresh path confirmed working |

**Do not read the cold-start figure as a device number.** This is a debug build - no R8, no
resource shrinking, and no baseline profile, with logcat reporting *"failed lock
verification and will run slower ... non-optimized dex code"* - running on a
software-rendered emulator on a low-power laptop CPU. The S24 Ultra has a Snapdragon 8
Gen 3 and would run a release build. The jank and warm-start figures are the meaningful
ones, and both are good.

Adding a Baseline Profile would be the single highest-value cold-start optimisation if it
turns out to matter on the real device.

## Why a wrapper is needed for local builds

A bare `gradle assembleDebug` fails on this machine with:

```
java.io.IOException: Unable to establish loopback connection
```

Java NIO builds every `Selector` on an AF_UNIX socket pair, created inside the directory
named by the **`TEMP` environment variable**. This user profile's Temp directory cannot
host one, and Gradle's daemon needs a Selector, so no build can start.

Isolated with a three-line Java program that only calls `Selector.open()`, run five times
because the failure is intermittent:

| Condition | Result |
|---|---|
| `TEMP` = the profile's own `AppData\Local\Temp` (default) | **FAIL 0/5** |
| `TEMP` = `C:\gtmp` | **PASS 5/5** |
| `TEMP` = long-name form of that same profile Temp dir | FAIL 0/5 |
| Same probe under a different Windows user account | PASS 5/5 |

Ruled out along the way: the 108-byte `sockaddr_un` limit (the failing path is 65 chars),
the 8.3 short name (the long form fails identically), spaces in the path (`C:\has space`
works), JDK version (17 and 21 fail alike), forcing the legacy
`sun.nio.ch.WindowsSelectorProvider`, Hyper-V reserved port ranges (60 of 16384 reserved),
and third-party Winsock LSPs (none installed). Blocking-IO loopback, NIO TCP loopback, and
`PipeImpl`'s self-connection peer check all work when exercised directly.

On the failing directory the AF_UNIX **bind succeeds** and **connect returns "Invalid
argument"** — after which the leftover `.sock` file cannot be deleted either, with Windows
reporting *"The file cannot be accessed by the system"*. That points at something
filtering that specific directory rather than anything about the path itself.

**`-Djava.io.tmpdir` does not fix it.** Windows resolves the AF_UNIX path natively from
the environment, so the override has to be on `TEMP`/`TMP` before the JVM starts — which
is the entire content of the build scripts.

To fix it at the source instead of carrying the wrapper, `devtools/fix-gradle-loopback.ps1`
(run elevated) tries Defender exclusions, then stopping McAfee Security Scan, then removing
it — re-testing after each step and stopping as soon as it passes.
`.github/workflows/build-apk.yml` also builds on `ubuntu-latest`, where none of this
applies.

### Installed toolchain

JDK 17 and 21 (Temurin), Android SDK platform 35, build-tools 35.0.0 and 34.0.0,
platform-tools (`adb`), Gradle 8.11.1 at `D:\Android\gradle\gradle-8.11.1`.
