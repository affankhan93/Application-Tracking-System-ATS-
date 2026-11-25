"""Phase 3: ATS score out of 100 in two steps.

1. rule-based : The five components of knowledge/scoring/ats_score_rubric.md.
2. (Job-description match): When a Job description is given, the keyword component also uses skill overlap with the job description 
and an embedding similarity between the resume and the job description.

Always pass `visible_text` form the integrity scan, so hidden test cannot raise the score.
"""
from __future__ import annotations
import csv 
import math
import os 
import pathlib
import re 
import statistics
from core.parser import ParsedResume, split_sections


WEIGHTS = {'parsability': 20, 'keyword_match': 30, 'sections' : 15, 'experience_quality': 25, 'readability' : 10}
BANDS = [(85, 'strong'), (70, 'good'), (55, 'needs_work'), (0, 'weak')]

ROLE_PROFILES_CSV = pathlib.Path(__file__).resolve().parent.parent / "data" / "role_profiles.csv"
TARGET_COVERAGE = 0.7        # Reaching this share of the required skills earns fulll keyword credit.
LIST_ONLY_CREDIT = 0.6       # A skill that appears only in a list, not in a bullet point, earns this share.
SEMANTIC_SHARE = {'embeddings': 0.35, 'tfidf': 0.15}  # share of the keyword component give to similarity; the offline TF-IDF method is less reliable, so it counts less
MIN_JD_SKILLS = 3          # Fewer recongnised skills than this in the Job description fall back to the role profile
SIMILARITY_RANGE = {'embeddings': (0.02, 0.70), 'tfidf' : (0.5, 0.35)} # cosine range mapped to 0..1, tune on my data

SECTION_HINTS = {'experience', 'projects', 'eduction', 'achievements', 'certifications'}  # section that count as evidence

EXTRA_SKILLS = [
    "git", "github", "linux", "bash", "fastapi", "flask", "django", "spring boot", "mysql", "postgresql", "mongodb",
    "nlp", "computer vision", "deep learning", "machine learning", "xgboost", "jenkins", "terraform", "ansible",
    "prometheus", "grafana", "helm", "azure", "gcp", "figma", "typescript", "next.js", "jest", "hubspot", "mailchimp",
    "canva", "semrush", "ahrefs", "ga4", "looker", "dax", "snowflake", "spark", "hadoop", "airflow", "mlflow", "dvc",
    "hugging face", "langchain", "llm", "scrum", "agile", "jira", "react", "node.js", "html", "css", "javascript",
    "java", "python", "c++", "sql", "excel", "tableau", "power bi", "tensorflow", "pytorch", "docker", "kubernetes",
    "aws", "seo", "tally", "gst", "sap",
]

ALIASES = {
    "scikit-learn" : ["sklearn", "scikit learn"], "power bi": ["powerbi"], "node.js": ["nodejs", "node js"],
    "postgresql": ["postgres"], "aws": ["amazon web services"], "gcp": ["google cloud"], "ci/cd": ["ci cd", "cicd"],
    "machine learning": ["ml model", "ml models"], "javascript": ["js", "ecmascript"],
    "data visualization": ["data visualisation", "matplotlib", "seaborn", "tableau", "power bi", "plotly"],
    "kubernetes": ["k8s"], "google analytics": ["ga4"], "a/b testing": ["ab testing", "a/b tests", "a/b test"],
    "recruitment": ["recruiting", "talent acquisition", "hiring"], "financial reporting": ["financial statements"],
    "social media": ["social media marketing", "instagram", "linkedin ads"], "seo": ["search engine optimization", "search engine optimisation"],
    "model deployment": ["deployed", "deployment of models"], "rest apis": ["rest api", "restful api", "restful"],
}

ACTION_VERBS = set("""built developed designed implemented engineered automated deployed launched created delivered shipped
wrote configured integrated migrated refactored optimised optimized analysed analyzed evaluated modelled modeled
forecasted identified validated tested trained cleaned merged standardised standardized presented documented negotiated
collaborated reported led coordinated mentored organised organized managed reduced increased improved streamlined
accelerated simplified raised cut grew resolved fixed ran conducted performed prepared processed reconciled filed
maintained closed recruited onboarded screened interviewed scheduled planned executed researched produced published
drove generated achieved secured saved boosted expanded redesigned rebuilt tracked monitored administered audited
budgeted supervised digitised digitized entered verified compared applied set established introduced revamped scaled
earned won completed investigated diagnosed debugged compiled extracted visualised visualized queried""".split())

