"""Bhasha Gap dashboard.  Run with:  streamlit run app.py"""

from __future__ import annotations

import os
from html import escape
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

from bhasha_gap import LANGUAGE_NAMES, language_label, ui
from bhasha_gap.analysis import cell_rates, cells_frame, key_findings, language_scorecard, load_results, pivot, results_frame
from bhasha_gap.check import (check_cost, check_question, load_checks, reliable_share, resolve_language,
                              save_check, verdict)
from bhasha_gap.collect import collect, estimate_credits, load_domain, plan_cells, save_results
from bhasha_gap.langdetect import LANG_SCRIPT
from bhasha_gap.serp import CacheMiss, SerpApiError, SerpClient

load_dotenv()
st.set_page_config(page_title="Bhasha Gap · India's language information gap", page_icon="🔎", layout="wide",
                   initial_sidebar_state="collapsed")

RESULTS_DIR = Path("data/results")
DOMAINS_DIR = Path("domains")
CACHE_DIR = Path("data/cache")

# Sequential single-hue scales read better than traffic lights and work for colour-blind readers.
BLUES = [[0, "#f4f1ea"], [0.5, "#8fb3c9"], [1, "#1d4e6f"]]
REDS = [[0, "#f4f1ea"], [0.5, "#e2a08a"], [1, "#9f2a12"]]
PURPLES = [[0, "#f4f1ea"], [0.5, "#b7a3dc"], [1, "#4b2d8f"]]
METRICS = {
    "reliable_pct": ("Reliable answers", "% of top results that are trustworthy pages written in the reader's language", BLUES, False),
    "native_pct": ("Written in the language", "% of top results written in the language that was searched", BLUES, False),
    "mt_pct": ("Google Translate copies", "% of top results that are machine-translated copies of foreign pages", PURPLES, True),
    "gap": ("Information gap", "How many people ask (Autocomplete) × how poorly Google answers, 0–100", REDS, True),
    "coverage": ("Coverage score", "Combined 0–100 score: language, trusted sources, native 'People also ask' (see Method)", BLUES, False),
}
PLOT_FONT = dict(family="Inter, Noto Sans, Nirmala UI, sans-serif", color="#16181d", size=13)

