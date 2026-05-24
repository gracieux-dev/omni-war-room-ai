import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import time
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from agents.agent_graph import war_room_graph

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="OmniWarRoom AI",
    page_icon="⚔️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Global CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
    background-color: #0E1117;
    color: #E0E0E0;
}

/* Sidebar */
section[data-testid="stSidebar"] {
    background-color: #13151C;
    border-right: 1px solid #1F2330;
}

/* Cards */
.card {
    background-color: #13151C;
    border: 1px solid #1F2330;
    border-radius: 10px;
    padding: 20px;
    height: 100%;
    min-height: 220px;
}
.card h4 {
    margin: 0 0 12px 0;
    font-size: 0.85rem;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #7C8DB0;
}
.card p, .card li {
    font-size: 0.9rem;
    color: #B0BAD0;
    line-height: 1.6;
}
.card ul { padding-left: 16px; margin: 0; }

/* Status badges */
.badge {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 20px;
    font-size: 0.75rem;
    font-weight: 600;
    margin-left: 6px;
}
.badge-ok   { background: #0D3320; color: #2ECC71; border: 1px solid #2ECC71; }
.badge-mock { background: #2D2200; color: #F39C12; border: 1px solid #F39C12; }
.badge-idle { background: #1A1D26; color: #7C8DB0; border: 1px solid #3A4060; }
.badge-run  { background: #0D1F3C; color: #3498DB; border: 1px solid #3498DB; }
.badge-done { background: #0D3320; color: #2ECC71; border: 1px solid #2ECC71; }

/* Alert box */
.alert-critical {
    background: linear-gradient(135deg, #1A0A0A, #2D1010);
    border: 1px solid #C0392B;
    border-left: 4px solid #E74C3C;
    border-radius: 8px;
    padding: 20px 24px;
    margin-top: 24px;
}
.alert-critical h3 { color: #E74C3C; margin: 0 0 10px 0; font-size: 1rem; letter-spacing: 0.06em; }
.alert-critical p  { color: #D0B0B0; margin: 4px 0; font-size: 0.9rem; }

.alert-stable {
    background: #0A1A10;
    border: 1px solid #1E8449;
    border-left: 4px solid #2ECC71;
    border-radius: 8px;
    padding: 20px 24px;
    margin-top: 24px;
}
.alert-stable h3 { color: #2ECC71; margin: 0 0 6px 0; font-size: 1rem; }
.alert-stable p  { color: #90C0A0; font-size: 0.9rem; }

/* ROI block */
.roi-block {
    background: #0D1F3C;
    border: 1px solid #2471A3;
    border-radius: 8px;
    padding: 16px 20px;
    margin-top: 16px;
}
.roi-block h4 { color: #3498DB; margin: 0 0 8px 0; font-size: 0.85rem; letter-spacing: 0.06em; }
.roi-block p  { color: #AED6F1; font-size: 0.9rem; margin: 3px 0; }

/* Divider */
.divider { border: none; border-top: 1px solid #1F2330; margin: 20px 0; }

/* Logo */
.logo {
    font-size: 1.15rem;
    font-weight: 700;
    letter-spacing: 0.1em;
    color: #FFFFFF;
    margin-bottom: 4px;
}
.logo span { color: #E74C3C; }
.tagline { font-size: 0.72rem; color: #5A6580; letter-spacing: 0.06em; margin-bottom: 20px; }
</style>
""", unsafe_allow_html=True)


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown('<div class="logo">⚔️ OMNI<span>WAR</span>ROOM AI</div>', unsafe_allow_html=True)
    st.markdown('<div class="tagline">COMPETITIVE INTELLIGENCE PLATFORM</div>', unsafe_allow_html=True)
    st.markdown('<hr class="divider">', unsafe_allow_html=True)

    st.markdown("**Data Sources**")
    st.markdown(
        'Bright Data MCP <span class="badge badge-mock">MOCK</span>',
        unsafe_allow_html=True,
    )
    st.markdown(
        'Groq LLM <span class="badge badge-ok">CONNECTED</span>',
        unsafe_allow_html=True,
    )

    st.markdown('<hr class="divider">', unsafe_allow_html=True)
    st.markdown("**Agent Swarm**")
    st.markdown(
        '🕵️ Scout &nbsp;<span class="badge badge-idle">IDLE</span>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '🧠 Analyst &nbsp;<span class="badge badge-idle">IDLE</span>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '⚡ Tactician &nbsp;<span class="badge badge-idle">IDLE</span>',
        unsafe_allow_html=True,
    )

    st.markdown('<hr class="divider">', unsafe_allow_html=True)
    st.caption("v0.1.0 — Hackathon Build")


# ── Main header ───────────────────────────────────────────────────────────────
st.markdown("## Strategic Intelligence Dashboard")
st.markdown(
    '<p style="color:#5A6580;margin-top:-12px;font-size:0.9rem;">'
    'Deploy your AI swarm to monitor, analyze, and counter competitor moves in real time.'
    '</p>',
    unsafe_allow_html=True,
)
st.markdown('<hr class="divider">', unsafe_allow_html=True)

# ── URL Input + Button ────────────────────────────────────────────────────────
col_input, col_btn = st.columns([4, 1])
with col_input:
    target_url = st.text_input(
        label="Target URL",
        value="https://competitor.com/pricing",
        placeholder="https://competitor.com/pricing",
        label_visibility="collapsed",
    )
with col_btn:
    deploy = st.button("⚔️ Deploy Swarm", use_container_width=True, type="primary")

st.markdown('<hr class="divider">', unsafe_allow_html=True)

# ── Live Feed columns (default / idle state) ──────────────────────────────────
st.markdown("#### 🔴 Live Agent Feed")
col1, col2, col3 = st.columns(3)

scout_placeholder    = col1.empty()
analyst_placeholder  = col2.empty()
tactician_placeholder = col3.empty()


def render_idle():
    scout_placeholder.markdown("""
    <div class="card">
        <h4>🕵️ Scout Agent</h4>
        <p><span class="badge badge-idle">IDLE</span></p>
        <p style="margin-top:14px;">Awaiting target URL to begin scraping sequence.</p>
    </div>""", unsafe_allow_html=True)

    analyst_placeholder.markdown("""
    <div class="card">
        <h4>🧠 Analyst Agent</h4>
        <p><span class="badge badge-idle">IDLE</span></p>
        <p style="margin-top:14px;">Waiting for Scout data feed to run market analysis.</p>
    </div>""", unsafe_allow_html=True)

    tactician_placeholder.markdown("""
    <div class="card">
        <h4>⚡ Tactician Agent</h4>
        <p><span class="badge badge-idle">IDLE</span></p>
        <p style="margin-top:14px;">On standby — activated only when threat level ≥ 3.</p>
    </div>""", unsafe_allow_html=True)


render_idle()

# ── Execution ─────────────────────────────────────────────────────────────────
if deploy and target_url:
    result_placeholder = st.empty()

    # --- Scout ---
    scout_placeholder.markdown("""
    <div class="card">
        <h4>🕵️ Scout Agent</h4>
        <p><span class="badge badge-run">RUNNING</span></p>
        <p style="margin-top:14px;">Connecting to Bright Data MCP...<br>Scraping target page...</p>
    </div>""", unsafe_allow_html=True)

    with st.spinner("Scout agent scraping target..."):
        time.sleep(2)

    scout_placeholder.markdown(f"""
    <div class="card">
        <h4>🕵️ Scout Agent</h4>
        <p><span class="badge badge-done">DONE</span></p>
        <p style="margin-top:14px;">
            <strong>URL:</strong> {target_url}<br>
            <strong>Price:</strong> $29.99<br>
            <strong>Stock:</strong> 142 units<br>
            <strong>Discount:</strong> 15% active<br>
            <strong>Badge:</strong> Best Seller
        </p>
    </div>""", unsafe_allow_html=True)

    # --- Analyst ---
    analyst_placeholder.markdown("""
    <div class="card">
        <h4>🧠 Analyst Agent</h4>
        <p><span class="badge badge-run">RUNNING</span></p>
        <p style="margin-top:14px;">Sending data to Groq LLM...<br>Extracting market signals...</p>
    </div>""", unsafe_allow_html=True)

    with st.spinner("Analyst agent evaluating threats via Groq..."):
        initial_state = {
            "target_url": target_url,
            "raw_data": "",
            "market_signals": [],
            "threat_level": 0,
            "action_plan": "",
        }
        final_state = asyncio.run(war_room_graph.ainvoke(initial_state))

    signals   = final_state.get("market_signals", [])
    threat    = final_state.get("threat_level", 0)
    plan      = final_state.get("action_plan", "")

    threat_color = "#E74C3C" if threat >= 3 else "#F39C12" if threat >= 2 else "#2ECC71"
    signals_html = "".join(f"<li>{s}</li>" for s in signals) if signals else "<li>No signals detected.</li>"

    analyst_placeholder.markdown(f"""
    <div class="card">
        <h4>🧠 Analyst Agent</h4>
        <p><span class="badge badge-done">DONE</span></p>
        <p style="margin-top:14px;">
            <strong>Threat Level:</strong>
            <span style="color:{threat_color};font-weight:700;font-size:1.1rem;"> {threat}/5</span>
        </p>
        <ul style="margin-top:8px;">{signals_html}</ul>
    </div>""", unsafe_allow_html=True)

    # --- Tactician ---
    if threat >= 3:
        tactician_placeholder.markdown("""
        <div class="card">
            <h4>⚡ Tactician Agent</h4>
            <p><span class="badge badge-run">RUNNING</span></p>
            <p style="margin-top:14px;">Threat confirmed. Drafting response plan...</p>
        </div>""", unsafe_allow_html=True)

        with st.spinner("Tactician drafting counter-strategy..."):
            time.sleep(1)

        tactician_placeholder.markdown(f"""
        <div class="card">
            <h4>⚡ Tactician Agent</h4>
            <p><span class="badge badge-done">ENGAGED</span></p>
            <p style="margin-top:14px;">{plan if plan else "Counter-strategy generated."}</p>
        </div>""", unsafe_allow_html=True)
    else:
        tactician_placeholder.markdown("""
        <div class="card">
            <h4>⚡ Tactician Agent</h4>
            <p><span class="badge badge-idle">STANDBY</span></p>
            <p style="margin-top:14px;">Threat level below threshold. No action required.</p>
        </div>""", unsafe_allow_html=True)

    # --- Strategic Alert ---
    st.markdown('<hr class="divider">', unsafe_allow_html=True)

    if threat >= 3:
        roi_gain   = round(threat * 4.7 + len(signals) * 2.1, 1)
        roi_margin = round(threat * 1.8, 1)

        st.markdown(f"""
        <div class="alert-critical">
            <h3>🚨 STRATEGIC ALERT — THREAT LEVEL {threat}/5</h3>
            <p><strong>Action:</strong> {plan}</p>
            <p><strong>Signals detected:</strong> {len(signals)}</p>
        </div>
        <div class="roi-block">
            <h4>📈 SIMULATED ROI IMPACT</h4>
            <p>Estimated revenue uplift if action deployed: <strong>+{roi_gain}%</strong></p>
            <p>Margin protection: <strong>+{roi_margin} pts</strong></p>
            <p>Response window: <strong>&lt; 2 hours recommended</strong></p>
        </div>""", unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div class="alert-stable">
            <h3>✅ MARKET STABLE — THREAT LEVEL {threat}/5</h3>
            <p>No immediate action required. Continue monitoring cadence.</p>
        </div>""", unsafe_allow_html=True)
