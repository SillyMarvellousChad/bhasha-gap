"""Bhasha Gap dashboard.  Run with:  streamlit run app.py"""

from __future__ import annotations

import html
import os
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

from bhasha_gap import LANGUAGE_NAMES, language_label, ui
from bhasha_gap.analysis import cells_frame, key_findings, language_summary, load_results, pivot, results_frame
from bhasha_gap.check import check_cost, check_question, load_checks, resolve_language, save_check
from bhasha_gap.collect import collect, estimate_credits, load_domain, plan_cells, save_results
from bhasha_gap.langdetect import LANG_SCRIPT
from bhasha_gap.serp import CacheMiss, SerpApiError, SerpClient

load_dotenv()
st.set_page_config(page_title="Bhasha Gap", page_icon="🗣️", layout="wide", initial_sidebar_state="collapsed")

RESULTS_DIR = Path("data/results")
DOMAINS_DIR = Path("domains")
CACHE_DIR = Path("data/cache")

TIER_COLORS = {
    "official": "#1b7f5a", "medical": "#4fa37f", "reference": "#8fb9a8",
    "news": "#d9a441", "machine_translated": "#8a6fb5", "unknown": "#b7b7b7", "ugc": "#c8553d",
}
METRICS = {
    "gap": ("Information gap", "High demand in this language, poorly answered", "Reds"),
    "coverage": ("Supply: coverage score", "How well Google serves a native reader (0–100)", "RdYlGn"),
    "native_share": ("Native-language share", "Share of top results written in the query language", "RdYlGn"),
    "trust": ("Trust", "Trustworthy (official/medical) results in the language; 3 or more = 100", "RdYlGn"),
    "mt_share": ("Machine-translated", "Share of top results that are Google Translate copies of other pages", "Purples"),
    "demand": ("Demand", "Native-script Autocomplete suggestions, normalised", "Blues"),
}
PERCENT_METRICS = {"native_share", "mt_share"}