st.markdown(f"<style>{Path('assets/style.css').read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


# ---------------------------------------------------------------- helpers
def html(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


def section(label: str, title: str, subtitle: str = "") -> None:
    html(f'<div class="section"><div class="section-label">{label}</div><div class="section-title">{title}</div>'
         + (f'<div class="section-sub">{subtitle}</div>' if subtitle else "") + "</div>")


def style_fig(fig: go.Figure, height: int) -> go.Figure:
    fig.update_layout(height=height, font=PLOT_FONT, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      margin=dict(l=10, r=10, t=10, b=10), hoverlabel=dict(font_family=PLOT_FONT["family"]))
    return fig


def two_line(lang: str) -> str:
    english, native = LANGUAGE_NAMES.get(lang, (lang, lang))
    return english if english == native else f"{english}<br>{native}"


@st.cache_data(show_spinner=False)
def load_dataset(path: str, mtime: float) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    """Cached per file version: re-reads only when the results file changes."""
    data = load_results(path)
    results = results_frame(data)
    cells = cell_rates(cells_frame(data), results) if not results.empty else cells_frame(data)
    return data, cells, results


# ---------------------------------------------------------------- researcher tools
def researcher_collection() -> None:
    """Run new SerpApi collections. Lives in the Method tab: visitors never need it."""
    with st.expander("For researchers: collect new data with SerpApi", expanded=not any(RESULTS_DIR.glob("*.json"))):
        domains = sorted(DOMAINS_DIR.glob("*.json"))
        domain_path = st.selectbox("Topic area", domains, format_func=lambda p: load_domain(p)["name"])
        domain = load_domain(domain_path)
        langs = st.multiselect("Languages", domain["languages"], default=domain["languages"], format_func=language_label)
        max_topics = st.slider("Topics", 1, len(domain["topics"]), len(domain["topics"]))
        per_cell = st.slider("Google searches per topic and language", 1, 3, 1,
                             help="How many of the top Autocomplete questions to search.")
        api_key = os.getenv("SERPAPI_API_KEY") or st.text_input("SerpApi key", type="password")
        max_credits = st.number_input("Credit cap for this run", 0, 5000, 50, step=10,
                                      help="The run stops spending once it reaches this many live searches.")

        client = SerpClient(api_key, CACHE_DIR, max_live_calls=int(max_credits))
        planned = plan_cells(domain, langs, max_topics)
        est = estimate_credits(client, planned, per_cell)
        st.caption(f"{est['cells']} topic × language combinations · up to **{est['max_credits']}** credits "
                   "(cached searches are free)")
        if api_key and st.button("Check remaining credits"):
            st.caption(f"Searches left this month: {client.searches_left()}")

        if st.button("Run collection", type="primary", disabled=not (api_key or est["max_credits"] == 0)):
            bar = st.progress(0.0)
            try:
                new = collect(domain, client, langs, max_topics, per_cell,
                              lambda i, n, label: bar.progress(i / n, text=label))
            except SerpApiError as e:
                st.error(str(e))
                return
            save_results(new, RESULTS_DIR / f"{domain['id']}.json")
            st.success(f"{client.live_calls} live searches, {client.cache_hits} from cache.")
            if new["skipped"]:
                st.warning(f"{len(new['skipped'])} combinations skipped (credit cap). Run again later to finish them.")
            st.rerun()


# ---------------------------------------------------------------- data
result_files = sorted(RESULTS_DIR.glob("*.json"))
if not result_files:
    st.title("Bhasha Gap")
    st.info("No data yet. Add your `SERPAPI_API_KEY` to `.env`, then collect data below "
            "or run `python -m bhasha_gap.collect`.")
    researcher_collection()
    st.stop()

datasets = {load_results(p)["domain_name"]: p for p in result_files}
area = next(iter(datasets))
if len(datasets) > 1:
    area = st.segmented_control("Topic area", list(datasets), default=area) or area
path = datasets[area]
data, cells, results = load_dataset(str(path), path.stat().st_mtime)
if cells.empty or results.empty:
    st.warning("This dataset has no results yet.")
    st.stop()

langs = [lang for lang in data["languages"] if lang in set(cells["lang"])]
indic = [lang for lang in langs if lang != "en"]
card = language_scorecard(cells, results)

# ---------------------------------------------------------------- the story
html(ui.masthead(data, card))

findings = key_findings(data, cells, results)
if findings:
    section("By the numbers", "What the search data shows")
    html(ui.stat_strip(findings))

story_html = ui.story(data, cells)
if story_html:
    section("One search, up close", "What a reader actually sees",
            "The worst-served question in our data. Titles link to the real pages Google returned.")
    html(story_html)

section("Language scorecard", "Which languages Google serves well",
        "<b>Reliable answers</b>: the share of top Google results that are written in the reader’s language, "
        "come from a government, WHO, hospital or medical source, and are not machine-translated.")
html(ui.scorecard(card))
html(f'<div class="sc-note">Based on {len(results)} Google results for {cells["topic"].nunique()} health topics '
     "per language. English is shown as the baseline.</div>")

section("Method in brief", "How Bhasha Gap measures the gap")
html(ui.how_it_works(data))
if data.get("skipped"):
    st.caption(f"{len(data['skipped'])} topic/language combinations not collected yet. They are excluded above.")

section("Explore", "The full data", "Every topic, language and search result, and a tool to check your own question.")
tab_map, tab_check, tab_sources, tab_detail, tab_write, tab_method = st.tabs(
    ["Topic map", "Check a question", "Sources", "Search detail", "What to write next", "Full method"]
)

# ---------------------------------------------------------------- topic map
with tab_map:
    metric = st.radio("Show", list(METRICS), format_func=lambda m: METRICS[m][0], horizontal=True,
                      label_visibility="collapsed")
    title, subtitle, scale, worst_high = METRICS[metric]
    table = pivot(cells, metric, langs)
    table = table.loc[table.mean(axis=1).sort_values(ascending=worst_high).index]  # best-served topics first
    fig = go.Figure(go.Heatmap(
        z=table.values,
        x=[two_line(lang) for lang in table.columns],
        y=table.index,
        colorscale=scale, zmin=0, zmax=100, xgap=2, ygap=2,
        text=table.map(lambda v: "" if pd.isna(v) else f"{v:.0f}").values,  # blank = not collected yet
        texttemplate="%{text}",
        hovertemplate="<b>%{y}</b> · %{x}<br>" + title + ": %{z:.0f}<extra></extra>",
        colorbar=dict(title="", thickness=10, outlinewidth=0),
    ))
    style_fig(fig, max(420, 44 * len(table) + 90))
    fig.update_layout(xaxis=dict(side="top", tickangle=0), yaxis=dict(autorange="reversed"))
    st.caption(f"**{title}.** {subtitle}. Hover over a square for details.")
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

# ---------------------------------------------------------------- check a question
with tab_check:
    st.markdown("#### Check any health question")
    st.caption("Type a question the way someone would search it, in their own language. Bhasha Gap asks Google "
               "live and grades the answers: 2 SerpApi credits, or free if the question was checked before.")
    q_col, l_col = st.columns([3, 1])
    question = q_col.text_input("Question", placeholder="e.g. पीलिया के लक्षण  ·  மஞ்சள் காமாலை அறிகுறிகள்")
    options = [None, *[code for code in LANGUAGE_NAMES if code in LANG_SCRIPT]]
    lang_choice = l_col.selectbox("Language", options,
                                  format_func=lambda c: "Detect automatically" if c is None else language_label(c))

    check_key = os.getenv("SERPAPI_API_KEY")
    check_client = SerpClient(check_key, CACHE_DIR)
    lang_q, note = resolve_language(question, lang_choice) if question.strip() else (None, None)
    if note:
        (st.warning if lang_q is None else st.info)(note)
    cost = check_cost(check_client, question.strip(), lang_q) if lang_q else 0
    label = "Check this question (free, already checked)" if lang_q and cost == 0 else f"Check this question ({cost or 2} credits)"
    if cost and not check_key:
        st.caption("Add SERPAPI_API_KEY to .env to check new questions.")

    if st.button(label, type="primary", disabled=not lang_q or (cost > 0 and not check_key)):
        try:
            with st.spinner("Asking Google India…"):
                result = check_question(check_client, question, lang_q)
            save_check(result)
            st.session_state["last_check"] = (result["question"], result["lang"])
        except (SerpApiError, CacheMiss) as e:
            st.error(f"The check failed: {e}")

    # Verdicts are recomputed so older saved checks follow the current rule.
    history = [{**c, "verdict": verdict(reliable_share(c["serp"]))} for c in load_checks()]
    if history:
        last = st.session_state.get("last_check")
        idx = next((i for i, c in enumerate(history) if (c["question"], c["lang"]) == last), 0)
        pick = st.selectbox(
            "Previously checked", range(len(history)), index=idx,
            format_func=lambda i: f"{history[i]['question']}  ·  {language_label(history[i]['lang'])}  ·  {history[i]['verdict']}",
        )
        result = history[pick]
        a = result["serp"]
        html(ui.verdict_card(result))
        english = card.loc["en", "reliable"] if "en" in card.index else None
        m1, m2, m3 = st.columns(3)
        share = reliable_share(a)
        m1.metric("Reliable answers", ui.pct(share),
                  None if english is None else f"{100 * (share - english):+.0f} pts vs English average")
        m2.metric("Written in the language", f"{a['native_count'] + a.get('machine_translated', 0)} of {a['n_results']}")
        m3.metric("Google Translate copies", a.get("machine_translated", 0))
        if result.get("hl_fallback"):
            st.caption(f"Google offers no {language_label(result['lang'])} setting for this search, "
                       "so it was searched without one.")
        html('<div class="subhead">Other questions people type</div>' + ui.chips(result["suggestions"]))
        st.caption("Crossed out: not in this language, or unrelated to the question.")
        html('<div class="subhead">What Google shows</div>' + ui.result_list(a["results"], result["lang"]))
        if a["related_questions"]:
            st.caption("People also ask: " + " · ".join(a["related_questions"]))

# ---------------------------------------------------------------- sources
with tab_sources:
    st.markdown("#### Where the answers come from")
    st.caption("For each language: the kind of website behind each of the top results.")
    mix = (results.assign(source=results["tier"].map(ui.TIER_LABELS))
           .groupby(["lang", "source"]).size().rename("n").reset_index()
           .assign(share=lambda d: 100 * d["n"] / d.groupby("lang")["n"].transform("sum"),
                   language=lambda d: d["lang"].map(lambda c: LANGUAGE_NAMES.get(c, (c,))[0])))
    order = [ui.TIER_LABELS[t] for t in ui.TIER_LABELS]
    fig = px.bar(mix, y="language", x="share", color="source", orientation="h",
                 color_discrete_map={ui.TIER_LABELS[t]: c for t, c in ui.TIER_COLORS.items()},
                 category_orders={"source": order,
                                  "language": [LANGUAGE_NAMES.get(c, (c,))[0] for c in card.index]},
                 labels={"share": "% of top results", "language": "", "source": ""},
                 hover_data={"n": True, "share": ":.0f"})
    style_fig(fig, 430)
    fig.update_layout(barmode="stack", legend=dict(orientation="h", y=-0.15), xaxis=dict(range=[0, 100]))
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

    st.markdown("#### Top websites per language")
    lang_pick = st.selectbox("Language", langs, index=langs.index(indic[0]) if indic else 0,
                             format_func=language_label, key="src_lang")
    top = (results[results["lang"] == lang_pick]
           .assign(source=lambda d: d["tier"].map(ui.TIER_LABELS),
                   in_language=lambda d: d["native"] & ~d["machine_translated"])
           .groupby(["domain", "source"])
           .agg(results=("domain", "size"), in_language=("in_language", "mean"))
           .reset_index().sort_values("results", ascending=False).head(12)
           .assign(in_language=lambda d: 100 * d["in_language"]))
    st.dataframe(top, hide_index=True, width="stretch",
                 column_config={"domain": "Website", "source": "Type", "results": "Top results",
                                "in_language": st.column_config.NumberColumn("In the language", format="%.0f%%")})

# ---------------------------------------------------------------- search detail
with tab_detail:
    c1, c2 = st.columns(2)
    topic = c1.selectbox("Topic", sorted(cells["topic"].unique()))
    lang = c2.selectbox("Language", langs, index=langs.index(indic[0]) if indic else 0,
                        format_func=language_label, key="detail_lang")
    raw = next((c for c in data["cells"] if c["topic"] == topic and c["lang"] == lang), None)
    if raw is None:
        st.info("This topic and language hasn't been collected yet.")
    else:
        r = cells[(cells["topic"] == topic) & (cells["lang"] == lang)].iloc[0]
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Reliable answers", f"{r.reliable_pct:.0f}%")
        m2.metric("Written in the language", f"{r.native_pct:.0f}%")
        m3.metric("Google Translate copies", f"{r.mt_pct:.0f}%")
        m4.metric("Coverage score", f"{r.coverage:.0f}/100", help="Combined score, see Full method")

        html(f'<div class="subhead">What people type after “{escape(raw["seed"])}”</div>' + ui.chips(raw["suggestions"]))
        st.caption("From Google Autocomplete. Crossed out: not in this language, or unrelated to the topic.")
        for serp in raw["serps"]:
            html(f'<div class="subhead">Google results for “{escape(serp["query"])}”</div>'
                 + ui.result_list(serp["results"], lang))
            if serp["related_questions"]:
                st.caption("People also ask: " + " · ".join(serp["related_questions"]))

# ---------------------------------------------------------------- what to write next
with tab_write:
    st.markdown("#### What to write next, and in which language")
    st.caption("Real questions people ask, ranked by how badly Google answers them in their language. "
               "A ready-made to-do list for health departments, NGOs, journalists and creators.")
    todo = (cells[cells["lang"] != "en"].sort_values(["reliable_pct", "gap"], ascending=[True, False])
            .assign(language=lambda d: d["lang"].map(language_label))
            [["topic", "language", "queries", "reliable_pct", "native_pct", "mt_pct", "gap"]])
    st.dataframe(
        todo, hide_index=True, width="stretch",
        column_config={
            "topic": "Topic", "language": "Language", "queries": "Question people ask",
            "reliable_pct": st.column_config.ProgressColumn("Reliable answers", min_value=0, max_value=100, format="%.0f%%"),
            "native_pct": st.column_config.NumberColumn("In the language", format="%.0f%%"),
            "mt_pct": st.column_config.NumberColumn("Translate copies", format="%.0f%%"),
            "gap": st.column_config.NumberColumn("Gap score", format="%.0f"),
        },
    )
    st.download_button("Download as CSV", todo.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"bhasha_gap_{data['domain']}_write_next.csv", mime="text/csv")

# ---------------------------------------------------------------- method
with tab_method:
    st.markdown(Path("docs/method.md").read_text(encoding="utf-8"))
    researcher_collection()

html(ui.footer(data))
