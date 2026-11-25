"""Supabase access. Keep the logged-in client in st.session_state (never st.chache_resource)"""

from __future__ import annotations
import streamlit as st
import os 
import uuid
from dotenv import load_dotenv

load_dotenv() 


LIST_COLUMNS = 'id, file_name, file_hash, created_at, ats_total, top_role, integrity_risk, review_status, jd_id, jd_match'


def _secret(name: str):
    try:
        value = st.secrets.get(name)
    except Exception:
        value = None
    return value or os.getenv(name)

def supabase_configured() -> bool:
    return bool(_secret('SUPABASE_URL') and _secret('SUPABASE_API_KEY'))


def get_client():
    if '_sb' not in st.session_state:
        from supabase import create_client
        st.session_state['_sb'] = create_client(_secret('SUPABASE_URL'), _secret('SUPABASE_API_KEY'))
    return st.session_state['_sb']


# ACCOUNTS
def ensure_profile(client, user) -> dict:
    rows = client.table("profiles").select('role, full_name').eq('id', user.id).limit(1).execute().data
    if rows:
        return rows[0]
    meta = user.user_metadata or {}
    role = meta.get("role") if meta.get('role') in ('candidate', 'recruiter') else 'candidate'
    profile = {'id': user.id, 'role': role, 'full_name': meta.get('full_name')}
    client.table('profiles').insert(profile).execute()
    return {'role': role, 'full_name': profile['full_name']}

def sign_in(email: str, password: str) -> dict:
    client = get_client()
    res = client.auth.sign_in_with_password({'email': email, 'password': password})
    profile = ensure_profile(client, res.user)
    user = {'id': res.user.id, 'email': res.user.email, 'role': profile['role'], 'name': profile.get('full_name')}
    st.session_state['user'] = user
    return user 


def sign_up(email: str, password: str, name: str, role: str) -> bool:
    """True if the user is signed in straight away, False if the email must be confirmed first."""
    client = get_client()
    res = client.auth.sign_up({"email": email, 'password': password, 'options':{'data': {'role':role, 'full_name': name}}})

    if res.session is None:
        return False
    sign_in(email, password)
    return True


def sign_out() -> None:
    try:
        get_client().auth.sign_out()
    finally:
        for key in ('user', '_sb', 'current', 'demo'):
            st.session_state.pop(key, None)


# Storage
class SupabaseStore:
    def __init__(self, client, user_id: str):
        self.client, self.user_id = client, user_id


    def save(self, a: dict, jd_id: str | None = None) -> str:
        slim = dict(a)
        integrity = dict(a['integrity'])
        visible = integrity.pop("visible_text", "")
        slim['integrity'] = integrity
        row = {'owner_id': self.user_id, 'jd_id': jd_id, 'file_hash': a['file_hash'], 'file_name': a['file_name'],
               'parsed_text': visible, 'parsed_data': slim, 'ats_total':a['score']['total'],
               'top_role': a['job_fit']['roles'][0]['role'], 'integrity_risk': integrity['risk'], 'jd_match': a.get('jd_match')}
        rid = self.client.table('resumes').upsert(row, on_conflict = 'owner_id, file_hash').execute().data[0]['id']
        for table in ('scores', 'integrity_flags'):
            self.client.table(table).delete().eq('resume_id', rid).execute()
        self.client.table("scores").insert({'resume_id': rid, 'total': a['score']['total'], 'breakdown': a['score']['components'],
                                            'top_fields': a['job_fit']['roles']}).execute()

        if integrity['findings']:
            self.client.table('integrity_flags').insert([
                {'resume_id': rid, 'flag_type': f['flag_type'], 'severity': f['severity'], 'evidence': f['evidence']}
                for f in integrity['findings']]).execute()
        self.client.table("feedback_reports").upsert({'resume_id': rid, 'report': a['feedback']}).execute()
        return rid 

    def list(self, jd_id: str | None = None, limit: int = 200):
        query = self.client.table('resumes').select(LIST_COLUMNS).order("created_at", desc = True).limit(limit)
        if jd_id:
            query = query.eq('jd_id', jd_id)
        return query.execute().data or []

    def get(self, rid: str)-> dict | None:
        rows = self.client.table('resumes').select("*").eq('id', rid).limit(1).execute().data
        if not rows:
            return None
        row = rows[0]
        a = row['parsed_data']
        a['integrity']['visible_text'] = row.get('parsed_text') or ""
        a['id'], a['review_status'] = row['id'], row.get('review_status', 'none')
        return a

    def delete(self, rid: str) -> None:
        self.client.table('resumes').delete().eq('id', rid).execute()

    def set_review(self, rid: str, status: str) -> None:
        self.client.table('resumes').update({'review_status': status}).eq('id', rid).execute()

    def list_jds(self) -> list[dict]:
        return self.client.table("job_descriptions").select('id, title, body').order('created_at', desc = True).execute().data or []

    def save_jd(self, title: str, body: str)-> str:
        return self.client.table('job_descriptions').insert(
            {'recruiter_id': self.user_id, 'title': title, 'body': body}).execute().data[0]['id']

def new_id() -> str:
    return uuid.uuid4().hex

