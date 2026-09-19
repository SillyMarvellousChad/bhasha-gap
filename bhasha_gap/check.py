"""Check any single question: the interactive version of one heatmap cell.

A user types a question in their own language. We detect the language,
then run the same two SerpApi calls as the pipeline (Autocomplete + Google
Search) and score the results. It costs 2 credits, or nothing if cached.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import language_label
from .langdetect import LANG_SCRIPT, detect, is_romanized_indic
from .scoring import assess_serp, assess_suggestions, coverage_score
from .serp import SerpClient

CHECKS_FILE = Path("data/checks.json")

# When a script is shared, auto-detection may be inconclusive. These are the
# candidate languages per script, most widely spoken first.
_SCRIPT_CANDIDATES = {
    script: [lang for lang, s in LANG_SCRIPT.items() if s == script] for script in set(LANG_SCRIPT.values())
}


def resolve_language(question: str, choice: str | None = None) -> tuple[str | None, str | None]:
    """Return (lang, note). `choice` is the user's pick; None means auto-detect."""
    if choice:
        return choice, None
    found = detect(question)
    if found.script is None:
        return None, "Couldn't recognise the script. Type the question in an Indian language or English."
    if found.lang:
        if found.lang == "en" and is_romanized_indic(question):
            return "en", ("This looks like Hindi typed in English letters. It will be checked as an English "
                          "search. Type it in Devanagari (हिन्दी) to measure the Hindi gap.")
        return found.lang, None
    candidates = _SCRIPT_CANDIDATES.get(found.script, [])
    if not candidates:
        return None, f"{found.script} script isn't supported yet."
    lang = candidates[0]
    others = ", ".join(language_label(c) for c in candidates[1:])
    return lang, f"Checked as {language_label(lang)}. {found.script} is also used for {others}; pick it in the language box if that's what you meant."


def check_cost(client: SerpClient, question: str, lang: str) -> int:
    """Live credits this check would spend (0 when fully cached)."""
    return sum(
        not client.is_cached(p)
        for p in (client.autocomplete_params(question, lang), client.google_params(question, lang))
    )


def verdict(coverage: float) -> str:
    if coverage >= 75:
        return "Well served"
    if coverage >= 40:
        return "Partly served"
    return "Poorly served"


def check_question(client: SerpClient, question: str, lang: str) -> dict:
    question = question.strip()
    ac = client.search(client.autocomplete_params(question, lang))
    suggestions = [s["value"] for s in ac.get("suggestions", []) if s.get("value")]
    serp = client.google(question, lang)
    a = assess_serp(serp, lang)
    a["coverage"] = coverage_score(a)
    return {
        "question": question,
        "lang": lang,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "hl_fallback": bool(ac.get("hl_fallback") or serp.get("hl_fallback")),
        "verdict": verdict(a["coverage"]),
        **assess_suggestions(suggestions, question, lang),
        "serp": a,
    }


def load_checks(path: Path = CHECKS_FILE) -> list[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_check(result: dict, path: Path = CHECKS_FILE) -> None:
    """Keep the latest result per (question, language), newest first."""
    checks = [c for c in load_checks(path) if (c["question"], c["lang"]) != (result["question"], result["lang"])]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([result, *checks], ensure_ascii=False, indent=1), encoding="utf-8")
