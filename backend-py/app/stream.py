"""
SSE streaming endpoint for real-time pipeline progress.
Mounts as a router in main.py.
"""
import json
import asyncio
import uuid
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

import hashlib

from app import cache
from app.agents.planner import plan_workflow
from app.agents.source_discovery import discover_sources
from app.agents.extraction import extract_all
from app.agents.critic import check_health, heal_and_retry
from app.agents.validator import validate_and_dedupe
from app.enrich import enrich_emails
from app.schemas import WorkflowSpec, SourceExtractionResult

router = APIRouter()

# In-memory store for task results (for SSE replay)
_task_results: dict = {}
_cancel_events: dict[str, asyncio.Event] = {}


def _sse_event(event: str, data: dict) -> str:
    """Format a Server-Sent Event."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _set_task_status(task_id: str, status: str, error_code: str | None = None, error_message: str | None = None):
    try:
        from app.db.persist import update_task_status
        update_task_status(task_id, status, error_code, error_message)
    except Exception as err:  # noqa: BLE001
        print(f"[stream] task status update failed: {err}")


def _record_event(task_id: str, agent: str, status: str, message: str | None = None):
    try:
        from app.db.persist import record_agent_event
        record_agent_event(task_id, agent, status, message)
    except Exception as err:  # noqa: BLE001
        print(f"[stream] agent event persistence failed: {err}")


def _cancelled(task_id: str) -> bool:
    event = _cancel_events.get(task_id)
    return event.is_set() if event else False


async def _run_pipeline_stream(prompt: str, task_id: str | None = None):
    """Run the full pipeline and yield SSE events at each stage.

    Each ``done`` event carries the full data payload so the frontend can
    populate its state incrementally — no second request needed.
    """
    if task_id is None:
        task_id = str(uuid.uuid4())
        try:
            from app.db.persist import create_task
            task_id = create_task(prompt)
        except Exception as err:  # noqa: BLE001
            print(f"[stream] task creation failed: {err}")
    _cancel_events[task_id] = asyncio.Event()

    yield _sse_event("pipeline:start", {"task_id": task_id, "timestamp": _now()})

    def cancel_and_return():
        _set_task_status(task_id, "cancelled", "TASK_CANCELLED", "Workflow cancelled by user")
        _record_event(task_id, "Pipeline", "cancelled", "Workflow cancelled by user")

    if _cancelled(task_id):
        cancel_and_return()
        yield _sse_event("pipeline:cancelled", {"task_id": task_id})
        return

    # --- Stage 1: Planner ---
    _record_event(task_id, "Planner", "started", "Generating workflow spec")
    yield _sse_event("planner:start", {"task_id": task_id, "timestamp": _now()})
    try:
        spec = await asyncio.to_thread(plan_workflow, prompt)
        if _cancelled(task_id):
            cancel_and_return()
            yield _sse_event("pipeline:cancelled", {"task_id": task_id})
            return
        _record_event(task_id, "Planner", "completed", "Workflow spec generated")
        yield _sse_event("planner:done", {
            "task_id": task_id,
            "spec": spec.model_dump(),
        })
    except Exception as err:
        _set_task_status(task_id, "failed", "PLANNER_FAILED", str(err))
        _record_event(task_id, "Planner", "failed", "Planner failed")
        yield _sse_event("pipeline:error", {"error": f"Planner failed: {err}"})
        return

    # --- Stage 2: Source Discovery ---
    _record_event(task_id, "Source Discovery", "started", "Resolving sources")
    yield _sse_event("discovery:start", {"task_id": task_id, "source_count": len(spec.sources)})
    try:
        resolved_spec = await asyncio.to_thread(discover_sources, spec)
        if _cancelled(task_id):
            cancel_and_return()
            yield _sse_event("pipeline:cancelled", {"task_id": task_id})
            return
        _record_event(task_id, "Source Discovery", "completed", "Sources resolved")
        yield _sse_event("discovery:done", {
            "task_id": task_id,
            "resolved_spec": resolved_spec.model_dump(),
        })
    except Exception as err:
        _set_task_status(task_id, "failed", "DISCOVERY_FAILED", str(err))
        _record_event(task_id, "Source Discovery", "failed", "Source discovery failed")
        yield _sse_event("pipeline:error", {"error": f"Discovery failed: {err}"})
        return

    # --- Stage 3: Extraction ---
    _record_event(task_id, "Extraction", "started", "Extracting records")
    yield _sse_event("extraction:start", {"task_id": task_id, "source_count": len(resolved_spec.sources)})
    try:
        extraction_results = await asyncio.to_thread(extract_all, resolved_spec)
        if _cancelled(task_id):
            cancel_and_return()
            yield _sse_event("pipeline:cancelled", {"task_id": task_id})
            return
        total_records = sum(len(r.records) for r in extraction_results)
        _record_event(task_id, "Extraction", "completed", f"Extracted {total_records} records")
        yield _sse_event("extraction:done", {
            "task_id": task_id,
            "extraction_results": [r.model_dump() for r in extraction_results],
            "total_records": total_records,
        })
    except Exception as err:
        _set_task_status(task_id, "failed", "EXTRACTION_FAILED", str(err))
        _record_event(task_id, "Extraction", "failed", "Extraction failed")
        yield _sse_event("pipeline:error", {"error": f"Extraction failed: {err}"})
        return

    # --- Stage 4: Critic ---
    _record_event(task_id, "Critic", "started", "Checking extraction quality")
    yield _sse_event("critic:start", {"task_id": task_id})
    healed_results: list[SourceExtractionResult] = []
    try:
        fields = spec.fields
        resolved_sources = resolved_spec.sources
        for result, resolved_source in zip(extraction_results, resolved_sources):
            if _cancelled(task_id):
                cancel_and_return()
                yield _sse_event("pipeline:cancelled", {"task_id": task_id})
                return
            report = await asyncio.to_thread(check_health, result, fields)
            if not report.needs_healing or not resolved_source.resolved:
                healed_results.append(result)
                continue
            retry_url = resolved_source.resolved[0].url
            healing = await asyncio.to_thread(heal_and_retry, retry_url, fields, result.records)
            healed_results.append(
                SourceExtractionResult(
                    query_or_url=result.query_or_url,
                    records=result.records + healing.recovered_records,
                    fetch_errors=result.fetch_errors + ([healing.diagnosis] if healing.diagnosis else []),
                )
            )
        await asyncio.to_thread(enrich_emails, healed_results)
        _record_event(task_id, "Critic", "completed", "Extraction quality checked")
        yield _sse_event("critic:done", {"task_id": task_id})
    except Exception as err:
        healed_results = extraction_results
        _record_event(task_id, "Critic", "warning", "Critic stage partially failed")
        yield _sse_event("critic:done", {"task_id": task_id, "warning": str(err)})

    # --- Stage 5: Validator ---
    _record_event(task_id, "Validator", "started", "Validating and deduplicating records")
    yield _sse_event("validator:start", {"task_id": task_id})
    try:
        all_records = [r for result in healed_results for r in result.records]
        validated = await asyncio.to_thread(validate_and_dedupe, all_records, spec.validation_rules)
        if _cancelled(task_id):
            cancel_and_return()
            yield _sse_event("pipeline:cancelled", {"task_id": task_id})
            return
        _record_event(task_id, "Validator", "completed", "Records validated")
        yield _sse_event("validator:done", {
            "task_id": task_id,
            "validated_result": validated.model_dump(),
        })
    except Exception as err:
        _set_task_status(task_id, "failed", "VALIDATOR_FAILED", str(err))
        _record_event(task_id, "Validator", "failed", "Validation failed")
        yield _sse_event("pipeline:error", {"error": f"Validator failed: {err}"})
        return

    # --- Persist ---
    # Falls back to the in-memory task_id if the DB write fails, so a run that
    # completed is never lost from the UI even when persistence itself breaks.
    persisted_task_id = task_id
    persist_error = None
    try:
        from app.db.persist import persist_workflow_run

        persisted_task_id = persist_workflow_run(prompt, spec, resolved_spec, healed_results, validated, task_id)
    except Exception as err:  # noqa: BLE001 — a DB hiccup shouldn't break a completed run
        persist_error = str(err)
        print(f"[stream] persist failed (run still shown in UI, just not saved to history): {err}")

    # --- Complete ---
    yield _sse_event("pipeline:complete", {
        "task_id": persisted_task_id,
        "total_records": len(validated.clean_records),
        "persist_error": persist_error,
    })

    # Store result for potential replay (same request/session only)
    _task_results[task_id] = {
        "prompt": prompt,
        "spec": spec.model_dump(),
        "resolved_spec": resolved_spec.model_dump(),
        "extraction_results": [r.model_dump() for r in extraction_results],
        "validated_result": validated.model_dump(),
    }
    _cancel_events.pop(task_id, None)


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


async def _locked_stream(prompt: str, task_id: str | None):
    name = "run:" + hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
    token = cache.acquire_lock(name, 900)
    if token is None:
        yield _sse_event("pipeline:error", {"error": "This prompt is already running. Wait for it to finish."})
        return
    try:
        async for chunk in _run_pipeline_stream(prompt, task_id):
            yield chunk
    finally:
        cache.release_lock(name, token)


@router.get("/api/workflows/run/stream")
async def stream_workflow(prompt: str, task_id: str | None = None):
    """SSE endpoint: streams pipeline progress events as they happen."""
    return StreamingResponse(
        _locked_stream(prompt, task_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api/workflows/result/{task_id}")
async def get_result(task_id: str):
    """Retrieve a completed pipeline result by task_id."""
    if task_id not in _task_results:
        raise HTTPException(status_code=404, detail="Task not found")
    return _task_results[task_id]


@router.post("/api/tasks/{task_id}/cancel")
async def cancel_task(task_id: str):
    event = _cancel_events.get(task_id)
    if not event:
        raise HTTPException(status_code=404, detail="Active task not found")
    event.set()
    return {"task_id": task_id, "status": "cancelling"}
