"""Small text helpers shared by the pipeline: HTML stripping, slugs, tokens."""

from __future__ import annotations

import html
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_WORD_RE = re.compile(r"[a-z0-9][a-z0-9'’-]*")
_PUNCT_SPACE_RE = re.compile(r"\s+([.,;:!?%)\]])")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'“(])")

# Words that carry no story-identifying information. Includes the usual English
# stopwords plus newsroom boilerplate ("live", "update", "video").
STOPWORDS: frozenset[str] = frozenset(
    """
    a about above after again against all also am an and any are as at be because been
    before being below between both but by can could did do does doing down during each few
    for from further had has have having he her here hers herself him himself his how i if in
    into is it its itself just let me more most my myself no nor not now of off on once only
    or other our ours ourselves out over own same she should so some such than that the their
    theirs them themselves then there these they this those through to too under until up very
    was we were what when where which while who whom why will with would you your yours
    yourself yourselves
    says said say saying told tells tell new news live update updates latest breaking report
    reports reported reporting analysis opinion explained explainer watch video photos pictures
    picture gallery podcast review reviews exclusive briefing today tonight yesterday week
    weeks day days year years month months amid among via per still yet one two three first
    last next back big top best worst way ways thing things get gets got make makes made
    take takes took come comes came go goes went see sees saw know knows knew think thinks
    thought want wants wanted need needs needed like likes liked look looks looked use uses
    used find finds found give gives gave keep keeps kept set sets put puts may might must
    shall ought us
    january february march april june july august september october november december jan
    feb mar apr jun jul aug sept sep oct nov dec monday tuesday wednesday thursday friday
    saturday sunday
    """.split()
)


def strip_html(text: str | None) -> str:
    """Remove tags and entities, collapse whitespace."""
    if not text:
        return ""
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = text.replace("\xa0", " ")
    text = _WS_RE.sub(" ", text).strip()
    return _PUNCT_SPACE_RE.sub(r"\1", text)


def truncate(text: str, limit: int, suffix: str = "…") -> str:
    if len(text) <= limit:
        return text
    cut = text[: limit - len(suffix)]
    # Prefer breaking at a word boundary.
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:-") + suffix


_BYLINE_RE = re.compile(
    r"^(?:[Bb]y|BY|[Ff]rom|FROM)\s+[A-Z][\w.'’-]*(?:\s+(?:and\s+)?[A-Z][\w.'’-]*){0,4}\s*[-–—:,|]?\s+(?=[A-Z0-9\"'“])"
)
_BOILERPLATE_RE = re.compile(
    r"newsletter|subscribe|sign up|sign-up|read more|click here|follow us|continue reading|"
    r"appeared first on|all rights reserved|©|download the app|listen to|watch the video|"
    r"get the latest|breaking news alerts",
    re.IGNORECASE,
)
_TERMINAL_RE = re.compile(r"[.!?][\"'”’)\]]*$")


def clean_summary(text: str) -> str:
    """Drop leading bylines and promotional boilerplate from a feed summary."""
    text = strip_html(text)
    text = _BYLINE_RE.sub("", text)
    kept = [s for s in _split_sentences(text) if not _BOILERPLATE_RE.search(s)]
    return " ".join(kept).strip()


