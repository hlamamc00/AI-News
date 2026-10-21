import json

from newsbot.article import Article
from newsbot.build import build_site, render_markdown
from newsbot.config import Settings


def _article(slug, region="europe", category="world", day="21"):
    return Article(
        slug=slug, headline=f"Headline {slug}", standfirst="Stand first.", body_markdown="## Sub\n\nBody **text**.",
        key_points=["one", "two"], region=region, category=category, tags=["t1"], confidence="high",
        published_at=f"2026-10-{day}T10:00:00+00:00",
        sources=[{"name": "BBC", "country": "UK", "title": "Src", "url": "https://bbc.example/x", "published_at": "2026-10-21T09:00:00+00:00"}],
        image={"url": "https://img.example/a.jpg", "credit": "BBC"},
    )


def test_render_markdown_strips_raw_html():
    html = render_markdown("Hello <script>alert(1)</script> **bold**")
    assert "<script>" not in html and "<strong>bold</strong>" in html


def test_build_site_writes_pages_with_base_path(tmp_path):
    settings = Settings({"site": {"title": "Test Desk", "base_url": "https://user.github.io/AI-News"}})
    out = build_site(settings, [_article("first"), _article("second", region="asia", category="sport", day="20")], tmp_path / "site")
    index = (out / "index.html").read_text()
    assert "Headline first" in index
    assert 'href="/AI-News/region/asia/"' in index
    page = out / "articles" / "2026" / "10" / "21" / "first" / "index.html"
    assert page.exists()
    html = page.read_text()
    assert "<strong>text</strong>" in html and "https://bbc.example/x" in html
    assert (out / "region" / "asia" / "index.html").read_text().count("Headline second") >= 1
    assert (out / "topic" / "sport" / "index.html").exists()
    feed = (out / "feed.xml").read_text()
    assert "https://user.github.io/AI-News/articles/2026/10/21/first/" in feed
    search = json.loads((out / "search.json").read_text())
    assert search[0]["url"] == "/AI-News/articles/2026/10/21/first/"
    assert (out / "static" / "style.css").exists()
    assert (out / ".nojekyll").exists()


def test_build_site_handles_no_articles(tmp_path):
    out = build_site(Settings({}), [], tmp_path / "site")
    assert "No articles yet" in (out / "index.html").read_text()


def test_default_config_builds_root_relative_links(tmp_path, monkeypatch):
    from newsbot.config import load_settings

    monkeypatch.delenv("NEWSBOT_BASE_URL", raising=False)
    settings = load_settings()
    assert settings.base_url == ""
    out = build_site(settings, [_article("first")], tmp_path / "site")
    index = (out / "index.html").read_text()
    assert 'href="/static/style.css"' in index and "/AI-News/" not in index
