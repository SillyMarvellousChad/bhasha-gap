import pytest

from bhasha_gap.analysis import cells_frame, language_summary, results_frame
from bhasha_gap.authority import classify, unwrap_translation
from bhasha_gap.collect import collect, estimate_credits, plan_cells
from bhasha_gap.langdetect import Detection, detect, is_romanized_indic, matches_language
from bhasha_gap.scoring import assess_serp, assess_suggestions, coverage_score, gap_score
from bhasha_gap.serp import CacheMiss, SerpClient


# ------------------------------------------------------------ language detection
@pytest.mark.parametrize("text, script, lang", [
    ("मधुमेह के लक्षण क्या है", "Devanagari", "hi"),
    ("मधुमेहाच्या रुग्णांनी काय खावे आणि काय टाळावे", "Devanagari", "mr"),
    ("ডায়াবেটিসের লক্ষণ", "Bengali", "bn"),
    ("நீரிழிவு நோய் அறிகுறிகள்", "Tamil", "ta"),
    ("మధుమేహం లక్షణాలు", "Telugu", "te"),
    ("Diabetes symptoms and treatment", "Latin", "en"),
    ("", None, None),
])
def test_detect(text, script, lang):
    assert detect(text) == Detection(script, lang)


def test_ambiguous_devanagari_matches_both():
    assert matches_language("मधुमेह", "hi")
    assert matches_language("मधुमेह", "mr")


def test_marathi_is_not_hindi():
    assert not matches_language("मधुमेह म्हणजे काय आहे", "hi")
    assert matches_language("मधुमेह म्हणजे काय आहे", "mr")


def test_english_title_does_not_count_for_hindi_query():
    assert not matches_language("Diabetes: Symptoms, Causes - Mayo Clinic", "hi")


def test_romanized_hindi():
    assert is_romanized_indic("sugar ka ilaj kya hai")
    assert not is_romanized_indic("sugar level chart")


# ------------------------------------------------------------ authority
@pytest.mark.parametrize("url, tier", [
    ("https://www.nhp.gov.in/disease/diabetes", "official"),
    ("https://main.mohfw.gov.in/", "official"),
    ("https://www.who.int/news-room", "official"),
    ("https://www.aiims.edu/en.html", "official"),
    ("https://www.mayoclinic.org/diseases", "medical"),
    ("https://hi.wikipedia.org/wiki/मधुमेह", "reference"),
    ("https://www.bbc.com/hindi/articles/x", "news"),
    ("https://www.youtube.com/watch?v=abc", "ugc"),
    ("https://some-random-blog.xyz/post", "unknown"),
])
def test_classify(url, tier):
    assert classify(url)[0] == tier


# ------------------------------------------------------------ scoring
def serp(*results, related=()):
    return {
        "organic_results": [
            {"position": i, "title": t, "snippet": "", "link": link} for i, (t, link) in enumerate(results, 1)
        ],
        "related_questions": [{"question": q} for q in related],
    }


def test_english_heavy_hindi_serp_scores_low():
    a = assess_serp(serp(
        ("मधुमेह के लक्षण क्या है", "https://www.nhp.gov.in/a"),
        ("Diabetes - Mayo Clinic", "https://www.mayoclinic.org/b"),
        ("Diabetes - WHO", "https://www.who.int/c"),
    ), "hi")
    assert a["native_count"] == 1
    assert a["trusted_native"] == 1
    assert a["native_share"] == pytest.approx(1 / 8)
    assert coverage_score(a) < 25


def test_well_served_serp_scores_high():
    rows = [(f"मधुमेह के लक्षण {i} क्या है", f"https://site{i}.gov.in/") for i in range(8)]
    a = assess_serp(serp(*rows, related=["मधुमेह का इलाज क्या है"]), "hi")
    assert coverage_score(a) == 100.0


def test_empty_serp_is_zero_coverage():
    a = assess_serp({"error": "Google hasn't returned any results for this query."}, "ta")
    assert a["n_results"] == 0 and coverage_score(a) == 0.0


def test_suggestions_drop_seed_and_count_native():
    d = assess_suggestions(["டெங்கு", "டெங்கு அறிகுறிகள்", "dengue symptoms in tamil"], "டெங்கு", "ta")
    assert d["demand_raw"] == 1
    assert len(d["suggestions"]) == 2


def test_gap_score():
    assert gap_score(100, 0) == 100
    assert gap_score(100, 100) == 0
    assert gap_score(50, 40) == 30


# ------------------------------------------------------------ pipeline
DOMAIN = {
    "id": "test", "name": "Test", "languages": ["en", "hi"],
    "topics": [{"id": "dengue", "label": "Dengue", "seeds": {"en": "dengue", "hi": "डेंगू"}}],
}


