import streamlit as st 
from ui.store import get_store
from ui.views import render_report, render_upload

store = get_store()
if st.session_state.get('current'):
    render_report(st.session_state['current'], store)
else:
    render_upload(store)