st.markdown(f"<style>{Path('assets/style.css').read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


# ---------------------------------------------------------------- shared views
def suggestion_chips(suggestions: list[dict]) -> None:
    chips = "".join(
        f'<span class="qchip{"" if s["native"] else " off"}">{html.escape(s["text"])}</span>'
        for s in suggestions
    ) or "<em>No suggestions</em>"
    st.markdown(chips, unsafe_allow_html=True)
    st.caption("Struck-through suggestions are not in the target language, or are unrelated to the topic.")


def results_table(rows: list[dict]) -> None:
    df = pd.DataFrame(rows)
    if df.empty:
        st.write("Google returned no results.")
        return
    if "machine_translated" not in df:
        df["machine_translated"] = False
    st.dataframe(
        df[["position", "title", "domain", "detected_lang", "native", "machine_translated", "tier", "link"]],
        hide_index=True, width="stretch",
        column_config={"link": st.column_config.LinkColumn("link", display_text="open"),
                       "native": st.column_config.CheckboxColumn("in language"),
                       "machine_translated": st.column_config.CheckboxColumn("Google Translate")},
    )


# ---------------------------------------------------------------- researcher tools
def researcher_collection() -> None:
    """Run new SerpApi collections. Lives in the Method tab: visitors never need it."""
    with st.expander("🔬 For researchers: collect new data with SerpApi", expanded=not any(RESULTS_DIR.glob("*.json"))):
        domains = sorted(DOMAINS_DIR.glob("*.json"))
        domain_path = st.selectbox("Topic area", domains, format_func=lambda p: load_domain(p)["name"])
        domain = load_domain(domain_path)
        langs = st.multiselect("Languages", domain["languages"], default=domain["languages"], format_func=language_label)
        max_topics = st.slider("Topics", 1, len(domain["topics"]), len(domain["topics"]))
        per_cell = st.slider("Google searches per cell", 1, 3, 1,
                             help="How many of the top native Autocomplete questions to search.")
        api_key = os.getenv("SERPAPI_API_KEY") or st.text_input("SerpApi key", type="password")
        max_credits = st.number_input("Credit cap for this run", 0, 5000, 50, step=10,
                                      help="The run stops spending once it reaches this many live searches.")

        client = SerpClient(api_key, CACHE_DIR, max_live_calls=int(max_credits))
        cells = plan_cells(domain, langs, max_topics)
        est = estimate_credits(client, cells, per_cell)
        st.caption(f"{est['cells']} cells · up to **{est['max_credits']}** credits (cached queries are free)")
        if api_key and st.button("Check remaining credits"):
            st.caption(f"Searches left this month: {client.searches_left()}")

        if st.button("Run collection", type="primary", disabled=not (api_key or est["max_credits"] == 0)):
            bar = st.progress(0.0)
            try:
                data = collect(domain, client, langs, max_topics, per_cell,
                               lambda i, n, label: bar.progress(i / n, text=label))
            except SerpApiError as e:
                st.error(str(e))
                return
            save_results(data, RESULTS_DIR / f"{domain['id']}.json")
            st.success(f"{client.live_calls} live calls, {client.cache_hits} from cache.")
            if data["skipped"]:
                st.warning(f"{len(data['skipped'])} cells skipped (credit cap). Run again later to finish them.")
            st.rerun()


def section(title: str, subtitle: str = "") -> None:
    st.markdown(f'<div class="section-title">{title}</div>'
                + (f'<div class="section-sub">{subtitle}</div>' if subtitle else ""), unsafe_allow_html=True)


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
data = load_results(datasets[area])
cells = cells_frame(data)
results = results_frame(data)
if cells.empty:
    st.warning("This dataset has no results yet.")
    st.stop()

langs = [lang for lang in data["languages"] if lang in set(cells["lang"])]
indic = [lang for lang in langs if lang != "en"]
summary = language_summary(cells).set_index("lang").reindex(langs)

st.markdown(ui.hero(data, cells), unsafe_allow_html=True)

section("How it works", "Three steps, no guesswork: every number on this page comes from a real Google search.")
st.markdown(ui.how_it_works(), unsafe_allow_html=True)

story_html = ui.story(data, cells)
if story_html:
    section("A real search, from our data",
            "This is what Google actually showed for one of the questions we measured.")
    st.markdown(story_html, unsafe_allow_html=True)

section("Language leaderboard 🏆",
        "How well Google serves each language, out of 100: are the answers in the language, and can you trust them?")
st.markdown(ui.leaderboard(cells, results), unsafe_allow_html=True)

findings = key_findings(data, cells, results)
if findings:
    section("What the search data shows")
    st.markdown(ui.findings_cards(findings), unsafe_allow_html=True)
if data.get("skipped"):
    st.caption(f"{len(data['skipped'])} topic/language combinations not collected yet. They are excluded above.")

section("Explore the data 🧭", "Dig into every topic, language and search result, or check your own question.")
tab_map, tab_check, tab_lang, tab_drill, tab_write, tab_method = st.tabs(
    ["🗺️ Gap map", "🔎 Check a question", "📊 Languages & sources", "🔬 Drill down", "✍️ Write next", "📖 Method"]
)

# ---------------------------------------------------------------- gap map
with tab_map:
    metric = st.radio("Show", list(METRICS), format_func=lambda m: METRICS[m][0], horizontal=True)
    title, subtitle, scale = METRICS[metric]
    table = pivot(cells, metric, langs)
    if metric in PERCENT_METRICS:
        table = table * 100
    worst_first = metric in {"gap", "mt_share"}
    table = table.loc[table.mean(axis=1).sort_values(ascending=not worst_first).index]
    fig = go.Figure(go.Heatmap(
        z=table.values,
        x=[language_label(lang) for lang in table.columns],
        y=table.index,
        colorscale=scale,
        zmin=0, zmax=100,
        text=table.map(lambda v: "" if pd.isna(v) else f"{v:.0f}").values,  # blank = not collected yet
        texttemplate="%{text}",
        hovertemplate="%{y} · %{x}<br>" + title + ": %{z:.1f}<extra></extra>",
        colorbar=dict(title=""),
    ))
    fig.update_layout(height=max(380, 34 * len(table) + 80), margin=dict(l=10, r=10, t=10, b=10),
                      xaxis=dict(side="top"), yaxis=dict(autorange="reversed"))
    st.caption(subtitle)
    st.plotly_chart(fig, width="stretch")

# ---------------------------------------------------------------- check a question
VERDICT_COLORS = {"Well served": "#1b7f5a", "Partly served": "#d9a441", "Poorly served": "#c8553d"}


def render_check(result: dict, english_benchmark: float | None) -> None:
    a = result["serp"]
    color = VERDICT_COLORS[result["verdict"]]
    st.markdown(
        f'<div class="finding" style="border-left-color:{color}">'
        f'<div class="label">{html.escape(language_label(result["lang"]))}</div>'
        f'<div class="value" style="color:{color}">{result["verdict"]}</div>'
        f'<div class="text">{html.escape(result["question"])}</div></div>',
        unsafe_allow_html=True,
    )
    st.write("")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Coverage", f"{a['coverage']:.0f}/100",
              None if english_benchmark is None else f"{a['coverage'] - english_benchmark:+.0f} vs English avg")
    m2.metric("In the language", f"{a['native_count']}/{a['n_results']}")
    m3.metric("Trustworthy + in language", a["trusted_native"])
    m4.metric("Google Translate copies", a.get("machine_translated", 0))
    if result.get("hl_fallback"):
        st.caption(f"Google has no {language_label(result['lang'])} interface for this engine, "
                   "so it was searched without a language setting.")
    st.markdown("**Other questions people type** (Google Autocomplete):")
    suggestion_chips(result["suggestions"])
    st.markdown("**What Google shows**")
    results_table(a["results"])
    if a["related_questions"]:
        st.caption("People also ask: " + " · ".join(a["related_questions"]))


