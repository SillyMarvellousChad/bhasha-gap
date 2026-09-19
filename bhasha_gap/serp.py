"""Thin SerpApi client with a permanent on-disk cache.

The free SerpApi plan has 250 searches a month, so every response is cached
by its parameters. Re-running the pipeline, tuning the scoring, or demoing the
app costs nothing once a query has been fetched.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import requests

SEARCH_URL = "https://serpapi.com/search.json"
ACCOUNT_URL = "https://serpapi.com/account.json"
GL = "in"
GOOGLE_DOMAIN = "google.co.in"

# SerpApi reports an empty SERP as an error. For us that is a measurement
# (zero supply), not a failure.
_EMPTY_RESULT_ERRORS = ("hasn't returned any results",)


class CacheMiss(RuntimeError):
    pass


class SerpApiError(RuntimeError):
    pass


class BudgetExhausted(CacheMiss):
    """The run's credit cap is reached. Treated like a cache miss: stop spending."""


class SerpClient:
    def __init__(
        self,
        api_key: str | None,
        cache_dir: str | Path = "data/cache",
        offline: bool = False,
        max_live_calls: int | None = None,
    ):
        self.api_key = api_key
        self.max_live_calls = max_live_calls
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.offline = offline or not api_key
        self.live_calls = 0
        self.cache_hits = 0

    def _path(self, params: dict) -> Path:
        key = json.dumps(params, sort_keys=True, ensure_ascii=False)
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
        return self.cache_dir / f"{params['engine']}_{params.get('hl', 'xx')}_{digest}.json"

    def is_cached(self, params: dict) -> bool:
        return self._path(params).exists()

    def search(self, params: dict) -> dict:
        path = self._path(params)
        if path.exists():
            self.cache_hits += 1
            return json.loads(path.read_text(encoding="utf-8"))
        if self.offline:
            raise CacheMiss(f"Not cached and running offline: {params}")
        if self.max_live_calls is not None and self.live_calls >= self.max_live_calls:
            raise BudgetExhausted(f"Credit cap of {self.max_live_calls} reached")

        resp = requests.get(SEARCH_URL, params={**params, "api_key": self.api_key}, timeout=90)
        data = resp.json()
        self.live_calls += 1
        error = data.get("error")
        if error and not any(e in error for e in _EMPTY_RESULT_ERRORS):
            raise SerpApiError(f"{error} (params: {params})")

        # Keep the cache small and free of account details.
        data.pop("search_metadata", None)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        return data

    @staticmethod
    def autocomplete_params(q: str, hl: str) -> dict:
        return {"engine": "google_autocomplete", "q": q, "hl": hl, "gl": GL}

    @staticmethod
    def google_params(q: str, hl: str) -> dict:
        return {"engine": "google", "q": q, "hl": hl, "gl": GL, "google_domain": GOOGLE_DOMAIN}

    def autocomplete(self, q: str, hl: str) -> list[str]:
        data = self.search(self.autocomplete_params(q, hl))
        return [s["value"] for s in data.get("suggestions", []) if s.get("value")]

    def google(self, q: str, hl: str) -> dict:
        return self.search(self.google_params(q, hl))

    def searches_left(self) -> int | None:
        """Remaining credits this month. The account endpoint is free to call."""
        if not self.api_key:
            return None
        try:
            data = requests.get(ACCOUNT_URL, params={"api_key": self.api_key}, timeout=30).json()
        except (requests.RequestException, ValueError):
            return None
        return data.get("total_searches_left", data.get("plan_searches_left"))
