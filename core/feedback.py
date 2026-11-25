"""Phase 5: structured feedback (pros, cons, tips). Uses RAG + an LLM, with a rules-only fallback.

generate_feedback() takes what Phases 1 to 4 produced. The ATS score and the integrity result awlays come from code.
The LLM only writes the explanation, and every reply passes core/guardrails.py before it is shown.

"""
from __future__ import annotations
from pydantic import BaseModel, Field, field_validator
from RAG_pipeline.Retrieval import retrieve_context
from dotenv import load_dotenv
load_dotenv()
 

COMPONENT_LABELS = {'parsability': 'formatting and parsability', 'keyword_match': 'keywords and skills', 
                    'sections': 'resume sections', 'experience_quality': 'experience and bullet quality',
                    'readability': 'readability and length'}

BULLET_TEMPLATE = 'Built [what you made]using [tool or method], which [result, for example reduced X by Y%].'

class Suggestion(BaseModel):
    title: str
    advice: str
    example_bullet: str | None = None

    @field_validator('example_bullet', mode='before')
    @classmethod
    def _empty_to_none(cls, v):
        return v or None


class Feedback(BaseModel):
    summary: str 
    pros: list[str]
    cons: list[str]
    missing_skills: list[str] = Field(default_factory=list)
    suggestions: list[Suggestion] = Field(default_factory=list)
    

    @field_validator('suggestions', mode='before')
    @classmethod
    # def _allow_plain_strings(cls, v):
    #     return [{'title': 'Tip', 'advice': x}if isinstance(x, str)else x for x in (v or [])]
    def _allow_plain_strings(cls, v):
        if v is None:
            return []
        if not isinstance(v, list):
            v = [v]
        return [
            {'title': 'Tip', 'advice': x} if isinstance(x, str) else x
            for x in v
        ]


def _integrity_dict(integrity):
    if integrity is None:
        return None
    return integrity.to_dict() if hasattr(integrity, 'to_dict') else integrity

def integrity_notice(integrity) -> str | None:
    """A fixed, code-written message. It never repeats the hidden text itself."""
    data = _integrity_dict(integrity)
    if not data or data.get('risk') == 'clean':
        return None
    kinds = []
    for f in data['findings']:
        words = f['evidance'].get('words')
        kinds.append(f['flag_type'].replace("_", " ") + (f" ({words} words)" if words else ""))
    level = 'high risk' if data['risk'] == 'high_risk' else 'needs review'
    return (f"Integrity check: {level}. Found: {', '.join(kinds)}. Hidden text was left out of the score and of this feedback."
            "A recruiter should review the evidence before any decision.")

def build_analysis(score: dict, integrity = None, job_fit: dict | None = None) -> str:
    """The trusted facts given to the LLM. It lists counts and types only, never text taken from the resume."""
    comps = score['components']
    lines = [f"ATS score: {score['total']}/100 ({score['band']})",
             "Components: "+"; ".join(f"{k} {v['score']}/{v['max']}" for k, v in comps.items()), 
             f"Role used: {score['role_used']}",
             "Core skills found: "+ (", ".join(score['matched_skills']) or 'none'),
             "Core skills not found: " + (", ".join(score['matched_skills']) or 'none')]
    by_loss = sorted(comps.items(), key=lambda kv: kv[1]['max']- kv[1]['score'], reverse=True)
    issues = [i for _, c in by_loss for i in c['issues']][:6]
    strengths = [s for _, c in by_loss for s in c['strengths']][:4]
    lines += ['Problems found by the scorer:'] + [f'-{i}' for i in issues]
    lines += ['Strengths found by the scorer:'] + [f'- {i}' for i in strengths]
    if score.get('jd'):
        jd = score['jd']
        lines.append(f"Job description match: similarity {jd['similarity']} ({jd['method']}); skills in the JD not shown in the resume:" + 
                     (", ".join(jd['missing_jd_skills']) or 'none'))
    if job_fit and job_fit.get('roles'):
        top = ', '.join(f"{r['role']} ({r['fit_score']})" for r in job_fit['roles'])
        lines.append(f"Best-fit roles: {top}")
        if job_fit.get('fields'):
            lines.append(f"Classifier category: {job_fit['fields'][0]['field']}; method agree: {job_fit.get('agreement')}")
    data = _integrity_dict(integrity)
    if data:
        kinds = ", ".join(f"{r['role']} ({r['fit_score']})" for r in job_fit['roles'])
        lines.append(f"Best-fit roles: {top}")
        if job_fit.get('fileds'):
            lines.append(f"Classifier category: {job_fit['fields'][0]['field']}; methods agree: {job_fit.get('agreement')}")
    data = _integrity_dict(integrity)
    if data:
        kinds = ", ".join(f"{f['flag_type']} ({f['severity']})" for f in data['findings']) or 'none'
        lines.append(f"Integrity: {data['risk']}; findings: {kinds}. Hidden text was excluded from the resume text below.")
    return "\n".join(lines)


