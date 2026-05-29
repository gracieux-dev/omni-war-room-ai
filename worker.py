import sys
import os
import re
import json
import time
import asyncio
import smtplib
import httpx
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from datetime import datetime, timezone

try:
    import pyttsx3 as _pyttsx3
    _TTS_AVAILABLE = True
except ImportError:
    _TTS_AVAILABLE = False

# Must be set BEFORE importing agent_graph
os.environ["OMNI_WORKER_MODE"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table

from rich.text import Text
from rich.rule import Rule
from rich.live import Live
from rich import box

from dotenv import load_dotenv
load_dotenv()

from agents.agent_graph import war_room_graph, THREAT_THRESHOLD

console = Console(highlight=False)

_CONFIG_PATH       = Path(__file__).parent / "data" / "worker_config.json"
_BRAIN_STATE_PATH  = Path(__file__).parent / "ui" / "static" / "worker_brain_state.json"
_JOURNAL_PATH      = Path(__file__).parent / "data" / "agent_journal.jsonl"
_JOURNAL_MAX_LINES = 300

WATCH_URLS = [
    "https://www.notion.so/pricing",
    "https://slack.com/intl/fr-fr/pricing",
    "https://www.shopify.com/fr/tarifs",
]
INTERVAL_SECONDS = 300
ALERT_RECIPIENT  = "chacoungracieux@gmail.com"

PHASE_ORDER = ["scout", "analyst", "tactician", "persistence"]
PHASE_LABEL = {
    "scout":       "🛰  SCOUT",
    "analyst":     "🧠 ANALYST",
    "tactician":   "⚡ TACTICIAN",
    "persistence": "💾 PERSIST",
}

PENDING = 0
RUNNING = 1
DONE    = 2
SKIP    = 3
ERROR   = 4

_SPINNER = ["⣾", "⣽", "⣻", "⢿", "⡿", "⣟", "⣯", "⣷"]
BAR_W    = 20


# ── Helpers ───────────────────────────────────────────────────────────────────

def write_journal(agent: str, url: str, msg: str) -> None:
    """Append one timestamped entry to agent_journal.jsonl; trim to last N lines."""
    try:
        _JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
        entry = json.dumps({
            "ts": datetime.now(timezone.utc).strftime("%H:%M:%S"),
            "agent": agent,
            "host": short_host(url) if url else "",
            "msg": str(msg)[:160],
        }, ensure_ascii=False)
        existing = []
        if _JOURNAL_PATH.exists():
            existing = _JOURNAL_PATH.read_text(encoding="utf-8").splitlines()
        existing.append(entry)
        if len(existing) > _JOURNAL_MAX_LINES:
            existing = existing[-_JOURNAL_MAX_LINES:]
        _JOURNAL_PATH.write_text("\n".join(existing) + "\n", encoding="utf-8")
    except Exception:
        pass


def write_brain_state(agent: str, threat: int, url: str, log: str) -> None:
    """Atomically write agent state to ui/static/worker_brain_state.json.

    write-to-.tmp then os.replace() prevents the uvicorn Content-Length
    race condition when Streamlit static serving reads the file mid-write.
    """
    try:
        _BRAIN_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({
            "agent": agent,
            "threat_level": max(0, min(5, int(threat))),
            "target_url": str(url)[:120],
            "log": str(log)[:120],
            "timestamp": int(time.time()),
        }, ensure_ascii=False)
        _tmp = _BRAIN_STATE_PATH.with_suffix(".tmp")
        _tmp.write_text(payload, encoding="utf-8")
        os.replace(_tmp, _BRAIN_STATE_PATH)
    except Exception:
        pass


def load_config():
    if _CONFIG_PATH.exists():
        try:
            cfg = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
            urls = [u for u in cfg.get("watch_urls", WATCH_URLS) if u.strip()]
            interval = int(cfg.get("interval_seconds", INTERVAL_SECONDS))
            return urls or WATCH_URLS, max(60, interval)
        except Exception:
            pass
    return WATCH_URLS, INTERVAL_SECONDS


def short_host(url: str) -> str:
    return url.replace("https://", "").replace("http://", "").split("/")[0][:28]


def tc(level: int) -> str:
    if level >= 4: return "bright_red"
    if level >= 3: return "red"
    if level >= 2: return "yellow"
    return "bright_green"


def threat_label(level: int) -> str:
    return {0: "NONE", 1: "LOW", 2: "MODERATE", 3: "HIGH", 4: "CRITICAL", 5: "MAXIMUM"}.get(level, str(level))


def parse_plan_items(plan: str, max_items: int = 5) -> list:
    items = []
    for line in plan.split("\n"):
        line = re.sub(r"^[\s]*[\d]+[.)]\s*", "", line.strip())
        line = re.sub(r"^[-•·*]\s*", "", line)
        if len(line) > 8:
            items.append(line[:110])
        if len(items) >= max_items:
            break
    return items or [plan[:200]]


def _spinner() -> str:
    return _SPINNER[int(time.time() * 8) % len(_SPINNER)]


# ── Live display ──────────────────────────────────────────────────────────────

def _phase_icon(status: int, color: str = "bright_green") -> Text:
    if status == PENDING: return Text("·", style="dim")
    if status == RUNNING: return Text(_spinner(), style="bold bright_cyan")
    if status == DONE:    return Text("✓", style=color)
    if status == SKIP:    return Text("—", style="dim")
    return                       Text("✗", style="bright_red")


def _pi(key: str, phases: dict, result) -> Text:
    """Phase icon for a given key given the current phases dict and result."""
    s = phases[key]
    c = tc(result.get("threat_level", 0)) if (result and s == DONE) else "bright_green"
    return _phase_icon(s, c)


def _render(scan: dict, session: int, starts: dict) -> Group:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d  %H:%M:%S  UTC")

    header = Panel(
        Text.assemble(
            ("⚔  WAR ROOM", "bold bright_cyan"),
            ("  ·  ", "dim"),
            (f"SESSION #{session}", "bright_cyan"),
            ("  ·  ", "dim"),
            (ts, "dim"),
        ),
        border_style="bright_cyan",
        box=box.HORIZONTALS,
        padding=(0, 2),
    )

    # ── Matrix table — one compact row per target ─────────────────────────────
    tbl = Table(
        show_header=True,
        header_style="dim",
        box=None,
        padding=(0, 2),
        show_edge=False,
        expand=False,
    )
    tbl.add_column("TARGET",    no_wrap=True, min_width=26,  style="bright_cyan")
    tbl.add_column("SCOUT",     justify="center", min_width=7)
    tbl.add_column("ANALYST",   justify="center", min_width=8)
    tbl.add_column("TACTICIAN", justify="center", min_width=10)
    tbl.add_column("PERSIST",   justify="center", min_width=8)
    tbl.add_column("TIME",      justify="right",  min_width=6, style="dim")
    tbl.add_column("THREAT",    justify="center", min_width=8)
    tbl.add_column("",          justify="left",   min_width=14)

    active_bars = []

    for url, state in scan.items():
        phases  = state["phases"]
        result  = state.get("result")
        elapsed = time.time() - starts[url]
        e_str   = f"{int(elapsed // 60):02d}:{int(elapsed % 60):02d}"

        if result:
            lvl   = result.get("threat_level", 0)
            col   = tc(lvl)
            t_cell = Text(f"{lvl}/5", style=col)
            if lvl >= THREAT_THRESHOLD:
                st_cell = Text(f"◀ {threat_label(lvl)}", style=f"bold {col}")
            else:
                st_cell = Text(threat_label(lvl), style=col)
        else:
            col     = "bright_cyan"
            t_cell  = Text("—", style="dim")
            st_cell = Text("", style="dim")

        tbl.add_row(
            short_host(url),
            _pi("scout",       phases, result),
            _pi("analyst",     phases, result),
            _pi("tactician",   phases, result),
            _pi("persistence", phases, result),
            e_str,
            t_cell,
            st_cell,
        )

        # Collect active phase progress bar
        for phase in PHASE_ORDER:
            if phases[phase] == RUNNING:
                bar = Text()
                bar.append("  ▸ ", style="dim")
                bar.append(short_host(url), style="bright_cyan")
                bar.append("  ·  ", style="dim")
                bar.append(PHASE_LABEL[phase], style="bold bright_cyan")
                bar.append("  [", style="dim")
                bar.append("█" * (BAR_W // 2), style="bright_cyan")
                bar.append("░" * (BAR_W - BAR_W // 2), style="dim")
                bar.append(f"]  {_spinner()}", style="bright_cyan")
                active_bars.append(bar)
                break

    blocks: list = [header, Text(""), tbl, Text("")]
    blocks.extend(active_bars)
    if active_bars:
        blocks.append(Text(""))
    return Group(*blocks)


# ── Email ─────────────────────────────────────────────────────────────────────

def _build_html(state: dict, session: int) -> str:
    url     = state.get("target_url", "N/A")
    threat  = state.get("threat_level", 0)
    signals = state.get("market_signals", [])
    plan    = state.get("action_plan", "No action plan generated.")
    ts      = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    host    = short_host(url)
    lbl     = threat_label(threat)
    bar     = "🔴" * threat + "⚫" * (5 - threat)

    color_map = {0: "#00ff41", 1: "#00ff41", 2: "#ffaa00", 3: "#ff6600", 4: "#ff2255", 5: "#ff0000"}
    color = color_map.get(threat, "#ff2255")

    signals_html = "".join(
        f'<div class="sig">{re.sub(r"^\\[\\w+\\]\\s*", "", s)}</div>'
        for s in (signals[:6] or ["No specific signals captured."])
    )
    actions_html = "".join(
        f'<div class="act"><span class="n">[{i}]</span>{item}</div>'
        for i, item in enumerate(parse_plan_items(plan), 1)
    )

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#070b14;color:#c8d8e8;font-family:'Courier New',monospace;padding:0}}
.wrap{{max-width:640px;margin:0 auto;padding:24px 12px}}
.hd{{border:1px solid {color};background:#0a0d17;padding:20px 24px;border-bottom:none}}
.hd-t{{color:{color};font-size:12px;letter-spacing:3px;text-transform:uppercase}}
.hd-s{{color:#444;font-size:11px;margin-top:6px}}
.bd{{border:1px solid #1a2534;background:#0a0d17;padding:24px}}
.sec{{color:#4499ff;font-size:10px;letter-spacing:3px;text-transform:uppercase;
      border-bottom:1px solid #1a2534;padding-bottom:8px;margin-bottom:14px;margin-top:24px}}
.sec:first-child{{margin-top:0}}
.t-row{{display:flex;align-items:baseline;gap:14px;margin-bottom:8px}}
.t-num{{font-size:44px;font-weight:bold;line-height:1;color:{color}}}
.t-lbl{{font-size:12px;letter-spacing:3px;color:{color}}}
.t-bar{{font-size:18px;letter-spacing:3px;margin-bottom:10px}}
.tgt{{color:#444;font-size:11px}}
.sig{{padding:6px 0;color:#c8d8e8;font-size:12px;border-bottom:1px solid #0f1825}}
.sig::before{{content:"▸ ";color:#4499ff}}
.act{{padding:7px 12px;margin-bottom:6px;border-left:2px solid {color};background:#060a10;font-size:12px;color:#c8d8e8}}
.n{{color:{color};margin-right:8px;font-weight:bold}}
.btns{{display:flex;gap:12px;margin-top:28px}}
.btn{{display:block;width:50%;padding:13px;text-align:center;text-decoration:none;
      font-family:'Courier New',monospace;font-size:11px;letter-spacing:2px;
      text-transform:uppercase;font-weight:bold}}
.ok{{background:{color};color:#070b14}}
.no{{background:transparent;color:#ff2255;border:2px solid #ff2255}}
.ft{{font-size:10px;color:#222;text-align:center;margin-top:20px;padding-top:16px;border-top:1px solid #111}}
</style></head><body>
<div class="wrap">
  <div class="hd">
    <div class="hd-t">⚔ OmniWarRoom AI — Enterprise Alert</div>
    <div class="hd-s">Session #{session} &nbsp;·&nbsp; {ts}</div>
  </div>
  <div class="bd">
    <div class="sec">Threat Assessment</div>
    <div class="t-row">
      <div class="t-num">{threat}/5</div>
      <div class="t-lbl">{lbl}</div>
    </div>
    <div class="t-bar">{bar}</div>
    <div class="tgt">TARGET: {url}</div>
    <div class="sec">Signals Detected</div>
    {signals_html}
    <div class="sec">Proposed Counterattack</div>
    {actions_html}
    <div class="btns">
      <a href="#" class="btn ok">✓ Approve &amp; Deploy</a>
      <a href="#" class="btn no">✕ Reject &amp; Archive</a>
    </div>
    <div class="ft">Auto-generated by OmniWarRoom AI Swarm — open your War Room dashboard for full context</div>
  </div>
</div>
</body></html>"""


_SMTP_MAP = {
    "gmail.com":    ("smtp.gmail.com",    587),
    "googlemail.com": ("smtp.gmail.com",  587),
    "mail.fr":      ("smtp.mail.fr",      587),
    "laposte.net":  ("smtp.laposte.net",  587),
    "orange.fr":    ("smtp.orange.fr",    587),
    "wanadoo.fr":   ("smtp.orange.fr",    587),
    "free.fr":      ("smtp.free.fr",      587),
    "sfr.fr":       ("smtp.sfr.fr",       587),
    "yahoo.com":    ("smtp.mail.yahoo.com", 587),
    "yahoo.fr":     ("smtp.mail.yahoo.com", 587),
    "outlook.com":  ("smtp.office365.com", 587),
    "hotmail.com":  ("smtp.office365.com", 587),
    "live.com":     ("smtp.office365.com", 587),
    "icloud.com":   ("smtp.mail.me.com",  587),
}


def _smtp_send(sender: str, password: str, recipient: str, msg) -> None:
    domain = sender.split("@")[-1].lower() if "@" in sender else ""
    host, port = _SMTP_MAP.get(
        domain,
        (os.getenv("MAIL_SMTP_SERVER", f"smtp.{domain}"), int(os.getenv("MAIL_SMTP_PORT", 587)))
    )
    with smtplib.SMTP(host, port, timeout=15) as s:
        s.ehlo()
        s.starttls()
        s.login(sender, password)
        s.sendmail(sender, [recipient], msg.as_string())


def _tts_speak(text: str) -> None:
    if not _TTS_AVAILABLE:
        return
    try:
        engine = _pyttsx3.init()
        engine.setProperty("rate", 165)
        engine.setProperty("volume", 0.9)
        engine.say(text)
        engine.runAndWait()
        engine.stop()
    except Exception:
        pass


async def speak_alert(state: dict) -> None:
    """Voice briefing via pyttsx3 — plays on the machine running worker.py."""
    threat = state.get("threat_level", 0)
    host   = short_host(state.get("target_url", "")).replace(".", " ")
    items  = parse_plan_items(state.get("action_plan", ""))
    action = items[0] if items else "Deploy defensive measures immediately."

    text = (
        f"Critical threat detected. Level {threat} out of 5. "
        f"Target: {host}. "
        f"Recommended action: {action}"
    )
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _tts_speak, text)
    if _TTS_AVAILABLE:
        console.print("  [bright_cyan]🔊  Voice briefing delivered[/bright_cyan]")


_TW_BASE = "https://api.triggerware.com"
_TW_HEADERS = lambda key: {"Api-Key": key, "Content-Type": "application/json"}


def _tw_trigger_name(url: str) -> str:
    """Sanitize a URL into a valid Triggerware trigger name."""
    host = short_host(url).replace(".", "_").replace("-", "_")
    return re.sub(r"[^a-z0-9_]", "", host.lower())[:30]


async def triggerware_sync(state: dict) -> None:
    """
    Triggerware integration (docs.triggerware.com):
    1. POST /triggers  — create a persistent monitor for this competitor (idempotent)
    2. POST /triggers/{name}/poll — get deltas since last check
    3. POST /query     — one-shot enrichment query for the current analysis
    Auth: Api-Key header  |  Base: https://api.triggerware.com
    """
    api_key = os.getenv("TRIGGERWARE_API_KEY", "").strip()
    if not api_key:
        return

    url     = state.get("target_url", "")
    threat  = state.get("threat_level", 0)
    color   = tc(threat)
    name    = _tw_trigger_name(url)
    headers = _TW_HEADERS(api_key)

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:

            # ── 1. Create trigger (ignored if already exists) ─────────────────
            await client.post(
                f"{_TW_BASE}/triggers",
                headers=headers,
                json={
                    "name":     name,
                    "query":    f"Monitor pricing, feature, and competitive changes at {url}",
                    "schedule": 300,   # every 5 minutes
                },
            )

            # ── 2. Poll deltas ────────────────────────────────────────────────
            poll = await client.post(
                f"{_TW_BASE}/triggers/{name}/poll",
                headers=headers,
            )
            if poll.status_code == 200:
                delta   = poll.json()
                added   = delta.get("added", [])
                removed = delta.get("deleted", [])
                if added or removed:
                    console.print(
                        f"  [{color}]⚡  Triggerware delta[/{color}]"
                        f"  [dim]→  +{len(added)} / -{len(removed)} rows  ·  trigger '{name}'[/dim]"
                    )
                else:
                    console.print(f"  [dim]⚡  Triggerware: no new delta for '{name}'[/dim]")

            # ── 3. One-shot enrichment query ──────────────────────────────────
            q = await client.post(
                f"{_TW_BASE}/query",
                headers=headers,
                json={"query": (
                    f"What recent market intelligence, pricing changes, or competitive moves "
                    f"are associated with {url} that would affect GTM strategy?"
                )},
            )
            if q.status_code == 200:
                rows = q.json().get("rows", [])
                if rows:
                    console.print(
                        f"  [{color}]⚡  Triggerware insight[/{color}]"
                        f"  [dim]→  {len(rows)} row(s) returned[/dim]"
                    )

    except Exception as e:
        console.print(f"  [red]⚡  Triggerware error: {e}[/red]")


async def send_alert_email(state: dict, session: int) -> None:
    sender   = (os.getenv("MAIL_SENDER") or os.getenv("GMAIL_SENDER", "")).strip()
    password = (os.getenv("MAIL_PASSWORD") or os.getenv("GMAIL_APP_PASSWORD", "")).strip()

    if not sender or not password:
        console.print(
            "  [yellow]⚠  Email skipped — add MAIL_SENDER + MAIL_PASSWORD to .env[/yellow]"
        )
        return

    threat = state.get("threat_level", 0)
    host   = short_host(state.get("target_url", ""))
    color  = tc(threat)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[ACTION REQUIRED] OmniWarRoom — Threat {threat}/5 ({threat_label(threat)}) on {host}"
    msg["From"]    = f"OmniWarRoom AI <{sender}>"
    msg["To"]      = ALERT_RECIPIENT
    msg.attach(MIMEText(_build_html(state, session), "html"))

    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _smtp_send, sender, password, ALERT_RECIPIENT, msg)
        console.print(
            f"  [{color}]📧  ALERT DISPATCHED[/{color}]"
            f"  [dim]→  {ALERT_RECIPIENT}  ·  Threat {threat}/5[/dim]"
        )
    except Exception as e:
        console.print(f"  [red]📧  Email failed: {e}[/red]")


# ── Per-URL execution ─────────────────────────────────────────────────────────

async def run_single(url: str, scan: dict, live: Live, starts: dict, session: int) -> dict:
    initial = {
        "target_url": url, "raw_data": "",
        "market_signals": [], "threat_level": 0, "action_plan": "",
    }
    acc = dict(initial)

    scan[url]["phases"]["scout"] = RUNNING
    write_brain_state("scout", 0, url, f"Scraping {short_host(url)}...")
    write_journal("scout", url, f"scraping {short_host(url)} via Bright Data...")
    live.update(_render(scan, session, starts))

    try:
        async for chunk in war_room_graph.astream(initial, stream_mode="updates"):
            node = next(iter(chunk))
            upd  = chunk[node]
            if upd:
                acc.update(upd)

            if node in PHASE_ORDER:
                # If conditional routing bypassed the "predict next" step, this node
                # arrives still PENDING — show it briefly as RUNNING before marking DONE.
                if scan[url]["phases"][node] == PENDING:
                    scan[url]["phases"][node] = RUNNING
                    live.update(_render(scan, session, starts))
                    await asyncio.sleep(0.5)

                scan[url]["phases"][node] = DONE
                _threat = acc.get("threat_level", 0)

                # Write brain state for completed node and next predicted node
                _node_logs = {
                    "scout":       f"Collection done — {short_host(url)}",
                    "analyst":     f"Analysis done — threat {_threat}/5",
                    "tactician":   f"Strategic plan generated — threat {_threat}/5",
                    "persistence": f"Memory enriched — cycle done",
                }
                _next_logs = {
                    "scout":       "Croisement SERP + Cognee...",
                    "tactician":   "Indexation Cognee...",
                }
                if node in _node_logs:
                    write_brain_state(node, _threat, url, _node_logs[node])
                    write_journal(node, url, _node_logs[node])

                # Predict next only for the two always-linear transitions:
                # scout (0) → analyst (1) and tactician (2) → persistence (3).
                idx = PHASE_ORDER.index(node)
                if idx in (0, 2) and idx + 1 < len(PHASE_ORDER):
                    nxt = PHASE_ORDER[idx + 1]
                    if scan[url]["phases"][nxt] == PENDING:
                        scan[url]["phases"][nxt] = RUNNING
                        if node in _next_logs:
                            write_brain_state(nxt, _threat, url, _next_logs[node])

                # If analyst completed and threat >= threshold, tactician is next
                if node == "analyst" and _threat >= THREAT_THRESHOLD:
                    write_brain_state("tactician", _threat, url, "MENACE CRITIQUE — plan en cours")
                    write_journal("analyst", url, f"threat_level={_threat} — activation Tactician")

            live.update(_render(scan, session, starts))
            await asyncio.sleep(1.2)

        # Any phase still marked RUNNING was skipped by conditional edge
        for p in PHASE_ORDER:
            if scan[url]["phases"][p] == RUNNING:
                scan[url]["phases"][p] = SKIP

        scan[url]["result"] = acc
        _final_threat = acc.get("threat_level", 0)
        write_brain_state("idle", _final_threat, url, f"Cycle done — threat {_final_threat}/5")
        write_journal("idle", url, f"cycle done — threat {_final_threat}/5")
        live.update(_render(scan, session, starts))

    except Exception as e:
        for p in PHASE_ORDER:
            if scan[url]["phases"][p] in (RUNNING, PENDING):
                scan[url]["phases"][p] = ERROR
        scan[url]["result"] = {
            "target_url": url, "threat_level": -1,
            "market_signals": [], "action_plan": "",
        }
        write_brain_state("idle", 0, url, f"Erreur: {str(e)[:80]}")
        live.update(_render(scan, session, starts))
        acc = scan[url]["result"]

    return acc


# ── Session ───────────────────────────────────────────────────────────────────

async def run_session(session: int, watch_urls: list, interval: int) -> None:
    scan   = {
        url: {"phases": {p: PENDING for p in PHASE_ORDER}, "result": None}
        for url in watch_urls
    }
    starts = {url: time.time() for url in watch_urls}
    write_journal("idle", "", f"SESSION #{session} — {len(watch_urls)} cibles")

    with Live(
        _render(scan, session, starts),
        console=console,
        refresh_per_second=4,
        vertical_overflow="visible",
    ) as live:
        results = await asyncio.gather(*[
            run_single(url, scan, live, starts, session)
            for url in watch_urls
        ])

    await asyncio.sleep(0.3)

    # ── Debrief table ─────────────────────────────────────────────────────────
    tbl = Table(
        box=box.SIMPLE_HEAD, show_header=True, header_style="bold dim",
        padding=(0, 2), show_edge=False,
    )
    tbl.add_column("Target",     style="bright_cyan", no_wrap=True, min_width=30)
    tbl.add_column("Threat",     justify="center", min_width=8)
    tbl.add_column("Signals",    justify="center", min_width=8)
    tbl.add_column("Assessment", justify="left",   min_width=12)

    critical, errors = [], []
    for r in results:
        level = r.get("threat_level", -1)
        if level < 0:
            errors.append(r)
            tbl.add_row(short_host(r.get("target_url", "")), "[bright_red]ERR[/bright_red]", "—", "[bright_red]Error[/bright_red]")
            continue
        color = tc(level)
        tbl.add_row(
            short_host(r.get("target_url", "")),
            f"[{color}]{level}/5[/{color}]",
            str(len(r.get("market_signals", []))),
            f"[{color}]{threat_label(level)}[/{color}]",
        )
        if level >= THREAT_THRESHOLD:
            critical.append(r)

    stats = Text.assemble(
        "  Scanned: ", (str(len(results)), "bright_cyan"),
        "   Critical: ", (str(len(critical)), "bright_red" if critical else "bright_green"),
        "   Errors: ",  (str(len(errors)),   "bright_red" if errors   else "dim"),
    )

    console.print()
    console.print(Panel(
        Group(tbl, Text(""), stats),
        title=f"[bold bright_cyan]  SESSION #{session} — DEBRIEF  [/bold bright_cyan]",
        border_style="bright_cyan",
        padding=(0, 2),
        box=box.DOUBLE_EDGE,
    ))

    # ── Dispatch email alerts for critical threats ────────────────────────────
    if critical:
        console.print()
        console.print(Rule(
            f"[bold bright_red]  {len(critical)} CRITICAL THREAT{'S' if len(critical) > 1 else ''}  —  DISPATCHING ALERTS  ",
            style="bright_red",
        ))
        console.print()
        for r in critical:
            await asyncio.sleep(0.4)
            await asyncio.gather(
                send_alert_email(r, session),
                triggerware_sync(r),
            )
            await speak_alert(r)
    else:
        console.print(
            f"\n  [bright_green]✓[/bright_green]  [dim]Market stable — "
            f"no threats above threshold ({THREAT_THRESHOLD}/5)[/dim]\n"
        )


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    watch_urls, interval = load_config()
    target_lines = [Text(f"  ▸ {u}", style="bright_cyan") for u in watch_urls]

    console.print()
    console.print(Panel(
        Group(
            Text(""),
            Text(" ⚔  OMNIWARROOM AI  ⚔", style="bold bright_cyan"),
            Text("    AUTONOMOUS COMPETITIVE INTELLIGENCE SWARM\n", style="dim"),
            Text.assemble(
                ("  TARGETS   ", "dim"), (str(len(watch_urls)), "bright_cyan"),
                ("  ·  INTERVAL  ", "dim"), (f"{interval}s", "bright_cyan"),
                ("  ·  THRESHOLD  ", "dim"), (f"{THREAT_THRESHOLD}/5", "bright_cyan"),
                ("  ·  ALERTS  ", "dim"), (ALERT_RECIPIENT, "bright_cyan"),
            ),
            Text(""),
            *target_lines,
            Text(""),
        ),
        title="[bold bright_cyan]  //  SYSTEM ONLINE  //  [/bold bright_cyan]",
        border_style="bright_cyan",
        box=box.DOUBLE_EDGE,
        padding=(0, 4),
    ))
    console.print()

    session = 1
    while True:
        await run_session(session, watch_urls, interval)
        session += 1
        console.print(
            f"\n  [dim]⏳  Next cycle in [bold white]{interval}s[/bold white]  ·  Ctrl+C to abort[/dim]\n"
        )
        await asyncio.sleep(interval)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n  [bold bright_red]▸ SWARM OFFLINE[/bold bright_red]\n")
