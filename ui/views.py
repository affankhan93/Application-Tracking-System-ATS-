"""The screens from UI mockups: Resume report, Candidates, Integrity report, plus Upload, Reports and Sign in."""

from __future__ import annotations
import csv 
import datetime as dt 
import io 
import json 
import streamlit as st 
from core.pipeline import analyze_resume
from ui.report_pdf import build_pdf 
from ui.theme import (BAND_TEXT, COMPONENT_NAMES, SEVERITY, card, chip, esc, html_block, progress_row, risk_chip, score_ring)
from dotenv import load_dotenv

load_dotenv()

MAX_BATCH = 25
FINDING_TITLES = {
    "hidden_color_text": "Text colour matches the background",
    "tiny_text": "Font too small to read", "invisible_text": "Invisible text in the PDF",
    "hidden_text_flag": "Word hidden-text setting", "off_page_text": "Text placed off the page",
    "text_not_rendered": "Text covered or not shown on the page", "text_layer_mismatch": "Text_layer and OCR mismatch",
    "prompt_injection": "Prompt-injection phrase", "zero_width_characters": "Invisible characters in the text",
    "keyword_stuffing": "Keyword stuffing", "suspicious_metadata": "Suspicious document properties",
}

HIDDEN_TYPES = {'hidden_color_text', 'tiny_text', 'invisible_text', 'hidden_text_flag', 'off_page_text', 
                'text_not_rendered', 'text_layer_mismatch'}

@st.cache_data(show_spinner=False, max_entries=64)
def cached_analysis(file_bytes: bytes, filename: str, jd: str | None, jd_tilte: str | None) -> dict:
    return analyze_resume(file_bytes, filename, jd, jd_tilte)

def ago(iso: str) -> str:
    seconds = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(iso)).total_seconds()
    if seconds < 90:
        return 'just now'
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)} h ago"
    return dt.datetime.fromisoformat(iso).strftime("%d %b %Y")


def candidate_label(file_hash: str, file_name: str, anonymised: bool)-> str:
    return f"Candidate {int(file_hash[:6], 16) % 10000:04d}" if anonymised else file_name


def finding_detail(f: dict)-> str:
    e, t = f['evidence'], f['flag_type']
    pages = ", ".join(str(p) for p in e.get("pages", []))
    if t in ("hidden_color_text", "low_constrast_text"):
        return f"{e['words']} words, page {pages}. Contrast ratio {e['contrast_ration']}:1."
    if t == 'tiny_text':
        return f"{e['words']} words on page {pages}, under 4 pt."
    if t in ("invisible_text", "hidden_text_flag", "off_page_text"):
        return f"{e['words']} words, page {pages}. Not visible to a reader."
    if t in ("text_not_rendered", "text_layer_mismatch"):
        return f"{e['words']} words exist in the file but not on the rendered page."
    if t == 'prompt_injection':
        phrases = "; ".join(f"“{p}”" for p in e.get("phrases", [])[:2])
        return f"Instruction aimed at an AI screener. {phrases}"
    if t == 'zero_width_characters':
        return f"{e['count']} zero-width characters mixed into the text."
    if t == 'keyword_stuffing':
        words = ", ".join(f"{w} x{c}" for w, c in e.get("repeated_words", {}).items())
        return f"Repeated: {words}." if words else "The same lines are repeated,"
    return e.get("field", "") and f"Property: {e['field']}." or "A document property holds hidden instructions or keywords."


def go_to(page_file: str, analysis: dict | None = None) -> None:
    if analysis is not None:
        st.session_state['current'] = analysis
    st.switch_page(page_file)


def open_saved(store, rid: str, flagged_first: bool = False) -> None:
    a = store.get(rid)
    if a is None:
        st.error("That report could not be found.")
        return 
    go_to("pages/3_Integrity.py" if flagged_first and a['integrity']['risk'] != 'clean' else 'pages/1_Upload_report.py', a)

def process_files(files, store, jd_title = None, jd_body = None, jd_id = None) -> list[str]:
    """Analyse and save each file. Returns a list of error messages (empty when everything worked)."""
    errors, bar = [], st.progress(0.0, text='Starting')
    for i, f in enumerate(files, start=1):
        bar.progress((i-1)/ len(files), text=f"Analysing {f.name} ({i}/{len(files)})")
        try:
            a = cached_analysis(f.getvalue(), f.name, jd_body, jd_title)
            a = dict(a, id = store.save(a, jd_id), jd_id=jd_id, review_status = 'none')
            st.session_state['last_saved'] = a
        except Exception as exc:
            errors.append(f"{f.name}: {exc}")
    bar.progress(1.0, text='Done')
    return errors 


