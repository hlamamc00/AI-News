"""Command-line entry point: ``python -m newsbot <command>``."""

from __future__ import annotations

import argparse
import logging
import sys

from . import __version__
from .config import load_settings, load_sources


def _cmd_run(args: argparse.Namespace) -> int:
    from .pipeline import run
    from .writer import NoWriterError

    try:
        report = run(
            limit=args.limit,
            writer_mode=args.writer,
            extract=False if args.no_extract else None,
            build=not args.no_build,
            dry_run=args.dry_run,
        )
    except NoWriterError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(report.summary())
    if report.errors and args.verbose:
        for name, err in sorted(report.errors.items()):
            print(f"  feed failed: {name}: {err}", file=sys.stderr)
    if report.selected and not report.written and not args.dry_run:
        print("error: stories were selected but none could be written", file=sys.stderr)
        return 1
    return 0


def _cmd_build(args: argparse.Namespace) -> int:
    from .build import build_site
    from .config import ARTICLES_DIR, PREVIEW_DIR
    from .store import load_articles

    articles = load_articles(ARTICLES_DIR)
    if args.preview:
        articles += load_articles(PREVIEW_DIR)
    out = build_site(load_settings(), articles)
    print(f"site built at {out}")
    return 0


def _cmd_sources(args: argparse.Namespace) -> int:
    from .fetch import fetch_source

    settings = load_settings()
    sources = load_sources()
    if not args.check:
        for src in sources:
            print(f"{src.region:12} {src.category:12} {src.name:32} {src.url}")
        print(f"{len(sources)} sources")
        return 0
    import concurrent.futures as cf

    failures = 0
    with cf.ThreadPoolExecutor(max_workers=settings.fetch_workers) as pool:
        futures = {pool.submit(fetch_source, src, settings): src for src in sources}
        for future in cf.as_completed(futures):
            src = futures[future]
            try:
                items = future.result()
                print(f"ok   {len(items):3d} items  {src.name}")
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"FAIL           {src.name}: {type(exc).__name__}: {exc}")
    print(f"{len(sources) - failures}/{len(sources)} feeds ok")
    return 1 if failures and args.strict else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="newsbot", description="Automated worldwide newsroom")
    parser.add_argument("--version", action="version", version=f"newsbot {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="fetch feeds, write new articles and rebuild the site")
    p_run.add_argument("--limit", type=int, help="maximum new articles this run")
    p_run.add_argument("--writer", choices=["auto", "claude", "template"], help="override writer.mode (template = local preview only)")
    p_run.add_argument("--no-extract", action="store_true", help="skip fetching full source pages")
    p_run.add_argument("--no-build", action="store_true", help="write articles but do not rebuild the site")
    p_run.add_argument("--dry-run", action="store_true", help="show which stories would be written, change nothing")
    p_run.set_defaults(func=_cmd_run)

    p_build = sub.add_parser("build", help="rebuild the static site from stored articles")
    p_build.add_argument("--preview", action="store_true", help="also include local preview articles")
    p_build.set_defaults(func=_cmd_build)

    p_sources = sub.add_parser("sources", help="list or check the feed catalogue")
    p_sources.add_argument("--check", action="store_true", help="fetch every feed and report failures")
    p_sources.add_argument("--strict", action="store_true", help="exit non-zero if any feed fails")
    p_sources.set_defaults(func=_cmd_sources)

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("trafilatura").setLevel(logging.ERROR)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpx2").setLevel(logging.WARNING)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
