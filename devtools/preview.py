#!/usr/bin/env python3
"""Renders the Android screens as HTML, driven by a real scan.json.

Not a mockup: every value on screen is read from the same JSON the app parses,
so a wrong number, a missing field or an empty-state bug shows up here exactly
as it would on the phone. Colours and layout mirror the Compose source
(ui/theme/Theme.kt, ui/screens/*.kt) so this stays a preview rather than a
separate design that drifts.

    python devtools/preview.py                 # writes devtools/preview.html
    python devtools/preview.py --open          # and opens it
"""
from __future__ import annotations

import argparse
import html
import json
import sys
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]


def esc(v: Any) -> str:
    return html.escape(str(v), quote=True)


def pct(v: Optional[float], dp: int = 1, sign: bool = True) -> str:
    if v is None:
        return "—"
    return f"{v:+.{dp}f}%" if sign else f"{v:.{dp}f}%"


def money(v: float) -> str:
    return f"₹{v:,.2f}"


# --------------------------------------------------------------------------
# Screen renderers - each mirrors one Composable
# --------------------------------------------------------------------------

def render_notification(scan: Dict) -> str:
    """The heads-up notification, which is the first thing seen in practice."""
    hits = scan.get("hits", [])
    days = scan.get("config", {}).get("streak_days", 3)
    if not hits:
        return (
            '<div class="notif-empty">No notification would fire — '
            "nothing met the streak rule this session.</div>"
        )
    if len(hits) == 1:
        h = hits[0]
        title = f"{h['symbol']} {pct(h['cumulative_pct'])} over {days} days"
    else:
        title = f"{len(hits)} stocks on a {days}-day streak"

    lines = "".join(
        f'<div class="notif-line"><span class="mono">{esc(h["symbol"])}</span>'
        f'<span class="mono gain">{pct(h["cumulative_pct"])}</span>'
        f'<span class="notif-verdict">{esc((h.get("attribution") or {}).get("headline", h["industry"]))}</span></div>'
        for h in hits[:6]
    )
    return f"""
    <div class="shade">
      <div class="notif">
        <div class="notif-head">
          <span class="notif-icon">📈</span>
          <span class="notif-app">Streak Monitor</span>
          <span class="notif-time">now</span>
        </div>
        <div class="notif-title">{esc(title)}</div>
        <div class="notif-body">{lines}</div>
      </div>
      <p class="shade-note">Tapping this opens the stock directly — the intent carries the
      symbol, so it skips the list.</p>
    </div>"""


def render_home(scan: Dict) -> str:
    market = scan.get("market", {})
    cfg = scan.get("config", {})
    hits = scan.get("hits", [])
    stats = scan.get("stats", {})

    header = f"""
    <div class="appbar">
      <div>
        <div class="appbar-title">Streak Monitor</div>
        <div class="appbar-sub">Session {esc(scan.get('session','—'))} &nbsp;·&nbsp;
          {stats.get('universe', 0)} stocks scanned</div>
      </div>
      <div class="appbar-actions"><span>⟳</span><span>⚙</span></div>
    </div>"""

    market_card = f"""
    <div class="card card-variant">
      <div class="card-label">Market</div>
      <div class="stat-row">
        <div class="stat"><div class="stat-val {tone(market.get('median_day_pct', 0))}">
          {pct(market.get('median_day_pct'), 2)}</div><div class="stat-lbl">Median move</div></div>
        <div class="stat"><div class="stat-val">{market.get('breadth_pct', 0):.0f}%</div>
          <div class="stat-lbl">Advancing</div></div>
        <div class="stat"><div class="stat-val">{len(hits)}</div><div class="stat-lbl">Matches</div></div>
      </div>
      <div class="card-foot">Rule: ≥ {cfg.get('daily_gain_pct', 3):.0f}% on each of
        {cfg.get('streak_days', 3)} consecutive sessions</div>
    </div>"""

    if not hits:
        sectors = "".join(
            f'<div class="sector-row"><span>{esc(s["industry"])}</span>'
            f'<span class="mono {tone(s["median_day_pct"])}">{pct(s["median_day_pct"], 2)}</span></div>'
            for s in scan.get("sectors", [])[:8]
        )
        body = f"""
        <div class="card">
          <div class="card-title">No stock met the streak rule</div>
          <div class="card-body">Nothing gained {cfg.get('daily_gain_pct',3):.0f}% on each of
            {cfg.get('streak_days',3)} consecutive sessions. On a quiet market that is the
            normal result, not a failure.</div>
        </div>
        <div class="card"><div class="card-title">Sector moves today</div>
          <div class="sector-list">{sectors}</div></div>"""
    else:
        body = "".join(hit_card(h) for h in hits)

    return header + f'<div class="screen-body">{market_card}{body}{disclaimer()}</div>'


