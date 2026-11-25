from __future__ import annotations
import datetime as dt
import streamlit as st 
from core.db import SupabaseStore, get_client, new_id 

class SessionStore:
    def __init__(self):
        self.data = st.session_state.setdefault("_demo_store", {'resumes': {}, 'jds': {}})

    def save(self, a: dict, jd_id: str | None = None) -> str:
        for rid, old in list(self.data['resumes'].items()):
            if old['file_hash'] == a['file_hash'] and old.get('jd_id') == jd_id:
                del self.data['resumes'][rid]
        rid = new_id()
        self.data['resumes']['rid'] = dict(a, id=rid, jd_id= jd_id, review_status = 'none')
        return rid 

    def list(self, jd_id: str | None = None, limit: int = 200):
        rows = []
        for rid, a in self.data['resumes'].items():
            if jd_id and a.get('jd_id') != jd_id:
                continue
            rows.append({"id": rid, "file_name": a["file_name"], "file_hash": a["file_hash"], "created_at": a["analyzed_at"],
                         "ats_total": a["score"]["total"], "top_role": a["job_fit"]["roles"][0]["role"],
                         "integrity_risk": a["integrity"]["risk"], "review_status": a["review_status"],
                         "jd_id": a.get("jd_id"), "jd_match": a.get("jd_match")})
        return sorted(rows, key= lambda r: r['created_at'], reverse=True)[:limit]

    def get(self, rid: str) -> dict | None:
        return self.data['resumes'].get(rid)

    def delete(self, rid: str) -> None:
        self.data['resumes'].pop(rid, None)

    def set_review(self, rid: str, status: str) -> None:
        if rid in self.data['resumes']:
            self.data['resumes'][rid]['review_status'] = status

    def list_jds(self) -> list[dict]:
        return [{'id': k, **v} for k, v in reversed(self.data['jds'].items())]

    def save_jd(self, title: str, body: str) -> str:
        jid = new_id()
        self.data['jds'][jid] = {'title': title, 'body': body}
        return jid 


def current_user() -> dict | None:
    return st.session_state.get('user')

def get_store():
    user = current_user()
    return SupabaseStore(get_client(), user['id']) if user else SessionStore()


def can_see_candidates() -> bool:
    user = current_user()
    return user is None or user['role'] == 'recruiter'

