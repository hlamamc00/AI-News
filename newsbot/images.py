"""Find openly licensed illustrations on Wikimedia Commons.

Publisher photos from the RSS feeds are never used. A Commons file is accepted
only when it is a landscape JPEG or PNG under CC0, public domain, CC BY or CC BY-SA,
carries no usage restrictions, and its title or description matches the query.
Images are shown as "illustrative" and credited on the article and on /credits/.
"""

from __future__ import annotations

import json
import logging
import math
import re
import time
import urllib.error
import urllib.parse

from .article import Article
from .config import Settings
from .fetch import http_get
from .textutil import strip_html, tokens, truncate

log = logging.getLogger(__name__)

API = "https://commons.wikimedia.org/w/api.php"

_LICENSE_OK = re.compile(
    r"^(cc0|cc[- ]zero|pdm|public domain|pd[- ]|no known copyright|cc[- ]by(?:[- ]sa)?(?:[- ][0-9.]+)?\b)",
    re.IGNORECASE,
)
_LICENSE_BAD = re.compile(r"\b(nc|nd|noncommercial|non-commercial|noderivs|fair use|gfdl only)\b", re.IGNORECASE)
_TITLE_SKIP = re.compile(
    r"\b(logo|flag of|coat of arms|map of|locator|diagram|screenshot|poster|cover|portrait|"
    r"mugshot|passport|banknote|stamp|infographic|chart|graph|icon|"
    # photos of people and of specific events would mislead as an illustration of a different story
    r"envoy|ambassador|president|minister|secretary|senator|delegation|summit|visit|visits|meeting|meets|"
    r"speech|speaks|conference|rally|protest|protesters|ceremony|funeral|arrest|crash|attack|bombing|"
    r"strike|victims|refugees|soldiers|troops|wounded|editathon|workshop|training|meetup|photocall)\b",
    re.IGNORECASE,
)


def _meta(info: dict, key: str) -> str:
    value = (info.get("extmetadata") or {}).get(key) or {}
    return str(value.get("value") or "").strip()


def _license_ok(name: str) -> bool:
    return bool(name) and bool(_LICENSE_OK.match(name)) and not _LICENSE_BAD.search(name)


def _clean_title(title: str) -> str:
    title = re.sub(r"^File:", "", title)
    title = re.sub(r"\.(jpe?g|png)$", "", title, flags=re.IGNORECASE)
    return strip_html(title.replace("_", " ")).strip()


def _get_json(url: str, settings: Settings, retries: int = 2) -> dict:
    """GET with the API user agent; on 429 wait for Retry-After (at most 30 s) and try again."""
    for attempt in range(retries + 1):
        try:
            raw = http_get(url, settings.api_user_agent, settings.images_timeout, accept="application/json")
            return json.loads(raw)
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt == retries:
                raise
            try:
                wait = min(30.0, float(exc.headers.get("Retry-After", "5")))
            except (TypeError, ValueError):
                wait = 5.0
            log.info("Commons asked us to slow down; waiting %.0fs", wait)
            time.sleep(wait)
    raise RuntimeError("unreachable")


def _search(query: str, settings: Settings) -> list[dict]:
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrnamespace": "6",
        "gsrsearch": f"{query} filetype:bitmap",
        "gsrlimit": "20",
        "prop": "imageinfo",
        "iiprop": "url|size|mime|extmetadata",
        "iiurlwidth": str(settings.images_thumb_width),
        "iiextmetadatafilter": "LicenseShortName|LicenseUrl|Artist|ImageDescription|ObjectName|Restrictions|NonFree",
    }
    url = f"{API}?{urllib.parse.urlencode(params)}"
    data = _get_json(url, settings)
    pages = (data.get("query") or {}).get("pages") or {}
    return sorted(pages.values(), key=lambda p: p.get("index", 999))


def pick_image(query: str, pages: list[dict], settings: Settings, exclude: set[str] | None = None) -> dict | None:
    """Choose the first acceptable Commons result for *query*."""
    exclude = exclude or set()
    qtokens = tokens(query)
    needed = max(1, math.ceil(0.6 * len(qtokens)))
    for page in pages:
        infos = page.get("imageinfo") or []
        if not infos:
            continue
        info = infos[0]
        title = _clean_title(page.get("title", ""))
        if _TITLE_SKIP.search(title):
            continue
        if info.get("mime") not in ("image/jpeg", "image/png"):
            continue
        width, height = int(info.get("width") or 0), int(info.get("height") or 0)
        if width < settings.images_min_width or height <= 0 or not 1.2 <= width / height <= 2.4:
            continue
        licence = _meta(info, "LicenseShortName")
        if not _license_ok(licence):
            continue
        if _meta(info, "NonFree").lower() in ("true", "1", "yes") or _meta(info, "Restrictions"):
            continue
        thumb = (info.get("thumburl") or "").split("?")[0]
        if not thumb or thumb in exclude:
            continue
        # The file's own title must carry the query; a description that merely mentions it is not enough.
        haystack = tokens(f"{title} {_meta(info, 'ObjectName')}")
        if len(qtokens & haystack) < needed:
            continue
        author = truncate(strip_html(_meta(info, "Artist")), 80) or "Unknown author"
        return {
            "url": thumb,
            "width": int(info.get("thumbwidth") or 0),
            "height": int(info.get("thumbheight") or 0),
            "alt": f"Illustrative photo: {title}",
            "title": title,
            "author": author,
            "license": licence,
            "license_url": _meta(info, "LicenseUrl"),
            "page_url": info.get("descriptionurl") or "",
            "source": "Wikimedia Commons",
        }
    return None


def find_commons_image(query: str, settings: Settings, exclude: set[str] | None = None) -> dict | None:
    query = (query or "").strip()
    if not query:
        return None
    try:
        return pick_image(query, _search(query, settings), settings, exclude)
    except Exception as exc:  # noqa: BLE001 - an illustration is optional
        log.warning("image search failed for %r: %s", query, exc)
        return None


def attach_images(articles: list[Article], settings: Settings, used_urls: set[str] | None = None) -> int:
    """Fill ``image`` on articles that have an ``image_query``. Sequential on purpose (polite to Commons)."""
    if not settings.images_enabled:
        return 0
    used = set(used_urls or ())
    attached = 0
    first = True
    for article in articles:
        if article.image or not article.image_query:
            continue
        if not first:
            time.sleep(settings.images_delay)
        first = False
        found = find_commons_image(article.image_query, settings, exclude=used)
        if found:
            article.image = found
            used.add(found["url"])
            attached += 1
    log.info("attached openly licensed images to %d of %d articles", attached, len(articles))
    return attached