# Upload 
def render_upload(store) -> None:
    html_block("<h1 class = 'ats-h1'> Upload a resume </h1><div class = 'ats-m' style = 'margin-bottom: 20px'> PDF or DOCX, up to 5 MB. The score and feedback use only the text a reader can see. </div>")
    with st.container(border=True):
        file = st.file_uploader("Resume", type=['pdf', 'docx'], key = 'single_upload')
        jd = st.text_area('Job description (optional)', height=140, key='single_jd', 
                          help="Paste a job description to get a job-description match.")
        if st.button("Analyse resume", type='primary', disabled=file is None):
            with st.status("Reading the file, checking for hidden text, scoring, and writing feedback...", expanded=False) as status:
                errors = process_files([file], store, jd_body=jd or None)
                status.update(label='Finished' if not errors else 'Failed', state='complete' if not errors else 'error')
            if errors:
                st.error(errors[0])
            else:
                st.session_state['current'] = st.session_state.pop('last_saved')
                st.rerun() 


# Resume report 
def render_report(a: dict, store) -> None:
    score, fb, integrity = a['score'], a['feedback'], a['integrity']
    f = fb['feedback']
    head = st.columns([6, 1.3, 1.7], vertical_alignment='center')
    head[0].markdown(f"<h1 class = 'ats-h1'> Resume report</h1><div class = 'ats-m'> {esc(a['file_name'])} analysed {esc(ago(a['analyzed_at']))}</div>", unsafe_allow_html=True)
    if head[1].button("Upload new", key='upload_new', use_container_width=True):
        st.session_state.pop('current', None)
        st.rerun()
    head[2].download_button("Download report", build_pdf(a), file_name=f"{a['file_name'].rsplit(".", 1)[0]}_report.pdf", mime = 'application/pdf', type='primary', use_container_width=True)

    left, right = st.columns([340, 860], gap='medium')
    with left:
        html_block(score_ring(score['total'], BAND_TEXT[score['band']])) 
        rows = [progress_row(COMPONENT_NAMES[k], f"{c['score']:g} / {c['max']}", 100 * c['score'] /c['max'], last=i == 4)
                for i, (k, c) in enumerate(score['components'].items())]
        html_block(card('<h2 class = "ats-t"> Score breakdown</h2>' + ''.join(rows)))
        n = len(integrity['findings'])
        text = 'No hidden text detected' if integrity['risk'] == 'clean' else f"{n} finding{'s' if n != 1 else ''} need a look"
        html_block(card(f'{risk_chip(integrity['risk'])}<span style = "font-size: 14px"> {esc(text)} </span>', 
                        'display: flex; align-items: center; gap:10px; margin-bottom: 8px'))

        if integrity['risk'] != 'clean' and st.button("Open integrity report", key='open_integrity', use_container_width=True):
            go_to("pages/3_Integrity.py")

    with right:
        fields = "".join(progress_row(r['role'], f"{r['fit_score']}%", r['fit_score'], last=i == len(a['job_fit']['roles']) - 1)
                         for i, r in enumerate(a['job_fit']['roles']))
        html_block(card('<h2 class = "ats-t"> Best-fit job fields</h2>' + fields))
        pros, cons = st.columns(2, gap='medium')
        pros.markdown(card('<h2 class = "ats-t" style = "color: #05603A">Pros</h2><ul>' + "".join(f"<li>{esc(x)}</li>" for x in f['pros']) + "</ul>"), unsafe_allow_html=True)
        cons.markdown(card('<h2 clsas = "ats-t" style = "color: #B42318">Cons</h2><ul>' + "".join(f"<li>{esc(x)}</li>" for x in f['cons']) + "</ul>"), unsafe_allow_html=True)

        items = ""
        for s in f['suggestions']:
            example = f'<div class = "ats-m">Example: {esc(s['example_bullet'])}</div>' if s.get("example_bullet") else ""
            items += f'<li><b>{esc(s['title'])}.</b> {esc(s['advice'])}{example}</li>'
        origin = "Written with AI from your knowledge base." if fb['source'] == 'llm' else 'Written from the rule-based checks.'
        html_block(card(f'<h2 class = "ats-t"> Suggestions </h2><ul>{items}<ul><div class = "ats-m" style = "margin-top: 12px"> {origin}</div>'))
        if fb.get("integrity_notice"):
            html_block(card(f'<div class = "ats-m">{esc(fb['integrity_notice'])}</div>'))


