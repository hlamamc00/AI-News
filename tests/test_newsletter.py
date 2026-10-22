from datetime import datetime, timedelta, timezone

from newsbot.article import Article
from newsbot.build import build_site
from newsbot.config import Settings
from newsbot.newsletter import build_edition, build_editions

UTC = timezone.utc


def art(n, when, region="europe", sources=2, confidence="high"):
    return Article(
        slug=f"story-{n}", headline=f"Story {n}", standfirst=f"Standfirst {n}.", body_markdown="Body " * 70,
        key_points=["k"], region=region, category="world", tags=["t"], confidence=confidence,
        published_at=when.isoformat(),
        sources=[{"name": f"Outlet{i}", "country": "X", "title": "t", "url": f"https://o{i}.example/{n}",
                  "published_at": when.isoformat()} for i in range(sources)],
        differences=[{"outlets": ["Outlet0", "Outlet1"], "point": "Outlet0 and Outlet1 give different figures here."}] if n == 0 else [],
    )


def day_articles(day, count, start_hour=8):
    base = datetime(day.year, day.month, day.day, start_hour, tzinfo=UTC)
    return [art(f"{day:%d}-{i}", base + timedelta(minutes=10 * i), region=["europe", "asia", "africa"][i % 3],
                sources=1 + i % 4) for i in range(count)]


def test_edition_covers_the_24_hours_before_the_edition_hour():
    s = Settings({"newsletter": {"edition_hour_utc": 6, "min_articles": 3}})
    inside = [art("in1", datetime(2026, 10, 20, 7, tzinfo=UTC)), art("in2", datetime(2026, 10, 20, 23, tzinfo=UTC)),
              art("in3", datetime(2026, 10, 21, 5, 59, tzinfo=UTC))]
    outside = [art("old", datetime(2026, 10, 20, 5, 59, tzinfo=UTC)), art("new", datetime(2026, 10, 21, 6, tzinfo=UTC))]
    ed = build_edition(datetime(2026, 10, 21).date(), inside + outside, s, "Desk")
    assert ed and ed.count == 3 and {a.slug for a in ed.top} == {"story-in1", "story-in2", "story-in3"}
    assert ed.path == "/newsletter/2026-10-21/" and ed.subject.startswith("Desk briefing, 21 October 2026: ")


def test_edition_needs_enough_articles_and_a_finished_window():
    s = Settings({"newsletter": {"edition_hour_utc": 6, "min_articles": 6}})
    arts = day_articles(datetime(2026, 10, 20).date(), 5)
    assert build_editions(arts, s, "Desk", now=datetime(2026, 10, 22, tzinfo=UTC)) == []
    arts = day_articles(datetime(2026, 10, 20).date(), 8)
    assert [e.key for e in build_editions(arts, s, "Desk", now=datetime(2026, 10, 22, tzinfo=UTC))] == ["2026-10-21"]
    assert build_editions(arts, s, "Desk", now=datetime(2026, 10, 21, 5, tzinfo=UTC)) == []  # window not over yet
    assert build_editions(arts, Settings({"newsletter": {"enabled": False}}), "Desk", now=datetime(2026, 10, 22, tzinfo=UTC)) == []


def test_top_stories_prefer_more_sources_and_regions_exclude_top():
    s = Settings({"newsletter": {"min_articles": 3, "top_stories": 2, "per_region": 1}})
    when = datetime(2026, 10, 20, 8, tzinfo=UTC)
    arts = [art("a", when, sources=1), art("b", when + timedelta(minutes=1), sources=4),
            art("c", when + timedelta(minutes=2), sources=3, region="asia"), art("d", when + timedelta(minutes=3), sources=2, region="asia")]
    ed = build_edition(datetime(2026, 10, 21).date(), arts, s, "Desk")
    assert [a.slug for a in ed.top] == ["story-b", "story-c"]
    assert [(slug, [a.slug for a in items]) for slug, _, items in ed.regions] == [("asia", ["story-d"]), ("europe", ["story-a"])]


def test_build_site_writes_editions_feed_and_text(tmp_path):
    s = Settings({"site": {"title": "Desk", "base_url": "https://x.example"}, "newsletter": {"min_articles": 3}})
    arts = day_articles(datetime(2026, 10, 20).date(), 8)
    out = build_site(s, arts, tmp_path / "site")
    page = out / "newsletter/2026-10-21/index.html"
    assert page.exists() and "Top stories" in page.read_text() and "https://x.example/articles/" in page.read_text()
    text = (out / "newsletter/2026-10-21/index.txt").read_text()
    assert text.startswith("Desk daily briefing, 21 October 2026") and "TOP STORIES" in text
    feed = (out / "newsletter/feed.xml").read_text()
    assert "<content:encoded><![CDATA[" in feed and "https://x.example/newsletter/2026-10-21/" in feed
    assert "Wed, 21 Oct 2026 06:00:00 +0000" in feed
    index = (out / "newsletter/index.html").read_text()
    assert "Recent editions" in index and "2026-10-21" in (out / "sitemap.xml").read_text()
    from xml.dom import minidom
    for xml in ("newsletter/feed.xml", "feed.xml", "sitemap.xml"):
        minidom.parse(str(out / xml))  # well-formed


def test_newsletter_can_be_switched_off(tmp_path):
    s = Settings({"newsletter": {"enabled": False}})
    out = build_site(s, day_articles(datetime(2026, 10, 20).date(), 8), tmp_path / "site")
    assert not (out / "newsletter").exists()
    assert "/newsletter/" not in (out / "index.html").read_text()
