import os
import json
import asyncio
import httpx
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict, List
from langgraph.graph import StateGraph, START, END
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from agents.schemas import MarketAnalysisOutput
from tools.bright_data_mcp import fetch_competitor_data, fetch_serp_sentiment

try:
    from langchain_google_genai import ChatGoogleGenerativeAI
    _GEMINI_AVAILABLE = True
except ImportError:
    _GEMINI_AVAILABLE = False

# ── Cognee — persistent memory (configure env before import) ──────────────────
if not os.getenv("LLM_PROVIDER"):
    os.environ["LLM_PROVIDER"] = "groq"
if not os.getenv("LLM_MODEL"):
    os.environ["LLM_MODEL"] = "llama-3.1-8b-instant"
if not os.getenv("LLM_API_KEY") and os.getenv("GROQ_API_KEY"):
    os.environ["LLM_API_KEY"] = os.getenv("GROQ_API_KEY", "")
if not os.getenv("VECTOR_DB_PROVIDER"):
    os.environ["VECTOR_DB_PROVIDER"] = "lancedb"
if not os.getenv("GRAPH_DB_PROVIDER"):
    os.environ["GRAPH_DB_PROVIDER"] = "networkx"
try:
    import cognee
    _COGNEE_AVAILABLE = True
except ImportError:
    _COGNEE_AVAILABLE = False

# ── AI/ML API — unified tertiary fallback (200+ models) ──────────────────────
try:
    from langchain_aimlapi import ChatAimlapi as ChatAIMLAPI
    _AIML_AVAILABLE = True
except ImportError:
    _AIML_AVAILABLE = False

THREAT_THRESHOLD = 3
MAX_RAW_CHARS    = 3500   # ~875 tokens — stays well under Groq 12k TPM limit
MAX_SERP_CHARS   = 1500   # ~375 tokens

# 1. Définition du State
class AgentState(TypedDict):
    target_url: str
    raw_data: str
    market_signals: List[str]
    threat_level: int
    action_plan: str

# 2. LLMs — modèle par nœud + fallback universel
#
#  Scout     → llama-3.1-8b-instant      : tool calling léger, économise le quota
#  Analyst   → gemini-2.0-flash          : meilleur structured output du marché (si GOOGLE_API_KEY dispo)
#              qwen/qwen3-32b            : fallback Groq si Gemini indisponible ou quota dépassé
#  Tactician → llama-3.3-70b-versatile   : plan stratégique long, nuancé
#  Fallback  → llama-3.1-8b-instant      : quota séparé (1 M TPD) déclenché sur 429

_MODEL_SCOUT     = "llama-3.1-8b-instant"
_MODEL_ANALYSIS  = "qwen/qwen3-32b"          # fallback Groq si Gemini absent
_MODEL_TACTICIAN = "llama-3.3-70b-versatile"
_MODEL_FALLBACK  = "llama-3.1-8b-instant"

llm_scout     = ChatGroq(model_name=_MODEL_SCOUT,     temperature=0)
llm_analysis  = ChatGroq(model_name=_MODEL_ANALYSIS,  temperature=0)
llm_tactician = ChatGroq(model_name=_MODEL_TACTICIAN, temperature=0)
llm_fallback  = ChatGroq(model_name=_MODEL_FALLBACK,  temperature=0)

# Analyst primary: Gemini 2.0 Flash when GOOGLE_API_KEY is available, else Qwen3-32B
_google_key = os.getenv("GOOGLE_API_KEY")
if _GEMINI_AVAILABLE and _google_key:
    llm_analyst_primary = ChatGoogleGenerativeAI(
        model="gemini-2.0-flash",
        temperature=0,
        google_api_key=_google_key,
    )
else:
    llm_analyst_primary = llm_analysis

# alias de compatibilité (send_enterprise_alert, etc.)
llm = llm_tactician

structured_llm          = llm_analyst_primary.with_structured_output(MarketAnalysisOutput)
structured_llm_fallback = llm_analysis.with_structured_output(MarketAnalysisOutput)   # Qwen3-32B as Gemini fallback

# AI/ML API — tertiary fallback across all nodes
_aiml_key = os.getenv("AIML_API_KEY", "").strip()
if _AIML_AVAILABLE and _aiml_key:
    try:
        llm_aiml            = ChatAIMLAPI(model="Qwen/Qwen2.5-7B-Instruct", api_key=_aiml_key)
        structured_llm_aiml = llm_aiml.with_structured_output(MarketAnalysisOutput)
    except Exception:
        llm_aiml            = None
        structured_llm_aiml = None
