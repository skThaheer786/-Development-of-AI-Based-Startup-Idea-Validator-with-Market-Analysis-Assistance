"""
Evidence helpers used by the research agents.

Nothing in this module invents data: every figure returned is parsed from text that was
actually retrieved from a web page / search snippet, and always carries its source id.
"""
import re
import datetime
import socket
import ipaddress
import logging
from urllib.parse import urlparse, urljoin

import requests

from config import Config

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; StartupIdeaValidatorBot/1.0; academic research tool)"

# ---------------------------------------------------------------------------
# Domains
# ---------------------------------------------------------------------------
_TWO_LEVEL_TLDS = {"co.uk", "co.in", "com.au", "co.nz", "co.za", "com.sg", "com.br", "co.jp", "org.uk",
                   "gov.uk", "ac.uk", "gov.in", "ac.in", "org.in", "net.in", "com.mx", "com.cn"}


def registered_domain(url_or_host):
    """'https://www.shop.example.co.uk/x' -> 'example.co.uk'"""
    if not url_or_host:
        return ""
    host = urlparse(url_or_host if "//" in url_or_host else "//" + url_or_host).hostname or ""
    host = host.lower().strip(".")
    if host.startswith("www."):
        host = host[4:]
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    last_two = ".".join(parts[-2:])
    if last_two in _TWO_LEVEL_TLDS and len(parts) >= 3:
        return ".".join(parts[-3:])
    return last_two


# Sites that *describe* companies but are not themselves competitors
NON_COMPANY_DOMAINS = {
    "g2.com", "capterra.com", "getapp.com", "softwareadvice.com", "trustradius.com", "sourceforge.net",
    "producthunt.com", "crunchbase.com", "linkedin.com", "facebook.com", "twitter.com", "x.com",
    "instagram.com", "youtube.com", "reddit.com", "quora.com", "medium.com", "wikipedia.org",
    "techcrunch.com", "forbes.com", "pitchbook.com", "tracxn.com", "cbinsights.com", "owler.com",
    "zoominfo.com", "glassdoor.com", "indeed.com", "play.google.com", "apps.apple.com", "github.com",
    "substack.com", "pinterest.com", "bloomberg.com", "reuters.com", "yourstory.com", "inc42.com",
    "entrackr.com", "startupindia.gov.in", "ycombinator.com", "angel.co", "wellfound.com", "slashdot.org",
    "alternativeto.net", "saashub.com", "stackshare.io", "gartner.com", "statista.com",
    "grandviewresearch.com", "marketsandmarkets.com", "mordorintelligence.com", "fortunebusinessinsights.com",
    "researchandmarkets.com", "precedenceresearch.com", "alliedmarketresearch.com", "imarcgroup.com",
}

_GOV_SUFFIXES = (".gov", ".gov.in", ".gov.uk", ".gov.au", ".edu", ".ac.in", ".ac.uk", ".edu.au", ".nic.in")
_INTERGOV = {"worldbank.org", "un.org", "fao.org", "who.int", "oecd.org", "imf.org", "europa.eu", "wto.org",
             "unep.org", "unesco.org", "itu.int", "ilo.org", "ifad.org", "wri.org", "unicef.org"}
_RESEARCH = {"grandviewresearch.com", "marketsandmarkets.com", "mordorintelligence.com", "statista.com",
             "fortunebusinessinsights.com", "researchandmarkets.com", "precedenceresearch.com",
             "alliedmarketresearch.com", "imarcgroup.com", "gartner.com", "mckinsey.com", "bcg.com",
             "deloitte.com", "pwc.com", "ey.com", "kpmg.com", "forrester.com", "idc.com", "ibisworld.com",
             "nasscom.in", "bain.com", "accenture.com", "cbinsights.com", "pitchbook.com", "tracxn.com"}
_NEWS = {"reuters.com", "bloomberg.com", "forbes.com", "techcrunch.com", "economictimes.indiatimes.com",
         "livemint.com", "thehindu.com", "businessinsider.com", "wsj.com", "ft.com", "bbc.com", "cnbc.com",
         "yourstory.com", "inc42.com", "entrackr.com", "business-standard.com", "theverge.com", "wired.com",
         "indianexpress.com", "hindustantimes.com", "nature.com", "sciencedirect.com", "springer.com",
         "ieee.org", "mit.edu", "hbr.org"}


def is_non_company_site(url):
    return registered_domain(url) in NON_COMPANY_DOMAINS