WEAK_PHRASES = re.compile(r"\b(responsible for | worked on | helped with | helped to | involved in | duties included | participated in | assisted with | assited in | tasked with)\b", re.I)
BULLET_MARK = re.compile(r"^\s*[--•*▪–·●◦]\s*")

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE = re.compile(r"(?<!\d)(?:\+?\d[\s-]?){10, 13}(?!\d)")
LINK = re.compile(r'(linkedin\.com|github\.com|gitlab\.com|https?://\S+|www\.\S+)', re.I)
MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
DATE_STYLES = {
    'year range': re.compile(r"\b(?:19|20)\d{2}\s*[-–to]+\s*(?:(?:19|20)\d{2}|present|current)\b", re.I),
    'month year': re.compile(rf"\b{MONTH}\s+(?:19|20)\d{{2}}\b", re.I),
    'numeric month/year': re.compile(r"\b\d{1,2}/(?:19|20)\d{2}\b"),
}

# helpers 
def _round(x: float)-> float:
    return round(x + 1e-9, 1)

def _component(max_points: int)->dict:
    return {'score': 0.0, 'max': max_points, 'strengths': [], 'issues': []}

def load_role_profiles(path=ROLE_PROFILES_CSV) -> dict:
    """role -> list of core skills (lower case), from data/role_profiels.csv"""
    profiles = {}
    with open(path, encoding='utf-8-sig') as fh:
        for row in csv.DictReader(fh):
            profiles[row['role']] = [s.strip().lower() for s in row['core_skills'].split(';') if s.strip()]
    return profiles

def _variants(term: str, aliases: bool = True)-> list[str]:
    out = [term] + (ALIASES.get(term, []) if aliases else [])
    out += [v[:-1] for v in list(out) if v.endswith('s')]
    return out 

def has_term(text_lower: str, term: str, aliases: bool = True) -> bool:
    for v in _variants(term.lower(), aliases):
        if re.search(r"(?<![a-z0-9+#])" + re.escape(v) + r"(?![a-z0-9+#])", text_lower):
            return True
    return False

def _skill_credit(term: str, evidence: str, everything: str)-> float:
    if has_term(evidence, term):
        return 1.0
    if has_term(everything, term):
        return LIST_ONLY_CREDIT
    return 0.0 

def _split(visible_text: str):
    sections = split_sections(visible_text)
    evidence = "\n".join(v for k, v in sections.items() if k in SECTION_HINTS).lower()
    if not any(k in SECTION_HINTS for k in sections):
        evidence = '\n'.join(v for k, v in sections.items() if k != 'skills').lower()
    return sections, evidence


def _bullets(sections: dict, visible_text: str)-> list[str]:
    body = '\n'.join(v for k, v in sections.items() if k in {'experience', 'projects'})
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    marked = [BULLET_MARK.sub("", ln) for ln in lines if BULLET_MARK.match(ln)]
    return marked if marked else [ln for ln in lines if len(ln.split()) >= 6]

def _looks_multicolumn(parsed: ParsedResume)-> bool:
    lines = {}
    for s in parsed.spans:
        if s.bbox is None:
            continue
        ln = lines.setdefault(s.line, {'x0': s.bbox[0], 'y0': s.bbox[1], 'x1':s.bbox[2], 'y1':s.bbox[3], 'page': s.page, 'words':0})
        ln['x0'], ln['y0'] = min(ln['x0'], s.bbox[0]), min(ln['y0'], s.bbox[1])
        ln['x1'], ln['y1'] = max(ln['x1'], s.bbox[2]), max(ln['y1'], s.bbox[3]) 
        ln['words'] += len(s.text.split())

    for pno, (width, _) in enumerate(parsed.page_sizes):
        page_lines = [ln for ln in lines.values() if ln['page'] == pno]
        left = [ln for ln in page_lines if ln['x0'] < 0.30 * width]
        right = [ln for ln in page_lines if ln['x1'] > 0.45 * width and ln['words'] >= 4 and ln['x1'] - ln['x0'] < 0.5 * width]
        beside = sum(any(l['y0'] < r['y1'] and r['y0'] < l['y1'] and l['x1'] < r['x0']for l in left) for r in right)
        if len(right) >= 5 and beside / len(right) >= 0.5:
            return True
    return False


