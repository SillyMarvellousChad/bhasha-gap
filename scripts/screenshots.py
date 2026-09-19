"""Capture dashboard screenshots for the README and demo (dev tool).

Needs the app running (streamlit run app.py) and `pip install playwright`.
Uses the locally installed Chrome, so no browser download is needed.

    python scripts/screenshots.py
"""

import os
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = os.getenv("BHASHA_URL", "http://localhost:8501")
OUT = Path("docs/screenshots")
SECTIONS = {
    "1b_by_the_numbers": "What the search data shows",
    "1c_real_search": "What a reader actually sees",
    "1d_scorecard": "Which languages Google serves well",
    "1e_method": "How Bhasha Gap measures the gap",
}
TABS = {
    "2_topic_map": "Topic map",
    "3_check_a_question": "Check a question",
    "4_sources": "Sources",
    "5_search_detail": "Search detail",
    "6_write_next": "What to write next",
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(viewport={"width": 1400, "height": 900}, device_scale_factor=1.5)
        page.goto(URL)
        page.locator(".masthead").wait_for(timeout=30_000)
        page.wait_for_timeout(1500)
        page.screenshot(path=OUT / "1_overview.png")
        for name, heading in SECTIONS.items():
            page.locator(".section-title", has_text=heading).evaluate("el => el.scrollIntoView({block: 'start'})")
            page.wait_for_timeout(500)
            page.screenshot(path=OUT / f"{name}.png")

        tablist = page.get_by_role("tablist")
        for name, tab in TABS.items():
            page.get_by_role("tab", name=tab).click()
            page.wait_for_timeout(2000)
            tablist.evaluate("el => el.scrollIntoView({block: 'start'})")
            page.wait_for_timeout(500)
            page.screenshot(path=OUT / f"{name}.png")
        browser.close()
    print(f"Saved screenshots to {OUT}/")


if __name__ == "__main__":
    main()
