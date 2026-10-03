"""
Single place for every LLM call (planner, extraction, critic).

Pick the provider in .env:
  LLM_PROVIDER=gemini   -> Google Gemini (free tier, big token limits)   needs GEMINI_API_KEY
  LLM_PROVIDER=groq     -> Groq (default; free tier is capped at 8K tokens/min) needs GROQ_API_KEY
Optional: GEMINI_MODEL (default gemini-2.5-flash), GROQ_MODEL (default openai/gpt-oss-20b)
"""
import functools
import json
import os
import re

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app import cache

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

GROQ_MAX_PROMPT_CHARS = int(os.environ.get("GROQ_MAX_PROMPT_CHARS", "8000"))
GEMINI_COOLDOWN_SECONDS = int(os.environ.get("GEMINI_COOLDOWN_SECONDS", "120"))
LLM_CACHE_ON = os.environ.get("LLM_CACHE", "1").strip() != "0"
LLM_CACHE_TTL_SECONDS = int(os.environ.get("LLM_CACHE_TTL_SECONDS", "21600"))  # 6 hours


def provider() -> str:
    return os.environ.get("LLM_PROVIDER", "groq").strip().lower()


def _is_rate_limit_error(err: BaseException) -> bool:
    text = str(err).lower()
    return (
        "429" in text
        or "rate_limit" in text
        or "rate limit" in text
        or "resource_exhausted" in text
        or "503" in text
        or "unavailable" in text
        or "overloaded" in text
    )


def _is_quota_exhausted(err: BaseException) -> bool:
    """Daily/free-tier quota is spent — retrying the SAME provider is pointless, so we
    fail fast and fall back to the other provider instead of backing off in place."""
    text = str(err).lower()
    return "exceeded your current quota" in text or "perday" in text or "per day" in text or "quota exceeded" in text


def _is_request_too_large(err: BaseException) -> bool:
    text = str(err).lower()
    return "413" in text or "request too large" in text or "request_too_large" in text


def _should_retry_same_provider(err: BaseException) -> bool:
    return _is_rate_limit_error(err) and not _is_quota_exhausted(err) and not _is_request_too_large(err)


def _shrink_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    head = int(limit * 0.6)
    return text[:head] + "\n[...]\n" + text[-(limit - head):]


def _fit_messages(messages: list, limit: int) -> list:
    total = sum(len(m["content"]) for m in messages)
    if total <= limit:
        return messages
    longest = max(range(len(messages)), key=lambda i: len(messages[i]["content"]))
    others = total - len(messages[longest]["content"])
    budget = max(1000, limit - others)
    fitted = list(messages)
    fitted[longest] = {**messages[longest], "content": _shrink_text(messages[longest]["content"], budget)}
    return fitted


@functools.lru_cache(maxsize=1)
def _groq_client():
    from langchain_groq import ChatGroq

    model = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
    extra = {"reasoning_effort": "low"} if model.startswith("openai/gpt-oss") else {}
    return ChatGroq(
        model=model,
        api_key=os.environ["GROQ_API_KEY"],
        max_tokens=3000,
        max_retries=0,
        timeout=60,
        **extra,
    )


def _groq_chat(messages: list, max_tokens: int | None) -> str:
    llm = _groq_client()
    if max_tokens:
        llm = llm.bind(max_tokens=max_tokens)
    return llm.invoke(messages).content