def tone(v: Optional[float]) -> str:
    if v is None:
        return ""
    return "gain" if v > 0 else ("loss" if v < 0 else "")


def hit_card(h: Dict) -> str:
    a = h.get("attribution") or {}
    chips = "".join(f'<span class="chip">{pct(d["gain_pct"], 1)}</span>' for d in h.get("days", []))
    if not h.get("is_current", True):
        chips += '<span class="chip chip-muted">feed lagging</span>'

    verdict_cls = {
        "company_catalyst": "gain",
        "unexplained": "caution",
    }.get(a.get("verdict", ""), "muted")

    cautions = ""
    if a.get("cautions"):
        n = len(a["cautions"])
        cautions = (
            f'<div class="caution-line">⚠ {n} caution flag{"s" if n > 1 else ""}</div>'
        )

    vol = f' &nbsp;·&nbsp; {h["volume_ratio"]:.1f}× volume' if h.get("volume_ratio") else ""
    return f"""
    <div class="card card-tap">
      <div class="hit-top">
        <div>
          <div class="hit-sym">{esc(h['symbol'])}</div>
          <div class="hit-name">{esc(h['name'])}</div>
        </div>
        <div class="hit-pct {tone(h['cumulative_pct'])}">{pct(h['cumulative_pct'])}</div>
      </div>
      <div class="chips">{chips}</div>
      <div class="verdict {verdict_cls}">{esc(a.get('headline', ''))}</div>
      {cautions}
      <div class="hit-foot">{esc(h['industry'])} &nbsp;·&nbsp;
        ₹{h['median_turnover_cr']:,.0f} cr/day{vol}</div>
    </div>"""


