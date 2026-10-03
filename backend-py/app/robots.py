from functools import lru_cache
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

UA = "DataForgeAI"


@lru_cache(maxsize=256)
def _parser(origin: str):
    rp = RobotFileParser()
    try:
        r = httpx.get(
            origin + "/robots.txt",
            timeout=5,
            follow_redirects=True,
            headers={"User-Agent": "DataForgeAI/1.0"},
        )
        if r.status_code >= 400:
            return None  # no robots.txt means allowed
        rp.parse(r.text.splitlines())
        return rp
    except Exception:
        return None


def is_allowed(url: str) -> bool:
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        return False
    rp = _parser(f"{p.scheme}://{p.netloc}")
    return True if rp is None else rp.can_fetch(UA, url)