class FakeClient(SerpClient):
    """Serves canned responses instead of calling SerpApi."""

    def search(self, params):
        self.live_calls += 1
        if params["engine"] == "google_autocomplete":
            if params["hl"] == "hi":
                return {"suggestions": [{"value": "डेंगू के लक्षण क्या है"}, {"value": "dengue symptoms"}]}
            return {"suggestions": [{"value": "dengue symptoms"}, {"value": "dengue treatment"}]}
        if params["hl"] == "hi":
            return serp(("Dengue - WHO", "https://www.who.int/x"), ("डेंगू के लक्षण", "https://youtube.com/y"))
        return serp(("Dengue fever - CDC", "https://www.cdc.gov/x"), ("Dengue - Mayo", "https://mayoclinic.org/y"))


def test_collect_end_to_end(tmp_path):
    client = FakeClient("fake", tmp_path)
    data = collect(DOMAIN, client, searches_per_cell=1)
    assert [c["lang"] for c in data["cells"]] == ["en", "hi"]
    hi = data["cells"][1]
    assert hi["serps"][0]["query"] == "डेंगू के लक्षण क्या है"  # searched the real question, not the seed

    cells = cells_frame(data).set_index("lang")
    assert cells.loc["en", "coverage"] > cells.loc["hi", "coverage"]
    assert cells.loc["hi", "gap"] > 0
    assert len(results_frame(data)) == 4
    assert set(language_summary(cells.reset_index())["lang"]) == {"en", "hi"}


def test_offline_client_raises_on_miss_and_collect_skips(tmp_path):
    client = SerpClient(None, tmp_path)
    with pytest.raises(CacheMiss):
        client.autocomplete("x", "hi")
    data = collect(DOMAIN, client)
    assert data["cells"] == [] and len(data["skipped"]) == 2


def test_estimate_credits(tmp_path):
    client = SerpClient(None, tmp_path)
    cells = plan_cells(DOMAIN)
    assert estimate_credits(client, cells, 2) == {"cells": 2, "max_credits": 6}


# ------------------------------------------------------------ findings from the first live run
def test_marathi_suffix_suggestion_is_not_hindi():
    assert detect("मधुमेहींसाठी").lang == "mr"
    assert not matches_language("मधुमेहींसाठी", "hi")


def test_confident_hindi_question_is_searched_before_ambiguous_one():
    d = assess_suggestions(["मधुमेह", "मधुमेह आहार", "मधुमेह के लक्षण"], "मधुमेह", "hi")
    ranked = sorted((s for s in d["suggestions"] if s["native"]), key=lambda s: not s["confident"])
    assert ranked[0]["text"] == "मधुमेह के लक्षण"


@pytest.mark.parametrize("url, original", [
    ("https://translate.google.com/translate?u=https://www.mayoclinic.org/x&hl=hi&sl=en&tl=hi",
     "https://www.mayoclinic.org/x"),
    ("https://www-mayoclinic-org.translate.goog/x?_x_tr_sl=en&_x_tr_tl=hi", "https://www.mayoclinic.org/x"),
    ("https://my--site-example-com.translate.goog/p", "https://my-site.example.com/p"),
    ("https://www.mayoclinic.org/x", None),
])
def test_unwrap_translation(url, original):
    assert unwrap_translation(url) == original


def test_machine_translated_counts_half_and_is_not_trusted():
    a = assess_serp(serp(
        ("उच्च रक्तचाप के लक्षण", "https://translate.google.com/translate?u=https://www.mayoclinic.org/x&tl=hi"),
        ("उच्च रक्तचाप के लक्षण", "https://www.fortishealthcare.com/y"),
    ), "hi")
    assert a["results"][0]["domain"] == "mayoclinic.org"
    assert a["results"][0]["tier"] == "machine_translated"
    assert a["machine_translated"] == 1 and a["native_count"] == 1
    assert a["native_share"] == pytest.approx(1.5 / 8)
    assert a["trusted_native"] == 1


def test_hospital_domains_are_medical():
    assert classify("https://www.carehospitals.com/ta/blog")[0] == "medical"


# ------------------------------------------------------------ more languages, budget, findings
@pytest.mark.parametrize("text, lang", [
    ("উচ্চ ৰক্তচাপৰ লক্ষণ", "as"),
    ("উচ্চ রক্তচাপের লক্ষণ", "bn"),
    ("ଉଚ୍ଚ ରକ୍ତଚାପର ଲକ୍ଷଣ", "or"),
    ("ਹਾਈ ਬਲੱਡ ਪ੍ਰੈਸ਼ਰ ਦੇ ਲੱਛਣ", "pa"),
])
def test_more_languages(text, lang):
    assert detect(text).lang == lang
    assert matches_language(text, lang)


