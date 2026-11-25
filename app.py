import streamlit as st 
from core.db import supabase_configured
from ui.theme import inject_css, render_nav
from ui.store import can_see_candidates, current_user
from ui.views import render_login
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(
    page_title= "ATS System",
    page_icon="📄",
    layout='wide', 
    initial_sidebar_state='collapsed'
)

inject_css() 

if supabase_configured() and not current_user() and not st.session_state.get('demo'):
    render_login()
    st.stop()

PAGES = {
    'upload': st.Page("pages/1_Upload_report.py", title='Upload', url_path='upload', default=True),
    'candidates': st.Page("pages/2_Recruiter_Board.py", title="Candidates", url_path="candidates"),
    'integrity': st.Page("pages/3_Integrity.py", title= "Integrity", url_path='integrity'),
    'reports': st.Page("pages/4_History.py", title="Reports", url_path='reports')
}

navigation = st.navigation(list(PAGES.values()), position='hidden')
render_nav(PAGES, current_user(), bool(st.session_state.get("demo")) or not supabase_configured(), can_see_candidates())
navigation.run() 

