"""Settings and feed catalogue loading."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .taxonomy import CATEGORIES, REGIONS

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
CONTENT_DIR = ROOT / "content"
ARTICLES_DIR = CONTENT_DIR / "articles"
STATE_FILE = CONTENT_DIR / "state.json"
# Local preview output (template writer). Git-ignored and never deployed.
PREVIEW_DIR = CONTENT_DIR / "preview"
PREVIEW_STATE_FILE = CONTENT_DIR / "preview-state.json"
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    region: str = "global"
    category: str = "world"
    country: str = ""

    def __post_init__(self) -> None:
        if self.region not in REGIONS:
            raise ValueError(f"source {self.name!r}: unknown region {self.region!r}")
        if self.category not in CATEGORIES:
            raise ValueError(f"source {self.name!r}: unknown category {self.category!r}")


@dataclass
class Settings:
    """A thin wrapper over the settings.yaml mapping with typed accessors."""

    raw: dict[str, Any] = field(default_factory=dict)

    # --- site
    @property
    def site_title(self) -> str:
        return str(self._get("site", "title", default="AI News Desk"))

    @property
    def site_tagline(self) -> str:
        return str(self._get("site", "tagline", default=""))

    @property
    def site_byline(self) -> str:
        return str(self._get("site", "byline", default="Automated newsroom"))

    @property
    def site_language(self) -> str:
        return str(self._get("site", "language", default="en"))

    @property
    def base_url(self) -> str:
        env = os.environ.get("NEWSBOT_BASE_URL")
        value = env or str(self._get("site", "base_url", default=""))
        return value.rstrip("/")

    # --- fetch
    @property
    def max_age_hours(self) -> float:
        return float(self._get("fetch", "max_age_hours", default=36))

    @property
    def per_feed_limit(self) -> int:
        return int(self._get("fetch", "per_feed_limit", default=40))

    @property
    def fetch_timeout(self) -> float:
        return float(self._get("fetch", "timeout_seconds", default=20))

    @property
    def fetch_workers(self) -> int:
        return int(self._get("fetch", "workers", default=16))

    @property
    def user_agent(self) -> str:
        return str(self._get("fetch", "user_agent", default="AINewsDeskBot/1.0"))

    @property
    def api_user_agent(self) -> str:
        """Descriptive agent for public APIs such as Wikimedia, which throttle browser-style agents."""
        return str(self._get("fetch", "api_user_agent", default="AINewsDeskBot/1.0 (+https://github.com/hlamamc00/AI-News)"))

    # --- extract
    @property
    def extract_enabled(self) -> bool:
        return bool(self._get("extract", "enabled", default=True))

    @property
    def extract_per_story(self) -> int:
        return int(self._get("extract", "per_story", default=2))

    @property
    def extract_max_chars(self) -> int:
        return int(self._get("extract", "max_chars", default=3500))

    @property
    def extract_timeout(self) -> float:
        return float(self._get("extract", "timeout_seconds", default=20))

    @property
    def extract_workers(self) -> int:
        return int(self._get("extract", "workers", default=8))

    # --- articles
    @property
    def max_per_run(self) -> int:
        env = os.environ.get("NEWSBOT_MAX_ARTICLES")
        return int(env) if env else int(self._get("articles", "max_per_run", default=24))

    @property
    def per_region_min(self) -> int:
        return int(self._get("articles", "per_region_min", default=2))

    @property
    def per_topic_min(self) -> int:
        return int(self._get("articles", "per_topic_min", default=1))

    @property
    def max_category_share(self) -> float:
        return float(self._get("articles", "max_category_share", default=0.4))

    @property
    def dedupe_window_hours(self) -> float:
        return float(self._get("articles", "dedupe_window_hours", default=48))

    @property
    def dedupe_threshold(self) -> float:
        return float(self._get("articles", "dedupe_threshold", default=0.5))

    # --- cluster
    @property
    def cluster_threshold(self) -> float:
        return float(self._get("cluster", "threshold", default=0.45))

    # --- writer
    @property
    def writer_mode(self) -> str:
        mode = os.environ.get("NEWSBOT_WRITER") or str(self._get("writer", "mode", default="auto"))
        mode = mode.lower()
        if mode not in {"auto", "claude", "template"}:
            raise ValueError(f"writer.mode must be auto|claude|template, got {mode!r}")
        return mode

    @property
    def writer_model(self) -> str:
        return str(self._get("writer", "model", default="claude-opus-5-5"))

    @property
    def writer_effort(self) -> str:
        return str(self._get("writer", "effort", default="medium"))

    @property
    def writer_max_tokens(self) -> int:
        return int(self._get("writer", "max_tokens", default=16000))

    @property
    def max_verbatim_ratio(self) -> float:
        return float(self._get("writer", "max_verbatim_ratio", default=0.10))

    @property
    def writer_workers(self) -> int:
        return int(self._get("writer", "workers", default=3))

    @property
    def writer_max_sources(self) -> int:
        return int(self._get("writer", "max_sources", default=6))

    # --- build
    @property
    def output_dir(self) -> Path:
        return ROOT / str(self._get("build", "output_dir", default="site"))

    @property
    def home_items(self) -> int:
        return int(self._get("build", "home_items", default=30))

    @property
    def section_items(self) -> int:
        return int(self._get("build", "section_items", default=60))

    @property
    def feed_items(self) -> int:
        return int(self._get("build", "feed_items", default=50))

    # --- images
    @property
    def images_enabled(self) -> bool:
        return bool(self._get("images", "enabled", default=True))

    @property
    def images_min_width(self) -> int:
        return int(self._get("images", "min_width", default=1000))

    @property
    def images_thumb_width(self) -> int:
        return int(self._get("images", "thumb_width", default=960))

    @property
    def images_delay(self) -> float:
        return float(self._get("images", "delay_seconds", default=1.0))

    @property
    def images_timeout(self) -> float:
        return float(self._get("images", "timeout_seconds", default=20))

    # --- newsletter
    @property
    def newsletter_enabled(self) -> bool:
        return bool(self._get("newsletter", "enabled", default=True))

    @property
    def newsletter_hour_utc(self) -> int:
        return int(self._get("newsletter", "edition_hour_utc", default=6)) % 24

    @property
    def newsletter_min_articles(self) -> int:
        return int(self._get("newsletter", "min_articles", default=6))

    @property
    def newsletter_top_stories(self) -> int:
        return int(self._get("newsletter", "top_stories", default=5))

    @property
    def newsletter_per_region(self) -> int:
        return int(self._get("newsletter", "per_region", default=3))

    @property
    def newsletter_archive_items(self) -> int:
        return int(self._get("newsletter", "archive_items", default=60))

    @property
    def subscribe_url(self) -> str:
        env = os.environ.get("NEWSBOT_SUBSCRIBE_URL")
        return (env or str(self._get("newsletter", "subscribe_url", default=""))).strip()

    @property
    def subscribe_email_field(self) -> str:
        return str(self._get("newsletter", "subscribe_email_field", default="email"))

    @property
    def subscribe_method(self) -> str:
        return str(self._get("newsletter", "subscribe_method", default="post")).lower()

    @property
    def subscribe_hidden(self) -> dict[str, str]:
        hidden = self._get("newsletter", "subscribe_hidden_fields", default={}) or {}
        return {str(k): str(v) for k, v in dict(hidden).items()}

    def _get(self, *keys: str, default: Any = None) -> Any:
        node: Any = self.raw
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return default if node is None else node


def load_settings(path: Path | None = None) -> Settings:
    path = path or CONFIG_DIR / "settings.yaml"
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return Settings(raw=data)


def load_sources(path: Path | None = None) -> list[Source]:
    path = path or CONFIG_DIR / "sources.yaml"
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    sources: list[Source] = []
    seen: set[str] = set()
    for entry in data.get("sources", []):
        src = Source(
            name=str(entry["name"]).strip(),
            url=str(entry["url"]).strip(),
            region=str(entry.get("region", "global")).strip(),
            category=str(entry.get("category", "world")).strip(),
            country=str(entry.get("country", "")).strip(),
        )
        if src.url in seen:
            continue
        seen.add(src.url)
        sources.append(src)
    return sources
