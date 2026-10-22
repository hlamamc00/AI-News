"""Turn a Story into an Article.

* ``ClaudeWriter``   - calls the Claude API and asks for an original article as
                       structured JSON, then checks it does not copy the sources.
                       This is the only writer used for anything that is published.
* ``TemplateWriter`` - local PREVIEW only. It quotes the publishers' own feed
                       summaries so the layout can be seen without an API key. Its
                       output is stored under content/preview/ and never deployed.
* ``Newsroom``       - picks the writer. A story the writer cannot produce is
                       skipped; the site never falls back to copying text.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from .article import Article
from .cluster import Story
from .config import Settings
from .fetch import Item
from .taxonomy import CATEGORIES, REGIONS
from .textutil import (
    first_sentence,
    jaccard,
    sentences,
    slugify,
    strip_html,
    tokens,
    truncate,
    verbatim_ratio,
)

log = logging.getLogger(__name__)

_MD_TAG_RE = re.compile(r"<[^>]+>")


class WriterError(RuntimeError):
    """The writer could not produce an article (service problem or bad output)."""


class NoWriterError(WriterError):
    """No usable writer is configured (for example ANTHROPIC_API_KEY is missing)."""


class StoryRejected(WriterError):
    """This particular story cannot be written (refusal, copying, unusable output).

    Retrying the same story is unlikely to help, so the pipeline counts these.
    """


class WriterRefused(StoryRejected):
    """The model declined the request (stop_reason == "refusal")."""


ARTICLE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "headline": {"type": "string", "description": "Specific, sentence-case headline under 90 characters."},
        "standfirst": {"type": "string", "description": "One or two sentences expanding the headline, under 220 characters."},
        "body_markdown": {
            "type": "string",
            "description": "The article body, 350-650 words, in Markdown paragraphs with optional '## ' subheadings.",
        },
        "key_points": {"type": "array", "items": {"type": "string"}, "description": "3 to 5 one-sentence facts."},
        "differences": {
            "type": "array",
            "description": "Real differences between the reports. Empty when they agree or there is one source.",
            "items": {
                "type": "object",
                "properties": {
                    "outlets": {"type": "array", "items": {"type": "string"}, "description": "Outlet names exactly as given."},
                    "point": {"type": "string", "description": "One neutral sentence describing the difference."},
                },
                "required": ["outlets", "point"],
                "additionalProperties": False,
            },
        },
        "image_query": {
            "type": "string",
            "description": "2-5 word search phrase for a neutral illustrative photo of a place, building, institution or object. Empty if none.",
        },
        "region": {"type": "string", "enum": REGIONS},
        "category": {"type": "string", "enum": CATEGORIES},
        "tags": {"type": "array", "items": {"type": "string"}, "description": "3 to 6 short lowercase topics."},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    },
    "required": [
        "headline", "standfirst", "body_markdown", "key_points", "differences", "image_query",
        "region", "category", "tags", "confidence",
    ],
    "additionalProperties": False,
}


SYSTEM_PROMPT = """You are the lead writer for {site_title}, an automated international news website.

For each request you receive several source reports about a single news story, gathered from the RSS feeds and article pages of established news organisations. You write one original, publishable news article from them.

Rules
1. Facts only from the sources. Never invent names, numbers, quotes, dates or events. If the sources conflict, say so and attribute each version. If something is unconfirmed, say it is unconfirmed.
2. Original prose. Rephrase everything in your own words and restructure it; do not reuse sentences or long phrases from the sources. A short direct quote (under 15 words) is allowed only when a source clearly presents it as a quotation, and it must be attributed. Drafts that echo the sources' wording are rejected.
3. Attribute where it matters, naming the outlets exactly as given ("according to Al Jazeera", "the BBC reported", "Yonhap said").
4. Style: neutral, clear international English in the inverted-pyramid form. The first paragraph answers who, what, where and when. Add the context a reader outside the region would need, spell out acronyms once, use metric units and write dates as "21 October 2026". No editorialising, no hype, no rhetorical questions, no em dashes.
5. Length: 350 to 650 words of body in 4 to 8 paragraphs. Optional "## " subheadings for longer pieces. Markdown only: paragraphs, "## " headings and the occasional bold term. No links, no HTML, no bullet lists inside the body.
6. Fields: headline under 90 characters, specific and in sentence case, no clickbait. standfirst: one or two sentences under 220 characters. key_points: 3 to 5 one-sentence facts. tags: 3 to 6 short lowercase topics (people, places, organisations, themes). region and category: the best fit from the allowed lists. confidence: "high" when several independent sources agree, "medium" for a single reliable source or minor inconsistencies, "low" when the material is thin or contradictory.
7. differences: list only differences that are actually present in the reports: conflicting figures, claims attributed to different parties, a fact one report gives and another contradicts, or clearly different emphasis. Each entry names the outlets involved exactly as given and states the difference in one neutral sentence, for example "The BBC and Al Jazeera put the toll at 153, while Reuters reports at least 100." Never infer bias from an outlet's reputation or country. Use an empty list when the reports agree or there is only one source.
8. image_query: a 2 to 5 word phrase for a neutral illustrative photograph of a place, building, institution, object or subject area linked to the story, such as "Sydney Metro train" or "Parliament of Ghana". Never a named person and never a specific event. Use an empty string if nothing suitable exists.
9. Do not mention that you are an AI, that this is a summary, or how the article was produced.

