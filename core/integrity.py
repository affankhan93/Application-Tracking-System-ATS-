"""Phase 2: integrity scan. Finds text a human cannot see and other attempts to manipulate screening."""

from __future__ import annotations
import math 
import re 
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass, field
import numpy as np 
import pymupdf
from core.parser import ParsedResume, ocr_pdf_pages

TINY_FONT_PT = 4   # text smaller than 4 then it cannot be read that.
HIDDEN_CONTRAST = 1.3   # WCAG contrast ratio below 1.3 effectively invisible
LOW_CONTRAST = 2.0       # below 2.0 very pale 
RENDER_ZOOM = 2     # page render scale for the visibility check if the text is properly visible or not 
INK_DIFF = 40     # grey-level difference that counts as ink
MIN_INK_FRACTION = 0.004   # less ink than this in a text box: nothing visibel there

# OCR is Optical Character Recognition it help us to extract text form image. I'm using "Tesseract OCR"
OCR_SPAN_MISSING = 0.6  # share of a line's words missing from OCR to call the line unreadable 
OCR_MIN_WORDS = 8  # unreadable words needed before the Optical Character Recognition (OCR) mismatch is reported. 
STUFF_MIN_COUNT = 8 # keyword repeated at least this often ... 
STUFF_MIN_SHARE = 0.05 # .. and making up at least this share of the words. 

HIDDEN_REASONS = {'hidden_color_text', 'tiny-text', 'invisible_text', 'hidden_text_flag', 
                  'off_page_text', 'text_not_rendered', 'text_layer_mismatch'}

MESSAGES = {
    'hidden_color_text' : "Text colour matches the background, so people cannot see it.",
    'low_contrast_text' : "Text is very pale against its background.",
    'tiny_text' : "Text is set in a font too small to read.",
    'invisible_text' : 'Text is marked invisible in the PDF.',
    'hidden_text_flag' : 'Text uses Words hidden-text setting.',
    'off_page_text' : 'Text is placed outside the visible page.',
    'text_not_rendered' : 'Text exists in the file but does not appear on the rendered page.',
    'text_layer_mismatch' : 'Text in the file cannot be found when the page is read as an image.'
}

# It is used to detect zero-width and invisible Unicode characters in text.
ZERO_WIDTH_RE = re.compile("[\u200b\u200c\u200d\u2060\ufeff\u202a-\u202e\u2066-\u2069]")

# Some common and Frequently used prompt injection pattern in Resume.
INJECTION_PATTERNS = [re.compile(p, re.I) for p in [
    r"ignore\s+(all\s+|any\s+)?(the\s+)?(previous|prior|above|earlier)\s+(instructions?|prompts?|rules)",
    r"disregard\s+(all\s+|any\s+)?(the\s+)?(previous\s+|prior\s+|above\s+)?(instructions?|rules)",
    r"\bsystem\s+(note|prompt|message|instructions?)\b",
    r"\b(rank|rate|score|mark|select)\s+(this|the)\s+(candidate|resume|applicant)",
    r"recommend\w*\s+(this\s+candidate\s+)?for\s+(an\s+)?(immediate\s+)?hire",
    r"score\s+of\s+100",
    r"\bai\s+(screener|screening|reviewer|recruiter)\b",
    r"do\s+not\s+(reject|flag|filter)",
    r"you\s+are\s+now\s+(a|an|the)\b",
]]

STOPWORDS = set("""the and for with that this from have has had was were are been being into over under about
across within using used use per via not but all any can will our their they them you your his her its out
who what when where which while than then also more most other such only very both each """)
META_TEXT_FIELDS = ("title", 'author', 'subject', 'keywords')

@dataclass
class IntegrityReport:
    risk : str          # 'clean', 'review' or 'high_risk'
    findings : list[dict]
    visible_text : str
    hidden_text : str
    checks_skipped: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def to_dict(self)-> dict:
        return {'risk': self.risk,
                'findings' : self.findings,
                'visible_text' : self.visible_text,
                'hidden_text': self.hidden_text,
                'checks_skipped' : self.checks_skipped,
                'stats' : self.stats
                }

