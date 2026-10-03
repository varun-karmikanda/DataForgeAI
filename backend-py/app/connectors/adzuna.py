"""
Adzuna connector — free job-search aggregator API (needs ADZUNA_APP_ID + ADZUNA_APP_KEY).
Docs: https://developer.adzuna.com/  Returns [] gracefully when keys are missing.
"""
import os

import httpx

from app.schemas import ConnectorParams, ResolvedResult

MAX_RESULTS = 20  # per page
MAX_PAGES = 4
_ALT_SPELLING = {"bangalore": "Bengaluru", "bengaluru": "Bangalore"}
DEFAULT_COUNTRY = os.environ.get("ADZUNA_COUNTRY", "in")  # 'in' = India; 'gb','us', etc.


def _attempts(params: ConnectorParams) -> list[dict]:
    words = params.keywords.split()
    loc = params.location.strip()
    alt_loc = _ALT_SPELLING.get(loc.lower(), "")
    attempts: list[dict] = []

    def add(extra: dict, where: str):
        attempt = {**extra}
        if where:
            attempt["where"] = where
        if attempt not in attempts:
            attempts.append(attempt)

    if words:
        add({"what": " ".join(words)}, loc)
        add({"what_or": " ".join(words)}, loc)
        if alt_loc:
            add({"what_or": " ".join(words)}, alt_loc)
        if len(words) > 3:
            add({"what": " ".join(words[:3])}, loc)
        add({"what_or": " ".join(words)}, "")
    else:
        add({}, loc)
    return attempts


def _search(base: dict, attempt: dict) -> list[dict]:
    jobs: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        url = f"https://api.adzuna.com/v1/api/jobs/{DEFAULT_COUNTRY}/search/{page}"
        resp = httpx.get(url, params={**base, **attempt}, timeout=30)
        resp.raise_for_status()
        batch = resp.json().get("results", [])
        jobs.extend(batch)
        if len(batch) < MAX_RESULTS:
            break
    return jobs


def fetch(params: ConnectorParams) -> list[ResolvedResult]:
    app_id = os.environ.get("ADZUNA_APP_ID", "").strip()
    app_key = os.environ.get("ADZUNA_APP_KEY", "").strip()
    if not app_id or not app_key:
        print("[connector] adzuna skipped: ADZUNA_APP_ID / ADZUNA_APP_KEY not set")
        return []

    base = {
        "app_id": app_id,
        "app_key": app_key,
        "results_per_page": MAX_RESULTS,
        "content-type": "application/json",
        "sort_by": "date",
    }

    jobs: list[dict] = []
    for attempt in _attempts(params):
        jobs = _search(base, attempt)
        print(f"[connector] adzuna {attempt} -> {len(jobs)} raw jobs")
        if jobs:
            break

    out: list[ResolvedResult] = []
    for job in jobs:
        title = job.get("title") or ""
        company = (job.get("company") or {}).get("display_name") or ""
        loc = (job.get("location") or {}).get("display_name") or ""
        desc = job.get("description") or ""
        raw = f"Title: {title}\nCompany: {company}\nLocation: {loc}\n\n{desc}"
        out.append(
            ResolvedResult(
                url=job.get("redirect_url") or "",
                title=title,
                snippet=desc[:300],
                raw_content=raw,
            )
        )
    return out