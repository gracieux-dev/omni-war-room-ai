import sys
import os
import io
import html as _html
import signal
import subprocess
import time
import streamlit.components.v1 as _st_comp
_UI_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_UI_DIR))   # root → agents/, tools/
sys.path.insert(0, _UI_DIR)                     # ui/ → brain_loader
from brain_loader import get_brain_html, write_brain_state_file

import asyncio
import json
from pathlib import Path
from datetime import datetime, timezone

import nest_asyncio
nest_asyncio.apply()

import pandas as pd
try:
    import plotly.graph_objects as go
    _PLOTLY = True
except ImportError:
    _PLOTLY = False

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# ── Speechmatics — voice command helper (REST-only, no SDK required) ─────────


def transcribe_audio(audio_bytes: bytes, mime_type: str = "audio/webm") -> str:
    """Submit audio to Speechmatics REST API via httpx — no SDK required."""
    api_key = os.getenv("SPEECHMATICS_API_KEY", "").strip()
    if not api_key:
        return "[SPEECHMATICS_API_KEY not set]"
    try:
        import io as _io
        import httpx as _hx
        import time as _t
        audio_buf = _io.BytesIO(audio_bytes)
        files = {"data_file": ("audio", audio_buf, mime_type or "audio/webm")}
        data  = {"config": '{"type":"transcription","transcription_config":{"language":"en"}}'}
        hdrs  = {"Authorization": f"Bearer {api_key}"}
        base  = "https://asr.api.speechmatics.com/v2"
        with _hx.Client(timeout=30) as cli:
            r = cli.post(f"{base}/jobs/", headers=hdrs, files=files, data=data)
            r.raise_for_status()
            job_id = r.json()["id"]
        with _hx.Client(timeout=30) as cli:
            for _ in range(60):
                _t.sleep(2)
                r2 = cli.get(f"{base}/jobs/{job_id}", headers=hdrs)
                status = r2.json().get("job", {}).get("status", "")
                if status == "done":
                    r3 = cli.get(f"{base}/jobs/{job_id}/transcript?format=txt", headers=hdrs)
                    return r3.text.strip()
                if status in ("rejected", "deleted"):
                    return f"[job {status}]"
        return "[timeout: transcription took too long]"
    except Exception as e:
        return f"[error: {e}]"


def extract_url_from_voice(transcript: str) -> str:
    import re
    t = transcript.lower().strip()
    m = re.search(r'https?://\S+', t)
    if m:
        return m.group()
    m = re.search(r'\b([a-z0-9-]+\.(com|io|ai|so|co|org|net|fr)[\w/.-]*)\b', t)
    if m:
        return f"https://{m.group()}"
    for name, url in {
        "notion":    "https://www.notion.so/pricing",
        "slack":     "https://slack.com/pricing",
        "shopify":   "https://www.shopify.com/pricing",
        "monday":    "https://monday.com/pricing",
        "asana":     "https://asana.com/pricing",
        "linear":    "https://linear.app/pricing",
        "figma":     "https://www.figma.com/pricing",
        "hubspot":   "https://www.hubspot.com/pricing",
        "salesforce":"https://www.salesforce.com/pricing",
    }.items():
        if name in t:
            return url
    return ""

from agents.agent_graph import war_room_graph, THREAT_THRESHOLD

ROOT         = Path(__file__).parent.parent
DATA_DIR     = ROOT / "data"
HISTORY_PATH = DATA_DIR / "market_history.json"
PID_FILE     = DATA_DIR / "worker.pid"
LOG_FILE     = DATA_DIR / "worker.log"
CONFIG_FILE  = DATA_DIR / "worker_config.json"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_URLS = [
    "https://www.notion.so/pricing",
    "https://slack.com/intl/fr-fr/pricing",
    "https://www.shopify.com/fr/tarifs",
]
DEFAULT_INTERVAL = 300

NEON_GREEN  = "#00FF41"
NEON_RED    = "#FF1744"
NEON_CYAN   = "#00E5FF"
NEON_AMBER  = "#FFB300"

# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="OmniWarRoom AI",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ══════════════════════════════════════════════════════════════════════════════
# CSS
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700;900&family=Fira+Code:wght@400;500;600&family=Rajdhani:wght@500;600;700&display=swap');

:root {
  --bg:       #0E1117;
  --bg-deep:  #080B12;
  --bg-card:  #0D1421;
  --green:    #00FF41;
  --red:      #FF1744;
  --cyan:     #00E5FF;
  --amber:    #FFB300;
  --text:     #C8D6F0;
  --muted:    #3D5070;
  --dim:      #1A2235;
  --border:   #111827;
  --border-lg:#1A2840;
  --font-ui:  'Rajdhani','Inter',sans-serif;
  --font-mono:'Fira Code','Courier New',monospace;
}

/* ── Animations ── */
@keyframes pulse-green {
  0%,100%{ opacity:1; box-shadow:0 0 6px var(--green),0 0 14px var(--green); }
  50%    { opacity:.6; box-shadow:0 0 20px var(--green),0 0 50px var(--green),0 0 90px rgba(0,255,65,.12); }
}
@keyframes pulse-red {
  0%,100%{ box-shadow:0 0 6px var(--red),0 0 14px var(--red); }
  50%    { box-shadow:0 0 24px var(--red),0 0 55px var(--red),0 0 100px rgba(255,23,68,.18); }
}
@keyframes pulse-cyan {
  0%,100%{ box-shadow:0 0 6px var(--cyan),0 0 14px var(--cyan); }
  50%    { box-shadow:0 0 18px var(--cyan),0 0 44px var(--cyan); }
}
@keyframes fadeInUp {
  from{ opacity:0; transform:translateY(14px); }
  to  { opacity:1; transform:translateY(0); }
}
@keyframes scan {
  0%  { left:-80%; }
  100%{ left:120%; }
}
@keyframes borderPulse {
  0%,100%{ border-color:rgba(0,229,255,.2); }
  50%    { border-color:rgba(0,229,255,.7); }
}
@keyframes terminalBlink {
  0%,100%{ opacity:1; }
  50%    { opacity:0; }
}

/* ── Base ── */
html,body,[class*="css"],.stApp{
  font-family:var(--font-ui) !important;
  background-color:var(--bg) !important;
  color:var(--text) !important;
}
::-webkit-scrollbar{ width:4px; height:4px; }
::-webkit-scrollbar-track{ background:var(--bg-deep); }
::-webkit-scrollbar-thumb{ background:var(--cyan); border-radius:2px; }

.main .block-container{
  padding-top:1.2rem !important;
  padding-left:2rem !important;
  padding-right:2rem !important;
  max-width:100% !important;
}