# helpers: It help us to detect resume.  
def _luminance(rgb: int) -> float: 
    """This function calculates the relative brigthness (luminance) of a color.
    ex:- It can help to analyze resume determine whether text is dark or light compared with its background."""
    def channel(v):
        v /= 255  # rgb = 255, 255, 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * channel((rgb >> 16) & 255) + 0.7152 * channel((rgb >> 8)& 255) + 0.0722 * channel(rgb & 255)


def contrast_ratio(a: int, b: int) -> float:
    """It calculates the contrast between two colors. Black & White"""
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)

def _tokens(text: str) -> list[str]:
    """It help to extracts meaningful word-like tokens from text."""
    return re.findall(r'[a-z][a-z0-9+#]{2,}', text.lower())

def _background(span, shapes) -> int: 
    """This function identifies the background color behind a particular text span."""
    cx, cy = (span.bbox[0] + span.bbox[2]) / 2, (span.bbox[1] + span.bbox[3]) / 2
    colour = 0xFFFFFF
    for sh in shapes:
        if sh.page == span.page and sh.fill is not None and sh.bbox[0] <= cx <= sh.bbox[2] and sh.bbox[1] <= cy <= sh.bbox[3]:
            colour = sh.fill
    return colour 

def _join_lines(spans) -> str:
    """This function combines individual text spans into properly ordered lines.
    When extracting text from PDF documents, text may be divided into multiple small pieces called spans."""
    lines = defaultdict(list)
    for s in spans:
        lines[s.line].append(s.text)
    return '\n'.join("".join(parts) for _, parts in sorted(lines.items()))

def _finding(flag_type: str, severity: str, message: str, **evidence) -> dict:
    """It can creates a structured report whenever the resume analyzer identifies an issue."""
    return {'flag_type': flag_type, 'severity': severity, 'message': message, 'evidence' : evidence}


# It check per span. 
def _metadata_checks(parsed: ParsedResume, reasons: dict, evidence: dict)-> None:
    """It can check resume analyze is properly."""
    for i, s in enumerate(parsed.spans):
        if s.hidden:
            reasons[i].add("hidden_text_flag")

        if s.alpha == 0:
            reasons[i].add("invisible_text")

        if s.font_size is not None and s.font_size < TINY_FONT_PT:
            reasons[i].add("tiny_text")

        if s.bbox is not None and parsed.page_sizes:
            w, h = parsed.page_sizes[s.page]
            cx, cy = (s.bbox[0] + s.bbox[2]) / 2, (s.bbox[1] + s.bbox[3]) / 2
            if not (0 <= cx <= w and 0 <= cy <= h):
                reasons[i].add("off_page_text")

        if s.color is not None:
            ratio = contrast_ratio(s.color, _background(s, parsed.shapes) if s.bbox else 0xFFFFFF)
            if ratio < HIDDEN_CONTRAST:
                reasons[i].add('hidden_color_text')
            elif ratio < LOW_CONTRAST:
                reasons[i].add("low_contrast_text")
            evidence[(i, 'contrast')] = round(ratio, 2)


