import json

from newsbot.cluster import cluster_items
from newsbot.config import Settings
from newsbot.writer import ARTICLE_SCHEMA, ClaudeWriter, TemplateWriter, build_user_prompt, make_article
from tests.test_cluster import make


def _story():
    items = [
        make("Court orders release of detained journalists in Dakar", "RFI", region="africa",
             summary="A court in Dakar ordered the release of three journalists on Tuesday. They had been held for a week. Lawyers welcomed the ruling.", country="France"),
        make("Senegal court frees three detained journalists", "Africanews", region="africa",
             summary="Three journalists detained in Senegal were released after a court ruling. Press groups had campaigned for them.", country="Pan-African"),
    ]
    return cluster_items(items, 0.45)[0]


def test_template_writer_produces_attributed_article():
    settings = Settings({})
    article = TemplateWriter(settings).write(_story())
    assert article.generated_by == "template"
    assert article.region == "africa"
    assert "RFI" in article.body_markdown and "Africanews" in article.body_markdown
    assert article.confidence == "medium"
    assert len(article.sources) == 2
    assert article.slug and article.path.startswith("/articles/")
    assert article.key_points


def test_make_article_validates_and_normalises():
    story = _story()
    data = {
        "headline": "<b>Senegal</b> frees journalists ",
        "standfirst": "Court ruling ends week-long detention.",
        "body_markdown": "word " * 80,
        "key_points": ["a", "a", "b"],
        "region": "africa",
        "category": "bogus",
        "tags": ["Press", "senegal", "press"],
        "confidence": "high",
    }
    a = make_article(story, data, generated_by="claude", model="m")
    assert a.headline == "Senegal frees journalists"
    assert a.category == "world"
    assert a.key_points == ["a", "b"]
    assert a.tags == ["press", "senegal"]
    assert a.model == "m"


def test_schema_matches_article_fields():
    required = set(ARTICLE_SCHEMA["required"])
    assert required == set(ARTICLE_SCHEMA["properties"])
    json.dumps(ARTICLE_SCHEMA)  # must be serialisable


def test_claude_request_shape(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    settings = Settings({"writer": {"model": "claude-opus-5-5", "effort": "medium", "max_tokens": 16000}})
    writer = ClaudeWriter(settings)
    kwargs = writer.request_kwargs(_story())
    assert kwargs["model"] == "claude-opus-5-5"
    assert kwargs["fallbacks"] == "default"
    assert kwargs["betas"] == ["server-side-fallback-2026-07-01"]
    assert kwargs["output_config"]["format"]["type"] == "json_schema"
    assert kwargs["output_config"]["effort"] == "medium"
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
    prompt = kwargs["messages"][0]["content"]
    assert "RFI" in prompt and "Africanews" in prompt and "SOURCES (2)" in prompt


def test_haiku_gets_no_fallbacks(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    writer = ClaudeWriter(Settings({"writer": {"model": "claude-haiku-5-5"}}))
    kwargs = writer.request_kwargs(_story())
    assert "fallbacks" not in kwargs and "betas" not in kwargs


def test_user_prompt_includes_full_text_when_extracted():
    story = _story()
    story.items[0].full_text = "Long extracted text " * 20
    prompt = build_user_prompt(story, Settings({}))
    assert "Article text (excerpt)" in prompt
