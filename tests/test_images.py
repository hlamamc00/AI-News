import json

import urllib.error
from email.message import Message

import pytest

from newsbot import images
from newsbot.article import Article
from newsbot.config import Settings
from tests.test_build import _article


def _page(index, title, *, mime="image/jpeg", width=2400, height=1400, licence="CC BY-SA 4.0",
          description="", non_free="", restrictions="", thumb="https://upload.wikimedia.org/x/960px-a.jpg?utm_source=c"):
    meta = {
        "LicenseShortName": {"value": licence}, "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/4.0"},
        "Artist": {"value": '<a href="//commons.wikimedia.org/u">Jane <b>Doe</b></a>'},
        "ImageDescription": {"value": description}, "Restrictions": {"value": restrictions}, "NonFree": {"value": non_free},
    }
    return {"index": index, "title": title, "imageinfo": [{
        "mime": mime, "width": width, "height": height, "thumburl": thumb, "thumbwidth": 960, "thumbheight": 560,
        "descriptionurl": "https://commons.wikimedia.org/wiki/" + title, "extmetadata": meta}]}


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(images.time, "sleep", lambda s: None)


def test_pick_image_filters_and_credits():
    pages = [
        _page(1, "File:Dakar courthouse logo.png", mime="image/png"),                    # title skip
        _page(2, "File:Dakar courthouse.svg", mime="image/svg+xml"),                      # wrong type
        _page(3, "File:Dakar courthouse tall.jpg", width=900, height=1600),               # portrait
        _page(4, "File:Dakar courthouse nc.jpg", licence="CC BY-NC 4.0"),                 # not open
        _page(5, "File:Dakar courthouse nonfree.jpg", non_free="true"),
        _page(6, "File:Dakar courthouse restricted.jpg", restrictions="personality"),
        _page(7, "File:Unrelated waterfall.jpg", description="Near the Dakar courthouse"),  # only the description matches
        _page(8, "File:US envoy meets minister at Dakar courthouse.jpg"),                 # people and events are skipped
        _page(9, "File:Dakar courthouse steps.jpg", description="The courthouse in Dakar"),
    ]
    hit = images.pick_image("Dakar courthouse", pages, Settings({}))
    assert hit and hit["title"] == "Dakar courthouse steps"
    assert hit["author"] == "Jane Doe" and hit["license"] == "CC BY-SA 4.0"
    assert "?" not in hit["url"] and hit["source"] == "Wikimedia Commons"
    assert images.pick_image("Dakar courthouse", pages[:8], Settings({})) is None


def test_pick_image_avoids_images_already_used():
    pages = [_page(1, "File:Dakar courthouse a.jpg", thumb="https://u/a.jpg"), _page(2, "File:Dakar courthouse b.jpg", thumb="https://u/b.jpg")]
    hit = images.pick_image("Dakar courthouse", pages, Settings({}), exclude={"https://u/a.jpg"})
    assert hit["url"] == "https://u/b.jpg"


def test_license_allowlist():
    ok = ["CC0", "Public domain", "CC BY 4.0", "CC BY-SA 3.0", "CC-BY-SA-4.0", "PDM 1.0", "CC BY-SA 2.0 DE"]
    bad = ["CC BY-NC 4.0", "CC BY-ND 2.0", "All rights reserved", "", "GFDL only", "Fair use"]
    assert all(images._license_ok(x) for x in ok)
    assert not any(images._license_ok(x) for x in bad)


def test_attach_images_uses_query_and_never_repeats(monkeypatch):
    calls = []

    def fake_get(url, ua, timeout, accept="*/*"):
        calls.append(url)
        page = _page(1, "File:Parliament of Ghana.jpg", thumb="https://u/parliament.jpg", description="Parliament of Ghana")
        return json.dumps({"query": {"pages": {"1": page}}}).encode()

    monkeypatch.setattr(images, "http_get", fake_get)
    a, b, c = _article("a"), _article("b"), _article("c")
    a.image = b.image = c.image = None
    a.image_query = b.image_query = "Parliament of Ghana"
    n = images.attach_images([a, b, c], Settings({}))
    assert n == 1 and a.image["url"] == "https://u/parliament.jpg" and b.image is None and c.image is None
    assert len(calls) == 2 and "gsrsearch=Parliament+of+Ghana" in calls[0]


def test_attach_images_survives_network_errors_and_can_be_disabled(monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("offline")

    monkeypatch.setattr(images, "http_get", boom)
    a = _article("a"); a.image = None; a.image_query = "Anything"
    assert images.attach_images([a], Settings({})) == 0 and a.image is None
    assert images.attach_images([a], Settings({"images": {"enabled": False}})) == 0


def test_search_retries_after_429_and_uses_the_api_user_agent(monkeypatch):
    seen = []

    def fake_get(url, ua, timeout, accept="*/*"):
        seen.append(ua)
        if len(seen) == 1:
            hdrs = Message(); hdrs["Retry-After"] = "3"
            raise urllib.error.HTTPError(url, 429, "Too Many Requests", hdrs, None)
        return json.dumps({"query": {"pages": {"1": _page(1, "File:Dakar courthouse.jpg")}}}).encode()

    monkeypatch.setattr(images, "http_get", fake_get)
    s = Settings({"fetch": {"user_agent": "Mozilla/5.0 browser-style"}})
    assert images.find_commons_image("Dakar courthouse", s) is not None
    assert len(seen) == 2 and all(ua.startswith("AINewsDeskBot/1.0 (+https://") for ua in seen)