# Job description similarity 
def pinecone_embed(texts: list[str])-> list[list[float]]:
    from langchain_pinecone import PineconeEmbeddings
    return PineconeEmbeddings(model = 'llama-text-embed-v2', dimension=1024).embed_documents(texts)

def _cosine(a, b)-> float:
    dot = sum(x*y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y*y for y in b))
    return dot / (na * nb) if na and nb else 0.0 


def jd_similarity(resume_text: str, jb_text: str, embed_fn = None)-> tuple[float, str]:
    """Cosine similarity between resume and job description, and the method used ('embeddings' or 'tfidf')."""
    if embed_fn is None and os.environ.get('PINECONE_API_KEY'):
        embed_fn = pinecone_embed
    if embed_fn is not None:
        try:
            a, b = embed_fn([resume_text, jb_text])
            return _cosine(a, b), 'embeddings'
        except Exception:
            pass 
    from sklearn.feature_extraction.text import TfidfVectorizer
    ml = TfidfVectorizer(stop_words='english', ngram_range=(1, 2), sublinear_tf=True, use_idf=False).fit_transform([resume_text, jb_text])
    return float((ml[0].multiply(ml[1])).sum()), 'tfidf'

def _scale(sim:float, method: str)-> float:
    lo, hi = SIMILARITY_RANGE[method]
    return max(0.0, min(1.0, (sim - lo) / (hi - lo)))


# components
def _parsability(parsed: ParsedResume, visible_text: str, sections: dict) -> dict:
    c, pts = _component(WEIGHTS['parsability']), WEIGHTS['parsability']
    words = len(visible_text.split())
    if parsed.source == 'pdf-ocr':
        pts -= 8
        c['issues'].append("The file is a scan with no text layer, so the text was read with OCR, which can make mistakes. Export a text-based PDF from Word or google docs.")
    if words < 80:
        pts -= 5
        c['issues'].append("Very little text could be read from the file. Check that the resume is not an image.")
    if parsed.source != 'docx' and _looks_multicolumn(parsed):
        pts -=6 
        c['issues'].append("The layout has multiple columns, which can scramble the reading order. Use a single column.")
    found = [k for k in ('summary', 'skills', 'experience', 'projects', 'education')if k in sections]
    if len(found) < 2:
        pts -= 5
        c['issues'].append("Few standard section headings were found. Use Summary, Skills, Experience, Projects, and Education.")
    odd = sum(1 for ch in visible_text if ch == '\ufffd' or '\ue000' <= ch <= '\uf8ff')
    if words and odd / max(len(visible_text), 1) > 0.02:
        pts -= 4
        c['issues'].append("Some characters could not be read properly. Avoid special symbols and icons.")
    if not c['issues']:
        c['issues'].append("Clean single-column text with standard headings.")
    c['score'] = max(0.0, pts)
    return c 


