"""Enrichment: fills empty email fields by searching for the college's own contact page."""
import os
import re
from urllib.parse import urlparse

from tavily import TavilyClient

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
JUNK = ("example.", "sentry", "wixpress", "noreply", "no-reply", ".png", ".jpg", ".webp", ".gif")
PREFERRED = ("sponsor", "event", "fest", "contact", "info", "admin", "principal", "office")
STOPWORDS = {
    "college", "of", "engineering", "university", "institute", "technology", "science",
    "sciences", "and", "the", "for", "deemed", "to", "be", "new", "school", "tech", "bangalore",
    "bengaluru", "mysuru", "mysore", "karnataka",
}
MAX_LOOKUPS = 8  # Tavily calls per run


def _tokens(name: str) -> list[str]:
    return [t for t in re.findall(r"[a-z]+", name.lower()) if len(t) >= 3 and t not in STOPWORDS]


def _email_field(data: dict) -> str | None:
    return next((k for k in data if "email" in k.lower()), None)


def _entity(data: dict):
    college = next((str(v) for k, v in data.items() if v and any(h in k.lower() for h in ("college", "institution", "university"))), None)
    fest = next((str(v) for k, v in data.items() if v and any(h in k.lower() for h in ("fest", "event"))), "")
    if not college:
        return None, None
    return college, f"{college} {fest} contact email sponsorship".strip()


def _find_email(client: TavilyClient, college: str, query: str):
    tokens = _tokens(college)
    if not tokens:
        return None
    try:
        res = client.search(query=query, max_results=4, include_raw_content=True)
    except Exception as err:  # noqa: BLE001
        print(f"[enrich] search failed: {str(err)[:80]}")
        return None
    candidates = []
    for r in res.get("results", []):
        host = urlparse(r["url"]).netloc.lower()
        text = (r.get("raw_content") or "") + " " + (r.get("content") or "")
        for email in set(EMAIL_RE.findall(text)):
            e = email.lower().strip(".")
            if any(j in e for j in JUNK):
                continue
            domain = e.split("@", 1)[1]
            if any(t in host or t in domain for t in tokens):  # must belong to this college
                candidates.append((e, r["url"]))
    if not candidates:
        return None
    candidates.sort(key=lambda c: 0 if any(p in c[0].split("@")[0] for p in PREFERRED) else 1)
    return candidates[0]


def enrich_emails(results: list) -> int:
    key = os.environ.get("TAVILY_API_KEY")
    if not key:
        return 0
    client = TavilyClient(api_key=key)
    done: dict = {}
    lookups = filled = 0
    for res in results:
        for rec in res.records:
            field = _email_field(rec.data)
            if not field or rec.data.get(field):
                continue
            college, query = _entity(rec.data)
            if not query:
                continue
            if query not in done:
                if lookups >= MAX_LOOKUPS:
                    continue
                lookups += 1
                done[query] = _find_email(client, college, query)
            hit = done[query]
            if hit:
                email, url = hit
                rec.data[field] = email
                rec.citation_snippet = f"{rec.citation_snippet} | email from {url}".strip(" |")
                filled += 1
    print(f"[enrich] {lookups} lookup(s), filled {filled} email(s)")
    return filled