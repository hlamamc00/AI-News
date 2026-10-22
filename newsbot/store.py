"""Persistence: article JSON files under content/articles and the seen-URL state."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .article import Article
from .config import ARTICLES_DIR, STATE_FILE

log = logging.getLogger(__name__)


def article_path(article: Article, root: Path = ARTICLES_DIR) -> Path:
    d = article.published
    return root / f"{d:%Y}" / f"{d:%m}" / f"{d:%d}" / f"{article.slug}.json"


def save_article(article: Article, root: Path = ARTICLES_DIR) -> Path:
    """Write the article, de-duplicating the slug within its day if needed."""
    path = article_path(article, root)
    base_slug = article.slug
    counter = 2
    while path.exists():
        article.slug = f"{base_slug}-{counter}"
        article.id = f"{article.published_at[:10]}-{article.slug}"
        path = article_path(article, root)
        counter += 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(article.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def load_articles(root: Path = ARTICLES_DIR) -> list[Article]:
    """All stored articles, newest first."""
    articles: list[Article] = []
    if not root.exists():
        return articles
    for path in root.rglob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            articles.append(Article.from_dict(data))
        except (OSError, ValueError, TypeError) as exc:
            log.warning("skipping unreadable article %s: %s", path, exc)
    articles.sort(key=lambda a: a.published, reverse=True)
    return articles


def recent_articles(hours: float, root: Path = ARTICLES_DIR) -> list[Article]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    return [a for a in load_articles(root) if a.published >= cutoff]


class State:
    """URLs already turned into articles, so a story is not rewritten from the same items."""

    def __init__(self, path: Path = STATE_FILE) -> None:
        self.path = path
        self.seen_urls: dict[str, str] = {}
        # url -> number of times the writer rejected a story built from it
        self.failures: dict[str, int] = {}
        self._failure_stamps: dict[str, str] = {}

    @classmethod
    def load(cls, path: Path = STATE_FILE) -> "State":
        state = cls(path)
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                state.seen_urls = dict(data.get("seen_urls", {}))
                state.failures = {k: int(v) for k, v in dict(data.get("failures", {})).items()}
                state._failure_stamps = dict(data.get("failure_stamps", {}))
            except (OSError, ValueError) as exc:
                log.warning("could not read state file %s: %s", path, exc)
        return state

    def has(self, url: str) -> bool:
        return url in self.seen_urls

    def failed(self, url: str, limit: int = 2) -> bool:
        """True once the writer has rejected this URL *limit* times."""
        return self.failures.get(url, 0) >= limit

    def fail(self, urls: list[str], when: datetime | None = None) -> None:
        stamp = (when or datetime.now(timezone.utc)).isoformat()
        for url in urls:
            self.failures[url] = self.failures.get(url, 0) + 1
            self._failure_stamps[url] = stamp

    def mark(self, urls: list[str], when: datetime | None = None) -> None:
        stamp = (when or datetime.now(timezone.utc)).isoformat()
        for url in urls:
            self.seen_urls[url] = stamp

    def prune(self, max_age_days: float = 10) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        keep: dict[str, str] = {}
        for url, stamp in self.seen_urls.items():
            try:
                when = datetime.fromisoformat(stamp)
            except ValueError:
                continue
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            if when >= cutoff:
                keep[url] = stamp
        self.seen_urls = keep
        live = {}
        for url, stamp in self._failure_stamps.items():
            try:
                when = datetime.fromisoformat(stamp)
            except ValueError:
                continue
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            if when >= cutoff:
                live[url] = stamp
        self._failure_stamps = live
        self.failures = {u: n for u, n in self.failures.items() if u in live}

    def save(self) -> None:
        self.prune()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "seen_urls": dict(sorted(self.seen_urls.items())),
            "failures": dict(sorted(self.failures.items())),
            "failure_stamps": dict(sorted(self._failure_stamps.items())),
        }
        self.path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
