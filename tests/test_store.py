from newsbot.store import State, load_articles, save_article
from tests.test_build import _article


def test_save_article_dedupes_slug_and_roundtrips(tmp_path):
    root = tmp_path / "articles"
    p1 = save_article(_article("same"), root)
    p2 = save_article(_article("same"), root)
    assert p1.name == "same.json" and p2.name == "same-2.json"
    loaded = load_articles(root)
    assert {a.slug for a in loaded} == {"same", "same-2"}
    assert loaded[0].headline.startswith("Headline")


def test_state_roundtrip_and_prune(tmp_path):
    path = tmp_path / "state.json"
    state = State(path)
    state.mark(["https://a", "https://b"])
    state.seen_urls["https://old"] = "2020-01-01T00:00:00+00:00"
    state.save()
    again = State.load(path)
    assert again.has("https://a") and not again.has("https://old")


def test_state_counts_rejections_and_forgets_them(tmp_path):
    path = tmp_path / "state.json"
    state = State(path)
    state.fail(["https://bad"])
    assert not state.failed("https://bad")
    state.fail(["https://bad"])
    assert state.failed("https://bad")
    state.save()
    again = State.load(path)
    assert again.failed("https://bad") and not again.failed("https://other")
    again._failure_stamps["https://bad"] = "2020-01-01T00:00:00+00:00"
    again.prune()
    assert not again.failed("https://bad")