def _gemini_chat(messages: list, max_tokens: int | None) -> str:
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    system = "\n".join(m["content"] for m in messages if m["role"] == "system")
    contents = [
        {"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
        for m in messages
        if m["role"] != "system"
    ]
    generation_config = {"temperature": 0, "maxOutputTokens": max_tokens or 8192}
    if "flash" in model and "image" not in model and "tts" not in model:
        generation_config["thinkingConfig"] = {"thinkingBudget": 0}  # no hidden reasoning tokens eating the answer
    body = {"contents": contents, "generationConfig": generation_config}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}

    resp = httpx.post(
        GEMINI_URL.format(model=model),
        headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"], "Content-Type": "application/json"},
        json=body,
        timeout=90,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Gemini error {resp.status_code}: {resp.text[:300]}")
    candidates = resp.json().get("candidates") or [{}]
    parts = (candidates[0].get("content") or {}).get("parts") or []
    return "".join(p.get("text", "") for p in parts)


_retry_provider = retry(
    retry=retry_if_exception(_should_retry_same_provider),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    stop=stop_after_attempt(5),
    reraise=True,
)


@_retry_provider
def _gemini_with_retry(messages: list, max_tokens: int | None) -> str:
    return _gemini_chat(messages, max_tokens)


@_retry_provider
def _groq_with_retry(messages: list, max_tokens: int | None) -> str:
    return _groq_chat(messages, max_tokens)


def _groq_fitted(messages: list, max_tokens: int | None) -> str:
    limit = GROQ_MAX_PROMPT_CHARS
    try:
        return _groq_with_retry(_fit_messages(messages, limit), max_tokens)
    except Exception as err:  # noqa: BLE001
        if not _is_request_too_large(err):
            raise
        print(f"[llm] Groq 413 at {limit} chars; retrying with {limit // 2}")
        return _groq_with_retry(_fit_messages(messages, limit // 2), max_tokens)


def _cooldown_seconds(err: BaseException, default: int) -> int:
    """How long a provider asked us to wait, read from its error text (e.g. 'try again in 9m29.3s')."""
    text = str(err)
    m = re.search(r"try again in\s+((?:\d+h)?(?:\d+m)?(?:\d+(?:\.\d+)?s)?)", text)
    if m and m.group(1):
        h = re.search(r"(\d+)h", m.group(1))
        mi = re.search(r"(\d+)m", m.group(1))
        sec = re.search(r"(\d+(?:\.\d+)?)s", m.group(1))
        total = (int(h.group(1)) * 3600 if h else 0) + (int(mi.group(1)) * 60 if mi else 0) + (float(sec.group(1)) if sec else 0)
        if total > 0:
            return int(total) + 3
    m = re.search(r'retryDelay"?\s*:\s*"?(\d+)s', text)
    if m:
        return int(m.group(1)) + 3
    return default


def _json_ok(text: str) -> bool:
    """We only cache answers that are valid JSON - every agent here asks for JSON, and a
    broken/truncated answer must never be replayed from the cache."""
    try:
        json.loads(re.sub(r"```json|```", "", text or "").strip())
        return True
    except (ValueError, TypeError):
        return False


def _groq_guarded(messages: list, max_tokens: int | None) -> str:
    wait = cache.blocked_seconds("groq")
    if wait > 0:
        raise RuntimeError(
            f"AI providers are rate-limited right now (Groq resets in about {max(1, wait // 60)} min). "
            "Answers already cached still work - try again a little later."
        )
    try:
        return _groq_fitted(messages, max_tokens)
    except Exception as err:  # noqa: BLE001
        if _is_rate_limit_error(err) and not _is_request_too_large(err):
            cache.block("groq", _cooldown_seconds(err, 60))
        raise


def _chat_uncached(messages: list, max_tokens: int | None) -> str:
    if provider() == "gemini" and cache.blocked_seconds("gemini") <= 0:
        try:
            return _gemini_with_retry(messages, max_tokens)
        except Exception as err:  # noqa: BLE001
            if _is_rate_limit_error(err):
                default = 600 if _is_quota_exhausted(err) else GEMINI_COOLDOWN_SECONDS
                cache.block("gemini", _cooldown_seconds(err, default))
            print(f"[llm] Gemini unavailable ({str(err)[:140]}); falling back to Groq")
    return _groq_guarded(messages, max_tokens)


def chat(messages: list, max_tokens: int | None = None) -> str:
    """Every LLM call in the app goes through here: cache first, then the providers."""
    key = None
    if LLM_CACHE_ON:
        key = cache.make_key("llm", json.dumps(messages, sort_keys=True, ensure_ascii=False), str(max_tokens))
        hit = cache.get_json(key)
        if isinstance(hit, dict) and isinstance(hit.get("text"), str):
            cache.stats["hit"] += 1
            print(f"[cache] HIT  llm ({cache.stats['hit']} hits / {cache.stats['miss']} misses this session)")
            return hit["text"]
        cache.stats["miss"] += 1

    text = _chat_uncached(messages, max_tokens)

    if key and _json_ok(text):
        cache.set_json(key, {"text": text}, LLM_CACHE_TTL_SECONDS)
    return text