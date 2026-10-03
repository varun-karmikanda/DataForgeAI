"""
Source-Discovery Agent — resolves each "web_search" source in a WorkflowSpec into
real URLs using Tavily (free tier), and passes "site" sources through as-is.
"""
import os
from urllib.parse import urlparse

from tavily import TavilyClient

from app.schemas import ResolvedResult, ResolvedSource, ResolvedWorkflowSpec, WorkflowSpec

MAX_RESULTS_PER_SOURCE = 5


def _clean_domain(d: str) -> str:
    d = d.strip().lower().replace("https://", "").replace("http://", "").split("/")[0]
    return d[4:] if d.startswith("www.") else d


def _is_blocked(url: str, domains: list) -> bool:
    host = urlparse(url).netloc.lower().split(":")[0]
    return any(host == d or host.endswith("." + d) for d in domains)


def _get_client() -> TavilyClient:
    return TavilyClient(api_key=os.environ["TAVILY_API_KEY"])


def discover_sources(spec: WorkflowSpec) -> ResolvedWorkflowSpec:
    """
    Takes a WorkflowSpec (from the Planner Agent) and returns a ResolvedWorkflowSpec
    where every source has a "resolved" list of real URLs, titles, and snippets.
    Domains the user asked to avoid (spec.exclude_domains) are never searched.
    """
    client = _get_client()
    exclude = [d for d in (_clean_domain(x) for x in spec.exclude_domains) if d]
    resolved_sources = []
    seen_urls: set[str] = set()  # dedupe identical URLs ACROSS sources before extraction

    for source in spec.sources:
        if source.type == "site":
            resolved = [ResolvedResult(url=source.query_or_url)]
        elif source.type == "connector" and source.connector is not None:
            from app.connectors import fetch_postings

            resolved = [r for r in fetch_postings(source.connector) if not _is_blocked(r.url, exclude)]
        else:
            resolved = _tavily_search(client, source.query_or_url, exclude)

        # Drop any URL we've already resolved for an earlier source, so the same
        # posting isn't fetched and sent to the LLM multiple times. Empty URLs pass through.
        deduped = []
        for r in resolved:
            if r.url and r.url in seen_urls:
                continue
            if r.url:
                seen_urls.add(r.url)
            deduped.append(r)
        dropped = len(resolved) - len(deduped)
        if dropped:
            print(f"[discovery] {source.query_or_url!r}: dropped {dropped} duplicate url(s) already seen")
        resolved = deduped

        resolved_sources.append(
            ResolvedSource(
                type=source.type,
                query_or_url=source.query_or_url,
                notes=source.notes,
                connector=source.connector,
                resolved=resolved,
            )
        )

    # Re-validates the whole enriched spec against the schema before returning.
    return ResolvedWorkflowSpec(
        goal=spec.goal,
        fields=spec.fields,
        sources=resolved_sources,
        validation_rules=spec.validation_rules,
        dedupe_strategy=spec.dedupe_strategy,
        exclude_domains=spec.exclude_domains,
    )


def _tavily_search(client: TavilyClient, query: str, exclude: list) -> list:
    response = client.search(
        query=query,
        max_results=MAX_RESULTS_PER_SOURCE,
        search_depth="advanced",
        include_raw_content=True,
        exclude_domains=exclude or None,
    )
    results = [r for r in response.get("results", []) if not _is_blocked(r["url"], exclude)]
    print(f"[discovery] {query!r} -> {len(results)} urls (excluded: {exclude or 'none'})")
    return [
        ResolvedResult(url=r["url"], title=r.get("title"), snippet=r.get("content"), raw_content=r.get("raw_content"))
        for r in results
    ]