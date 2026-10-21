from datetime import datetime, timedelta, timezone

from newsbot.config import Settings, Source
from newsbot.fetch import parse_feed

RSS = """<?xml version="1.0"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
<channel><title>Test</title>
<item><title>Fresh story &amp; more</title><link>https://ex.com/a?utm_source=rss</link>
  <description><![CDATA[<p>First <b>para</b> of a story that is long enough to keep.</p>]]></description>
  <pubDate>{fresh}</pubDate>
  <media:thumbnail url="https://img.ex.com/small.jpg" width="100"/>
  <media:thumbnail url="https://img.ex.com/big.jpg" width="800"/>
</item>
<item><title>Stale story</title><link>https://ex.com/b</link><pubDate>{stale}</pubDate></item>
<item><title>No link</title><description>x</description></item>
</channel></rss>"""


def test_parse_feed_normalises_and_filters():
    now = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
    fmt = "%a, %d %b %Y %H:%M:%S +0000"
    data = RSS.format(fresh=(now - timedelta(hours=2)).strftime(fmt), stale=(now - timedelta(days=5)).strftime(fmt))
    settings = Settings({"fetch": {"max_age_hours": 36, "per_feed_limit": 10}})
    src = Source(name="Ex", url="https://ex.com/rss", region="europe", category="world", country="Exland")
    items = parse_feed(src, data.encode(), settings, now=now)
    assert [i.title for i in items] == ["Fresh story & more"]
    item = items[0]
    assert item.url == "https://ex.com/a"
    assert item.summary == "First para of a story that is long enough to keep."
    assert item.image == "https://img.ex.com/big.jpg"
    assert item.region == "europe" and item.source == "Ex"


def test_parse_feed_rejects_garbage():
    settings = Settings({})
    src = Source(name="Ex", url="https://ex.com/rss")
    try:
        parse_feed(src, b"<html><body>not a feed</body></html>", settings)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for non-feed content")
