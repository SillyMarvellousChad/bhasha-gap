"""Bhasha Gap: measuring India's language information gap with SerpApi."""

LANGUAGE_NAMES = {
    "en": ("English", "English"),
    "hi": ("Hindi", "हिन्दी"),
    "bn": ("Bengali", "বাংলা"),
    "as": ("Assamese", "অসমীয়া"),
    "mr": ("Marathi", "मराठी"),
    "ta": ("Tamil", "தமிழ்"),
    "te": ("Telugu", "తెలుగు"),
    "kn": ("Kannada", "ಕನ್ನಡ"),
    "ml": ("Malayalam", "മലയാളം"),
    "gu": ("Gujarati", "ગુજરાતી"),
    "pa": ("Punjabi", "ਪੰਜਾਬੀ"),
    "or": ("Odia", "ଓଡ଼ିଆ"),
}


def language_label(code: str) -> str:
    english, native = LANGUAGE_NAMES.get(code, (code, code))
    return english if english == native else f"{english} · {native}"
