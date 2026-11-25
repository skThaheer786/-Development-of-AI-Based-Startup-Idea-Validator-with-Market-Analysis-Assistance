import re
import time
import threading
from concurrent.futures import ThreadPoolExecutor
import logging
from urllib.parse import urlparse, parse_qs, unquote, quote

import requests

from config import Config
from .evidence import classify_source, registered_domain, USER_AGENT

logger = logging.getLogger(__name__)

_CACHE = {}
_CACHE_TTL = 6 * 3600


class SearchService:
    """
    Real web search only. Provider order:
      1. Tavily (if TAVILY_API_KEY is set)           - free tier available
      2. DuckDuckGo via the `ddgs` package           - free, no key
      3. DuckDuckGo HTML endpoint                    - free, no key
    Wikipedia is available for background summaries (free, no key).

    If nothing can be retrieved, search() returns [] -- results are NEVER simulated.
    `diagnostics` records what happened so the UI can explain gaps honestly.
    """

    TAVILY_ENDPOINT = "https://api.tavily.com/search"
    DDG_HTML_ENDPOINT = "https://html.duckduckgo.com/html/"

    def __init__(self, api_key=None, max_searches=None):
        self.api_key = (api_key if api_key is not None else Config.TAVILY_API_KEY or "").strip()
        self.max_searches = max_searches if max_searches is not None else Config.MAX_SEARCHES_PER_IDEA
        self.searches_used = 0
        self.diagnostics = []
        self._lock = threading.Lock()
        self._hard_failures = 0
        self._provider_fail = {}

    # ------------------------------------------------------------------
    def is_available(self):
        """True when the optional Tavily key is configured."""
        return bool(self.api_key and len(self.api_key) > 8)

    def providers(self):
        names = []
        if self.is_available():
            names.append("Tavily")
        names.extend(["DuckDuckGo", "Wikipedia"])
        return names

    def budget_left(self):
        return max(0, self.max_searches - self.searches_used)

    def test_connection(self):
        """Test Tavily connectivity (Bearer authentication, as per current Tavily docs)."""
        if not self.is_available():
            return False, "No Tavily key set. Free DuckDuckGo + Wikipedia search will be used instead."
        try:
            res = requests.post(
                self.TAVILY_ENDPOINT,
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={"query": "startup market trends", "max_results": 1, "search_depth": "basic"},
                timeout=10,
            )
            if res.status_code == 200:
                return True, "Tavily API connected successfully!"
            if res.status_code in (401, 403):
                return False, "Tavily rejected the API key (401/403)."
            return False, f"Tavily returned HTTP {res.status_code}: {res.text[:120]}"
        except requests.exceptions.RequestException as exc:
            return False, f"Tavily connection error: {exc}"

    # ------------------------------------------------------------------
    @staticmethod
    def _normalize(title, url, snippet, provider):
        info = classify_source(url)
        return {
            "title": (title or "").strip()[:200] or registered_domain(url),
            "url": url,
            "snippet": re.sub(r"\s+", " ", (snippet or "")).strip()[:900],
            "provider": provider,
            "domain": registered_domain(url),
            "tier": info["tier"],
            "source_label": info["label"],
            "reliability": info["reliability"],
            "is_verified": True,  # a genuinely retrieved web result (not simulated)
            "retrieved_at": time.strftime("%Y-%m-%d"),
        }

    def _tavily(self, query, n):
        res = requests.post(
            self.TAVILY_ENDPOINT,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={"query": query, "max_results": n, "search_depth": "basic", "include_answer": False},
            timeout=Config.HTTP_TIMEOUT,
        )
        if res.status_code != 200:
            raise RuntimeError(f"Tavily HTTP {res.status_code}")
        return [self._normalize(r.get("title"), r.get("url"), r.get("content"), "Tavily")
                for r in res.json().get("results", []) if r.get("url")]

    def _ddg_lib(self, query, n):
        try:
            from ddgs import DDGS  # type: ignore
        except ImportError:
            try:
                from duckduckgo_search import DDGS  # type: ignore
            except ImportError:
                raise RuntimeError("ddgs package not installed")
        last = None
        for backend in ("auto", "brave", "bing", "mojeek", "yahoo"):   # different free engines; one is usually reachable
            try:
                rows = DDGS().text(query, max_results=n, backend=backend)
            except TypeError:                                          # older package without backend=
                rows = DDGS().text(query, max_results=n)
            except Exception as exc:
                last = exc
                continue
            res = [self._normalize(r.get("title"), r.get("href") or r.get("url"), r.get("body"), "Free web search")
                   for r in (rows or []) if (r.get("href") or r.get("url"))]
            if res:
                return res
        if last:
            raise last
        return []

    @staticmethod
    def parse_ddg_html(html, n):
        """Parse html.duckduckgo.com result markup. Separate so it can be unit-tested."""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        out = []
        for node in soup.select("div.result"):
            link = node.select_one("a.result__a")
            if not link or not link.get("href"):
                continue
            href = link["href"]
            if "uddg=" in href:
                href = unquote(parse_qs(urlparse(href if href.startswith("http") else "https:" + href).query)
                               .get("uddg", [href])[0])
            if not href.startswith("http"):
                continue
            snip = node.select_one(".result__snippet")
            out.append((link.get_text(" ", strip=True), href, snip.get_text(" ", strip=True) if snip else ""))
            if len(out) >= n:
                break
        return out

    def _ddg_html(self, query, n):
        resp = requests.post(self.DDG_HTML_ENDPOINT, data={"q": query},
                             headers={"User-Agent": USER_AGENT}, timeout=Config.HTTP_TIMEOUT)
        if resp.status_code != 200:
            raise RuntimeError(f"DuckDuckGo HTTP {resp.status_code} (rate limited?)")
        if "anomaly" in resp.text.lower() and "result__a" not in resp.text:
            raise RuntimeError("DuckDuckGo asked for a captcha (rate limited)")
        return [self._normalize(t, u, s, "DuckDuckGo") for t, u, s in self.parse_ddg_html(resp.text, n)]

    # ------------------------------------------------------------------
    def search(self, query, max_results=6):
        """
        Returns a list of real search results (possibly empty). Never simulated.
        """
        query = re.sub(r"\s+", " ", (query or "")).strip()
        if not query:
            return []

        cache_key = (query.lower(), max_results)
        cached = _CACHE.get(cache_key)
        if cached and time.time() - cached[0] < _CACHE_TTL and cached[1]:
            self.diagnostics.append({"query": query, "provider": cached[1][0]["provider"],
                                     "results": len(cached[1]), "error": None, "cached": True})
            return [dict(r) for r in cached[1]]

        if self._hard_failures >= 3:
            self.diagnostics.append({"query": query, "provider": None, "results": 0, "cached": False,
                                     "error": "web search skipped: providers kept failing (network blocked or rate limited)"})
            return []
        if self.budget_left() <= 0:
            self.diagnostics.append({"query": query, "provider": None, "results": 0,
                                     "error": "search budget for this idea exhausted", "cached": False})
            return []
        with self._lock:
            self.searches_used += 1

        providers = []
        if self.is_available():
            providers.append(("Tavily", self._tavily))
        providers.extend([("DuckDuckGo", self._ddg_lib), ("DuckDuckGo", self._ddg_html)])

        errors = []
        for idx, (name, fn) in enumerate(providers):
            pkey = f"{idx}:{name}"
            if self._provider_fail.get(pkey, 0) >= 2:
                errors.append(f"{name}: skipped after repeated failures")
                continue
            try:
                results = fn(query, max_results)
            except Exception as exc:  # network / rate limit / missing package
                errors.append(f"{name}: {str(exc)[:100]}")
                self._provider_fail[pkey] = self._provider_fail.get(pkey, 0) + 1
                logger.warning("Search provider %s failed for '%s': %s", name, query, exc)
                continue
            if results:
                _CACHE[cache_key] = (time.time(), results)
                self.diagnostics.append({"query": query, "provider": name, "results": len(results),
                                         "error": None, "cached": False})
                return [dict(r) for r in results]
            errors.append(f"{name}: no results")

        if errors and not any("no results" in e for e in errors):
            self._hard_failures += 1
        self.diagnostics.append({"query": query, "provider": None, "results": 0,
                                 "error": "; ".join(errors)[:300], "cached": False})
        return []

    def search_many(self, queries, max_results=6, workers=4):
        """Run several queries in parallel; returns all results (order follows the query order)."""
        uniq, seen = [], set()
        for q in queries or []:
            if q and q.lower() not in seen:
                seen.add(q.lower())
                uniq.append(q)
        if Config.QUICK_MODE:
            uniq = uniq[:3]
        if not uniq:
            return []
        with ThreadPoolExecutor(max_workers=min(workers, len(uniq))) as pool:
            batches = list(pool.map(lambda q: self.search(q, max_results), uniq))
        return [r for batch in batches for r in batch]

    def wikipedia_summary(self, term):
        """Free background context. Returns an evidence-style dict or None."""
        term = (term or "").strip()
        if not term:
            return None
        try:
            r = requests.get("https://en.wikipedia.org/w/api.php",
                             params={"action": "query", "list": "search", "srsearch": term,
                                     "srlimit": 1, "format": "json"},
                             headers={"User-Agent": USER_AGENT}, timeout=Config.HTTP_TIMEOUT)
            hits = r.json().get("query", {}).get("search", [])
            if not hits:
                return None
            title = hits[0]["title"]
            s = requests.get(f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(title.replace(' ', '_'))}",
                             headers={"User-Agent": USER_AGENT}, timeout=Config.HTTP_TIMEOUT)
            if s.status_code != 200:
                return None
            data = s.json()
            extract = data.get("extract") or ""
            page = (data.get("content_urls", {}).get("desktop", {}) or {}).get("page") \
                or f"https://en.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}"
            if len(extract) < 40:
                return None
            self.diagnostics.append({"query": f"wikipedia: {term}", "provider": "Wikipedia", "results": 1,
                                     "error": None, "cached": False})
            return self._normalize(title, page, extract, "Wikipedia")
        except Exception as exc:
            self.diagnostics.append({"query": f"wikipedia: {term}", "provider": "Wikipedia", "results": 0,
                                     "error": str(exc)[:100], "cached": False})
            return None

    def summary(self):
        """Compact description of what happened (for the UI / report)."""
        total = len(self.diagnostics)
        ok = [d for d in self.diagnostics if d["results"] > 0]
        failed = [d for d in self.diagnostics if d["results"] == 0]
        return {"queries": total, "with_results": len(ok), "failed": len(failed),
                "providers_used": sorted({d["provider"] for d in ok if d["provider"]}),
                "log": self.diagnostics}