def classify_source(url):
    """Returns {'tier','label','reliability'} for a URL. Reliability is a heuristic about the *publisher*."""
    host = (urlparse(url).hostname or "").lower()
    dom = registered_domain(url)
    if dom in _INTERGOV or host.endswith(_GOV_SUFFIXES) or any(host.endswith(s) for s in _GOV_SUFFIXES):
        return {"tier": "government", "label": "Government / institution", "reliability": "High"}
    if dom == "wikipedia.org":
        return {"tier": "reference", "label": "Encyclopedia", "reliability": "Medium"}
    if dom in _RESEARCH:
        return {"tier": "research", "label": "Research / consulting publisher", "reliability": "Medium"}
    if dom in _NEWS:
        return {"tier": "news", "label": "News / journal", "reliability": "Medium"}
    if dom in {"reddit.com", "quora.com", "medium.com", "substack.com", "linkedin.com", "facebook.com"}:
        return {"tier": "community", "label": "Community / opinion", "reliability": "Low"}
    return {"tier": "other", "label": "Web page", "reliability": "Unrated"}


# ---------------------------------------------------------------------------
# Figure extraction (market size / CAGR) from retrieved text
# ---------------------------------------------------------------------------
_UNIT_MULT = {
    "trillion": 1e12, "tn": 1e12, "billion": 1e9, "bn": 1e9, "b": 1e9, "million": 1e6, "mn": 1e6, "m": 1e6,
    "thousand": 1e3, "k": 1e3, "crore": 1e7, "cr": 1e7, "lakh": 1e5,
}
_CUR_NORMAL = {"usd": "USD", "us$": "USD", "$": "USD", "dollars": "USD", "us dollars": "USD", "inr": "INR",
               "rs": "INR", "rs.": "INR", "₹": "INR", "eur": "EUR", "€": "EUR", "gbp": "GBP", "£": "GBP"}

_MONEY_PREFIX = re.compile(
    r"(?P<cur>USD|US\$|\$|INR|Rs\.?|₹|EUR|€|GBP|£)\s?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"\s?(?P<unit>trillion|billion|million|thousand|crore|lakh|bn|mn|tn|cr\b|[BMK]\b)?",
    re.IGNORECASE)
_MONEY_SUFFIX = re.compile(
    r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s?(?P<unit>trillion|billion|million|crore|lakh)\s?"
    r"(?P<cur>USD|US dollars|dollars|INR|rupees|EUR|euros|GBP)",
    re.IGNORECASE)
_CAGR_A = re.compile(
    r"(?:CAGR|compound annual growth rate|annual growth rate|growing at)[^.%\d]{0,70}?(?P<pct>\d{1,2}(?:\.\d+)?)\s?%",
    re.IGNORECASE)
_CAGR_B = re.compile(r"(?P<pct>\d{1,2}(?:\.\d+)?)\s?%\s?(?:CAGR|compound annual growth)", re.IGNORECASE)
_YEAR = re.compile(r"\b(20[1-4]\d)\b")
_FORECAST_WORDS = re.compile(r"\b(reach|projected|expected|forecast|anticipated|will|by 20\d\d|to grow)\b", re.IGNORECASE)
_MARKET_WORDS = re.compile(r"\b(market|industry|sector|segment|spending|revenue)\b", re.IGNORECASE)
_CUR_SUFFIX_NORMAL = {"usd": "USD", "us dollars": "USD", "dollars": "USD", "inr": "INR", "rupees": "INR",
                      "eur": "EUR", "euros": "EUR", "gbp": "GBP"}


def _sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text or "") if s.strip()]


def _relevant(text, tokens):
    if not tokens:
        return True
    low = text.lower()
    return any(t in low for t in tokens)


def _to_base(num_s, unit):
    try:
        num = float(num_s.replace(",", ""))
    except ValueError:
        return None
    if unit:
        mult = _UNIT_MULT.get(unit.lower().strip("."))
        if mult:
            num *= mult
    return num


def _year_and_forecast(sent, start, end):
    """
    The year a money amount refers to, and whether it is a forecast, judged from the words around THAT amount
    (not the whole sentence): "valued at $40B in 2025 ... to $68B by 2035" gives 2025/base and 2035/forecast.
    """
    near = [(m.start(), int(m.group(1))) for m in _YEAR.finditer(sent)]
    year = None
    if near:
        # closest year token to the amount; a later year wins ties ("by 2035")
        year = min(near, key=lambda p: (min(abs(p[0] - start), abs(p[0] - end)), -p[1]))[1]
    before = sent[max(0, start - 70):start]
    after = sent[end:end + 25]
    forecast = bool(_FORECAST_WORDS.search(before)) or bool(re.match(r"\s*(?:by|in)\s+20\d\d", after) and year and year > datetime.date.today().year)
    if year and year > datetime.date.today().year:
        forecast = True
    return year, forecast


