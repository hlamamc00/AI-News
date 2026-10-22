import json
from types import SimpleNamespace

import anthropic
import httpx2 as httpx
import pytest

from newsbot.cluster import cluster_items
from newsbot.config import Settings
from newsbot.textutil import verbatim_ratio
from newsbot.writer import (
    ARTICLE_SCHEMA,
    ClaudeWriter,
    Newsroom,
    NoWriterError,
    StoryRejected,
    TemplateWriter,
    WriterError,
    WriterRefused,
    build_user_prompt,
    make_article,
)
from tests.test_cluster import make

SOURCE_A = (
    "A court in Dakar ordered the release of three journalists on Tuesday after they had been held for a week "
    "without charge. Lawyers for the group welcomed the ruling and said the three would walk free by evening. "
    "Press freedom organisations had campaigned for their release since the arrests were first reported last week "
    "by local radio stations and several regional newspapers across the country."
)
SOURCE_B = (
    "Three journalists detained in Senegal were freed after a judge accepted a request from their defence team. "
    "Media groups across West Africa had demanded the release, arguing that the reporters were doing their jobs. "
    "The government has not commented on the decision and officials did not respond to requests from reporters."
)
PARAPHRASE = (
    "Senegal released three reporters on Tuesday once a judge in the capital accepted their lawyers' argument that "
    "the detention lacked a legal basis. The trio spent seven days in custody. Their attorneys said they expected "
    "the men and women to leave the building later that day. Regional press associations and rights monitors had "
    "pushed for the outcome in public statements for days, and local broadcasters were first to report the arrests. "
    "Officials have stayed silent so far. Colleagues gathered outside the courthouse and applauded when the decision "
    "was announced to the waiting crowd."
)


def _story():
    items = [
        make("Court orders release of detained journalists in Dakar", "RFI", region="africa", summary=SOURCE_A, country="France"),
        make("Senegal court frees three detained journalists", "Africanews", region="africa", summary=SOURCE_B, country="Pan-African"),
    ]
    return cluster_items(items, 0.45)[0]


def _data(body=PARAPHRASE, **over):
    data = {
        "headline": "Senegal court frees three detained journalists",
        "standfirst": "A judge ordered the release after a week in custody.",
        "body_markdown": body,
        "key_points": ["Three journalists were released.", "They were held for a week."],
        "differences": [],
        "image_query": "Dakar courthouse",
        "region": "africa",
        "category": "world",
        "tags": ["senegal", "press freedom"],
        "confidence": "high",
    }
    data.update(over)
    return data


def _reply(data, stop="end_turn"):
    return SimpleNamespace(
        stop_reason=stop, stop_details=None, model="claude-opus-5-5", usage=None,
        content=[SimpleNamespace(type="text", text=data if isinstance(data, str) else json.dumps(data))],
    )


class FakeMessages:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def _writer(monkeypatch, replies, **settings):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    writer = ClaudeWriter(Settings({"writer": settings}))
    writer.client = SimpleNamespace(beta=SimpleNamespace(messages=FakeMessages(replies)))
    return writer


def test_verbatim_ratio_separates_copying_from_paraphrase():
    assert verbatim_ratio(PARAPHRASE, [SOURCE_A, SOURCE_B]) < 0.05
    assert verbatim_ratio(SOURCE_A, [SOURCE_A, SOURCE_B]) > 0.9
    assert verbatim_ratio("too short", [SOURCE_A]) == 0.0


def test_template_writer_is_preview_only_and_attributed():
    article = TemplateWriter(Settings({})).write(_story())
    assert article.generated_by == "template"
    assert "RFI" in article.body_markdown and "Africanews" in article.body_markdown
    assert article.differences == [] and article.image is None


def test_make_article_validates_and_normalises():
    data = _data(
        headline="<b>Senegal</b> frees journalists ", body="word " * 80, key_points=["a", "a", "b"],
        category="bogus", tags=["Press", "senegal", "press"], image_query="  Dakar <i>courthouse</i> ",
    )
    a = make_article(_story(), data, generated_by="claude", model="m")
    assert a.headline == "Senegal frees journalists"
    assert a.category == "world" and a.key_points == ["a", "b"] and a.tags == ["press", "senegal"]
    assert a.image_query == "Dakar courthouse" and a.image is None and a.model == "m"
    with pytest.raises(StoryRejected):
        make_article(_story(), _data(body="far too short"), generated_by="claude")


