import streamlit as st 
from ui.store import can_see_candidates, get_store
from ui.views import render_candidates

if can_see_candidates():
    render_candidates(get_store())
else:
    st.info("The Candidates page is for recruiter accounts.")
