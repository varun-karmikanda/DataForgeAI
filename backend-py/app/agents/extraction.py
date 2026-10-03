"""
Extraction Agent — for one resolved source, fetches the page, pulls the requested
fields via the LLM, and captures the exact snippet each record's data came from.
"""
import json
import os
import re

import httpx
import trafilatura
from rapidfuzz import fuzz
from urllib.parse import urljoin

from app.llm import chat, provider
from app.robots import is_allowed
from app.agents.freshness import check_links, find_deadline, min_years_required, posting_status
from app.schemas import ExtractedRecord, ResolvedSource, SourceExtractionResult

MIN_FILLED_RATIO = 0.34  # drop records where fewer than this share of fields have a value
# Groq free tier is capped at 8K tokens/min, so send little; Gemini can take far more per call.
MAX_CHARS_TO_LLM = int(os.environ.get("MAX_CHARS_TO_LLM", "40000" if provider() == "gemini" else "6000"))


def invoke_llm(messages: list, max_tokens: int | None = None) -> str:
    """Shared LLM call for extraction.py and critic.py (provider + rate-limit retry live in app/llm.py)."""
    return chat(messages, max_tokens=max_tokens)


def _head_tail(text: str) -> str:
    """Keep the start AND the end of long pages (job requirements are usually at the end)."""
    if len(text) <= MAX_CHARS_TO_LLM:
        return text
    head = int(MAX_CHARS_TO_LLM * 0.6)
    return text[:head] + "\n[...]\n" + text[-(MAX_CHARS_TO_LLM - head):]


def fetch_page_text(url: str) -> str:
    resp = httpx.get(url, timeout=15, follow_redirects=True, headers={"User-Agent": "DataForgeAI/1.0"})
    resp.raise_for_status()
    text = trafilatura.extract(resp.text, include_links=True) or ""
    return _head_tail(text)


THIN_PAGE_CHARS = 4000  # below this, the page is probably a JS shell with no real content


def _tavily_extract(url: str) -> str:
    """Tavily's advanced extractor renders JS-heavy pages that a plain HTML fetch can't read."""
    from tavily import TavilyClient

    client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    response = client.extract(urls=[url], extract_depth="advanced")
    results = response.get("results", [])
    return (results[0].get("raw_content") or "") if results else ""


def get_page_text(result) -> str:
    """Tavily search text if it is substantial; otherwise try Tavily's advanced extractor, then our own fetch."""
    raw = (getattr(result, "raw_content", None) or "").strip()
    if len(raw) >= THIN_PAGE_CHARS:
        return _head_tail(raw)
    try:
        deep = _tavily_extract(result.url).strip()
        if len(deep) > len(raw):
            print(f"[extraction] thin page {result.url}: {len(raw)} -> {len(deep)} chars via Tavily extract")
            return _head_tail(deep)
    except Exception as err:  # noqa: BLE001
        print(f"[extraction] Tavily extract failed for {result.url}: {err}")
    if len(raw) > 500:
        return _head_tail(raw)
    return fetch_page_text(result.url)


def _extraction_prompt(fields: list, page_text: str, goal: str = "") -> str:
    field_list = ", ".join(fields)
    goal_block = (
        f"""The user's goal: {goal}
Skip records that clearly don't match this goal (location, seniority, topic, etc.).
NEVER copy wording from the goal into a value. Every value must be copied exactly as the page states it
(e.g. if the page says "3+ years", write "3+ years" even if the goal says freshers).
"""
        if goal
        else ""
    )
    return f"""You are the Extraction Agent in a data-collection platform.
{goal_block}Given the page text below, extract EVERY distinct record you can find (all rows, cards and list items, not just the first), using exactly
these fields: {field_list}.
Only use values that appear in the page text. Never guess or invent a value; use null instead.
For each record, also include "citation_snippet": the exact short quote (under 25 words)
from the page text that the record's data came from.

Output ONLY a JSON array (no prose, no markdown fences), shape:
[{{ "data": {{"field": "value", ...}}, "citation_snippet": string }}]

If a field isn't present for a record, set it to null. If you find nothing, output [].

Page text:
---
{page_text}
---"""


