"""Group feed items into stories, rank them, and pick a balanced set to write."""

from __future__ import annotations

import logging
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .config import Settings
from .fetch import Item
from .taxonomy import CATEGORIES, REGIONS, guess_category, region_scores
from .textutil import jaccard, overlap, tokens

log = logging.getLogger(__name__)


@dataclass
class Story:
    items: list[Item] = field(default_factory=list)
    title_tokens: set[str] = field(default_factory=set)
    all_tokens: set[str] = field(default_factory=set)
    score: float = 0.0

    def add(self, item: Item, t_tokens: set[str], a_tokens: set[str]) -> None:
        self.items.append(item)
        self.title_tokens |= t_tokens
        self.all_tokens |= a_tokens

    def _rank(self, item: Item) -> tuple:
        """Prefer an outlet from the story's own region, then richer text, then recency."""
        region = self.region
        local = 1 if item.region == region and region != "global" else 0
        return (local, min(len(item.text), 4000), item.published)

    @property
    def lead(self) -> Item:
        """The item the writer should treat as primary."""
        return max(self.items, key=self._rank)

    @property
    def newest(self) -> datetime:
        return max(i.published for i in self.items)

    @property
    def sources(self) -> list[str]:
        seen: list[str] = []
        for item in self.items:
            if item.source not in seen:
                seen.append(item.source)
        return seen

    @property
    def countries(self) -> set[str]:
        return {i.country for i in self.items if i.country}

    @property
    def text(self) -> str:
        return " ".join(f"{i.title}. {i.summary}" for i in self.items)

    @property
    def region(self) -> str:
        """Feed labels are a hint; place names in the text are stronger evidence."""
        total = len(self.items)
        votes = Counter(i.region for i in self.items if i.region != "global")
        top_vote, top_count = (votes.most_common(1)[0] if votes else ("global", 0))
        scores = region_scores(self.text)
        if scores:
            (kw_region, kw_hits), *rest = list(scores.items())
            runner_up = rest[0][1] if rest else 0
            if kw_hits >= 2 and kw_hits >= 2 * runner_up:
                return kw_region
        if top_count >= 0.5 * total:
            return top_vote
        if scores:
            return next(iter(scores))
        return top_vote if top_count >= 0.34 * total else "global"

    @property
    def category(self) -> str:
        """Majority of the feeds' own labels; keyword evidence only for thin stories."""
        votes = Counter(i.category for i in self.items)
        top, count = votes.most_common(1)[0]
        n = len(self.items)
        if top != "world" and count >= 0.5 * n:
            return top
        if top == "world":
            # Thin stories need little evidence; big ones have more text, so demand more hits.
            return guess_category(self.text, default="world", min_hits=3 if n <= 2 else max(6, n))
        return top if count >= 0.5 * n else "world"

    @property
    def keywords(self) -> set[str]:
        """Tokens shared by most member titles (or the lone title for single-item stories)."""
        if len(self.items) == 1:
            return tokens(self.items[0].title)
        counts = Counter()
        for item in self.items:
            counts.update(tokens(item.title))
        needed = max(2, math.ceil(len(self.items) / 2))
        shared = {tok for tok, n in counts.items() if n >= needed}
        return shared or set(tok for tok, _ in counts.most_common(8))

    def ordered_items(self, limit: int) -> list[Item]:
        """Distinct-source items, most informative first, capped at *limit*."""
        seen: set[str] = set()
        out: list[Item] = []
        for item in sorted(self.items, key=self._rank, reverse=True):
            if item.source in seen:
                continue
            seen.add(item.source)
            out.append(item)
            if len(out) >= limit:
                break
        return out


def _similarity(story: Story, t_tokens: set[str], a_tokens: set[str]) -> float:
    """Best single-link similarity between a candidate item and a story's members."""
    best = 0.0
    for member in story.items:
        mt = tokens(member.title)
        shared_title = sum(1 for tok in mt & t_tokens if not tok.isdigit())
        if shared_title < 2:
            continue
        ma = mt | tokens(member.summary)
        score = 0.65 * overlap(mt, t_tokens) + 0.35 * overlap(ma, a_tokens)
        if score > best:
            best = score
    return best


