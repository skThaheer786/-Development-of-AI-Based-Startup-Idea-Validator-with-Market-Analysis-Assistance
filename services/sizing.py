"""
Transparent market sizing (TAM / SAM / SOM) and CAGR resolution.

Two explainable approaches are supported and the most complete one is used:
  * bottom-up : customers x annual revenue per customer (TAM), x reachable share (SAM), x winnable share (SOM)
  * top-down  : a market size PUBLISHED in a retrieved source (TAM), x the share this product can serve (SAM), x winnable share (SOM)

The LLM only proposes *assumptions* (each labelled 'sourced' or 'ai_assumption'). All arithmetic is done here, so the
numbers are reproducible and the formula can be shown. Each level is calculated on its own: one missing optional input no
longer blanks the other levels. "Insufficient data" is returned only for a level that genuinely cannot be calculated.
CAGR is only reported when a retrieved source actually states one.
"""
import re
import math
import datetime

from .evidence import format_money, classify_source

BASIS_SOURCED = "sourced"
BASIS_ASSUMPTION = "ai_assumption"
INSUFFICIENT = "Insufficient data"

_UNITS = {"trillion": 1e12, "tn": 1e12, "billion": 1e9, "bn": 1e9, "b": 1e9, "million": 1e6, "mn": 1e6, "mm": 1e6, "m": 1e6,
          "thousand": 1e3, "k": 1e3, "lakh": 1e5, "lakhs": 1e5, "crore": 1e7, "crores": 1e7, "cr": 1e7}
_NUM_RX = re.compile(r"(\d+(?:\.\d+)?)\s*(trillion|tn|billion|bn|million|mn|mm|thousand|lakhs?|crores?|cr|[kmb])?(?![a-z])")

# Models often rename fields; accept the common variants
ALIASES = {
    "unit_count": ["number_of_customers", "customer_count", "total_customers", "num_customers", "units", "customers", "potential_customers"],
    "annual_revenue_per_unit": ["annual_revenue_per_customer", "revenue_per_customer", "arpu", "annual_arpu", "revenue_per_unit",
                                "annual_spend_per_unit", "annual_spend_per_customer", "price_per_customer_per_year"],
    "serviceable_share": ["sam_share", "serviceable_percentage", "reachable_share", "serviceable_fraction", "sam_percentage"],
    "obtainable_share": ["som_share", "obtainable_percentage", "winnable_share", "obtainable_fraction", "som_percentage", "market_share_year3"],
    "topdown_serviceable_share": ["top_down_serviceable_share", "topdown_sam_share", "serviceable_share_of_published_market"],
}
_VALUE_KEYS = ("value", "estimate", "base", "mid", "midpoint", "amount", "number", "count", "expected", "point", "best")
_LOW_KEYS = ("low", "min", "lower", "conservative")
_HIGH_KEYS = ("high", "max", "upper", "optimistic")


def parse_number(x):
    """
    Lenient numeric parser for model output. Returns (value|None, had_percent_sign).
    Accepts 60000, "60,000", "$1,500", "20%", "1.2 million", "about 60 thousand", "50-70 thousand" (midpoint).
    """
    if x is None or isinstance(x, bool):
        return None, False
    if isinstance(x, (int, float)):
        return (float(x), False) if math.isfinite(x) else (None, False)
    if not isinstance(x, str):
        return None, False
    text = x.strip().lower().replace(",", "")
    if not text:
        return None, False
    pct = "%" in text or "percent" in text
    hits = list(_NUM_RX.finditer(text))
    vals = []
    for m in hits:
        try:
            n = float(m.group(1))
        except ValueError:
            continue
        vals.append((n, (m.group(2) or "").lower(), m.start(), m.end()))
    # drop 4-digit years when other numbers are present ("2025 estimate: 60000")
    if len(vals) > 1:
        no_year = [v for v in vals if not (1900 <= v[0] <= 2100 and not v[1])]
        vals = no_year or vals
    if not vals:
        return None, pct
    first = vals[0]
    if len(vals) >= 2 and re.search(r"(-|–|—|\bto\b)", text[first[3]:vals[1][2]]):      # a range -> midpoint
        unit_hi = vals[1][1] or first[1]
        lo = first[0] * _UNITS.get(first[1] or unit_hi, 1)
        hi = vals[1][0] * _UNITS.get(unit_hi, 1)
        return (lo + hi) / 2, pct
    return first[0] * _UNITS.get(first[1], 1), pct


