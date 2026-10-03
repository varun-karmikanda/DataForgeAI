"""
Resume Agent: reads an uploaded resume (PDF / TXT) and turns it into a structured
candidate profile. The frontend lets the user review/edit that profile, then turns it
into a normal job-search prompt for the existing Planner -> ... -> Validator pipeline.

Nothing here is saved to disk or the database; the file is read from memory only.
"""
import io
import json
import re
from typing import List

from pydantic import BaseModel, Field
from pypdf import PdfReader

from app.llm import chat

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_RESUME_CHARS = 6000  # keeps the LLM call under the Groq prompt-size limit


class ResumeProfile(BaseModel):
    name: str = ""
    current_role: str = ""
    experience: str = ""  # e.g. "Fresher" or "3 years"
    skills: List[str] = Field(default_factory=list)
    target_roles: List[str] = Field(default_factory=list)
    locations: List[str] = Field(default_factory=list)
    summary: str = ""


SYSTEM_PROMPT = """You are the Resume Agent in a job-data platform.
Read the resume text and output ONLY a JSON object (no prose, no markdown fences) in exactly this shape:

{
  "name": string,
  "current_role": string,
  "experience": string,
  "skills": string[],
  "target_roles": string[],
  "locations": string[],
  "summary": string
}

Rules:
- Use ONLY information present in the resume. Never invent employers, skills or places.
- "current_role": the latest job title; if the person is a student or has no job, use e.g. "Final-year B.E. student".
- "experience": "Fresher" if no full-time work experience, otherwise e.g. "3 years" (internships alone still count as "Fresher").
- "skills": up to 15 technical skills/tools/languages actually listed or clearly used in projects. Short names only (e.g. "React", "PostgreSQL").
- "target_roles": 2-3 job titles this person is best suited for, based on their skills and projects (e.g. "Full Stack Developer").
- "locations": cities mentioned as the person's location or preferred work location. Empty list if none.
- "summary": ONE plain sentence describing the candidate.
- If a value is not in the resume, use "" or [].
"""


def extract_text(filename: str, data: bytes) -> str:
    """Pulls plain text out of an uploaded resume. Raises ValueError with a user-friendly message."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("File is too large (max 5 MB).")

    name = (filename or "").lower()
    if name.endswith(".pdf"):
        try:
            reader = PdfReader(io.BytesIO(data))
            text = "\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception as err:  # noqa: BLE001
            raise ValueError(f"Could not read this PDF: {err}") from err
    elif name.endswith(".txt") or name.endswith(".md"):
        text = data.decode("utf-8", errors="ignore")
    else:
        raise ValueError("Unsupported file type. Upload a PDF or TXT resume.")

    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) < 80:
        raise ValueError(
            "No readable text found. This looks like a scanned/image PDF. Export a text-based PDF and try again."
        )
    return text


def _as_list(value) -> List[str]:
    if isinstance(value, str):
        value = [v for v in re.split(r"[,\n]", value)]
    if not isinstance(value, list):
        return []
    seen, out = set(), []
    for item in value:
        s = str(item).strip()
        if s and s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)
    return out


def extract_profile(resume_text: str) -> ResumeProfile:
    """Asks the LLM to turn resume text into a ResumeProfile."""
    text = chat(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": resume_text[:MAX_RESUME_CHARS]},
        ],
        max_tokens=1500,
    )
    cleaned = re.sub(r"```json|```", "", text).strip()
    try:
        raw = json.loads(cleaned)
    except json.JSONDecodeError as err:
        raise ValueError(f"Resume Agent returned invalid JSON: {err}") from err
    if not isinstance(raw, dict):
        raise ValueError("Resume Agent returned an unexpected shape.")

    return ResumeProfile(
        name=str(raw.get("name") or "").strip(),
        current_role=str(raw.get("current_role") or "").strip(),
        experience=str(raw.get("experience") or "").strip(),
        skills=_as_list(raw.get("skills"))[:15],
        target_roles=_as_list(raw.get("target_roles"))[:3],
        locations=_as_list(raw.get("locations"))[:3],
        summary=str(raw.get("summary") or "").strip(),
    )