"""
Freshness check - decides whether a job posting is still open, using only the
posting's own text (no LLM, no tokens).

A posting is dropped when it
  * says it is closed ("no longer accepting applications", "position has been filled", ...), or
  * names a last date / deadline that is already in the past (India time).
A posting with no closing information is kept ("unknown") - we never guess.
"""
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MON = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"

_CLOSED_RE = re.compile(
    r"no longer (?:accepting|taking) (?:any )?(?:applications?|candidates?|resumes?)"
    r"|not (?:currently )?accepting (?:any )?(?:new )?(?:applications?|candidates?)"
    r"|applications? (?:are |is |have been |has been )?(?:now )?(?:closed|over)\b"
    r"|(?:job|position|posting|role|vacancy|opening|requisition)[^.\n]{0,40}"
    r"(?:has|have|is|was|been)[^.\n]{0,15}(?:expired|closed|filled)"
    r"|(?:job|position|posting|role|vacancy|opening)[^.\n]{0,40}no longer (?:available|open|active)"
    r"|this (?:job|posting|position|vacancy) (?:has )?expired"
    r"|hiring (?:for this (?:role|position) )?is (?:now )?closed",
    re.IGNORECASE,
)

_CUE_RE = re.compile(
    r"last\s+date|last\s+day|closing\s+date|closes?\b|close\s+on|deadline|due\s+date"
    r"|apply\s+(?:by|before|until|till|on or before)|applications?\s+(?:close|due|accepted\s+(?:until|till)|open\s+(?:until|till))"
    r"|valid\s+(?:through|till|until|up\s*to)|expir(?:y|es|ing)(?:\s+date)?|end\s+date",
    re.IGNORECASE,
)

