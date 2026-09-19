"""Source-authority tiers for result domains.

The question Bhasha Gap asks is not "are there results in my language?" but
"are there *trustworthy* results in my language?". Each result's domain gets a
tier and a weight. The lists are intentionally transparent and easy to extend.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

# Suffixes that mark government, intergovernmental, or academic sites.
OFFICIAL_SUFFIXES = (".gov.in", ".nic.in", ".gov", ".int", ".ac.in", ".edu", ".edu.in", ".res.in")

TIERS: dict[str, tuple[float, set[str]]] = {
    "official": (1.0, {
        "who.int", "unicef.org", "icmr.gov.in", "mohfw.gov.in", "nhp.gov.in",
        "aiims.edu", "nih.gov", "cdc.gov", "medlineplus.gov", "nhs.uk",
    }),
    "medical": (0.8, {
        "mayoclinic.org", "clevelandclinic.org", "webmd.com", "healthline.com",
        "msdmanuals.com", "medicalnewstoday.com", "hopkinsmedicine.org",
        "apollohospitals.com", "apollo247.com", "maxhealthcare.in",
        "fortishealthcare.com", "manipalhospitals.com", "narayanahealth.org",
        "medanta.org", "practo.com", "1mg.com", "pharmeasy.in", "netmeds.com",
        "myupchar.com", "heart.org", "sciencedirect.com", "thelancet.com",
        "bmj.com", "nature.com", "lalpathlabs.com", "apolloclinic.com",
        "relainstitute.com", "medicoverhospitals.in", "metropolisindia.com",
    }),
    "reference": (0.6, {"wikipedia.org", "britannica.com", "vikaspedia.in"}),
    "news": (0.5, {
        "bbc.com", "bbc.co.uk", "thehindu.com", "indianexpress.com", "ndtv.com",
        "aajtak.in", "amarujala.com", "jagran.com", "bhaskar.com",
        "livehindustan.com", "indiatimes.com", "hindustantimes.com",
        "abplive.com", "india.com", "news18.com", "lokmat.com", "loksatta.com",
        "esakal.com", "anandabazar.com", "eisamay.com", "dinamalar.com",
        "dailythanthi.com", "vikatan.com", "dinamani.com", "eenadu.net",
        "sakshi.com", "andhrajyothy.com", "tv9telugu.com", "tv9hindi.com",
        "tv9marathi.com", "tv9bangla.com", "oneindia.com", "prothomalo.com",
        "sangbadpratidin.in", "puthiyathalaimurai.com",
        "zeenews.com", "patrika.com", "prabhatkhabar.com", "etvbharat.com",
        "samayam.com", "ntnews.com", "hindutamil.in", "bartamanpatrika.com",
    }),
    "ugc": (0.2, {
        "youtube.com", "facebook.com", "instagram.com", "quora.com",
        "reddit.com", "sharechat.com", "pinterest.com", "twitter.com", "x.com",
        "linkedin.com", "blogspot.com", "wordpress.com", "medium.com",
        "justdial.com", "moj4.com", "kooapp.com", "scribd.com", "slideshare.net",
    }),
}

UNKNOWN_WEIGHT = 0.35
# Google Translate proxies of (usually English) pages. They are readable, but
# nobody has checked the medical accuracy of the translation.
MACHINE_TRANSLATED = ("machine_translated", 0.5)
# Hospital sites (carehospitals.com, yashodahospitals.com …) are too many to list.
_HOSPITAL_KEYWORDS = ("hospital",)


def domain_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def unwrap_translation(url: str) -> str | None:
    """Original URL if `url` is a Google Translate proxy, else None."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host == "translate.google.com":
        return parse_qs(parsed.query).get("u", [None])[0]
    if host.endswith(".translate.goog"):
        # www-mayoclinic-org.translate.goog -> www.mayoclinic.org ("--" encodes "-")
        label = host.removesuffix(".translate.goog")
        original = "-".join(part.replace("-", ".") for part in label.split("--"))
        return parsed._replace(netloc=original, query="").geturl()
    return None


def _matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def classify(url: str) -> tuple[str, float]:
    """Return (tier, weight) for a result URL."""
    if unwrap_translation(url):
        return MACHINE_TRANSLATED
    host = domain_of(url)
    if not host:
        return "unknown", UNKNOWN_WEIGHT
    # Named domains first, so e.g. medlineplus.gov lands in "official" by name.
    for tier, (weight, domains) in TIERS.items():
        if any(_matches(host, d) for d in domains):
            return tier, weight
    if host.endswith(OFFICIAL_SUFFIXES):
        return "official", TIERS["official"][0]
    if any(k in host for k in _HOSPITAL_KEYWORDS):
        return "medical", TIERS["medical"][0]
    return "unknown", UNKNOWN_WEIGHT
