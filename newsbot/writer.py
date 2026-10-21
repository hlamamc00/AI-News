"""Turn a Story into an Article.

Two writers are available:

* ``ClaudeWriter``   - calls the Claude API and asks for an original article as
                       structured JSON. Used when ``ANTHROPIC_API_KEY`` is set.
* ``TemplateWriter`` - no LLM: stitches the attributed source summaries into a
                       readable, clearly labelled digest. Always available, and
                       the fallback whenever the API call fails for a story.
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
from .textutil import first_sentence, jaccard, sentences, slugify, strip_html, tokens, truncate

log = logging.getLogger(__name__)

_MD_TAG_RE = re.compile(r"<[^>]+>")


class WriterError(RuntimeError):
    """The writer could not produce an article for this story."""


class WriterRefused(WriterError):
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
        "region": {"type": "string", "enum": REGIONS},
        "category": {"type": "string", "enum": CATEGORIES},
        "tags": {"type": "array", "items": {"type": "string"}, "description": "3 to 6 short lowercase topics."},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    },
    "required": ["headline", "standfirst", "body_markdown", "key_points", "region", "category", "tags", "confidence"],
    "additionalProperties": False,
}


SYSTEM_PROMPT = """You are the lead writer for {site_title}, an automated international news website.

For each request you receive several source reports about a single news story, gathered from the RSS feeds and article pages of established news organisations. You write one original, publishable news article from them.

Rules
1. Facts only from the sources. Never invent names, numbers, quotes, dates or events. If the sources conflict, say so and attribute each version. If something is unconfirmed, say it is unconfirmed.
2. Original prose. Rephrase everything in your own words; do not copy sentences from the sources. A short direct quote (under 15 words) is allowed only when a source clearly presents it as a quotation, and it must be attributed.
3. Attribute where it matters, naming the outlets exactly as given ("according to Al Jazeera", "the BBC reported", "Yonhap said").
4. Style: neutral, clear international English in the inverted-pyramid form. The first paragraph answers who, what, where and when. Add the context a reader outside the region would need, spell out acronyms once, use metric units and write dates as "21 October 2026". No editorialising, no hype, no rhetorical questions, no em dashes.
5. Length: 350 to 650 words of body in 4 to 8 paragraphs. Optional "## " subheadings for longer pieces. Markdown only: paragraphs, "## " headings and the occasional bold term. No links, no HTML, no bullet lists inside the body.
6. Fields: headline under 90 characters, specific and in sentence case, no clickbait. standfirst: one or two sentences under 220 characters. key_points: 3 to 5 one-sentence facts. tags: 3 to 6 short lowercase topics (people, places, organisations, themes). region and category: the best fit from the allowed lists. confidence: "high" when several independent sources agree, "medium" for a single reliable source or minor inconsistencies, "low" when the material is thin or contradictory.
7. Do not mention that you are an AI, that this is a summary, or how the article was produced.

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


def _story_image(story: Story) -> dict[str, str] | None:
    for item in story.ordered_items(10):
        if item.image:
            return {"url": item.image, "credit": item.source}
    return None


def make_article(story: Story, data: dict[str, Any], generated_by: str, model: str | None = None) -> Article:
    """Validate writer output and assemble the Article record."""
    headline = truncate(strip_html(str(data.get("headline") or "")).strip(), 120) or story.lead.title
    body = _MD_TAG_RE.sub("", str(data.get("body_markdown") or "")).strip()
    if len(body.split()) < 60:
        raise WriterError("article body too short")
    standfirst = truncate(strip_html(str(data.get("standfirst") or "")), 300) or first_sentence(body)
    key_points = _clean_list(data.get("key_points"), 5)
    tags = _clean_list(data.get("tags"), 6, lower=True)
    published = story.newest if story.newest <= datetime.now(timezone.utc) else datetime.now(timezone.utc)
    return Article(
        slug=slugify(headline),
        headline=headline,
        standfirst=standfirst,
        body_markdown=body,
        key_points=key_points,
        region=str(data.get("region") or story.region),
        category=str(data.get("category") or story.category),
        tags=tags,
        confidence=str(data.get("confidence") or "medium"),
        published_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        sources=[i.to_source_ref() for i in story.ordered_items(12)],
        image=_story_image(story),
        generated_by=generated_by,
        model=model,
    )


class TemplateWriter:
    """Deterministic, attribution-heavy digest used when no LLM is available."""

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
        names = story.sources
        if len(names) > 1:
            listed = ", ".join(names[:-1]) + f" and {names[-1]}"
            paragraphs.append(
                f"This digest was assembled automatically from reporting by {listed}. "
                "Follow the source links below for the full coverage."
            )
        else:
            paragraphs.append(
                f"This digest was assembled automatically from reporting by {names[0]}. "
                "Follow the source link below for the full coverage."
            )
        body = "\n\n".join(paragraphs)
        key_points: list[str] = []
        for item in items[:6]:
            sent = first_sentence(item.summary or item.text, 200)
            if not sent or any(jaccard(tokens(sent), tokens(k)) >= 0.5 for k in key_points):
                continue  # the same fact phrased by another outlet
            key_points.append(sent)
            if len(key_points) == 5:
                break
        counts: Counter[str] = Counter()
        for item in story.items:
            counts.update(tok for tok in tokens(item.title) if not tok.isdigit())
        tags = [tok for tok, _ in counts.most_common(5)]
        n = len(names)
        data = {
            "headline": lead.title,
            "standfirst": first_sentence(lead_text, 220) or lead.title,
            "body_markdown": body,
            "key_points": key_points or [lead.title],
            "region": story.region,
            "category": story.category,
            "tags": tags,
            "confidence": "high" if n >= 3 else "medium" if n == 2 else "low",
        }
        # The digest body can legitimately be short when feeds only carry a
        # one-line blurb; relax the minimum rather than fail.
        try:
            return make_article(story, data, generated_by=self.name)
        except WriterError:
            data["body_markdown"] = body + "\n\n" + "\n\n".join(
                f"{i.source}: {i.title}." for i in items
            )
            return make_article(story, data, generated_by=self.name)