def render_detail(scan: Dict) -> str:
    hits = scan.get("hits", [])
    if not hits:
        return ('<div class="appbar"><div class="appbar-title">Detail</div></div>'
                '<div class="screen-body"><div class="card"><div class="card-body">'
                "No hits in this scan, so there is no detail screen to show. Run the "
                "scan on a day with a match, or lower the threshold.</div></div></div>")
    h = hits[0]
    a = h.get("attribution") or {}
    sc = h.get("scorecard") or {}
    r = h.get("returns", {})

    header = f"""
    <div class="appbar"><div class="appbar-title">← {esc(h['symbol'])}</div></div>"""

    daily = "&nbsp;&nbsp;&nbsp;".join(
        f'{esc(d["date"][-5:])}&nbsp;&nbsp;{pct(d["gain_pct"], 2)}' for d in h.get("days", [])
    )
    extras = []
    if h.get("volume_ratio"):
        extras.append(f"{h['volume_ratio']:.1f}× normal volume")
    if h.get("pct_from_52w_high") is not None:
        extras.append(f"{h['pct_from_52w_high']:.0f}% from 52w high")

    head_card = f"""
    <div class="card">
      <div class="card-title">{esc(h['name'])}</div>
      <div class="card-sub">{esc(h['industry'])} &nbsp;·&nbsp;
        {esc(h['start_date'])} to {esc(h['end_date'])}</div>
      <div class="big-pct {tone(h['cumulative_pct'])}">{pct(h['cumulative_pct'])}</div>
      <div class="mono daily">{daily}</div>
      <hr>
      <div class="stat-row">
        <div class="stat"><div class="stat-val">{money(h['last_close'])}</div>
          <div class="stat-lbl">Close</div></div>
        <div class="stat"><div class="stat-val {tone(r.get('m1'))}">{pct(r.get('m1'))}</div>
          <div class="stat-lbl">1M</div></div>
        <div class="stat"><div class="stat-val {tone(r.get('m3'))}">{pct(r.get('m3'))}</div>
          <div class="stat-lbl">3M</div></div>
        <div class="stat"><div class="stat-val {tone(r.get('y1'))}">{pct(r.get('y1'))}</div>
          <div class="stat-lbl">1Y</div></div>
      </div>
      <div class="card-foot">₹{h['median_turnover_cr']:,.0f} cr median daily turnover
        {(' · ' + ' · '.join(extras)) if extras else ''}</div>
    </div>"""

    verdict_cls = {"company_catalyst": "gain", "unexplained": "caution"}.get(
        a.get("verdict", ""), "")
    why = f"""
    <div class="card">
      <div class="card-title">Why it moved</div>
      <div class="verdict-strong {verdict_cls}">{esc(a.get('headline',''))}</div>
      <ul class="bullets">{''.join(f'<li>{esc(b)}</li>' for b in a.get('explanation', []))}</ul>
    </div>"""

    caution = ""
    if a.get("cautions"):
        caution = f"""
        <div class="card card-error">
          <div class="card-title">Caution</div>
          <ul class="bullets">{''.join(f'<li>{esc(c)}</li>' for c in a['cautions'])}</ul>
        </div>"""

    filings = ""
    if a.get("filings"):
        rows = ""
        for f in a["filings"]:
            rows += f"""
            <div class="filing">
              <div class="filing-head">
                <span class="bucket bucket-{esc(f['bucket'])}">{esc(f['bucket'].upper())}</span>
                <span class="filing-date mono">{esc(f['date'])} {esc(f['time'])}</span>
              </div>
              <div class="filing-cat">{esc(f['category'])}</div>
              <div class="filing-label bucket-text-{esc(f['bucket'])}">{esc(f['label'])}</div>
              {'<div class="filing-link">Open filing PDF</div>' if f.get('pdf_url') else ''}
            </div>"""
        filings = f'<div class="card"><div class="card-title">Exchange filings in the window</div>{rows}</div>'

    year = ""
    if sc:
        factors = "".join(
            f'<div class="factor"><span class="factor-name">{esc(f["name"])}</span>'
            f'<span class="mono factor-val f-{esc(f["stance"])}">{esc(f["value"])}</span>'
            f'<span class="mono factor-peer">vs {esc(f["peer_value"])}</span></div>'
            for f in sc.get("factors", [])
        )
        def block(title: str, items: List[str], cls: str) -> str:
            if not items:
                return ""
            return (f'<div class="subhead">{title}</div><ul class="bullets {cls}">'
                    + "".join(f"<li>{esc(i)}</li>" for i in items) + "</ul>")
        year = f"""
        <div class="card">
          <div class="card-title">One-year view</div>
          <div class="card-sub">{sc.get('bull_count',0)} supporting / {sc.get('bear_count',0)}
            opposing factors, measured against {(h.get('benchmark') or {}).get('peers',0)} sector peers.</div>
          <div class="factors">{factors}</div>
          {block('Bull case', sc.get('bull_case', []), 'b-gain')}
          {block('Bear case', sc.get('bear_case', []), 'b-loss')}
          {block('What would break this thesis', sc.get('invalidators', []), 'b-caution')}
          {block('Data the engine could not get', sc.get('data_gaps', []), 'b-muted')}
        </div>"""

    claude = f"""
    <div class="card card-primary">
      <div class="card-title">✦ Deep dive with Claude</div>
      <div class="card-body">Sends every number on this screen — the streak, the sector
        comparison, the filings and the fundamentals — to the Claude app as a research
        prompt. Uses your existing subscription; no API key, no extra cost.</div>
      <div class="btn btn-filled">Open in Claude</div>
      <div class="btn btn-outline">⧉ Copy prompt</div>
      <div class="prompt-size mono">prompt payload: {len(h.get('research_prompt','')):,} characters</div>
    </div>"""

    news = ""
    if a.get("headlines"):
        items = "".join(f'<div class="headline">{esc(x["title"])}</div>'
                        for x in a["headlines"][:6])
        news = f"""<div class="card"><div class="card-title">Recent headlines</div>
          <div class="card-sub">Unverified, from Google News. Treat as leads, not evidence.</div>
          {items}</div>"""

    return header + (f'<div class="screen-body">{head_card}{why}{caution}{filings}'
                     f'{year}{claude}{news}{disclaimer()}</div>')