def _keyword_match(visible_text, sections, evidence, role, job_description, embed_fn, profiles):
    c = _component(WEIGHTS['keyword_match'])
    lower = visible_text.lower()
    coverage = {}
    for name, skills in profiles.items():
        credits = [_skill_credit(s, evidence, lower) for s in skills]
        coverage[name] = sum(credits) / len(credits) if credits else 0.0 
    role_used = role if role in profiles else max(coverage, key = coverage.get)
    credits = {s: _skill_credit(s, evidence, lower)for s in profiles[role_used]}
    role_part = min(1.0, coverage[role_used] / TARGET_COVERAGE)
    matched = [s for s, v in credits.items() if v > 0]
    missing = [s for s, v in credits.items() if v == 0]
    info = {'role_used': role_used, 'matched_skills': matched, 'missing_skills': missing[:8], 'jb':None}

    skill_part = role_part
    if job_description:
        vocab = sorted({s for sk in profiles.values() for s in sk} | set(EXTRA_SKILLS))
        jd_lower = job_description.lower()
        jd_skills = [t for t in vocab if has_term(jd_lower, t, aliases=False)] # exact terms only: 'hiring' must not count as 'recruitement'
        sim, method = jd_similarity(visible_text, job_description, embed_fn)
        semantic = _scale(sim, method)
        if len(jd_skills) >= MIN_JD_SKILLS:
            jd_credits = {s: _skill_credit(s, evidence, lower)for s in jd_skills}
            skill_part = min(1.0, (sum(jd_credits.values()) / len(jd_credits)) / TARGET_COVERAGE)
            jd_missing = [s for s, v in jd_credits.items() if v == 0]
        else:
            jd_missing = []
            c['issues'].append("The job description names few recognisable skills, so the role profile was also used.")
        share = SEMANTIC_SHARE[method]
        total = (1 - share) * skill_part + share * semantic
        info['jd'] = {'similarity': round(sim, 3), 'similarity_scaled': round(semantic, 2), 'method': method, 'skills_in_jd': jd_skills, 'missing_jd_skills': jd_missing[:10]}
        c['score'] = c['max'] * total
        if jd_missing:
            c['issues'].append("Skills in the job description that the resume does not show: " + ", ".join(jd_missing[:6]) + ".")
        if semantic >= 0.6:
            c['strengths'].append("The wording of the resume is close to the job description.")
    else:
        c['score'] = c['max'] * role_part
        if missing:
            c ['issues'].append(f"Core {role_used} skills not found: "+", ".join(missing[:6]) + ".Add them only if you have used them, with a project or bullet as proof.")
    list_only = [s for s, v in credits.items() if v == LIST_ONLY_CREDIT]
    if list_only:
        c['issues'].append("These skills appear only in a list, with no bullet showing how they were used." +", ".join(list_only[:5]) + ".")
    if role_part >= 0.8:
        c['strengths'].append(f"Covers most of the core skills for {role_used}.")
    return c, info


def _sections_component(visible_text: str, sections: dict) -> dict:
    c, pts = _component(WEIGHTS['sections']), 0
    checks = [
        (2, bool(EMAIL.search(visible_text)), 'email address', "Add a professional email address."),
        (1, bool(PHONE.search(visible_text)), 'phone number', 'Add a phone number.'),
        (2, bool(LINK.search(visible_text)), "LinkedIn, GitHub or portfolio link", "Add links to your GithHub, LinkedIn, or portfolio."),
        (2, 'summary' in sections, 'summary', "Add a 2 to 3 line summary with your target role and strongest skills."),
        (3, 'skills' in sections, 'skills section', 'Add a Skills section grouped by type.'),
        (3, 'experience' in sections or 'projects' in sections, 'experience or projects', "Add an Experience or Projects section."),
        (2, 'education' in sections, 'education section', "Add an Education section.")
    ]
    present = []
    for points, ok, name, fix in checks:
        if ok:
            pts += points
            present.append(name)
        else:
            c['issues'].append(f"Missing {name}. {fix}")
    if present:
        c['strengths'].append("Found: " + ", ".join(present) +  ".")
    c['score'] = pts
    return c 


def _experience_quality(sections: dict, visible_text: str, profiles: dict)->dict:
    c = _component(WEIGHTS['experience_quality'])
    bullets = _bullets(sections, visible_text)
    if not bullets:
        c['issues'].append("No experience or project bullets were found. Describe what you did in 3 to 5 bullets per role or projects.")
        return c 
    vocab = {s for sk in profiles.values() for s in sk} | set(EXTRA_SKILLS)
    n = len(bullets)
    first = [BULLET_MARK.sub("", b).split()[0].lower().strip(",.:,") if b.split() else "" for b in bullets]
    verb = sum(f in ACTION_VERBS for f in first) / n 
    weak = sum(bool(WEAK_PHRASES.search(b)) for b in bullets) / n
    no_years = [re.sub(r'(?<!\d)(?:19|20)\d{2}(?!\d)', '', b) for b in bullets]
    quant = sum(bool(re.search(r"\d", b))for b in no_years) / n 
    spec = sum(any(has_term(b.lower(), t)for t in vocab)for b in bullets) / n
    count_factor = min(1.0, n/4)
    c['score'] = c['max'] * count_factor * (0.35 * quant + 0.30 * verb + 0.20 * spec + 0.15 * (1- weak))
    if n < 4:
        c['issues'].append(f"Only {n} bullet(s) found. Aim for 3 to 5 per role or project.")
    if quant < 0.5:
        c['issues'].append("Most bullets have no numbers. Add results such as time saved, accuracy, users, letancy, using real figures.")
    else:
        c['strengths'].append("Bullets include measurable results.")
    if verb < 0.6:
        c['issues'].append("Many bullets do no start with a strong action verb such as Built, Reduced, or Automated.")
    else:
        c['strengths'].append("bullets start with strong actoins verbs.")
    if weak > 0:
        c['issues'].append("Replace weak phrases like 'worked on' and 'responsible for' with wath you achieved.")
    if spec < 0.5:
        c['issues'].append("Name the tools and methods you used inside the bullets.")
    return c 