def test_differences_keep_only_real_outlets_and_real_points():
    diffs = [
        {"outlets": ["RFI", "africanews"], "point": "RFI says the group was held for a week while Africanews gives no figure."},
        {"outlets": ["Made Up Daily"], "point": "An outlet that was never a source says something different here."},
        {"outlets": ["RFI"], "point": "too short"},
        "not a dict",
    ]
    a = make_article(_story(), _data(differences=diffs), generated_by="claude")
    assert a.differences == [{"outlets": ["RFI", "Africanews"], "point": diffs[0]["point"]}]
    # a single-source story can never have differences
    single = cluster_items([make("Lone story about a vote", "RFI", summary=SOURCE_A)], 0.45)[0]
    assert make_article(single, _data(differences=diffs), generated_by="claude").differences == []


def test_schema_fields_are_all_required_and_serialisable():
    assert set(ARTICLE_SCHEMA["required"]) == set(ARTICLE_SCHEMA["properties"])
    assert {"differences", "image_query"} <= set(ARTICLE_SCHEMA["properties"])
    json.dumps(ARTICLE_SCHEMA)


def test_claude_request_shape(monkeypatch):
    writer = _writer(monkeypatch, [], model="claude-opus-5-5", effort="medium", max_tokens=16000)
    kwargs = writer.request_kwargs(_story())
    assert kwargs["model"] == "claude-opus-5-5" and kwargs["fallbacks"] == "default"
    assert kwargs["betas"] == ["server-side-fallback-2026-07-01"]
    assert kwargs["output_config"]["format"]["type"] == "json_schema"
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "RFI" in kwargs["messages"][0]["content"] and "SOURCES (2)" in kwargs["messages"][0]["content"]
    haiku = _writer(monkeypatch, [], model="claude-haiku-5-5").request_kwargs(_story())
    assert "fallbacks" not in haiku and "betas" not in haiku


def test_user_prompt_includes_full_text_when_extracted():
    story = _story()
    story.items[0].full_text = "Long extracted text " * 20
    assert "Article text (excerpt)" in build_user_prompt(story, Settings({}))


def test_claude_accepts_an_original_draft(monkeypatch):
    writer = _writer(monkeypatch, [_reply(_data())])
    article = writer.write(_story())
    assert article.generated_by == "claude" and article.model == "claude-opus-5-5"
    assert len(writer.client.beta.messages.calls) == 1


def test_claude_retries_once_when_the_draft_copies_the_sources(monkeypatch):
    copied = _data(body=SOURCE_A + " " + SOURCE_B)
    writer = _writer(monkeypatch, [_reply(copied), _reply(_data())])
    article = writer.write(_story())
    calls = writer.client.beta.messages.calls
    assert len(calls) == 2 and "reused too much of the sources" in calls[1]["messages"][0]["content"]
    assert article.body_markdown == PARAPHRASE


def test_claude_gives_up_when_the_draft_still_copies(monkeypatch):
    copied = _data(body=SOURCE_A + " " + SOURCE_B)
    writer = _writer(monkeypatch, [_reply(copied), _reply(copied)])
    with pytest.raises(StoryRejected, match="too close"):
        writer.write(_story())


@pytest.mark.parametrize(
    "reply, exc",
    [
        (_reply("{}", stop="refusal"), WriterRefused),
        (_reply(_data(), stop="max_tokens"), StoryRejected),
        (_reply("not json"), StoryRejected),
        (_reply("[1, 2]"), StoryRejected),
    ],
)
def test_claude_rejects_unusable_responses(monkeypatch, reply, exc):
    with pytest.raises(exc):
        _writer(monkeypatch, [reply]).write(_story())


def test_missing_api_key_stops_the_run_instead_of_copying(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    for mode in ("auto", "claude"):
        with pytest.raises(NoWriterError, match="ANTHROPIC_API_KEY"):
            Newsroom(Settings({}), mode=mode)


def test_preview_mode_needs_no_key_and_is_flagged(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    room = Newsroom(Settings({}), mode="template")
    assert room.preview and room.write(_story()).generated_by == "template"


def test_service_errors_never_fall_back_to_template(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    room = Newsroom(Settings({}), mode="auto")
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    room.claude.client = SimpleNamespace(beta=SimpleNamespace(messages=FakeMessages(
        [anthropic.APIConnectionError(request=request)] * 6)))
    for _ in range(4):
        with pytest.raises(WriterError) as info:
            room.write(_story())
        assert not isinstance(info.value, StoryRejected)
    assert room.disabled  # four failures in a row switch the writer off for the run
    with pytest.raises(WriterError, match="disabled"):
        room.write(_story())


def test_story_rejections_pass_through_unchanged(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    room = Newsroom(Settings({}), mode="auto")
    room.claude.client = SimpleNamespace(beta=SimpleNamespace(messages=FakeMessages([_reply("{}", stop="refusal")])))
    with pytest.raises(WriterRefused):
        room.write(_story())
    assert room.disabled is None
