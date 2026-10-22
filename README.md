# AI News Desk

An automated, worldwide news site. A scheduled job pulls the public RSS/Atom feeds
of 177 feeds from news organisations on every continent, groups the headlines into
stories, reads the source articles, writes an original article for each story with the
Claude API, and publishes a static site, RSS feeds and a daily email briefing to GitHub
Pages. Nobody edits it by hand, and it says so.

```
feeds (177, all regions) ──► fetch ──► cluster into stories ──► rank + balance
                                                                     │
site/ (HTML, RSS, sitemap, search) ◄── build ◄── store JSON ◄── write (Claude / template)
```

* **Worldwide by design.** Every run guarantees stories from Africa, the Americas,
  Asia, Europe, the Middle East and Oceania when the feeds have them, and caps how
  much of a run any single topic (sport, culture, ...) can take.
* **Original writing, honest sourcing.** The writer is told to use only facts that
  appear in the sources, to attribute them by outlet, and to say when sources
  disagree. Every draft is checked for copied wording (more than a tenth of its
  eight-word phrases appearing verbatim in the sources is rejected, with one
  rewrite attempt). A story that cannot be written safely is skipped. **The site
  never falls back to publishing the publishers' text.**
* **Where the reports differ.** Each article lists real differences between outlets,
  such as conflicting figures, and only names outlets that were actually sources.
* **Openly licensed images only.** Illustrations come from Wikimedia Commons (CC0,
  public domain, CC BY, CC BY-SA), are matched on the file title, skip people and
  event photos, are captioned as illustrative, and are credited on the article and
  on `/credits/`. Publisher photos are never used.
* **Polite scraping.** Feeds are used for discovery. Full article pages are fetched
  once per story, honouring `robots.txt`, and are never republished.
* **Feeds and a newsletter.** RSS for the whole site, every region and every topic,
  a daily briefing page and feed, and an email signup form (see below).

## Quick start (local)

The pipeline lives in this repository, so run every command from inside the
cloned folder. Python 3.12 or 3.13 is recommended.

```bash
git clone https://github.com/hlamamc00/AI-News.git
cd AI-News
git checkout claude/intelligent-archimedes-ily833   # skip once merged to main
```

**macOS / Linux**

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...   # real articles need a key
python -m newsbot run --limit 10      # fetch, write 10 articles, build site/
python -m http.server -d site 8000    # open http://localhost:8000
```

**Windows (PowerShell)**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:ANTHROPIC_API_KEY = "sk-ant-..."   # real articles need a key; this window only
python -m newsbot run --limit 10        # fetch, write 10 articles, build site\
python -m http.server -d site 8000      # open http://localhost:8000
```

If PowerShell refuses to activate the virtual environment, run
`Set-ExecutionPolicy -Scope Process Bypass` first. `export`, `source` and `&&`
are bash syntax and do not work in Windows PowerShell 5.

**No API key? Preview the layout.** `python -m newsbot run --writer template --limit 10`
builds a local site from the publishers' own summaries so you can see the design.
That output is written to `content/preview/`, is git-ignored, and is never committed
or deployed. Without `--writer template`, a missing key stops the run with a clear
error, so the live site can never be filled with copied text.

Useful commands:

| Command | What it does |
| --- | --- |
| `python -m newsbot run` | Full pipeline: fetch, cluster, write new articles, rebuild the site |
| `python -m newsbot run --dry-run` | Show which stories would be written, change nothing |
| `python -m newsbot run --writer template` | Local layout preview from publisher summaries (never published) |
| `python -m newsbot run --no-extract` | Skip fetching full source pages (faster, less context) |
| `python -m newsbot build` | Rebuild `site/` from the stored articles (`--preview` adds local preview articles) |
| `python -m newsbot sources --check` | Fetch every feed in the catalogue and report failures |

Local builds use root-relative links. The publish workflow sets
`NEWSBOT_BASE_URL` to the GitHub Pages address so the RSS feed, sitemap and
canonical links are absolute when deployed.

## Deploy to GitHub Pages (fully automatic)

1. Merge this branch into `main`.
2. **Settings → Pages → Build and deployment → Source:** choose **GitHub Actions**.
3. **Settings → Secrets and variables → Actions → New repository secret:**
   `ANTHROPIC_API_KEY`. It is required: the workflow stops with a clear message
   without it, because articles are only ever written by Claude.
4. **Actions → Publish → Run workflow** to publish the first batch, or wait for the
   schedule (every three hours, see `.github/workflows/publish.yml`).

Each run commits the new article JSON files to `content/` and deploys the rebuilt
site. The workflow sets the site's base URL from Pages automatically. If your
default branch is protected, allow the `github-actions[bot]` user to push to it, or
the article commit step will fail (the deploy still runs from the artifact).

## RSS feeds