def _render_check(parsed: ParsedResume, file_bytes: bytes, reasons: dict)-> None:
    """Text boxes with no visible ink on the rendered page: covered by a shape, or too faint to see."""
    doc = pymupdf.open(stream=file_bytes, filetype='pdf')
    by_page = defaultdict(list)

    for i, s in enumerate(parsed.spans):
        if not (reasons[i] & HIDDEN_REASONS) and len(s.text.strip()) >= 3 and s.bbox is not None:
            by_page[s.page].append(i)

    for pno, indices in by_page.items():
        page = doc[pno]
        if page.rotation:
            continue
        pix = page.get_pixmap(matrix = pymupdf.Matrix(RENDER_ZOOM, RENDER_ZOOM), colorspace = pymupdf.csGRAY, alpha = False)
        img = np.frombuffer(pix.samples, dtype = np.uint8).reshape(pix.height, pix.stride)[:, :pix.width].astype(int)
        for i in indices:
            x0, y0, x1, y1 = (v * RENDER_ZOOM for v in parsed.spans[i].bbox)
            region = img[max(0, math.floor(y0)):math.ceil(y1), max(0, math.floor(x0)):math.ceil(x1)]
            if region.shape[0] < 2 or region.shape[1] < 2:
                continue
            ink = float((np.abs(region - int(np.median(region))) > INK_DIFF).mean())
            if ink < MIN_INK_FRACTION:
                reasons[i].add('text_not_rendered')


def _ocr_check(parsed: ParsedResume, file_bytes: bytes, reasons: dict)-> None:
    """Lines whose words cannot be found on any line when the page is read as an image.
    ex:- text behind a picture."""
    ocr_lines = [set(_tokens(line)) for line in '\n'.join(ocr_pdf_pages(file_bytes)).splitlines()]
    ocr_lines = [line for line in ocr_lines if line]
    flagged, missing_total = [], 0
    for i, s in enumerate(parsed.spans):
        if reasons[i] & HIDDEN_REASONS:
            continue
        toks = set(_tokens(s.text))
        if len(toks) < 4:
            continue
        missing = len(toks) - max((len(toks & line) for line in ocr_lines), default=0)
        if missing / len(toks) >= OCR_SPAN_MISSING:
            flagged.append(i)
            missing_total += missing
    if missing_total >= OCR_MIN_WORDS:
        for i in flagged:
            reasons[i].add('text_layer_mismatch')


# document-leve checks 
def _injection_findings(sources: dict) -> list[dict]:
    """It help to find the hidden text in the resume that can instruct an AI to increase the score of ATS."""
    hits = {}
    for where, text in sources.items():
        for pat in INJECTION_PATTERNS:
            for m in pat.finditer(text):
                hits.setdefault(where, []).append(m.group(0)[:80])
    if not hits:
        return []
    return [_finding('prompt_injection', 'high', 'Text that tries to instruct an AI screener or force a good score.',
                     found_in = sorted(hits), phrases =[p for v in hits.values() for p in v][:5])]


def _zero_width_findings(text: str)-> list[dict]:
    found = list(ZERO_WIDTH_RE.finditer(text))
    if not found:
        return []
    severity = 'high' if len(found) >= 15 else 'medium' if len(found) >= 3 else 'low'
    samples = [ZERO_WIDTH_RE.sub('<ZW>', text[max(0, m.start() - 8):m.end() + 8]).replace("\n", " ")for m in found[:3]]
    return [_finding("zero_width_characters", severity, "Invisible characters are mixed into the text.",
                     count = len(found), samples=samples)]


def _stuffing_findings(visible_text: str)-> list[dict]:
    """It checks wheather someone has repated the same keywords or sentences too many times in their resume.
    Repating keywords excessively can be an attempt to manipulate an ATS."""
    toks = [t for t in _tokens(visible_text) if t not in STOPWORDS]
    total = max(len(toks), 1)
    heavy = {t: c for t, c in Counter(toks).items() if c >= STUFF_MIN_COUNT and c / total >= STUFF_MIN_SHARE}
    lines = Counter(re.sub(r"\s+", " ", ln.strip().lower()) for ln in visible_text.splitlines() if len(ln.strip()) >= 20)
    repeated = {ln[:80]: c for ln, c in lines.items() if c >= 3}
    if not heavy and not repeated:
        return []
    return [_finding("keyword_stuffing", 'medium', 'keywords or lines are repated far more than noraml writing needs.',
                     repeated_words = dict(sorted(heavy.items(), key=lambda kv: -kv[1])[:5]), repeated_lines = repeated)]


