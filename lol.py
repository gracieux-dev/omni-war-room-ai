import os
from fpdf import FPDF

# ── Palette  - dark terminal aesthetic (matches worker.py Rich theme) ──────────
BG     = (7,   11,  20 )   # #070b14
CARD   = (10,  14,  24 )   # slightly lighter
CARD2  = (16,  20,  36 )   # alternate rows / header
BORDER = (30,  40,  68 )   # subtle border
CYAN   = (0,   180, 255)   # primary  - Bright Data / scout
VIOLET = (68,  99,  255)   # analyst / secondary
PINK   = (255, 34,  85 )   # danger / threat  #ff2255
LIME   = (0,   230, 100)   # success / persistence  #00e664
GOLD   = (255, 170, 0  )   # warning / tactician
TEXT   = (200, 216, 232)   # body text  #c8d8e8
MUTED  = (68,  88,  120)   # secondary text
DIM    = (40,  50,  78 )   # very muted / dividers
WHITE  = (255, 255, 255)

W, H  = 297, 210
M     = 20         # left/right margin
CW    = 257        # usable width = W - 2*M
YH    = 44         # content zone top (after header)
YF    = 193        # footer divider y
CH    = YF - YH    # 149mm  - max card height


class OmniWarRoomDeck(FPDF):

    def __init__(self):
        super().__init__(orientation="landscape", unit="mm", format="A4")
        self.set_margins(0, 0, 0)
        self.set_auto_page_break(auto=False)

    # ── Core drawing ────────────────────────────────────────────────────────

    def _fill(self, x, y, w, h, color):
        self.set_fill_color(*color)
        self.rect(x, y, w, h, "F")

    def _stroke(self, x, y, w, h, color, lw=0.3):
        self.set_draw_color(*color)
        self.set_line_width(lw)
        self.rect(x, y, w, h, "D")

    def _card(self, x, y, w, h, accent=None):
        self._fill(x, y, w, h, CARD)
        self._stroke(x, y, w, h, BORDER)
        color = accent or CYAN
        self._fill(x, y, w, 2.5, color)          # top accent bar
        self._corner_l(x, y, w, h, color)

    def _corner_l(self, x, y, w, h, color, s=9):
        self.set_draw_color(*color)
        self.set_line_width(0.7)
        self.line(x, y + s, x, y);  self.line(x, y, x + s, y)
        self.line(x + w, y + h - s, x + w, y + h)
        self.line(x + w, y + h, x + w - s, y + h)

    def _hline(self, x, y, w, color=BORDER, lw=0.3):
        self.set_draw_color(*color)
        self.set_line_width(lw)
        self.line(x, y, x + w, y)

    def _dot(self, x, y, sz, color):
        self._fill(x, y, sz, sz, color)

    # ── Typography ──────────────────────────────────────────────────────────

    def _eyebrow(self, x, y, text, color=MUTED):
        self.set_font("Helvetica", "B", 7.5)
        self.set_text_color(*color)
        self.set_xy(x, y)
        self.cell(CW, 4.5, text.upper())

    def _h1(self, x, y, text, w=CW, color=TEXT):
        self.set_font("Helvetica", "B", 22)
        self.set_text_color(*color)
        self.set_xy(x, y)
        self.multi_cell(w, 8.5, text)

    def _h2(self, x, y, text, w, color=TEXT):
        self.set_font("Helvetica", "B", 11.5)
        self.set_text_color(*color)
        self.set_xy(x, y)
        self.multi_cell(w, 5.5, text)

    def _label(self, x, y, text, w, color=MUTED, size=8.5, lh=4.8):
        self.set_font("Helvetica", "", size)
        self.set_text_color(*color)
        self.set_xy(x, y)
        self.multi_cell(w, lh, text)
        return self.get_y()

    def _mono(self, x, y, text, w, color=CYAN, size=8):
        self.set_font("Courier", "B", size)
        self.set_text_color(*color)
        self.set_xy(x, y)
        self.multi_cell(w, 4.5, text)
        return self.get_y()

    def _bullets(self, x, y, items, w, color=TEXT, size=8.5, lh=4.8, gap=2.5):
        cy = y
        for item in items:
            self.set_font("Helvetica", "B", size)
            self.set_text_color(*CYAN)
            self.set_xy(x, cy)
            self.cell(5, lh, "-")
            self.set_font("Helvetica", "", size)
            self.set_text_color(*color)
            self.set_xy(x + 5, cy)
            self.multi_cell(w - 5, lh, item)
            cy = self.get_y() + gap
        return cy

    def _chip(self, x, y, text, color=CYAN, text_color=None):
        self.set_font("Helvetica", "B", 7.5)
        tw = self.get_string_width(text) + 10
        self._fill(x, y, tw, 6.5, color)
        self.set_text_color(*(text_color or BG))
        self.set_xy(x + 1.5, y + 0.8)
        self.cell(tw - 3, 5, text, align="C")

    def _tag(self, x, y, text, color=DIM):
        self.set_font("Helvetica", "B", 7)
        tw = self.get_string_width(text) + 8
        self._fill(x, y, tw, 5.5, color)
        self._stroke(x, y, tw, 5.5, BORDER)
        self.set_text_color(*MUTED)
        self.set_xy(x + 1, y + 0.5)
        self.cell(tw - 2, 4.5, text, align="C")

    # ── Page chrome ──────────────────────────────────────────────────────────

    def _new_page(self, n: int, total: int = 9):
        self.add_page()
        self._fill(0, 0, W, H, BG)
        self._fill(0, 0, W, 2, CYAN)           # top accent stripe
        # ghost slide number
        self.set_font("Helvetica", "B", 80)
        self.set_text_color(*(14, 18, 38))
        self.set_xy(W - M - 62, 8)
        self.cell(62, 36, f"{n:02d}", align="R")
        # footer
        self._hline(M, YF, CW)
        self.set_font("Helvetica", "", 7)
        self.set_text_color(*MUTED)
        self.set_xy(M, YF + 3)
        self.cell(140, 4, "OmniWarRoom AI   Bright Data AI Agents Hackathon   Lablab.ai")
        self.set_xy(W - M - 36, YF + 3)
        self.cell(36, 4, f"{n:02d} / {total:02d}", align="R")

    def _slide_header(self, eyebrow_text, title, accent=CYAN):
        self._eyebrow(M, 15, eyebrow_text, MUTED)
        self._h1(M, 22, title)
        self._fill(M, 37, 70, 1.5, accent)     # decorative underline rule

    # ── Slides ───────────────────────────────────────────────────────────────

    def create_title_slide(self):
        self.add_page()
        self._fill(0, 0, W, H, BG)
        self._fill(0, 0, W, 2, CYAN)

        # Right panel
        px = 183
        self._fill(px, 0, W - px, H, CARD)
        self.set_draw_color(*BORDER)
        self.set_line_width(0.4)
        self.line(px, 0, px, H)

        # Ghost title text
        self.set_font("Helvetica", "B", 78)
        self.set_text_color(*(14, 18, 38))
        self.set_xy(M - 3, 52)
        self.cell(175, 44, "OWR")

        # Eyebrow
        self._eyebrow(M, 20, "Bright Data AI Agents & Web Data Hackathon  -  Lablab.ai", MUTED)

        # Title
        self.set_font("Helvetica", "B", 44)
        self.set_text_color(*TEXT)
        self.set_xy(M, 36)
        self.cell(163, 16, "OmniWarRoom")

        self.set_font("Helvetica", "B", 44)
        self.set_text_color(*CYAN)
        self.set_xy(M, 53)
        self.cell(163, 16, "AI")

        # Accent rule
        self._fill(M, 74, 110, 1.5, CYAN)

        # Tagline
        self.set_font("Helvetica", "", 11.5)
        self.set_text_color(*MUTED)
        self.set_xy(M, 80)
        self.multi_cell(160, 6,
            "Autonomous Multi-Agent Swarm for Real-Time\n"
            "Competitive Intelligence & Market Countermeasures")

        # Track chips
        self._chip(M, 103, "GTM Intelligence Track", CYAN)
        self._chip(M + 72, 103, "Risk & Compliance Track", PINK)

        # Right panel content
        rp = px + 10
        rw = W - px - 20

        self.set_font("Helvetica", "B", 7.5)
        self.set_text_color(*MUTED)
        self.set_xy(rp, 22)
        self.cell(rw, 4.5, "TECH STACK")
        self._hline(rp, 28, rw, BORDER)

        stack = [
            (CYAN,   "LangGraph 1.2.2",        "Orchestration"),
            (LIME,   "Bright Data MCP + REST",  "Web Intelligence"),
            (MUTED,  "Groq LLaMA 3.1-8B",       "Scout LLM"),
            (VIOLET, "Gemini 2.0 Flash",        "Analyst LLM"),
            (GOLD,   "Groq LLaMA 3.3-70B",      "Tactician LLM"),
            (LIME,   "Cognee 1.1.0 + LanceDB",  "Memory"),
            (MUTED,  "Pydantic v2 + Streamlit",  "Schema & UI"),
        ]
        ty = 34
        for color, name, role in stack:
            self._dot(rp, ty + 2, 3.5, color)
            self.set_font("Helvetica", "B", 8.5)
            self.set_text_color(*TEXT)
            self.set_xy(rp + 6, ty)
            self.cell(rw - 6, 4.5, name)
            self.set_font("Helvetica", "", 7.5)
            self.set_text_color(*MUTED)
            self.set_xy(rp + 6, ty + 5.5)
            self.cell(rw - 6, 4, role)
            ty += 13

        # Footer line
        self._hline(M, YF, CW)
        self.set_font("Helvetica", "", 7)
        self.set_text_color(*MUTED)
        self.set_xy(M, YF + 3)
        self.cell(180, 4, "OmniWarRoom AI   Bright Data AI Agents Hackathon   Lablab.ai")

    def create_problem_slide(self):
        self._new_page(2)
        self._slide_header("01 - Context", "The Problem & Our Answer", PINK)

        cw, gap = 124, 9
        lx, rx = M, M + cw + gap   # left x, right x

        # Left card  - threat
        self._card(lx, YH, cw, CH, PINK)
        self._eyebrow(lx + 12, YH + 10, "Three Blind Spots", PINK)
        self._h2(lx + 12, YH + 17, "Your Competitors Are Invisible", cw - 22, PINK)
        self._hline(lx + 12, YH + 31, cw - 22, DIM)
        self._bullets(lx + 12, YH + 36, [
            "Competitors reprice overnight - you find out Monday morning.",
            "DataDome & Akamai block every classic scraper with a 403.",
            "Manual analysis takes hours, the response window is gone.",
        ], cw - 22, TEXT, 9, 5.2, 3)
        self._tag(lx + 12, YH + CH - 14, "GTM Intelligence Track + Risk & Compliance Track", CARD2)

        # Right card  - solution
        self._card(rx, YH, cw, CH, LIME)
        self._eyebrow(rx + 12, YH + 10, "OmniWarRoom Answer", LIME)
        self._h2(rx + 12, YH + 17, "Three Forces Working For You", cw - 22, LIME)
        self._hline(rx + 12, YH + 31, cw - 22, DIM)
        self._bullets(rx + 12, YH + 36, [
            "Autonomous worker loop scans all targets 24/7, never stops.",
            "Bright Data Web Unlocker bypasses all bot shields natively.",
            "Threat scored, plan written, alert sent  - under 4 minutes.",
        ], cw - 22, TEXT, 9, 5.2, 3)
        self._tag(rx + 12, YH + CH - 14, "INTERVAL = 300s | THRESHOLD = 3/5", CARD2)

    def create_stack_slide(self):
        self._new_page(3)
        self._slide_header("02 - Architecture", "Technical Stack", VIOLET)

        self._card(M, YH, CW, CH, VIOLET)

        col_w   = [46, 68, 135]    # sum=249, padded inside card
        row_h   = 18
        pad_x   = M + 8
        headers = ["Layer", "Technology", "Role in Production"]
        ty      = YH + 8

        # header row
        self._fill(M + 2, ty, CW - 4, row_h, CARD2)
        cx = pad_x
        for i, hdr in enumerate(headers):
            self.set_font("Helvetica", "B", 7.5)
            self.set_text_color(*MUTED)
            self.set_xy(cx, ty + 5.5)
            self.cell(col_w[i], 5, hdr.upper())
            cx += col_w[i]

        rows = [
            ("Orchestration",   "LangGraph 1.2.2",
             "Async StateGraph, conditional routing scout->analyst->tactician->persistence"),
            ("Web Intelligence", "Bright Data MCP + REST",
             "Web Unlocker + SERP API  - bypasses DataDome, Akamai, Cloudflare"),
            ("Scout LLM",       "Groq llama-3.1-8b-instant",
             "Lightweight tool calling for MCP data collection, conserves TPM quota"),
            ("Analyst LLM",     "Gemini 2.0 Flash (primary)",
             "Structured output via Pydantic MarketAnalysisOutput, cascade to Qwen3-32B"),
            ("Tactician LLM",   "Groq llama-3.3-70b-versatile",
             "Counter-strategy plans (3-5 actions, ROI-framed) when threat >= 3"),
            ("Memory",          "Cognee 1.1.0 + LanceDB",
             "Persistent knowledge graph (NetworkX) indexed via cognee.add / cognify()"),
        ]

        cy = ty + row_h
        for ri, (layer, tech, role) in enumerate(rows):
            if ri % 2 == 0:
                self._fill(M + 2, cy, CW - 4, row_h, CARD2)
            self._hline(M + 2, cy, CW - 4, DIM)
            cx = pad_x
            dots = [CYAN, LIME, MUTED, VIOLET, GOLD, LIME]
            self._dot(cx - 5, cy + 7, 3, dots[ri])
            for ci, (txt, bold) in enumerate([(layer, True), (tech, False), (role, False)]):
                self.set_font("Helvetica", "B" if bold else "", 8.5 if bold else 8)
                self.set_text_color(*(TEXT if ci < 2 else MUTED))
                self.set_xy(cx, cy + 5.5)
                self.cell(col_w[ci], 6, txt)
                cx += col_w[ci]
            cy += row_h

    def create_brightdata_slide(self):
        self._new_page(4)
        self._slide_header("03 - Bright Data", "Bright Data: The Intelligence Layer", CYAN)

        cw, gap = 81, 7     # 3 * 81 + 2 * 7 = 257 = CW ✓

        cols = [
            (CYAN,   "WEB UNLOCKER",  "Bypass Every Bot Shield",
             "POWERS SCOUT NODE", [
                "DataDome, Akamai & Cloudflare blocked on every classic scraper.",
                "Residential IP rotation + browser fingerprinting per request.",
                "Scout agent gets clean HTML  - zero 403s at production scale.",
                "Raw output capped at MAX_RAW_CHARS = 3,500 chars (~875 tokens).",
            ]),
            (VIOLET, "SERP API",       "Google Search Intelligence",
             "POWERS ANALYST NODE", [
                "Structured organic results + People Also Ask per query.",
                "Cross-referenced with Web Unlocker data by Analyst node.",
                "Parsed JSON returned  - no HTML parsing, no retry logic.",
                "Output capped at MAX_SERP_CHARS = 1,500 chars (~375 tokens).",
            ]),
            (LIME,   "MCP SERVER",     "LLM-Native Tool Calling",
             "POWERS TOOL DISPATCH", [
                "streamable_http transport via MultiServerMCPClient.",
                "LLM binds tools dynamically  - no hardcoded scraping logic.",
                "One endpoint replaces 10+ custom scraping integrations.",
                "Hackathon track: Bright Data AI Agents & Web Data.",
            ]),
        ]

        for i, (color, eyebrow, title, badge, items) in enumerate(cols):
            x = M + i * (cw + gap)
            self._card(x, YH, cw, CH, color)
            self._eyebrow(x + 9, YH + 9, eyebrow, color)
            self._h2(x + 9, YH + 17, title, cw - 16, color)
            self._hline(x + 9, YH + 30, cw - 16, DIM)
            self._bullets(x + 9, YH + 35, items, cw - 16, TEXT, 8.5, 4.8, 2.5)
            self._chip(x + 9, YH + CH - 13, badge, color)

    def create_swarm_slide(self):
        self._new_page(5)
        self._slide_header("04 - Agent Logic", "The Multi-Agent Swarm", CYAN)

        cw, gap = 59, 7     # 4 * 59 + 3 * 7 = 257 = CW ✓

        agents = [
            (CYAN,   "SCOUT",       "llama-3.1-8b-instant", [
                "Binds Bright Data MCP tools dynamically via LangGraph.",
                "LLM decides what to fetch  - no hardcoded scraping.",
                "Web Unlocker: residential IP + browser fingerprint.",
                "Output capped: MAX_RAW_CHARS = 3,500 chars.",
            ], "MAX_RAW = 3,500 chars"),
            (VIOLET, "ANALYST",     "Gemini 2.0 Flash", [
                "Scores threat 1-5 via Pydantic MarketAnalysisOutput.",
                "Cross-refs Web Unlocker + SERP + Cognee memory.",
                "Auto-cascade: Qwen3-32B -> Qwen2.5-7B on 429.",
                "Conditional: threat >= 3 -> Tactician node.",
            ], "THRESHOLD = 3 / 5"),
            (GOLD,   "TACTICIAN",   "llama-3.3-70b-versatile", [
                "Fires only when threat_level >= THREAT_THRESHOLD.",
                "Generates 3-5 timed, ROI-framed counter-actions.",
                "Triggers email + Triggerware + pyttsx3 in parallel.",
                "Fallback: llm_fallback on HTTP 429 rate limit.",
            ], "3-5 ACTIONS / CYCLE"),
            (LIME,   "PERSISTENCE", "Cognee 1.1.0", [
                "Saves cycle to market_history.json (NDJSON).",
                "cognee.add() queues data to LanceDB + NetworkX.",
                "_bg_cognify() runs fire-and-forget (asyncio task).",
                "Analyst queries this graph in the next cycle.",
            ], "MAX JOURNAL = 300 lines"),
        ]

        for i, (color, name, model, items, stat) in enumerate(agents):
            x = M + i * (cw + gap)
            self._card(x, YH, cw, CH, color)

            self.set_font("Helvetica", "B", 10.5)
            self.set_text_color(*color)
            self.set_xy(x + 7, YH + 9)
            self.cell(cw - 12, 5.5, name)

            self.set_font("Courier", "", 7.5)
            self.set_text_color(*MUTED)
            self.set_xy(x + 7, YH + 16)
            self.cell(cw - 12, 4.5, model)

            self._hline(x + 7, YH + 23, cw - 12, DIM)

            cy = YH + 28
            for b in items:
                self.set_font("Helvetica", "B", 8)
                self.set_text_color(*color)
                self.set_xy(x + 7, cy)
                self.cell(5, 4.5, "-")
                self.set_font("Helvetica", "", 8)
                self.set_text_color(*TEXT)
                self.set_xy(x + 12, cy)
                self.multi_cell(cw - 18, 4.5, b)
                cy = self.get_y() + 2

            self._fill(x + 7, YH + CH - 13, cw - 14, 9, CARD2)
            self._stroke(x + 7, YH + CH - 13, cw - 14, 9, DIM)
            self.set_font("Courier", "B", 7)
            self.set_text_color(*color)
            self.set_xy(x + 9, YH + CH - 11)
            self.cell(cw - 18, 5, stat)

    def create_worker_slide(self):
        self._new_page(6)
        self._slide_header("05 - Automation", "The Autonomous Worker Engine", GOLD)

        self._card(M, YH, CW, CH, GOLD)

        points = [
            (CYAN, "Process Isolation",
             "worker.py is a standalone subprocess, fully decoupled from Streamlit ui/app.py."),
            (CYAN, "True Parallelism",
             "asyncio.gather() scans all competitor URLs simultaneously in each session cycle."),
            (LIME, "Atomic State Writes",
             "Brain state written via os.replace() on a .tmp file  - prevents race conditions."),
            (LIME, "Full Audit Trail",
             "All events appended to agent_journal.jsonl  - NDJSON, max 300 lines, auto-rotating."),
            (GOLD, "Multi-Channel Dispatch",
             "On critical threat: HTML email (SMTP auto-detect) + Triggerware webhook + pyttsx3 TTS."),
        ]

        # 2-col layout: max 2 rows of 2 + 1 last row
        col_w, col_gap = 118, 13
        cy = YH + 12
        for i, (color, title, body) in enumerate(points):
            col = i % 2
            if i == 4:                    # last item spans full width
                x = M + 12
                bw = CW - 24
            else:
                x = M + 12 + col * (col_w + col_gap)
                bw = col_w
            if i > 0 and col == 0:
                cy += 36

            self._dot(x, cy + 3, 4, color)
            self.set_font("Helvetica", "B", 9.5)
            self.set_text_color(*color)
            self.set_xy(x + 8, cy)
            self.cell(bw - 8, 5.5, title)
            self.set_font("Helvetica", "", 8.5)
            self.set_text_color(*MUTED)
            self.set_xy(x + 8, cy + 7)
            self.multi_cell(bw - 8, 4.8, body)

    def create_ui_slide(self):
        self._new_page(7)
        self._slide_header("06 - Dashboard", "Streamlit Interface", VIOLET)

        cw, gap = 124, 9
        lx, rx = M, M + cw + gap

        # Left card  - Control
        self._card(lx, YH, cw, CH, CYAN)
        self._eyebrow(lx + 12, YH + 10, "Control Plane", CYAN)
        self._h2(lx + 12, YH + 17, "Live Operations", cw - 22, CYAN)
        self._hline(lx + 12, YH + 30, cw - 22, DIM)
        self._bullets(lx + 12, YH + 35, [
            "SVG brain polls worker_brain_state.json every 1.5s via native JS.",
            "Voice command: Speechmatics REST transcribes WebM audio to URL list.",
            "One-click Deploy Swarm with live execution trace in the terminal panel.",
            "STRATEGIC ALERT card expands / collapses via postMessage iframe API.",
        ], cw - 22, TEXT, 8.5, 4.8, 2.5)

        # Right card  - Data
        self._card(rx, YH, cw, CH, GOLD)
        self._eyebrow(rx + 12, YH + 10, "Data Plane", GOLD)
        self._h2(rx + 12, YH + 17, "Market Intelligence", cw - 22, GOLD)
        self._hline(rx + 12, YH + 30, cw - 22, DIM)
        self._bullets(rx + 12, YH + 35, [
            "KPI row: total scans, critical count, avg threat, latest alert host.",
            "Plotly time-series chart per host with green / amber / red zones.",
            "History feed: expandable cards per critical scan with signals + plan.",
            "Worker tab: phase matrix (Rich table), live journal, GTM alert feed.",
        ], cw - 22, TEXT, 8.5, 4.8, 2.5)

    def create_governance_slide(self):
        self._new_page(8)
        self._slide_header("07 - Governance", "Human-in-the-Loop", LIME)

        cw, gap = 124, 9
        lx, rx = M, M + cw + gap

        # Left card  - Controls
        self._card(lx, YH, cw, CH, LIME)
        self._eyebrow(lx + 12, YH + 10, "Alert System", LIME)
        self._h2(lx + 12, YH + 17, "No Autonomous Action", cw - 22, LIME)
        self._hline(lx + 12, YH + 30, cw - 22, DIM)
        self._bullets(lx + 12, YH + 35, [
            "AI scores and plans  - never prices, spends, or messages autonomously.",
            "_SMTP_MAP: 14 email domains auto-mapped (Gmail, Outlook, Yahoo, etc.).",
            "HTML email: threat gauge, signals list, numbered action plan, CTAs.",
            "Subject: [ACTION REQUIRED] Threat X/5 (LABEL) on competitor-host.",
        ], cw - 22, TEXT, 8.5, 4.8, 2.5)

        # Right card  - Schema
        self._card(rx, YH, cw, CH, VIOLET)
        self._eyebrow(rx + 12, YH + 10, "Data Schema", VIOLET)
        self._h2(rx + 12, YH + 17, "Pydantic Enforcement", cw - 22, VIOLET)
        self._hline(rx + 12, YH + 30, cw - 22, DIM)

        fields = [
            ("competitor_name",  "str",   "Auto-identified from scraped page content"),
            ("threat_level",     "int",   "Normalised score 1-5 (threshold = 3)"),
            ("signals_detected", "list",  "Category + description + severity per signal"),
            ("confidence_score", "float", "LLM certainty score from 0.0 to 1.0"),
            ("action_plan",      "str",   "Generated by Tactician  - 3-5 timed actions"),
        ]
        fy = YH + 35
        for field, ftype, desc in fields:
            self.set_font("Courier", "B", 8)
            self.set_text_color(*CYAN)
            self.set_xy(rx + 12, fy)
            self.cell(60, 4.8, field)
            self.set_font("Courier", "", 8)
            self.set_text_color(*VIOLET)
            self.set_xy(rx + 74, fy)
            self.cell(20, 4.8, ftype)
            self.set_font("Helvetica", "", 7.5)
            self.set_text_color(*MUTED)
            self.set_xy(rx + 12, fy + 5.5)
            self.cell(cw - 22, 4, desc)
            self._hline(rx + 12, fy + 11, cw - 22, DIM)
            fy += 14

    def create_summary_slide(self):
        self._new_page(9)
        self._slide_header("08 - Why We Win", "What Makes OmniWarRoom AI Different", CYAN)

        cw, ch, gap = 124, 68, 9
        cards = [
            (CYAN,   "Sees Through Every Wall",
             "Bright Data Web Unlocker permanently removes DataDome, Akamai, Cloudflare."
             " No 403s, no blind spots, clean HTML at production scale."),
            (LIME,   "Production-Grade Swarm",
             "Async LangGraph, asyncio.gather parallel scans, os.replace atomic writes,"
             " LLM cascade failover, Cognee knowledge graph. Built to run unsupervised."),
            (GOLD,   "4-Minute Closed Loop",
             "Scout + Analyst + Tactician + Persistence. Raw web data becomes a qualified"
             " threat score and a ready counter-strategy in under 4 minutes, 24/7."),
            (PINK,   "Human-in-the-Loop",
             "AI analyses and recommends. Humans approve. Full audit trail in"
             " agent_journal.jsonl. Branded HTML alert with Approve / Reject CTA buttons."),
        ]

        for i, (color, title, body) in enumerate(cards):
            col = i % 2
            row = i // 2
            x = M + col * (cw + gap)
            y = YH + row * (ch + gap)

            self._card(x, y, cw, ch, color)

            # Left accent bar
            self._fill(x + 2.5, y + 2.5, 3, ch - 5, color)

            self.set_font("Helvetica", "B", 11)
            self.set_text_color(*color)
            self.set_xy(x + 13, y + 12)
            self.cell(cw - 20, 6, title)

            self.set_font("Helvetica", "", 8.5)
            self.set_text_color(*MUTED)
            self.set_xy(x + 13, y + 22)
            self.multi_cell(cw - 20, 5, body)

    # ── Entry point ──────────────────────────────────────────────────────────

    def generate(self, filename: str = "OmniWarRoom_PitchDeck.pdf") -> None:
        self.create_title_slide()
        self.create_problem_slide()
        self.create_stack_slide()
        self.create_brightdata_slide()
        self.create_swarm_slide()
        self.create_worker_slide()
        self.create_ui_slide()
        self.create_governance_slide()
        self.create_summary_slide()
        self.output(filename)
        print(f"Deck generated: {os.path.abspath(filename)}")


if __name__ == "__main__":
    OmniWarRoomDeck().generate()
