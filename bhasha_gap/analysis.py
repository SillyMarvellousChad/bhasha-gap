"""Load collected results into tidy DataFrames for the dashboard."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from . import language_label
from .scoring import EXPECTED_RESULTS, TRUSTED_MIN_WEIGHT, TRUSTED_TARGET, gap_score


def load_results(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def cells_frame(data: dict) -> pd.DataFrame:
    """One row per (topic, language) with demand, supply and gap."""
    rows = []
    for c in data["cells"]:
        serps = c["serps"]
        n = len(serps) or 1
        rows.append({
            "topic_id": c["topic_id"],
            "topic": c["topic"],
            "lang": c["lang"],
            "seed": c["seed"],
            "demand_raw": c["demand_raw"],
            "romanized_count": c["romanized_count"],
            "suggestions": len(c["suggestions"]),
            "coverage": sum(s["coverage"] for s in serps) / n,
            "native_share": sum(s["native_share"] for s in serps) / n,
            "trusted_native": sum(s["trusted_native"] for s in serps) / n,
            "reliable_share": sum(s["trusted_native"] / max(s["n_results"], 1) for s in serps) / n,
            "mt_share": sum(s.get("machine_translated", 0) / max(s["n_results"], EXPECTED_RESULTS)
                            for s in serps) / n,
            "authority_mean": sum(s["authority_mean"] for s in serps) / n,
            "native_paa": any(s["related_native"] > 0 for s in serps),
            "n_results": sum(s["n_results"] for s in serps) / n,
            "queries": " | ".join(s["query"] for s in serps),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    max_demand = df["demand_raw"].max() or 1
    df["demand"] = (100 * df["demand_raw"] / max_demand).round(1)
    df["gap"] = [gap_score(d, c) for d, c in zip(df["demand"], df["coverage"])]
    df["trust"] = (100 * (df["trusted_native"] / TRUSTED_TARGET).clip(upper=1)).round(1)
    df["coverage"] = df["coverage"].round(1)
    return df


def results_frame(data: dict) -> pd.DataFrame:
    """One row per organic result, for drill-down and source analysis."""
    rows = [
        {"topic": c["topic"], "lang": c["lang"], "query": s["query"], **r}
        for c in data["cells"]
        for s in c["serps"]
        for r in s["results"]
    ]
    df = pd.DataFrame(rows)
    if not df.empty and "machine_translated" not in df:  # datasets from before MT tagging
        df["machine_translated"] = False
    return df


def reliable_mask(results: pd.DataFrame) -> pd.Series:
    """A reliable answer is in the reader's language, from a trusted source, and not machine-translated."""
    return results["native"] & ~results["machine_translated"] & (results["authority"] >= TRUSTED_MIN_WEIGHT)


def language_scorecard(cells: pd.DataFrame, results: pd.DataFrame) -> pd.DataFrame:
    """Per language: share of top results that are reliable, in the language, or Google Translate copies."""
    r = results.assign(
        reliable=reliable_mask(results),
        own_language=results["native"] & ~results["machine_translated"],
    )
    card = r.groupby("lang").agg(
        reliable=("reliable", "mean"),
        own_language=("own_language", "mean"),
        machine_translated=("machine_translated", "mean"),
        results=("reliable", "size"),
    )
    card["coverage"] = cells.groupby("lang")["coverage"].mean()
    card["topics"] = cells.groupby("lang")["topic"].nunique()
    return card.sort_values("reliable", ascending=False)


def cell_rates(cells: pd.DataFrame, results: pd.DataFrame) -> pd.DataFrame:
    """`cells` plus per-result percentages, computed exactly like the language scorecard."""
    rates = (
        results.assign(reliable=reliable_mask(results))
        .groupby(["topic", "lang"])
        .agg(reliable_pct=("reliable", "mean"), native_pct=("native", "mean"), mt_pct=("machine_translated", "mean"))
        .mul(100)
        .reset_index()
    )
    return cells.merge(rates, on=["topic", "lang"], how="left")


def language_summary(cells: pd.DataFrame) -> pd.DataFrame:
    return (
        cells.groupby("lang", sort=False)
        .agg(
            coverage=("coverage", "mean"),
            native_share=("native_share", "mean"),
            trusted_native=("trusted_native", "mean"),
            demand=("demand", "mean"),
            gap=("gap", "mean"),
            topics=("topic", "count"),
        )
        .reset_index()
    )


def _pct(x: float) -> str:
    return f"{100 * x:.0f}%"