Respond with JSON matching the required schema and nothing else."""


def _render_source(index: int, item: Item, max_chars: int) -> str:
    lines = [
        f"[{index}] {item.source}" + (f" ({item.country})" if item.country else "")
        + f" - published {item.published:%Y-%m-%d %H:%M} UTC",
        f"Headline: {item.title}",
        f"URL: {item.url}",
    ]
    if item.summary:
        lines.append(f"Summary: {item.summary}")
    if item.full_text:
        lines.append(f"Article text (excerpt): {truncate(item.full_text, max_chars)}")
    return "\n".join(lines)


def build_user_prompt(story: Story, settings: Settings, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    items = story.ordered_items(settings.writer_max_sources)
    parts = [
        f"Current date and time: {now:%A %d %B %Y, %H:%M} UTC",
        f"Allowed regions: {', '.join(REGIONS)}",
        f"Allowed categories: {', '.join(CATEGORIES)}",
        f"Feed defaults for this story (override if the content says otherwise): region={story.region}, category={story.category}",
        "",
        f"SOURCES ({len(items)}):",
        "",
    ]
    for i, item in enumerate(items, start=1):
        parts.append(_render_source(i, item, settings.extract_max_chars))
        parts.append("")
    parts.append("Write the article now.")
    return "\n".join(parts)


def _clean_list(values: Any, limit: int, lower: bool = False) -> list[str]:
    out: list[str] = []
    for value in values or []:
        text = strip_html(str(value)).strip(" .")
        if lower:
            text = text.lower()
        if text and text not in out:
            out.append(text)
        if len(out) >= limit:
            break
    return out


def _clean_differences(values: Any, outlet_names: list[str]) -> list[dict[str, Any]]:
    """Keep only differences that name real source outlets and say something."""
    if len(outlet_names) < 2:
        return []
    canonical = {name.lower(): name for name in outlet_names}
    out: list[dict[str, Any]] = []
    for entry in values or []:
        if not isinstance(entry, dict):
            continue
        point = truncate(strip_html(str(entry.get("point") or "")), 320)
        outlets = [canonical[o.lower().strip()] for o in entry.get("outlets") or [] if str(o).lower().strip() in canonical]
        if len(point) < 20 or not outlets:
            continue
        out.append({"outlets": list(dict.fromkeys(outlets)), "point": point})
        if len(out) == 4:
            break
    return out


def make_article(
    story: Story,
    data: dict[str, Any],
    generated_by: str,
    model: str | None = None,
    items: list[Item] | None = None,
) -> Article:
    """Validate writer output and assemble the Article record."""
    items = items or story.ordered_items(12)
    headline = truncate(strip_html(str(data.get("headline") or "")).strip(), 120) or story.lead.title
    body = _MD_TAG_RE.sub("", str(data.get("body_markdown") or "")).strip()
    if len(body.split()) < 60:
        raise StoryRejected("article body too short")
    standfirst = truncate(strip_html(str(data.get("standfirst") or "")), 300) or first_sentence(body)
    key_points = _clean_list(data.get("key_points"), 5)
    tags = _clean_list(data.get("tags"), 6, lower=True)
    image_query = truncate(strip_html(str(data.get("image_query") or "")), 80, suffix="").strip()
    outlet_names = list(dict.fromkeys(i.source for i in items))
    return Article(
        slug=slugify(headline),
        headline=headline,
        standfirst=standfirst,
        body_markdown=body,
        key_points=key_points,
        differences=_clean_differences(data.get("differences"), outlet_names),
        region=str(data.get("region") or story.region),
        category=str(data.get("category") or story.category),
        tags=tags,
        confidence=str(data.get("confidence") or "medium"),
        published_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        sources=[i.to_source_ref() for i in items],
        image=None,
        image_query=image_query,
        generated_by=generated_by,
        model=model,
    )


class TemplateWriter:
    """Local preview only: quotes the feeds' own summaries. Never published."""

    name = "template"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def write(self, story: Story) -> Article:
        items = story.ordered_items(self.settings.writer_max_sources)
        lead = items[0]
        lead_text = lead.summary or lead.text
        lead_sents = sentences(lead_text)[:3]
        paragraphs: list[str] = []
        if lead_sents:
            paragraphs.append(f"{' '.join(lead_sents)} ({lead.source})")
        else:
            paragraphs.append(f"{lead.source} is reporting: {lead.title}.")
        for other in items[1:5]:
            sents = sentences(other.summary or other.text)[:2]
            if not sents:
                continue
            paragraphs.append(f"**{other.source}** adds: {' '.join(sents)}")
        paragraphs.append("Preview digest assembled from the publishers' own summaries. It is never published.")
        body = "\n\n".join(paragraphs)
        key_points: list[str] = []
        for item in items[:6]:
            sent = first_sentence(item.summary or item.text, 200)
            if not sent or any(jaccard(tokens(sent), tokens(k)) >= 0.5 for k in key_points):
                continue
            key_points.append(sent)
            if len(key_points) == 5:
                break
        counts: Counter[str] = Counter()
        for item in story.items:
            counts.update(tok for tok in tokens(item.title) if not tok.isdigit())
        n = len(story.sources)
        data = {
            "headline": lead.title,
            "standfirst": first_sentence(lead_text, 220) or lead.title,
            "body_markdown": body,
            "key_points": key_points or [lead.title],
            "differences": [],
            "image_query": "",
            "region": story.region,
            "category": story.category,
            "tags": [tok for tok, _ in counts.most_common(5)],
            "confidence": "high" if n >= 3 else "medium" if n == 2 else "low",
        }
        try:
            return make_article(story, data, generated_by=self.name, items=items)
        except StoryRejected:
            data["body_markdown"] = body + "\n\n" + "\n\n".join(f"{i.source}: {i.title}." for i in items)
            return make_article(story, data, generated_by=self.name, items=items)


