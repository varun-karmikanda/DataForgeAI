"""
FastAPI server exposing the Planner + Source-Discovery agents.
Mirrors the Node version's routes: /api/workflows/plan and /api/workflows/discover,
plus /api/workflows/run which chains both through the LangGraph graph in one call.
"""
import os
from urllib.parse import quote
from dotenv import load_dotenv

load_dotenv()  # must run before any agent module reads os.environ for API keys

import asyncio

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.agents.planner import plan_workflow
from app.agents.source_discovery import discover_sources
from app.resume import ResumeProfile, extract_profile, extract_text
from app.schemas import WorkflowSpec
from app.stream import router as stream_router
from app.db.database import init_db

# ---------------------------------------------------------------------------
# CORS configuration
# ---------------------------------------------------------------------------
# ALLOWED_ORIGINS — comma-separated list of allowed origin URLs.
#   • In development, include http://localhost:3000 and/or http://127.0.0.1:3000.
#   • In production, set this to your real frontend domain(s), e.g.:
#       ALLOWED_ORIGINS=https://app.example.com,https://www.example.com
#   • Empty entries and whitespace are silently ignored.
# ---------------------------------------------------------------------------
_is_dev = os.environ.get("ENV", "development") == "development"

_raw_origins = os.environ.get("ALLOWED_ORIGINS", "")
_allowed_origins: list[str] = [
    o.strip()
    for o in _raw_origins.split(",")
    if o.strip()
]

# In development, automatically include common localhost dev origins.
if _is_dev:
    _dev_origins = ["http://localhost:3000", "http://127.0.0.1:3000"]
    _allowed_origins = list(dict.fromkeys(_allowed_origins + _dev_origins))

# Safety net: if nothing is configured at all, reject all cross-origin requests.
if not _allowed_origins:
    _allowed_origins = []

app = FastAPI(title="DataForge AI — Planning Service")
app.include_router(stream_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_origin_regex=None,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Accept"],
)


class PlanRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=8000)


class DiscoverRequest(BaseModel):
    spec: WorkflowSpec


@app.get("/health")
@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/tasks")
def list_tasks_route(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: str | None = None,
    search: str | None = None,
):
    from app.db.persist import list_tasks

    try:
        return {"tasks": list_tasks(limit=limit, offset=offset, status=status, search=search)}
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Could not list tasks: {err}") from err


@app.get("/api/tasks/{task_id}")
def get_task_route(task_id: str):
    from app.db.persist import get_task

    try:
        task = get_task(task_id)
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Could not load task: {err}") from err
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@app.get("/api/tasks/{task_id}/events")
def get_task_events_route(task_id: str):
    from app.db.persist import list_task_events

    try:
        events = list_task_events(task_id)
    except Exception as err:
        raise HTTPException(status_code=500, detail="Could not load task events") from err
    return {"task_id": task_id, "events": events}


@app.post("/api/tasks/{task_id}/retry", status_code=202)
def retry_task_route(task_id: str):
    from app.db.persist import create_task, get_task

    original = get_task(task_id)
    if original is None:
        raise HTTPException(status_code=404, detail="Task not found")
    try:
        retry_id = create_task(original["prompt"], retry_of=task_id)
    except Exception as err:
        raise HTTPException(status_code=500, detail="Could not create retry task") from err
    return {
        "task_id": retry_id,
        "prompt": original["prompt"],
        "stream_url": f"/api/workflows/run/stream?prompt={quote(original['prompt'])}&task_id={retry_id}",
    }


@app.on_event("startup")
def init_database():
    """Creates the Postgres/SQLite tables on first run if they don't exist yet."""
    try:
        init_db()
        print("Database ready.")
    except Exception as err:
        print(f"DB init failed (non-fatal - history/persistence will be unavailable): {err}")


@app.on_event("startup")
def warm_up_llm():
    """Opt-in only: set LLM_WARMUP=1 in .env to pre-load the LLM client at startup."""
    if os.environ.get("LLM_WARMUP") != "1":
        return
    try:
        plan_workflow("warmup")
        print("LLM warm-up complete.")
    except Exception as err:
        print(f"LLM warm-up failed (non-fatal): {err}")


@app.post("/api/workflows/plan")
def plan(req: PlanRequest):
    try:
        spec = plan_workflow(req.prompt)
        return {"prompt": req.prompt, "spec": spec.model_dump()}
    except Exception as err:
        raise HTTPException(status_code=500, detail=str(err)) from err


@app.post("/api/workflows/discover")
def discover(req: DiscoverRequest):
    try:
        resolved = discover_sources(req.spec)
        return {"spec": resolved.model_dump()}
    except Exception as err:
        raise HTTPException(status_code=500, detail=str(err)) from err


@app.post("/api/workflows/run")
def run(req: PlanRequest):
    """Runs Planner -> Source-Discovery -> Extraction -> Critic -> Validator, then persists the run."""
    result = run_workflow(req.prompt)
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])

    task_id = None
    persist_error = None
    try:
        from app.db.persist import persist_workflow_run

        task_id = persist_workflow_run(
            req.prompt,
            result["spec"],
            result["resolved_spec"],
            result["extraction_results"],
            result["validated_result"],
        )
    except Exception as err:  # noqa: BLE001 - a DB hiccup shouldn't break the response
        persist_error = str(err)

    return {
        "prompt": req.prompt,
        "task_id": task_id,
        "persist_error": persist_error,
        "spec": result["spec"].model_dump(),
        "resolved_spec": result["resolved_spec"].model_dump(),
        "extraction_results": [r.model_dump() for r in result["extraction_results"]],
        "validated_result": result["validated_result"].model_dump(),
    }
@app.post("/api/resume/parse", response_model=ResumeProfile)
async def parse_resume(file: UploadFile = File(...)):
    """Reads an uploaded resume (PDF/TXT) and returns a structured candidate profile.
    The file is processed in memory only; nothing is stored."""
    data = await file.read()
    try:
        text = extract_text(file.filename or "", data)
        return await asyncio.to_thread(extract_profile, text)
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    except Exception as err:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Resume parsing failed: {err}") from err