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

    # 1. The language gap: worst-served language vs English.
    by_lang = indic_cells.groupby("lang")["native_share"].mean()
    if not by_lang.empty:
        worst = by_lang.idxmin()
        text = f"of page-one results for {language_label(worst)} questions are actually in {language_label(worst).split(' ·')[0]}"
        if "en" in set(cells["lang"]):
            text += f", vs {_pct(cells.loc[cells['lang'] == 'en', 'native_share'].mean())} for English"
        findings.append({"label": "Language gap", "value": _pct(by_lang[worst]), "text": text + "."})

    # 2. The trust gap: native results that come from official/medical sources.
    def trusted_share(df: pd.DataFrame) -> float:
        own = df[df["native"] & ~df["machine_translated"]]
        return (own["authority"] >= TRUSTED_MIN_WEIGHT).mean() if len(own) else float("nan")

    trust = indic_results.groupby("lang").apply(trusted_share, include_groups=False).dropna()
    if not trust.empty:
        worst = trust.idxmin()
        text = f"of {language_label(worst)} results come from official or medical sources"
        if not en_results.empty:
            text += f", vs {_pct(trusted_share(en_results))} in English"
        findings.append({"label": "Trust gap", "value": _pct(trust[worst]), "text": text + "."})

    # 3. Machine translation filling the gap.
    mt = indic_results[indic_results["machine_translated"]]
    if len(mt):
        by_lang = indic_results.groupby("lang")["machine_translated"].mean()
        top = by_lang.idxmax()
        sources = ", ".join(mt["domain"].value_counts().head(3).index)
        findings.append({
            "label": "Machine-translated",
            "value": _pct(by_lang[top]),
            "text": f"of {language_label(top)} results are Google Translate copies of English pages ({sources}).",
        })

    # 4. Hinglish: Hindi demand typed in Roman script, hidden inside English.
    en_cells = [c for c in data["cells"] if c["lang"] == "en"]
    en_sugg = [s for c in en_cells for s in c["suggestions"]]
    hinglish = [s["text"] for s in en_sugg if s.get("romanized")]
    if hinglish:
        findings.append({
            "label": "Hidden demand",
            "value": f"{len(hinglish)}/{len(en_sugg)}",
            "text": f"English Autocomplete suggestions are Hindi typed in Roman script, e.g. \"{hinglish[0]}\".",
        })

    # 5. The single worst cell, with a real question.
    if not indic_cells.empty:
        w = indic_cells.sort_values("gap", ascending=False).iloc[0]
        findings.append({
            "label": "Biggest gap",
            "value": f"{w['gap']:.0f}/100",
            "text": f"{w['topic']} in {language_label(w['lang'])}: people ask \"{w['queries'].split(' | ')[0]}\" "
                    f"and {w['trusted_native']:.0f} of the top results are trustworthy and in their language.",
        })
    return findings


def pivot(cells: pd.DataFrame, metric: str, lang_order: list[str]) -> pd.DataFrame:
    table = cells.pivot(index="topic", columns="lang", values=metric)
    return table[[lang for lang in lang_order if lang in table.columns]]