def extract_figures(text, source_id, title="", relevance_tokens=None):
    """
    Parse market-size and CAGR claims out of retrieved text.
    Returns list of dicts: {kind, value, currency?, pct?, year, forecast, sentence, source_id}
    `relevance_tokens`: lowercase tokens; a sentence must mention one (or the title must) to count.
    """
    figures, seen = [], set()
    for sent in _sentences(text):
        if len(sent) < 20:
            continue
        if not (_relevant(sent, relevance_tokens) or _relevant(title, relevance_tokens)):
            continue
        short = sent if len(sent) <= 280 else sent[:277] + "..."
        years = [int(y) for y in _YEAR.findall(sent)]
        forecast = bool(_FORECAST_WORDS.search(sent))

        # CAGR
        for rx in (_CAGR_A, _CAGR_B):
            for m in rx.finditer(sent):
                pct = float(m.group("pct"))
                if 0 < pct <= 60:
                    key = ("cagr", pct, source_id)
                    if key not in seen:
                        seen.add(key)
                        figures.append({"kind": "cagr", "pct": pct, "years": years, "sentence": short,
                                        "source_id": source_id})

        # Market size (needs market wording in the same sentence)
        if _MARKET_WORDS.search(sent):
            candidates = []
            for m in _MONEY_PREFIX.finditer(sent):
                cur = _CUR_NORMAL.get(m.group("cur").lower(), "USD")
                value = _to_base(m.group("num"), m.group("unit"))
                if value:
                    candidates.append((cur, value, bool(m.group("unit")), m.start(), m.end()))
            for m in _MONEY_SUFFIX.finditer(sent):
                cur = _CUR_SUFFIX_NORMAL.get(m.group("cur").lower(), "USD")
                value = _to_base(m.group("num"), m.group("unit"))
                if value:
                    candidates.append((cur, value, True, m.start(), m.end()))
            for cur, value, had_unit, c_start, c_end in candidates:
                if not had_unit and value < 1e6:
                    continue  # a bare "$29" is a price, not a market size
                if value < 5e5:
                    continue
                key = ("size", round(value), source_id)
                if key in seen:
                    continue
                seen.add(key)
                year, is_forecast = _year_and_forecast(sent, c_start, c_end)
                figures.append({"kind": "market_size", "value": value, "currency": cur, "years": years, "year": year,
                                "forecast": is_forecast, "sentence": short, "source_id": source_id})
    return figures


def format_money(value, currency="USD"):
    """Human friendly money string. 1_250_000_000 -> '$1.25 B'"""
    if value is None:
        return "N/A"
    symbol = {"USD": "$", "INR": "₹", "EUR": "€", "GBP": "£"}.get(currency, currency + " ")
    absval = abs(value)
    if absval >= 1e12:
        s = f"{value / 1e12:.2f} T"
    elif absval >= 1e9:
        s = f"{value / 1e9:.2f} B"
    elif absval >= 1e6:
        s = f"{value / 1e6:.1f} M"
    elif absval >= 1e5:
        s = f"{value / 1e3:.0f} K"
    else:
        s = f"{value:,.0f}"
    return f"{symbol}{s}"


