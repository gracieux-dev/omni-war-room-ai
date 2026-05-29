# OmniWarRoom AI
> **Autonomous Multi-Agent Swarm for Real-Time Competitive Intelligence & Automated Market Countermeasures**

Built for the **Bright Data AI Agents & Web Data Hackathon (Lablab.ai)**.  
Stack: **LangGraph · Groq · Google Gemini · Bright Data MCP · Streamlit**

---

## Overview

OmniWarRoom AI deploys an autonomous swarm of specialized AI agents that continuously monitor competitor ecosystems, evaluate threat levels in real time, and formulate actionable business counter-strategies.

**Dual-track coverage:**
- **GTM Intelligence** — competitor pricing drops, stock levels, aggressive campaigns
- **Risk & Compliance** — market vulnerabilities, product anomalies, customer sentiment crises

---

## Architecture

```
Bright Data Web/SERP (live unblocked data)
        ���
        ▼
┌─────────────────────────────────────────┐
│             LANGGRAPH SWARM             │
│                                         │
│  Scout ──��� Analyst ──► Tactician        │
│  (scrape)  (LLM eval) (if threat ≥ 3)  │
│                │                        │
│           Persistence                   │
│           (Cognee memory)               │
└─────────────────────────────────────────┘
        │
        ▼
Streamlit Dashboard  ·  Email Alert  ·  Voice Briefing
```

**Agents:**
| Agent | Model | Role |
|-------|-------|------|
| Scout | Groq llama-3.1-8b | Live data collection via Bright Data MCP |
| Analyst | Gemini 2.0 Flash + Qwen3-32B | Structured threat scoring (Pydantic) |
| Tactician | Groq llama-3.3-70b | Counter-strategy & ROI plan (threat ≥ 3) |
| Persistence | Cognee | Memory enrichment across cycles |

---

## Features

- Real-time SVG brain visualization with 6 agent states (JS polling, no st.rerun)
- Autonomous worker loop with configurable interval and URL targets
- Email alerts via SMTP (auto-detects server from sender domain: Gmail, mail.fr, etc.)
- Voice command input via Speechmatics REST API
- STRATEGIC ALERT card with expand/collapse toggle
- Full history, journal, and GTM alert feed

---

## Quick Start

### Prerequisites
- Python 3.12+
- A Bright Data account with Web Unlocker + SERP zones
- Groq API key (free tier works)
- Google Gemini API key

### 1. Clone & install

```bash
git clone https://github.com/gracieux-dev/omni-war-room-ai.git
cd omni-war-room-ai
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your API keys
```

Required keys:
```env
GROQ_API_KEY=...
GOOGLE_API_KEY=...
BRIGHT_DATA_API_KEY=...
BRIGHT_DATA_UNLOCKER_ZONE=...
BRIGHT_DATA_SERP_ZONE=...
BRIGHT_DATA_MCP_URL=...
```

Optional:
```env
MAIL_SENDER=you@mail.fr        # Email alerts (auto-detects SMTP from domain)
MAIL_PASSWORD=...
AIML_API_KEY=...               # Tertiary LLM fallback
SPEECHMATICS_API_KEY=...       # Voice command transcription
TRIGGERWARE_API_KEY=...        # GTM webhook integration
```

### 3. Run

```bash
streamlit run ui/app.py
```

Or use the startup script:
```bash
bash start.sh
```

---

## Deployment

### Streamlit Community Cloud
1. Push to GitHub (`.env` is gitignored — add secrets via dashboard)
2. Set main file path: `ui/app.py`
3. Add all env vars in the Secrets section

### Railway / Render
The `Procfile` is included:
```
web: streamlit run ui/app.py --server.port $PORT --server.address 0.0.0.0
```
Add env vars in the platform dashboard.

### VPS / Docker
```bash
# Install dependencies
pip install -r requirements.txt

# Copy and fill .env
cp .env.example .env && nano .env

# Start
bash start.sh
```

---

## Project Structure

```
omni-war-room-ai/
├── ui/
│   ├── app.py                  # Streamlit dashboard
│   ├── brain_loader.py         # Brain state file helper
│   ├── brain_component.html    # SVG brain visualization (JS polling)
│   └── static/                 # Static files served by Streamlit
├── agents/
│   ├── agent_graph.py          # LangGraph swarm definition
│   └── schemas.py              # Pydantic output schemas
├── tools/
│   └── bright_data_mcp.py      # Bright Data MCP client
├── data/                       # Runtime data (gitignored)
├── worker.py                   # Autonomous worker loop
├── requirements.txt
├── Procfile                    # Cloud deployment
├── start.sh                    # Local startup
├── .env.example                # Environment template
└── .streamlit/config.toml
```

---

## Notes

- The **autonomous worker** (`worker.py`) is started/stopped from the UI. On cloud platforms without persistent compute, run it as a separate process or background job.
- `pyttsx3` (voice briefing) requires system TTS libraries ��� not available on most cloud platforms. It fails silently if unavailable.
- `cognee` memory uses a local SQLite database inside `.venv` by default — set `COGNEE_DB_PATH` to a writable path for cloud deployments.