def _field(container, key):
    """Value of `key` in a dict, tolerating alias names and different capitalisation/underscores."""
    if not isinstance(container, dict):
        return None
    norm = {re.sub(r"[^a-z]", "", str(k).lower()): v for k, v in container.items()}
    for name in [key] + ALIASES.get(key, []):
        nk = re.sub(r"[^a-z]", "", name.lower())
        if nk in norm and norm[nk] is not None:
            return norm[nk]
    return None


def _first(d, keys):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def _clean_assumption(raw, key, label, kind, valid_source_ids):
    """
    Validate one assumption (dict OR bare scalar, numbers OR numeric text). Returns (assumption|None, notes).
    A missing/unusable assumption returns (None, [reason]) and only blocks the levels that depend on it.
    """
    notes = []
    if raw is None:
        return None, [f"'{label}' was not provided"]
    box = raw if isinstance(raw, dict) else {"value": raw}
    v, v_pct = parse_number(_first(box, _VALUE_KEYS))
    lo, lo_pct = parse_number(_first(box, _LOW_KEYS))
    hi, hi_pct = parse_number(_first(box, _HIGH_KEYS))
    if v is None and lo and hi and lo > 0 and hi >= lo:
        v = (lo + hi) / 2                      # the model gave only a range: use its midpoint
        notes.append(f"'{label}' was given as a range; its midpoint is used")
    if v is None or v <= 0:
        return None, [f"'{label}' has no usable number (it was empty, zero or not numeric)"]

    def share(val, pct):
        if val is None:
            return None
        return val / 100.0 if (pct or val > 1) else val

    if kind == "share":
        v, lo, hi = share(v, v_pct), share(lo, lo_pct), share(hi, hi_pct)
        if not (0 < v <= 1):
            return None, [f"'{label}' is not a valid share"]
    derived = False
    if not lo or lo <= 0 or lo > v:
        lo, derived = v * 0.6, True
    if not hi or hi < v:
        hi, derived = v * 1.4, True
    if kind == "share":
        hi = min(hi, 1.0)
    basis = box.get("basis") if box.get("basis") in (BASIS_SOURCED, BASIS_ASSUMPTION) else BASIS_ASSUMPTION
    src_ids = [s for s in (box.get("source_ids") or []) if s in valid_source_ids]
    if basis == BASIS_SOURCED and not src_ids:
        basis = BASIS_ASSUMPTION
        notes.append(f"'{label}' claimed a source that was not in the retrieved evidence, so it is shown as an AI assumption")
    if basis == BASIS_ASSUMPTION:
        src_ids = []
    return {"key": key, "label": label, "kind": kind, "value": v, "low": lo, "high": hi, "range_auto": derived,
            "basis": basis, "source_ids": src_ids, "note": str(box.get("note") or "")[:300],
            "applies_to": str(box.get("applies_to_figure") or "")}, notes


def _display(a, currency):
    if a["kind"] == "money":
        return {k: format_money(a[k], currency) for k in ("value", "low", "high")}
    if a["kind"] == "share":
        return {k: f"{a[k] * 100:.1f}%" for k in ("value", "low", "high")}
    return {k: f"{a[k]:,.0f}" for k in ("value", "low", "high")}


def pick_topdown_figure(figures, currency=None, prefer_id=None):
    """
    Best published market-size figure to use as a top-down TAM. Excludes adjacent-market and low-reliability sources.
    Prefers the figure the model's share refers to, then narrower scope, base-year over forecast, year closest to now.
    """
    cands = [f for f in figures or [] if f.get("value") and f.get("scope") != "adjacent" and f.get("reliability") != "Low"]
    if not cands:
        return None
    if prefer_id:
        for f in cands:
            if f.get("fid") == prefer_id:
                return f
    this_year = datetime.date.today().year

    def rank(f):
        scope = {"segment": 0, "regional": 1, "global": 2}.get(f.get("scope", ""), 3)
        forecast = 1 if (f.get("forecast") or "forecast" in (f.get("label") or "").lower()) else 0
        gap = abs((f.get("year") or 0) - this_year) if f.get("year") else 9
        cur = 0 if (not currency or f.get("currency") == currency) else 1
        rel = {"High": 0, "Medium": 1}.get(f.get("reliability"), 2)
        return (scope, forecast, gap, cur, rel)
    return sorted(cands, key=rank)[0]


