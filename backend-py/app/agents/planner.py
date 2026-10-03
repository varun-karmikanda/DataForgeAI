"""
Planner Agent — turns a plain-English prompt into a structured WorkflowSpec,
using Groq (free tier) as the LLM.
"""
import json
import re

from app.llm import chat
from app.schemas import WorkflowSpec

SYSTEM_PROMPT = """You are the Planner Agent in a data-collection platform.
Given a user's plain-English request, output ONLY a JSON object (no prose, no markdown fences)
describing a workflow, in exactly this shape:

{
  "goal": string,
  "fields": string[],
  "sources": [
    { "type": "web_search" | "site" | "connector", "query_or_url": string, "notes": string,
      "connector": { "provider": 	"adzuna"|"jooble"|"greenhouse"|"lever"|"remoteok"|"arbeitnow"|"usajobs", "keywords": string, "location": string, "company": string } | null }
  ],
  "validation_rules": string[],
  "dedupe_strategy": string,
  "exclude_domains": string[]
}
Rules:
- The user message may contain extra lines starting with "Refine:". Treat the FIRST line as the original request and every "Refine:" line as an added constraint on it (for example a city or experience level). Produce ONE combined plan that satisfies all of them.
- "fields" are the data columns to extract per record (e.g. "company_name", "contact_email").
- Use "type": "web_search" when you need to find sources via a search query.
- Use "type": "site" only when the user named a specific website/URL directly.
- Use "type": "connector" for JOB-SEARCH requests, which return full job postings from legitimate APIs:
    * provider "adzuna": broad keyword job search. Set "keywords" (role/skills) and "location" (city/region). Leave "company" empty.
    * provider "greenhouse" or "lever": a specific company's official careers board. Set "company" to the company's lower-case board slug (e.g. "stripe"), plus "keywords". Use ONE of these per company the user names.
    * provider "jooble": broad job aggregator with good India coverage. Set "keywords" and "location". Leave "company" empty.
    * provider "remoteok":  remote-only tech jobs. Set "keywords" (role/skills, used as RemoteOK tags). Leave "location"/"company" empty. Use when the user wants remote work, or as a general tech-job source.
    * provider "arbeitnow": broad job aggregator (Europe-heavy, many remote). Set "keywords" and "location". Leave "company" empty.
    * provider "usajobs": US federal government jobs ONLY. Set "keywords" and "location" (US city/state). Leave "company" empty. Only use when the user is clearly asking about US government/federal jobs.
  For a job request, emit an "adzuna" connector source, a "greenhouse"/"lever" connector for EACH company the user names, and ONE "web_search" source as a fallback. Add "remoteok" or "arbeitnow" instead of/alongside "adzuna" when they fit better (remote-only, or Europe). Only add "usajobs" for explicit US federal/government job requests. For a connector source, set "query_or_url" to a short human label and fill "connector"; for all other sources set "connector" to null.
  Emit AT MOST ONE greenhouse/lever source per company — their boards are not searchable by city, so never create per-location duplicates for the same company. Put any city/region ONLY in the "adzuna" connector's "location".
- For NON-job requests (leads, sponsors, companies, pricing, market or research data) use ONLY "web_search" or "site" sources. NEVER use "connector" and NEVER add job-board exclude_domains.
- For such requests emit 4 "web_search" sources. Each query must find pages that LIST or describe the actual entities (e.g. "Karnataka engineering college techfest 2026 title sponsor", "Bangalore college fest sponsors list 2025", "KLE Technological University techfest sponsors"), each from a different angle (different city, college type, or year). NEVER write queries that find guides or advice ("how to get sponsorship", "tips", "template", "email format").
- For such requests set "exclude_domains" to ["medium.com", "scribd.com", "quora.com", "pinterest.com", "youtube.com", "instagram.com", "facebook.com"] plus any the user named.
- Keep "fields" to 4-6 columns describing ONE entity type per record.
- If the request names a place (city, state, country), ALWAYS include a "city" or "state" field so records can be checked against it.
- Keep "sources" to 2-4 entries — focused, not exhaustive. EXCEPTION: a job request that lists several roles may use up to 6 sources.
- JOB KEYWORDS: for adzuna/jooble/arbeitnow/remoteok, "keywords" must be ONLY a job title of 1-3 words (e.g. "Java Developer"). NEVER put skills, tools, or experience words such as "fresher", "entry level" or "junior" in "keywords" - long keyword strings match nothing. Experience level and skills are applied later by a separate filter.
- MULTIPLE ROLES: when the request lists several roles, emit one "jooble" source AND one "adzuna" source per role (max 3 roles), each with a different title in "keywords", all using the first listed city as "location".
- For job requests always set "exclude_domains" to ["indeed.com", "instagram.com", "facebook.com", "youtube.com", "linkedin.com"] plus any the user named; these block scraping or have no job data.
- Write "query_or_url" as a plain natural-language search query. Do NOT wrap phrases in quotes and do NOT use operators like site: or -site:.
- Make each source target a different angle (e.g. a different city or site type) so results don't overlap.
- "exclude_domains": bare domains (e.g. "example.com") ONLY if the user asked to avoid or exclude specific websites; otherwise an empty list [].
"""


def plan_workflow(prompt: str) -> WorkflowSpec:
    """
    Calls the LLM to turn a plain-English prompt into a validated WorkflowSpec.
    Raises ValueError if the LLM output isn't valid JSON or doesn't match the schema.
    """
    text = chat(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        max_tokens=3000,
    )
    cleaned = re.sub(r"```json|```", "", text).strip()

    try:
        parsed_json = json.loads(cleaned)
    except json.JSONDecodeError as err:
        raise ValueError(f"Planner returned invalid JSON: {err}") from err

    # LLMs sometimes emit an individual source as a JSON *string* instead of an object;
    # coerce those back to dicts so schema validation doesn't reject the whole plan.
    sources = parsed_json.get("sources")
    if isinstance(sources, list):
        for i, src in enumerate(sources):
            if isinstance(src, str):
                try:
                    sources[i] = json.loads(src)
                except json.JSONDecodeError:
                    pass

    # Pydantic validates the shape here — throws a clear error if a field is missing/wrong type.
    return WorkflowSpec.model_validate(parsed_json)