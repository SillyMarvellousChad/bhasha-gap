### How Bhasha Gap measures the gap

Bhasha Gap uses the search results page as a **measurement instrument**, not as content to summarise. No LLM is involved. Every number traces back to a SerpApi response.

**1. Demand: what people actually ask.**
For each topic, a native-language seed term (for example `मधुमेह`, `நீரிழிவு`) is sent to SerpApi's **Google Autocomplete** engine with `hl=<language>` and `gl=in`. Autocomplete reflects what real users type, so the suggestions are real questions in real phrasing. The demand signal is the number of suggestions written in the target language, normalised to 0–100 across the dataset.

Two kinds of suggestion are never used as the question to measure:
- **Translation requests** like "fever meaning in hindi", "बुखार in english" or "టీకా అర్థం" ("vaccine meaning"). The word for *meaning* is recognised in all 9 languages. In India these are often the *top* English suggestions, and they count as **hidden demand** for Indian-language content.
- **Off-topic suggestions.** In low-resource languages, Autocomplete sometimes returns unrelated words, such as Odia ସ୍ବଭାବ ("nature") for dengue, or Punjabi ਤਬੀਲਿਸੀ ("Tbilisi") for TB. A suggestion counts only if it contains the seed or its first word is a close spelling of it (similarity ≥ 0.6). When nothing qualifies, the seed itself is searched. A language where most topics get no related suggestion is reported as **Autocomplete is silent**.

**2. Supply: what Google returns.**
The top native suggestions, or the seed itself if there are none, are searched with SerpApi's **Google Search** engine (`google_domain=google.co.in`, `gl=in`, `hl=<language>`). For each organic result we record:

- **Language.** Unicode script detection on the title and snippet. Two scripts are shared:
  - **Devanagari** (Hindi and Marathi) is split with marker words (`है/के/में` vs `आहे/आणि/मध्ये`), Marathi postpositions glued to nouns (`-च्या`, `-साठी`, `-मध्ये`) and the letter `ळ`.
  - **Bengali script** (Bengali and Assamese) is split by how *ra* is written: Assamese uses `ৰ`/`ৱ`, Bengali uses `র`.
- **Authority tier.** official (gov.in, nic.in, WHO …), medical (hospitals, Mayo Clinic …), reference, news, unknown, or user-generated (YouTube, Quora …).
- **Machine translation.** Google often fills Indian-language results with Google Translate proxies of English pages. These are tagged `machine_translated`, attributed to the original site, and count as half a native result. They are never counted as trusted, because nobody has reviewed the translation.
- **People also ask.** Whether Google's related-questions block exists in the language.

**3. Scores.**

The headline measure is **reliable answers**: the share of top results that are (a) written in the reader's language, (b) from an official or medical source (authority ≥ 0.8), and (c) not a Google Translate copy. It is computed per result, so every percentage on the page (scorecard, findings, topic map) uses the same denominator. A checked question is *Well served* at 50% reliable answers or more, *Partly served* at 25–49%, and *Poorly served* below 25%.


| Score | Formula |
|---|---|
| Native share | (native results + ½ × machine-translated results) ÷ max(results, 8) |
| Coverage (0–100) | 45% native share + 40% min(trusted native results ÷ 3, 1) + 15% native "People also ask" |
| Gap (0–100) | demand × (100 − coverage) ÷ 100 |

A *trusted* result has authority ≥ 0.8 (official or medical), and it is not a machine translation.

**Hidden demand.** English Autocomplete often returns Hindi typed in Roman script ("diabetes ke lakshan"). These suggestions are flagged as romanised. They are people searching in Hindi who have given up on the script. **English is the control column.** It shows what "well served" looks like for the same topics.

**Check a question.** The dashboard's question box runs the same two calls for any single question: Autocomplete, then Google Search on that exact question. The language is auto-detected, and it can be overridden when a script is shared (Devanagari for Hindi/Marathi, Bengali script for Bengali/Assamese).

**Limitations.** A language with a silent Autocomplete gets low measured demand, so its *gap* score understates the problem. Read it together with the coverage view. One snapshot, one location (`gl=in`). Autocomplete volume is a relative proxy, not absolute search counts. Script detection can't tell romanised Hindi from English. The authority list is hand-curated and editable in `bhasha_gap/authority.py`. Seed translations should be checked by native speakers.
