"""HTML building blocks for the dashboard's story sections.

Pure functions that turn collected data into HTML strings, so they can be
tested without Streamlit. Every piece of text that comes from search data is
escaped.
"""

from __future__ import annotations

from html import escape

import pandas as pd

from . import LANGUAGE_NAMES
from .scoring import TRUSTED_MIN_WEIGHT

LANG_COLORS = {
    "en": "#3b6ea5", "hi": "#e76f51", "bn": "#2a9d8f", "mr": "#f4a261", "ta": "#9b5de5",
    "te": "#d4a017", "as": "#ef476f", "or": "#06a77d", "pa": "#118ab2",
    "kn": "#8338ec", "ml": "#fb5607", "gu": "#3a86ff",
}
FINDING_ICONS = {
    "Language gap": "🗣️", "Trust gap": "🛡️", "Machine-translated": "🤖",
    "Hidden demand": "🔍", "Autocomplete is silent": "🔇", "Biggest gap": "🎯",
}


def _color(lang: str) -> str:
    return LANG_COLORS.get(lang, "#6c757d")


def _names(lang: str) -> tuple[str, str]:
    return LANGUAGE_NAMES.get(lang, (lang, lang))


def mood(coverage: float) -> tuple[str, str]:
    """A face and a plain-words label for a 0-100 coverage score."""
    if coverage >= 85:
        return "😀", "Well served"
    if coverage >= 70:
        return "🙂", "Mostly OK"
    if coverage >= 50:
        return "😐", "Patchy"
    return "😟", "Poorly served"


def hero(data: dict, cells: pd.DataFrame) -> str:
    """Banner with real questions people typed, floating in their own scripts."""
    bubbles, seen = [], set()
    for c in data["cells"]:
        if c["lang"] in seen:
            continue
        text = next((s["text"] for s in c["suggestions"] if s["native"] and len(s["text"]) <= 32), None)
        if text:
            seen.add(c["lang"])
            bubbles.append((c["lang"], text))
    chips = "".join(
        f'<span class="bubble" style="--c:{_color(lang)};animation-delay:{i * 0.35:.2f}s" '
        f'title="{escape(_names(lang)[0])}">{escape(text)}</span>'
        for i, (lang, text) in enumerate(bubbles)
    )
    n_searches = sum(len(c["serps"]) for c in data["cells"])
    stats = (f'<b>{cells["lang"].nunique()}</b> languages · <b>{cells["topic"].nunique()}</b> topics · '
             f'<b>{n_searches}</b> real Google searches')
    return (
        '<div class="hero">'
        '<div class="hero-kicker">🗣️ India speaks many languages. Does the internet?</div>'
        '<h1>Bhasha Gap</h1>'
        '<p class="hero-tag">Millions of Indians search for health information in their own language. '
        'We measured how often Google gives them a trustworthy answer they can read.</p>'
        f'<div class="bubbles">{chips}</div>'
        f'<div class="hero-stats">{stats}</div>'
        '<div class="hero-note">These floating questions are real searches people typed, collected from Google Autocomplete.</div>'
        '</div>'
    )


def how_it_works() -> str:
    steps = [
        ("⌨️", "What people type", "Google Autocomplete reveals the real questions people ask, in each language."),
        ("🔎", "What Google shows", "We search those exact questions from India, just like a real person would."),
        ("✅", "We grade every answer", "Is it in their language? Is it from a trusted source? Or just a Google Translate copy?"),
    ]
    cards = "".join(
        f'<div class="step"><div class="step-icon">{icon}</div><div class="step-num">Step {i}</div>'
        f'<div class="step-title">{title}</div><div class="step-text">{text}</div></div>'
        for i, (icon, title, text) in enumerate(steps, start=1)
    )
    return f'<div class="steps">{cards}</div>'


_TIER_BADGES = {
    "reference": ('info', "📚 Encyclopedia"),
    "news": ('info', "📰 News site"),
    "ugc": ('warn', "📱 Social / video"),
}


def _badges(r: dict, lang_name: str) -> str:
    badges = []
    if r.get("machine_translated"):
        badges.append(('mt', "🤖 Google Translate copy"))
    elif not r["native"]:
        badges.append(('off', f"🌐 Not in {lang_name}"))
    if not r.get("machine_translated"):
        if r["authority"] >= TRUSTED_MIN_WEIGHT:
            badges.append(('ok', "✅ Trusted source"))
        else:
            badges.append(_TIER_BADGES.get(r["tier"], ('warn', "⚠️ Unverified source")))
    return "".join(f'<span class="badge {cls}">{escape(label)}</span>' for cls, label in badges)