Every page advertises its feed. `/feeds/` lists them all: the whole site
(`/feed.xml`), each region (`/region/africa/feed.xml`), each topic
(`/topic/sport/feed.xml`) and the daily briefing (`/newsletter/feed.xml`). Items
carry the full article, the "where the reports differ" box, the source list and the
image credit, so feed readers show a complete, correctly attributed story.

## Newsletter

The site publishes a **daily briefing**: the top stories of the previous 24 hours,
then a short list per region, each linking to the article and its sources. An edition
is built from the stored articles at 06:00 UTC (`newsletter.edition_hour_utc`), and
only when at least six stories exist (`newsletter.min_articles`). Each edition is a
web page (`/newsletter/2026-10-22/`), a plain-text file (`index.txt`) and an item in
`/newsletter/feed.xml` with the email-ready HTML.

Sending email needs a provider, because lists, consent and unsubscribe links are
their job. One-time setup:

1. Create an account with an email provider that has a signup form and an
   "RSS to email" (RSS campaign) feature, for example Buttondown, Mailchimp, Brevo
   or MailerLite. Check their current plans, as RSS campaigns are a paid feature on
   some.
2. Point the provider's RSS campaign at `https://<your-site>/newsletter/feed.xml` and
   schedule it daily, shortly after 06:30 UTC.
3. Copy the provider's hosted signup form **action URL** into
   `newsletter.subscribe_url` in `config/settings.yaml`, or set the repository
   variable `NEWSBOT_SUBSCRIBE_URL` (Settings → Secrets and variables → Actions →
   Variables). Set `subscribe_email_field` if the provider's field is not `email`
   (Mailchimp uses `EMAIL`) and add any required hidden inputs under
   `subscribe_hidden_fields`.

The signup form appears on the home page, article pages and `/newsletter/` only when
the URL is set.

## Configuration

* `config/settings.yaml` – site title and tagline, fetch limits, extraction,
  how many articles per run, regional and topic floors, writer model, effort and copy
  threshold, images, newsletter, build options. Environment overrides: `NEWSBOT_BASE_URL`, `NEWSBOT_WRITER`
  (`auto|claude|template`), `NEWSBOT_MAX_ARTICLES`, `ANTHROPIC_API_KEY`.
* `config/sources.yaml` – the feed catalogue. Each entry has a name, feed URL,
  default region, default category and country. Add or remove feeds freely; the
  writer re-classifies stories from their content, so the defaults are only hints.
  Allowed regions: `global, africa, americas, asia, europe, middle-east, oceania`.
  Allowed categories: `world, politics, business, technology, science, health,
  environment, sport, culture`.

### The writer

The Claude writer (`newsbot/writer.py`) sends the sources for one story and asks
for a JSON article validated against a schema: headline, standfirst, body, key
points, differences between outlets, an image search phrase, region, category, tags
and confidence. It uses `claude-opus-5-5` with `effort: medium` by default, caches
the stable system prompt, and opts into server-side fallback so a safety-declined
request is retried on a substitute model. A draft that copies the sources is
retried once, then skipped. A story the writer rejects twice is not retried again.
Change `writer.model` / `writer.effort` in `settings.yaml` to trade cost against
quality.

### What it costs to run

Three knobs set the bill: the schedule (`publish.yml`, default four runs a day),
`articles.max_per_run` (default 24) and `writer.model`. At the defaults a run is
roughly one to three US dollars, so expect something like 5–10 dollars a day with
`claude-opus-5-5`, about half that with `claude-sonnet-5-5`, and a few cents with
`claude-haiku-5-5`. Lower `max_per_run`, run less often, or raise
`articles.dedupe_window_hours` to spend less. The newsletter and feeds cost nothing
extra, because they are built from articles that already exist.

## Project layout

```
config/            settings.yaml, sources.yaml
newsbot/           the pipeline package
  fetch.py         concurrent feed fetching and normalisation
  cluster.py       story clustering, ranking, regional/topical balancing
  extract.py       polite full-text extraction (robots.txt, trafilatura)
  writer.py        Claude writer with copy check; preview-only template writer
  images.py        openly licensed illustrations from Wikimedia Commons
  newsletter.py    daily briefing editions
  store.py         article JSON files and the seen-URL state
  build.py         static site generator (Jinja2): pages, RSS, sitemap, search index
  templates/       HTML templates and static assets
content/           articles/YYYY/MM/DD/<slug>.json and state.json (committed);
                   preview/ (git-ignored local preview output)
site/              generated output (ignored by git, deployed by the workflow)
tests/             pytest suite (offline)
```

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

## Notes on responsible use

Articles are machine-written from the facts in several reports and each links to
every source it used; nothing from the publishers is republished in full. Machine-
written text can still contain errors, which is why every page carries a confidence
level, the About page explains how the site is produced, and the footer says so.
If you run this publicly, keep that disclosure and the source links, keep the image
credits, set `fetch.api_user_agent` to your own contact URL, and remove any feed
whose publisher asks you to.
