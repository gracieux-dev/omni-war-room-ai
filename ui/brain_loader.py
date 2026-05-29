"""
brain_loader.py — helpers for the WarRoom Brain neural visualization.

Usage in app.py:
    from brain_loader import get_brain_html, write_brain_state_file
    st.components.v1.html(get_brain_html(), height=320, scrolling=False)
"""

import json
import time
from pathlib import Path

_HERE      = Path(__file__).parent
_HTML_FILE = _HERE / "brain_component.html"
_STATIC    = _HERE / "static"
_STATE_FILE = _STATIC / "worker_brain_state.json"

# URL served by Streamlit static file server (enableStaticServing = true)
_POLL_URL = "/app/static/worker_brain_state.json"


def get_brain_html(poll_url: str = _POLL_URL) -> str:
    """Read brain_component.html, inject the polling URL, return ready HTML."""
    html = _HTML_FILE.read_text(encoding="utf-8")
    return html.replace("__POLL_PATH__", poll_url)


def write_brain_state_file(
    agent: str,
    threat_level: int = 0,
    target_url: str = "",
    log: str = "",
) -> None:
    """Atomically write brain state to ui/static/worker_brain_state.json.

    Uses write-to-tmp + os.replace() to avoid the uvicorn Content-Length
    race condition when Streamlit static serving reads the file mid-write.
    """
    try:
        _STATIC.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {
                "agent": str(agent),
                "threat_level": max(0, min(5, int(threat_level))),
                "target_url": str(target_url)[:120],
                "log": str(log)[:120],
                "timestamp": int(time.time()),
            },
            ensure_ascii=False,
        )
        _tmp = _STATE_FILE.with_suffix(".tmp")
        _tmp.write_text(payload, encoding="utf-8")
        import os as _os
        _os.replace(_tmp, _STATE_FILE)
    except Exception:
        pass