# ---------------------------------------------------------------------------
# Safe page fetching (for verifying competitor websites / pricing)
# ---------------------------------------------------------------------------
def is_safe_url(url):
    """Block non-http(s) URLs and anything resolving to private / loopback addresses (SSRF guard)."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return False
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return False
        return True
    except Exception:
        return False


_PRICE_RX = re.compile(
    r"(?:(?:US\$|USD|\$|₹|Rs\.?|INR|€|£)\s?\d[\d,]*(?:\.\d{1,2})?\s?(?:/|per\s)?\s?"
    r"(?:mo(?:nth)?|yr|year|user|seat|month|annum|kg|order|student|farm|acre)?)",
    re.IGNORECASE)


def extract_prices(text, limit=6):
    """Pull literal price strings (e.g. '$29/month') out of page text. Never infers prices."""
    found, seen = [], set()
    for m in _PRICE_RX.finditer(text or ""):
        s = re.sub(r"\s+", " ", m.group(0)).strip()
        digits = re.sub(r"[^\d.]", "", s)
        if not digits or len(s) < 2 or s.lower() in seen:
            continue
        seen.add(s.lower())
        # context: keep a little of the surrounding text so the user can judge
        found.append(s)
        if len(found) >= limit:
            break
    return found


def _visible_text(soup, limit=2500):
    for tag in soup(["script", "style", "noscript", "svg", "header", "footer", "nav", "form"]):
        tag.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    return text[:limit]


def fetch_page(url, timeout=None, max_bytes=600_000):
    """
    Fetch an HTML page and return a compact summary:
    {ok, status, final_url, title, description, headings, text, pricing_url, error}
    """
    result = {"ok": False, "status": None, "final_url": url, "title": "", "description": "",
              "headings": [], "text": "", "pricing_url": "", "error": ""}
    if not is_safe_url(url):
        result["error"] = "blocked or unresolvable URL"
        return result
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        result["error"] = "beautifulsoup4 is not installed"
        return result

    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8"},
                            timeout=timeout or Config.HTTP_TIMEOUT, allow_redirects=True, stream=True)
        result["status"] = resp.status_code
        result["final_url"] = resp.url
        ctype = resp.headers.get("content-type", "")
        if resp.status_code >= 400:
            result["error"] = f"HTTP {resp.status_code}"
            return result
        if "html" not in ctype.lower() and ctype:
            result["error"] = f"not an HTML page ({ctype[:40]})"
            return result
        raw = b""
        for chunk in resp.iter_content(16384):
            raw += chunk
            if len(raw) > max_bytes:
                break
        soup = BeautifulSoup(raw, "lxml") if _has_lxml() else BeautifulSoup(raw, "html.parser")
    except requests.exceptions.RequestException as exc:
        result["error"] = f"{type(exc).__name__}"
        return result

    result["ok"] = True
    result["title"] = (soup.title.string or "").strip()[:160] if soup.title and soup.title.string else ""
    meta = soup.find("meta", attrs={"name": re.compile("^description$", re.I)}) or \
        soup.find("meta", attrs={"property": re.compile("^og:description$", re.I)})
    if meta and meta.get("content"):
        result["description"] = meta["content"].strip()[:320]
    result["headings"] = [h.get_text(" ", strip=True)[:120] for h in soup.find_all(["h1", "h2"])[:8]
                          if h.get_text(strip=True)]
    for a in soup.find_all("a", href=True):
        label = (a.get_text(" ", strip=True) or "").lower()
        href = a["href"].lower()
        if "pricing" in label or "plans" in label or "/pricing" in href or "/plans" in href:
            result["pricing_url"] = urljoin(result["final_url"], a["href"])
            break
    result["text"] = _visible_text(soup)
    return result


def _has_lxml():
    try:
        import lxml  # noqa: F401
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# Evidence book: stable ids (S1, S2 ...) shared between searches, prompts and the UI
# ---------------------------------------------------------------------------
class EvidenceBook:
    """Collects retrieved sources, de-duplicates by URL and hands out citation ids."""

    def __init__(self, prefix="S"):
        self.prefix = prefix
        import threading
        self._lock = threading.Lock()
        self.items = []      # list of dicts (each has 'id')
        self._by_url = {}

    def add(self, results):
        with self._lock:
            return self._add(results)

    def _add(self, results):
        """Add search results; returns the list of stored items (with ids)."""
        stored, seen_ids = [], set()
        for r in results or []:
            url = (r.get("url") or "").split("#")[0].rstrip("/")
            if not url:
                continue
            if url in self._by_url:
                existing = self._by_url[url]
                if existing["id"] not in seen_ids:
                    seen_ids.add(existing["id"])
                    stored.append(existing)
                continue
            item = dict(r)
            item["id"] = f"{self.prefix}{len(self.items) + 1}"
            self.items.append(item)
            self._by_url[url] = item
            seen_ids.add(item["id"])
            stored.append(item)
        return stored

    def get(self, source_id):
        for it in self.items:
            if it["id"] == source_id:
                return it
        return None

    def valid_ids(self, ids):
        known = {it["id"] for it in self.items}
        return [i for i in (ids or []) if i in known]

    def for_prompt(self, items=None, snippet_chars=380, limit=14):
        """Compact text block the LLM must cite from."""
        rows = []
        for it in (items if items is not None else self.items)[:limit]:
            rows.append(f"[{it['id']}] {it['title'][:110]} | {it['domain']} | {it['snippet'][:snippet_chars]}")
        return "\n".join(rows) if rows else "(no web evidence could be retrieved)"

    def public(self, ids=None):
        """Serializable list for storing in results / templates."""
        wanted = set(ids) if ids is not None else None
        out = []
        for it in self.items:
            if wanted is not None and it["id"] not in wanted:
                continue
            out.append({k: it.get(k) for k in ("id", "title", "url", "snippet", "provider", "domain", "tier",
                                              "source_label", "reliability", "is_verified", "retrieved_at")})
        return out
