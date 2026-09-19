"""Lightweight, dependency-free language detection for Indian-language SERP text.

Search result titles and snippets are short, so statistical detectors are
unreliable on them. Instead we rely on Unicode script blocks (which cleanly
separate most Indian languages) and add a marker-word pass to split the two
big Devanagari languages, Hindi and Marathi.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SCRIPT_RANGES: dict[str, tuple[int, int]] = {
    "Devanagari": (0x0900, 0x097F),
    "Bengali": (0x0980, 0x09FF),
    "Gurmukhi": (0x0A00, 0x0A7F),
    "Gujarati": (0x0A80, 0x0AFF),
    "Oriya": (0x0B00, 0x0B7F),
    "Tamil": (0x0B80, 0x0BFF),
    "Telugu": (0x0C00, 0x0C7F),
    "Kannada": (0x0C80, 0x0CFF),
    "Malayalam": (0x0D00, 0x0D7F),
}

LANG_SCRIPT: dict[str, str] = {
    "en": "Latin",
    "hi": "Devanagari",
    "mr": "Devanagari",
    "bn": "Bengali",
    "ta": "Tamil",
    "te": "Telugu",
    "kn": "Kannada",
    "ml": "Malayalam",
    "gu": "Gujarati",
    "pa": "Gurmukhi",
    "or": "Oriya",
}

# Only languages whose script is unique to them. Devanagari is shared by
# Hindi and Marathi, so it is resolved separately.
_SCRIPT_TO_LANG = {
    script: lang
    for lang, script in LANG_SCRIPT.items()
    if list(LANG_SCRIPT.values()).count(script) == 1
}

_HINDI_MARKERS = {
    "है", "हैं", "के", "की", "का", "में", "और", "से", "को", "लिए", "क्या",
    "कैसे", "होता", "होती", "होते", "करें", "नहीं", "यह", "वह", "जाता", "किया",
}
_MARATHI_MARKERS = {
    "आहे", "आहेत", "आणि", "मध्ये", "साठी", "काय", "कसे", "कशी", "होतो",
    "करा", "नाही", "हे", "व", "या", "कोणते", "कसा", "असते", "असतो",
}
_DEVANAGARI_WORD = re.compile(r"[ऀ-ॿ]+")

# Common words in Hindi typed in Latin script ("sugar ka ilaj kya hai").
_ROMANIZED_MARKERS = {
    "hai", "kya", "ka", "ki", "ke", "kaise", "mein", "me", "ilaj", "hota",
    "hoti", "kare", "karein", "nahi", "aur", "se", "ko", "liye", "kab",
    "kyu", "kyon", "upay", "lakshan", "gharelu", "dawa", "rog",
}


@dataclass(frozen=True)
class Detection:
    script: str | None
    lang: str | None  # None when the script is shared and evidence is inconclusive


def _script_of(ch: str) -> str | None:
    cp = ord(ch)
    for name, (lo, hi) in SCRIPT_RANGES.items():
        if lo <= cp <= hi:
            return name
    if ch.isascii() and ch.isalpha():
        return "Latin"
    return None


def script_profile(text: str) -> dict[str, float]:
    """Share of letter characters belonging to each script."""
    counts: dict[str, int] = {}
    for ch in text:
        script = _script_of(ch)
        if script:
            counts[script] = counts.get(script, 0) + 1
    total = sum(counts.values())
    return {s: c / total for s, c in counts.items()} if total else {}


def dominant_script(text: str, min_share: float = 0.5) -> str | None:
    profile = script_profile(text)
    if not profile:
        return None
    script, share = max(profile.items(), key=lambda kv: kv[1])
    return script if share >= min_share else None


def devanagari_lang(text: str) -> str | None:
    """Split Devanagari text into Hindi or Marathi using marker words.

    The retroflex ळ is frequent in Marathi and almost absent from Hindi, and
    the genitive suffix -च्या is distinctly Marathi, so both count as evidence.
    """
    words = _DEVANAGARI_WORD.findall(text)
    hi = sum(w in _HINDI_MARKERS for w in words)
    mr = sum(w in _MARATHI_MARKERS for w in words)
    mr += sum(w.endswith("च्या") and w != "च्या" for w in words)
    mr += text.count("ळ")
    if hi > mr:
        return "hi"
    if mr > hi:
        return "mr"
    return None


def detect(text: str) -> Detection:
    script = dominant_script(text)
    if script is None:
        return Detection(None, None)
    if script == "Latin":
        return Detection(script, "en")
    if script == "Devanagari":
        return Detection(script, devanagari_lang(text))
    return Detection(script, _SCRIPT_TO_LANG.get(script))


def matches_language(text: str, lang: str) -> bool:
    """True if `text` is written in `lang`.

    Ambiguous Devanagari counts as a match for both Hindi and Marathi. Short
    titles often carry no marker words, and penalising them would inflate the
    measured gap.
    """
    expected = LANG_SCRIPT.get(lang)
    if expected is None:
        raise ValueError(f"Unsupported language: {lang}")
    found = detect(text)
    if found.script != expected:
        return False
    return found.lang is None or found.lang == lang


def is_romanized_indic(text: str) -> bool:
    """Heuristic: Latin-script text that reads like transliterated Hindi."""
    if dominant_script(text) != "Latin":
        return False
    words = re.findall(r"[a-z]+", text.lower())
    return sum(w in _ROMANIZED_MARKERS for w in words) >= 2
