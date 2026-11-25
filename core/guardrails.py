"""Prompt-injection guardrails for the RAG feedback step. 

Input side: clean the resume text, remove instruction-like phrases, and wrap it so the model sees it as data.
Output side: reject or trim a reply that leaked the secret, repeats instructions, adds links, or names skills 
            the resume already shows as missing.
"""

from __future__ import annotations 
import json
import re 
import secrets
from core.integrity import INJECTION_PATTERNS, ZERO_WIDTH_RE
from core.scoring import has_term

START, END = '<<<RESUME_START>>>', '<<<RESUME_END>>>'
MAX_RESUME_CHARS = 12000
MAX_ITEM_CHARS = 400 
MAX_ITEMS = 5
REDACTION = '[insturction-like text removed]'
ROLE_LINE_RE = re.compile(r'^[ \t]*(system|assistant|user|developer|human|ai)[ \t]*:', re.I | re.M)
CONTROL_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
URL_RE = re.compile(r"https?://|www\.", re.I)
LEAK_PHRASES = ("security rules", "untrusted candidate data", "resume_start", "resume_end")

def make_canary() -> str:
    """A random code placed in the system prompt. If it shows up in the reply, the prompt leaked."""
    return "CANARY- "+ secrets.token_hex(4)

def sanitize_resume_text(text: str)-> tuple[str, list[str]]:
    """Return (clean text, notes). Use only the integrity scan's visible text as input."""
    notes = []
    text = CONTROL_RE.sub("", ZERO_WIDTH_RE.sub("", text))
    for marker in (START, END, "RESUME_START", 'RESUME_END'):
        text = text.replace(marker, "")
    text = text.replace("<<<", "<").replace(">>>", ">")
    removed = 0 
    for pattern in INJECTION_PATTERNS:
        text, n = pattern.sub(REDACTION, text)
        removed += n
    text, n = ROLE_LINE_RE.subn("[role label removed]:", text)
    removed += n
    if removed:
        notes.append(f"Removed {removed} instruction-like phrase(s) from the resume text before sending it to the model.")
    if len(text) > MAX_RESUME_CHARS:
        text = text[:MAX_RESUME_CHARS]
        notes.append(f"The resume text was cut ot {MAX_RESUME_CHARS} characters.")
    return text, notes


def wrap_resume(text: str) -> str:
    return f"{START}\n{text}\n{END}"

def _item_text(item)-> str:
    return json.dumps(item, ensure_ascii= False) if not isinstance(item, str) else item 

def _bad_item(item)-> str | None:
    text = _item_text(item)
    if any(p.search(text) for p in INJECTION_PATTERNS):
        return "instruction-like text in the reply"
    if URL_RE.search(text):
        return "link in the reply"
    return None 


def _trim(item):
    if isinstance(item, str):
        return item[: MAX_ITEM_CHARS]
    return {k: (v[:MAX_ITEM_CHARS] if isinstance(v, str) else v)for k, v in item.items()}


def check_output(feedback: dict, resume_text: str, canary: str) -> tuple[dict, list[str], bool]:
    """Return (cleaned feedback, flags rejected. A rejected reply must not be shown.)"""
    blob = json.dumps(feedback, ensure_ascii=False).lower()
    if canary.lower() in blob:
        return feedback, ['The reply contained the secret code from the system prompt.'], True
    if any(phrase in blob for phrase in LEAK_PHRASES):
        return feedback, ['The reply repeated parts of the system prompt.'], True

    flags, cleaned = [], {'summary': str(feedback.get('summary', ""))[:MAX_ITEM_CHARS * 2]}
    if _bad_item(cleaned['summary']):
        flags.append(f"Summary dropped: {_bad_item(cleaned['summary'])}.")
        cleaned["summary"] = ""
    for key in ('pros', 'cons', 'suggestions'):
        kept = []
        for item in feedback.get(key, []):
            reason = _bad_item(item)
            if reason:
                flags.append(f"A {key[:-1]} was dropped: {reason}.")
            else:
                kept.append(_trim(item))
        cleaned[key] = kept[:MAX_ITEMS]
    lower = resume_text.lower()
    missing = [] 
    for skill in feedback.get('missing_skills', []):
        if _bad_item(skill):
            flags.append("A missing skill was dropped: instruction-like text or a link.")
        elif has_term(lower, str(skill).lower().strip()):
            flags.append(f"Skill '{skill}' was listed as missing but the resume shows it, so it was removed.")
        else:
            missing.append(str(skill)[:80])
    cleaned['missing_skills'] = missing[:8]
    return cleaned, flags, False

