"""
Quality guard against generic, boilerplate AI text.

An item is "generic" when it matches a known boilerplate phrase, or when it is a long statement
that never mentions anything specific to the submitted idea (its users, features, numbers,
competitors, location, regulations...). Generic items trigger one corrective retry.
"""
import re

BOILERPLATE_PATTERNS = [
    r"\bai[- ]native\b", r"\bbloated\b", r"\blegacy (?:enterprise|incumbent|software|suite)",
    r"\b10x\b", r"\bfrictionless\b", r"\bsecular growth\b", r"\bdouble[- ]digit\b",
    r"\bmanual overhead\b", r"\bseamless(?:ly)? integrat", r"\bcutting[- ]edge\b", r"\bgame[- ]chang",
    r"\bsynerg", r"\bend[- ]to[- ]end automation\b", r"\btime[- ]to[- ]value\b", r"\bzero[- ]friction\b",
    r"\bearly brand recognition\b", r"\blimited (?:early )?(?:capital|funding|resources)\b",
    r"\bcustomer inertia\b", r"\breluctan(?:ce|t) to change\b", r"\brising (?:paid )?(?:customer )?acquisition costs?\b",
    r"\bevolving (?:data )?(?:privacy|regulat)", r"\bunbundling\b", r"\bscalab(?:le|ility) (?:solution|platform)\b",
    r"\bdisruptive\b", r"\brobust (?:and )?scalable\b", r"\bleverag(?:e|ing) (?:the power|ai|technology)\b",
    r"\bin today'?s (?:fast[- ]paced|digital)\b", r"\bunlock(?:s|ing)? (?:the )?(?:full )?potential\b",
    r"\bmeasurable roi\b", r"\bcompetitive landscape is (?:crowded|evolving)\b",
]
_BOILER_RX = [re.compile(p, re.IGNORECASE) for p in BOILERPLATE_PATTERNS]

STOPWORDS = set("""a an the and or of for to in on at by with from into over under about as is are was were be been being this that
these those it its their our your you we they them his her not no yes can could should would will may might must do does did
have has had than then so such via per each any all more most less least very much many few new using use used based
platform app application system solution tool service services software product products startup company business
customers customer users user data ai machine learning model models""".split())

# Tokens too common across all startup ideas to prove specificity
GENERIC_TOKENS = {"market", "growth", "cost", "costs", "revenue", "pricing", "price", "support", "team", "risk",
                  "scale", "feature", "features", "build", "launch", "early", "strong", "high", "low", "key",
                  "digital", "online", "mobile", "cloud", "global", "local", "value", "model", "adoption"}


def tokens(text):
    out = set()
    for w in re.findall(r"[a-zA-Z][a-zA-Z\-']{2,}", (text or "").lower()):
        w = w.strip("-'")
        if w in STOPWORDS or w in GENERIC_TOKENS or len(w) < 4:
            continue
        out.add(_stem(w))
    return out


def _stem(w):
    for suf in ("ing", "ies", "es", "s", "ed", "ly"):
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[: -len(suf)] if suf != "ies" else w[:-3] + "y"
    return w


def build_anchors(*texts, extra_terms=None):
    """Distinctive tokens describing THIS idea (title, solution, audience, competitor names, ...)."""
    anchors = set()
    for t in texts:
        anchors |= tokens(t if isinstance(t, str) else " ".join(map(str, t or [])))
    for term in extra_terms or []:
        anchors |= tokens(term)
    return anchors


def text_of(item):
    """Flatten a str/dict item into the text that must pass the guard."""
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        parts = [str(v) for k, v in item.items()
                 if isinstance(v, (str, int, float)) and k not in ("basis", "severity", "category", "source_ids", "id")]
        return " ".join(parts)
    return str(item)


def is_generic(item, anchors, min_words=7):
    """Returns (flag, reason)."""
    txt = text_of(item).strip()
    if not txt:
        return True, "empty"
    for rx in _BOILER_RX:
        m = rx.search(txt)
        if m:
            return True, f"boilerplate phrase '{m.group(0)}'"
    words = txt.split()
    if len(words) >= min_words and anchors:
        if not (tokens(txt) & anchors):
            return True, "mentions nothing specific to this idea"
    return False, ""


def audit(items, anchors):
    """Returns list of (index, reason) for generic items."""
    flagged = []
    for i, it in enumerate(items or []):
        bad, reason = is_generic(it, anchors)
        if bad:
            flagged.append((i, reason))
    return flagged


def similarity(a, b):
    """Jaccard similarity between two blocks of text (0..1); used to compare ideas."""
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


# ---------------------------------------------------------------------------
# Path helpers so agents can declare which JSON lists must pass the guard
# ---------------------------------------------------------------------------
def get_path(data, path):
    cur = data
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def audit_paths(data, paths, anchors):
    """Returns [(path, index, text, reason)] for every generic item found under the given list paths."""
    flagged = []
    for path in paths:
        items = get_path(data, path)
        if not isinstance(items, list):
            continue
        for idx, reason in audit(items, anchors):
            flagged.append((path, idx, text_of(items[idx])[:140], reason))
    return flagged


def total_items(data, paths):
    n = 0
    for path in paths:
        items = get_path(data, path)
        if isinstance(items, list):
            n += len(items)
    return n


def strip_flagged(data, flagged, min_keep=3):
    """Remove still-generic items when the list stays healthy (>= min_keep left). Returns removed count."""
    by_path = {}
    for path, idx, _, _ in flagged:
        by_path.setdefault(path, set()).add(idx)
    removed = 0
    for path, idxs in by_path.items():
        items = get_path(data, path)
        if not isinstance(items, list):
            continue
        if len(items) - len(idxs) >= min_keep:
            keep = [it for i, it in enumerate(items) if i not in idxs]
            removed += len(items) - len(keep)
            items[:] = keep
    return removed