def _salvage_json_array(text: str) -> list:
    """Recover complete objects from a truncated JSON array."""
    decoder = json.JSONDecoder()
    start = text.find("[")
    if start == -1:
        return []
    idx, out = start + 1, []
    while idx < len(text):
        while idx < len(text) and text[idx] in " \n\r\t,":
            idx += 1
        if idx >= len(text) or text[idx] != "{":
            break
        try:
            obj, end = decoder.raw_decode(text, idx)
        except json.JSONDecodeError:
            break
        out.append(obj)
        idx = end
    return out


def extract_records_from_text(page_text: str, fields: list, goal: str = "") -> list:
    text = invoke_llm([{"role": "user", "content": _extraction_prompt(fields, page_text, goal)}])
    cleaned = re.sub(r"```json|```", "", text).strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        parsed = _salvage_json_array(cleaned)
        print(f"[extraction] JSON parse failed; salvaged {len(parsed)} records. Output starts: {cleaned[:200]!r}")
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]  # drop any malformed non-object entries


GROUNDING_THRESHOLD = 80


def _norm(text) -> str:
    return re.sub(r"\s+", " ", str(text)).strip().lower()


def _squash(text) -> str:
    return re.sub(r"\s+", "", str(text)).lower()


def _is_grounded(value, norm_text: str, squashed_text: str) -> bool:
    v = _norm(value)
    if not v:
        return False
    if v in norm_text or _squash(v) in squashed_text:
        return True
    if re.search(r"\d", v) and len(v) <= 40:
        return False  # numbers, dates and links must appear exactly as written
    if len(v) < 4:
        return False  # short values must match exactly
    return fuzz.partial_ratio(v, norm_text) >= GROUNDING_THRESHOLD


def _ground(data: dict, page_text: str) -> dict:
    """Null out any value that can't be found in the page text (guards against invented values)."""
    norm_text = _norm(page_text)
    squashed_text = _squash(page_text)
    out = {}
    for key, value in data.items():
        if value in (None, ""):
            out[key] = None
        elif _is_grounded(value, norm_text, squashed_text):
            out[key] = value
        else:
            print(f"[extraction] ungrounded, nulled: {key}={str(value)[:60]!r}")
            out[key] = None
    return out


FILTER_BATCH_SIZE = 15


_ENTRY_LEVEL_GOAL_RE = re.compile(
    r"fresher|entry[- ]?level|graduate|junior|trainee|intern\b|no experience|\b0\s*(?:-|to|–)\s*1\b",
    re.IGNORECASE,
)
_SENIOR_TITLE_RE = re.compile(
    r"\b(director|vp|vice president|president|chief|head|general manager|senior|sr\.?|principal|"
    r"staff|architect|lead(?!\s+generation)|manager)\b",
    re.IGNORECASE,
)
_JUNIOR_TITLE_RE = re.compile(r"trainee|intern|graduate|assistant|associate|junior|fresher", re.IGNORECASE)
_JOB_GOAL_RE = re.compile(
    r"\b(jobs?|hiring|vacanc\w*|openings?|careers?|positions?|recruit\w*|internships?|freshers?|walk-?in)\b",
    re.IGNORECASE,
)


def _is_job_goal(goal: str) -> bool:
    return bool(_JOB_GOAL_RE.search(goal or ""))


def _is_senior_for_entry_goal(record, goal: str) -> bool:
    """Free, no-LLM check: a senior job title can never satisfy a fresher / 0-1 year goal."""
    if not _ENTRY_LEVEL_GOAL_RE.search(goal or ""):
        return False
    titles = [
        str(v)
        for k, v in record.data.items()
        if v and any(h in k.lower() for h in ("title", "role", "position", "job_name"))
    ]
    title = " ".join(titles)
    if not title or _JUNIOR_TITLE_RE.search(title):
        return False
    return bool(_SENIOR_TITLE_RE.search(title))


ENTRY_MAX_YEARS = int(os.environ.get("ENTRY_MAX_YEARS", "1"))  # a "fresher" goal tolerates up to this many years


def _over_experience_for_entry_goal(text: str, goal: str) -> int | None:
    """Free, no-LLM check: returns the years asked for when it is more than a fresher goal allows."""
    if not _ENTRY_LEVEL_GOAL_RE.search(goal or ""):
        return None
    years = min_years_required(text)
    return years if years is not None and years > ENTRY_MAX_YEARS else None


