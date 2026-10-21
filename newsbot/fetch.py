"""Fetch and normalise items from the RSS/Atom catalogue."""

from __future__ import annotations

import concurrent.futures as cf
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import feedparser

from .config import Settings, Source
from .textutil import canonical_url, clean_summary, clean_title, is_noise_title, truncate

log = logging.getLogger(__name__)


@dataclass
class Item:
    """One normalised feed entry."""

    title: str
    url: str
    summary: str
    published: datetime
    source: str
    country: str
    region: str
    category: str
    image: str | None = None
    full_text: str = ""
    # Populated by the extractor when it fetched the page.
    extracted: bool = False
    meta: dict = field(default_factory=dict)

    @property
    def text(self) -> str:
        """Best available body text for this item."""
        return self.full_text or self.summary

    def to_source_ref(self) -> dict:
        return {
            "name": self.source,
            "country": self.country,
            "title": self.title,
            "url": self.url,
            "published_at": self.published.isoformat(),
        }


def http_get(url: str, user_agent: str, timeout: float, accept: str = "*/*") -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": accept,
            "Accept-Language": "en;q=0.9, *;q=0.5",
            "Accept-Encoding": "identity",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (http(s) only, from config)
        return resp.read()


def _entry_datetime(entry, now: datetime) -> datetime | None:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        value = entry.get(key)
        if value:
            try:
                dt = datetime(*value[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
            # Some feeds publish slightly in the future; clamp instead of dropping.
            if dt > now + timedelta(hours=1):
                return now
            return dt
    return None


def _entry_summary(entry) -> str:
    candidates = []
    if entry.get("summary"):
        candidates.append(entry["summary"])
    if entry.get("description"):
        candidates.append(entry["description"])
    for content in entry.get("content") or []:
        if content.get("value"):
            candidates.append(content["value"])
    best = max((clean_summary(c) for c in candidates), key=len, default="")
    if len(best) < 40:  # "[allAfrica]", "Read more", a bare source name
        return ""
    return truncate(best, 1500)


def _entry_image(entry) -> str | None:
    best_url, best_width = None, -1
    for media in list(entry.get("media_content") or []) + list(entry.get("media_thumbnail") or []):
        url = media.get("url")
        if not url:
            continue
        mtype = (media.get("type") or media.get("medium") or "").lower()
        if mtype and not (mtype.startswith("image") or mtype == "image"):
            continue
        try:
            width = int(media.get("width") or 0)
        except (TypeError, ValueError):
            width = 0
        if width > best_width:
            best_url, best_width = url, width
    if best_url:
        return best_url
    for enc in entry.get("enclosures") or []:
        if (enc.get("type") or "").startswith("image") and enc.get("href"):
            return enc["href"]
    for link in entry.get("links") or []:
        if link.get("rel") == "enclosure" and (link.get("type") or "").startswith("image") and link.get("href"):
            return link["href"]
    return None


def parse_feed(source: Source, data: bytes, settings: Settings, now: datetime | None = None) -> list[Item]:
    """Turn raw feed bytes into Items, dropping stale or malformed entries."""
    now = now or datetime.now(timezone.utc)
    parsed = feedparser.parse(data)
    if not parsed.entries and (parsed.bozo or not parsed.version):
        reason = getattr(parsed, "bozo_exception", None) or "not an RSS/Atom document"
        raise ValueError(f"unparseable feed: {reason}")
    cutoff = now - timedelta(hours=settings.max_age_hours)
    items: list[Item] = []
    for entry in parsed.entries[: settings.per_feed_limit * 2]:
        url = canonical_url(entry.get("link") or "")
        title = clean_title(entry.get("title") or "")
        if not url or not title or not url.startswith(("http://", "https://")):
            continue
        if is_noise_title(title):
            continue
        published = _entry_datetime(entry, now)
        if published is None:
            # Undated entries are treated as "now" once (first time we see them);
            # the seen-URL state stops them being picked up again later.
            published = now
        if published < cutoff:
            continue
        items.append(
            Item(
                title=title,
                url=url,
                summary=_entry_summary(entry),
                published=published,
                source=source.name,
                country=source.country,
                region=source.region,
                category=source.category,
                image=_entry_image(entry),
            )
        )
        if len(items) >= settings.per_feed_limit:
            break
    return items


def fetch_source(source: Source, settings: Settings) -> list[Item]:
    data = http_get(
        source.url,
        settings.user_agent,
        settings.fetch_timeout,
        accept="application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8",
    )
    return parse_feed(source, data, settings)


def fetch_all(sources: list[Source], settings: Settings) -> tuple[list[Item], dict[str, str]]:
    """Fetch every feed concurrently. Returns (items, {source name: error})."""
    items: list[Item] = []
    errors: dict[str, str] = {}
    started = time.monotonic()
    with cf.ThreadPoolExecutor(max_workers=settings.fetch_workers) as pool:
        futures = {pool.submit(fetch_source, src, settings): src for src in sources}
        for future in cf.as_completed(futures):
            src = futures[future]
            try:
                got = future.result()
            except Exception as exc:  # noqa: BLE001 - one bad feed must not stop the run
                errors[src.name] = f"{type(exc).__name__}: {exc}"
                log.warning("feed failed: %s (%s)", src.name, errors[src.name])
                continue
            items.extend(got)
            log.debug("feed ok: %s -> %d items", src.name, len(got))
    # The same URL can appear in several feeds from the same publisher
    # (e.g. BBC World and BBC Africa). Keep the most specific region.
    by_url: dict[str, Item] = {}
    for item in items:
        existing = by_url.get(item.url)
        if existing is None or (existing.region == "global" and item.region != "global"):
            by_url[item.url] = item
    log.info(
        "fetched %d items from %d/%d feeds in %.1fs",
        len(by_url), len(sources) - len(errors), len(sources), time.monotonic() - started,
    )
    return list(by_url.values()), errors
