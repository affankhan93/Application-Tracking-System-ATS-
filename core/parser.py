from __future__ import annotations
from dataclasses import dataclass, field
import pymupdf
import io 
import re 
import pytesseract
from PIL import Image 
import docx

MAX_PAGES = 5 # Max 5 pages of resume is allowed. 
MIN_TEXT_CHARS = 30 # If a page 30 characters below then it treated as scanned and OCR is used.
BIG_CLIP = pymupdf.Rect(-3000, -3000, 6000, 6000) # let PyMuPDF return text placed outside the page

SECTION_ALIASES = {
    'summary' : ['summary', 'profile', 'objective', 'about me', 'professtional summary'],
    'skills' : ['technical skill', 'skills', 'key skills', 'core competencies'],
    'experience' : ['experience', 'work experience', 'professional experience', 'employment history'],
    'projects' : ['projects', 'academic projects', 'personal projects', 'group project', 'Open-source contribution project'],
    'eduction' : ['education', 'academic qualifications', 'qualifications'],
    'certifications' : ['certifications', 'certificates', 'courses'],
    'achievements' : ['achievements', 'awards', 'accomplishments'],
 
}

_HEADING_LOOKUP = {alias : name for name, aliases in SECTION_ALIASES.items() for alias in aliases}

@dataclass
class Span:
    text: str
    font_size: float | None     # It points, None if the file does not say
    color: int | None           # 0xRRGGBB; None if unknown (DOCX theme or auto colour)
    bbox: tuple | None          # (x0, y0, x1, y1), origin top-left; None for Docx
    page: int
    alpha: int = 225            # 0 means invisiable text (PDF render mode 3)
    hidden: bool = False        # DOCX 'hidden text' font flag
    line: int = 0           # running line number (PDF line or DOCX paragraph), used to rebuild text


@dataclass
class Shape:
    bbox: tuple 
    fill: int | None
    page: int 

@dataclass
class ParsedResume:
    text: str                # all text in the file, hidden text included.
    spans: list[Span] = field(default_factory=list)
    shapes: list[Shape] = field(default_factory=list)
    sections: dict = field(default_factory=dict)
    page_sizes: list[tuple] = field(default_factory=list)
    page_count: int = 0
    metadata: dict = field(default_factory=dict)
    source: str = 'pdf'     # pdf, pdf-ocr or docx


def split_sections(text: str) -> dict:
    """Group lines under known headings (Summary, Skills, Experience, ....) Text before the first heading is 'header',"""
    sections, current = {'header': []}, 'header'
    for line in text.splitlines():
        key = re.sub(r'[^a-z]', "", line.lower()).strip() 
        if key in _HEADING_LOOKUP and len(line.strip()) < 40:
            current = _HEADING_LOOKUP[key]
            sections.setdefault(current, [])
        elif line.strip():
            sections[current].append(line.strip())
    return {k: '\n'.join(v) for k, v in sections.items() if v}

def _rgb_float_to_int(rgb) -> int | None:
    if not rgb:
        return None
    r, g, b = (int(round(c * 255)) for c in rgb[: 3])
    return (r << 16)  | (g << 8) | b 

def ocr_pdf_pages(file_bytes: bytes, dpi: int = 200) -> list[str]:
    """OCR each page as an image. Needs the tessearct program (packages.txt on Streamlit Cloud)."""
    doc = pymupdf.open(stream=file_bytes, filetype='pdf')
    texts = [] 
    for page in doc:
        pix = page.get_pixmap(dpi = dpi)
        img = Image.frombytes('RGB', [pix.width, pix.height], pix.samples)
        texts.append(pytesseract.image_to_string(img))
    return texts


def _parse_pdf(file_bytes: bytes) -> ParsedResume:
    try:
        doc = pymupdf.open(stream=file_bytes, filetype='pdf')
    except Exception as exc:
        raise ValueError(f"Could not open the PDF: {exc}") from exc
    if doc.page_count > MAX_PAGES:
        raise ValueError(f"Too many pages ({doc.page_count}); a resume should be at most {MAX_PAGES} is allowed.")

    spans, shapes, page_sizes, page_texts = [], [], [], [] 
    for pno, page in enumerate(doc):
        page_sizes.append((page.rect.width, page.rect.height))
        lines_out = [] 
        for block in page.get_text('dict', clip = BIG_CLIP)['blocks']:
            if block['type'] != 0:
                continue
            for line in block['lines']:
                parts = [] 
                for s in line['spans']:
                    if not s['text'].strip():
                        continue
                    parts.append(s['text'])
                    spans.append(Span(text = s['text'], font_size=round(s['size'], 2), color=s['color'],
                                      bbox = tuple(s['bbox']), page = pno, alpha= s.get('alpha', 255)))
                
                if parts:
                    lines_out.append("".join(parts))
        page_texts.append("\n".join(lines_out))
        for d in page.get_drawings():
            if d.get('fill') is not None:
                shapes.append(Shape(bbox=tuple(d['rect']), fill=_rgb_float_to_int(d['fill']), page=pno))

    text = '\n'.join(page_texts)
    meta = {k: v for k, v in (doc.metadata or {}).items() if v}
    source = 'pdf'
    if len(text.strip()) < MIN_TEXT_CHARS:
        text = '\n'.join(ocr_pdf_pages(file_bytes))
        spans, source = [], 'pdf-ocr'
    return ParsedResume(text = text, spans = spans, sections = split_sections(text), 
                        page_sizes=page_sizes, page_count=doc.page_count, metadata=meta, source = source)


def _parse_docx(file_bytes: bytes) -> ParsedResume:
    try:
        document = docx.Document(io.BytesIO(file_bytes))
    except Exception as exc:
        raise ValueError(f"Cloud not open the DOCX: {exc}") from exc

    paragraphs = list(document.paragraphs)
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                paragraphs.extend(cell.paragraphs)

    spans, lines = [], []
    for p in paragraphs:
        if p.text.strip():
            lines.append(p.text)
        for run in p.runs:
            if not run.text.strip():
                continue
            rgb = run.font.color.rgb if run.font.color is not None and run.font.color.type is not None else None
            spans.append(Span(text=run.text, 
                              font_size=run.font.size.pt if run.font.size else None, 
                              color= int(str(rgb), 16) if rgb is not None else None,
                              bbox=None, page = 0, hidden=bool(run.font.hidden)))

    text = '\n'.join(lines)
    props = document.core_properties
    meta = {k: v for k,v in {'title': props.title, 'author': props.author}.items() if v}
    return ParsedResume(text=text, spans=spans, sections=split_sections(text), page_sizes=[], page_count=1, metadata=meta, source='docx')


def parse_resume(file_bytes: bytes, filename: str) -> ParsedResume:
    name = filename.lower()
    if name.endswith('.pdf'):
        return _parse_pdf(file_bytes)
    if name.endswith('.docx'):
        return _parse_docx(file_bytes)
    raise ValueError("Unsupported file type. Please upload a PDF or DOCX.")