def filter_relevant(records: list, goal: str) -> list:
    if goal:
        before = len(records)
        records = [r for r in records if not _is_senior_for_entry_goal(r, goal)]
        if len(records) < before:
            print(f"[extraction] dropped {before - len(records)} senior-title record(s) for entry-level goal (no LLM used)")
        kept_exp = []
        for r in records:
            text = (r.citation_snippet or "") + "\n" + " ".join(str(v) for v in r.data.values() if v)
            years = _over_experience_for_entry_goal(text, goal)
            if years is not None:
                print(f"[extraction] dropped {str(r.data)[:60]} -> asks {years}+ years experience (goal is entry-level)")
            else:
                kept_exp.append(r)
        records = kept_exp
    if not goal or len(records) <= FILTER_BATCH_SIZE:
        return _filter_relevant_batch(records, goal)
    kept: list = []
    for start in range(0, len(records), FILTER_BATCH_SIZE):
        kept.extend(_filter_relevant_batch(records[start:start + FILTER_BATCH_SIZE], goal))
    return kept


def _filter_relevant_batch(records: list, goal: str) -> list:
    """One small LLM call per source. Classifies each record against the goal and
    KEEPS anything that isn't a clear contradiction (keep-if-unsure): records whose
    criterion isn't stated are kept and tagged match_status="unconfirmed"."""
    if not goal or not records:
        return records
    lines = [
        f"{i}: " + json.dumps({k: (str(v)[:80] if v else None) for k, v in r.data.items()}, ensure_ascii=False)
        for i, r in enumerate(records)
    ]
    records_block = "\n".join(lines)
    prompt = f"""User goal: {goal}

Below are extracted records as "index: fields". Classify EACH record against the goal.
Return ONLY a JSON object: {{"verdicts": [{{"index": int, "status": "match"|"contradicts"|"unstated", "reason": string}}]}}
- "match": the record clearly satisfies the goal.
- "contradicts": a field clearly conflicts with the goal (wrong location, wrong experience level, unrelated role/topic).
  A seniority word in the job title that conflicts with the requested experience level also counts as "contradicts"
  (e.g. Director, Head, VP, Senior, Lead, Principal, General Manager when the goal asks for freshers / 0-1 years).
- "unstated": the goal's criterion is not present in the record (do NOT treat a null field as a contradiction).

Records:
{records_block}"""
    try:
        text = invoke_llm([{"role": "user", "content": prompt}], max_tokens=1200)
        parsed = json.loads(re.sub(r"```json|```", "", text).strip())
        verdicts = {v["index"]: v for v in parsed.get("verdicts", []) if isinstance(v.get("index"), int)}
    except Exception as err:  # noqa: BLE001 — never lose data because the filter failed
        print(f"[extraction] relevance filter skipped: {err}")
        for r in records:
            r.match_status = "unconfirmed"
            r.match_reason = "Relevance check skipped (AI rate-limited)"
        return records
    kept: list = []
    for i, record in enumerate(records):
        verdict = verdicts.get(i)
        status = verdict.get("status") if verdict else None
        if status == "contradicts":
            print(f"[extraction] dropped: {str(record.data)[:90]} -> {(verdict.get('reason') or '')[:80]}")
            continue  # only clear contradictions are dropped
        if status == "unstated":
            record.match_status = "unconfirmed"
            record.match_reason = (verdict.get("reason") or "")[:200]
        kept.append(record)
    unconfirmed = sum(1 for r in kept if r.match_status == "unconfirmed")
    print(f"[extraction] relevance filter kept {len(kept)}/{len(records)} ({unconfirmed} unconfirmed)")
    return kept


# Field-name buckets a connector-sourced posting can fill, keyed by keywords that might
# appear in whatever field names the Planner invents (e.g. "company_name", "employer").
# Order matters: first matching bucket wins.
_CONNECTOR_FIELD_BUCKETS = [
    (("title", "role", "position", "job_name"), "title"),
    (("compan", "employer", "agency", "org"), "company"),
    (("locat",), "location"),
    (("salary", "pay", "compensation", "wage"), "salary"),
    (("remote",), "remote"),
    (("tag", "skill", "categor"), "tags"),
    (("url", "link", "apply"), "url"),
    (("descript", "summary", "detail", "about"), "description"),
]


_DEADLINE_FIELD_HINTS = ("deadline", "last_date", "closing", "apply_by", "expiry", "expires")


