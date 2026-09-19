"""Collection pipeline: demand from Autocomplete, supply from Google Search.

For every (topic, language) cell:
  1. Google Autocomplete on the native-language seed term records what
     people actually type (demand).
  2. The top native suggestions, which are real questions in real phrasing,
     are searched on Google with that interface language (supply).
  3. Each SERP is scored for native-language share and source authority.

Usage:
    python -m bhasha_gap.collect --domain domains/health.json --yes
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .scoring import assess_serp, assess_suggestions, coverage_score
from .serp import BudgetExhausted, CacheMiss, SerpApiError, SerpClient

ProgressFn = Callable[[int, int, str], None]


def load_domain(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def plan_cells(domain: dict, langs: list[str] | None = None, max_topics: int | None = None) -> list[tuple[dict, str]]:
    langs = langs or domain["languages"]
    topics = domain["topics"][:max_topics] if max_topics else domain["topics"]
    return [(t, lang) for t in topics for lang in langs if lang in t["seeds"]]


def estimate_credits(client: SerpClient, cells: list[tuple[dict, str]], searches_per_cell: int) -> dict:
    """Upper bound on live SerpApi calls. Cached queries are free."""
    uncached_autocomplete = sum(
        not client.is_cached(client.autocomplete_params(t["seeds"][lang], lang)) for t, lang in cells
    )
    # Search queries depend on the autocomplete output, so a cell whose
    # autocomplete is cached is assumed to have its searches cached as well.
    return {
        "cells": len(cells),
        "max_credits": uncached_autocomplete * (1 + searches_per_cell),
    }


def collect_cell(client: SerpClient, topic: dict, lang: str, searches_per_cell: int) -> dict:
    seed = topic["seeds"][lang]
    ac = client.search(client.autocomplete_params(seed, lang))
    suggestions = [s["value"] for s in ac.get("suggestions", []) if s.get("value")]
    demand = assess_suggestions(suggestions, seed, lang)
    hl_fallback = bool(ac.get("hl_fallback"))
    # Search real questions (not "... meaning in hindi" translation requests),
    # the ones we are surest are in `lang` first.
    native = sorted(
        (s for s in demand["suggestions"] if s["native"]),
        key=lambda s: (s.get("seeks_translation", False), not s["confident"]),
    )
    native_questions = [s["text"] for s in native]
    queries = native_questions[:searches_per_cell] or [seed]

    serps = []
    for q in queries:
        serp = client.google(q, lang)
        hl_fallback |= bool(serp.get("hl_fallback"))
        a = assess_serp(serp, lang)
        a["query"] = q
        a["coverage"] = coverage_score(a)
        serps.append(a)

    return {
        "topic_id": topic["id"],
        "topic": topic["label"],
        "lang": lang,
        "seed": seed,
        "hl_fallback": hl_fallback,  # Google has no interface in this language
        **demand,
        "serps": serps,
    }


def collect(
    domain: dict,
    client: SerpClient,
    langs: list[str] | None = None,
    max_topics: int | None = None,
    searches_per_cell: int = 1,
    progress: ProgressFn | None = None,
) -> dict:
    cells = plan_cells(domain, langs, max_topics)
    results, skipped, errors = [], [], []
    budget_hit = False
    for i, (topic, lang) in enumerate(cells, start=1):
        if progress:
            progress(i, len(cells), f"{topic['label']} · {lang}")
        try:
            results.append(collect_cell(client, topic, lang, searches_per_cell))
        except BudgetExhausted:
            # Keep going: later cells may still be fully cached.
            budget_hit = True
            skipped.append(f"{topic['id']}:{lang}")
        except CacheMiss:
            skipped.append(f"{topic['id']}:{lang}")
        except SerpApiError as e:
            # One bad cell must not throw away the rest of a paid run.
            skipped.append(f"{topic['id']}:{lang}")
            errors.append(f"{topic['id']}:{lang}: {e}")

    return {
        "domain": domain["id"],
        "domain_name": domain["name"],
        "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "languages": sorted({lang for _, lang in cells}, key=(langs or domain["languages"]).index),
        "searches_per_cell": searches_per_cell,
        "cells": results,
        "skipped": skipped,
        "budget_hit": budget_hit,
        "errors": errors,
    }


def save_results(data: dict, out: str | Path) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    p = argparse.ArgumentParser(description="Collect Bhasha Gap measurements via SerpApi.")
    p.add_argument("--domain", default="domains/health.json")
    p.add_argument("--langs", help="Comma-separated language codes (default: all in domain)")
    p.add_argument("--topics", type=int, help="Only the first N topics")
    p.add_argument("--searches-per-cell", type=int, default=1, help="Google searches per topic×language (default 1)")
    p.add_argument("--out", help="Output JSON (default: data/results/<domain>.json)")
    p.add_argument("--cache", default="data/cache")
    p.add_argument("--offline", action="store_true", help="Use only cached responses; never spend credits")
    p.add_argument("--max-credits", type=int, help="Hard cap on live SerpApi calls for this run")
    p.add_argument("--yes", action="store_true", help="Skip the credit confirmation prompt")
    args = p.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")

    domain = load_domain(args.domain)
    langs = args.langs.split(",") if args.langs else None
    client = SerpClient(os.getenv("SERPAPI_API_KEY"), args.cache, offline=args.offline,
                        max_live_calls=args.max_credits)
    cells = plan_cells(domain, langs, args.topics)
    est = estimate_credits(client, cells, args.searches_per_cell)

    print(f"{est['cells']} cells, up to {est['max_credits']} SerpApi credits (cached queries are free).")
    if args.max_credits is not None:
        print(f"Credit cap for this run: {args.max_credits}")
    if not client.offline:
        left = client.searches_left()
        if left is not None:
            print(f"Your account has {left} searches left this month.")
    elif est["max_credits"]:
        print("Offline mode: cells that are not cached will be skipped.")

    if est["max_credits"] and not client.offline and not args.yes:
        if input("Proceed? [y/N] ").strip().lower() != "y":
            return 1

    def report(i: int, n: int, label: str) -> None:
        print(f"  [{i:>3}/{n}] {label}", flush=True)

    data = collect(domain, client, langs, args.topics, args.searches_per_cell, report)
    out = save_results(data, args.out or f"data/results/{domain['id']}.json")
    print(f"\nSaved {len(data['cells'])} cells to {out}")
    print(f"Live SerpApi calls: {client.live_calls}, cache hits: {client.cache_hits}")
    if data["skipped"]:
        reason = "credit cap reached / not cached" if data["budget_hit"] else "not cached"
        print(f"Skipped ({reason}): {', '.join(data['skipped'])}")
        print("Re-run later: finished cells come from the cache for free.")
    for e in data["errors"]:
        print(f"ERROR {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