/* ── Sidebar ── */
section[data-testid="stSidebar"]{
  background:linear-gradient(180deg,#060911 0%,var(--bg) 100%) !important;
  border-right:1px solid rgba(0,229,255,.07) !important;
}

/* ── Tabs ── */
.stTabs [data-baseweb="tab-list"]{
  background:transparent !important;
  border-bottom:1px solid var(--dim) !important;
  gap:0 !important;
}
.stTabs [data-baseweb="tab"]{
  background:transparent !important;
  color:var(--muted) !important;
  font-family:var(--font-ui) !important;
  font-size:.76rem !important;
  font-weight:700 !important;
  letter-spacing:.16em !important;
  text-transform:uppercase !important;
  padding:12px 28px !important;
  border:none !important;
  border-bottom:2px solid transparent !important;
  transition:all .2s !important;
}
.stTabs [aria-selected="true"]{
  color:var(--cyan) !important;
  border-bottom:2px solid var(--cyan) !important;
  text-shadow:0 0 14px var(--cyan) !important;
  background:rgba(0,229,255,.03) !important;
}

/* ── Buttons ── */
.stButton > button{
  font-family:var(--font-ui) !important;
  font-size:.78rem !important;
  font-weight:700 !important;
  letter-spacing:.14em !important;
  text-transform:uppercase !important;
  border-radius:3px !important;
  transition:all .2s !important;
}
.stButton > button[kind="primary"]{
  background:transparent !important;
  color:var(--cyan) !important;
  border:1px solid var(--cyan) !important;
  box-shadow:0 0 14px rgba(0,229,255,.15),inset 0 0 14px rgba(0,229,255,.04) !important;
}
.stButton > button[kind="primary"]:hover{
  background:rgba(0,229,255,.08) !important;
  box-shadow:0 0 28px rgba(0,229,255,.35),inset 0 0 22px rgba(0,229,255,.08) !important;
}
.stButton > button:not([kind="primary"]){
  background:transparent !important;
  color:var(--muted) !important;
  border:1px solid var(--border-lg) !important;
}
.stButton > button:not([kind="primary"]):hover{
  color:var(--text) !important;
  border-color:var(--muted) !important;
}
.stButton > button:disabled{ opacity:.22 !important; }

/* ── Inputs ── */
div[data-testid="stTextInput"] input,
div[data-testid="stTextArea"] textarea,
div[data-testid="stNumberInput"] input{
  background:#060911 !important;
  border:1px solid var(--border-lg) !important;
  color:var(--cyan) !important;
  font-family:var(--font-mono) !important;
  font-size:.82rem !important;
  border-radius:3px !important;
  caret-color:var(--cyan) !important;
}
div[data-testid="stTextInput"] input:focus,
div[data-testid="stTextArea"] textarea:focus,
div[data-testid="stNumberInput"] input:focus{
  border-color:var(--cyan) !important;
  box-shadow:0 0 14px rgba(0,229,255,.2) !important;
  outline:none !important;
}
label[data-testid="stWidgetLabel"] p{
  color:var(--muted) !important;
  font-family:var(--font-ui) !important;
  font-size:.7rem !important;
  letter-spacing:.1em !important;
  text-transform:uppercase !important;
}

/* ── Glassmorphism metrics ── */
div[data-testid="metric-container"]{
  background:rgba(13,20,33,.85) !important;
  backdrop-filter:blur(12px) !important;
  -webkit-backdrop-filter:blur(12px) !important;
  border:1px solid rgba(0,229,255,.14) !important;
  border-radius:6px !important;
  padding:20px !important;
  position:relative !important;
  overflow:hidden !important;
  box-shadow:0 4px 30px rgba(0,229,255,.05),inset 0 1px 0 rgba(255,255,255,.04) !important;
}
div[data-testid="metric-container"]::before{
  content:'';
  position:absolute;
  top:0;left:0;right:0;height:1px;
  background:linear-gradient(90deg,transparent,var(--cyan),transparent);
  opacity:.5;
}
div[data-testid="metric-container"] [data-testid="stMetricValue"]{
  color:var(--cyan) !important;
  font-family:var(--font-mono) !important;
  font-size:2rem !important;
  font-weight:500 !important;
  text-shadow:0 0 22px rgba(0,229,255,.45) !important;
}
div[data-testid="metric-container"] [data-testid="stMetricLabel"]{
  color:var(--muted) !important;
  font-family:var(--font-ui) !important;
  font-size:.68rem !important;
  letter-spacing:.14em !important;
  text-transform:uppercase !important;
}

/* ── Dataframe ── */
[data-testid="stDataFrame"]{
  border:1px solid var(--border-lg) !important;
  border-radius:4px !important;
}

/* ── Terminal / code ── */
[data-testid="stCode"] pre,
.stCode pre{
  background:#020408 !important;
  border:1px solid rgba(0,255,65,.2) !important;
  border-radius:4px !important;
  font-family:var(--font-mono) !important;
  font-size:.76rem !important;
  line-height:1.7 !important;
  color:var(--green) !important;
  text-shadow:0 0 8px rgba(0,255,65,.28) !important;
  box-shadow:inset 0 0 50px rgba(0,255,65,.02),0 0 20px rgba(0,255,65,.04) !important;
}

/* ── st.status ── */
div[data-testid="stStatusContainer"]{
  background:rgba(6,9,17,.95) !important;
  border:1px solid rgba(0,229,255,.25) !important;
  border-radius:4px !important;
}
div[data-testid="stStatusContainer"] summary{
  font-family:var(--font-mono) !important;
  font-size:.8rem !important;
  color:var(--cyan) !important;
}

/* ── Spinner ── */
.stSpinner > div{ border-top-color:var(--cyan) !important; }

/* ── Streamlit alerts ── */
div[data-testid="stAlert"]{ border-radius:4px !important; font-family:var(--font-ui) !important; }

/* ── Caption / misc ── */
.stCaption,small{ color:var(--muted) !important; font-family:var(--font-ui) !important; }
hr{ border-color:var(--dim) !important; margin:20px 0 !important; }

/* ═══════════════════════════════
   CUSTOM COMPONENT CLASSES
═══════════════════════════════ */

/* Hero header */
.hero{
  background:linear-gradient(135deg,#06090F 0%,#0A1020 40%,#060B18 100%);
  border:1px solid rgba(0,229,255,.1);
  border-radius:6px;
  padding:28px 36px;
  margin-bottom:22px;
  position:relative;
  overflow:hidden;
}
.hero::before{
  content:'';
  position:absolute;
  top:0;left:-80%;
  width:50%;height:100%;
  background:linear-gradient(90deg,transparent,rgba(0,229,255,.04),transparent);
  animation:scan 6s linear infinite;
}
.hero-title{
  font-family:var(--font-ui);
  font-size:2.2rem;
  font-weight:700;
  letter-spacing:.22em;
  color:#ffffff;
  text-shadow:0 0 30px rgba(0,229,255,.3),0 2px 20px rgba(0,0,0,.5);
  margin:0 0 4px 0;
  line-height:1;
}
.hero-title em{ color:var(--red); font-style:normal; text-shadow:0 0 20px rgba(255,23,68,.5); }
.hero-subtitle{
  font-family:var(--font-mono);
  font-size:.78rem;
  color:var(--muted);
  letter-spacing:.12em;
  margin:6px 0 18px 0;
}
.hero-status{
  display:inline-flex;
  align-items:center;
  gap:10px;
  background:rgba(0,255,65,.05);
  border:1px solid rgba(0,255,65,.2);
  border-radius:3px;
  padding:7px 16px;
  font-family:var(--font-mono);
  font-size:.74rem;
  color:var(--green);
  text-shadow:0 0 8px rgba(0,255,65,.3);
}
.hero-status.alert{
  background:rgba(255,23,68,.06);
  border-color:rgba(255,23,68,.3);
  color:var(--red);
  text-shadow:0 0 8px rgba(255,23,68,.4);
}
.status-dot{
  width:8px;height:8px;
  border-radius:50%;
  background:var(--green);
  animation:pulse-green 2s ease-in-out infinite;
}
.status-dot.red{
  background:var(--red);
  animation:pulse-red 1.4s ease-in-out infinite;
}

.section-label{
  font-family:var(--font-ui);
  font-size:.67rem;
  font-weight:700;
  letter-spacing:.2em;
  text-transform:uppercase;
  color:var(--muted);
  border-bottom:1px solid var(--dim);
  padding-bottom:8px;
  margin-bottom:20px;
}

/* Input form frame */
.scan-frame{
  background:rgba(8,11,18,.8);
  border:1px solid rgba(0,229,255,.12);
  border-radius:5px;
  padding:20px 24px;
  margin-bottom:4px;
}

/* Agent cards */
.agent-card{
  background:var(--bg-card);
  border:1px solid var(--dim);
  border-radius:4px;
  padding:20px 20px 20px 24px;
  min-height:220px;
  position:relative;
  overflow:hidden;
}
.agent-card::before{
  content:'';
  position:absolute;
  left:0;top:0;bottom:0;
  width:3px;
  background:var(--muted);
  transition:all .3s;
}
.agent-card.running::before{ background:var(--cyan); box-shadow:0 0 14px var(--cyan); animation:pulse-cyan 1.4s infinite; }
.agent-card.running        { border-color:rgba(0,229,255,.22); animation:borderPulse 2s infinite; }
.agent-card.done-g::before { background:var(--green); box-shadow:0 0 12px var(--green); }
.agent-card.done-g         { border-color:rgba(0,255,65,.18); }
.agent-card.done-r::before { background:var(--red); box-shadow:0 0 12px var(--red); }
.agent-card.done-r         { border-color:rgba(255,23,68,.18); }
.agent-card.engaged::before{ background:var(--red); animation:pulse-red 1s infinite; }
.agent-card.engaged        { border-color:rgba(255,23,68,.35); }

.agent-name{ font-family:var(--font-ui); font-size:.68rem; font-weight:700; letter-spacing:.18em; text-transform:uppercase; color:var(--muted); margin:0 0 12px 0; }
.agent-body{ font-size:.87rem; color:#8A9BBF; line-height:1.7; }
.agent-body strong{ color:var(--text); }
.agent-body ul{ padding-left:14px; margin:8px 0 0 0; }
.agent-body li{ margin-bottom:4px; }

.badge{
  display:inline-flex;align-items:center;gap:5px;
  padding:3px 11px;border-radius:2px;
  font-family:var(--font-mono);font-size:.67rem;font-weight:500;letter-spacing:.08em;
  margin-bottom:10px;
}
.badge-idle   { background:rgba(26,34,53,.9); color:var(--muted); border:1px solid var(--dim); }
.badge-run    { background:rgba(0,229,255,.07); color:var(--cyan); border:1px solid rgba(0,229,255,.35); animation:pulse-cyan 1.5s infinite; }
.badge-ok     { background:rgba(0,255,65,.05); color:var(--green); border:1px solid rgba(0,255,65,.32); }
.badge-alert  { background:rgba(255,23,68,.07); color:var(--red); border:1px solid rgba(255,23,68,.38); animation:pulse-red 1.2s infinite; }
.badge-done   { background:rgba(0,255,65,.05); color:var(--green); border:1px solid rgba(0,255,65,.28); }

.threat-num{ font-family:var(--font-mono); font-size:2.8rem; font-weight:500; line-height:1; }
.threat-denom{ font-family:var(--font-mono); font-size:1rem; color:var(--muted); }
.c-green{ color:var(--green); text-shadow:0 0 22px rgba(0,255,65,.5); }
.c-amber{ color:var(--amber); text-shadow:0 0 22px rgba(255,179,0,.5); }
.c-red  { color:var(--red); text-shadow:0 0 22px rgba(255,23,68,.5); animation:pulse-red 2s infinite; }

/* Terminal */
.terminal-wrap{
  background:#020408;
  border:1px solid rgba(0,255,65,.22);
  border-radius:4px;
  padding:16px 20px;
  font-family:var(--font-mono);
  font-size:.76rem;
  line-height:1.72;
  color:var(--green);
  text-shadow:0 0 7px rgba(0,255,65,.25);
  box-shadow:inset 0 0 60px rgba(0,255,65,.02),0 0 20px rgba(0,255,65,.04);
  max-height:340px;
  overflow-y:auto;
  white-space:pre-wrap;
  animation:fadeInUp .3s ease-out;
}
.terminal-wrap .t-cyan  { color:var(--cyan); text-shadow:0 0 8px rgba(0,229,255,.3); }
.terminal-wrap .t-red   { color:var(--red); text-shadow:0 0 8px rgba(255,23,68,.4); }
.terminal-wrap .t-muted { color:#2A3A50; }
.terminal-cursor{ display:inline-block; width:7px; height:1em; background:var(--green); vertical-align:text-bottom; animation:terminalBlink .8s step-end infinite; margin-left:2px; }

/* Alert / stable result cards */
.result-critical{
  background:linear-gradient(135deg,rgba(18,4,4,.96),rgba(30,7,7,.96));
  border:1px solid rgba(255,23,68,.32);
  border-left:3px solid var(--red);
  border-radius:4px;
  padding:20px 24px;
  margin-bottom:14px;
  animation:fadeInUp .35s ease-out;
  box-shadow:0 4px 35px rgba(255,23,68,.07);
}
.result-critical h4{ color:var(--red); margin:0 0 10px 0; font-size:.76rem; font-weight:700; letter-spacing:.12em; text-transform:uppercase; text-shadow:0 0 12px rgba(255,23,68,.5); }
.result-critical p { color:#C09898; margin:3px 0; font-size:.84rem; }

.result-stable{
  background:rgba(0,255,65,.025);
  border:1px solid rgba(0,255,65,.18);
  border-left:3px solid var(--green);
  border-radius:4px;
  padding:20px 24px;
  margin-top:18px;
  animation:fadeInUp .35s ease-out;
}
.result-stable h3{ color:var(--green); margin:0 0 6px 0; font-size:1rem; text-shadow:0 0 14px rgba(0,255,65,.4); }
.result-stable p { color:#80A888; font-size:.87rem; }

.roi-box{
  background:rgba(0,229,255,.025);
  border:1px solid rgba(0,229,255,.16);
  border-radius:4px;
  padding:16px 20px;
  margin-top:14px;
  animation:fadeInUp .4s ease-out .1s both;
}
.roi-box h4{ color:var(--cyan); margin:0 0 8px 0; font-size:.7rem; letter-spacing:.14em; text-transform:uppercase; }
.roi-box p { color:#90C0D0; font-size:.85rem; margin:3px 0; }

/* Sidebar */
.sb-logo{ font-family:var(--font-ui); font-size:1.1rem; font-weight:700; letter-spacing:.2em; color:#fff; text-shadow:0 0 16px rgba(0,229,255,.28); }
.sb-logo em{ color:var(--red); font-style:normal; }
.sb-tag{ font-family:var(--font-mono); font-size:.58rem; color:var(--muted); letter-spacing:.1em; margin-bottom:22px; }
.sb-sect{ font-family:var(--font-ui); font-size:.63rem; font-weight:700; letter-spacing:.18em; text-transform:uppercase; color:var(--dim); margin:18px 0 10px 0; padding-bottom:5px; border-bottom:1px solid var(--dim); }
.sb-row{ display:flex; align-items:center; justify-content:space-between; font-family:var(--font-ui); font-size:.82rem; color:var(--muted); margin-bottom:8px; }
.sb-val{ font-family:var(--font-mono); font-size:.72rem; color:var(--cyan); }
.sb-val.g{ color:var(--green); } .sb-val.r{ color:var(--red); }

/* Worker tab */
.badge-won { display:inline-flex;align-items:center;gap:8px;background:rgba(0,255,65,.07);color:var(--green);border:1px solid rgba(0,255,65,.35);border-radius:3px;padding:6px 18px;font-family:var(--font-mono);font-size:.82rem;animation:pulse-green 2.2s ease-in-out infinite; }
.badge-woff{ display:inline-flex;align-items:center;gap:8px;background:rgba(26,34,53,.9);color:var(--muted);border:1px solid var(--border-lg);border-radius:3px;padding:6px 18px;font-family:var(--font-mono);font-size:.82rem; }
.cfg-label{ font-family:var(--font-ui);font-size:.67rem;font-weight:700;letter-spacing:.15em;text-transform:uppercase;color:var(--muted);margin-bottom:6px;display:block; }
.cfg-hint { font-size:.7rem;color:var(--dim);margin-bottom:10px; }

/* Voice command */
.voice-frame{
  background:rgba(0,229,255,.03);
  border:1px solid rgba(0,229,255,.14);
  border-radius:5px;
  padding:14px 20px;
  margin-top:10px;
}
.voice-frame .st-emotion-cache-nahz7x{ color:var(--cyan) !important; }

/* Partner badge */
.partner-row{
  display:flex; align-items:center; justify-content:space-between;
  font-family:var(--font-ui); font-size:.78rem; color:var(--muted); margin-bottom:7px;
}
.partner-on { font-family:var(--font-mono); font-size:.66rem; color:var(--green); }
.partner-off{ font-family:var(--font-mono); font-size:.66rem; color:var(--dim); }

/* Chart container */
.chart-frame{
  background:rgba(8,11,18,.6);
  border:1px solid var(--border-lg);
  border-radius:5px;
  padding:4px;
  margin-bottom:4px;
}

/* History alert card */
.hist-card{
  background:linear-gradient(135deg,rgba(16,4,4,.96),rgba(26,6,6,.96));
  border:1px solid rgba(255,23,68,.28);
  border-left:3px solid var(--red);
  border-radius:4px;
  padding:16px 20px;
  margin-bottom:12px;
  animation:fadeInUp .3s ease-out;
}
.hist-card h4{ color:var(--red); margin:0 0 8px 0; font-size:.75rem; letter-spacing:.1em; text-transform:uppercase; }
.hist-card p { color:#B89090; font-size:.82rem; margin:2px 0; }

/* ── Worker tab ──────────────────────────────────────────────── */
.w-hdr{
  display:flex;justify-content:space-between;align-items:center;
  background:#03050a;border:1px solid #0d1f38;border-radius:4px;
  padding:9px 16px;margin-bottom:10px;
}
.w-hdr-title{
  font-family:var(--font-mono);font-size:.78rem;color:#2a4060;letter-spacing:.08em;
}
.w-hdr-badges{display:flex;gap:7px;align-items:center;flex-wrap:wrap;}
.badge-won{
  background:rgba(0,255,65,.08);color:#00ff41;
  border:1px solid rgba(0,255,65,.25);padding:3px 10px;border-radius:2px;
  font-size:.62rem;letter-spacing:.15em;font-family:var(--font-mono);
}
.badge-woff{
  background:rgba(61,80,112,.06);color:#2a4060;
  border:1px solid #0f1825;padding:3px 10px;border-radius:2px;
  font-size:.62rem;letter-spacing:.15em;font-family:var(--font-mono);
}
.badge-scan{
  background:rgba(0,229,255,.06);color:#00e5ff;
  border:1px solid rgba(0,229,255,.18);padding:3px 10px;border-radius:2px;
  font-size:.62rem;letter-spacing:.15em;font-family:var(--font-mono);
}
.badge-threat-hdr{
  background:rgba(255,23,68,.1);color:#ff1744;
  border:1px solid rgba(255,23,68,.28);padding:3px 10px;border-radius:2px;
  font-size:.62rem;letter-spacing:.15em;font-family:var(--font-mono);
  animation:pulse-red 1.4s infinite;
}
.w-panel{
  background:#03050a;border:1px solid #0d1f38;border-radius:4px;padding:13px 15px;
}
.w-panel-title{
  font-size:.64rem;letter-spacing:.25em;color:#2a4060;text-transform:uppercase;
  margin-bottom:10px;display:flex;justify-content:space-between;align-items:center;
  font-family:var(--font-mono);border-bottom:1px solid #060c18;padding-bottom:7px;
}
.w-panel-title span{color:#0d1f38;font-size:.6rem;}
.w-target-row{
  display:flex;align-items:center;gap:8px;padding:7px 0;
  border-bottom:1px solid #06090f;
}
.w-target-row:last-child{border-bottom:none;}
.w-host{
  font-family:var(--font-mono);font-size:.72rem;color:#2a4060;
  flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0;
}
.w-host .ck{color:#00ff41;margin-right:5px;font-size:.7rem;}
.ph{
  padding:2px 7px;border-radius:2px;font-size:.58rem;letter-spacing:.1em;
  font-family:var(--font-mono);text-transform:uppercase;min-width:70px;text-align:center;
  white-space:nowrap;
}
.ph-scout    {background:rgba(0,255,65,.09);  color:#00ff41; border:1px solid rgba(0,255,65,.22);}
.ph-analyst  {background:rgba(139,92,246,.09);color:#8b5cf6; border:1px solid rgba(139,92,246,.22);}
.ph-tactician{background:rgba(255,23,68,.09); color:#ff1744; border:1px solid rgba(255,23,68,.22);animation:pulse-red 1.2s infinite;}
.ph-persist  {background:rgba(16,185,129,.09);color:#10b981; border:1px solid rgba(16,185,129,.22);}
.ph-idle     {background:rgba(13,31,56,.3);   color:#1a2840; border:1px solid #0a1628;}
.w-bar{
  height:2px;border-radius:1px;background:#060c18;
  flex:1;min-width:50px;overflow:hidden;
}
.w-bar-fill{height:100%;border-radius:1px;transition:width .4s;}
.w-elapsed{
  font-family:var(--font-mono);font-size:.6rem;color:#1a2840;
  min-width:30px;text-align:right;
}
/* Journal */
.w-journal{
  background:#03050a;border:1px solid #0d1f38;border-radius:4px;
  padding:11px 13px;max-height:210px;overflow-y:auto;
  scrollbar-width:thin;scrollbar-color:#1a2840 transparent;
}
.w-journal::-webkit-scrollbar{width:3px;}
.w-journal::-webkit-scrollbar-thumb{background:#1a2840;}
.wj-line{font-family:var(--font-mono);font-size:.68rem;line-height:1.8;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.wj-ts{color:#1a2840;}
.wj-scout    {color:#00ff41;}
.wj-analyst  {color:#8b5cf6;}
.wj-tactician{color:#ff1744;}
.wj-persist  {color:#10b981;}
.wj-dim      {color:#2a4060;}
/* Alerts */
.w-alerts{
  background:#03050a;border:1px solid #0d1f38;border-radius:4px;
  padding:11px 13px;
  max-height:188px;overflow-y:auto;
}
.wa-item{
  display:flex;align-items:flex-start;gap:8px;padding:5px 0;
  border-bottom:1px solid #06090f;
}
.wa-item:last-child{border-bottom:none;}
.wa-dot{width:6px;height:6px;border-radius:50%;flex-shrink:0;margin-top:5px;}
.wa-text{font-family:var(--font-mono);font-size:.69rem;color:#2a4060;line-height:1.5;}
/* Footer bar */
.w-foot{
  display:flex;justify-content:space-between;align-items:center;
  border-top:1px solid #0d1f38;margin-top:10px;padding-top:8px;
}
.w-foot-brand{font-family:var(--font-mono);font-size:.58rem;color:#0d1f38;letter-spacing:.12em;}
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# PROCESS MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

def is_worker_running() -> bool:
    if not PID_FILE.exists():
        return False
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        PID_FILE.unlink(missing_ok=True)
        return False


def start_worker(watch_urls: list, interval: int) -> None:
    if is_worker_running():
        return
    CONFIG_FILE.write_text(
        json.dumps({"watch_urls": watch_urls, "interval_seconds": interval}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    log_fp = open(LOG_FILE, "w", encoding="utf-8", buffering=1)
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "worker.py")],
        stdout=log_fp, stderr=log_fp,
        cwd=str(ROOT), env=env, creationflags=flags,
    )
    PID_FILE.write_text(str(proc.pid), encoding="utf-8")


def stop_worker() -> None:
    if not PID_FILE.exists():
        return
    try:
        pid = int(PID_FILE.read_text().strip())
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
        else:
            os.kill(pid, signal.SIGTERM)
    except Exception:
        pass
    PID_FILE.unlink(missing_ok=True)


def read_worker_log(tail: int = 40) -> str:
    if not LOG_FILE.exists():
        return ""
    try:
        lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-tail:])
    except OSError:
        return ""


# ══════════════════════════════════════════════════════════════════════════════
# DATA HELPERS
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=10)
def load_history() -> list:
    if not HISTORY_PATH.exists():
        return []
    try:
        return json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def load_worker_config() -> tuple:
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            return cfg.get("watch_urls", DEFAULT_URLS), cfg.get("interval_seconds", DEFAULT_INTERVAL)
        except Exception:
            pass
    return DEFAULT_URLS, DEFAULT_INTERVAL


def fmt_ts(raw: str) -> str:
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return raw


def threat_css(level: int) -> str:
    if level >= THREAT_THRESHOLD:
        return "c-red"
    if level >= 2:
        return "c-amber"
    return "c-green"


def build_exec_log(result: dict, elapsed: float) -> str:
    url     = _html.escape(result.get("target_url", ""))
    raw_len = len(result.get("raw_data", ""))
    threat  = result.get("threat_level", 0)
    signals = result.get("market_signals", [])
    plan    = result.get("action_plan", "")

    def ts(frac): return f"{elapsed * frac:06.3f}s"

    lines = [
        f'<span class="t-muted">// OmniWarRoom AI — Execution Trace</span>',
        f'<span class="t-muted">// {datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}</span>',
        "",
        f'[{ts(.03)}] <span class="t-cyan">INIT</span>  Scout agent loaded',
        f'[{ts(.06)}] <span class="t-cyan">CONN</span>  Connecting to Bright Data MCP...',
        f'[{ts(.09)}] <span class="t-cyan">LOCK</span>  Target acquired: {url}',
        f'[{ts(.45)}] <span class="t-cyan">FETCH</span> HTTP 200 OK — {raw_len:,} chars extracted',
        f'[{ts(.50)}] <span class="t-cyan">PIPE</span>  Raw data forwarded to Analyst node',
        f'[{ts(.54)}] <span class="t-cyan">SERP</span>  Dispatching sentiment query...',
        f'[{ts(.75)}] <span class="t-cyan">LLM</span>   Groq LLaMA-3.3-70B processing...',
        f'[{ts(.82)}] <span class="t-cyan">SCAN</span>  {len(signals)} market signal(s) extracted',
        f'[{ts(.85)}]  {"<span class=\"t-red\">WARN</span>" if threat >= THREAT_THRESHOLD else "<span>INFO</span>"}  Threat assessment: <span class="{"t-red" if threat >= THREAT_THRESHOLD else ""}"> {threat}/5</span>',
    ]

    if threat >= THREAT_THRESHOLD:
        lines += [
            f'[{ts(.87)}] <span class="t-red">CRIT</span>  THRESHOLD BREACHED — Tactician engaged',
            f'[{ts(.94)}] <span class="t-red">PLAN</span>  Counter-strike plan generated',
            f'[{ts(.96)}] <span class="t-red">ALRT</span>  Enterprise alert dispatched',
        ]

    lines += [
        f'[{ts(.98)}] <span class="t-cyan">SAVE</span>  Persisting to market_history.json',
        f'[{ts(1.0)}] <span class="t-cyan">DONE</span>  Session complete. Elapsed: {elapsed:.2f}s',
        f'<span class="t-muted">{"─" * 52}</span>',
        f'<span class="terminal-cursor"></span>',
    ]
    return "\n".join(lines)


def make_threat_chart(history: list):
    if not _PLOTLY:
        return None
    if not history:
        return None

    rows = []
    for e in history:
        try:
            ts = datetime.fromisoformat(e.get("timestamp", "").replace("Z", "+00:00"))
        except ValueError:
            continue
        host = e.get("target_url", "").replace("https://", "").split("/")[0]
        rows.append({"ts": ts, "threat": e.get("threat_level", 0), "host": host})

    if not rows:
        return None

    df = pd.DataFrame(rows).sort_values("ts")
    hosts = df["host"].unique()
    palette = [NEON_CYAN, NEON_GREEN, NEON_AMBER, "#BF5FFF", "#FF9100"]

    def _hex_rgba(hex_color: str, alpha: float) -> str:
        h = hex_color.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f"rgba({r},{g},{b},{alpha})"

    fig = go.Figure()

    # ── Background threat zones ────────────────────────────────────────────────
    fig.add_hrect(y0=0,   y1=2,   fillcolor="rgba(0,255,65,.03)",   line_width=0, layer="below")
    fig.add_hrect(y0=2,   y1=3,   fillcolor="rgba(255,179,0,.07)",  line_width=0, layer="below")
    fig.add_hrect(y0=3,   y1=5.4, fillcolor="rgba(255,23,68,.08)",  line_width=0, layer="below")

    # ── Zone labels ────────────────────────────────────────────────────────────
    for y, lbl, col in [
        (1.0, "SAFE",          "rgba(0,255,65,.22)"),
        (2.5, "MODERATE",      "rgba(255,179,0,.22)"),
        (4.2, "CRITICAL ZONE", "rgba(255,23,68,.22)"),
    ]:
        fig.add_annotation(
            x=1, xref="paper", y=y, yref="y",
            text=lbl,
            font=dict(color=col, size=9, family="Fira Code, monospace"),
            showarrow=False, xanchor="right",
        )

    for i, host in enumerate(hosts):
        sub    = df[df["host"] == host]
        color  = palette[i % len(palette)]
        glow   = _hex_rgba(color, 0.18)
        fill   = _hex_rgba(color, 0.05)
        threats = sub["threat"].tolist()

        # ── Glow layer (wide, transparent, behind) ────────────────────────────
        fig.add_trace(go.Scatter(
            x=sub["ts"], y=sub["threat"],
            mode="lines",
            showlegend=False,
            line=dict(color=glow, width=12),
            hoverinfo="skip",
        ))

        # ── Area fill ─────────────────────────────────────────────────────────
        fig.add_trace(go.Scatter(
            x=sub["ts"], y=sub["threat"],
            mode="none",
            showlegend=False,
            fill="tozeroy",
            fillcolor=fill,
            hoverinfo="skip",
        ))

        # ── Main line + markers ───────────────────────────────────────────────
        m_colors  = [NEON_RED if t >= THREAT_THRESHOLD else color for t in threats]
        m_sizes   = [11 if t >= THREAT_THRESHOLD else 7 for t in threats]
        m_symbols = ["diamond" if t >= THREAT_THRESHOLD else "circle" for t in threats]

        fig.add_trace(go.Scatter(
            x=sub["ts"], y=sub["threat"],
            mode="lines+markers",
            name=host,
            line=dict(color=color, width=2),
            marker=dict(
                color=m_colors,
                size=m_sizes,
                symbol=m_symbols,
                line=dict(color=color, width=1),
            ),
            hovertemplate="<b>%{fullData.name}</b><br>%{x}<br>Threat: %{y}/5<extra></extra>",
        ))

    # ── Threshold line ─────────────────────────────────────────────────────────
    fig.add_hline(
        y=THREAT_THRESHOLD, line_dash="dash", line_color=NEON_RED,
        line_width=1.5, opacity=0.75,
        annotation_text=f" ⚠ ALERT THRESHOLD ({THREAT_THRESHOLD}/5)",
        annotation_font_color=NEON_RED, annotation_font_size=10,
        annotation_position="top left",
    )

    fig.update_layout(
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Fira Code, monospace", color="#3D5070", size=11),
        title=None,
        margin=dict(l=10, r=20, t=16, b=10),
        legend=dict(
            bgcolor="rgba(8,11,18,.7)",
            bordercolor="rgba(0,229,255,.15)",
            borderwidth=1,
            font=dict(color="#C8D6F0", size=11),
        ),
        xaxis=dict(
            gridcolor="#111827", linecolor="#1A2840",
            tickcolor="#1A2840", tickfont=dict(color="#3D5070"),
            showgrid=True,
        ),
        yaxis=dict(
            gridcolor="#111827", linecolor="#1A2840",
            tickcolor="#1A2840", tickfont=dict(color="#3D5070"),
            range=[-0.2, 5.4], dtick=1,
            showgrid=True,
            title=dict(text="Threat Level", font=dict(color="#3D5070", size=11)),
        ),
        hoverlabel=dict(
            bgcolor="#0D1421",
            bordercolor="#1A2840",
            font=dict(family="Fira Code", color="#C8D6F0"),
        ),
    )
    return fig


# ══════════════════════════════════════════════════════════════════════════════
# WARROOM BRAIN — neural visualization component (SVG / JS polling)
# brain_component.html is loaded once; JS polls /app/static/worker_brain_state.json
# ══════════════════════════════════════════════════════════════════════════════



@st.fragment
def brain_widget() -> None:
    """Render the WarRoom Brain once — JS inside polls /app/static/worker_brain_state.json."""
    _st_comp.html(get_brain_html(), height=320, scrolling=False)


# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════
history      = load_history()
worker_on    = is_worker_running()
critical_cnt = sum(1 for e in history if e.get("threat_level", 0) >= THREAT_THRESHOLD)
avg_threat   = (sum(e.get("threat_level", 0) for e in history) / len(history)) if history else 0.0

with st.sidebar:
    st.markdown(
        '<div class="sb-logo">OMNI<em>WAR</em>ROOM AI</div>'
        '<div class="sb-tag">// COMPETITIVE INTELLIGENCE PLATFORM v0.3</div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="sb-sect">Technology Partners</div>', unsafe_allow_html=True)
    _cognee_on   = bool(os.getenv("GROQ_API_KEY"))
    _gemini_on   = bool(os.getenv("GOOGLE_API_KEY"))
    _aiml_on     = bool(os.getenv("AIML_API_KEY"))
    _smat_on     = bool(os.getenv("SPEECHMATICS_API_KEY"))
    _trig_on     = bool(os.getenv("TRIGGERWARE_API_KEY"))
    st.markdown(f"""
    <div class="partner-row">Cognee memory   <span class="partner-{'on' if _cognee_on else 'off'}">{'ACTIVE' if _cognee_on else 'NO KEY'}</span></div>
    <div class="partner-row">Gemini analyst  <span class="partner-{'on' if _gemini_on else 'off'}">{'ACTIVE' if _gemini_on else 'NO KEY'}</span></div>
    <div class="partner-row">AI/ML API fbk   <span class="partner-{'on' if _aiml_on else 'off'}">{'ACTIVE' if _aiml_on else 'NO KEY'}</span></div>
    <div class="partner-row">Speechmatics    <span class="partner-{'on' if _smat_on else 'off'}">{'ACTIVE' if _smat_on else 'NO KEY'}</span></div>
    <div class="partner-row">Triggerware     <span class="partner-{'on' if _trig_on else 'off'}">{'ACTIVE' if _trig_on else 'NO URL'}</span></div>
    """, unsafe_allow_html=True)
    st.markdown('<div class="sb-sect">Infrastructure</div>', unsafe_allow_html=True)
    mcp_set = bool(os.getenv("BRIGHT_DATA_MCP_URL"))
    st.markdown(f"""
    <div class="sb-row">Bright Data MCP <span class="sb-val {'g' if mcp_set else ''}">{'LIVE' if mcp_set else 'FALLBACK'}</span></div>
    <div class="sb-row">Groq LLaMA-3.3  <span class="sb-val g">CONNECTED</span></div>
    <div class="sb-row">Auto Worker     <span class="sb-val {'g' if worker_on else ''}">{'RUNNING' if worker_on else 'STOPPED'}</span></div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="sb-sect">Intel Summary</div>', unsafe_allow_html=True)
    st.markdown(f"""
    <div class="sb-row">Total scans    <span class="sb-val">{len(history)}</span></div>
    <div class="sb-row">Critical (≥{THREAT_THRESHOLD})  <span class="sb-val {'r' if critical_cnt else 'g'}">{critical_cnt}</span></div>
    <div class="sb-row">Avg threat     <span class="sb-val">{avg_threat:.1f}/5</span></div>
    <div class="sb-row">Unique targets <span class="sb-val">{len({e.get('target_url') for e in history})}</span></div>
    """, unsafe_allow_html=True)

    if history:
        last_ts = fmt_ts(history[-1].get("timestamp", ""))
        st.markdown(
            f'<div class="sb-sect">Last Scan</div>'
            f'<div style="font-family:var(--font-mono);font-size:.68rem;color:var(--muted)">{last_ts} UTC</div>',
            unsafe_allow_html=True,
        )
    st.markdown("<hr>", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# HERO HEADER
# ══════════════════════════════════════════════════════════════════════════════
is_critical = critical_cnt > 0
status_class = "alert" if is_critical else ""
dot_class    = "red"   if is_critical else ""
status_text  = (
    f"WORKER: {'ACTIVE' if worker_on else 'STANDBY'} · {critical_cnt} CRITICAL ALERT{'S' if critical_cnt != 1 else ''}"
    if is_critical else
    f"WORKER: {'ACTIVE' if worker_on else 'STANDBY'} · LISTENING TO MARKET SIGNALS"
)

st.markdown(f"""
<div class="hero">
  <div class="hero-title">OMNI<em>WAR</em>ROOM &nbsp;<span style="opacity:.35;font-size:.65em;letter-spacing:.1em">AI</span></div>
  <div class="hero-subtitle">// Automated Market Countermeasures — Bright Data × Groq LLaMA</div>
  <div class="hero-status {status_class}">
    <div class="status-dot {dot_class}"></div>
    {status_text}
  </div>
</div>
""", unsafe_allow_html=True)


tab_control, tab_data, tab_worker = st.tabs([
    "⚔  CONTROL PLANE",
    "📊  DATA PLANE",
    "🔁  WORKER",
])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — CONTROL PLANE
# ══════════════════════════════════════════════════════════════════════════════
with tab_control:
    # ── Session state defaults ─────────────────────────────────────────────────
    for _k, _v in [
        ("graph_result", None), ("graph_error", None), ("exec_log", None),
    ]:
        if _k not in st.session_state:
            st.session_state[_k] = _v

    # ── Two-column layout: scan form left, brain right ─────────────────────────
    _scan_col, _brain_col = st.columns([3, 1], gap="large")

    with _brain_col:
        brain_widget()

    with _scan_col:
        st.markdown('<div class="section-label">Manual Ingestion Trigger — Bright Data Server Fleet</div>', unsafe_allow_html=True)

    # ── Input form (full-width below the header/brain row) ────────────────────
    st.markdown('<div class="scan-frame">', unsafe_allow_html=True)
    col_in, col_btn = st.columns([5, 1])
    with col_in:
        _default_url = st.session_state.get("voice_url", "https://competitor.com/pricing")
        target_url = st.text_input(
            "target_url", value=_default_url,
            placeholder="https://competitor.com/pricing",
            label_visibility="collapsed",
        )
    with col_btn:
        deploy = st.button("⚔  DEPLOY SWARM", use_container_width=True, type="primary")
    st.markdown('</div>', unsafe_allow_html=True)

    # ── Voice command (Speechmatics) ─────────────────────────────────────────
    with st.expander("🎙  VOICE COMMAND  —  Powered by Speechmatics", expanded=False):
        _has_smat_key = bool(os.getenv("SPEECHMATICS_API_KEY"))
        if not _has_smat_key:
            st.markdown(
                '<div style="font-family:\'Fira Code\',monospace;font-size:.76rem;color:#3D5070;margin-bottom:8px;">'
                '// No SPEECHMATICS_API_KEY — recording available but transcription will be skipped.'
                ' Get a free key at speechmatics.com/developers'
                '</div>',
                unsafe_allow_html=True,
            )
        st.caption("Say: 'analyze notion.so' · 'scan slack pricing' · 'check shopify'")
        if hasattr(st, "audio_input"):
            audio_data = st.audio_input("Record voice command", key="voice_rec")
        else:
            audio_data = st.file_uploader(
                "Upload audio (.wav / .mp3)", type=["wav", "mp3"], key="voice_file"
            )

        if audio_data is not None:
            if not _has_smat_key:
                st.warning("// Add SPEECHMATICS_API_KEY to .env to enable transcription")
            else:
                try:
                    # Read bytes — getvalue() is safer than read() (no seek needed)
                    if hasattr(audio_data, "getvalue"):
                        raw_bytes = audio_data.getvalue()
                    elif hasattr(audio_data, "read"):
                        raw_bytes = audio_data.read()
                    else:
                        raw_bytes = bytes(audio_data)

                    if not raw_bytes:
                        st.warning("// Empty audio — try recording again.")
                    else:
                        _mime = getattr(audio_data, "type", None) or "audio/webm"
                        write_brain_state_file("listen", 0, "", "listening...")
                        with st.spinner("🎙 Transcribing with Speechmatics..."):
                            transcript = transcribe_audio(raw_bytes, _mime)

                        if transcript and not transcript.startswith("["):
                            st.markdown(
                                f'<div class="terminal-wrap">// Transcript: {_html.escape(transcript)}'
                                f'<span class="terminal-cursor"></span></div>',
                                unsafe_allow_html=True,
                            )
                            detected = extract_url_from_voice(transcript)
                            if detected:
                                write_brain_state_file("scout", 0, detected,
                                                       f"URL detected: {detected[:60]}")
                                st.session_state["voice_url"] = detected
                                st.success(f"✓ URL detected: {detected} — click Deploy Swarm to launch")
                            else:
                                write_brain_state_file("idle", 0, "", "No URL detected")
                                st.warning("No URL detected. Try: 'analyze notion.so pricing'")
                        else:
                            write_brain_state_file("idle", 0, "", "Transcription failed")
                            st.error(f"Transcription failed: {transcript}")
                except Exception as _ve:
                    write_brain_state_file("idle", 0, "", "Audio error")
                    st.error(f"// Voice error: {_ve}")

    # Use voice-detected URL if available
    if "voice_url" in st.session_state and st.session_state["voice_url"]:
        target_url = st.session_state["voice_url"]

    # ── Execution with status steps ───────────────────────────────────────────
    if deploy and target_url:
        st.session_state["graph_result"] = None
        st.session_state["graph_error"]  = None
        st.session_state["exec_log"]     = None

        def _line(text: str):
            st.markdown(
                f'<span style="font-family:\'Fira Code\',monospace;font-size:.79rem;color:{NEON_CYAN};">{text}</span>',
                unsafe_allow_html=True,
            )

        with st.status("⚡  SWARM DEPLOYING ...", expanded=True) as status:
            _line("› Initializing Scout agent...")
            time.sleep(0.25)
            _line("› Connecting to Bright Data MCP endpoint...")
            time.sleep(0.3)
            _line(f"› Target locked: {target_url}")
            time.sleep(0.2)
            _line("› Bypassing bot detection — Web Unlocker active...")

            t0 = time.time()
            try:
                initial_state = {
                    "target_url": target_url,
                    "raw_data": "", "market_signals": [],
                    "threat_level": 0, "action_plan": "",
                }

                # Brain → scout before blocking invocation
                write_brain_state_file("scout", 0, target_url,
                                       f"Scraping {target_url[:55]}...")

                result = asyncio.run(war_room_graph.ainvoke(initial_state))
                elapsed = time.time() - t0

                # Brain → idle after scan (agent_graph nodes wrote intermediate states)
                _final_threat = result.get("threat_level", 0)
                write_brain_state_file("idle", _final_threat, target_url,
                                       f"Cycle done — threat {_final_threat}/5")

                st.session_state["graph_result"] = result
                st.session_state["exec_log"]     = build_exec_log(result, elapsed)
                load_history.clear()

                threat  = result.get("threat_level", 0)
                signals = result.get("market_signals", [])

                _line(f"› Raw data extracted — {len(result.get('raw_data',''))} chars")
                time.sleep(0.1)
                st.markdown(
                    f'<span style="font-family:\'Fira Code\',monospace;font-size:.79rem;color:{NEON_GREEN};">✓ SERP sentiment analysis complete</span>',
                    unsafe_allow_html=True,
                )
                time.sleep(0.1)
                _line(f"› Groq LLaMA-3.3-70B: {len(signals)} signal(s) extracted")
                time.sleep(0.1)
                color = NEON_RED if threat >= THREAT_THRESHOLD else NEON_GREEN
                st.markdown(
                    f'<span style="font-family:\'Fira Code\',monospace;font-size:.79rem;color:{color};">'
                    f'{"⚠ CRITICAL —" if threat >= THREAT_THRESHOLD else "✓ STABLE —"} Threat level: {threat}/5</span>',
                    unsafe_allow_html=True,
                )
                if threat >= THREAT_THRESHOLD:
                    time.sleep(0.15)
                    st.markdown(
                        f'<span style="font-family:\'Fira Code\',monospace;font-size:.79rem;color:{NEON_RED};">⚡ Tactician engaged — generating counter-strike plan...</span>',
                        unsafe_allow_html=True,
                    )
                    time.sleep(0.1)
                    st.markdown(
                        f'<span style="font-family:\'Fira Code\',monospace;font-size:.79rem;color:{NEON_RED};">✓ Enterprise alert dispatched</span>',
                        unsafe_allow_html=True,
                    )

                lbl = (
                    f"✓ COMPLETE — Threat {threat}/5 · {len(signals)} signal(s) · {elapsed:.1f}s"
                )
                status.update(label=lbl, state="complete", expanded=False)

            except Exception as e:
                st.session_state["graph_error"] = str(e)
                status.update(label="✗ SWARM ERROR", state="error", expanded=True)

    # ── Execution terminal log ────────────────────────────────────────────────
    if st.session_state["exec_log"]:
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown('<div class="section-label">Execution Trace</div>', unsafe_allow_html=True)
        st.markdown(
            f'<div class="terminal-wrap">{st.session_state["exec_log"]}</div>',
            unsafe_allow_html=True,
        )

    # ── Error ─────────────────────────────────────────────────────────────────
    if st.session_state["graph_error"]:
        st.markdown(f"""
        <div class="result-critical">
            <h4>⚠ Swarm Error</h4>
            <p>{st.session_state['graph_error']}</p>
        </div>""", unsafe_allow_html=True)

    # ── Agent cards + result ──────────────────────────────────────────────────
    elif st.session_state["graph_result"]:
        res     = st.session_state["graph_result"]
        signals = res.get("market_signals", [])
        threat  = res.get("threat_level", 0)
        plan    = res.get("action_plan", "")
        tc      = threat_css(threat)

        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown('<div class="section-label">Agent Status</div>', unsafe_allow_html=True)

        col1, col2, col3 = st.columns(3)

        col1.markdown(f"""
        <div class="agent-card done-g">
          <div class="agent-name">// Scout Agent</div>
          <span class="badge badge-done">✓ COMPLETE</span>
          <div class="agent-body">
            <strong>Target:</strong> {_html.escape(res.get("target_url",""))}<br>
            <strong>Raw data:</strong> collected &amp; forwarded
          </div>
        </div>""", unsafe_allow_html=True)

        sigs_html = "".join(f"<li>{s}</li>" for s in signals) or "<li>No signals detected.</li>"
        col2.markdown(f"""
        <div class="agent-card {'done-r' if threat >= THREAT_THRESHOLD else 'done-g'}">
          <div class="agent-name">// Analyst Agent</div>
          <span class="badge badge-done">✓ COMPLETE</span>
          <div class="agent-body">
            <div style="display:flex;align-items:baseline;gap:6px;margin:6px 0 10px 0">
              <span class="threat-num {tc}">{threat}</span>
              <span class="threat-denom">/5</span>
            </div>
            <ul>{sigs_html}</ul>
          </div>
        </div>""", unsafe_allow_html=True)

        if threat >= THREAT_THRESHOLD:
            col3.markdown(f"""
            <div class="agent-card engaged">
              <div class="agent-name">// Tactician Agent</div>
              <span class="badge badge-alert">⚡ ENGAGED</span>
              <div class="agent-body">{_html.escape(plan) if plan else "Counter-strategy generated."}</div>
            </div>""", unsafe_allow_html=True)
        else:
            col3.markdown(f"""
            <div class="agent-card">
              <div class="agent-name">// Tactician Agent</div>
              <span class="badge badge-idle">○ STANDBY</span>
              <div class="agent-body">Threat level below activation threshold. No action required.</div>
            </div>""", unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        if threat >= THREAT_THRESHOLD:
            roi_gain   = round(threat * 4.7 + len(signals) * 2.1, 1)
            roi_margin = round(threat * 1.8, 1)
            _plan_esc  = _html.escape(plan)
            _sig_count = len(signals)
            _alert_html = (
                '<html><head><style>'
                ':root{--red:#ff1744;--green:#00ff41;--dim:#c09898;}'
                '*{margin:0;padding:0;box-sizing:border-box;}'
                'body{background:transparent;font-family:"Courier New",monospace;padding:0;}'
                '.card{'
                'background:linear-gradient(135deg,rgba(18,4,4,.97),rgba(30,7,7,.97));'
                'border:1px solid rgba(255,23,68,.32);border-left:3px solid var(--red);'
                'border-radius:4px;padding:18px 22px;margin-bottom:10px;'
                'overflow:hidden;max-height:108px;transition:max-height .4s ease;}'
                '.card.open{max-height:600px;}'
                '.card h4{color:var(--red);margin:0 0 10px;font-size:.76rem;font-weight:700;'
                'letter-spacing:.12em;text-transform:uppercase;text-shadow:0 0 12px rgba(255,23,68,.5);}'
                '.card p{color:var(--dim);margin:3px 0;font-size:.84rem;line-height:1.55;}'
                '.roi{'
                'background:rgba(0,255,65,.025);border:1px solid rgba(0,255,65,.18);'
                'border-left:3px solid var(--green);border-radius:4px;padding:14px 20px;'
                'margin-bottom:10px;display:none;}'
                '.roi.open{display:block;}'
                '.roi h4{color:var(--green);margin:0 0 8px;font-size:.72rem;font-weight:700;'
                'letter-spacing:.1em;text-transform:uppercase;}'
                '.roi p{color:#90b090;font-size:.82rem;margin:3px 0;}'
                '.toggle{background:none;border:1px solid rgba(255,23,68,.28);color:var(--red);'
                'font-family:"Courier New",monospace;font-size:.7rem;letter-spacing:.1em;'
                'cursor:pointer;padding:5px 16px;border-radius:3px;'
                'text-transform:uppercase;transition:background .2s;}'
                '.toggle:hover{background:rgba(255,23,68,.12);}'
                '</style></head><body>'
                '<div class="card" id="card">'
                '<h4>⚡ STRATEGIC ALERT — THREAT ' + str(threat) + '/5</h4>'
                '<p><strong>Immediate action:</strong> ' + _plan_esc + '</p>'
                '<p><strong>Signals detected:</strong> ' + str(_sig_count) + ' &nbsp;·&nbsp; <strong>Alert dispatched:</strong> ✓</p>'
                '</div>'
                '<div class="roi" id="roi">'
                '<h4>Simulated ROI Impact</h4>'
                '<p>Revenue uplift if actioned within 2h: <strong>+' + str(roi_gain) + '%</strong></p>'
                '<p>Margin protection: <strong>+' + str(roi_margin) + ' pts</strong></p>'
                '</div>'
                '<button class="toggle" id="btn" onclick="toggle()">▼ Show more</button>'
                '<script>'
                'var open=false;'
                'function resize(h){window.parent.postMessage({isStreamlitMessage:true,type:"streamlit:setFrameHeight",height:h},"*");}'
                'function toggle(){'
                'open=!open;'
                'document.getElementById("card").className="card"+(open?" open":"");'
                'document.getElementById("roi").className="roi"+(open?" open":"");'
                'document.getElementById("btn").textContent=open?"▲ Show less":"▼ Show more";'
                'setTimeout(function(){resize(open?document.body.scrollHeight+20:160);},420);'
                '}'
                'resize(160);'
                '</script>'
                '</body></html>'
            )
            _st_comp.html(_alert_html, height=160, scrolling=False)
        else:
            st.markdown(f"""
            <div class="result-stable">
              <h3>✓ MARKET STABLE — THREAT {threat}/5</h3>
              <p>No immediate action required. Scan persisted to history.</p>
            </div>""", unsafe_allow_html=True)

    else:
        # Idle cards
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown('<div class="section-label">Agent Status</div>', unsafe_allow_html=True)
        col1, col2, col3 = st.columns(3)
        for col, name, desc in [
            (col1, "// Scout Agent",     "Awaiting target URL to begin intelligence collection."),
            (col2, "// Analyst Agent",   "Standing by. Waiting for Scout data feed."),
            (col3, "// Tactician Agent", f"Dormant. Activates when threat ≥ {THREAT_THRESHOLD}/5."),
        ]:
            col.markdown(f"""
            <div class="agent-card">
              <div class="agent-name">{name}</div>
              <span class="badge badge-idle">● IDLE</span>
              <div class="agent-body">{desc}</div>
            </div>""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — DATA PLANE
# ══════════════════════════════════════════════════════════════════════════════
with tab_data:
    st.markdown('<div class="section-label">Historical Scans — Time-Series Market Intelligence</div>', unsafe_allow_html=True)

    history = load_history()

    if not history:
        st.markdown("""
        <div style="text-align:center;padding:60px 20px;">
          <div style="font-family:'Fira Code',monospace;font-size:1rem;color:#1A2840;margin-bottom:12px;">
            ████████████████████████████████
          </div>
          <div style="font-family:'Rajdhani',sans-serif;font-size:1.1rem;letter-spacing:.2em;color:#3D5070;text-transform:uppercase;">
            No Intel Gathered Yet
          </div>
          <div style="font-family:'Fira Code',monospace;font-size:.78rem;color:#1A2840;margin-top:8px;">
            // Waiting for swarm deployment...
          </div>
        </div>""", unsafe_allow_html=True)

    else:
        # ── Metrics ───────────────────────────────────────────────────────────
        latest_threat = history[-1].get("threat_level", 0) if history else 0
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Scans",     len(history))
        c2.metric("Critical (≥3)",   critical_cnt)
        c3.metric("Avg Threat",      f"{avg_threat:.1f} /5")
        c4.metric("Latest Alert",    f"{latest_threat} /5")

        st.markdown("<br>", unsafe_allow_html=True)

        # ── Plotly chart ──────────────────────────────────────────────────────
        fig = make_threat_chart(history)
        if not _PLOTLY:
            st.markdown(
                '<div style="font-family:\'Fira Code\',monospace;font-size:.76rem;color:#1A2840;padding:12px 0;">'
                '// pip install plotly  →  to enable the threat chart'
                '</div>',
                unsafe_allow_html=True,
            )
        elif fig:
            st.markdown('<div class="section-label">Threat Level — Time Series</div>', unsafe_allow_html=True)
            st.markdown('<div class="chart-frame">', unsafe_allow_html=True)
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
            st.markdown('</div>', unsafe_allow_html=True)

        # ── Scan table ────────────────────────────────────────────────────────
        st.markdown('<div class="section-label">Scan History</div>', unsafe_allow_html=True)
        rows = []
        for entry in reversed(history):
            rows.append({
                "Timestamp (UTC)": fmt_ts(entry.get("timestamp", "")),
                "Target URL":      entry.get("target_url", ""),
                "Threat Level":    entry.get("threat_level", 0),
                "Signals":         len(entry.get("signals_detected", [])),
                "Action Plan":     (entry.get("action_plan", "") or "—")[:90],
            })
        df = pd.DataFrame(rows)
        st.dataframe(
            df, use_container_width=True, hide_index=True,
            column_config={
                "Threat Level": st.column_config.ProgressColumn(
                    "Threat Level", min_value=0, max_value=5, format="%d /5"
                ),
            },
        )

        # ── Critical alert feed ───────────────────────────────────────────────
        crits = [e for e in reversed(history) if e.get("threat_level", 0) >= THREAT_THRESHOLD]
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown(
            f'<div class="section-label">GTM Alert Feed &nbsp;'
            f'<span style="color:var(--red);font-family:var(--font-mono)">'
            f'{len(crits)} critical event{"s" if len(crits) != 1 else ""}'
            f'</span></div>',
            unsafe_allow_html=True,
        )

        if not crits:
            st.success("No critical threats recorded. Market is stable.")
        else:
            for entry in crits[:10]:
                sigs = entry.get("signals_detected", [])
                sig_html = "".join(f"<p>· {_html.escape(str(s))}</p>" for s in sigs) if sigs else "<p>· No signal detail available.</p>"
                e_url    = _html.escape(entry.get("target_url", ""))
                e_plan   = _html.escape(entry.get("action_plan", "—") or "—")
                e_ts     = _html.escape(fmt_ts(entry.get("timestamp", "")))
                st.markdown(f"""
                <div class="hist-card">
                  <h4>⚡ THREAT {entry.get("threat_level")}/5 — {e_url}</h4>
                  <p><strong>Detected:</strong> {e_ts} UTC</p>
                  {sig_html}
                  <p><strong>Action:</strong> {e_plan}</p>
                </div>""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — WORKER PLANE (redesign v2.1)
# ══════════════════════════════════════════════════════════════════════════════
with tab_worker:
    _wr = is_worker_running()
    _saved_urls, _saved_interval = load_worker_config()
    _JOURNAL_PATH = ROOT / "data" / "agent_journal.jsonl"
    _BRAIN_SF      = Path(__file__).parent / "static" / "worker_brain_state.json"

    # ── helpers ────────────────────────────────────────────────────────────────
    def _read_brain_sf():
        if _BRAIN_SF.exists():
            try: return json.loads(_BRAIN_SF.read_text(encoding="utf-8"))
            except Exception: pass
        return {}

    def _read_journal(n=60):
        if not _JOURNAL_PATH.exists():
            return []
        try:
            lines = _JOURNAL_PATH.read_text(encoding="utf-8").splitlines()
            entries = []
            for ln in lines[-n:]:
                try: entries.append(json.loads(ln))
                except Exception: pass
            return entries
        except Exception:
            return []

    def _phase_badge(phase: str) -> str:
        m = {"scout": "ph-scout", "analyst": "ph-analyst",
             "tactician": "ph-tactician", "persistence": "ph-persist"}
        labels = {"scout": "SCOUT", "analyst": "ANALYST",
                  "tactician": "TACTIC", "persistence": "PERSIST", "idle": "VEILLE"}
        cls  = m.get(phase, "ph-idle")
        lbl  = labels.get(phase, "VEILLE")
        return f'<span class="ph {cls}">{lbl}</span>'

    def _bar_html(threat: int) -> str:
        pct = int(threat / 5 * 100) if threat else 0
        col = ("#ff1744" if threat >= 4 else "#ffb300" if threat >= 2 else "#00ff41")
        return (f'<div class="w-bar"><div class="w-bar-fill" '
                f'style="width:{pct}%;background:{col};"></div></div>')

    def _threat_dot(threat: int) -> str:
        col = ("#ff1744" if threat >= 4 else "#ffb300" if threat >= 2 else "#00ff41")
        return f'<span style="color:{col};font-size:.6rem;">●</span>'

    # ── header bar ─────────────────────────────────────────────────────────────
    _bs = _read_brain_sf()
    _curr_threat_w = _bs.get("threat_level", 0)
    _scans_done    = len(set(e.get("target_url","") for e in load_history()))
    _n_urls        = len(_saved_urls)
    _threat_badge  = ('<span class="badge-threat-hdr">MENACE CRITIQUE</span>'
                      if _curr_threat_w >= THREAT_THRESHOLD else "")

    _wbadge = "badge-won" if _wr else "badge-woff"
    _wlabel = "ACTIF" if _wr else "INACTIF"
    st.markdown(
        f'<div class="w-hdr">'
        f'<span class="w-hdr-title">○ &nbsp; OMNIWARROOM AI — WORKER v2.1</span>'
        f'<div class="w-hdr-badges">'
        f'<span class="{_wbadge}">WORKER {_wlabel}</span>'
        f'<span class="badge-scan">SCAN {min(_scans_done, _n_urls)}/{_n_urls}</span>'
        f'{_threat_badge}'
        f'</div></div>',
        unsafe_allow_html=True,
    )

    # ── main row: brain | targets ───────────────────────────────────────────────
    _w_brain_col, _w_right_col = st.columns([9, 10], gap="medium")

    with _w_brain_col:
        # Brain (JS polls worker_brain_state.json at 500 ms — no st.rerun needed)
        _st_comp.html(get_brain_html(), height=330, scrolling=False)

    with _w_right_col:
        @st.fragment(run_every=5)
        def _w_targets():
            _bsnow  = _read_brain_sf()
            _active = _bsnow.get("target_url", "")
            _aphase = _bsnow.get("agent", "idle")
            _hist   = load_history()
            # latest result per URL
            _latest = {}
            for e in _hist:
                u = e.get("target_url","")
                _latest[u] = e

            rows_html = ""
            _c_urls, _c_interval = load_worker_config()
            for u in _c_urls:
                host   = u.replace("https://","").replace("http://","").split("/")[0][:30]
                phase  = _aphase if (u == _active and _aphase != "idle") else "idle"
                result = _latest.get(u, {})
                threat = result.get("threat_level", 0)
                rows_html += (
                    '<div class="w-target-row">'
                    f'<div class="w-host"><span class="ck">✓</span>{host}</div>'
                    f'{_phase_badge(phase)}'
                    f'{_bar_html(threat)}'
                    f'<div class="w-elapsed">{_threat_dot(threat)}</div>'
                    '</div>'
                )

            _cycle_n = max(1, len(_hist) // max(1, _n_urls))
            _empty   = '<div class="wj-dim" style="font-family:var(--font-mono);font-size:.7rem;padding:8px 0;">_ no targets configured</div>'
            st.markdown(
                '<div class="w-panel">'
                '<div class="w-panel-title">Monitored targets'
                f'<span># cycle #{_cycle_n}</span></div>'
                f'{rows_html or _empty}'
                '</div>',
                unsafe_allow_html=True,
            )

        _w_targets()

    # ── bottom row: journal | alerts ────────────────────────────────────────────
    _w_jcol, _w_acol = st.columns([3, 2], gap="medium")

    with _w_jcol:
        @st.fragment(run_every=6)
        def _w_journal_frag():
            entries = _read_journal(60)
            _cls_map = {
                "scout": "wj-scout", "analyst": "wj-analyst",
                "tactician": "wj-tactician", "persistence": "wj-persist",
                "idle": "wj-dim",
            }
            if not entries:
                lines_html = '<div class="wj-line wj-dim">_ worker initialised...</div>'
            else:
                lines_html = ""
                for e in entries:
                    ts   = _html.escape(e.get("ts",""))
                    ag   = e.get("agent","idle")
                    host = _html.escape(e.get("host",""))
                    msg  = _html.escape(e.get("msg",""))
                    cls  = _cls_map.get(ag, "wj-dim")
                    tag  = ag.upper() if ag != "idle" else ""
                    tag_html = (f'<span class="{cls}">[{tag}]</span> ' if tag else "")
                    host_html = (f'<span style="color:#1a3050">{host}</span> — ' if host else "")
                    lines_html += (f'<div class="wj-line">'
                                   f'<span class="wj-ts">[{ts}]</span> ► '
                                   f'{tag_html}{host_html}'
                                   f'<span class="{cls}">{msg}</span>'
                                   f'</div>')

            _jt = ('<div style="font-family:var(--font-mono);font-size:.64rem;letter-spacing:.22em;'
                   'color:#2a4060;text-transform:uppercase;padding-bottom:6px;'
                   'border-bottom:1px solid #060c18;margin-bottom:8px;">Worker Journal</div>')
            st.markdown(
                _jt + f'<div class="w-journal">{lines_html}</div>',
                unsafe_allow_html=True,
            )

        _w_journal_frag()

    with _w_acol:
        @st.fragment(run_every=10)
        def _w_alerts_frag():
            _hist_a = load_history()
            _recent = [e for e in reversed(_hist_a) if e.get("threat_level",0) >= 2][:8]
            items_html = ""
            for e in _recent:
                threat  = e.get("threat_level", 0)
                col     = ("#ff1744" if threat >= 4 else "#ffb300" if threat >= 2 else "#00ff41")
                host    = e.get("target_url","").replace("https://","").split("/")[0][:28]
                signals = e.get("market_signals", [])
                sig_txt = _html.escape(signals[0][:55] if signals else "signal detected")
                items_html += (
                    '<div class="wa-item">'
                    f'<div class="wa-dot" style="background:{col};box-shadow:0 0 5px {col}44;"></div>'
                    f'<div class="wa-text"><span style="color:{col};">{host}</span> — {sig_txt}</div>'
                    '</div>'
                )

            if not items_html:
                items_html = '<div class="wa-text wj-dim" style="padding:8px 0;">_ no recent alerts</div>'

            _at = ('<div style="font-family:var(--font-mono);font-size:.64rem;letter-spacing:.22em;'
                   'color:#2a4060;text-transform:uppercase;padding-bottom:6px;'
                   'border-bottom:1px solid #060c18;margin-bottom:8px;">GTM Alert Feed</div>')
            st.markdown(
                _at + f'<div class="w-alerts">{items_html}</div>',
                unsafe_allow_html=True,
            )

        _w_alerts_frag()

    # ── config expander + action footer ────────────────────────────────────────
    with st.expander("⚙  CONFIGURATION — URLs & Interval", expanded=not _wr):
        _cfg_u, _cfg_i = st.columns([3, 1])
        with _cfg_u:
            urls_input = st.text_area(
                "Targets (one URL per line)",
                value="\n".join(_saved_urls), height=110,
                key="w_urls", disabled=_wr,
            )
            urls_to_watch = [u.strip() for u in urls_input.splitlines()
                             if u.strip().startswith("http")]
        with _cfg_i:
            interval_val = st.number_input(
                "Intervalle (s)", min_value=60, max_value=3600,
                value=_saved_interval, step=60,
                key="w_interval", disabled=_wr,
            )
    urls_to_watch = [u.strip() for u in _saved_urls]  # fallback if expander collapsed

    st.markdown("<br>", unsafe_allow_html=True)
    _fa, _fb, _fc, _fd = st.columns([2, 2, 2, 5])
    with _fa:
        start_clicked = st.button("▶  LANCER CYCLE", use_container_width=True,
                                   type="primary", disabled=_wr, key="btn_start")
    with _fb:
        stop_clicked  = st.button("■  STOP", use_container_width=True,
                                   disabled=not _wr, key="btn_stop")
    with _fd:
        st.markdown(
            '<div class="w-foot-brand" style="text-align:right;padding-top:8px;">'
            'OMNIWARROOM &nbsp;·&nbsp; BRIGHT DATA MCF &nbsp;·&nbsp; LANGGRAPH'
            '</div>', unsafe_allow_html=True)

    if start_clicked:
        _urls_start = [u.strip() for u in st.session_state.get("w_urls","").splitlines()
                       if u.strip().startswith("http")]
        if not _urls_start:
            _urls_start = _saved_urls
        _int_start = int(st.session_state.get("w_interval", _saved_interval))
        start_worker(_urls_start, _int_start)
        st.toast(f"Swarm started — {len(_urls_start)} targets · cycle {_int_start}s", icon="🚀")
        time.sleep(0.4)
        st.rerun()

    if stop_clicked:
        stop_worker()
        write_brain_state_file("idle", 0, "", "worker stopped")
        st.toast("Worker stopped.", icon="🛑")
        time.sleep(0.4)
        st.rerun()