def key_findings(data: dict, cells: pd.DataFrame, results: pd.DataFrame) -> list[dict]:
    """The headline numbers for the pitch, computed from the data.

    Each finding is {"label", "value", "text"}. Findings with no supporting
    data (e.g. no machine translation seen) are left out, never invented.
    """
    findings: list[dict] = []
    if cells.empty or results.empty:
        return findings
    indic_cells = cells[cells["lang"] != "en"]
    indic_results = results[results["lang"] != "en"]
    en_results = results[results["lang"] == "en"]

    # 1. The language gap: worst-served language vs English (per result, like the scorecard).
    by_lang = indic_results.groupby("lang")["native"].mean()
    if not by_lang.empty:
        worst = by_lang.idxmin()
        name = language_label(worst).split(" ·")[0]
        text = f"of page-one results for {name} questions are actually written in {name}"
        if not en_results.empty:
            text += f", vs {_pct(en_results['native'].mean())} for English"
        findings.append({"label": "Language gap", "value": _pct(by_lang[worst]), "text": text + "."})

    # 2. The trust gap: top results that are reliable (in the language, trusted, not machine-translated).
    reliable = indic_results.assign(ok=reliable_mask(indic_results)).groupby("lang")["ok"].mean()
    if not reliable.empty:
        worst = reliable.idxmin()
        name = language_label(worst).split(" ·")[0]
        text = f"of top results for {name} questions are trustworthy pages written in {name}"
        if not en_results.empty:
            text += f", vs {_pct(reliable_mask(en_results).mean())} for English"
        findings.append({"label": "Trust gap", "value": _pct(reliable[worst]), "text": text + "."})

    # 3. Machine translation filling the gap.
    mt = indic_results[indic_results["machine_translated"]]
    if len(mt):
        by_lang = indic_results.groupby("lang")["machine_translated"].mean()
        top = by_lang.idxmax()
        sources = ", ".join(mt["domain"].value_counts().head(3).index)
        findings.append({
            "label": "Machine-translated",
            "value": _pct(by_lang[top]),
            "text": f"of results for {language_label(top).split(' ·')[0]} questions are Google Translate copies "
                    f"of foreign websites ({sources}).",
        })

    # 4. Hidden demand: Indian-language demand inside English Autocomplete,
    # either typed in Roman script or asking for a translation.
    en_cells = [c for c in data["cells"] if c["lang"] == "en"]
    en_sugg = [s for c in en_cells for s in c["suggestions"]]
    hidden = [s["text"] for s in en_sugg if s.get("romanized") or s.get("seeks_translation")]
    if hidden:
        examples = sorted(hidden, key=lambda t: "in hindi" not in t.lower())[:2]
        findings.append({
            "label": "Hidden demand",
            "value": f"{len(hidden)}/{len(en_sugg)}",
            "text": "English Autocomplete suggestions are really people looking for an Indian language, e.g. "
                    + ", ".join(f"\"{t}\"" for t in examples) + ".",
        })

    # 5. Autocomplete has nothing on-topic to suggest: Google barely knows the language.
    silent = indic_cells.assign(silent=indic_cells["demand_raw"] <= 1).groupby("lang")["silent"].mean()
    if not silent.empty and silent.max() >= 0.3:
        lang = silent.idxmax()
        n_topics = int((indic_cells["lang"] == lang).sum())
        findings.append({
            "label": "Autocomplete is silent",
            "value": f"{round(silent[lang] * n_topics)}/{n_topics}",
            "text": f"health topics get almost no related Autocomplete suggestions in {language_label(lang).split(' ·')[0]}: "
                    "Google has too little search data in the language to suggest anything.",
        })

    # 6. The single worst cell, with a real question.
    if not indic_cells.empty:
        w = indic_cells.sort_values("gap", ascending=False).iloc[0]
        findings.append({
            "label": "Biggest gap",
            "value": f"{w['gap']:.0f}/100",
            "text": f"{w['topic']} in {language_label(w['lang']).split(' ·')[0]}: people ask "
                    f"\"{w['queries'].split(' | ')[0]}\", and {w['trusted_native']:.0f} of the top results "
                    "are trustworthy and in their language.",
        })
    return findings


def pivot(cells: pd.DataFrame, metric: str, lang_order: list[str]) -> pd.DataFrame:
    table = cells.pivot(index="topic", columns="lang", values=metric)
    return table[[lang for lang in lang_order if lang in table.columns]]
