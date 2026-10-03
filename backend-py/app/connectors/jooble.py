"""
Jooble connector - official free job-search REST API (needs JOOBLE_API_KEY).
Get a free key at https://jooble.org/api/about   (registration, no credit card).
Docs: POST https://jooble.org/api/{api_key}  with JSON {"keywords", "location", "page", "ResultOnPage"}
Returns [] gracefully when the key is missing. Descriptions from Jooble are short snippets,
and links go through Jooble's own job pages - that is how their API is meant to be used.
"""
import html
import os
import re

import httpx

from app.schemas import ConnectorParams, ResolvedResult

MAX_RESULTS = 20  # jobs per page
MAX_PAGES = 2
_ALT_SPELLING = {"bangalore": "Bengaluru", "bengaluru": "Bangalore"}
_TAG_RE = re.compile(r"<[^>]+>")


def _clean(fragment: str) -> str:
    text = _TAG_RE.sub(" ", html.unescape(fragment or ""))
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def _attempts(params: ConnectorParams) -> list[dict]:
    keywords = params.keywords.strip()
    loc = params.location.strip()
    alt = _ALT_SPELLING.get(loc.lower(), "")
    attempts: list[dict] = []
    # exact city, then alternate spelling. No "anywhere" fallback when a city was requested:
    # it returns jobs from other countries that the relevance filter then throws away,
    # after spending LLM calls on them. (If no location was asked for, search anywhere.)
    for where in ((loc, alt) if loc else ("",)):
        if loc and not where:  # no alternate spelling exists for this city
            continue
        attempt = {"keywords": keywords, "location": where}
        if attempt not in attempts:
            attempts.append(attempt)
    return attempts


def _search(api_key: str, attempt: dict) -> list[dict]:
    jobs: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        resp = httpx.post(
            f"https://{os.environ.get('JOOBLE_HOST', 'jooble.org').strip()}/api/{api_key}",
            json={**attempt, "page": str(page), "ResultOnPage": str(MAX_RESULTS)},
            timeout=30,
        )
        resp.raise_for_status()
        batch = resp.json().get("jobs", [])
        jobs.extend(batch)
        if len(batch) < MAX_RESULTS:
            break
    return jobs


def fetch(params: ConnectorParams) -> list[ResolvedResult]:
    api_key = os.environ.get("JOOBLE_API_KEY", "").strip()
    if not api_key:
        print("[connector] jooble skipped: JOOBLE_API_KEY not set")
        return []

    jobs: list[dict] = []
    for attempt in _attempts(params):
        jobs = _search(api_key, attempt)
        print(f"[connector] jooble {attempt} -> {len(jobs)} raw jobs")
        if jobs:
            break

    out: list[ResolvedResult] = []
    for job in jobs:
        title = _clean(job.get("title", ""))
        company = _clean(job.get("company", ""))
        loc = _clean(job.get("location", ""))
        salary = _clean(job.get("salary", ""))
        snippet = _clean(job.get("snippet", ""))
        raw = f"Title: {title}\nCompany: {company}\nLocation: {loc}\nSalary: {salary}\n\n{snippet}"
        out.append(
            ResolvedResult(
                url=job.get("link") or "",
                title=title,
                snippet=snippet[:300],
                raw_content=raw,
            )
        )
    return out