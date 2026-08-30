# Streak Monitor — NSE consecutive-gain screener

Finds Nifty 500 stocks that gained **≥3% on each of 3 consecutive sessions**, works out
*why* they moved, and builds a peer-relative one-year research brief. Android app for the
notification and the reading; a scheduled job does the work.

No paid APIs. No broker account. No LLM in the automated path.

---

## What makes the "why" trustworthy

The engine answers three questions in order, because only the leftover needs a
company-specific explanation:

1. **Did the whole market move?** — median move and breadth across the Nifty 500.
2. **Did the whole sector move?** — median move across that stock's industry peers.
3. **Did the company disclose anything?** — NSE corporate filings on those exact dates.

A stock up 9% while its sector is up 8% did not have news; it had a sector rotation. The
engine says so rather than inventing a story.

Filings are sorted into three buckets, because they mean opposite things:

| Bucket | Examples | Meaning |
|---|---|---|
| `catalyst` | order win, results, credit rating action, capacity expansion | plausible cause of the rise |
| `caution` | **Spurt in Volume**, ASM/GSM surveillance, promoter pledge, auditor exit | a warning, *not* a buy signal |
| `neutral` | newspaper publication, board meeting intimation | noise |

`caution` deliberately outranks `catalyst` — a surveillance notice about a company that
also won an order is still, first of all, a warning.

**Real output from a live run:**

> **NMDC Steel (NSLNISP) +22.7% over 3 sessions**
> Verdict: *unexplained.* Outpaced its sector by +21.5pp yet filed no disclosure that
> would account for it. Volume 14.8× normal. Caution: two NSE surveillance queries, a
> director departure, and only ₹18 cr/day turnover.
> One-year view: P/B 1.1 vs sector 3.3 (cheap on assets) but **P/E 158 vs sector 18.9**
> and net margin 0.6% vs 13.1%.

That is the useful answer. A naive screener would have said "🚀 up 22.7%!"

---

## Architecture

```
GitHub Actions (cron, 17:00 + 20:00 IST, Mon–Fri)
  └── engine/run_scan.py
        ├── Nifty 500 list ........... nsearchives.nseindia.com  (free)
        ├── Daily OHLCV .............. Yahoo chart API           (free, no key)
        ├── Fundamentals ............. Yahoo quoteSummary        (free, cookie+crumb)
        ├── Corporate filings ........ nseindia.com/api          (free, cookie warmup)
        └── Headlines ................ Google News RSS           (free)
              ↓
        docs/scan.json  (committed to the repo, ~25 KB)
              ↓
   Android app polls it → local notification → detail screen
              ↓
        "Open in Claude" → your Claude subscription, interactively
```

**Why no LLM in the automated path.** A Claude *subscription* covers interactive use
(claude.ai, the mobile app, Claude Code) — it cannot authenticate a cron job. That would
need pay-as-you-go API credits, a separate product. Since the attribution is deterministic
anyway, the app computes it and hands the evidence to the Claude app when *you* want a
deeper read. Zero marginal cost, and nothing on the detail screen is model-generated.

---

## Setup

### 1. Push this to GitHub

```bash
git init && git add . && git commit -m "Initial commit" && git branch -M main
```

Then create a repo and push. Actions must be allowed to commit:
**Settings → Actions → General → Workflow permissions → Read and write**.

### 2. Run the first scan

Actions tab → **Daily NSE scan** → *Run workflow*. It writes `docs/scan.json`.

### 3. Build the APK

Actions tab → **Build APK** → *Run workflow* → download the `streak-monitor-apk`
artifact. No Android Studio needed. Transfer to your phone and install (you'll need to
allow install from unknown sources once).

The APK is baked with your repo's feed URL automatically. To override, set repo variable
`FEED_URL` (**Settings → Secrets and variables → Actions → Variables**).

### 4. On the phone — do not skip this

One UI puts unused apps to sleep, which silently kills background refresh. You would
simply never get an alert, with nothing indicating why.

- **Settings → Apps → Streak Monitor → Battery → Unrestricted**
- **Settings → Battery → Background usage limits** → confirm the app is **not** in
  *Sleeping apps* or *Deep sleeping apps*

The app's Settings screen has buttons that jump straight to these.

### 5. Optional — instant push

The app polls every 6 hours. For an immediate push instead, install
[ntfy](https://ntfy.sh) from the Play Store, subscribe to a topic name only you know, and
add it as repo secret `NTFY_TOPIC`. The workflow will push there on every new hit.

---

## Running it locally

```bash
cd engine && pip install -r requirements-dev.txt
```

```bash
python run_scan.py
```

Useful flags:

```bash
python run_scan.py --gain 2 --days 4 --min-turnover 25 --json out/scan.json
```

| Flag | Meaning |
|---|---|
| `--gain` | minimum daily gain % (default 3) |
| `--days` | consecutive sessions required (default 3) |
| `--min-turnover` | liquidity floor, ₹ crore/day median (default 5) |
| `--watchlist` | extra symbols outside the Nifty 500, comma-separated |
| `--no-enrich` | screen only — skips filings and fundamentals, ~3s |
| `--state` | dedupe file, so a re-run doesn't re-alert |

```bash
python -m pytest tests/ -v
```

A full enriched scan of all 500 names takes about **13 seconds**.

---

## Things worth knowing

**Yahoo lags part of the universe by a session.** Roughly a third of NSE names get
backfilled a day late. The screener tolerates a lag of up to 5 calendar days and marks
those hits *"feed lagging"* rather than dropping them — an early version compared against
an index instead and silently discarded 316 of 500 stocks. The second daily cron run
catches the stragglers.

**Yahoo's NSE sector indices are unreliable** — most were six weeks stale when this was
built. So sector moves are computed from the constituents instead, which is always as
fresh as the price data and needs no extra requests.

**Don't send `Accept: application/json` to Yahoo.** The crumb endpoint answers 406, every
`quoteSummary` call then fails, and because the chart endpoint keeps working it looks like
missing fundamentals rather than an auth problem.

**A quiet market produces zero hits, and that is correct.** 3%×3 days is a genuinely rare
event — the live run while building this found exactly one across the whole Nifty 500. If
you want more signal, lower `--gain` or `--days`; the sensitivity is roughly:

| Rule | Matches (one sample session) |
|---|---|
| ≥3% × 3d | 1 |
| ≥2% × 3d | 1 |
| ≥2% × 2d | 4 |
| ≥3% × 1d | 31 |

**Scope.** Screens the Nifty 500 only. Smaller counters are where 3%×3-day streaks are
most common and least meaningful — thin books, wide spreads, and the occasional operator.
Add specific names via `--watchlist` if you follow one.

---

## Not investment advice

A research tool that surfaces evidence and comparisons. It deliberately produces a bull
case, a bear case, and what would invalidate the thesis — never a verdict. Price data
comes from a free public source and can be wrong, delayed or missing. Verify every filing
at [nseindia.com](https://www.nseindia.com) before acting on it.