def rule_based_feedback(score: dict, integrity = None)-> Feedback:
    """Feedback built only from the scorer's findings. Used when the LLM or the knowledge base is unavailable."""
    comps = score['components']
    by_loss = sorted(comps.items(), key=lambda kv: kv[1]['max'] - kv[1]['score'], reverse=True)
    pros = [s for _, c in by_loss for s in c['strengths']][:4] or ['Your resume could be read by the system.']
    cons = [i for _, c in by_loss for i in c['issues']][:4] or ['No major problems were found.']
    Suggestions = []
    for name, comp in by_loss:
        if comp['issues'] and len(Suggestions) < 4:
            bullet = BULLET_TEMPLATE if name == 'experience_quality' else None
            Suggestions.append(Suggestion(title = f"Improve {COMPONENT_LABELS[name]}", advice=comp['issues'][0], example_bullet=bullet))
    if not Suggestions:
        Suggestions = [Suggestion(title = 'keep it up', advice='Tailor the skills and bullets to each job description.')]
    worst = [COMPONENT_LABELS[n] for n, c in by_loss[:2] if c['max'] - c['score'] > 0.5]
    gaps = f"The biggest gains are in: {'; '.join(worst)}." if worst else ""
    return Feedback(summary=f"Your resume scored {score['total']}/100 ({score['band'.replace('_', ' ')]}).{gaps}", 
                    pros=pros, cons=cons, missing_skills = list(score['missing_skills']), suggestions = Suggestions)


def generate_feedback(visibile_text: str, score: dict, integrity= None, job_fit: dict | None = None,
                      job_description: str | None = None, llm = None, store = None, use_llm: bool = True) -> dict:
    """Return {'feedback', 'source' ('llm' or 'rules'), 'sources', 'role', 'integrity_notic', 'guardrails'}.
    visible_text must come from the integrity scan. job_description is already part of 'score' when it was used. """
    role = score['role_used']
    data = _integrity_dict(integrity)
    flagged = bool(data and data.get('risk') != 'clean')
    notes, flags, context, sources = [], [], "", []
    feedback, source = None, 'rules'

    if use_llm:
        from RAG_pipeline.Generation import generate, get_llm # if it place outside of this function then circular import error is occur so that's why I place this import here.
        try:
            context, sources = retrieve_context(role, score, flagged, store=store)
        except Exception as exc:
            notes.append(f"Knowledge base unavailable ({type(exc).__name__}); continuing without extra context.")
        try:
            result = generate(llm or get_llm(), visibile_text, role, build_analysis(score, integrity, job_fit), context)
            notes += result['notes']
            flags += result['flags']
            if result['feedback'] is not None and (result['feedback'].pros or result['feedback'].cons):
                feedback, source = result['feedback'], 'llm'
        except Exception as exc:
            notes.append(f"LLM unavailable ({type(exc).__name__}); used rule-based feedback.")

    if feedback is None:
        feedback = rule_based_feedback(score, integrity)
        sources = []
    return {'feedback': feedback.model_dump(), 'source': source, 'sources': sources, 'role': role, 
            'integrity_notice': integrity_notice(integrity), 'guardrails': {'notes': notes, 'flags': flags}}