# Integrity report 
def _page_sketch(visible_text: str, findings: list[dict]) -> str:
    """A simple drawing of the resume: gray bars for real lines, read boxes where hidden text was found."""
    from core.parser import _HEADING_LOOKUP
    bars, lines = [], [ln.strip() for ln in visible_text.splitlines() if ln.strip()[:14]]
    for i, ln in enumerate(lines):
        key = "".join(ch for ch in ln.lower() if ch.isalpha() or ch == " ").strip()
        if i == 0:
            bars.append('<div style= "height: 14px; width: 45%; background:#14213D;border-radius:3px"></div>')
        elif key in _HEADING_LOOKUP:
             bars.append('<div style="height:14px;width:35%;background:#14213D;border-radius:3px;margin-top:10px"></div>')
        else:
            width = 30 if i == 1 else min(92, 25 + len(ln))
            colour = "#C5CCDA" if i == 1 else "#E6EAF2"
            bars.append(f'<div style = "height:8px; width: {width}%;background:{colour};border-radius:3px"></div>')
    boxes = []
    for f in findings:
        if f['flag_type'] in HIDDEN_TYPES and f['evidence'].get('sample'):
            boxes.append('<div style = "border: 2px dashed #B42318;background:#FEE4E2;border-radius:6px;padding:10px;font-size:12px;'
                        f'color:#B42318;line-height:1.5"><b>Hidden text found.</b> {esc(FINDING_TITLES[f["flag_type"]])}. '
                        f'{esc(f["evidence"]["sample"][:220])}</div>')
    at = min(4, len(bars))
    pieces = bars[:at] + boxes[:3] + bars[at:]
    return ('<div class="ats-c" style="background:#EEF1F6"><div style="background:#fff;border:1px solid #DDE2EC;padding:28px;'
            'display:flex;flex-direction:column;gap:10px">' + "".join(pieces) + "</div></div>")


def render_integrity(a: dict, store, anonymised: bool) -> None:
    integrity = a['integrity']
    findings = integrity['findings']
    label = candidate_label(a['file_hash'], a['file_hash'], anonymised)
    pages = max(1, a.get('pages', 1))
    head = st.columns([5, 1.2, 1.9, 1.7], vertical_alignment='center')
    head[1].markdown(f'<div style="text-align:right">{risk_chip(integrity["risk"])}</div>', unsafe_allow_html=True)
    marked = a.get("review_status") == "needs_review"
    if head[2].button("Marked for manual review" if marked else "Mark for manual review", key="mark_review",
                      disabled=marked or not a.get('id'), use_container_width=True):
        store.set_review(a['id'], 'needs_review')
        a['review_status'] = 'needs_review'
        st.rerun()
    evidence = {'file': a['file_name'], 'risk': integrity['risk'], 'findigns': findings, 'stats': integrity['stats'],
                'checks_skipped': integrity['checks_skipped']}
    head[3].download_button("Download evidence", json.dumps(evidence, indent=2, ensure_ascii=False), file_name='integrity_evidence.json', 
                            mime='application/json', type='primary', use_container_width=True)

    left, right = st.columns(2, gap='medium')
    left.markdown(_page_sketch(integrity['visible_text'], findings), unsafe_allow_html=True)
    if findings:
        items = ""
        for f in findings:
            name, kind = SEVERITY[f['severity']]
            items += (f'<li>{chip(name, kind)} <b>{esc(FINDING_TITLES.get(f["flag_type"], f["flag_type"]))}</b>'
                      f'<div class="ats-m">{esc(finding_detail(f))}</div></li>')
        body = f'<ul class = "ats-plain"> {items}</ul>'
    else:
        body = '<div style="font-size:14px">No hidden text or manipulation was found.</div>'
    skipped = f' Not run: {esc(", ".join(integrity["checks_skipped"]))}.' if integrity["checks_skipped"] else ""
    right.markdown(card('<h2 class="ats-t">Findings</h2>' + body + '<div class="ats-m" style="margin-top:16px">'
                    f'Scoring used visible text only. A recruiter should review before any decision.{skipped}</div>'),unsafe_allow_html=True) 
    if st.button("Open resume report", key='open_report'):
        go_to("pages/1_Upload_Report.py")


