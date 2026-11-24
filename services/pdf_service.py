import io
import html
from datetime import datetime

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether,
                                HRFlowable)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas

CONTENT_W = 504  # letter width minus 54pt margins


def _safe(text):
    """Escape for reportlab Paragraph markup and replace glyphs missing from built-in Helvetica."""
    if text is None:
        return ""
    t = str(text).replace("₹", "INR ").replace("→", "->").replace("≥", ">=").replace("≤", "<=") \
        .replace("×", "x").replace("–", "-").replace("—", "-").replace("’", "'").replace("“", '"').replace("”", '"')
    t = t.encode("latin-1", "replace").decode("latin-1")
    return html.escape(t, quote=False)


def _item(item, *keys):
    if isinstance(item, dict):
        for k in keys or ("point", "feature", "risk", "opportunity", "signal", "trend", "name"):
            if item.get(k):
                return str(item[k])
        return ""
    return "" if item is None else str(item)


class NumberedCanvas(canvas.Canvas):
    """Running header/footer with page numbers"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        n = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(n)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#64748b"))
        if self._pageNumber > 1:
            self.drawString(54, 750, "Startup Idea Validator AI - Validation Report")
            self.setStrokeColor(colors.HexColor("#e2e8f0"))
            self.setLineWidth(0.5)
            self.line(54, 742, 558, 742)
        self.drawRightString(558, 36, f"Page {self._pageNumber} of {page_count}")
        self.drawString(54, 36, "Sourced facts are linked; AI estimates are labelled as such.")
        self.setStrokeColor(colors.HexColor("#e2e8f0"))
        self.line(54, 48, 558, 48)
        self.restoreState()


class PDFReportService:
    """Generates the PDF validation report from stored analysis results."""

    NAVY = colors.HexColor("#0f172a")
    BLUE = colors.HexColor("#1e40af")
    ACCENT = colors.HexColor("#3b82f6")
    SLATE = colors.HexColor("#475569")
    LIGHT = colors.HexColor("#f8fafc")
    BORDER = colors.HexColor("#e2e8f0")
    GREEN = colors.HexColor("#16a34a")
    AMBER = colors.HexColor("#ca8a04")
    RED = colors.HexColor("#dc2626")

    @classmethod
    def _styles(cls):
        base = getSampleStyleSheet()
        mk = lambda name, **kw: ParagraphStyle(name, parent=base["Normal"], **kw)
        return {
            "title": mk("T", fontName="Helvetica-Bold", fontSize=24, leading=28, textColor=cls.NAVY, spaceAfter=6),
            "sub": mk("S", fontSize=11, leading=15, textColor=cls.SLATE, spaceAfter=12),
            "h1": mk("H1", fontName="Helvetica-Bold", fontSize=15, leading=18, textColor=cls.BLUE, spaceBefore=14,
                     spaceAfter=8, keepWithNext=True),
            "h2": mk("H2", fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=cls.NAVY, spaceBefore=8,
                     spaceAfter=4, keepWithNext=True),
            "body": mk("B", fontSize=9.5, leading=13.5, textColor=colors.HexColor("#1e293b"), spaceAfter=5),
            "small": mk("Sm", fontSize=8, leading=10.5, textColor=cls.SLATE),
            "cell": mk("C", fontSize=8, leading=10.5, textColor=colors.HexColor("#1e293b")),
            "cellb": mk("Cb", fontName="Helvetica-Bold", fontSize=8, leading=10.5, textColor=cls.NAVY),
            "head": mk("Hd", fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=colors.white),
            "bullet": mk("Bu", fontSize=9, leading=12.5, leftIndent=12, bulletIndent=2, spaceAfter=2),
            "note": mk("N", fontSize=8.5, leading=11.5, textColor=colors.HexColor("#92400e")),
        }

    @classmethod
    def _table(cls, rows, widths, st, header=True, zebra=True):
        data = []
        for r_i, row in enumerate(rows):
            cells = []
            for c in row:
                if isinstance(c, str):
                    cells.append(Paragraph(c, st["head"] if (header and r_i == 0) else st["cell"]))
                else:
                    cells.append(c)
            data.append(cells)
        t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
        style = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("GRID", (0, 0), (-1, -1), 0.4, cls.BORDER),
                 ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                 ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]
        if header:
            style.append(("BACKGROUND", (0, 0), (-1, 0), cls.BLUE))
        if zebra:
            for i in range(1 if header else 0, len(rows)):
                if i % 2 == 0:
                    style.append(("BACKGROUND", (0, i), (-1, i), cls.LIGHT))
        t.setStyle(TableStyle(style))
        return t

    @staticmethod
    def _link(url, label=None):
        if not url:
            return _safe(label or "")
        return f'<a href="{html.escape(url, quote=True)}" color="#1e40af">{_safe(label or url)[:70]}</a>'

    @classmethod
    def generate_report(cls, idea, analysis_dict, competitors, report_meta=None, output_path=None):
        """Build the PDF. Returns bytes when output_path is None, else writes the file and returns the path."""
        buffer = io.BytesIO() if not output_path else None
        doc = SimpleDocTemplate(output_path or buffer, pagesize=letter, leftMargin=54, rightMargin=54,
                                topMargin=54, bottomMargin=54, title=f"Validation Report - {idea.get('title', '')}")
        st = cls._styles()
        g = lambda k: (analysis_dict.get(k, {}) or {}).get("data", {}) or {}
        market, comp, swot_risk, mvp, gtm, advisor = g("market"), g("competitors"), g("swot_risk"), g("mvp"), g("gtm"), g("advisor")
        report = g("report") or (report_meta if isinstance(report_meta, dict) else {}) or {}
        swot = swot_risk.get("swot", {}) or {}

        def para(t, style="body"):
            return Paragraph(_safe(t), st[style])

        def na(msg):
            return Paragraph("Insufficient data: " + _safe(msg), st["note"])

        def bullets(items, style="bullet"):
            return [Paragraph("• " + _safe(i), st[style]) for i in items if i]

        story = []

        # ------------------------------------------------------------------ cover / verdict
        score = report.get("viability_score")
        if score is None:
            score = idea.get("viability_score")
        rec = report.get("recommendation") or idea.get("recommendation") or "PENDING"
        from services.scoring import RECOMMENDATION_LABELS
        rec_text = RECOMMENDATION_LABELS.get(str(rec).upper(), rec)
        rec_color = cls.GREEN if rec == "PROCEED" else cls.AMBER if rec == "IMPROVE" else cls.RED
        story += [Spacer(1, 30), para(idea.get("title", "Startup Idea"), "title"),
                  para(f"Startup Validation Report  |  {datetime.now().strftime('%B %d, %Y')}  |  "
                       f"Industry: {idea.get('industry') or 'Not specified'}", "sub"),
                  HRFlowable(width="100%", thickness=1.2, color=cls.BLUE, spaceAfter=12)]
        verdict = Table([[Paragraph(f'<font size="30" color="{rec_color.hexval().replace("0x", "#")}"><b>{score if score is not None else "n/a"}</b></font>'
                                    f'<font size="11" color="#64748b"> / 100</font>', st["body"]),
                          Paragraph(f'<b>Verdict: {_safe(rec_text)}</b><br/>Confidence: {_safe((report.get("confidence") or {}).get("level", "n/a"))}'
                                    + ("<br/>" + _safe(" ".join((report.get("confidence") or {}).get("reasons", []))) if (report.get("confidence") or {}).get("reasons") else ""),
                                    st["body"])]], colWidths=[150, 354])
        verdict.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.8, cls.BORDER), ("BACKGROUND", (0, 0), (-1, -1), cls.LIGHT),
                                     ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("PADDING", (0, 0), (-1, -1), 10)]))
        story += [verdict, Spacer(1, 10), Paragraph("Executive summary", st["h1"])]
        for chunk in (report.get("executive_summary") or "Executive summary not available.").split("\n"):
            if chunk.strip():
                story.append(para(chunk.strip()))
        if report.get("verdict_explanation"):
            story += [Paragraph("Why this verdict", st["h2"]), para(report["verdict_explanation"])]
            for r_ in report.get("main_score_reducers") or []:
                story.append(Paragraph(f"• <b>{_safe(r_.get('factor_label'))}</b> ({_safe(r_.get('dimension_label'))}, {r_.get('rating')}/5): "
                                       f"{_safe(r_.get('reason'))} (+{r_.get('points_if_raised_to_4')} pts if raised to 4/5)", st["bullet"]))
            for title_, key_, field_ in (("Main strengths", "key_strengths", "point"), ("Main weaknesses", "key_weaknesses", "point"),
                                         ("Main risks", "key_risks", "risk")):
                if report.get(key_):
                    story.append(Paragraph(title_, st["h2"]))
                    for i_ in report[key_]:
                        story.append(Paragraph("• " + _safe(i_.get(field_)) + (" - " + _safe(i_.get("why") or i_.get("fix") or "") if (i_.get("why") or i_.get("fix")) else ""), st["bullet"]))
        if report.get("verdict_explanation"):
            story.append(Paragraph("Why this verdict", st["h2"]))
            story.append(para(report["verdict_explanation"]))
            for f in report.get("main_score_reducers") or []:
                story.append(Paragraph(f"• <b>{_safe(f.get('factor_label'))}</b> ({_safe(f.get('dimension_label'))}, {f.get('rating')}/5): "
                                       f"{_safe(f.get('reason'))} <i>(+{f.get('points_if_raised_to_4')} pts if raised to 4/5)</i>", st["bullet"]))
            for title, key, field in (("Main strengths", "key_strengths", "point"), ("Main weaknesses", "key_weaknesses", "point"),
                                      ("Top risks", "key_risks", "risk")):
                if report.get(key):
                    story.append(Paragraph(title, st["h2"]))
                    for i in report[key]:
                        extra = (i.get("why") or ("Fix: " + (i.get("fix") or ""))) if isinstance(i, dict) else ""
                        story.append(Paragraph(f"• <b>{_safe(i.get(field))}</b> - {_safe(extra)}", st["bullet"]))
            if report.get("disclaimer"):
                story.append(Paragraph(_safe(report["disclaimer"]), st["note"]))
        for label, key in (("Biggest strength", "biggest_strength"), ("Biggest weakness", "biggest_weakness"),
                           ("Best market opportunity", "best_market_opportunity"), ("Next action", "recommended_next_action")):
            if report.get(key):
                story.append(Paragraph(f"<b>{label}:</b> {_safe(report[key])}", st["body"]))
        if report.get("disclaimer"):
            story.append(Paragraph(_safe(report["disclaimer"]), st["note"]))

        # ------------------------------------------------------------------ scores explained
        dims = (report.get("score_breakdown") or {}).get("dimensions") or {}
        if dims:
            story.append(Paragraph("How the score was calculated", st["h1"]))
            rows = [["Dimension", "Score", "Weight", "Why"]]
            for d in dims.values():
                rows.append([_safe(d["label"]), f"{d['score']}/100" if d["score"] is not None else "n/a",
                             f"{int(d['weight'] * 100)}%", _safe(d["explanation"])])
            story.append(cls._table(rows, [95, 45, 38, 326], st))
            story.append(Spacer(1, 4))
            story.append(Paragraph(_safe(report.get("scoring_rules", "")), st["small"]))

        # ------------------------------------------------------------------ market
        story += [PageBreak(), Paragraph("1. Market research", st["h1"])]
        if market.get("_error"):
            story.append(na(market["_error"]))
        else:
            story.append(para(market.get("market_summary", "")))
            dq = market.get("data_quality", {})
            story.append(Paragraph(f"Research base: {dq.get('sources_retrieved', 0)} web source(s), "
                                   f"{dq.get('verified_figures', 0)} sourced market figure(s). "
                                   + _safe(" ".join(dq.get("notes", []))), st["small"]))
            story.append(Paragraph("Sourced market figures", st["h2"]))
            figs = market.get("verified_figures", [])
            if figs:
                rows = [["Figure", "Scope / note", "Source"]]
                for f in figs:
                    rows.append([f"<b>{_safe(f['value_text'])}</b> ({_safe(f.get('label', ''))}{', ' + str(f['year']) if f.get('year') else ''})",
                                 _safe(f.get("note", "")), cls._link(f.get("url"), f.get("source_title") or f.get("url"))])
                story.append(cls._table(rows, [120, 214, 170], st))
            else:
                story.append(na("no retrieved source stated a market size matching this market, so none is shown."))
            ci = market.get("cagr_info", {})
            story.append(Paragraph(f"<b>Growth rate (CAGR):</b> {_safe(market.get('cagr', 'Insufficient data'))} - {_safe(ci.get('explanation', ''))}", st["body"]))
            for s_ in ci.get("sources", [])[:3]:
                story.append(Paragraph("Source: " + cls._link(s_["url"], s_["title"]), st["small"]))

            for title, items, key in (("Customer demand signals", market.get("demand_signals", []), "signal"),
                                      ("Market trends", market.get("trends", []), "trend"),
                                      ("Opportunities", market.get("opportunities", []), "opportunity")):
                if items:
                    story.append(Paragraph(title, st["h2"]))
                    for it in items:
                        tag = "[Sourced]" if it.get("basis") == "sourced" else "[AI analysis]"
                        extra = it.get("detail") or it.get("impact") or it.get("why") or ""
                        story.append(Paragraph(f"• <b>{_safe(it.get(key))}</b> {tag} - {_safe(extra)}", st["bullet"]))

            # sizing
            story.append(Paragraph("Market sizing (TAM / SAM / SOM)", st["h2"]))
            sz = market.get("sizing", {})
            if sz.get("status") in ("calculated", "partial"):
                story.append(para(f"Method: {sz.get('approach_label', '')} | Currency: {sz.get('currency', '')} | Timeframe: {sz.get('timeframe', '')}", "small"))
                if sz.get("tam_source"):
                    story.append(Paragraph("Sourced TAM: " + cls._link(sz["tam_source"].get("url"), sz["tam_source"].get("title") or sz["tam_source"].get("url")), st["small"]))
                rows = [["", "Estimate", "Low - High", "Calculation"]]
                for k in ("tam", "sam", "som"):
                    if sz.get(k):
                        rows.append([k.upper(), f"<b>{_safe(sz[k]['text'])}</b>", _safe(sz[k]["range_text"]), _safe(sz["formula"].get(k, ""))])
                    else:
                        rows.append([k.upper(), "Insufficient data", "-", _safe((sz.get("missing") or {}).get(k, ""))])
                story.append(cls._table(rows, [36, 70, 110, 288], st))
                rows = [["Assumption", "Value", "Basis"]]
                for a in sz["assumptions"]:
                    basis = "Sourced" if a["basis"] == "sourced" else "AI assumption"
                    rows.append([_safe(a["label"]), _safe(a["display"]["value"]), basis + (" - " + _safe(a["note"]) if a.get("note") else "")])
                story += [Spacer(1, 4), cls._table(rows, [150, 80, 274], st), Spacer(1, 3), para(sz.get("method", ""), "small")]
                if sz.get("cross_check"):
                    story.append(para(sz["cross_check"], "small"))
                story += [Paragraph("Caution: " + _safe(c), st["note"]) for c in sz.get("cautions", [])]
            else:
                story.append(na(sz.get("reason", "sizing assumptions were missing.")))

        # ------------------------------------------------------------------ competitors
        story += [PageBreak(), Paragraph("2. Competitor analysis", st["h1"])]
        comps = comp.get("competitors") or []
        if comp.get("_error"):
            story.append(na(comp["_error"]))
        elif not comps:
            story.append(na(comp.get("note", "no competitor website could be verified.")))
        else:
            story.append(para("Each competitor below had its official website located and opened. Products, features and "
                              "prices are taken from those pages; 'gap vs your idea' is AI analysis.", "small"))
            rows = [["Company", "Type", "Products / key features", "Pricing found", "Strengths (site) / Weaknesses (AI) / Gap vs your idea"]]
            for c in comps:
                feats = "; ".join((c.get("products") or [])[:2] + (c.get("key_features") or [])[:3])
                rows.append([f"<b>{_safe(c['name'])}</b><br/>{cls._link(c.get('website_url'), c.get('website_url'))}",
                             _safe(c.get("competitor_type", "")), _safe(feats or "Not stated on site"),
                             _safe(c["pricing"]["text"]) if isinstance(c.get("pricing"), dict) else "n/a",
                             _safe("Strengths: " + "; ".join(c.get("site_strengths") or []) + " | Weaknesses (AI): " + "; ".join(c.get("ai_weaknesses") or []) + " | Gap: " + (c.get("gaps_vs_idea") or ""))])
            story.append(cls._table(rows, [104, 44, 130, 76, 150], st))
            if comp.get("comparison_features"):
                names = [c["name"] for c in comps]
                story.append(Paragraph("Capability comparison", st["h2"]))
                w = max(40, int((504 - 130 - 50) / max(1, len(names))))
                rows = [["Capability", "Your idea"] + [_safe(n)[:14] for n in names]]
                for r in comp["comparison_features"]:
                    rows.append([_safe(r["capability"]), "Yes" if r.get("idea_offers") else "No"] +
                                [{"yes": "Yes", "no": "No"}.get(r["competitors"].get(n), "?") for n in names])
                story.append(cls._table(rows, [130, 50] + [w] * len(names), st))
                story.append(para("? = not clear from the competitor's public pages.", "small"))
            if comp.get("opportunities"):
                story.append(Paragraph("Where your idea can be different", st["h2"]))
                for o in comp["opportunities"]:
                    story.append(Paragraph(f"• <b>{_safe(o.get('opportunity'))}</b> - {_safe(o.get('why', ''))}", st["bullet"]))
        if comp.get("unverified_mentions"):
            story.append(para("Names mentioned but not verified (excluded): " + ", ".join(u["name"] for u in comp["unverified_mentions"]), "small"))

        # ------------------------------------------------------------------ SWOT + risks
        story += [PageBreak(), Paragraph("3. SWOT analysis", st["h1"])]
        if swot_risk.get("_error"):
            story.append(na(swot_risk["_error"]))
        else:
            def quad(title, items):
                cell = [Paragraph(f"<b>{title}</b>", st["cellb"])]
                for i in items:
                    cell.append(Paragraph("• " + _safe(_item(i, "point")), st["cell"]))
                return cell
            t = Table([[quad("Strengths", swot.get("strengths", [])), quad("Weaknesses", swot.get("weaknesses", []))],
                       [quad("Opportunities", swot.get("opportunities", [])), quad("Threats", swot.get("threats", []))]],
                      colWidths=[252, 252])
            t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, cls.BORDER), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                   ("PADDING", (0, 0), (-1, -1), 7), ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#f0fdf4")),
                                   ("BACKGROUND", (1, 0), (1, 0), colors.HexColor("#fef2f2")),
                                   ("BACKGROUND", (0, 1), (0, 1), colors.HexColor("#eff6ff")),
                                   ("BACKGROUND", (1, 1), (1, 1), colors.HexColor("#fffbeb"))]))
            story.append(t)
            story.append(Paragraph("Risk register", st["h1"]))
            rows = [["Risk", "Severity", "Impact x Likelihood", "Realistic solution"]]
            for r in swot_risk.get("risks", []):
                rows.append([f"<b>{_safe(r.get('category'))}</b>: {_safe(r.get('risk'))}", _safe(r.get("severity")),
                             f"{r.get('impact_score')} x {r.get('likelihood_score')}", _safe(r.get("realistic_solution", ""))])
            story.append(cls._table(rows, [180, 50, 64, 210], st))
            if swot_risk.get("overall_risk_score") is not None:
                story.append(para(f"Composite risk score: {swot_risk['overall_risk_score']}/100 ({swot_risk.get('risk_rating')})", "small"))

        # ------------------------------------------------------------------ MVP
        story += [PageBreak(), Paragraph("4. MVP and development roadmap", st["h1"])]
        if mvp.get("_error"):
            story.append(na(mvp["_error"]))
        else:
            story.append(para(f"Team assumption: {mvp.get('team_assumption', 'not stated')}. Riskiest assumption to test: {mvp.get('riskiest_assumption', 'n/a')}"))
            tcn = (mvp.get("timeline_check") or {}).get("note")
            if tcn:
                story.append(para("Timeline check: " + tcn))
            for b in mvp.get("build_order") or []:
                story.append(Paragraph(f"Build first {b.get('step', '')}: <b>{_safe(b.get('what'))}</b> - {_safe(b.get('why_first'))}", st["bullet"]))
            ce = mvp.get("cost_estimate") or {}
            if ce.get("status") == "ok":
                story.append(Paragraph("Development cost estimate (AI estimate from stated assumptions)", st["h2"]))
                story.append(para(f"Cash: {ce['cash_total']['text']}  |  Own time (valued): {ce['own_time_total']['text']}"))
                for a in ce.get("assumptions", []):
                    story.append(Paragraph("• Assumption: " + _safe(a), st["bullet"]))
            elif ce:
                story.append(para(ce.get("reason", "Insufficient data for a cost estimate.")))
            for title, key in (("Must-have features", "must_have"), ("Should-have", "should_have"), ("Could-have", "could_have")):
                if mvp.get(key):
                    story.append(Paragraph(title, st["h2"]))
                    for f in mvp[key]:
                        story.append(Paragraph(f"• <b>{_safe(_item(f, 'feature'))}</b> - {_safe(f.get('why', '')) if isinstance(f, dict) else ''}", st["bullet"]))
            if mvp.get("roadmap"):
                story.append(Paragraph("Roadmap", st["h2"]))
                rows = [["Phase", "Weeks", "Goal and deliverables", "Exit criteria"]]
                for p_ in mvp["roadmap"]:
                    rows.append([_safe(p_.get("phase")), _safe(p_.get("weeks")),
                                 _safe(p_.get("goal", "") + " - " + "; ".join(p_.get("deliverables", []))), _safe(p_.get("exit_criteria", ""))])
                story.append(cls._table(rows, [80, 40, 250, 134], st))

        # ------------------------------------------------------------------ GTM
        story += [PageBreak(), Paragraph("5. Pricing, first customers and 30/60/90-day plan", st["h1"])]
        if gtm.get("_error"):
            story.append(na(gtm["_error"]))
        else:
            story.append(para(gtm.get("positioning_statement", "")))
            if gtm.get("revenue_models"):
                story.append(Paragraph("Revenue models", st["h2"]))
                for m_ in gtm["revenue_models"]:
                    story.append(Paragraph(f"• <b>{_safe(m_.get('model'))}</b> ({_safe(m_.get('example_price', ''))}) - {_safe(m_.get('fit_reason', ''))}", st["bullet"]))
            ps = gtm.get("pricing_strategy", {})
            if ps.get("tiers"):
                story.append(Paragraph("Suggested pricing (to be validated with customers)", st["h2"]))
                rows = [["Tier", "Price", "Target", "Basis"]]
                for t_ in ps["tiers"]:
                    rows.append([_safe(t_.get("name")), _safe(t_.get("price")), _safe(t_.get("target")), _safe(t_.get("basis", ""))])
                story.append(cls._table(rows, [100, 90, 214, 100], st))
                story.append(para(ps.get("rationale", ""), "small"))
            if gtm.get("price_anchors"):
                story.append(para("Competitor prices found: " + "; ".join(f"{a['competitor']}: {', '.join(a['prices'][:3])}" for a in gtm["price_anchors"]), "small"))
            fc = gtm.get("first_customers", {})
            if fc:
                story.append(Paragraph("How to find the first customers", st["h2"]))
                story.append(para(fc.get("ideal_customer_profile", "")))
                for ch in fc.get("where_to_find", []):
                    story.append(Paragraph(f"• <b>{_safe(ch.get('channel'))}</b> - {_safe(ch.get('action', ''))}", st["bullet"]))
                if fc.get("outreach_message"):
                    story.append(Paragraph("<b>Sample outreach:</b> " + _safe(fc["outreach_message"]), st["body"]))
            story.append(Paragraph("30 / 60 / 90-day action plan", st["h2"]))
            for ph in gtm.get("launch_roadmap_90_days", []):
                block = [Paragraph(f"<b>{_safe(ph.get('phase'))}</b> - {_safe(ph.get('goal', ''))}", st["body"])]
                block += bullets(ph.get("actions", []))
                block.append(Paragraph("Success metric: " + _safe(ph.get("success_metric", "")), st["small"]))
                story.append(KeepTogether(block))

        # ------------------------------------------------------------------ sources
        sources = (report.get("research_summary") or {}).get("sources") or []
        story += [Paragraph("6. Sources", st["h1"])]
        if sources:
            for s_ in sources:
                story.append(Paragraph(f"[{_safe(s_['id'])}] {cls._link(s_['url'], s_['title'])} - {_safe(s_.get('source_label', ''))}", st["small"]))
        else:
            story.append(na("no web sources were retrieved for this report."))

        doc.build(story, canvasmaker=NumberedCanvas)
        if output_path:
            return output_path
        return buffer.getvalue()