def render_settings(scan: Dict) -> str:
    return """
    <div class="appbar"><div class="appbar-title">← Settings</div></div>
    <div class="screen-body">
      <div class="card">
        <div class="card-title">Scan feed</div>
        <div class="card-body">The raw URL of scan.json published by your GitHub Actions
          workflow. The screener thresholds live in that workflow, not here.</div>
        <div class="field"><span class="field-label">Feed URL</span>
          <span class="mono field-val">https://raw.githubusercontent.com/…/docs/scan.json</span></div>
        <div class="btn btn-outline">Save and refresh</div>
      </div>
      <div class="card card-tertiary">
        <div class="card-title">Important on Samsung</div>
        <div class="card-body">One UI puts unused apps to sleep, which silently stops
          background refresh — you would simply never get an alert, with nothing to
          indicate why.<br><br>
          1.&nbsp; Battery → tap below → set this app to Unrestricted.<br><br>
          2.&nbsp; Settings → Battery → Background usage limits → make sure this app is
          NOT in "Sleeping apps" or "Deep sleeping apps".</div>
        <div class="btn btn-outline">Open battery settings</div>
        <div class="btn btn-outline">Open notification settings</div>
      </div>
      <div class="card">
        <div class="card-title">How this app works</div>
        <div class="card-body">A scheduled job scans the Nifty 500 after each close and
          publishes the result as a small JSON file. This app reads that file — it does not
          talk to any broker, hold any credentials, or place any orders.<br><br>
          Attribution is computed, not generated. Nothing on the detail screen is written
          by a language model.</div>
      </div>
    </div>"""


def disclaimer() -> str:
    return ('<div class="disclaimer">Evidence for your own judgement, not investment '
            "advice. Verify every filing before acting on it.</div>")


# --------------------------------------------------------------------------
# Page assembly
# --------------------------------------------------------------------------