else:
    llm_aiml            = None
    structured_llm_aiml = None


def _is_rate_limit(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "429" in msg or "rate_limit" in msg or "rate limit" in msg


async def _ainvoke(primary, fallback, messages, tertiary=None):
    try:
        return await primary.ainvoke(messages)
    except Exception as exc:
        if _is_rate_limit(exc):
            model = getattr(primary, "model_name", "primary")
            print(f"⚠️  [LLM] Rate limit on {model} — switching to {getattr(fallback, 'model_name', 'fallback')}")
            try:
                return await fallback.ainvoke(messages)
            except Exception as exc2:
                if _is_rate_limit(exc2) and tertiary is not None:
                    print("⚠️  [LLM] Rate limit cascade — AI/ML API engaged")
                    return await tertiary.ainvoke(messages)
                raise
        raise


async def _bg_cognify():
    """Fire-and-forget: indexes Cognee data into knowledge graph in background."""
    try:
        await cognee.cognify()
        print("🧠 [Cognee] Knowledge graph indexed.")
    except Exception as e:
        print(f"🧠 [Cognee] Cognify error: {e}")

# 3. Helpers entreprise

import time as _time
_BRAIN_PATH = Path(__file__).parent.parent / "ui" / "static" / "worker_brain_state.json"


def _update_brain_state(agent: str, threat: int = 0, log: str = "") -> None:
    """Atomically write brain state to ui/static/worker_brain_state.json for JS polling."""
    try:
        _BRAIN_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({
            "agent": agent,
            "threat_level": max(0, min(5, int(threat))),
            "target_url": "",
            "log": log[:120],
            "timestamp": int(_time.time()),
        }, ensure_ascii=False)
        _tmp = _BRAIN_PATH.with_suffix(".tmp")
        _tmp.write_text(payload, encoding="utf-8")
        os.replace(_tmp, _BRAIN_PATH)
    except Exception:
        pass


def save_analysis_to_history(state: AgentState) -> None:
    history_path = Path(__file__).parent.parent / "data" / "market_history.json"
    history_path.parent.mkdir(parents=True, exist_ok=True)

    entry = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "target_url": state.get("target_url", ""),
        "threat_level": state.get("threat_level", 0),
        "signals_detected": state.get("market_signals", []),
        "action_plan": state.get("action_plan", ""),
    }

    history: list = []
    if history_path.exists():
        try:
            history = json.loads(history_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            history = []

    history.append(entry)
    history_path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"💾 [Persistence] Entry saved → {history_path} ({len(history)} total)")


async def send_enterprise_alert(state: AgentState) -> None:
    threat    = state.get("threat_level", 0)
    url       = state.get("target_url", "N/A")
    signals   = state.get("market_signals", [])
    plan      = state.get("action_plan", "N/A")
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    signals_text = "\n".join(f"  • {s}" for s in signals) or "  • No signals detected"
    threat_bar   = "🔴" * threat + "⚫" * (5 - threat)

    alert_body = f"""
╔══════════════════════════════════════════════════════════════╗
║         🚨  OMNIWARROOM AI — ENTERPRISE ALERT               ║
╚══════════════════════════════════════════════════════════════╝

[TO]    #exec-alerts (Slack)  /  cto@company.com (SendGrid)
[FROM]  OmniWarRoom AI Swarm v0.1
[TIME]  {timestamp}
[LEVEL] CRITICAL — Threat {threat}/5

── COMPETITOR INTELLIGENCE BRIEF ──────────────────────────────
Target      : {url}
Threat Level: {threat_bar} ({threat}/5)

SIGNALS DETECTED:
{signals_text}

RECOMMENDED IMMEDIATE ACTION:
  {plan}

RESPONSE WINDOW: < 2 hours
────────────────────────────────────────────────────────────────
Auto-generated by OmniWarRoom AI. Open your War Room dashboard.
"""

    webhook_url = os.getenv("ALERT_WEBHOOK_URL")
    if webhook_url:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(webhook_url, json={"text": alert_body})
            print("📡 [Alert] Webhook delivered.")
        except Exception as e:
            print(f"📡 [Alert] Webhook failed ({e}) — logging locally.")
    else:
        print("📡 [Alert] ALERT_WEBHOOK_URL not set — simulation mode:")

    if not os.getenv("OMNI_WORKER_MODE"):
        print(alert_body)