def test_bengali_is_not_assamese():
    assert not matches_language("উচ্চ রক্তচাপের লক্ষণ", "as")
    assert not matches_language("উচ্চ ৰক্তচাপৰ লক্ষণ", "bn")


def test_all_domain_seeds_are_in_their_language():
    from pathlib import Path
    from bhasha_gap.collect import load_domain
    for path in Path("domains").glob("*.json"):
        d = load_domain(path)
        for t in d["topics"]:
            assert set(d["languages"]) <= set(t["seeds"]), (path, t["id"])
            for lang, seed in t["seeds"].items():
                assert matches_language(seed, lang), (path.name, t["id"], lang, seed)


def test_credit_cap_stops_spending_and_skips(tmp_path):
    class Counting(FakeClient):
        def search(self, params):
            if self.max_live_calls is not None and self.live_calls >= self.max_live_calls:
                from bhasha_gap.serp import BudgetExhausted
                raise BudgetExhausted("cap")
            return super().search(params)

    client = Counting("fake", tmp_path, max_live_calls=2)
    data = collect(DOMAIN, client)
    assert client.live_calls == 2
    assert [c["lang"] for c in data["cells"]] == ["en"]
    assert data["skipped"] == ["dengue:hi"] and data["budget_hit"]


def test_real_client_enforces_cap_before_network(tmp_path, monkeypatch):
    from bhasha_gap import serp as serp_mod
    monkeypatch.setattr(serp_mod.requests, "get", lambda *a, **k: pytest.fail("network call past cap"))
    client = SerpClient("key", tmp_path, max_live_calls=0)
    with pytest.raises(serp_mod.BudgetExhausted):
        client.autocomplete("x", "hi")


def test_key_findings_only_report_what_the_data_shows(tmp_path):
    from bhasha_gap.analysis import key_findings
    data = collect(DOMAIN, FakeClient("fake", tmp_path))
    labels = {f["label"] for f in key_findings(data, cells_frame(data), results_frame(data))}
    assert {"Language gap", "Trust gap", "Biggest gap"} <= labels
    assert "Machine-translated" not in labels  # the fake SERPs contain no Google Translate links


def test_unsupported_hl_falls_back_and_caches(tmp_path, monkeypatch):
    from bhasha_gap import serp as serp_mod
    calls = []

    class Resp:
        def __init__(self, data):
            self.data = data

        def json(self):
            return self.data

    def fake_get(url, params, timeout):
        calls.append(params)
        if "hl" in params:
            return Resp({"error": "Unsupported `as` interface language - hl parameter."})
        return Resp({"suggestions": [{"value": "মধুমেহৰ লক্ষণ"}]})

    monkeypatch.setattr(serp_mod.requests, "get", fake_get)
    client = SerpClient("key", tmp_path)
    data = client.search(client.autocomplete_params("মধুমেহ", "as"))
    assert data["hl_fallback"] and data["suggestions"][0]["value"] == "মধুমেহৰ লক্ষণ"
    assert "hl" not in calls[1] and client.live_calls == 2
    client.search(client.autocomplete_params("মধুমেহ", "as"))  # second time: from cache
    assert len(calls) == 2


def test_serpapi_error_in_one_cell_does_not_stop_the_run(tmp_path):
    from bhasha_gap.serp import SerpApiError

    class Flaky(FakeClient):
        def search(self, params):
            if params["hl"] == "en":
                raise SerpApiError("boom")
            return super().search(params)

    data = collect(DOMAIN, Flaky("fake", tmp_path))
    assert [c["lang"] for c in data["cells"]] == ["hi"]
    assert data["skipped"] == ["dengue:en"] and "boom" in data["errors"][0]


# ------------------------------------------------------------ check any question
from bhasha_gap.check import check_cost, check_question, load_checks, resolve_language, save_check, verdict


@pytest.mark.parametrize("question, choice, lang, has_note", [
    ("மஞ்சள் காமாலை அறிகுறிகள்", None, "ta", False),
    ("पीलिया के लक्षण क्या है", None, "hi", False),
    ("कावीळ म्हणजे काय", None, "mr", False),
    ("पीलिया", None, "hi", True),          # ambiguous Devanagari: defaults to Hindi, explains
    ("জণ্ডিচৰ লক্ষণ", None, "as", False),
    ("জন্ডিসের লক্ষণ", None, "bn", False),
    ("jaundice symptoms", None, "en", False),
    ("piliya ke lakshan kya hai", None, "en", True),  # romanised Hindi: warns
    ("पीलिया", "mr", "mr", False),          # the user's pick wins
    ("12345 ???", None, None, True),
])
def test_resolve_language(question, choice, lang, has_note):
    got, note = resolve_language(question, choice)
    assert got == lang and bool(note) == has_note