# Candidates 
def render_candidates(store) -> None:
    jds = store.list_jds()
    options = {None: "All resumes", **{j['id']: j['title'] for j in jds}}
    jd_id = st.session_state.get("jd_id") if st.session_state.get("jd_id") in options else None
    rows = store.list(jd_id)
    anonymised = st.session_state.get("anonymised", True)

    head = st.columns([5, 1.9, 1.3, 1.8], vertical_alignment='center')
    head[0].markdown(f"<h1 class = 'ats-h1'> Candidates</h1><div class = 'ats-m'> {esc(options[jd_id])} {len(rows)} resume {'s' if len(rows) != 1 else ''}</div>", unsafe_allow_html=True)
    head[1].checkbox("Anonymised view", value=True, key = 'anonymised')
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(['Candidate', 'ATS score', 'JD match', 'Top field', 'Integrity', 'Review status'])
    for r in rows:
            writer.writerow([candidate_label(r["file_hash"], r["file_name"], anonymised), r["ats_total"],
                             "" if r["jd_match"] is None else f"{r['jd_match']}%", r["top_role"], r["integrity_risk"], r["review_status"]])
    head[2].download_button("Export CSV", buf.getvalue(), file_name="candidates.csv", mime="text/csv", use_container_width=True)
    with head[3].popover("Upload resumes", type="primary", use_container_width=True):
        _upload_many(store, jds)

    picked = st.selectbox("Job description", list(options), format_func=options.get, index=list(options).index(jd_id), key='jd_pick')
    if picked != jd_id:
        st.session_state['jd_id'] = picked
        st.rerun()

    with st.container(border=True):
        cols = st.columns([2.2, 1, 1, 1.6, 1.2, 1])
        for col, name in zip(cols, ['Candidate', 'ATS score', 'JD match', 'Top field', 'Integrity', ""]):
            col.markdown(f'<span class = "ats-th"> {name}</span>', unsafe_allow_html=True)
        html_block('<div class = "ats-rule"> </div>')
        if not rows:
            html_block("<div class = 'ats-m' style= 'padding: 12px 0'> No resumes yet. Use “Upload resumes”.</div>")
        for r in sorted(rows, key = lambda r: -r['ats_total']):
            cols = st.columns([2.2, 1, 1, 1.6, 1.2, 1], vertical_alignment="center")
            cols[0].markdown(f'<b class="ats-td">{esc(candidate_label(r["file_hash"], r["file_name"], anonymised))}</b>', unsafe_allow_html=True)
            cols[1].markdown(f'<span class="ats-td">{r["ats_total"]}</span>', unsafe_allow_html=True)
            cols[2].markdown(f'<span class="ats-td">{"–" if r["jd_match"] is None else str(r["jd_match"]) + "%"}</span>', unsafe_allow_html=True)
            cols[3].markdown(f'<span class="ats-td">{esc(r["top_role"])}</span>', unsafe_allow_html=True)
            if cols[5].button("View", key=f"view_{r['id']}", use_container_width=True):
                open_saved(store, r["id"], flagged_first=True)
            html_block('<div class="ats-rule"></div>')
    html_block('<div class="ats-m">Scores support the recruiter\'s decision. Flagged resumes go to manual review, never auto-reject.</div>')
           


def _upload_many(store, jds: list[dict]) -> None:
    choice = st.selectbox("Job description", ["No job description", "New job description"] + [j["title"] for j in jds], key="batch_jd")
    title = body = None
    jd_id = None
    if choice == "New job description":
        title = st.text_input("Title", key="batch_jd_title")
        body = st.text_area("Job description text", height=120, key="batch_jd_body")
    elif choice != "No job description":
        match = next(j for j in jds if j["title"] == choice)
        title, body, jd_id = match["title"], match["body"], match["id"]
    files = st.file_uploader(f"Resumes (up to {MAX_BATCH})", type=["pdf", "docx"], accept_multiple_files=True, key="batch_files")
    if st.button("Analyse resumes", type="primary", disabled=not files, key="batch_go"):
        if len(files) > MAX_BATCH:
            st.error(f"Please upload at most {MAX_BATCH} resumes at a time.")
            return
        if choice == "New job description":
            if not (title and body):
                st.error("Add a title and the job description text.")
                return
            jd_id = store.save_jd(title.strip(), body.strip())
        errors = process_files(files, store, title, body, jd_id)
        if jd_id:
            st.session_state["jd_id"] = jd_id
        if errors:
            st.warning("Some files could not be analysed: " + "; ".join(errors))
        else:
            st.rerun()
    
