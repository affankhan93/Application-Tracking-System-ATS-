import streamlit as st 
from ui.store import current_user, get_store
from ui.views import render_integrity

analysis = st.session_state.get("current")
if analysis:
    user = current_user()
    anonymised = st.session_state.get("anonymised", True) and (user is None or user['role'] == 'recruiter')
    render_integrity(analysis, get_store(), anonymised)
else:
    st.info("Open a report first: upload a resume, or choose one from Reports or Candidates.")

    