def test_check_question_and_cost(tmp_path):
    client = FakeClient("fake", tmp_path)
    r = check_question(client, "  डेंगू के लक्षण  ", "hi")
    assert r["question"] == "डेंगू के लक्षण"
    assert r["serp"]["n_results"] == 2 and r["verdict"] == verdict(r["serp"]["coverage"])
    assert check_cost(SerpClient(None, tmp_path / "empty"), "x", "hi") == 2


def test_verdict_thresholds():
    assert [verdict(v) for v in (90, 75, 50, 39.9)] == ["Well served", "Well served", "Partly served", "Poorly served"]


def test_check_history_keeps_latest_per_question(tmp_path):
    path = tmp_path / "checks.json"
    assert load_checks(path) == []
    save_check({"question": "a", "lang": "hi", "v": 1}, path)
    save_check({"question": "b", "lang": "hi", "v": 1}, path)
    save_check({"question": "a", "lang": "hi", "v": 2}, path)
    assert [(c["question"], c["v"]) for c in load_checks(path)] == [("a", 2), ("b", 1)]


@pytest.mark.parametrize("text, expected", [
    ("fever meaning in hindi", True),
    ("fever in hindi", True),
    ("बुखार in english", True),
    ("thyroid ka matlab", True),
    ("fever symptoms", False),
    ("बुखार के लक्षण", False),
])
def test_seeks_translation(text, expected):
    from bhasha_gap.langdetect import seeks_translation
    assert seeks_translation(text) == expected


def test_translation_requests_are_not_measured_as_questions(tmp_path):
    class Fever(FakeClient):
        def search(self, params):
            if params["engine"] == "google_autocomplete" and params["hl"] == "en":
                return {"suggestions": [{"value": "dengue meaning in hindi"}, {"value": "dengue symptoms"}]}
            return super().search(params)

    data = collect({**DOMAIN, "languages": ["en"]}, Fever("fake", tmp_path))
    assert data["cells"][0]["serps"][0]["query"] == "dengue symptoms"


@pytest.mark.parametrize("text, seed, expected", [
    ("ସ୍ବଭାବ", "ଡେଙ୍ଗୁ", False),          # Odia Autocomplete junk ("nature")
    ("ਤਬੀਲਿਸੀ", "ਟੀਬੀ", False),            # "Tbilisi" for TB
    ("ডেঙ্গুর লক্ষণ", "ডেংগু", True),        # spelling variant of the seed
    ("उच्च रक्तचाप के लक्षण", "उच्च रक्तचाप", True),
    ("diabetes symptoms", "diabetes", True),
])
def test_on_topic(text, seed, expected):
    from bhasha_gap.scoring import on_topic
    assert on_topic(text, seed) == expected


def test_off_topic_suggestions_are_not_demand_or_queries():
    d = assess_suggestions(["ଡେଙ୍ଗୁ symptoms", "ସ୍ବଭାବ", "ଭାନିଜି"], "ଡେଙ୍ଗୁ", "or")
    assert d["demand_raw"] == 0 and d["off_topic_count"] == 2


# ------------------------------------------------------------ UI building blocks
def test_ui_blocks_render_and_escape(tmp_path):
    from bhasha_gap import ui
    from bhasha_gap.analysis import key_findings

    data = collect(DOMAIN, FakeClient("fake", tmp_path))
    data["cells"][1]["suggestions"].insert(0, {"text": "डेंगू <script>x</script>", "native": True})
    cells, results = cells_frame(data), results_frame(data)
    hero = ui.hero(data, cells)
    assert "<script>" not in hero and "&lt;script&gt;" in hero
    assert "2</b> real Google searches" in hero
    assert "Step 3" in ui.how_it_works()
    assert ui.story(data, cells) == ""  # the fake Hindi SERP has only 2 results: too few to tell a story
    cells.loc[cells["lang"] == "hi", "n_results"] = 8
    story = ui.story(data, cells)
    assert "डेंगू के लक्षण क्या है" in story and "Google Translate copy" not in story
    board = ui.leaderboard(cells, results)
    assert board.index("English") < board.index("Hindi")  # English is better served in the fake data
    assert "🛡️" in ui.findings_cards(key_findings(data, cells, results))


@pytest.mark.parametrize("score, label", [(90, "Well served"), (75, "Mostly OK"), (55, "Patchy"), (20, "Poorly served")])
def test_mood(score, label):
    from bhasha_gap.ui import mood
    assert mood(score)[1] == label