def _readability(parsed: ParsedResume, visible_text: str, sections: dict)-> dict:
    c, pts = _component(WEIGHTS['readability']), 0.0
    words = len(visible_text.split())
    length = 4.0 - 2 * max(0, parsed.page_count - 2) - (2 if words < 150 else 0) - (2 if words > 1100 else 0)
    pts += max(0.0, length)
    if parsed.page_count > 2:
        c['issues'].append("The resume is longer than 2 pages. Cut it to one page. or two at most. not more that")
    if words < 150:
        c['issues'].append("The resume is very short. Add detail about your projects/internship and experince.")
    if words > 1500:
        c['issues'].append("The resume is very long. Keep it focused on the target role.")
    bullets = _bullets(sections, visible_text)
    lengths = [len(b.split())for b in bullets]
    median = statistics.median(lengths) if lengths else None
    if median is None:
        pts += 1
    elif median <= 30:
        pts += 3
        c['strengths'].append("Bullets are short an easy to scan.")
    elif median <= 45:
        pts += 2
    else:
        pts += 1
        c['issues'].append("Bullets are long. keep each to one or two lines and one idea.")
    styles = [name for name, rx in DATE_STYLES.items() if rx.search(visible_text)]
    if len(styles) >= 2:
        pts += 1.5
        c['issues'].append("Dates are written in different formats (" + ", ".join(styles) + "). Use one format.")
    elif styles:
        pts += 3
        c['strengths'].append("Dates use one consistent format.")
    else:
        pts += 1.5
    c['score'] = min(c['max'], pts)
    return c 

def role_skill_coverage(visible_text: str, profiles: dict | None = None) -> dict:
    """For every role profile: share of its core skills shown in the resume (bullet = 1.0, list only = 0.6)."""
    profiles = profiles or load_role_profiles()
    _, evidence = _split(visible_text)
    lower = visible_text.lower()
    out = {}
    for role, skills in profiles.items():
        credits = {sk: _skill_credit(sk, evidence, lower) for sk in skills}
        out[role] = {'coverage': sum(credits.values()) / len(credits) if credits else 0.0, 
                     "matched": [k for k, v in credits.items() if v > 0],
                     "missing": [k for k, v in credits.items() if v == 0]}
    return out 

# public entry point 
def score_resume(parsed: ParsedResume, visible_text: str | None = None, role: str | None = None, job_description: str | None = None, embed_fn = None, profiles: dict | None = None) -> dict:
    """Score a resume out of 100. Pass the integrity report's visible_text. Returns a JSON-friendly dict."""
    warning = []
    if visible_text is None:
        visible_text = parsed.text
        warning.append("Scored the full text of the file. Run the integrity scan and pass visible_text so hidden texxt cannot raise the score.")
    profiles = profiles or load_role_profiles()
    sections, evidence = _split(visible_text)

    parts = {
        'parsability': _parsability(parsed, visible_text, sections),
        'sections': _sections_component(visible_text, sections), 
        'experience_quality': _experience_quality(sections, visible_text, profiles),
        'readability': _readability(parsed, visible_text, sections),
    }
    parts['keyword_match'], info = _keyword_match(visible_text, sections, evidence, role, job_description, embed_fn, profiles)
    for c in parts.values():
        c['score'] = _round(c['score'])
    total = int(round(sum(c['score']for c in parts.values())))
    band = next(name for floor, name in BANDS if total >= floor)

    by_loss = sorted(parts.items(), key=lambda kv: kv[1]['max'] - kv[1]['score'], reverse=True)
    suggestions = [c['issues'][0] for _, c in by_loss if c['issues']][:3]
    return {'total': total, 'band': band, 'components' : {k: parts[k] for k in WEIGHTS}, 'suggestions': suggestions, 'warnings': warning, **info}