def pick_story_cell(data: dict, cells: pd.DataFrame) -> dict | None:
    """The worst-covered non-English question that has enough results to show."""
    indic = cells[(cells["lang"] != "en") & (cells["n_results"] >= 5)]
    if indic.empty:
        return None
    worst = indic.sort_values(["coverage", "gap"], ascending=[True, False]).iloc[0]
    return next(c for c in data["cells"] if c["topic"] == worst["topic"] and c["lang"] == worst["lang"])


def _verdict_count(good: int, total: int) -> str:
    if good == 0:
        return f"<b>None</b> of the {total} answers are"
    return f"Only <b>{good}</b> of {total} answers {'is' if good == 1 else 'are'}"


def story(data: dict, cells: pd.DataFrame, max_results: int = 5) -> str:
    cell = pick_story_cell(data, cells)
    if cell is None:
        return ""
    serp = cell["serps"][0]
    english_name, native_name = _names(cell["lang"])
    rows = "".join(
        f'<div class="result"><div class="r-title">{escape(r["title"][:90])}</div>'
        f'<div class="r-domain">{escape(r["domain"])}</div><div class="r-badges">{_badges(r, english_name)}</div></div>'
        for r in serp["results"][:max_results]
    )
    en = cells[(cells["lang"] == "en") & (cells["topic"] == cell["topic"])]
    compare = ""
    if not en.empty:
        compare = (f' Someone asking about {escape(cell["topic"].lower())} in English gets '
                   f'<b>{en.iloc[0]["trusted_native"]:.0f}</b>.')
    return (
        '<div class="story">'
        f'<div class="story-who">🧑‍🦱 Someone searches in <b style="color:{_color(cell["lang"])}">'
        f'{escape(english_name)} · {escape(native_name)}</b> about <b>{escape(cell["topic"].lower())}</b>:</div>'
        f'<div class="searchbar">🔍 <span>{escape(serp["query"])}</span></div>'
        f'<div class="results">{rows}</div>'
        f'<div class="story-verdict">{_verdict_count(serp["trusted_native"], serp["n_results"])} '
        f'trustworthy <i>and</i> in {escape(english_name)}.{compare}</div>'
        '</div>'
    )


def leaderboard(cells: pd.DataFrame, results: pd.DataFrame) -> str:
    """One tile per language, best served first: score ring, face, plain-words stats."""
    by_lang = cells.groupby("lang").agg(coverage=("coverage", "mean"), trusted=("trusted_native", "mean"))
    mt = results.groupby("lang")["machine_translated"].mean() if not results.empty else pd.Series(dtype=float)
    tiles = []
    for rank, (lang, row) in enumerate(by_lang.sort_values("coverage", ascending=False).iterrows(), start=1):
        english_name, native_name = _names(lang)
        face, label = mood(row.coverage)
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"#{rank}")
        mt_pct = 100 * mt.get(lang, 0.0)
        extra = f'<div class="tile-line">🤖 {mt_pct:.0f}% Google Translate copies</div>' if mt_pct >= 1 else ""
        baseline = '<span class="baseline">baseline</span>' if lang == "en" else ""
        tiles.append(
            f'<div class="tile" style="--c:{_color(lang)}">'
            f'<div class="tile-rank">{medal}</div>'
            f'<div class="ring" style="--p:{row.coverage:.0f}"><span>{row.coverage:.0f}</span></div>'
            f'<div class="tile-native">{escape(native_name)}</div>'
            f'<div class="tile-name">{escape(english_name)} {baseline}</div>'
            f'<div class="tile-mood">{face} {label}</div>'
            f'<div class="tile-line">🛡️ {row.trusted:.1f} trusted answers per question</div>'
            f'{extra}</div>'
        )
    return f'<div class="tiles">{"".join(tiles)}</div>'


def findings_cards(findings: list[dict]) -> str:
    cards = "".join(
        f'<div class="finding"><div class="f-icon">{FINDING_ICONS.get(f["label"], "📌")}</div>'
        f'<div class="label">{escape(f["label"])}</div><div class="value">{escape(f["value"])}</div>'
        f'<div class="text">{escape(f["text"])}</div></div>'
        for f in findings
    )
    return f'<div class="findings">{cards}</div>'