# 4. Les Nœuds Asynchrones
async def scout_node(state: AgentState):
    _update_brain_state("scout", 0, f"Scraping {state['target_url'][:40]}...")
    mcp_url = os.getenv("BRIGHT_DATA_MCP_URL")

    if not mcp_url:
        print(f"🕵️ [Scout] BRIGHT_DATA_MCP_URL non définie — fallback scraping direct : {state['target_url']}")
        data = await fetch_competitor_data(state["target_url"])
        _update_brain_state("scout", 0, f"{len(str(data)[:MAX_RAW_CHARS])} chars extraits")
        return {"raw_data": str(data)[:MAX_RAW_CHARS]}

    print(f"🕵️ [Scout] Connexion MCP Bright Data → {state['target_url']}")

    try:
        # langchain-mcp-adapters >= 0.1.0 : plus de context manager, appel direct
        client    = MultiServerMCPClient({
            "bright_data": {
                "url": mcp_url,
                "transport": "streamable_http",  # /mcp → streamable_http ; /sse → sse
            }
        })
        mcp_tools          = await client.get_tools()
        scout_llm          = llm_scout.bind_tools(mcp_tools)       # 8B suffisant pour tool calling
        scout_llm_fallback = llm_fallback.bind_tools(mcp_tools)

        messages = [
            SystemMessage(
                "Tu es un agent de collecte de données. "
                "Utilise les outils MCP disponibles pour extraire le contenu complet de l'URL cible "
                "sous forme de texte brut ou markdown."
            ),
            HumanMessage(f"Extrais le contenu de : {state['target_url']}"),
        ]

        ai_msg = await _ainvoke(scout_llm, scout_llm_fallback, messages)

        raw_parts = []
        for tc in getattr(ai_msg, "tool_calls", []):
            tool_fn = next((t for t in mcp_tools if t.name == tc["name"]), None)
            if tool_fn:
                result = await tool_fn.ainvoke(tc["args"])
                raw_parts.append(str(result))

        raw_data = "\n\n".join(raw_parts) if raw_parts else ai_msg.content

    except Exception as e:
        print(f"🕵️ [Scout] Erreur MCP ({e}) — fallback scraping direct.")
        data = await fetch_competitor_data(state["target_url"])
        raw_data = str(data)

    _update_brain_state("scout", 0, f"{len(raw_data[:MAX_RAW_CHARS]):,} chars extraits")
    return {"raw_data": raw_data[:MAX_RAW_CHARS]}

async def analyst_node(state: AgentState):
    _update_brain_state("analyst", 0, "Croisement SERP + Cognee...")
    # Query Cognee for historical intelligence on this competitor
    cognee_context = ""
    if _COGNEE_AVAILABLE:
        try:
            results = await asyncio.wait_for(
                cognee.search(
                    f"competitor signals {state['target_url']}",
                    query_type="INSIGHTS",
                ),
                timeout=5.0,
            )
            if results:
                snippets = [str(r)[:300] for r in results[:3]]
                cognee_context = (
                    "\n\n--- HISTORICAL INTELLIGENCE (Cognee Memory) ---\n"
                    + "\n".join(snippets)
                )
                print(f"🧠 [Cognee] {len(results)} historical insight(s) injected into analysis.")
        except Exception as e:
            print(f"🧠 [Cognee] Query skipped: {e}")

    print("🧠 [Analyst] Récupération du sentiment SERP...")
    serp_sentiment = await fetch_serp_sentiment(f"avis {state['target_url']}")

    print("🧠 [Analyst] Évaluation via Gemini / Groq...")
    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            "Tu es un Analyste Marché expert. "
            "Croise les données HTML du site concurrent avec les signaux Google pour évaluer les menaces. "
            "Si des données historiques sont disponibles, intègre-les pour détecter des tendances. "
            "Rends un JSON parfait selon le schéma fourni.",
        ),
        (
            "human",
            "Cible : {target_url}\n\n"
            "--- DONNÉES BRUTES DU SITE (Web Unlocker) ---\n{raw_data}\n\n"
            "--- SENTIMENT WEB / RÉSULTATS GOOGLE (SERP) ---\n{serp_sentiment}"
            "{cognee_context}",
        ),
    ])

    formatted_prompt = prompt.format_messages(
        target_url=state["target_url"],
        raw_data=state["raw_data"][:MAX_RAW_CHARS],
        serp_sentiment=serp_sentiment[:MAX_SERP_CHARS],
        cognee_context=cognee_context,
    )
    try:
        analysis: MarketAnalysisOutput = await _ainvoke(
            structured_llm, structured_llm_fallback, formatted_prompt,
            tertiary=structured_llm_aiml,
        )
        signals = [f"[{s.category.upper()}] {s.description} ({s.severity})" for s in analysis.signals_detected]
        _update_brain_state("analyst", analysis.threat_level,
                            f"threat_level : {analysis.threat_level} · confidence : {int(analysis.confidence_score*100)}%")
        return {"market_signals": signals, "threat_level": analysis.threat_level}
    except Exception as e:
        print(f"🧠 [Analyst] Erreur LLM ({e}) — threat_level=0 par défaut.")
        _update_brain_state("analyst", 0, "Analyse échouée — fallback")
        return {"market_signals": [f"[ERROR] Analyse échouée : {type(e).__name__} (critical)"], "threat_level": 0}