with tab_check:
    st.subheader("Check any question")
    st.caption("Type a health question the way someone would search it, in their own language. "
               "Bhasha Gap runs the same measurement live: 2 SerpApi credits, or free if it was checked before.")
    q_col, l_col = st.columns([3, 1])
    question = q_col.text_input("Question", placeholder="e.g. पीलिया के लक्षण · மஞ்சள் காமாலை அறிகுறிகள்")
    options = [None, *[code for code in LANGUAGE_NAMES if code in LANG_SCRIPT]]
    lang_choice = l_col.selectbox("Language", options,
                                  format_func=lambda c: "Auto-detect" if c is None else language_label(c))

    check_key = os.getenv("SERPAPI_API_KEY")
    check_client = SerpClient(check_key, CACHE_DIR)
    lang_q, note = resolve_language(question, lang_choice) if question.strip() else (None, None)
    if note:
        (st.warning if lang_q is None else st.info)(note)
    cost = check_cost(check_client, question.strip(), lang_q) if lang_q else 0
    label = "Check (free, already cached)" if lang_q and cost == 0 else f"Check ({cost or 2} credits)"
    if cost and not check_key:
        st.caption("Add SERPAPI_API_KEY to .env to run new checks.")

    if st.button(label, type="primary", disabled=not lang_q or (cost > 0 and not check_key)):
        try:
            with st.spinner("Asking Google…"):
                result = check_question(check_client, question, lang_q)
            save_check(result)
            st.session_state["last_check"] = (result["question"], result["lang"])
        except (SerpApiError, CacheMiss) as e:
            st.error(str(e))

    english_benchmark = cells.loc[cells["lang"] == "en", "coverage"].mean() if "en" in langs else None
    history = load_checks()
    if history:
        last = st.session_state.get("last_check")
        idx = next((i for i, c in enumerate(history) if (c["question"], c["lang"]) == last), 0)
        pick = st.selectbox(
            "Checked questions", range(len(history)), index=idx,
            format_func=lambda i: f"{history[i]['verdict']} · {language_label(history[i]['lang'])} · {history[i]['question']}",
        )
        render_check(history[pick], english_benchmark)

