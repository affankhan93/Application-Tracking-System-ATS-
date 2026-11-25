"""Look and feel copied from the ATS System UI mockup: Colours, cards, chips, bars, ring and top navigation."""

import html
import streamlit as st 

CSS = """<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');
html, body, .stApp, .stMarkdown, button, input, textarea, select { font-family: 'Inter', system-ui, sans-serif !important; }
.stApp { background: #F4F6FA; color: #14213D; }
header[data-testid="stHeader"], [data-testid="stToolbar"], footer, #MainMenu { display: none !important; }
.block-container { max-width: 1200px; padding: 0 24px 48px; }
/* navigation bar */
.st-key-topnav { background: #fff; border: 1px solid #DDE2EC; border-top: 0; border-radius: 0 0 12px 12px; padding: 4px 24px; margin-bottom: 24px; }
.st-key-topnav a { font-size: 14px; color: #14213D; text-decoration: none; padding: 6px 0; }
.st-key-topnav a[aria-current="page"], .st-key-topnav a[aria-current="page"] p { font-weight: 600; background: transparent; }
.ats-brand { font-size: 16px; font-weight: 600; color: #2457D6; }
/* cards, text, chips, bars (same values as the mockups) */
.ats-c { background: #fff; border: 1px solid #DDE2EC; border-radius: 12px; padding: 20px; margin-bottom: 20px; }
.ats-t { font-size: 15px; font-weight: 600; margin: 0 0 14px; }
.ats-m { color: #5B6475; font-size: 13px; }
.ats-h1 { margin: 0; font-size: 24px; font-weight: 600; line-height: 1.3; }
.ats-chip { display: inline-block; padding: 2px 10px; border-radius: 99px; font-size: 12px; font-weight: 600; }
.ats-g { background: #E3F6EC; color: #05603A; } .ats-y { background: #FEF0C7; color: #93370D; }
.ats-r { background: #FEE4E2; color: #B42318; } .ats-n { background: #EEF1F6; color: #5B6475; }
.ats-bar { height: 8px; border-radius: 4px; background: #E6EAF2; }
.ats-bar i { display: block; height: 8px; border-radius: 4px; background: #2457D6; }
.ats-row { display: flex; justify-content: space-between; font-size: 14px; margin-bottom: 6px; }
.ats-c ul { margin: 0; padding-left: 18px; font-size: 14px; line-height: 1.7; }
.ats-c ul.ats-plain { list-style: none; padding: 0; line-height: 1.5; display: flex; flex-direction: column; gap: 14px; }
.ats-th { color: #5B6475; font-weight: 500; font-size: 13px; }
.ats-td { font-size: 14px; }
.ats-rule { border-bottom: 1px solid #E6EAF2; margin: 4px 0 8px; }
/* Streamlit widgets styled like the mockup buttons */
.stButton button, .stDownloadButton button { border-radius: 8px; border: 1px solid #C5CCDA; font-size: 14px; font-weight: 500; padding: 10px 16px; background: #fff; color: #14213D; min-height: 0; }
.stButton button[data-testid="stBaseButton-primary"], .stDownloadButton button[data-testid="stBaseButton-primary"] { background: #2457D6; border-color: #2457D6; color: #fff; }
[data-testid="stVerticalBlockBorderWrapper"] { background: #fff; border-color: #DDE2EC; border-radius: 12px; }
</style>"""

RISK = {'clean': ("Clean", 'g'), 'review': ('Review', 'y'), 'high_risk': ('High risk', 'r')}
SEVERITY = {'high': ("High", 'r'), 'medium': ('Medium', 'y'), 'low': ('Low', 'n')}
BAND_TEXT = {'strong': "Strong. Only minor polishing is needed.", "good": "Good. A few fixes can lift it above 85.",
             'needs_work': "Needs work. Several important gaps.", "weak": "Weak. Needs a rewrite of structure and content."}
COMPONENT_NAMES = {'parsability': 'Parsability', 'keyword_match': 'Keyword match', 'sections': 'Sections', 
                   'experience_quality': 'Experience quality', 'readability': 'Readability'}

def esc(value) -> str:
    """Escape anything that came from a resume or a user before it goes into HTML."""
    return html.escape(str(value), quote=True)

def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)

def html_block(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)

def chip(text: str, kind: str) -> str:
    return f'<span class= "ats-chip ats-{kind}"> {esc(text)}</span>'

def risk_chip(risk: str) -> str:
    label, kind = RISK.get(risk, ('Unknown', 'n'))
    return chip(label, kind)

def progress_row(label: str, right: str, pct: float, last: bool = False) -> str:
    gap = "" if last else ' style="margin-bottom: 14px"'
    return (f'<div class = "ats-row"><span>{esc(label)}</span> <span>{esc(right)}</span></div>'
            f'<div class = "ats-bar"{gap}><i style = "width:{max(0, min(100, pct)):.0f}%"></i></div>')


def card(inner: str, style: str = "")-> str:
    return f'<div class = "ats-c" style="{style}"> {inner}</div>'

def score_ring(total: int, caption: str)-> str:
    return card(
        '<div style="width:150px;height:150px;border-radius:50%;margin:0 auto 14px;'
        f'background:conic-gradient(#2457D6 0 {total}%,#E6EAF2 0);display:flex;align-items:center;justify-content:center">'
        '<div style="width:114px;height:114px;border-radius:50%;background:#fff;display:flex;flex-direction:column;'
        f'align-items:center;justify-content:center"><b style="font-size:36px">{total}</b><span class="ats-m">of 100</span></div></div>'
        f'<div style="font-weight:600">ATS friendly score</div><div class="ats-m" style="margin-top:4px">{esc(caption)}</div>',
        "text-align:center") 


def render_nav(pages: dict, user: dict | None, demo: bool, show_candidates: bool) -> None:
    """Top bar: brand, Upload, Reports, Candidates, and the account on the right."""
    with st.container(key='topnav'):
        cols = st.columns([1.5, 0.9, 0.9, 1.1, 2.6, 2.0], vertical_alignment='center')

        cols[0].markdown('<span class ="ats-brank"> ATS System</span>', unsafe_allow_html=True)
        cols[1].page_link(pages['upload'], label='Upload')
        cols[2].page_link(pages['reports'], label='Reports')

        if show_candidates:
            cols[3].page_link(pages['candidates'], label='Candidates')
        if user:
            cols[5].markdown(f'<div class = "ats-m" style = "text-align:right"> {esc(user['email'])}</div>', unsafe_allow_html=True)
            if cols[5].button("Sign out", key='nav_signout'):
                from core.db import sign_out
                sign_out()
                st.rerun()
        else:
            cols[5].markdown('<div class = "ats-m" style="text-align:right"> Demo mode, results are not saved</div>', unsafe_allow_html=True)

            