class ClaudeWriter:
    """Writes original articles with the Claude API (structured JSON output)."""

    name = "claude"
    attempts = 2

    def __init__(self, settings: Settings) -> None:
        import anthropic  # lazy import so the CLI starts fast and preview mode needs no SDK setup

        self._anthropic = anthropic
        self.settings = settings
        self.client = anthropic.Anthropic()  # credentials resolved from the environment
        self.model = settings.writer_model
        self.system_prompt = SYSTEM_PROMPT.format(site_title=settings.site_title)

    def request_kwargs(self, story: Story, note: str = "") -> dict[str, Any]:
        prompt = build_user_prompt(story, self.settings)
        if note:
            prompt = f"{prompt}\n\n{note}"
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.settings.writer_max_tokens,
            # Stable prefix first so repeated calls in one run hit the prompt cache.
            "system": [{"type": "text", "text": self.system_prompt, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": prompt}],
            "output_config": {
                "effort": self.settings.writer_effort,
                "format": {"type": "json_schema", "schema": ARTICLE_SCHEMA},
            },
        }
        # Server-side fallback re-runs a safety-declined request on a substitute
        # model. Haiku has no fallback support, so the parameter is omitted there.
        if not self.model.startswith("claude-haiku"):
            kwargs["betas"] = ["server-side-fallback-2026-07-01"]
            kwargs["fallbacks"] = "default"
        return kwargs

    def _call(self, story: Story, note: str = "") -> tuple[dict[str, Any], str]:
        response = self.client.beta.messages.create(**self.request_kwargs(story, note))
        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            raise WriterRefused(f"model declined ({getattr(details, 'category', None)})")
        if response.stop_reason == "max_tokens":
            raise StoryRejected("response truncated at max_tokens")
        text = next((block.text for block in response.content if block.type == "text"), "")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise StoryRejected(f"invalid JSON from model: {exc}") from exc
        if not isinstance(data, dict):
            raise StoryRejected("model returned JSON that is not an object")
        usage = getattr(response, "usage", None)
        if usage is not None:
            log.debug(
                "claude usage: in=%s cached=%s out=%s",
                getattr(usage, "input_tokens", "?"),
                getattr(usage, "cache_read_input_tokens", "?"),
                getattr(usage, "output_tokens", "?"),
            )
        return data, getattr(response, "model", self.model)

    def write(self, story: Story) -> Article:
        items = story.ordered_items(self.settings.writer_max_sources)
        source_texts = [f"{i.title}. {i.summary} {i.full_text}" for i in items]
        limit = self.settings.max_verbatim_ratio
        note = ""
        ratio = 0.0
        for attempt in range(1, self.attempts + 1):
            data, model = self._call(story, note)
            ratio = verbatim_ratio(str(data.get("body_markdown") or ""), source_texts)
            if ratio <= limit:
                return make_article(story, data, generated_by=self.name, model=model, items=items)
            log.warning("draft for %r copies the sources (%.0f%% shared phrases), attempt %d", story.lead.title, ratio * 100, attempt)
            note = (
                f"Your previous draft reused too much of the sources' wording ({ratio:.0%} of its eight-word phrases "
                "appear verbatim in them). Write the whole article again from scratch, in your own sentences and structure."
            )
        raise StoryRejected(f"draft too close to the sources ({ratio:.0%} shared phrases)")


class Newsroom:
    """Owns the writer for a run. Never falls back to copying publisher text."""

    def __init__(self, settings: Settings, mode: str | None = None) -> None:
        self.settings = settings
        self.mode = mode or settings.writer_mode
        self.preview = self.mode == "template"
        self.claude: ClaudeWriter | None = None
        self.template: TemplateWriter | None = None
        self._disabled_reason: str | None = None
        self._consecutive_failures = 0
        # Reentrant: _note_failure holds the lock while it calls _disable.
        self._lock = threading.RLock()
        if self.preview:
            self.template = TemplateWriter(settings)
            log.warning("writer: PREVIEW template mode. Output goes to content/preview/ and is never published.")
            return
        has_key = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
        if not has_key:
            raise NoWriterError(
                "ANTHROPIC_API_KEY is not set, so no articles can be written. Set it (locally: an environment "
                "variable; on GitHub: Settings > Secrets and variables > Actions), or run with --writer template "
                "for a local layout preview that is never published."
            )
        self.claude = ClaudeWriter(settings)
        log.info("writer: claude (%s, effort=%s)", settings.writer_model, settings.writer_effort)

    @property
    def disabled(self) -> str | None:
        return self._disabled_reason

    def _disable(self, reason: str) -> None:
        with self._lock:
            if not self._disabled_reason:
                self._disabled_reason = reason
                log.error("Claude writer disabled for the rest of this run: %s", reason)

    def _note_failure(self, reason: str) -> None:
        with self._lock:
            self._consecutive_failures += 1
            if self._consecutive_failures >= 4:
                self._disable(reason)

    def write(self, story: Story) -> Article:
        if self.template is not None:
            return self.template.write(story)
        assert self.claude is not None
        if self._disabled_reason:
            raise WriterError(f"writer disabled: {self._disabled_reason}")
        anthropic = self.claude._anthropic
        try:
            article = self.claude.write(story)
        except StoryRejected:
            raise
        except anthropic.AuthenticationError as exc:
            self._disable(f"authentication failed: {exc.message}")
            raise WriterError("authentication failed") from exc
        except anthropic.PermissionDeniedError as exc:
            self._disable(f"permission denied: {exc.message}")
            raise WriterError("permission denied") from exc
        except anthropic.NotFoundError as exc:
            self._disable(f"model or endpoint not found: {exc.message}")
            raise WriterError("model not found") from exc
        except anthropic.BadRequestError as exc:
            log.warning("bad request for %r: %s", story.lead.title, exc.message)
            self._note_failure("repeated bad requests")
            raise WriterError(f"bad request: {exc.message}") from exc
        except anthropic.RateLimitError as exc:
            log.warning("rate limited on %r: %s", story.lead.title, exc.message)
            self._note_failure("persistent rate limiting")
            raise WriterError("rate limited") from exc
        except anthropic.APIStatusError as exc:
            log.warning("API error %s on %r: %s", exc.status_code, story.lead.title, exc.message)
            self._note_failure(f"repeated API errors ({exc.status_code})")
            raise WriterError(f"API error {exc.status_code}") from exc
        except anthropic.APIConnectionError as exc:
            log.warning("connection error on %r: %s", story.lead.title, exc)
            self._note_failure("connection errors")
            raise WriterError("connection error") from exc
        with self._lock:
            self._consecutive_failures = 0
        return article
