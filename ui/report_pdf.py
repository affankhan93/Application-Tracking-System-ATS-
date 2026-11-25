"""Downloadable PDF version of a resume report."""

import io 
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4 
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm 
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

NAMES = {"parsability": "Parsability",
         "keyword_match": "Keyword match",
         "sections": "Sections",
         "experience_quality": "Experience quality",
         "readability": "Readability"}

def build_pdf(a: dict)-> bytes:
    s = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=s['BodyText'], fontSize=10, leading=14)
    h1 = ParagraphStyle("h1", parent=s['Title'], fontSize= 20, alignment=0, spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=body, fontSize=13, spaceBefore= 10, spaceAfter=4,  textColor=colors.HexColor("#2457D6"))
    muted = ParagraphStyle("muted", parent=body, textColor=colors.HexColor("#5B6475"), fontSize=9)
    p = lambda text, style = body: Paragraph(escape(str(text)), style)

    score, fb = a['score'], a['feedback']['feedback']
    story = [p("Resume report", h1), p(f"{a['file_name']} | {a['analyzed_at'][:10]}", muted), 
             p(f"ATS friendly score: {score['total']} / 100 ({score['band'].replace('_', " ")})", h2)]

    rows = [[NAMES.get(k, k.replace("_", " ").title()), f"{v['score']:.0f} / {v['max']}"] for k, v in score['components'].items()]
    table = Table(rows, colWidths=[90 * mm, 30 * mm])
    table.setStyle(TableStyle([('FONTSIZE', (0,0), (-1, -1), 10), ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#DDE2EC")), 
                               ("ALIGN", (1, 0), (1, -1), 'RIGHT')]))

    story += [table, p("Best-fit job fields", h2)]
    story += [p(f"{r['role']}: {r['fit_score']}%") for r in a['job_fit']['roles']]
    story += [p("Pros", h2)] + [p(f"- {x}") for x in fb['pros']]
    story += [p("Cons", h2)] + [p(f"- {x}") for x in fb['cons']]
    story.append(p("Suggestions", h2))
    for sug in fb['suggestions']:
        story.append(p(f"- {sug['title']}: {sug['advice']}"))
        if sug.get("example_bullet"):
            story.append(p(f" Example: {sug['example_bullet']}", muted))

    notice = a['feedback'].get("integrity_notice")
    story += [p("Integrity", h2), p(notice or "No hidden text was detected.")]
    story += [Spacer(1, 8), p("The score is a guide and supports a human decision. It is never a reason to reject a resume automatically.", muted)]
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize = A4, leftMargin = 20 *mm, rightMargin = 20 * mm, topMargin = 18 * mm, bottomMargin = 18 * mm).build(story)
    return buf.getvalue() 