def _fill_deadline_field(data: dict, text: str) -> None:
    """If the plan has a deadline-style column and the text states a last date, fill it."""
    deadline = find_deadline(text)
    if not deadline:
        return
    for field in list(data):
        if not data.get(field) and any(h in field.lower() for h in _DEADLINE_FIELD_HINTS):
            data[field] = deadline.isoformat()


def _parse_connector_record(raw_content: str, fallback_url: str, fields: list) -> dict:
    """
    Turns a connector's own structured "Title: X\nCompany: Y\n...\n\n<body>" text
    directly into a {field: value} dict — no LLM call. Connector responses are already
    structured data from a real API, not prose to guess at, so there's nothing to extract.
    """
    _EMPTY_SENTINELS = {"", "not listed", "none", "n/a", "null", "not specified"}
    lines = raw_content.split("\n")
    header: dict[str, str] = {}
    body_start = len(lines)
    for i, line in enumerate(lines):
        if not line.strip():
            body_start = i + 1
            break
        if ":" in line:
            key, _, value = line.partition(":")
            value = value.strip()
            if value.lower() not in _EMPTY_SENTINELS:
                header[key.strip().lower()] = value
    body = "\n".join(lines[body_start:]).strip()

    buckets = {
        "title": header.get("title", ""),
        "company": header.get("company") or header.get("agency", ""),
        "location": header.get("location", ""),
        "salary": header.get("salary", ""),
        "tags": header.get("tags", ""),
        "url": fallback_url,
        "description": body[:400].rsplit(" ", 1)[0] + ("..." if len(body) > 400 else ""),
    }
    remote_header = header.get("remote", "").strip().lower()
    if remote_header in ("true", "yes"):
        buckets["remote"] = "Remote"
    elif remote_header in ("false", "no"):
        buckets["remote"] = "On-site"
    elif "remote" in buckets["location"].strip().lower():
        buckets["remote"] = "Remote"
    else:
        buckets["remote"] = ""

    data: dict[str, str | None] = {}
    for field in fields:
        field_lower = field.lower()
        value = None
        for keywords, bucket in _CONNECTOR_FIELD_BUCKETS:
            if any(kw in field_lower for kw in keywords):
                value = buckets.get(bucket) or None
                break
        data[field] = value
    return data


def extract_from_connector_source(resolved_source: ResolvedSource, fields: list, goal: str = "") -> SourceExtractionResult:
    """Connector sources are already structured data — parse them directly, no LLM per posting."""
    records: list = []
    errors: list = []
    closed_count = 0

    for result in resolved_source.resolved:
        raw_content = result.raw_content or ""
        if not raw_content.strip():
            errors.append(f"{result.url}: connector returned no content")
            continue
        status, why = posting_status(raw_content)
        if status in ("closed", "expired"):
            closed_count += 1
            print(f"[freshness] dropped connector posting {result.url[:70]} -> {why}")
            continue
        years = _over_experience_for_entry_goal(raw_content, goal)
        if years is not None:
            print(f"[extraction] dropped connector posting {result.url[:60]} -> asks {years}+ years experience (goal is entry-level)")
            continue
        data = _parse_connector_record(raw_content, result.url, fields)
        _fill_deadline_field(data, raw_content)
        filled = sum(1 for f in fields if data.get(f))
        if filled < max(2, int(len(fields) * MIN_FILLED_RATIO)):
            continue  # posting didn't have enough of the requested fields
        snippet = raw_content.split("\n\n", 1)[0][:200]  # the header block itself, e.g. "Title: X\nCompany: Y"
        records.append(
            ExtractedRecord(
                source_url=result.url,
                data=data,
                citation_snippet=snippet,
                citation_url=result.url,
                match_status="match",  # came directly from the source's own structured feed, nothing to ground
            )
        )
    print(f"[extraction] connector {resolved_source.query_or_url!r} -> parsed {len(records)}/{len(resolved_source.resolved)} postings ({closed_count} closed/expired dropped), no LLM calls")

    records = filter_relevant(records, goal)  # one batched call for the whole source, not per-record

    # Only the survivors: open each apply link and drop ones whose page says the job is gone.
    link_results = check_links([r.source_url for r in records])
    if link_results:
        alive = []
        for r in records:
            status, why, page_years = link_results.get(r.source_url, ("unknown", "", None))
            if status == "closed":
                print(f"[freshness] dropped dead link {r.source_url[:70]} -> {why}")
            elif page_years is not None and _ENTRY_LEVEL_GOAL_RE.search(goal or "") and page_years > ENTRY_MAX_YEARS:
                print(f"[extraction] dropped {r.source_url[:60]} -> job page asks {page_years}+ years experience (goal is entry-level)")
            else:
                alive.append(r)
        print(f"[extraction] link check: {len(records) - len(alive)} dropped of {len(records)} (dead link or too much experience)")
        records = alive
    return SourceExtractionResult(query_or_url=resolved_source.query_or_url, records=records, fetch_errors=errors)


