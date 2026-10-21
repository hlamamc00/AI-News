"""The end-to-end run: fetch -> cluster -> select -> extract -> write -> store -> build."""

from __future__ import annotations

import concurrent.futures as cf
import logging
import time
from dataclasses import dataclass, field

from . import build as site_builder
from .cluster import Story, cluster_items, select_stories
from .config import Settings, Source, load_settings, load_sources
from .extract import enrich_items
from .fetch import fetch_all
from .store import State, recent_articles, save_article
from .textutil import tokens
from .writer import Newsroom

log = logging.getLogger(__name__)


@dataclass
class RunReport:
    feeds_ok: int = 0
    feeds_failed: int = 0
    items: int = 0
    stories: int = 0
    selected: int = 0
    written: int = 0
    by_writer: dict[str, int] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    seconds: float = 0.0

    def summary(self) -> str:
        writers = ", ".join(f"{k}={v}" for k, v in sorted(self.by_writer.items())) or "none"
        return (
            f"feeds {self.feeds_ok} ok / {self.feeds_failed} failed; {self.items} items -> "
            f"{self.stories} stories; selected {self.selected}; wrote {self.written} ({writers}) "
            f"in {self.seconds:.0f}s"
        )


def run(
    settings: Settings | None = None,
    sources: list[Source] | None = None,
    *,
    limit: int | None = None,
    writer_mode: str | None = None,
    extract: bool | None = None,
    build: bool = True,
    dry_run: bool = False,
) -> RunReport:
    settings = settings or load_settings()
    sources = sources or load_sources()
    report = RunReport()
    started = time.monotonic()

    # 1. Fetch
    items, errors = fetch_all(sources, settings)
    report.feeds_failed = len(errors)
    report.feeds_ok = len(sources) - len(errors)
    report.errors = errors

    # 2. Drop URLs we already turned into articles
    state = State.load()
    fresh = [i for i in items if not state.has(i.url)]
    report.items = len(fresh)
    log.info("%d items are new (%d already used)", len(fresh), len(items) - len(fresh))

    # 3. Cluster and select
    stories = cluster_items(fresh, settings.cluster_threshold)
    report.stories = len(stories)
    recent = recent_articles(settings.dedupe_window_hours)
    recent_keywords = [tokens(a.headline) | set(a.tags) for a in recent]
    selected = select_stories(stories, settings, recent_keywords, limit=limit)
    report.selected = len(selected)

    if dry_run:
        for story in selected:
            log.info(
                "[dry-run] %-11s %-11s %d src  %s",
                story.region, story.category, len(story.sources), story.lead.title,
            )
        report.seconds = time.monotonic() - started
        return report

    # 4. Enrich the lead sources with full text
    do_extract = settings.extract_enabled if extract is None else extract
    if do_extract and selected:
        to_fetch = []
        for story in selected:
            to_fetch.extend(story.ordered_items(settings.extract_per_story))
        enrich_items(to_fetch, settings)

    # 5. Write
    newsroom = Newsroom(settings, mode=writer_mode)
    written: list[tuple[Story, object]] = []

    def produce(story: Story):
        return story, newsroom.write(story)

    workers = settings.writer_workers if newsroom.active == "claude" else 1
    with cf.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for future in cf.as_completed([pool.submit(produce, s) for s in selected]):
            try:
                story, article = future.result()
            except Exception as exc:  # noqa: BLE001 - one failed story must not sink the run
                log.error("failed to write a story: %s", exc)
                continue
            written.append((story, article))

    # 6. Store
    for story, article in sorted(written, key=lambda pair: pair[0].score, reverse=True):
        path = save_article(article)  # type: ignore[arg-type]
        state.mark([i.url for i in story.items])
        report.written += 1
        report.by_writer[article.generated_by] = report.by_writer.get(article.generated_by, 0) + 1  # type: ignore[attr-defined]
        log.info("wrote %s", path.relative_to(path.parents[4]))
    state.save()

    # 7. Build the site
    if build:
        out = site_builder.build_site(settings)
        log.info("site built at %s", out)

    report.seconds = time.monotonic() - started
    log.info("run complete: %s", report.summary())
    return report
