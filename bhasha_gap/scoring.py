"""Turn raw SerpApi responses into supply (coverage) and demand measurements.

Supply = how well a search results page serves a speaker of the language.
Demand = how much people search the topic in that language, from Autocomplete.
Gap    = high demand x low supply.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from difflib import SequenceMatcher

from .authority import classify, domain_of, unwrap_translation
from .langdetect import detect, is_romanized_indic, matches_language, seeks_translation

# Google usually shows 7-10 organic results on page one. Dividing by at least
# this many means a SERP with only 2 results, both native, is not scored 100%.
EXPECTED_RESULTS = 8
# A reader is well served once there are this many trustworthy native results.
TRUSTED_TARGET = 3
TRUSTED_MIN_WEIGHT = 0.8
# A Google Translate proxy is readable but not native content: half credit.
MACHINE_TRANSLATED_CREDIT = 0.5

COVERAGE_WEIGHTS = {"native": 0.45, "trusted_native": 0.40, "native_paa": 0.15}


@dataclass
class ResultRow:
    position: int
    title: str
    link: str
    domain: str  # for machine translations, the original site
    machine_translated: bool
    script: str | None
    detected_lang: str | None
    native: bool
    tier: str
    authority: float


def assess_serp(serp: dict, lang: str) -> dict:
    """Summarise one Google SERP from the point of view of a `lang` reader."""
    rows: list[ResultRow] = []
    for i, r in enumerate(serp.get("organic_results", [])[:10], start=1):
        text = f"{r.get('title', '')} {r.get('snippet', '')}"
        link = r.get("link", "")
        original = unwrap_translation(link)
        found = detect(text)
        tier, weight = classify(link)
        rows.append(ResultRow(
            position=r.get("position", i),
            title=r.get("title", ""),
            link=link,
            domain=domain_of(original or link),
            machine_translated=original is not None,
            script=found.script,
            detected_lang=found.lang,
            native=matches_language(text, lang),
            tier=tier,
            authority=weight,
        ))

    related = [q.get("question", "") for q in serp.get("related_questions", []) if q.get("question")]
    native_count = sum(r.native and not r.machine_translated for r in rows)
    mt_native = sum(r.native and r.machine_translated for r in rows)
    trusted_native = sum(r.native and r.authority >= TRUSTED_MIN_WEIGHT for r in rows)
    native_credit = native_count + MACHINE_TRANSLATED_CREDIT * mt_native

    return {
        "results": [asdict(r) for r in rows],
        "n_results": len(rows),
        "native_count": native_count,
        "machine_translated": mt_native,
        "native_share": native_credit / max(len(rows), EXPECTED_RESULTS),
        "trusted_native": trusted_native,
        "authority_mean": sum(r.authority for r in rows) / len(rows) if rows else 0.0,
        "related_questions": related,
        "related_native": sum(matches_language(q, lang) for q in related),
        "has_knowledge_graph": "knowledge_graph" in serp,
        "has_ai_overview": "ai_overview" in serp,
        "total_results": serp.get("search_information", {}).get("total_results"),
    }


def coverage_score(a: dict) -> float:
    """0-100: how well one SERP serves a native reader."""
    if a["n_results"] == 0:
        return 0.0
    parts = {
        "native": a["native_share"],
        "trusted_native": min(a["trusted_native"] / TRUSTED_TARGET, 1.0),
        "native_paa": 1.0 if a["related_native"] > 0 else 0.0,
    }
    return round(100 * sum(COVERAGE_WEIGHTS[k] * v for k, v in parts.items()), 1)


# Autocomplete in low-resource languages sometimes returns unrelated words
# (Odia ଡେଙ୍ଗୁ -> ସ୍ବଭାବ "nature"; Punjabi ਟੀਬੀ -> ਤਬੀਲਿਸੀ "Tbilisi"). A suggestion is
# on topic if it contains the seed or its first word is a close spelling of it.
ON_TOPIC_MIN_SIMILARITY = 0.6


def on_topic(text: str, seed: str) -> bool:
    text, seed = text.strip().lower(), seed.strip().lower()
    if not text or not seed:
        return False
    if seed in text:
        return True
    return SequenceMatcher(None, text.split()[0], seed.split()[0]).ratio() >= ON_TOPIC_MIN_SIMILARITY


def assess_suggestions(suggestions: list[str], seed: str, lang: str) -> dict:
    """Classify Autocomplete suggestions: what people actually type.

    `confident` marks suggestions positively identified as `lang`, not merely
    in its script. Hindi and Marathi share seed words such as मधुमेह, so
    Autocomplete for one often returns phrases in the other.
    """
    seed_norm = seed.strip().lower()
    rows = [
        {
            "text": s,
            "native": matches_language(s, lang) and on_topic(s, seed),
            "on_topic": on_topic(s, seed),
            "confident": detect(s).lang == lang,
            "romanized": is_romanized_indic(s),  # in English cells this is Hinglish demand
            "seeks_translation": seeks_translation(s),
        }
        for s in suggestions
        if s.strip().lower() != seed_norm
    ]
    return {
        "suggestions": rows,
        "demand_raw": sum(r["native"] for r in rows),
        "off_topic_count": sum(not r["on_topic"] for r in rows),
        "romanized_count": sum(r["romanized"] for r in rows),
    }


def gap_score(demand: float, coverage: float) -> float:
    """0-100: demand (normalised 0-100) that coverage fails to meet."""
    return round(demand * (100 - coverage) / 100, 1)