def _metadata_findings(metadata: dict)-> tuple[list[dict], dict]:
    """When someone creates a PDF resume, the PDF can contain additional information called metadata.
    ex: author name, subject, etc. This function checks selected metadata fields to identify unusally long text that might contain hidden keyword content."""
    texts = {f"metadata: {k}": str(v) for k, v in metadata.items() if k in META_TEXT_FIELDS}
    findings = []
    for key, value in texts.items():
        if len(value) > 250 or len(value.split()) > 40:
            findings.append(_finding('suspicious_metadata', 'medium', 'A documents property holds a long block of keywords',
                                     field = key, length = len(value)))

    return findings, texts 

# main entry point 
def scan(parsed: ParsedResume, file_bytes: bytes | None = None, use_ocr: bool = True)-> IntegrityReport:
    skipped: list[str] = []
    reasons: dict[int, set] = defaultdict(set)
    evidence: dict = {} 

    _metadata_checks(parsed, reasons, evidence)
    if parsed.source == 'pdf' and parsed.spans:
        if file_bytes:
            _render_check(parsed, file_bytes, reasons)
        else:
            skipped.append("render_check (original file bytes needed)")
        if use_ocr and file_bytes:
            if shutil.which("tesseract"):
                _ocr_check(parsed, file_bytes, reasons)
            else:
                skipped.append('ocr_text_layer_comparison (tesseract not installed)')

    hidden_idx = {i for i in range(len(parsed.spans)) if reasons[i] & HIDDEN_REASONS}
    if parsed.spans:
        visible = _join_lines(s for i, s in enumerate(parsed.spans) if i not in hidden_idx)
        hidden = _join_lines(parsed.spans[i] for i in sorted(hidden_idx))
    else:
        visible, hidden = parsed.text, ""
    visible = ZERO_WIDTH_RE.sub("", visible)

    findings: list[dict] = []
    for reason in MESSAGES:
        idx = [i for i in range(len(parsed.spans)) if reason in reasons[i]]
        if not idx:
            continue
        spans = [parsed.spans[i] for i in idx]
        info = {'words': sum(len(s.text.split()) for s in spans), 
                'pages': sorted({s.page + 1 for s in spans}),
                'sample': ' '.join(s.text.strip() for s in spans)[:200]}
        if reason in ('hidden_color_text', 'low_contrast_text'):
            info['contrast_ratio'] = min(evidence[(i, 'contrast')] for i in idx)
            info['colour'] = f"#{spans[0].color:06X}"
        findings.append(_finding(reason, 'high' if reason in HIDDEN_REASONS else 'medium', MESSAGES[reason], **info))

    meta_findings, meta_texts = _metadata_findings(parsed.metadata)
    findings += _injection_findings({'visible text': visible, 'hidden text': hidden, **meta_texts})
    findings += _zero_width_findings(parsed.text)
    findings += _stuffing_findings(visible)
    for f in meta_findings:
        if not any(x['flag_type'] == 'prompt_injection' and any(k.startswith('metadata') for k in x['evidence']['found_in']) for x in findings):
            findings.append(f)

    if any(f['flag_type'] == 'prompt_injection' and any(k.startswith('metadata') for k in f['evidence']['found_in']) for f in findings):
        findings.append(_finding('suspicious_metadata', 'high', 'A document property contains insturctions aimed at an AI screener.'))
    
    risk = "high_risk" if any(f["severity"] == "high" for f in findings) else \
           "review" if any(f["severity"] == "medium" for f in findings) else "clean"
    words_total = len(parsed.text.split())
    words_hidden = sum(len(parsed.spans[i].text.split()) for i in hidden_idx)
    stats = {'words_total': words_total, 'words_hidden': words_hidden, 'hidden_share': round(words_hidden / words_total, 3) if words_total else 0.0}
    return IntegrityReport(risk=risk, findings=findings, visible_text=visible, hidden_text=hidden, checks_skipped=skipped, stats=stats)