async def tactician_node(state: AgentState) -> dict:
    _update_brain_state("tactician", state.get("threat_level", 0), "MENACE CRITIQUE — plan en cours")
    print("⚡ [Tactician] Élaboration de la riposte via Groq...")
    signals_text = "\n".join(f"- {s}" for s in state.get("market_signals", [])) or "Aucun signal spécifique."
    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            "Tu es un Stratège GTM expert. Sur la base des menaces concurrentielles détectées, "
            "génère un plan de riposte précis, actionnable et orienté impact business mesurable. "
            "Sois concis : 3 à 5 actions maximum, chacune avec un délai d'exécution.",
        ),
        (
            "human",
            "Concurrent : {target_url}\n"
            "Niveau de menace : {threat_level}/5\n"
            "Signaux :\n{signals}\n\n"
            "Génère le plan de contre-attaque immédiat.",
        ),
    ])
    try:
        formatted = prompt.format_messages(
            target_url=state["target_url"],
            threat_level=state["threat_level"],
            signals=signals_text,
        )
        response = await _ainvoke(llm_tactician, llm_fallback, formatted, tertiary=llm_aiml)
        action_plan = response.content.strip()
        _update_brain_state("tactician", state.get("threat_level", 0), "Alerte email envoyée")
    except Exception as e:
        print(f"⚡ [Tactician] Erreur LLM ({e}) — plan de fallback.")
        action_plan = "Action requise : Ajustement tarifaire d'urgence et activation campagne défensive."

    updated = {"action_plan": action_plan}
    await send_enterprise_alert({**state, **updated})
    return updated


async def persistence_node(state: AgentState) -> dict:
    _update_brain_state("persistence", state.get("threat_level", 0), "Indexation Cognee...")
    await asyncio.to_thread(save_analysis_to_history, state)

    if _COGNEE_AVAILABLE:
        try:
            content = json.dumps({
                "url":          state.get("target_url", ""),
                "threat_level": state.get("threat_level", 0),
                "signals":      state.get("market_signals", []),
                "action_plan":  state.get("action_plan", ""),
                "timestamp":    datetime.now(timezone.utc).isoformat(),
            }, ensure_ascii=False)
            await asyncio.wait_for(
                cognee.add(content, dataset_name="omniwarroom_intel"),
                timeout=5.0,
            )
            asyncio.get_running_loop().create_task(_bg_cognify())
            print("🧠 [Cognee] Intelligence queued for knowledge graph indexing.")
        except Exception as e:
            print(f"🧠 [Cognee] Persistence failed: {e}")

    _update_brain_state("idle", 0, "Mémoire enrichie — cycle terminé")
    return {}


# 5. Routeur
def route_threat(state: AgentState):
    if state.get("threat_level", 0) >= THREAT_THRESHOLD:
        print("🚨 Menace détectée -> Tacticien.")
        return "tactician"
    print("✅ Stable -> Fin.")
    return END

# 6. Compilation
builder = StateGraph(AgentState)
builder.add_node("scout", scout_node)
builder.add_node("analyst", analyst_node)
builder.add_node("tactician", tactician_node)
builder.add_node("persistence", persistence_node)

builder.add_edge(START, "scout")
builder.add_edge("scout", "analyst")
builder.add_conditional_edges(
    "analyst", route_threat,
    {"tactician": "tactician", END: "persistence"},
)
builder.add_edge("tactician", "persistence")
builder.add_edge("persistence", END)

war_room_graph = builder.compile()
