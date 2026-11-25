from __future__ import annotations
import datetime as dt
import hashlib
import os 
from core.feedback import generate_feedback
from core.integrity import scan
from core.job_fit import suggest_job_fit
from core.parser import parse_resume
from core.scoring import score_resume
from dotenv import load_dotenv


load_dotenv()

MAX_FILE_BYTES = 5 * 1024 * 1024

def llm_configured() -> bool:
    """The AI-written feedback needs and LLM and Pinecone. Without them the app uses rule-base feedback."""
    return bool(os.getenv("PINECONE_API_KEY") and os.getenv("GROQ_API_KEY"))

def file_hash(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest() 

def jd_match_percent(score: dict)-> int | None:
    """Share of the keyword component earned when a job description was used."""
    if not score.get('jd'):
        return None
    kw = score['components']['keyword_match']
    return round(100 * kw['score'] / kw['max'])

def analyze_resume(file_bytes: bytes, filename: str, job_description: str | None = None, 
                   jd_title: str | None = None, use_llm: bool | None = None) -> dict:
    if len(file_bytes) > MAX_FILE_BYTES:
        raise ValueError("The file is larher than 5 MB.")
    parsed = parse_resume(file_bytes, filename)
    report = scan(parsed, file_bytes)
    jd = (job_description or "").strip() or None
    score = score_resume(parsed, report.visible_text, job_description= jd)
    fit = suggest_job_fit(report.visible_text)
    feedback = generate_feedback(report.visible_text, score, report, fit, jd, 
                                 use_llm = llm_configured() if use_llm is None else use_llm)
    return {
        "file_name": filename, "file_hash": file_hash(file_bytes), 'analyzed_at': dt.datetime.now(dt.timezone.utc).isoformat(), 
        'pages': parsed.page_count, 'source': parsed.source, 'jd_title': jd_title,
        'integrity': report.to_dict(), 'score': score, 'job_fit': fit, 'feedback': feedback,
        'jd_match': jd_match_percent(score)
    }