# Reports (history)
def render_history(store) -> None:
    rows = store.list()
    html_block(f'<h1 class="ats-h1">Reports</h1><div class="ats-m" style="margin-bottom:20px">{len(rows)} saved report{"s" if len(rows) != 1 else ""}</div>')
    with st.container(border=True):
        cols = st.columns([2.6, 1.3, 1, 1.6, 1.2, 0.9, 0.9])
        for col, name in zip(cols, ["File", "Date", "ATS score", "Top field", "Integrity", "", ""]):
            col.markdown(f'<span class="ats-th">{name}</span>', unsafe_allow_html=True)
        html_block('<div class="ats-rule"></div>')
        if not rows:
            html_block('<div class="ats-m" style="padding:12px 0">No reports yet. Upload a resume to create one.</div>')
        for r in rows:
            cols = st.columns([2.6, 1.3, 1, 1.6, 1.2, 0.9, 0.9], vertical_alignment="center")
            cols[0].markdown(f'<b class="ats-td">{esc(r["file_name"])}</b>', unsafe_allow_html=True)
            cols[1].markdown(f'<span class="ats-td">{esc(dt.datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")).strftime("%d %b %Y"))}</span>', unsafe_allow_html=True)
            cols[2].markdown(f'<span class="ats-td">{r["ats_total"]}</span>', unsafe_allow_html=True)
            cols[3].markdown(f'<span class="ats-td">{esc(r["top_role"])}</span>', unsafe_allow_html=True)
            cols[4].markdown(risk_chip(r["integrity_risk"]), unsafe_allow_html=True)
            if cols[5].button("View", key=f"hv_{r['id']}", use_container_width=True):
                open_saved(store, r["id"])
            if cols[6].button("Delete", key=f"hd_{r['id']}", use_container_width=True):
                store.delete(r["id"])
                st.session_state.pop("current", None)
                st.rerun()
            html_block('<div class="ats-rule"></div>')
    html_block('<div class="ats-m">Deleting a report removes the resume text and results from storage.</div>')


def _auth_message(exc: Exception) -> str:
    return str(getattr(exc, 'message', None) or exc)[:300]

# Sign in 
def render_login() -> None:
    from core.db import sign_in, sign_up
    html_block('<h1 class="ats-h1" style="margin-top:48px">ATS System</h1><div class="ats-m" style="margin-bottom:20px">Sign in to save your reports.</div>')
    _, mid, _ = st.columns([1, 1.4, 1])
    with mid:
        tab_in, tab_up = st.tabs(["Sign in", "Create account"])
        with tab_in:
            email = st.text_input("Email", key="si_email")
            password = st.text_input("Password", type="password", key="si_pw")
            if st.button("Sign in", type="primary", key="si_go"):
                try:
                    sign_in(email.strip(), password)
                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not sign in: {_auth_message(exc)}.")
        with tab_up:
            name = st.text_input("Name", key="su_name")
            role = st.radio("I am a", ["candidate", "recruiter"], horizontal=True, key="su_role")
            email = st.text_input("Email", key="su_email")
            password = st.text_input("Password (at least 8 characters)", type="password", key="su_pw")
            if st.button("Create account", type="primary", key="su_go"):
                if len(password) < 8:
                    st.error("Use a password with at least 8 characters.")
                else:
                    try:
                        if sign_up(email.strip(), password, name.strip(), role):
                            st.rerun()
                        st.success("Account created. Check your email to confirm it, then sign in.")
                    except Exception as exc:
                        st.error(f"Could not create the account: {_auth_message(exc)}")
        if st.button("Try without an account (results are not saved)", key="demo_go"):
            st.session_state["demo"] = True
            st.rerun()

        
