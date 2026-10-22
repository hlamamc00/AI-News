"""Daily briefing editions, built deterministically from stored articles.

An edition dated D covers the 24 hours before ``edition_hour_utc`` on D and exists
once that moment has passed. Because it is derived purely from the stored
articles, a rebuild reproduces every edition and no extra state is needed.
The site publishes each edition as a web page, as plain text, and as an item in
``/newsletter/feed.xml`` so an email provider's "RSS to email" campaign can send it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from .article import Article
from .config import Settings
from .taxonomy import REGION_LABELS, REGIONS

_CONFIDENCE_RANK = {"high": 2, "medium": 1, "low": 0}


@dataclass
class Edition:
    day: date
    start: datetime
    end: datetime
    top: list[Article]
    regions: list[tuple[str, str, list[Article]]]  # (slug, label, articles)
    subject: str
    count: int = 0
    html: str = field(default="", repr=False)
    text: str = field(default="", repr=False)

    @property
    def key(self) -> str:
        return f"{self.day:%Y-%m-%d}"

    @property
    def path(self) -> str:
        return f"/newsletter/{self.key}/"

    @property
    def date_label(self) -> str:
        return f"{self.day.day} {self.day:%B %Y}"


def _rank(article: Article) -> tuple:
    return (len(article.source_names), _CONFIDENCE_RANK.get(article.confidence, 1), article.published)


def build_edition(day: date, articles: list[Article], settings: Settings, site_title: str) -> Edition | None:
    end = datetime(day.year, day.month, day.day, settings.newsletter_hour_utc, tzinfo=timezone.utc)
    start = end - timedelta(hours=24)
    window = [a for a in articles if start <= a.published < end]
    if not window or len(window) < settings.newsletter_min_articles:
        return None
    ranked = sorted(window, key=_rank, reverse=True)
    top = ranked[: settings.newsletter_top_stories]
    top_ids = {a.id for a in top}
    regions: list[tuple[str, str, list[Article]]] = []
    for slug in REGIONS:
        picks = [a for a in ranked if a.region == slug and a.id not in top_ids][: settings.newsletter_per_region]
        if picks:
            regions.append((slug, REGION_LABELS[slug], picks))
    subject = f"{site_title} briefing, {day.day} {day:%B %Y}: {top[0].headline}"
    return Edition(day=day, start=start, end=end, top=top, regions=regions, subject=subject, count=len(window))


def build_editions(articles: list[Article], settings: Settings, site_title: str, now: datetime | None = None) -> list[Edition]:
    """All editions that exist at *now*, newest first."""
    if not settings.newsletter_enabled or not articles:
        return []
    now = now or datetime.now(timezone.utc)
    first = min(a.published for a in articles).date()
    last = max(a.published for a in articles).date() + timedelta(days=1)
    editions: list[Edition] = []
    day = first
    while day <= last:
        end = datetime(day.year, day.month, day.day, settings.newsletter_hour_utc, tzinfo=timezone.utc)
        if end <= now:
            edition = build_edition(day, articles, settings, site_title)
            if edition:
                editions.append(edition)
        day += timedelta(days=1)
    editions.sort(key=lambda e: e.day, reverse=True)
    return editions