def build(scan: Dict) -> str:
    screens = {
        "notification": render_notification(scan),
        "home": render_home(scan),
        "detail": render_detail(scan),
        "settings": render_settings(scan),
    }
    panes = "".join(
        f'<div class="screen" data-screen="{k}" {"hidden" if k != "home" else ""}>{v}</div>'
        for k, v in screens.items()
    )

    hits = scan.get("hits", [])
    facts = [
        ("Session", scan.get("session", "—")),
        ("Generated", scan.get("generated_at", "—")[:16].replace("T", " ")),
        ("Universe", f"{scan.get('stats', {}).get('universe', 0)} stocks"),
        ("Matches", str(len(hits))),
        ("Feed size", f"{len(json.dumps(scan)) / 1024:.1f} KB"),
    ]
    fact_rows = "".join(
        f'<div class="fact"><span>{esc(k)}</span><span class="mono">{esc(v)}</span></div>'
        for k, v in facts
    )

    css = CSS
    data_json = json.dumps(scan, ensure_ascii=False)

    return f"""<title>Streak Monitor Preview</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Roboto:wght@400;500;700&display=swap">
<style>{css}</style>

<header class="harness-head">
  <div>
    <h1>Streak Monitor</h1>
    <p class="sub">Android screens rendered from the live <code>scan.json</code> — every
      value below is the one the phone would parse.</p>
  </div>
  <div class="facts">{fact_rows}</div>
</header>

<div class="controls">
  <div class="seg" role="tablist" aria-label="Screen">
    <button class="seg-btn" data-go="notification" role="tab" aria-selected="false">Notification</button>
    <button class="seg-btn is-on" data-go="home" role="tab" aria-selected="true">Home</button>
    <button class="seg-btn" data-go="detail" role="tab" aria-selected="false">Detail</button>
    <button class="seg-btn" data-go="settings" role="tab" aria-selected="false">Settings</button>
  </div>
  <button class="theme-btn" id="devtheme" aria-label="Toggle device theme">◐ Device: dark</button>
</div>

<main class="stage">
  <div class="phone-wrap">
    <div class="phone" id="phone" data-device-theme="dark">
      <div class="statusbar"><span class="mono">9:41</span><span class="mono">▮▮▮ ⬤</span></div>
      <div class="viewport" id="viewport">{panes}</div>
    </div>
    <div class="phone-cap mono">S24 Ultra · 412 × 915 dp</div>
  </div>

  <aside class="notes">
    <h2>What this catches</h2>
    <ul>
      <li><b>Data bugs</b> — wrong numbers, missing fields, bad formatting all surface
        here exactly as on the phone, because this reads the same JSON.</li>
      <li><b>Empty states</b> — switch the scan to a day with no hits and the Home and
        Detail screens have to stay sensible.</li>
      <li><b>Overflow</b> — long company names, many filings, long caution lists.</li>
      <li><b>Both themes</b> — the toggle above flips the device independently of your
        system setting.</li>
    </ul>
    <h2>What it cannot catch</h2>
    <ul>
      <li>Compose rendering, touch targets, scroll physics, real fonts metrics.</li>
      <li>Whether the Kotlin compiles — that needs a JDK and the Android SDK.</li>
      <li>Real battery behaviour — needs the phone and <code>batterystats</code>.</li>
    </ul>
  </aside>
</main>

<script>
const data = {data_json};
const viewport = document.getElementById('viewport');
document.querySelectorAll('.seg-btn').forEach(btn => {{
  btn.addEventListener('click', () => {{
    document.querySelectorAll('.seg-btn').forEach(b => {{
      b.classList.toggle('is-on', b === btn);
      b.setAttribute('aria-selected', b === btn ? 'true' : 'false');
    }});
    viewport.querySelectorAll('.screen').forEach(s => {{
      s.hidden = s.dataset.screen !== btn.dataset.go;
    }});
    viewport.scrollTop = 0;
  }});
}});
const phone = document.getElementById('phone');
const themeBtn = document.getElementById('devtheme');
themeBtn.addEventListener('click', () => {{
  const next = phone.dataset.deviceTheme === 'dark' ? 'light' : 'dark';
  phone.dataset.deviceTheme = next;
  themeBtn.textContent = '◐ Device: ' + next;
}});
console.log('scan.json loaded:', data.stats, data.hits.length, 'hits');
</script>
"""