def _split_sentences(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    return [s.strip() for s in _SENTENCE_RE.split(text) if s.strip()]


def sentences(text: str, complete_only: bool = True) -> list[str]:
    """Split into sentences; by default drop a trailing fragment left by truncation."""
    parts = _split_sentences(text)
    if complete_only and len(parts) > 1 and not _TERMINAL_RE.search(parts[-1]):
        parts = parts[:-1]
    if complete_only and len(parts) > 1 and parts[-1].endswith("…"):
        parts = parts[:-1]
    return parts


def first_sentence(text: str, limit: int = 240) -> str:
    parts = sentences(text)
    if not parts:
        return ""
    return truncate(parts[0], limit)


def slugify(text: str, max_len: int = 70) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    if len(text) > max_len:
        text = text[:max_len].rsplit("-", 1)[0]
    return text or "story"


def tokens(text: str) -> set[str]:
    """Lower-cased, de-stopworded keyword set with crude plural stripping."""
    out: set[str] = set()
    for word in _WORD_RE.findall(text.lower()):
        word = word.replace("’", "'")
        if word.endswith("'s"):
            word = word[:-2]
        word = word.strip("'-")
        if len(word) < 3 and not word.isdigit():
            continue
        if word in STOPWORDS:
            continue
        if word.isdigit() and len(word) != 4:  # keep years, drop other numbers
            continue
        out.add(stem(word))
    return out


def stem(word: str) -> str:
    """Tiny rule-based stemmer: enough to match 'kills', 'killed' and 'killing'."""
    if word.isdigit() or len(word) <= 3:
        return word
    if word.endswith("ies") and len(word) > 4:
        word = word[:-3] + "y"
    elif word.endswith("es") and len(word) > 5:
        word = word[:-2]
    elif word.endswith("s") and not word.endswith("ss"):
        word = word[:-1]
    if word.endswith("ed") and len(word) > 5:
        word = word[:-2]
    elif word.endswith("ing") and len(word) > 6:
        word = word[:-3]
    return word


def overlap(a: set[str], b: set[str]) -> float:
    """Overlap coefficient: |a ∩ b| / min(|a|, |b|)."""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "utm_id",
    "fbclid", "gclid", "mc_cid", "mc_eid", "ref", "cmpid", "ns_mchannel", "ns_source",
    "ns_campaign", "ns_linkname", "ns_fee", "at_medium", "at_campaign", "ocid", "ito",
    "CMP", "cmp", "s", "sref", "share_type", "ftag", "ftcode",
}


def canonical_url(url: str) -> str:
    """Strip tracking parameters and fragments so the same page hashes the same."""
    url = (url or "").strip()
    if not url:
        return ""
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k not in _TRACKING_PARAMS]
    path = parts.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    return urlunsplit((parts.scheme.lower() or "https", parts.netloc.lower(), path, urlencode(query), ""))


_NOISE_RE = re.compile(
    r"\b(?:as it happened|live updates?|live blog|live reaction|in pictures|podcast|quiz|crossword|newsletter|"
    r"horoscopes?|cartoon|weather forecast|the briefing|morning mail|afternoon update|first edition|"
    r"today in focus|readers' letters|round-?up|news digest|daily digest|bulletin|today's headlines|"
    r"top headlines|all of africa today|what's on|tv guide|what to watch|this week in)\b",
    re.IGNORECASE,
)


def is_noise_title(title: str) -> bool:
    """Live blogs, podcasts, quizzes and newsletters are not usable source reports."""
    t = title.strip()
    if re.search(r"\s[-–—|]\s*live\s*$", t, re.IGNORECASE) or re.match(r"^live[:\s]", t, re.IGNORECASE):
        return True
    return bool(_NOISE_RE.search(t))


def clean_title(title: str) -> str:
    """Drop trailing ' - Source Name' / ' | Source' decorations some feeds add."""
    title = strip_html(title)
    title = re.sub(r"\s+[-|–—]\s+[A-Z][\w .&']{2,40}$", "", title)
    return title.strip()


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower().replace("’", "'"))


def verbatim_ratio(body: str, source_texts: list[str], n: int = 8) -> float:
    """Share of the body's n-word phrases that appear word for word in any source.

    Paraphrase scores near zero; copied sentences score high. A few short quotes
    barely move it.
    """
    words = _words(body)
    if len(words) < n:
        return 0.0
    grams = {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}
    source_grams: set[tuple[str, ...]] = set()
    for text in source_texts:
        sw = _words(text)
        source_grams.update(tuple(sw[i : i + n]) for i in range(len(sw) - n + 1))
    return len(grams & source_grams) / len(grams)
