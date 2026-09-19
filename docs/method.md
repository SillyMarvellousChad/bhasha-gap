### How Bhasha Gap measures the gap

Bhasha Gap uses the search results page as a **measurement instrument**, not as content to summarise. No LLM is involved. Every number traces back to a SerpApi response.

**1. Demand: what people actually ask.**
For each topic, a native-language seed term (for example `मधुमेह`, `நீரிழிவு`) is sent to SerpApi's **Google Autocomplete** engine with `hl=<language>` and `gl=in`. Autocomplete reflects what real users type, so the suggestions are real questions in real phrasing. The demand signal is the number of suggestions written in the target language, normalised to 0–100 across the dataset.

**2. Supply: what Google returns.**
The top native suggestions, or the seed itself if there are none, are searched with SerpApi's **Google Search** engine (`google_domain=google.co.in`, `gl=in`, `hl=<language>`). For each organic result we record:

- **Language.** Unicode script detection on the title and snippet. Hindi and Marathi share Devanagari, so they are split with marker words (`है/के/में` vs `आहे/आणि/मध्ये`), the Marathi genitive `-च्या` and the letter `ळ`.
- **Authority tier.** official (gov.in, nic.in, WHO …), medical (hospitals, Mayo Clinic …), reference, news, unknown, or user-generated (YouTube, Quora …).
- **People also ask.** Whether Google's related-questions block exists in the language.

**3. Scores.**

| Score | Formula |
|---|---|
| Native share | native results ÷ max(results, 8) |
| Coverage (0–100) | 45% native share + 40% min(trusted native results ÷ 3, 1) + 15% native "People also ask" |
| Gap (0–100) | demand × (100 − coverage) ÷ 100 |

A *trusted* result has authority ≥ 0.8 (official or medical). **English is the control column.** It shows what "well served" looks like for the same topics.

**Limitations.** One snapshot, one location (`gl=in`). Autocomplete volume is a relative proxy, not absolute search counts. Script detection can't tell romanised Hindi from English. The authority list is hand-curated and editable in `bhasha_gap/authority.py`. Seed translations should be checked by native speakers.