# ---------------------------------------------------------------- languages
with tab_lang:
    left, right = st.columns(2)
    with left:
        st.subheader("Is the answer in my language?")
        bars = summary.reset_index().assign(
            language=lambda d: d["lang"].map(language_label),
            native=lambda d: d["native_share"] * 100,
        )
        fig = px.bar(bars, x="language", y="native", text_auto=".0f",
                     labels={"native": "% of top results in the language", "language": ""})
        fig.update_traces(marker_color="#3b6ea5")
        fig.update_layout(height=360, margin=dict(t=10, b=10), yaxis_range=[0, 100])
        st.plotly_chart(fig, width="stretch")
    with right:
        st.subheader("Can I trust it?")
        native = results[results["native"]]
        if native.empty:
            st.write("No native-language results collected.")
        else:
            mix = (native.groupby(["lang", "tier"]).size().rename("n").reset_index()
                   .assign(share=lambda d: 100 * d["n"] / d.groupby("lang")["n"].transform("sum"),
                           language=lambda d: d["lang"].map(language_label)))
            fig = px.bar(mix, x="language", y="share", color="tier", color_discrete_map=TIER_COLORS,
                         category_orders={"tier": list(TIER_COLORS),
                                          "language": [language_label(lang) for lang in langs]},
                         labels={"share": "% of native results", "language": "", "tier": "Source"})
            fig.update_layout(height=360, margin=dict(t=10, b=10), barmode="stack")
            st.plotly_chart(fig, width="stretch")

    st.subheader("Who supplies each language?")
    lang_pick = st.selectbox("Language", langs, index=langs.index(indic[0]) if indic else 0,
                             format_func=language_label, key="src_lang")
    top = (results[(results["lang"] == lang_pick) & results["native"]]
           .groupby(["domain", "tier"]).size().rename("results").reset_index()
           .sort_values("results", ascending=False).head(12))
    st.dataframe(top, hide_index=True, width="stretch")

# ---------------------------------------------------------------- drill down
with tab_drill:
    c1, c2 = st.columns(2)
    topic = c1.selectbox("Topic", sorted(cells["topic"].unique()))
    lang = c2.selectbox("Language", langs, index=langs.index(indic[0]) if indic else 0,
                        format_func=language_label, key="drill_lang")
    cell_row = cells[(cells["topic"] == topic) & (cells["lang"] == lang)]
    raw = next((c for c in data["cells"] if c["topic"] == topic and c["lang"] == lang), None)
    if raw is None:
        st.write("Not collected.")
    else:
        r = cell_row.iloc[0]
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Coverage", f"{r.coverage:.0f}/100")
        m2.metric("Native results", f"{r.native_share * 100:.0f}%")
        m3.metric("Trusted native results", f"{r.trusted_native:.0f}")
        m4.metric("Gap", f"{r.gap:.0f}")

        st.markdown(f"**What people type** after *{raw['seed']}* (Google Autocomplete, `hl={lang}`):")
        suggestion_chips(raw["suggestions"])

        for serp in raw["serps"]:
            st.markdown(f"#### Google results for *{serp['query']}*  ·  coverage {serp['coverage']:.0f}")
            results_table(serp["results"])
            if serp["related_questions"]:
                st.caption("People also ask: " + " · ".join(serp["related_questions"]))

# ---------------------------------------------------------------- write next
with tab_write:
    st.subheader("What to write next, and in which language")
    st.caption("Real questions people ask, ranked by how badly the web answers them in their language. "
               "Useful for health departments, NGOs, journalists and creators.")
    todo = (cells[cells["lang"] != "en"].sort_values("gap", ascending=False)
            .assign(language=lambda d: d["lang"].map(language_label))
            [["topic", "language", "queries", "gap", "coverage", "native_share", "trusted_native", "mt_share"]])
    st.dataframe(
        todo, hide_index=True, width="stretch",
        column_config={
            "queries": "Question people ask",
            "gap": st.column_config.ProgressColumn("Gap", min_value=0, max_value=100, format="%.0f"),
            "coverage": st.column_config.NumberColumn("Coverage", format="%.0f"),
            "native_share": st.column_config.NumberColumn("Native share", format="percent"),
            "trusted_native": st.column_config.NumberColumn("Trusted native", format="%.0f"),
            "mt_share": st.column_config.NumberColumn("Google Translate", format="percent"),
        },
    )
    st.download_button("Download CSV", todo.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"bhasha_gap_{data['domain']}.csv", mime="text/csv")

# ---------------------------------------------------------------- method
with tab_method:
    st.markdown(Path("docs/method.md").read_text(encoding="utf-8"))
    researcher_collection()

st.markdown('<div class="footer">Built with SerpApi · Every number comes from a real Google search · '
            'No AI-generated data</div>', unsafe_allow_html=True)