def extract_from_source(resolved_source: ResolvedSource, fields: list, goal: str = "") -> SourceExtractionResult:
    if resolved_source.type == "connector":
        return extract_from_connector_source(resolved_source, fields, goal)
    records: list = []
    errors: list = []

    for result in resolved_source.resolved:
        if not is_allowed(result.url):
            errors.append(f"{result.url}: skipped, disallowed by robots.txt")
            print(f"[extraction] ROBOTS BLOCKED {result.url}")
            continue
        try:
            page_text = get_page_text(result)
        except Exception as err:  # noqa: BLE001
            errors.append(f"{result.url}: {err}")
            print(f"[extraction] FETCH FAILED {result.url}: {str(err)[:120]}")
            continue

        if not page_text.strip():
            errors.append(f"{result.url}: no extractable text")
            print(f"[extraction] NO TEXT {result.url}")
            continue

        try:
            raw_records = extract_records_from_text(page_text, fields, goal)
        except Exception as err:  # noqa: BLE001 — rate limit exhausted retries, or another LLM failure
            errors.append(f"{result.url}: LLM extraction failed: {err}")
            print(f"[extraction] LLM FAILED {result.url}: {str(err)[:120]}")
            continue
        print(f"[extraction] {result.url} -> {len(page_text)} chars, {len(raw_records)} raw records")

        for raw in raw_records:
            data = _ground(raw.get("data", {}), page_text)
            for key, value in data.items():
                if isinstance(value, str) and value.startswith("/") and any(h in key.lower() for h in ("link", "url")):
                    data[key] = urljoin(result.url, value)  # make relative links absolute
            record_text = (raw.get("citation_snippet") or "") + "\n" + " ".join(str(v) for v in data.values() if v)
            if _is_job_goal(goal):
                status, why = posting_status(record_text)
                if status in ("closed", "expired"):
                    print(f"[freshness] dropped {str(data)[:70]} -> {why}")
                    continue
            _fill_deadline_field(data, record_text)
            filled = sum(1 for f in fields if data.get(f))
            if filled < max(2, int(len(fields) * MIN_FILLED_RATIO)):
                continue  # mostly-null record: page wasn't really a listing for this goal
            records.append(
                ExtractedRecord(
                    source_url=result.url,
                    data=data,
                    citation_snippet=raw.get("citation_snippet", ""),
                    citation_url=result.url,
                )
            )

    records = filter_relevant(records, goal)
    return SourceExtractionResult(query_or_url=resolved_source.query_or_url, records=records, fetch_errors=errors)


def extract_all(resolved_spec) -> list:
    """Sequential fallback (e.g. for local testing without Redis/RQ running)."""
    return [extract_from_source(source, resolved_spec.fields, resolved_spec.goal) for source in resolved_spec.sources]


def run_extraction_job(task_id: str, source_id: str, resolved_source_dict: dict, fields: list) -> dict:
    """RQ worker entrypoint: runs one source's extraction, writes to Postgres, publishes progress."""
    from app.db.database import get_session
    from app.db.models import Record
    from app.db.redis_client import publish_event

    resolved_source = ResolvedSource.model_validate(resolved_source_dict)
    result = extract_from_source(resolved_source, fields)

    with get_session() as db:
        for record in result.records:
            db.add(
                Record(
                    task_id=task_id,
                    source_id=source_id,
                    data_json=record.data,
                    citation_snippet=record.citation_snippet,
                    citation_url=record.citation_url,
                )
            )

    publish_event(task_id, "record:new", {"source_id": source_id, "count": len(result.records)})
    return {"source_id": source_id, "record_count": len(result.records), "errors": result.fetch_errors}