def cluster_items(items: list[Item], threshold: float) -> list[Story]:
    """Greedy single-link clustering over an inverted index of title tokens."""
    stories: list[Story] = []
    index: dict[str, set[int]] = defaultdict(set)
    for item in sorted(items, key=lambda i: i.published, reverse=True):
        t_tokens = tokens(item.title)
        a_tokens = t_tokens | tokens(item.summary)
        candidates: Counter[int] = Counter()
        for tok in t_tokens:
            if tok.isdigit():
                continue  # years and scores are shared by unrelated stories
            for idx in index.get(tok, ()):
                candidates[idx] += 1
        best_idx, best_score = -1, 0.0
        for idx, shared in candidates.items():
            if shared < 2:
                continue
            score = _similarity(stories[idx], t_tokens, a_tokens)
            if score > best_score:
                best_idx, best_score = idx, score
        if best_idx >= 0 and best_score >= threshold:
            stories[best_idx].add(item, t_tokens, a_tokens)
            idx = best_idx
        else:
            stories.append(Story())
            idx = len(stories) - 1
            stories[idx].add(item, t_tokens, a_tokens)
        for tok in t_tokens:
            index[tok].add(idx)
    log.info("clustered %d items into %d stories", len(items), len(stories))
    return stories


def score_story(story: Story, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    age_hours = max(0.0, (now - story.newest).total_seconds() / 3600)
    recency = 3.0 * math.exp(-age_hours / 12.0)
    n_sources = len(story.sources)
    n_countries = len(story.countries)
    has_text = 0.5 if len(story.lead.text) > 300 else 0.0
    return 3.0 * n_sources + 1.0 * n_countries + recency + has_text


def is_already_covered(story: Story, recent_keywords: list[set[str]], threshold: float) -> bool:
    kw = story.keywords
    if not kw:
        return False
    return any(jaccard(kw, prev) >= threshold or overlap(kw, prev) >= 0.8 for prev in recent_keywords)


def too_similar(story: Story, chosen: list[Story], df: Counter | None = None, rare_df: int = 3) -> bool:
    """Same event told from another angle: skip it so one run does not repeat itself.

    *df* is the number of candidate stories whose keywords contain each token. Two
    stories that share a rare token (a surname, a place) plus one more are the same
    event even when their headlines are worded very differently.
    """
    kw = story.keywords
    for other in chosen:
        okw = other.keywords
        shared = kw & okw
        if jaccard(kw, okw) >= 0.4 or (len(shared) >= 3 and overlap(kw, okw) >= 0.6):
            return True
        if df and len(shared) >= 2 and overlap(kw, okw) >= 0.3 and any(df[t] <= rare_df for t in shared):
            return True
        if jaccard(story.all_tokens, other.all_tokens) >= 0.3:
            return True
    return False


def select_stories(
    stories: list[Story],
    settings: Settings,
    recent_keywords: list[set[str]] | None = None,
    limit: int | None = None,
) -> list[Story]:
    """Rank stories and choose a regionally and topically balanced subset."""
    limit = limit or settings.max_per_run
    recent_keywords = recent_keywords or []
    now = datetime.now(timezone.utc)
    pool: list[Story] = []
    skipped = 0
    for story in stories:
        if not story.items[0].summary and len(story.items) == 1 and len(story.lead.text) < 80:
            continue  # bare headline with nothing to write from
        if is_already_covered(story, recent_keywords, settings.dedupe_threshold):
            skipped += 1
            continue
        story.score = score_story(story, now)
        pool.append(story)
    pool.sort(key=lambda s: s.score, reverse=True)
    if skipped:
        log.info("skipped %d stories already covered recently", skipped)

    chosen: list[Story] = []
    chosen_ids: set[int] = set()
    df: Counter[str] = Counter()
    for story in pool:
        df.update(story.keywords)
    rare_df = max(3, len(pool) // 300)
    # General news is uncapped; topical categories (sport, culture, ...) each get a share.
    category_cap = max(2, math.ceil(settings.max_category_share * limit))
    category_counts: Counter[str] = Counter()

    def take(story: Story) -> bool:
        if id(story) in chosen_ids or len(chosen) >= limit:
            return False
        cat = story.category
        if cat != "world" and category_counts[cat] >= category_cap:
            return False
        if too_similar(story, chosen, df, rare_df):
            return False
        chosen.append(story)
        chosen_ids.add(id(story))
        category_counts[cat] += 1
        return True

    # 1) regional floor: worldwide coverage comes first
    by_region: dict[str, list[Story]] = defaultdict(list)
    by_category: dict[str, list[Story]] = defaultdict(list)
    for story in pool:
        by_region[story.region].append(story)
        by_category[story.category].append(story)
    for region in REGIONS:
        taken = 0
        for story in by_region.get(region, []):
            if taken >= settings.per_region_min:
                break
            if take(story):
                taken += 1
    # 2) topical floor: a little business, science, sport ... every run
    for category in CATEGORIES:
        if category == "world":
            continue
        taken = sum(1 for s in chosen if s.category == category)
        for story in by_category.get(category, []):
            if taken >= settings.per_topic_min:
                break
            if take(story):
                taken += 1
    # 3) fill the rest by score
    for story in pool:
        if len(chosen) >= limit:
            break
        take(story)
    chosen.sort(key=lambda s: s.score, reverse=True)
    log.info("selected %d of %d candidate stories", len(chosen), len(pool))
    return chosen
