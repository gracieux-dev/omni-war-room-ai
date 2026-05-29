import os
import re
import urllib.parse
import httpx
from html.parser import HTMLParser

_BD_API = "https://api.brightdata.com/request"


class _HTMLTextExtractor(HTMLParser):
    """Strips HTML tags, skips script/style/nav, returns readable plain text."""

    _SKIP_TAGS = {"script", "style", "nav", "footer", "header", "noscript", "meta", "link"}

    def __init__(self):
        super().__init__()
        self._texts: list = []
        self._skip_depth: int = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth == 0:
            text = data.strip()
            if text:
                self._texts.append(text)

    def result(self) -> str:
        return " ".join(self._texts)


def _extract_text(html: str, max_chars: int = 5000) -> str:
    extractor = _HTMLTextExtractor()
    try:
        extractor.feed(html)
        text = extractor.result()
    except Exception:
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()
    return text[:max_chars]


def _headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


async def fetch_competitor_data(url: str) -> dict:
    api_key = os.getenv("BRIGHT_DATA_API_KEY")
    zone    = os.getenv("BRIGHT_DATA_UNLOCKER_ZONE", "cli_unlocker")

    if not api_key:
        return {"error": "BRIGHT_DATA_API_KEY non défini.", "url": url, "raw_content": ""}

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                _BD_API,
                headers=_headers(api_key),
                json={"zone": zone, "url": url, "format": "raw"},
            )
            response.raise_for_status()

        return {
            "url": url,
            "status_code": response.status_code,
            "raw_content": _extract_text(response.text),
        }

    except httpx.HTTPStatusError as e:
        code = e.response.status_code
        msg  = (f"Authentification Bright Data échouée (HTTP {code}) — vérifie BRIGHT_DATA_API_KEY."
                if code in (401, 403, 407) else f"HTTP {code} reçu depuis la cible.")
        print(f"🔴 [Scout] {msg}")
        return {"error": msg, "url": url, "raw_content": ""}
    except httpx.TimeoutException:
        print("🔴 [Scout] Timeout après 60s.")
        return {"error": "Timeout après 60 secondes.", "url": url, "raw_content": ""}
    except Exception as e:
        msg = f"Erreur inattendue ({type(e).__name__}) : {e}"
        print(f"🔴 [Scout] {msg}")
        return {"error": msg, "url": url, "raw_content": ""}


async def fetch_serp_sentiment(query: str) -> str:
    api_key = os.getenv("BRIGHT_DATA_API_KEY")
    zone    = os.getenv("BRIGHT_DATA_SERP_ZONE", "cli_unlocker")

    if not api_key:
        return "SERP non disponible : BRIGHT_DATA_API_KEY manquant."

    google_url  = f"https://www.google.com/search?q={urllib.parse.quote_plus(query)}&hl=fr&num=5"
    dedicated   = zone != "cli_unlocker"
    fmt         = "json" if dedicated else "raw"

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(
                _BD_API,
                headers=_headers(api_key),
                json={"zone": zone, "url": google_url, "format": fmt},
            )
            response.raise_for_status()

        if dedicated:
            data    = response.json()
            organic = data.get("organic", [])
            if not organic:
                return "SERP : aucun résultat organique retourné."
            lines = []
            for i, r in enumerate(organic[:5], 1):
                title   = r.get("title", "Sans titre")
                snippet = r.get("description") or r.get("snippet", "")
                lines.append(f"{i}. {title}\n   {snippet}")
            return "\n".join(lines)
        else:
            # cli_unlocker sur Google : extraction texte du HTML brut
            text = _extract_text(response.text, max_chars=3000)
            if not text:
                # Dernier recours : retourner les 2000 premiers chars du HTML brut
                raw = response.text[:2000] if response.text else ""
                return raw or "SERP : aucun contenu récupérable via cli_unlocker."
            return text

    except httpx.HTTPStatusError as e:
        code = e.response.status_code
        msg  = (f"Authentification Bright Data SERP échouée (HTTP {code})."
                if code in (401, 403, 407) else f"SERP erreur HTTP {code}.")
        print(f"🔴 [SERP] {msg}")
        return msg
    except httpx.TimeoutException:
        print("🔴 [SERP] Timeout après 45s.")
        return "SERP erreur : timeout après 45 secondes."
    except Exception as e:
        msg = f"SERP erreur ({type(e).__name__}) : {e}"
        print(f"🔴 [SERP] {msg}")
        return msg


async def diagnose_connections() -> None:
    """Diagnostic rapide des deux connexions Bright Data."""
    api_key = os.getenv("BRIGHT_DATA_API_KEY")
    zone    = os.getenv("BRIGHT_DATA_UNLOCKER_ZONE", "cli_unlocker")

    print("=" * 55)
    print("  DIAGNOSTIC BRIGHT DATA CONNECTIONS")
    print("=" * 55)
    print(f"  API_KEY          : {'✅ défini' if api_key else '❌ MANQUANT'}")
    print(f"  UNLOCKER_ZONE    : {zone}")
    print(f"  SERP_ZONE        : {os.getenv('BRIGHT_DATA_SERP_ZONE', 'cli_unlocker (défaut)')}")
    print("-" * 55)

    print("  [1/2] Test Web Unlocker → https://httpbin.org/ip ...")
    result = await fetch_competitor_data("https://httpbin.org/ip")
    if result.get("raw_content"):
        print(f"  ✅ Web Unlocker OK — {result['raw_content'][:80]}")
    else:
        print(f"  ❌ Web Unlocker FAIL — {result.get('error')}")

    print("  [2/2] Test SERP → query 'prix concurrent' ...")
    serp = await fetch_serp_sentiment("prix concurrent")
    ok   = serp and "erreur" not in serp.lower() and "non disponible" not in serp.lower()
    print(f"  {'✅ SERP OK' if ok else '❌ SERP FAIL'} — {serp[:80]}")

    print("=" * 55)


if __name__ == "__main__":
    import asyncio
    from dotenv import load_dotenv
    load_dotenv()
    asyncio.run(diagnose_connections())
