"""The Article record that the writer produces and the site builder consumes."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from .taxonomy import CATEGORIES, REGIONS


@dataclass
class Article:
    slug: str
    headline: str
    standfirst: str
    body_markdown: str
    key_points: list[str]
    region: str
    category: str
    tags: list[str]
    confidence: str
    published_at: str  # ISO 8601, UTC
    sources: list[dict[str, Any]]
    image: dict[str, str] | None = None
    generated_by: str = "template"
    model: str | None = None
    word_count: int = 0
    id: str = ""

    def __post_init__(self) -> None:
        if self.region not in REGIONS:
            self.region = "global"
        if self.category not in CATEGORIES:
            self.category = "world"
        if self.confidence not in {"high", "medium", "low"}:
            self.confidence = "medium"
        if not self.word_count:
            self.word_count = len(self.body_markdown.split())
        if not self.id:
            self.id = f"{self.published_at[:10]}-{self.slug}"

    @property
    def published(self) -> datetime:
        dt = datetime.fromisoformat(self.published_at.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    @property
    def path(self) -> str:
        """Site-relative URL path, e.g. /articles/2026/10/21/my-story/."""
        d = self.published
        return f"/articles/{d:%Y}/{d:%m}/{d:%d}/{self.slug}/"

    @property
    def source_names(self) -> list[str]:
        names: list[str] = []
        for src in self.sources:
            if src.get("name") and src["name"] not in names:
                names.append(src["name"])
        return names

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Article":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})
