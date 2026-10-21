# AI News Desk

An automated, worldwide news site. A scheduled job pulls the public RSS/Atom feeds
of 177 news organisations on every continent, groups the headlines into stories,
reads the source articles, writes an original article for each story with the
Claude API (or a clearly labelled digest when no API key is configured), and
publishes a static site to GitHub Pages. Nobody edits it by hand.

```
feeds (177, all regions) ──► fetch ──► cluster into stories ──► rank + balance
                                                                     │
site/ (HTML, RSS, sitemap, search) ◄── build ◄── store JSON ◄── write (Claude / template)
```

* **Worldwide by design.** Every run guarantees stories from Africa, the Americas,
  Asia, Europe, the Middle East and Oceania when the feeds have them, and caps
  how much of a run any single topic (sport, culture, ...) can take.
* **Original writing, honest sourcing.** The Claude writer is told to use only
  facts that appear in the sources, to attribute them by outlet, and to say when
  sources disagree. Every article lists and links the reports it was built from
  and shows a confidence level.
* **Polite scraping.** Only syndication feeds are used for discovery. Full article
  pages are fetched once per story, honouring `robots.txt`, and are never
  republished. Thumbnails are the publishers' own RSS images, hot-linked and lazy
  loaded (switch them off with `build.show_images: false`).
* **Degrades gracefully.** No API key, a rate limit, or a refused request all fall
  back to the template digest, so the site keeps updating.

## Quick start (local)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Optional: enable the Claude writer. Without it, the template digest is used.
export ANTHROPIC_API_KEY=sk-ant-...

python -m newsbot run --limit 10      # fetch, write 10 articles, build site/
python -m http.server -d site 8000    # open http://localhost:8000
```

Useful commands:

| Command | What it does |
| --- | --- |
| `python -m newsbot run` | Full pipeline: fetch, cluster, write new articles, rebuild the site |
| `python -m newsbot run --dry-run` | Show which stories would be written, change nothing |
| `python -m newsbot run --writer template` | Force the no-LLM digest writer |
| `python -m newsbot run --no-extract` | Skip fetching full source pages (faster, less context) |
| `python -m newsbot build` | Rebuild `site/` from the stored articles only |
| `python -m newsbot sources --check` | Fetch every feed in the catalogue and report failures |

For local previews, set `NEWSBOT_BASE_URL=http://localhost:8000` before `build`
so links are not prefixed with the GitHub Pages project path.

## Deploy to GitHub Pages (fully automatic)

1. Merge this branch into `main`.
2. **Settings → Pages → Build and deployment → Source:** choose **GitHub Actions**.
3. **Settings → Secrets and variables → Actions → New repository secret:**
   `ANTHROPIC_API_KEY` (optional but recommended; without it articles are digests).
4. **Actions → Publish → Run workflow** to publish the first batch, or wait for the
   schedule (every three hours, see `.github/workflows/publish.yml`).

Each run commits the new article JSON files to `content/` and deploys the rebuilt
site. The workflow sets the site's base URL from Pages automatically. If your
default branch is protected, allow the `github-actions[bot]` user to push to it, or
the article commit step will fail (the deploy still runs from the artifact).

## Configuration

* `config/settings.yaml` – site title and tagline, fetch limits, extraction,
  how many articles per run, regional floor, topic cap, writer model and effort,
  build options. Environment overrides: `NEWSBOT_BASE_URL`, `NEWSBOT_WRITER`
  (`auto|claude|template`), `NEWSBOT_MAX_ARTICLES`, `ANTHROPIC_API_KEY`.
* `config/sources.yaml` – the feed catalogue. Each entry has a name, feed URL,
  default region, default category and country. Add or remove feeds freely; the
  writer re-classifies stories from their content, so the defaults are only hints.
  Allowed regions: `global, africa, americas, asia, europe, middle-east, oceania`.
  Allowed categories: `world, politics, business, technology, science, health,
  environment, sport, culture`.

### The writer

The Claude writer (`newsbot/writer.py`) sends the sources for one story and asks
for a JSON article validated against a schema (headline, standfirst, body,
key points, region, category, tags, confidence). It uses `claude-opus-5-5` with
`effort: medium` by default, enables prompt caching on the stable system prompt,
and opts into server-side fallback so a safety-declined request is retried on a
substitute model instead of failing. Change `writer.model` / `writer.effort` in
`settings.yaml` to trade cost against quality. A run of 24 articles costs roughly
one to three US dollars at the default settings (output and thinking tokens
dominate); switching `writer.model` to `claude-sonnet-5-5` roughly halves that.

### What it costs to run

Three knobs set the bill: the schedule (`publish.yml`, default four runs a day),
`articles.max_per_run` (default 24) and `writer.model`. At the defaults a run is
roughly one to three US dollars, so expect something like 5–10 dollars a day with
`claude-opus-5-5`, about half that with `claude-sonnet-5-5`, and a few cents with
`claude-haiku-5-5`. Lower `max_per_run`, run less often, or raise
`articles.dedupe_window_hours` to spend less. Without an API key the site costs
nothing to run beyond GitHub Actions minutes.

## Project layout

```
config/            settings.yaml, sources.yaml
newsbot/           the pipeline package
  fetch.py         concurrent feed fetching and normalisation
  cluster.py       story clustering, ranking, regional/topical balancing
  extract.py       polite full-text extraction (robots.txt, trafilatura)
  writer.py        Claude writer, template writer, graceful fallback
  store.py         article JSON files and the seen-URL state
  build.py         static site generator (Jinja2): pages, RSS, sitemap, search index
  templates/       HTML templates and static assets
content/           articles/YYYY/MM/DD/<slug>.json and state.json (committed)
site/              generated output (ignored by git, deployed by the workflow)
tests/             pytest suite (offline)
```

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

## Notes on responsible use

This site republishes nothing in full: articles are either machine-written from
the facts in several reports, or short attributed digests of the publishers' own
feed summaries. Each article links to every source it used. Machine-written text
can still contain errors, which is why every page carries a confidence level and
the About page explains how the site is produced. If you run this publicly, keep
that disclosure, keep the source links, and remove any feed whose publisher asks
you to.
