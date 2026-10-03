"""
Job connectors — resolve a ConnectorParams into real job postings via legitimate
public APIs (no scraping of gated sites). Each connector returns a list of
ResolvedResult where raw_content holds the full posting text, so the Extraction
Agent can verify the user's criteria (experience, location, etc.) against the
actual posting rather than a search snippet.
"""
import re
import time

import httpx

from app.schemas import ConnectorParams, ResolvedResult

from . import adzuna, arbeitnow, greenhouse, jooble, lever, remoteok, usajobs

_PROVIDERS = {
    "adzuna": adzuna.fetch,
    "jooble": jooble.fetch,
    "greenhouse": greenhouse.fetch,
    "lever": lever.fetch,
    "remoteok": remoteok.fetch,
    "arbeitnow": arbeitnow.fetch,
    "usajobs": usajobs.fetch,
}


MAX_TRIES = 3          # 1 try + 2 retries for temporary errors
RETRY_DELAYS = (1.5, 3.0)
_SECRET_RE = re.compile(r"(app_key|api_key|apikey|key|token|secret|password)=[^&\s'\"]+", re.IGNORECASE)


_PATH_KEY_RE = re.compile(r"/api/[0-9A-Za-z-]{16,}")  # Jooble puts the key in the URL path


def _redact(text: str) -> str:
    """Error messages from httpx contain the full request URL, including API keys - hide them."""
    text = _PATH_KEY_RE.sub("/api/***", text)
    return _SECRET_RE.sub(r"\1=***", text)


def _is_transient(err: Exception) -> bool:
    """Temporary problems worth retrying: provider overloaded (5xx / 429), timeouts, dropped connections."""
    if isinstance(err, httpx.HTTPStatusError):
        code = err.response.status_code
        return code == 429 or code >= 500
    return isinstance(err, (httpx.TimeoutException, httpx.TransportError))


def fetch_postings(params: ConnectorParams) -> list[ResolvedResult]:
    """Dispatch to the right provider. Never raises - a failing connector returns []."""
    fn = _PROVIDERS.get(params.provider)
    if fn is None:
        print(f"[connector] unknown provider: {params.provider!r}")
        return []
    for attempt in range(1, MAX_TRIES + 1):
        try:
            results = fn(params)
            print(f"[connector] {params.provider} -> {len(results)} postings")
            return results
        except Exception as err:  # noqa: BLE001 - a broken connector must not kill the run
            if attempt < MAX_TRIES and _is_transient(err):
                delay = RETRY_DELAYS[attempt - 1]
                print(f"[connector] {params.provider} temporary error ({_redact(str(err))[:90]}); retry {attempt}/{MAX_TRIES - 1} in {delay}s")
                time.sleep(delay)
                continue
            print(f"[connector] {params.provider} failed: {_redact(str(err))[:160]}")
            return []
    return []