CSS = """
:root{
  --bg:#EEF2F1; --panel:#FFFFFF; --ink:#16201E; --ink-dim:#5A6B67; --line:#D2DDDA;
  --accent:#20524A; --accent-soft:#A7F2E0;
  /* Device palette - light. Mirrors ui/theme/Theme.kt exactly. */
  --d-surface:#FFFBFF; --d-surface-var:#DBE5E0; --d-ink:#191C1B; --d-ink-dim:#3F4945;
  --d-primary:#20524A; --d-primary-c:#A7F2E0; --d-on-primary-c:#00201A;
  --d-gain:#1B7F4B; --d-loss:#B3261E; --d-caution:#8A5A00;
  --d-error-c:#F9DEDC; --d-on-error-c:#410E0B; --d-tert-c:#DDE7F5; --d-on-tert-c:#0F1B2A;
  --d-outline:#E2E8E5;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --bg:#12171A; --panel:#1A2124; --ink:#DCE5E2; --ink-dim:#8DA09B; --line:#2A3438;
    --accent:#8BD5C5; --accent-soft:#005046;
  }
}
:root[data-theme="dark"]{
  --bg:#12171A; --panel:#1A2124; --ink:#DCE5E2; --ink-dim:#8DA09B; --line:#2A3438;
  --accent:#8BD5C5; --accent-soft:#005046;
}
/* Device dark palette, toggled independently of the host theme. */
.phone[data-device-theme="dark"]{
  --d-surface:#101413; --d-surface-var:#3F4945; --d-ink:#E1E3E1; --d-ink-dim:#BFC9C4;
  --d-primary:#8BD5C5; --d-primary-c:#005046; --d-on-primary-c:#A7F2E0;
  --d-gain:#6FD39B; --d-loss:#F2B8B5; --d-caution:#FFD08A;
  --d-error-c:#601410; --d-on-error-c:#F9DEDC; --d-tert-c:#1E2A38; --d-on-tert-c:#CFE0F5;
  --d-outline:#2A3230;
}

*{box-sizing:border-box}
body{
  margin:0; background:var(--bg); color:var(--ink);
  font-family:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,monospace;
  font-size:14px; line-height:1.55; padding:28px 24px 56px;
}
.mono{font-family:"JetBrains Mono",ui-monospace,monospace; font-variant-numeric:tabular-nums}

.harness-head{
  display:flex; flex-wrap:wrap; gap:24px; justify-content:space-between;
  align-items:flex-start; max-width:1180px; margin:0 auto 22px;
  padding-bottom:20px; border-bottom:1px solid var(--line);
}
.harness-head h1{
  margin:0; font-size:22px; font-weight:700; letter-spacing:-.01em; color:var(--ink);
}
.sub{margin:6px 0 0; color:var(--ink-dim); max-width:56ch; font-size:13px}
code{background:var(--panel); padding:1px 5px; border-radius:4px; font-size:12px}
.facts{display:grid; gap:3px; min-width:230px}
.fact{display:flex; justify-content:space-between; gap:18px; font-size:12px; color:var(--ink-dim)}
.fact span:last-child{color:var(--ink)}

.controls{
  display:flex; flex-wrap:wrap; gap:12px; justify-content:space-between;
  align-items:center; max-width:1180px; margin:0 auto 20px;
}
.seg{display:flex; gap:2px; background:var(--panel); padding:3px; border-radius:9px;
  border:1px solid var(--line)}
.seg-btn,.theme-btn{
  font:inherit; font-size:12px; cursor:pointer; border:0; border-radius:7px;
  padding:7px 14px; background:transparent; color:var(--ink-dim);
}
.seg-btn.is-on{background:var(--accent); color:var(--bg); font-weight:700}
.theme-btn{border:1px solid var(--line); background:var(--panel); color:var(--ink-dim)}
.seg-btn:focus-visible,.theme-btn:focus-visible{outline:2px solid var(--accent); outline-offset:2px}

.stage{
  display:flex; gap:36px; align-items:flex-start; justify-content:center;
  flex-wrap:wrap; max-width:1180px; margin:0 auto;
}
.phone-wrap{display:flex; flex-direction:column; align-items:center; gap:10px}
.phone{
  width:412px; max-width:100%;
  /* Fits the browser window so the page itself does not also scroll; the
     dp caption below still states the true device height. */
  height:min(915px, calc(100vh - 210px)); min-height:520px;
  background:var(--d-surface); border-radius:34px; overflow:hidden;
  border:9px solid #0A0D0C; box-shadow:0 18px 50px rgba(0,0,0,.34);
  display:flex; flex-direction:column;
}
.phone-cap{font-size:11px; color:var(--ink-dim)}
.statusbar{
  display:flex; justify-content:space-between; padding:8px 20px 4px;
  font-size:11px; color:var(--d-ink-dim); background:var(--d-surface); flex:0 0 auto;
}
.viewport{flex:1; overflow-y:auto; overflow-x:hidden; background:var(--d-surface);
  font-family:Roboto,system-ui,sans-serif;
  /* Keeps a scroll gesture inside the phone instead of chaining to the page. */
  overscroll-behavior:contain; scrollbar-width:thin}
.viewport::-webkit-scrollbar{width:5px}
.viewport::-webkit-scrollbar-thumb{background:var(--d-surface-var); border-radius:3px}

/* ---- device UI ---- */
.appbar{
  display:flex; justify-content:space-between; align-items:flex-start;
  padding:12px 16px 10px; color:var(--d-ink); background:var(--d-surface);
  position:sticky; top:0; z-index:2;
}
.appbar-title{font-size:20px; font-weight:500}
.appbar-sub{font-size:11px; color:var(--d-ink-dim); margin-top:1px}
.appbar-actions{display:flex; gap:16px; font-size:17px; color:var(--d-ink-dim)}
.screen-body{padding:4px 16px 28px; display:flex; flex-direction:column; gap:12px}

.card{
  background:var(--d-surface); border:1px solid var(--d-outline);
  border-radius:12px; padding:16px; color:var(--d-ink);
}
.card-variant{background:var(--d-surface-var)}
.card-primary{background:var(--d-primary-c); color:var(--d-on-primary-c); border-color:transparent}
.card-error{background:var(--d-error-c); color:var(--d-on-error-c); border-color:transparent}
.card-tertiary{background:var(--d-tert-c); color:var(--d-on-tert-c); border-color:transparent}
.card-tap{cursor:pointer}
.card-label{font-size:12px; font-weight:500; letter-spacing:.04em}
.card-title{font-size:14px; font-weight:700; margin-bottom:4px}
.card-sub{font-size:11px; color:var(--d-ink-dim); margin-bottom:8px}
.card-body{font-size:12.5px; color:inherit; opacity:.92}
.card-foot{font-size:11px; color:var(--d-ink-dim); margin-top:8px}
.card hr{border:0; border-top:1px solid var(--d-outline); margin:12px 0}

.stat-row{display:flex; gap:20px; margin-top:8px; flex-wrap:wrap}
.stat-val{font-size:15px; font-weight:500; font-variant-numeric:tabular-nums}
.stat-lbl{font-size:10px; color:var(--d-ink-dim)}
.gain{color:var(--d-gain)} .loss{color:var(--d-loss)} .caution{color:var(--d-caution)}
.muted{color:var(--d-ink-dim)}

.hit-top{display:flex; justify-content:space-between; align-items:flex-start; gap:12px}
.hit-sym{font-size:16px; font-weight:700}
.hit-name{font-size:11px; color:var(--d-ink-dim)}
.hit-pct{font-size:24px; font-weight:700; font-variant-numeric:tabular-nums; white-space:nowrap}
.chips{display:flex; gap:6px; margin-top:10px; flex-wrap:wrap}
.chip{
  background:var(--d-primary-c); color:var(--d-on-primary-c);
  border-radius:6px; padding:3px 8px; font-size:11px;
  font-family:"JetBrains Mono",monospace; font-variant-numeric:tabular-nums;
}
.chip-muted{background:var(--d-surface-var); color:var(--d-ink-dim)}
.verdict{margin-top:12px; font-size:12.5px}
.verdict-strong{font-size:13px; font-weight:500; margin:2px 0 8px}
.caution-line{margin-top:8px; font-size:11.5px; color:var(--d-caution)}
.hit-foot{margin-top:10px; font-size:10.5px; color:var(--d-ink-dim)}

.big-pct{font-size:34px; font-weight:700; margin:12px 0 4px; font-variant-numeric:tabular-nums}
.daily{font-size:11.5px; color:var(--d-ink-dim)}

.bullets{margin:6px 0 0; padding-left:16px; font-size:12px; display:flex;
  flex-direction:column; gap:5px}
.bullets li{line-height:1.5}
.b-gain li{color:var(--d-gain)} .b-loss li{color:var(--d-loss)}
.b-caution li{color:var(--d-caution)} .b-muted li{color:var(--d-ink-dim)}
.subhead{margin-top:14px; font-size:10px; font-weight:700; letter-spacing:.07em;
  text-transform:uppercase; color:var(--d-ink-dim)}

.filing{padding:8px 0; border-top:1px solid var(--d-outline)}
.filing:first-of-type{border-top:0}
.filing-head{display:flex; align-items:center; gap:8px}
.bucket{font-size:9px; font-weight:700; letter-spacing:.06em; padding:2px 6px; border-radius:4px}
.bucket-caution{background:color-mix(in srgb,var(--d-caution) 18%,transparent); color:var(--d-caution)}
.bucket-catalyst{background:color-mix(in srgb,var(--d-gain) 18%,transparent); color:var(--d-gain)}
.bucket-neutral{background:var(--d-surface-var); color:var(--d-ink-dim)}
.bucket-text-caution{color:var(--d-caution)} .bucket-text-catalyst{color:var(--d-gain)}
.bucket-text-neutral{color:var(--d-ink-dim)}
.filing-date{font-size:10px; color:var(--d-ink-dim)}
.filing-cat{font-size:12.5px; margin-top:3px}
.filing-label{font-size:11px}
.filing-link{font-size:11px; color:var(--d-primary); margin-top:3px; font-weight:500}

.factors{margin-top:8px; display:flex; flex-direction:column; gap:5px}
.factor{display:flex; align-items:baseline; gap:8px; font-size:11.5px}
.factor-name{flex:1; color:var(--d-ink)}
.factor-val{font-weight:700}
.factor-peer{font-size:10px; color:var(--d-ink-dim)}
.f-bull{color:var(--d-gain)} .f-bear{color:var(--d-loss)} .f-unknown{color:var(--d-ink-dim)}

.btn{
  margin-top:8px; text-align:center; padding:11px; border-radius:22px;
  font-size:13px; font-weight:500; cursor:pointer;
}
.btn-filled{background:var(--d-primary); color:var(--d-surface)}
.btn-outline{border:1px solid currentColor; opacity:.9}
.prompt-size{margin-top:10px; font-size:10px; opacity:.7; text-align:center}
.field{margin:10px 0; padding:11px 12px; border:1px solid var(--d-outline); border-radius:6px;
  display:flex; flex-direction:column; gap:3px}
.field-label{font-size:10px; color:var(--d-primary)}
.field-val{font-size:10.5px; color:var(--d-ink-dim); word-break:break-all}
.headline{font-size:11.5px; color:var(--d-primary); padding:6px 0;
  border-top:1px solid var(--d-outline)}
.sector-list{margin-top:8px}
.sector-row{display:flex; justify-content:space-between; font-size:11.5px; padding:3px 0}
.disclaimer{font-size:10px; color:var(--d-ink-dim); padding:6px 2px 0}

.shade{padding:16px}
.notif{background:var(--d-surface-var); border-radius:20px; padding:14px 16px; color:var(--d-ink)}
.notif-head{display:flex; align-items:center; gap:7px; font-size:11px; color:var(--d-ink-dim)}
.notif-app{font-weight:500}
.notif-time{margin-left:auto}
.notif-title{font-size:14px; font-weight:700; margin:8px 0 6px}
.notif-body{display:flex; flex-direction:column; gap:5px}
.notif-line{display:flex; gap:8px; align-items:baseline; font-size:11px; flex-wrap:wrap}
.notif-verdict{color:var(--d-ink-dim); flex:1 1 100%; font-size:10.5px}
.notif-empty{padding:22px; font-size:12.5px; color:var(--d-ink-dim)}
.shade-note{font-size:11px; color:var(--d-ink-dim); margin-top:14px; padding:0 2px}

.notes{
  flex:1 1 300px; min-width:280px; max-width:400px;
  background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:20px;
}
.notes h2{font-size:12px; text-transform:uppercase; letter-spacing:.07em;
  color:var(--ink-dim); margin:0 0 10px}
.notes h2:not(:first-child){margin-top:22px}
.notes ul{margin:0; padding-left:16px; display:flex; flex-direction:column; gap:8px}
.notes li{font-size:12px; color:var(--ink-dim); line-height:1.5}
.notes b{color:var(--ink); font-weight:700}

@media (max-width:900px){
  body{padding:18px 14px 40px}
  .stage{gap:24px}
  .phone{width:100%; max-width:412px; height:min(760px, calc(100vh - 150px))}
}
@media (prefers-reduced-motion:reduce){*{animation:none!important; transition:none!important}}
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", default=str(ROOT / "engine" / "out" / "scan.json"))
    ap.add_argument("--out", default=str(ROOT / "devtools" / "preview.html"))
    ap.add_argument("--open", action="store_true", help="open in the default browser")
    args = ap.parse_args()

    scan_path = Path(args.scan)
    if not scan_path.exists():
        print(f"No scan at {scan_path}\nRun: cd engine && python run_scan.py --json out/scan.json")
        return 1

    scan = json.loads(scan_path.read_text(encoding="utf-8"))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build(scan), encoding="utf-8")

    print(f"wrote {out}  ({out.stat().st_size:,} bytes)")
    print(f"  session {scan.get('session')}, {len(scan.get('hits', []))} hit(s)")
    if args.open:
        webbrowser.open(out.resolve().as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
