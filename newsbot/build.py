"""Static site generator: turns stored articles into HTML, RSS, a sitemap and a search index."""

from __future__ import annotations

import json
import logging
import re
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import markdown
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from .article import Article
from .config import ROOT, TEMPLATES_DIR, Settings, load_sources
from .newsletter import build_editions
from .store import load_articles
from .taxonomy import CATEGORIES, CATEGORY_LABELS, REGION_LABELS, REGIONS

log = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")


def render_markdown(text: str) -> str:
    """Markdown -> HTML with any raw HTML in the source removed first."""
    return markdown.markdown(_TAG_RE.sub("", text or ""), output_format="html")


def _fmt_date(value: datetime | str) -> str:
    dt = _as_dt(value)
    return f"{dt.day} {dt:%B %Y}"


def _fmt_datetime(value: datetime | str) -> str:
    dt = _as_dt(value)
    return f"{dt.day} {dt:%b %Y}, {dt:%H:%M} UTC"


def _rfc822(value: datetime | str) -> str:
    return _as_dt(value).strftime("%a, %d %b %Y %H:%M:%S +0000")


def _as_dt(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _cdata(html: str) -> Markup:
    """Make *html* safe to place inside a CDATA section."""
    return Markup(str(html).replace("]]>", "]]]]><![CDATA[>"))


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def build_site(settings: Settings, articles: list[Article] | None = None, output_dir: Path | None = None) -> Path:
    articles = load_articles() if articles is None else sorted(articles, key=lambda a: a.published, reverse=True)
    out = Path(output_dir or settings.output_dir)
    if out.resolve() in (ROOT.resolve(), Path("/")):
        raise ValueError("refusing to build into the project root")
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    base_url = settings.base_url
    base_path = urlsplit(base_url).path.rstrip("/") if base_url else ""
    now = datetime.now(timezone.utc)
    sources = load_sources()

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["md"] = render_markdown
    env.filters["fmt_date"] = _fmt_date
    env.filters["fmt_datetime"] = _fmt_datetime
    env.filters["rfc822"] = _rfc822
    env.filters["region_label"] = lambda slug: REGION_LABELS.get(slug, slug)
    env.filters["category_label"] = lambda slug: CATEGORY_LABELS.get(slug, slug)
    env.filters["cdata"] = _cdata
    env.filters["feed_html"] = lambda a: _cdata(env.get_template("_feed_item.html").render(article=a))
    env.globals.update(
        site={
            "title": settings.site_title,
            "tagline": settings.site_tagline,
            "byline": settings.site_byline,
            "base_url": base_url,
            "language": settings.site_language,
            "generated_at": now,
            "year": now.year,
            "article_count": len(articles),
            "source_count": len(sources),
            "subscribe": {
                "url": settings.subscribe_url,
                "email_field": settings.subscribe_email_field,
                "method": settings.subscribe_method if settings.subscribe_method in ("get", "post") else "post",
                "hidden": settings.subscribe_hidden,
            },
        },
        newsletter_enabled=settings.newsletter_enabled,
        regions=[{"slug": r, "label": REGION_LABELS[r], "path": f"/region/{r}/"} for r in REGIONS],
        topics=[{"slug": c, "label": CATEGORY_LABELS[c], "path": f"/topic/{c}/"} for c in CATEGORIES],
        u=lambda path: f"{base_path}{path}",
        abs_url=lambda path: f"{base_url}{path}" if base_url else path,
    )

    def page(template: str, rel_path: str, **ctx) -> None:
        html = env.get_template(template).render(**ctx)
        _write(out / rel_path.lstrip("/"), html)

    def feed(rel_path: str, title: str, page_path: str, description: str, items: list[Article]) -> None:
        page(
            "feed.xml", rel_path,
            articles=items[: settings.feed_items], feed_title=title, feed_page=page_path,
            feed_self=rel_path, feed_description=description,
        )

    # --- home
    latest = articles[: settings.home_items]
    hero = next((a for a in latest if a.confidence != "low" and len(a.source_names) >= 2), latest[0] if latest else None)
    rest = [a for a in latest if a is not hero]
    by_region: dict[str, list[Article]] = defaultdict(list)
    by_category: dict[str, list[Article]] = defaultdict(list)
    for a in articles:
        by_region[a.region].append(a)
        by_category[a.category].append(a)
    rails = [
        {"slug": r, "label": REGION_LABELS[r], "path": f"/region/{r}/", "items": by_region[r][:4]}
        for r in REGIONS
        if by_region.get(r)
    ]
    page("index.html", "index.html", hero=hero, articles=rest, rails=rails, title=None)

    # --- sections
    for r in REGIONS:
        page(
            "section.html",
            f"/region/{r}/index.html",
            title=REGION_LABELS[r],
            kicker="Region",
            description=f"The latest {REGION_LABELS[r]} coverage.",
            articles=by_region.get(r, [])[: settings.section_items],
            feed_path=f"/region/{r}/feed.xml",
            feed_label=f"{REGION_LABELS[r]}",
        )
        feed(
            f"/region/{r}/feed.xml", f"{settings.site_title}: {REGION_LABELS[r]}", f"/region/{r}/",
            f"The latest {REGION_LABELS[r]} stories.", by_region.get(r, []),
        )
    for c in CATEGORIES:
        page(
            "section.html",
            f"/topic/{c}/index.html",
            title=CATEGORY_LABELS[c],
            kicker="Topic",
            description=f"The latest {CATEGORY_LABELS[c].lower()} stories from around the world.",
            articles=by_category.get(c, [])[: settings.section_items],
            feed_path=f"/topic/{c}/feed.xml",
            feed_label=f"{CATEGORY_LABELS[c]}",
        )
        feed(
            f"/topic/{c}/feed.xml", f"{settings.site_title}: {CATEGORY_LABELS[c]}", f"/topic/{c}/",
            f"The latest {CATEGORY_LABELS[c].lower()} stories from around the world.", by_category.get(c, []),
        )

    # --- articles
    for a in articles:
        related = [
            b for b in articles if b is not a and (b.region == a.region or b.category == a.category)
        ][:4]
        page("article.html", f"{a.path}index.html", article=a, related=related, title=a.headline)

    # --- archive, about, search, 404
    by_day: dict[str, list[Article]] = defaultdict(list)
    for a in articles:
        by_day[a.published.strftime("%Y-%m-%d")].append(a)
    page("archive.html", "/archive/index.html", days=sorted(by_day.items(), reverse=True), title="Archive")
    grouped_sources: dict[str, list] = defaultdict(list)
    for src in sources:
        grouped_sources[src.region].append(src)
    page(
        "about.html",
        "/about/index.html",
        title="About",
        grouped_sources=[(REGION_LABELS[r], grouped_sources[r]) for r in REGIONS if grouped_sources.get(r)],
    )
    page("search.html", "/search/index.html", title="Search")
    page("404.html", "404.html", title="Page not found")

    # --- newsletter
    editions = build_editions(articles, settings, settings.site_title)
    if settings.newsletter_enabled:
        digest = env.get_template("_digest.html")
        digest_text = env.get_template("_digest.txt")
        for e in editions:
            e.html = digest.render(edition=e).strip()
            e.text = digest_text.render(edition=e).strip() + "\n"
            page("newsletter_edition.html", f"{e.path}index.html", edition=e, digest_html=e.html, title=e.subject)
            _write(out / e.path.lstrip("/") / "index.txt", e.text)
        page(
            "newsletter.html", "/newsletter/index.html", title="Newsletter",
            editions=editions[: settings.newsletter_archive_items],
        )
        page("newsletter_feed.xml", "/newsletter/feed.xml", editions=editions[:14])

    # --- feeds index and image credits
    page("feeds.html", "/feeds/index.html", title="RSS feeds")
    page("credits.html", "/credits/index.html", title="Image credits", credits=[a for a in articles if a.image])

    # --- machine-readable
    feed("feed.xml", settings.site_title, "/", settings.site_tagline, articles)
    page("sitemap.xml", "sitemap.xml", articles=articles, editions=editions)
    _write(out / "robots.txt", f"User-agent: *\nAllow: /\nSitemap: {base_url}/sitemap.xml\n" if base_url else "User-agent: *\nAllow: /\n")
    index = [
        {
            "headline": a.headline,
            "standfirst": a.standfirst,
            "url": f"{base_path}{a.path}",
            "date": a.published_at[:10],
            "region": REGION_LABELS.get(a.region, a.region),
            "category": CATEGORY_LABELS.get(a.category, a.category),
            "tags": a.tags,
            "sources": a.source_names,
        }
        for a in articles
    ]
    _write(out / "search.json", json.dumps(index, ensure_ascii=False))
    _write(out / ".nojekyll", "")

    # --- static assets
    static_src = TEMPLATES_DIR / "static"
    if static_src.exists():
        shutil.copytree(static_src, out / "static", dirs_exist_ok=True)

    log.info("built %d article pages into %s", len(articles), out)
    return out