def _levels_bottom_up(A, cur):
    uc, rev, sam_f, som_f = A.get("unit_count"), A.get("annual_revenue_per_unit"), A.get("serviceable_share"), A.get("obtainable_share")
    out = {}
    if uc and rev:
        out["tam"] = tuple(uc[w] * rev[w] for w in ("value", "low", "high"))
        if sam_f:
            out["sam"] = tuple(out["tam"][i] * sam_f[w] for i, w in enumerate(("value", "low", "high")))
            if som_f:
                out["som"] = tuple(out["sam"][i] * som_f[w] for i, w in enumerate(("value", "low", "high")))
    return out


def _levels_top_down(fig, A):
    share, som_f = A.get("topdown_serviceable_share"), A.get("obtainable_share")
    out = {}
    if fig:
        out["tam"] = (fig["value"], fig["value"], fig["value"])      # a sourced figure is a point value
        if share:
            out["sam"] = tuple(fig["value"] * share[w] for w in ("value", "low", "high"))
            if som_f:
                out["som"] = tuple(out["sam"][i] * som_f[w] for i, w in enumerate(("value", "low", "high")))
    return out


def merge_sizing_inputs(primary, fallback, valid_source_ids=()):
    """Keep every usable assumption from `primary`; fill only the unusable/missing ones from `fallback`."""
    primary = primary if isinstance(primary, dict) else {}
    fallback = fallback if isinstance(fallback, dict) else {}
    merged = {k: primary.get(k) or fallback.get(k) for k in ("customer_unit", "currency", "geography")}
    for key in ("unit_count", "annual_revenue_per_unit", "serviceable_share", "topdown_serviceable_share", "obtainable_share"):
        raw = _field(primary, key)
        ok, _ = _clean_assumption(raw, key, key, "share" if "share" in key else "money", set(valid_source_ids))
        merged[key] = raw if ok else _field(fallback, key)
    return merged