class ClaudeWriter:
    """Writes original articles with the Claude API (structured JSON output)."""

    name = "claude"

    def __init__(self, settings: Settings) -> None:
        import anthropic  # lazy: the template writer must work without the SDK configured

        self._anthropic = anthropic
        self.settings = settings
        self.client = anthropic.Anthropic()  # credentials resolved from the environment
        self.model = settings.writer_model
        self.system_prompt = SYSTEM_PROMPT.format(site_title=settings.site_title)

    def request_kwargs(self, story: Story) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.settings.writer_max_tokens,
            # Stable prefix first so repeated calls in one run hit the prompt cache.
            "system": [{"type": "text", "text": self.system_prompt, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": build_user_prompt(story, self.settings)}],
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

    def write(self, story: Story) -> Article:
        response = self.client.beta.messages.create(**self.request_kwargs(story))
        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            raise WriterRefused(f"model declined ({getattr(details, 'category', None)})")
        if response.stop_reason == "max_tokens":
            raise WriterError("response truncated at max_tokens")
        text = next((block.text for block in response.content if block.type == "text"), "")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise WriterError(f"invalid JSON from model: {exc}") from exc
        usage = getattr(response, "usage", None)
        if usage is not None:
            log.debug(
                "claude usage: in=%s cached=%s out=%s",
                getattr(usage, "input_tokens", "?"),
                getattr(usage, "cache_read_input_tokens", "?"),
                getattr(usage, "output_tokens", "?"),
            )
        return make_article(story, data, generated_by=self.name, model=response.model)


class Newsroom:
    """Chooses a writer per story and degrades gracefully when the API misbehaves."""

    def __init__(self, settings: Settings, mode: str | None = None) -> None:
        self.settings = settings
        self.mode = mode or settings.writer_mode
        self.template = TemplateWriter(settings)
        self.claude: ClaudeWriter | None = None
        self._claude_disabled_reason: str | None = None
        self._consecutive_failures = 0
        self._lock = threading.Lock()
        has_key = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
        if self.mode == "template":
            log.info("writer: template (LLM disabled by configuration)")
        elif self.mode == "claude" or has_key:
            try:
                self.claude = ClaudeWriter(settings)
                log.info("writer: claude (%s, effort=%s)", settings.writer_model, settings.writer_effort)
            except Exception as exc:  # noqa: BLE001
                if self.mode == "claude":
                    raise
                log.warning("Claude writer unavailable (%s); using template writer", exc)
        else:
            log.info("writer: template (set ANTHROPIC_API_KEY to enable the Claude writer)")

    @property
    def active(self) -> str:
        return "claude" if self.claude and not self._claude_disabled_reason else "template"

    def _disable_claude(self, reason: str) -> None:
        with self._lock:
            if not self._claude_disabled_reason:
                self._claude_disabled_reason = reason
                log.error("Claude writer disabled for the rest of this run: %s", reason)

    def write(self, story: Story) -> Article:
        if self.claude and not self._claude_disabled_reason:
            anthropic = self.claude._anthropic
            try:
                article = self.claude.write(story)
                with self._lock:
                    self._consecutive_failures = 0
                return article
            except anthropic.AuthenticationError as exc:
                self._disable_claude(f"authentication failed: {exc.message}")
            except anthropic.PermissionDeniedError as exc:
                self._disable_claude(f"permission denied: {exc.message}")
            except anthropic.NotFoundError as exc:
                self._disable_claude(f"model or endpoint not found: {exc.message}")
            except anthropic.BadRequestError as exc:
                log.warning("bad request for %r: %s", story.lead.title, exc.message)
                self._note_failure("repeated bad requests")
            except anthropic.RateLimitError as exc:
                log.warning("rate limited on %r: %s", story.lead.title, exc.message)
                self._note_failure("persistent rate limiting")
            except anthropic.APIStatusError as exc:
                log.warning("API error %s on %r: %s", exc.status_code, story.lead.title, exc.message)
                self._note_failure(f"repeated API errors ({exc.status_code})")
            except anthropic.APIConnectionError as exc:
                log.warning("connection error on %r: %s", story.lead.title, exc)
                self._note_failure("connection errors")
            except WriterRefused as exc:
                log.warning("model declined %r: %s", story.lead.title, exc)
            except WriterError as exc:
                log.warning("writer error on %r: %s", story.lead.title, exc)
            if self.mode == "claude":
                raise WriterError(f"Claude writer failed for {story.lead.title!r}")
            log.info("falling back to the template writer for %r", story.lead.title)
        return self.template.write(story)

    def _note_failure(self, reason: str) -> None:
        with self._lock:
            self._consecutive_failures += 1
            if self._consecutive_failures >= 4:
                self._disable_claude(reason)
