"""
Validator Agent — flags missing/implausible fields and dedupes records, recording
*why* two records were judged duplicates instead of merging silently.
"""
import json
import re
from urllib.parse import urlparse

from rapidfuzz import fuzz

from app.llm import chat
from app.schemas import ExtractedRecord, MergeDecision, ValidatedResult, ValidationIssue

DUPLICATE_NAME_THRESHOLD = 88
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _looks_implausible(field: str, value) -> str | None:
    if value in (None, "", "null"):
        return "missing"
    if "email" in field.lower() and not EMAIL_RE.match(str(value)):
        return "not a valid email format"
    if "url" in field.lower() and not str(value).startswith(("http://", "https://")):
        return "not a valid URL"
    return None


def _primary_name_field(record: ExtractedRecord) -> str | None:
    """Identity key: ALL name/title/company-like fields joined, so two different
    companies with the same job title are not treated as duplicates."""
    parts = [
        str(v)
        for k, v in record.data.items()
        if any(hint in k.lower() for hint in ("name", "title", "company")) and v
    ]
    return " | ".join(parts) if parts else None


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return url


VALIDATION_BATCH_SIZE = 15


def _check_validation_rules(records: list, validation_rules: list) -> list:
    issues: list = []
    for start in range(0, len(records), VALIDATION_BATCH_SIZE):
        batch = records[start:start + VALIDATION_BATCH_SIZE]
        for issue in _check_validation_rules_batch(batch, validation_rules):
            issue.record_index += start  # convert batch-local index to global index
            issues.append(issue)
    return issues


def _check_validation_rules_batch(records: list, validation_rules: list) -> list:
    """One batched LLM call checks every record against every rule at once — same
    pattern as extraction.py's filter_relevant, so this never scales with record
    count and can't reintroduce the per-record rate-limit problem we hit earlier."""
    if not validation_rules or not records:
        return []

    rules_block = "\n".join(f"- {r}" for r in validation_rules)
    lines = [
        f"{i}: " + json.dumps({k: (str(v)[:80] if v else None) for k, v in r.data.items()}, ensure_ascii=False)
        for i, r in enumerate(records)
    ]
    records_block = "\n".join(lines)
    prompt = f"""Check each record below against these validation rules:
{rules_block}

Records (as "index: fields"):
{records_block}

Return ONLY a JSON object: {{"violations": [{{"index": int, "rule": string}}]}}
listing every record that clearly breaks a rule, with which rule it breaks (verbatim).
A record with a null/missing field it needs is a violation UNLESS the rule only applies
when that field is present. If every record passes, return {{"violations": []}}."""

    try:
        text = chat([{"role": "user", "content": prompt}], max_tokens=2000)
        cleaned = re.sub(r"```json|```", "", text).strip()
        parsed = json.loads(cleaned)
        violations = parsed.get("violations", [])
    except Exception as err:  # noqa: BLE001 — never block validation because the rule-check failed
        print(f"[validator] rule check skipped: {err}")
        return []

    issues = []
    for v in violations:
        idx = v.get("index")
        rule = v.get("rule")
        if isinstance(idx, int) and 0 <= idx < len(records) and rule:
            issues.append(ValidationIssue(record_index=idx, field="_rule", reason=rule))
    print(f"[validator] rule check: {len(issues)} violation(s) across {len(validation_rules)} rule(s)")
    return issues


_EMAIL_FIND_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def _clean_record(record: ExtractedRecord) -> None:
    """Normalizes whitespace, emails and links in place."""
    for key, value in list(record.data.items()):
        if not isinstance(value, str):
            continue
        v = re.sub(r"\s+", " ", value).strip().strip(",;|")
        k = key.lower()
        if "email" in k:
            m = _EMAIL_FIND_RE.search(v)
            v = m.group(0).lower() if m else v
        elif any(h in k for h in ("url", "link", "website")) and v.startswith("www."):
            v = "https://" + v
        record.data[key] = v or None


def validate_and_dedupe(records: list, validation_rules: list) -> ValidatedResult:
    for record in records:
        _clean_record(record)
    issues: list = []
    for i, record in enumerate(records):
        for field, value in record.data.items():
            reason = _looks_implausible(field, value)
            if reason:
                issues.append(ValidationIssue(record_index=i, field=field, reason=reason))

    issues.extend(_check_validation_rules(records, validation_rules))

    # Attach real problems (rule violations, bad email/URL) to the record itself so the UI
    # can flag the row. Plain "missing" is skipped: it would flag nearly every row.
    for issue in issues:
        if issue.reason != "missing" and 0 <= issue.record_index < len(records):
            label = issue.reason if issue.field == "_rule" else f"{issue.field}: {issue.reason}"
            records[issue.record_index].flags.append(label)

    merges: list = []
    dropped: set = set()

    for i in range(len(records)):
        if i in dropped:
            continue
        name_i = _primary_name_field(records[i])
        if not name_i:
            continue
        for j in range(i + 1, len(records)):
            if j in dropped:
                continue
            name_j = _primary_name_field(records[j])
            if not name_j:
                continue

            score = fuzz.ratio(str(name_i).lower(), str(name_j).lower())
            if score >= DUPLICATE_NAME_THRESHOLD:
                same_domain = _domain(records[i].citation_url) == _domain(records[j].citation_url)
                reason = f"name similarity {score:.0f}%" + (" + same source domain" if same_domain else "")
                merges.append(MergeDecision(kept_index=i, dropped_index=j, reason=reason, similarity_score=score / 100))
                dropped.add(j)

    clean_records = [r for idx, r in enumerate(records) if idx not in dropped]
    return ValidatedResult(clean_records=clean_records, issues=issues, merges=merges)