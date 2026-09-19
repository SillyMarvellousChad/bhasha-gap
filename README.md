# Bhasha Gap

**Mapping India's information inequality with search data.**

Hundreds of millions of Indians search in Hindi, Bengali, Marathi, Tamil and Telugu. Bhasha Gap measures how often the internet actually answers them *in their language*, and from sources they can trust.

It pairs two SerpApi signals:

- **Demand.** Google **Autocomplete** in each language (`hl=hi`, `hl=ta` …) records what people really type, such as `मधुमेह के लक्षण` or `டெங்கு அறிகுறிகள்`.
- **Supply.** Those exact questions are run through Google **Search** (`gl=in`). Each result is scored for the language it is written in and the authority of its source.

The output is a **topic × language heatmap**. Red cells are questions people ask in large numbers that the web barely answers in their language. The **Write next** list turns that into an actionable content backlog for health departments, NGOs, journalists and creators.

> Search is used as a *measurement instrument*, not a content pipe. There is no LLM, and every number traces back to a SERP.

Track: **Knowledge & Public Interest** · SerpApi India Hackathon 2026

---

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env            # macOS/Linux: cp .env.example .env, then add your SERPAPI_API_KEY
```

Collect data (asks before spending credits and prints the estimate):

```bash
python -m bhasha_gap.collect --domain domains/health.json
```

Launch the dashboard:

```bash
streamlit run app.py
```

You can also collect from the app's sidebar (**Collect new data**).

### Credit budget

The free SerpApi plan has **250 searches/month**. One cell (topic × language) costs `1 + searches-per-cell` credits.

| Run | Cells | Credits |
|---|---|---|
| Full health domain, 6 languages, 1 search/cell | 90 | 180 |
| 8 topics, 6 languages | 48 | 96 |
| Quick test: `--topics 2 --langs en,hi,ta` | 6 | 12 |

Every response is cached permanently in `data/cache/`. Re-running, re-scoring or demoing costs **zero** credits. `--offline` guarantees no live calls.

---

## How it works

```
seed term per language ──► Google Autocomplete (hl=xx, gl=in) ──► real questions + demand count
                                                                     │
                            Google Search (hl=xx, gl=in) ◄───────────┘
                                     │
               per result: script/language detection + source-authority tier
                                     │
               coverage (0–100) ──► gap = demand × (1 − coverage) ──► heatmap / write-next list
```

| Module | Role |
|---|---|
| `bhasha_gap/serp.py` | SerpApi client with permanent disk cache and credit counter |
| `bhasha_gap/langdetect.py` | Unicode-script language detection, plus Hindi/Marathi disambiguation (`है/में` vs `आहे/मध्ये`, `-च्या`, `ळ`) |
| `bhasha_gap/authority.py` | Source tiers: official (gov.in, nic.in, WHO), medical, reference, news, unknown, user-generated |
| `bhasha_gap/scoring.py` | Native share, trusted-native count, coverage and gap scores |
| `bhasha_gap/collect.py` | Pipeline and CLI |
| `bhasha_gap/analysis.py` | DataFrames for the dashboard |
| `domains/health.json` | 15 health topics with seed terms in 6 languages |
| `app.py` | Streamlit dashboard |

The full scoring method is in [docs/method.md](docs/method.md).

**Add a domain.** Copy `domains/health.json` (for example to `government_schemes.json`), then fill in topics and seed terms per language. Kannada, Malayalam, Gujarati, Punjabi and Odia are already supported by the detector.

## Tests

```bash
pytest
```

## How the project uses SerpApi

The whole analysis depends on SerpApi's multi-locale search:

- **Google Autocomplete engine**, per language, to harvest the real questions people type (demand).
- **Google Search engine** with `hl`/`gl`/`google_domain`, to measure what Indians are actually served (supply). This uses `organic_results` for language and authority, `related_questions` for native "People also ask", and the empty-SERP response as a zero-supply measurement.
- The **Account API** to show remaining credits before a run.

Without per-language SERPs there is no data. Every number in the dashboard comes from a SerpApi response.

## Limitations

A single snapshot, from one location (`gl=in`). Autocomplete volume is a relative proxy, not an absolute search count. Script detection cannot tell romanised Hindi from English. The authority list is hand-curated. Seed translations should be verified by native speakers.

## AI tools used

Claude (Anthropic) helped design and write the code. The app itself uses no LLM.
