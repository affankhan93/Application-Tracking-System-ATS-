"""Phase 4: Which job field suits this resume. 

There are two methods. shown side by side:
    1. classifier (suggest_filed): The model trained on the kaggle Resume Dataset.
    2. Similarity ranking (rank_roles): ranks the 9 role profiels from data/role_profiles.csv by skill coverage plus
    text similarity. 

""" 

from __future__ import annotations
import pathlib
from functools import lru_cache
import joblib 
import numpy as np 
from core.text_utils import clean_text
import csv 
import os 
from core.scoring import ROLE_PROFILES_CSV, TARGET_COVERAGE, pinecone_embed, role_skill_coverage 
from core.text_utils import clean_text
from sklearn.feature_extraction.text import TfidfVectorizer

DEFAULT_MODEL = pathlib.Path(__file__).resolve().parent.parent / "ML_pipeline" / "Linear_SVC_model.pkl"
SKILL_SHARE = 0.6  # 60% is weight of skill coverage in the role ranking; the rest is 40% for text similarity.
TECH_ROLES = ['Data Scientist', 'Data Analyst', 'ML Engineer', 'Software Developer', 'Web Developer', 'DevOps Engineer']

CATEGORY_TO_ROLES = {
    "INFORMATION-TECHNOLOGY": TECH_ROLES,
    "HR": ['HR Executive'],
    "ACCOUNTANT": ['Accountant'],
    "FINANCE": ['Accountant'],
    "DIGITAL-MEDIA": ['Digital Marketing Executive']
}


# method 1 is classifier
@lru_cache(maxsize=2)
def _load(path: str):
    bundle = joblib.load(path)
    return bundle['model'], bundle.get('skip_words', 0)


def suggest_fields(resume, top_k: int = 5, model_path = DEFAULT_MODEL)-> list[dict]:
    """resume: ParsedResume or plain text. Once Phase 2 exists. pass the visible text only, becuase ParsedResume.text still contains any hidden text."""
    text = resume if isinstance(resume, str) else resume.text
    model, skipwords = _load(str(model_path))
    proba = model.predict_proba([clean_text(text, skipwords)])[0]
    order = np.argsort(proba)[::-1][:top_k]
    return [{'field': model.classes_[i], 'confidence': round(float(proba[i]), 3)} for i in order]

# method 2 is similarity ranking 
def load_role_documents(path = ROLE_PROFILES_CSV) -> dict:
    docs = {}
    with open(path, encoding='utf-8-sig') as file:
        for row in csv.DictReader(file):
            skills = [s.strip().lower() for s in row['core_skills'].split(";") if s.strip()]
            docs[row['role']] = {'skills': skills, 'text': f"{row['role']}. {row['description']} Skills: {','.join(skills)}."}
        return docs 
    
def _cosine(a, b)-> float:
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    return float(a @ b / (na * nb)) if na and nb else 0.0 

def _similarities(resume_text: str, role_texts: list[str], embed_fn)-> tuple[list[float], str]:
    if embed_fn is None and os.environ.get("PINECONE_API_KEY"):
        embed_fn = pinecone_embed
    if embed_fn is not None:
        try:
            vecs = embed_fn([resume_text] + role_texts)
            return [_cosine(vecs[0], v) for v in vecs[1:]], 'embeddings'
        except Exception:
            pass 
    matrix = TfidfVectorizer(stop_words='english', ngram_range=(1, 2), sublinear_tf=True).fit_transform([resume_text] + role_texts)
    sims = (matrix[1:] @ matrix[0].T).toarray().ravel()
    return [float(x) for x in sims], 'tfidf'

def rank_roles(resume, top_k: int = 3, embed_fn = None, role_docs: dict | None = None)-> tuple[list[dict], str]:
    """Rank the role profiles for a resume. Returns (ranked roles, similarity method used.)"""
    text = resume if isinstance(resume, str) else resume.text
    role_docs = role_docs or load_role_documents() 
    roles = list(role_docs)
    coverage = role_skill_coverage(text, {r: role_docs[r]['skills'] for r in roles})
    sims, method = _similarities(text, [role_docs[r]['text']for r in roles], embed_fn)
    lo, hi = min(sims), max(sims)
    ranked = []
    for role, sim in zip(roles, sims):
        skill_part = min(1.0, coverage[role]['coverage'] / TARGET_COVERAGE)
        sim_part = (sim - lo) / (hi - lo) if hi > lo else 0.5
        ranked.append({"role": role, "fit_score": round(100 * (SKILL_SHARE * skill_part + (1 - SKILL_SHARE) * sim_part)),
                               "skill_coverage": round(coverage[role]["coverage"], 2), "similarity": round(sim, 3),
                               "matched_skills": coverage[role]["matched"][:6], "missing_skills": coverage[role]["missing"][:4]})
    ranked.sort(key = lambda r: (-r['fit_score'], -r['skill_coverage']))
    return ranked[:top_k], method

# both together
def suggest_job_fit(resume, top_k: int = 3, model_path = DEFAULT_MODEL, embed_fn = None)-> dict:
    """{'roles' : ranked roles, 'fileds': classifier categories, 'agreement' : bool or None, 'method': ..., "notes": [..]}"""
    roles, method = rank_roles(resume, top_k, embed_fn)
    notes, fields = [], []
    if pathlib.Path(model_path).exists():
        fields = suggest_fields(resume, top_k, model_path)
    else:
        notes.append("Classifier model not found, so only the role ranking is shown.")
    agreement = None 
    if fields:
        allowed = CATEGORY_TO_ROLES.get(str(fields[0]['field']).upper())
        if allowed is not None:
            agreement = roles[0]['role'] in allowed
    return {'roles': roles, 'fields': fields, 'agreement': agreement, 'method': method, 'notes': notes}