_DATE_PATTERNS = [
    ("iso", re.compile(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b")),
    ("dmy_name", re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?[\s\-/,.]*{_MON}[a-z]*\.?,?[\s\-/,.]*(20\d{{2}})\b", re.IGNORECASE)),
    ("mdy_name", re.compile(rf"\b{_MON}[a-z]*\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(20\d{{2}})\b", re.IGNORECASE)),
    ("numeric", re.compile(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](20\d{2})\b")),
]


def today_ist() -> date:
    return datetime.now(IST).date()


def _safe_date(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _first_date(fragment: str) -> date | None:
    best: tuple[int, date] | None = None  # earliest position in the fragment wins
    for kind, pattern in _DATE_PATTERNS:
        m = pattern.search(fragment)
        if not m:
            continue
        if kind == "iso":
            found = _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        elif kind == "dmy_name":
            found = _safe_date(int(m.group(3)), _MONTHS[m.group(2)[:3].lower()], int(m.group(1)))
        elif kind == "mdy_name":
            found = _safe_date(int(m.group(3)), _MONTHS[m.group(1)[:3].lower()], int(m.group(2)))
        else:  # numeric: India writes day first; swap only when it can't be a month
            a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            found = _safe_date(y, b, a) if b <= 12 else _safe_date(y, a, b)
        if found and (best is None or m.start() < best[0]):
            best = (m.start(), found)
    return best[1] if best else None


def find_deadline(text: str) -> date | None:
    """Latest date that appears right after a deadline-style phrase, or None."""
    dates: list[date] = []
    for cue in _CUE_RE.finditer(text or ""):
        found = _first_date((text or "")[cue.end(): cue.end() + 60])
        if found:
            dates.append(found)
    return max(dates) if dates else None


def posting_status(text: str, today: date | None = None) -> tuple[str, str]:
    """Returns (status, reason). status is 'closed', 'expired', 'open' or 'unknown'."""
    today = today or today_ist()
    text = text or ""
    m = _CLOSED_RE.search(text)
    if m:
        return "closed", f'posting says "{m.group(0).strip()[:60]}"'
    deadline = find_deadline(text)
    if deadline is None:
        return "unknown", ""
    if deadline < today:  # a deadline of today is still open until the day ends
        return "expired", f"last date {deadline.isoformat()} has passed"
    return "open", deadline.isoformat()


# ---------------------------------------------------------------------------
# Required experience: "4 or more years of professional experience", "2-5 years", "minimum 3 yrs" ...
# ---------------------------------------------------------------------------
_YEARS_RE = re.compile(
    r"(\d{1,2})\s*(?:\+|plus)?\s*(?:(?:-|\u2013|to)\s*(\d{1,2})\s*)?"
    r"(?:(?:or|and)\s+(?:more|above|over|up)\s+)?(?:years?|yrs?)\b",
    re.IGNORECASE,
)
_EXPERIENCE_WORD_RE = re.compile(r"experience|\bexp\b", re.IGNORECASE)
_FRESHER_FRIENDLY_RE = re.compile(
    r"fresher|entry[- ]?level|new grad|recent graduate|graduates? (?:welcome|can apply)|campus|"
    r"no (?:prior |previous )?experience|\b0\s*(?:-|to|\u2013)\s*1\s*(?:years?|yrs?)",
    re.IGNORECASE,
)


def min_years_required(text: str) -> int | None:
    """Highest 'minimum years of experience' the posting asks for, or None if it states none.
    A years figure only counts when the word 'experience' is close by, and it is ignored when the
    same sentence area says fresher / entry-level (e.g. 'freshers or 2 years experience')."""
    text = text or ""
    best: int | None = None
    for m in _YEARS_RE.finditer(text):
        around = text[max(0, m.start() - 60): m.end() + 60]
        if not _EXPERIENCE_WORD_RE.search(around):
            continue
        if _FRESHER_FRIENDLY_RE.search(text[max(0, m.start() - 120): m.end() + 120]):
            continue
        years = int(m.group(1))  # for a range "2-5 years" the minimum, 2, is what matters
        if years > 40:
            continue
        best = years if best is None else max(best, years)
    return best


# ---------------------------------------------------------------------------
# Link check: open the apply link and see whether the page itself says the job is gone.
# Job APIs (Adzuna, Jooble, ...) only send a short description, which never says "expired".
# ---------------------------------------------------------------------------
LINK_CHECK = os.environ.get("LINK_CHECK", "1") != "0"
LINK_TIMEOUT = float(os.environ.get("LINK_CHECK_TIMEOUT", "8"))
_BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
_TAGS_RE = re.compile(r"<(script|style|noscript)\b.*?</\1>|<[^>]+>", re.IGNORECASE | re.DOTALL)


def _visible_text(html: str) -> str:
    return re.sub(r"\s+", " ", _TAGS_RE.sub(" ", html or ""))


def check_link(url: str, client=None) -> tuple[str, str, int | None]:
    """Returns (status, reason, min_years). status is 'closed' only when the page clearly says the job
    is gone (404/410 or an 'expired / no longer available' message). Anything else - blocked, timeout,
    odd page - is 'unknown' and the posting is kept: we never drop a job on a guess.
    min_years is the experience the page asks for (None if it states none)."""
    import httpx

    own = client is None
    client = client or httpx.Client(timeout=LINK_TIMEOUT, follow_redirects=True, headers={"User-Agent": _BROWSER_UA})
    try:
        resp = client.get(url)
    except Exception:  # noqa: BLE001 - network error, bad redirect, timeout
        return "unknown", "", None
    finally:
        if own:
            client.close()
    if resp.status_code in (404, 410):
        return "closed", f"link returned HTTP {resp.status_code}", None
    if resp.status_code >= 400:
        return "unknown", "", None  # 403/429/5xx: bot-blocked or flaky, not proof the job is gone
    ctype = resp.headers.get("content-type", "")
    if "html" not in ctype and "text" not in ctype:
        return "unknown", "", None
    page = _visible_text(resp.text[:300_000])[:30_000]
    status, why = posting_status(page)
    if status in ("closed", "expired"):
        return "closed", f"page says: {why}", None
    return "unknown", "", min_years_required(page)


def check_links(urls: list[str], workers: int = 8) -> dict[str, tuple[str, str, int | None]]:
    """Check many links in parallel. Returns {url: (status, reason, min_years)}."""
    if not LINK_CHECK or not urls:
        return {}
    import httpx

    with httpx.Client(timeout=LINK_TIMEOUT, follow_redirects=True, headers={"User-Agent": _BROWSER_UA}) as client:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(lambda u: check_link(u, client), urls))
    return dict(zip(urls, results))