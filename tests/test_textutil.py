from newsbot.textutil import canonical_url, clean_title, first_sentence, slugify, strip_html, tokens


def test_strip_html_and_entities():
    assert strip_html("<p>Hello &amp; <b>world</b></p>\n  twice") == "Hello & world twice"


def test_slugify():
    assert slugify("Élan: a 'test' headline!!") == "elan-a-test-headline"
    assert slugify("") == "story"
    assert len(slugify("word " * 40)) <= 70


def test_tokens_drop_stopwords_and_plurals():
    t = tokens("Scientists say new study finds 2026 floods hit cities")
    assert "scientist" in t and "flood" in t and "city" in t
    assert "say" not in t and "new" not in t
    assert "2026" in t


def test_canonical_url_strips_tracking():
    url = "https://Example.com/a/b/?utm_source=x&id=5&fbclid=zzz#frag"
    assert canonical_url(url) == "https://example.com/a/b?id=5"
    assert canonical_url("") == ""


def test_clean_title_removes_source_suffix():
    assert clean_title("Big news today - BBC News") == "Big news today"
    assert clean_title("Keep this - not a source because it is long and lower case") != "Keep this"


def test_stem_unifies_verb_forms():
    from newsbot.textutil import stem

    assert stem("kills") == stem("killed") == stem("killing") == "kill"
    assert stem("batters") == stem("battered")
    assert stem("news") == "new" and stem("2026") == "2026"


def test_first_sentence():
    assert first_sentence("One. Two! Three?") == "One."


def test_is_noise_title():
    from newsbot.textutil import is_noise_title

    assert is_noise_title("Bayern Munich v Arsenal: Champions League – live")
    assert is_noise_title("Live: Minister says threats against MPs are not new")
    assert is_noise_title("Morning Mail: MPs' protections under scrutiny")
    assert is_noise_title("Election night as it happened")
    assert not is_noise_title("Residents live in fear after floods")
    assert not is_noise_title("Olive harvest hit by drought")


def test_clean_summary_drops_bylines_and_boilerplate():
    from newsbot.textutil import clean_summary, sentences

    raw = "By Jane Doe The minister spoke on Tuesday. Sign up for our newsletter here. Talks continue."
    assert clean_summary(raw) == "The minister spoke on Tuesday. Talks continue."
    assert sentences("One is done. Two is cut off mid") == ["One is done."]
    assert sentences("Only fragment without end") == ["Only fragment without end"]
