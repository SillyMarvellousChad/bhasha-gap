"""Capture dashboard screenshots for the README and demo (dev tool).

Needs the app running (streamlit run app.py) and `pip install playwright`.
Uses the locally installed Chrome, so no browser download is needed.

    python scripts/screenshots.py
"""

from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "http://localhost:8501"
OUT = Path("docs/screenshots")
SECTIONS = {
    "1b_real_search": "A real search",
    "1c_leaderboard": "Language leaderboard",
    "1d_findings": "What the search data shows",
}
TABS = {
    "2_gap_map": ("Gap map", "Supply: coverage score"),
    "3_check_a_question": ("Check a question", None),
    "4_languages_sources": ("Languages & sources", None),
    "5_drill_down": ("Drill down", None),
    "6_write_next": ("Write next", None),
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(viewport={"width": 1400, "height": 900}, device_scale_factor=1.5)
        page.goto(URL)
        page.get_by_text("What the search data shows").wait_for(timeout=30_000)
        page.wait_for_timeout(1500)
        page.screenshot(path=OUT / "1_overview.png")
        for name, heading in SECTIONS.items():
            page.locator(".section-title", has_text=heading).evaluate("el => el.scrollIntoView({block: 'start'})")
            page.wait_for_timeout(500)
            page.screenshot(path=OUT / f"{name}.png")

        tablist = page.get_by_role("tablist")
        for name, (tab, radio) in TABS.items():
            page.get_by_role("tab", name=tab).click()
            if radio:
                page.get_by_text(radio, exact=True).click()
            page.wait_for_timeout(2000)
            tablist.evaluate("el => el.scrollIntoView({block: 'start'})")
            page.wait_for_timeout(500)
            page.screenshot(path=OUT / f"{name}.png")
        browser.close()
    print(f"Saved screenshots to {OUT}/")


if __name__ == "__main__":
    main()
