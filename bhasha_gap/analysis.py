"""Load collected results into tidy DataFrames for the dashboard."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .scoring import gap_score


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
    return pd.DataFrame(rows)


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


def pivot(cells: pd.DataFrame, metric: str, lang_order: list[str]) -> pd.DataFrame:
    table = cells.pivot(index="topic", columns="lang", values=metric)
    return table[[lang for lang in lang_order if lang in table.columns]]