def build_sizing(raw, valid_source_ids=(), figures=None):
    """
    raw     : the model's sizing assumptions (customer_unit, currency, geography, unit_count, annual_revenue_per_unit,
              serviceable_share, obtainable_share, topdown_serviceable_share) - messy values are tolerated.
    figures : verified published market-size figures from the research (dicts with value, currency, year, scope, ...).
    Returns a dict with status 'calculated' (TAM, SAM and SOM), 'partial' (some levels) or 'unavailable' (none).
    """
    valid = set(valid_source_ids)
    result = {"status": "unavailable", "reason": "", "cautions": [], "assumptions": [], "missing": {}}
    raw = raw if isinstance(raw, dict) else {}
    cur_raw = (raw.get("currency") or "").strip().upper()[:3] if isinstance(raw.get("currency"), str) else ""
    currency = cur_raw if len(cur_raw) == 3 else "USD"
    unit_name = str(raw.get("customer_unit") or "customers").strip()[:120]

    specs = [("unit_count", f"Number of {unit_name}", "count"), ("annual_revenue_per_unit", "Annual revenue per customer", "money"),
             ("serviceable_share", "Share reachable (SAM filter)", "share"),
             ("topdown_serviceable_share", "Share of the published market this product can serve (SAM filter)", "share"),
             ("obtainable_share", "Share you can win in 3 years (SOM filter)", "share")]
    A, problems = {}, {}
    for key, label, kind in specs:
        a, notes = _clean_assumption(_field(raw, key), key, label, kind, valid)
        result["cautions"].extend([n for n in notes if "source" in n])
        if a is None:
            problems[key] = notes[0]
        else:
            A[key] = a
            result["cautions"].extend([n for n in notes if "midpoint" in n])

    ref = A.get("topdown_serviceable_share", {}).get("applies_to") or None
    fig = pick_topdown_figure(figures, cur_raw or None, ref)
    bu, td = _levels_bottom_up(A, currency), _levels_top_down(fig, A)

    if len(bu) == 3 or (len(bu) >= len(td) and len(bu) > 0 and len(td) < 3):
        approach = "bottom_up" if bu else None
    else:
        approach = "top_down" if td else ("bottom_up" if bu else None)
    if len(td) == 3 and len(bu) < 3:
        approach = "top_down"
    if approach is None:
        why = []
        if not fig:
            why.append("no published market-size figure matching this market was found in the retrieved sources")
        why += [p for k, p in problems.items() if k in ("unit_count", "annual_revenue_per_unit")]
        result["reason"] = ("Insufficient data to size this market responsibly: " + "; ".join(why or ["no usable assumptions were returned"]) + ".")
        result["debug"] = {"problems": problems, "figures_considered": len(figures or [])}
        return result

    levels = bu if approach == "bottom_up" else td
    other = td if approach == "bottom_up" else bu
    if approach == "bottom_up":
        cur, used = currency, [A[k] for k in ("unit_count", "annual_revenue_per_unit", "serviceable_share", "obtainable_share") if k in A]
        timeframe = "Annual revenue potential at full adoption (current-year assumptions); SOM covers about 3 years"
        label = "Bottom-up: customers x annual revenue per customer"
    else:
        cur = fig["currency"]
        used = [A[k] for k in ("topdown_serviceable_share", "obtainable_share") if k in A]
        tf = f"{fig['year']} " if fig.get("year") else ""
        timeframe = f"Published {tf}market size{' (forecast)' if fig.get('forecast') else ''}; SOM covers about 3 years"
        label = "Top-down: published market size x share this product can serve"
    for a in used:
        a["display"] = _display(a, cur)

    names = {"tam": "TAM", "sam": "SAM", "som": "SOM"}
    result["status"] = "calculated" if len(levels) == 3 else "partial"
    result.update({"approach": approach, "approach_label": label, "timeframe": timeframe, "currency": cur,
                   "geography": str(raw.get("geography") or "").strip()[:120], "customer_unit": unit_name, "formula": {}})
    for lvl, (val, lo, hi) in levels.items():
        result[lvl] = {"value": val, "low": lo, "high": hi, "text": format_money(val, cur),
                       "range_text": f"{format_money(lo, cur)} – {format_money(hi, cur)}"}

    if approach == "bottom_up":
        uc, rev = A["unit_count"], A["annual_revenue_per_unit"]
        result["formula"]["tam"] = f"TAM = {uc['display']['value']} {unit_name} × {rev['display']['value']} per year = {result['tam']['text']}"
        if "sam" in levels:
            result["formula"]["sam"] = f"SAM = TAM × {A['serviceable_share']['display']['value']} = {result['sam']['text']}"
    else:
        yr = f", {fig['year']}" if fig.get("year") else ""
        result["tam_source"] = {"id": fig["source_id"], "title": fig.get("source_title", ""), "url": fig.get("url", ""), "year": fig.get("year"),
                                "scope": fig.get("scope", ""), "reliability": fig.get("reliability", ""), "value_text": fig["value_text"]}
        result["formula"]["tam"] = (f"TAM = {fig['value_text']} (published {fig.get('scope') or ''} market size{yr}, source {fig['source_id']}) "
                                    "- a sourced figure, not an estimate")
        if "sam" in levels:
            result["formula"]["sam"] = f"SAM = TAM × {A['topdown_serviceable_share']['display']['value']} = {result['sam']['text']}"
        used.insert(0, {"key": "published_market_size", "label": "Published market size (sourced)", "kind": "money", "value": fig["value"],
                        "low": fig["value"], "high": fig["value"], "range_auto": False, "basis": BASIS_SOURCED,
                        "source_ids": [fig["source_id"]], "note": (fig.get("note") or fig.get("context") or "")[:300],
                        "display": {k: fig["value_text"] for k in ("value", "low", "high")}})
    if "som" in levels:
        result["formula"]["som"] = f"SOM = SAM × {A['obtainable_share']['display']['value']} = {result['som']['text']}"
    result["assumptions"] = used

    for lvl in ("tam", "sam", "som"):
        if lvl not in levels:
            needs = {"tam": "customer count and revenue per customer, or a relevant published market size",
                     "sam": "a usable share of the market this product can reach", "som": "a usable share a new entrant could win"}[lvl]
            result["missing"][lvl] = f"Insufficient data for {names[lvl]}: {needs} was not available."
    if "som" in levels and A["obtainable_share"]["value"] > 0.15:
        result["cautions"].append("A 3-year obtainable share above 15% is aggressive for a new entrant; treat SOM as optimistic.")
    sam_key = "serviceable_share" if approach == "bottom_up" else "topdown_serviceable_share"
    if "sam" in levels and A[sam_key]["value"] > 0.6:
        result["cautions"].append("More than 60% of the TAM being reachable in the first years is unlikely; validate the SAM filter.")
    if approach == "top_down":
        result["cautions"].append("TAM is a third-party published estimate (publishers often disagree); the SAM and SOM filters are AI assumptions.")
    elif all(a["basis"] == BASIS_ASSUMPTION for a in used):
        result["cautions"].append("Every input is an AI assumption (no retrieved source supports any of them). "
                                  "Use this as a structured starting estimate, not as research.")
    if "tam" in other and "tam" in levels:
        a, b = levels["tam"][0], other["tam"][0]
        if a and b:
            ratio = a / b
            other_name = "published market size" if approach == "bottom_up" else "bottom-up estimate"
            result["cross_check"] = (f"Cross-check: the {other_name} is {format_money(b, cur)}; this TAM is {ratio:.2g}x of it. "
                                     + ("Large gaps usually mean the customer count, price or geography assumption needs review." if not 0.1 <= ratio <= 10 else
                                        "The two approaches are within one order of magnitude."))
    method = {"bottom_up": ("Bottom-up estimate: potential customers × annual revenue per customer gives the TAM; the SAM keeps the share reachable with this "
                            "product, geography and channel; the SOM is the share of the SAM a new entrant could win in about three years."),
              "top_down": ("Top-down estimate: the TAM is a market size published in a retrieved source; the SAM keeps the share this product, "
                           "geography and channel can serve; the SOM is the share of the SAM a new entrant could win in about three years.")}[approach]
    result["method"] = method + " Low/high cases use each assumption's low/high value together."
    result["debug"] = {"problems": problems, "approach": approach}
    return result


