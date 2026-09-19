"""HTML building blocks for the dashboard.

Pure functions that turn collected data into HTML strings, so they can be
tested without Streamlit. Every piece of text that comes from search data is
escaped, and links are only emitted for http(s) URLs.
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from urllib.parse import urlparse

import pandas as pd

from . import LANGUAGE_NAMES
from .scoring import TRUSTED_MIN_WEIGHT

# Plain-language names for source tiers, shared with the charts.
TIER_LABELS = {
    "official": "Government / WHO",
    "medical": "Hospital / medical",
    "reference": "Encyclopedia",
    "news": "News site",
    "machine_translated": "Google Translate copy",
    "unknown": "Unverified website",
    "ugc": "Social media / video",
}
TIER_COLORS = {
    "official": "#1f5f3f", "medical": "#3f8f63", "reference": "#7aa693", "news": "#c58a17",
    "machine_translated": "#6d4bb3", "unknown": "#a3a3a3", "ugc": "#b4441b",
}

_ICONS = {
    "type": '<rect x="2.5" y="6" width="19" height="12" rx="2"/><path d="M6.5 10h1M10.5 10h1M14.5 10h1M8 14h8"/>',
    "search": '<circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/>',
    "shield": '<path d="M12 3l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6z"/><path d="M9 12l2 2 4-4"/>',
}


def icon(name: str) -> str:
    return (f'<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" '
            f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{_ICONS[name]}</svg>')


def lang_name(code: str | None) -> str:
    return LANGUAGE_NAMES.get(code, (code or "another language", ""))[0]


def native_name(code: str) -> str:
    return LANGUAGE_NAMES.get(code, (code, code))[1]


def safe_url(url: str) -> str | None:
    """The URL if it is a plain web link, else None (never emit javascript: or data: links)."""
    return url if urlparse(url).scheme in ("http", "https") else None


def pretty_date(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%d %b %Y").lstrip("0")
    except ValueError:
        return iso


def pct(x: float) -> str:
    return f"{100 * x:.0f}%"


def band(share: float) -> str:
    return "good" if share >= 0.5 else "mid" if share >= 0.25 else "bad"


# ---------------------------------------------------------------- page sections
def masthead(data: dict, card: pd.DataFrame) -> str:
    """Headline written from the data: the worst-served language vs English."""
    indic = card.drop(index="en", errors="ignore")
    n_searches = sum(len(c["serps"]) for c in data["cells"])
    if not indic.empty and "en" in card.index:
        worst = indic["reliable"].idxmin()
        w, e = indic.loc[worst, "reliable"], card.loc["en", "reliable"]
        headline = (f"Ask Google a health question in {lang_name(worst)}, and only "
                    f"<em>{100 * w:.0f} in 100</em> answers are trustworthy pages you can read.")
        dek = (f"Ask the same kind of question in English and it’s {100 * e:.0f} in 100. "
               f"Bhasha Gap measures this gap across {card.shape[0]} languages using {n_searches} real "
               "Google searches from India.")
    else:
        headline = "How often does Google answer Indians in their own language?"
        dek = f"Bhasha Gap measures it using {n_searches} real Google searches from India."
    return (
        '<header class="masthead">'
        '<div class="brand"><span class="wordmark">Bhasha Gap</span><span class="brand-native">भाषा</span></div>'
        f'<div class="kicker">Data investigation · {escape(data.get("domain_name", ""))} information in Indian languages</div>'
        f'<h1 class="headline">{headline}</h1>'
        f'<p class="dek">{escape(dek)}</p>'
        f'<div class="meta">Collected {escape(pretty_date(data["collected_at"]))} · Google India (google.co.in) '
        'via SerpApi · No AI-generated data</div>'
        '</header>'
    )


def stat_strip(findings: list[dict]) -> str:
    items = "".join(
        f'<div class="stat"><div class="stat-label">{escape(f["label"])}</div>'
        f'<div class="stat-value">{escape(f["value"])}</div>'
        f'<div class="stat-text">{escape(f["text"])}</div></div>'
        for f in findings
    )
    return f'<div class="stats">{items}</div>'


def how_it_works(data: dict) -> str:
    examples = []
    for c in data["cells"]:
        if c["lang"] != "en" and c["lang"] not in {lang for lang, _ in examples}:
            text = next((s["text"] for s in c["suggestions"] if s["native"] and len(s["text"]) <= 28), None)
            if text:
                examples.append((c["lang"], text))
    sample = " · ".join(f'<span title="{escape(lang_name(lang))}">{escape(t)}</span>' for lang, t in examples[:6])
    steps = [
        ("type", "What people ask",
         "For each topic and language, Google Autocomplete shows the questions people really type."
         + (f'<div class="examples">{sample}</div>' if sample else "")),
        ("search", "What Google shows",
         "We run those exact questions on Google India, in that language, and record the top results."),
        ("shield", "How each answer rates",
         "Every result is checked: is it written in the reader’s language, is it from a trusted source, "
         "and is it just a Google Translate copy of a foreign page?"),
    ]
    cols = "".join(
        f'<div class="step">{icon(ic)}<div class="step-num">{i:02d}</div>'
        f'<div class="step-title">{title}</div><div class="step-text">{text}</div></div>'
        for i, (ic, title, text) in enumerate(steps, start=1)
    )
    return f'<div class="steps">{cols}</div>'


def result_list(results: list[dict], lang: str) -> str:
    """Google-style list of results with clickable titles and plain-language labels."""
    if not results:
        return '<p class="muted">Google returned no results.</p>'
    items = []
    for r in results:
        url = safe_url(r.get("link", ""))
        title = escape(r.get("title") or r.get("domain") or "Untitled")
        title_html = (f'<a href="{escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">{title}</a>'
                      if url else title)
        mt = r.get("machine_translated", False)
        reliable = r["native"] and not mt and r["authority"] >= TRUSTED_MIN_WEIGHT
        tags = []
        if reliable:
            tags.append('<span class="tag tag-good">✓ Reliable answer</span>')
        if mt:
            tags.append(f'<span class="tag tag-mt">Google Translate copy of {escape(r["domain"])}</span>')
        elif r["native"]:
            tags.append(f'<span class="tag">In {escape(lang_name(lang))}</span>')
        else:
            tags.append(f'<span class="tag tag-off">In {escape(lang_name(r.get("detected_lang")))}</span>')
        if not mt:
            color = TIER_COLORS.get(r["tier"], "#a3a3a3")
            tags.append(f'<span class="tag"><i class="dot" style="background:{color}"></i>'
                        f'{escape(TIER_LABELS.get(r["tier"], r["tier"]))}</span>')
        items.append(
            f'<li class="result"><div class="r-domain">{escape(r["domain"])}</div>'
            f'<div class="r-title">{title_html}</div><div class="r-tags">{"".join(tags)}</div></li>'
        )
    return f'<ol class="results">{"".join(items)}</ol>'


def pick_story_cell(data: dict, cells: pd.DataFrame) -> dict | None:
    """The worst-covered non-English question that has enough results to show."""
    indic = cells[(cells["lang"] != "en") & (cells["n_results"] >= 5)]
    if indic.empty:
        return None
    worst = indic.sort_values(["coverage", "gap"], ascending=[True, False]).iloc[0]
    return next(c for c in data["cells"] if c["topic"] == worst["topic"] and c["lang"] == worst["lang"])


def _verdict_count(good: int, total: int) -> str:
    if good == 0:
        return f"<b>None</b> of the {total} results were"
    return f"Only <b>{good}</b> of {total} results {'was' if good == 1 else 'were'}"


def story(data: dict, cells: pd.DataFrame, max_results: int = 5) -> str:
    cell = pick_story_cell(data, cells)
    if cell is None:
        return ""
    serp = cell["serps"][0]
    name = lang_name(cell["lang"])
    en = cells[(cells["lang"] == "en") & (cells["topic"] == cell["topic"])]
    compare = ""
    if not en.empty:
        compare = (f' For an English question about {escape(cell["topic"].lower())}, '
                   f'<b>{en.iloc[0]["trusted_native"]:.0f}</b> were.')
    return (
        '<div class="story">'
        f'<div class="story-head">A real {escape(name)} search about <b>{escape(cell["topic"].lower())}</b>, '
        'exactly as Google India returned it</div>'
        f'<div class="searchbar">{icon("search")}<span lang="{escape(cell["lang"])}">{escape(serp["query"])}</span></div>'
        f'{result_list(serp["results"][:max_results], cell["lang"])}'
        f'<div class="verdict">{_verdict_count(serp["trusted_native"], serp["n_results"])} trustworthy pages '
        f'written in {escape(name)}.{compare}</div>'
        '</div>'
    )


def scorecard(card: pd.DataFrame) -> str:
    """One row per language, best served first, with a bar for reliable answers."""
    head = ('<div class="sc-row sc-head"><div></div><div>Language</div><div>Reliable answers</div>'
            '<div class="num">In the language</div><div class="num">Translate copies</div></div>')
    rows, rank = [], 0
    for lang, row in card.iterrows():
        is_base = lang == "en"
        if not is_base:
            rank += 1
        rows.append(
            f'<div class="sc-row{" sc-base" if is_base else ""}">'
            f'<div class="sc-rank">{"—" if is_base else rank}</div>'
            f'<div class="sc-lang"><span class="sc-name">{escape(lang_name(lang))}</span>'
            f'<span class="sc-native" lang="{escape(lang)}">{escape(native_name(lang)) if not is_base else "baseline"}</span></div>'
            f'<div class="sc-bar"><div class="sc-track"><div class="sc-fill {band(row.reliable)}" '
            f'style="width:{100 * row.reliable:.1f}%"></div></div><span class="sc-val">{pct(row.reliable)}</span></div>'
            f'<div class="num">{pct(row.own_language + row.machine_translated)}</div>'
            f'<div class="num{" warn" if row.machine_translated >= 0.05 else ""}">{pct(row.machine_translated)}</div>'
            '</div>'
        )
    return f'<div class="scorecard">{head}{"".join(rows)}</div>'


def verdict_card(result: dict) -> str:
    a = result["serp"]
    cls = {"Well served": "good", "Partly served": "mid", "Poorly served": "bad"}[result["verdict"]]
    return (
        f'<div class="verdict-card {cls}"><div class="vc-lang">{escape(lang_name(result["lang"]))}</div>'
        f'<div class="vc-verdict">{escape(result["verdict"])}</div>'
        f'<div class="vc-q" lang="{escape(result["lang"])}">“{escape(result["question"])}”</div>'
        f'<div class="vc-line">{a["trusted_native"]} of {a["n_results"]} results are reliable answers</div></div>'
    )


def chips(suggestions: list[dict]) -> str:
    if not suggestions:
        return '<p class="muted">Google Autocomplete had no suggestions.</p>'
    return '<div class="chips">' + "".join(
        f'<span class="chip{"" if s["native"] else " off"}">{escape(s["text"])}</span>' for s in suggestions
    ) + "</div>"


def footer(data: dict) -> str:
    return (
        '<footer class="footer"><div><b>Bhasha Gap</b> · built for the SerpApi India Hackathon 2026</div>'
        f'<div>Data: Google Autocomplete and Google Search (google.co.in) via SerpApi, collected '
        f'{escape(pretty_date(data["collected_at"]))}. Every figure is computed from real search results.</div></footer>'
    )
