"""Fetch the full text of source articles, politely (robots.txt, timeouts, caps)."""

from __future__ import annotations

import concurrent.futures as cf
import logging
import threading
import urllib.robotparser
from urllib.parse import urlsplit

from .config import Settings
from .fetch import Item, http_get
from .textutil import truncate

log = logging.getLogger(__name__)

_robots_cache: dict[str, urllib.robotparser.RobotFileParser | None] = {}
_robots_lock = threading.Lock()


def _robots_for(url: str, settings: Settings) -> urllib.robotparser.RobotFileParser | None:
    parts = urlsplit(url)
    base = f"{parts.scheme}://{parts.netloc}"
    with _robots_lock:
        if base in _robots_cache:
            return _robots_cache[base]
    parser: urllib.robotparser.RobotFileParser | None = urllib.robotparser.RobotFileParser()
    try:
        data = http_get(f"{base}/robots.txt", settings.user_agent, min(settings.extract_timeout, 10))
        parser.parse(data.decode("utf-8", "replace").splitlines())
    except Exception:  # noqa: BLE001 - missing/blocked robots.txt means no restrictions
        parser = None
    with _robots_lock:
        _robots_cache[base] = parser
    return parser


def allowed_by_robots(url: str, settings: Settings) -> bool:
    parser = _robots_for(url, settings)
    if parser is None:
        return True
    try:
        return parser.can_fetch(settings.user_agent, url)
    except Exception:  # noqa: BLE001
        return True


def extract_text(url: str, settings: Settings) -> str:
    """Return the main article text for *url*, or '' if it cannot be obtained."""
    if not allowed_by_robots(url, settings):
        log.debug("robots.txt disallows %s", url)
        return ""
    import trafilatura  # imported lazily: it is slow to import and optional at runtime

    html = http_get(url, settings.user_agent, settings.extract_timeout, accept="text/html,*/*;q=0.8")
    text = trafilatura.extract(
        html.decode("utf-8", "replace"),
        include_comments=False,
        include_tables=False,
        favor_precision=True,
        url=url,
    )
    return truncate((text or "").strip(), settings.extract_max_chars)


def enrich_items(items: list[Item], settings: Settings) -> int:
    """Fill ``full_text`` on the given items concurrently. Returns the number enriched."""
    if not items:
        return 0
    done = 0

    def work(item: Item) -> None:
        nonlocal done
        try:
            text = extract_text(item.url, settings)
        except Exception as exc:  # noqa: BLE001 - extraction is best-effort
            log.debug("extract failed for %s: %s", item.url, exc)
            return
        if len(text) > len(item.summary) + 200:
            item.full_text = text
            item.extracted = True
            done += 1

    with cf.ThreadPoolExecutor(max_workers=settings.extract_workers) as pool:
        list(pool.map(work, items))
    log.info("extracted full text for %d/%d source pages", done, len(items))
    return done