# ---------------------------------------------------------------------------
# CAGR: only from retrieved sources
# ---------------------------------------------------------------------------
def resolve_cagr(figures, source_lookup, had_any_sources):
    """
    figures: output of evidence.extract_figures (kind == 'cagr'), source_lookup: id -> source dict
    Returns {status, value_text, low, high, sources[], explanation}
    status: 'verified_multi' | 'verified_single' | 'unavailable'
    """
    usable = []
    for f in figures:
        if f.get("kind") != "cagr":
            continue
        src = source_lookup.get(f["source_id"])
        if not src or classify_source(src["url"])["reliability"] == "Low":
            continue
        usable.append((f, src))

    if not usable:
        if not had_any_sources:
            why = ("No web sources could be retrieved (search returned nothing), so no growth rate could be verified.")
        else:
            why = ("None of the retrieved sources stated a compound annual growth rate for this specific market. "
                   "A growth rate is not shown rather than guessing one.")
        return {"status": "unavailable", "value_text": "Insufficient data", "explanation": why, "sources": []}

    pcts = sorted(f["pct"] for f, _ in usable)
    domains = {src["domain"] for _, src in usable}
    sources = []
    seen = set()
    for f, src in usable:
        if src["id"] in seen:
            continue
        seen.add(src["id"])
        sources.append({"id": src["id"], "title": src["title"], "url": src["url"], "pct": f["pct"],
                        "sentence": f["sentence"], "reliability": src.get("reliability")})
    lo, hi = pcts[0], pcts[-1]
    if len(domains) >= 2:
        value_text = f"{lo:g}%" if lo == hi else f"{lo:g}% – {hi:g}%"
        expl = (f"Reported by {len(domains)} independent publishers" +
                ("; the sources disagree, so a range is shown." if hi / lo > 1.5 else "."))
        status = "verified_multi"
    else:
        value_text = f"{pcts[0]:g}%"
        expl = "Only one publisher states this growth rate; treat it as indicative, not confirmed."
        status = "verified_single"
    return {"status": status, "value_text": value_text, "low": lo, "high": hi,
            "explanation": expl, "sources": sources}
