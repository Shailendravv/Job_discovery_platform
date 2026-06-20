# Plan: Preserve Resume Formatting Through Upload → Tailor → Download

## Problem Statement

The current pipeline flattens every uploaded resume (PDF or DOCX) into a plain
string at extraction time, loses that string to an LLM tailoring call that
explicitly requests plain text back, and then **reconstructs** formatting
in `docx_service.py` / `PDF_service.py` using heuristics on the plain text
(`stripped.isupper()`, `endswith(":")`). Two independent rendering engines
(`python-docx` and `reportlab`) rebuild the document from scratch with no
shared source of truth, so:

- Bold headings are guessed, not preserved — mixed-case headings never trigger
  the `isupper()` check and stay unbolded.
- Hyperlinks are completely lost — extraction never captures URLs, and neither
  generator ever creates a hyperlink object.
- DOCX and PDF outputs visually diverge from each other and from the original,
  since they're built by two separate engines with separate default styles.

**Root cause:** the data model is `str` everywhere. A `str` cannot represent
"this line is bold" or "this text links to this URL." Fixing the renderers
alone (`docx_service.py`/`PDF_service.py`) cannot work — the information they'd
need was already discarded by the extractors before generation ever runs.

## Solution Overview

Replace the flat-string pipeline with a structured element list that survives
unchanged from extraction through tailoring through rendering:

```
upload (PDF or DOCX)
   → extract_structured(...)            # NEW: returns list[ResumeElement], not str
   → MongoDB stores structured elements (in addition to a flat-text fallback)
tailor
   → tailor_resume_structured(...)      # CHANGED: LLM call takes/returns structured JSON
   → generate_docx(elements)            # CHANGED: renders from elements, real bold + real hyperlinks
   → generate_pdf_from_docx(docx_bytes) # CHANGED: convert the DOCX, don't rebuild in reportlab
```

One shape (`ResumeElement`) flows through every stage. Nothing reconstructs
formatting from heuristics on plain text after this change — formatting is
either captured at extraction time (ground truth) or explicitly assigned by
the LLM tailoring step (e.g., "this bullet is part of the Experience section
so render as bullet style").

---

## Step 0 — Shared data model

Create a new file `app/models/resume_elements.py`:

```python
from pydantic import BaseModel
from typing import Literal, Optional


class ResumeLink(BaseModel):
    text: str
    url: str


class ResumeElement(BaseModel):
    """
    One structural unit of a resume: a heading, a bullet, a paragraph line,
    or a contact-info line. This is the single shape that flows through
    extraction -> tailoring -> rendering.
    """
    text: str
    type: Literal["heading", "subheading", "bullet", "normal"] = "normal"
    bold: bool = False
    links: list[ResumeLink] = []
    # font/size are optional overrides; if None, renderer uses its default
    # for that `type`. Only set when extraction found an explicit value
    # worth preserving (e.g., a DOCX run with unusual size).
    font_size_pt: Optional[float] = None
```

Use `list[ResumeElement]` (or its `.model_dump()` JSON form) everywhere the
code currently passes `resume_text: str` or `tailored_text: str` between the
tailoring boundary. Keep a flat-text rendering of the same content
(`"\n".join(el.text for el in elements)`) only for:
- the LLM parsing call (`parse_resume_text`) which extracts name/skills/etc and
  doesn't need formatting,
- the `extracted_text_preview` field in the API response,
- the `extracted_text` field saved to MongoDB (keep this as a fallback/search
  field; add a new `structured_elements` field alongside it — do not remove
  `extracted_text`, other code may depend on it).

---

## Step 1 — DOCX structured extraction

File: `app/services/docx_service.py`

Add a new function. **Keep `extract_text_from_docx` as-is** (other code may
still call it for the flat-text fallback) — add this alongside it:

```python
from docx.oxml.ns import qn
from app.models.resume_elements import ResumeElement, ResumeLink


def extract_structured_from_docx(file_bytes: bytes) -> list[ResumeElement]:
    """
    Extract paragraphs as structured elements preserving bold flags and
    hyperlink URLs. This is ground truth — bold/links come from the actual
    OOXML runs, not a guess based on text shape.
    """
    doc = Document(io.BytesIO(file_bytes))
    elements: list[ResumeElement] = []

    for p in doc.paragraphs:
        if not p.text.strip():
            continue

        is_bold = bool(p.runs) and any(r.bold for r in p.runs if r.text.strip())
        is_heading_style = p.style.name.startswith("Heading")

        links: list[ResumeLink] = []
        for hyperlink in p._p.findall(qn("w:hyperlink")):
            r_id = hyperlink.get(qn("r:id"))
            if r_id and r_id in doc.part.rels:
                url = doc.part.rels[r_id].target_ref
                link_text = "".join(node.text or "" for node in hyperlink.iter(qn("w:t")))
                if link_text:
                    links.append(ResumeLink(text=link_text, url=url))

        el_type = "heading" if (is_bold or is_heading_style) else "normal"

        elements.append(ResumeElement(
            text=p.text.strip(),
            type=el_type,
            bold=is_bold or is_heading_style,
            links=links,
        ))

    return elements
```

**Test this against 3-5 real uploaded resumes before moving on.** Print the
output and manually confirm headings show `bold=True` and known links show up
in `links`. DOCX hyperlink extraction via raw OOXML has edge cases (e.g.
hyperlinks split across multiple `<w:r>` runs inside the same `<w:hyperlink>`)
— if you find links missing or text garbled, paste a sample of the failing
DOCX's XML (`doc.element.xml`) for a follow-up fix before trusting this in
production.

---

## Step 2 — PDF structured extraction

File: `app/services/PDF_service.py`

`pypdf` cannot give you font/bold/link info. Switch the **extraction** path
(not the generation path) to `PyMuPDF` (`pip install pymupdf`, imported as
`fitz`):

```python
import fitz  # PyMuPDF
from app.models.resume_elements import ResumeElement, ResumeLink


def extract_structured_from_pdf(file_bytes: bytes) -> list[ResumeElement]:
    """
    Extract structured elements from a PDF using font metadata as a proxy
    for bold/heading, and page link annotations for hyperlinks.

    Heuristic, not ground truth: bold is inferred from font name and size
    relative to the page's most common (body) font size. Verify against
    real uploads — scanned/image-based PDFs will yield no text at all and
    should fall back to extract_text_from_pdf + a manual-formatting warning.
    """
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    elements: list[ResumeElement] = []

    # First pass: collect font sizes to find the body-text baseline
    sizes = []
    for page in doc:
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    sizes.append(round(span["size"]))
    body_size = max(set(sizes), key=sizes.count) if sizes else 11

    for page_num, page in enumerate(doc):
        # Map link annotations by their bounding box for this page
        page_links = page.get_links()  # [{"from": Rect, "uri": str, ...}, ...]

        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                line_text = "".join(span["text"] for span in line.get("spans", [])).strip()
                if not line_text:
                    continue

                spans = line.get("spans", [])
                font_name = spans[0]["font"] if spans else ""
                size = round(spans[0]["size"]) if spans else body_size
                is_bold = "bold" in font_name.lower() or "black" in font_name.lower()
                is_heading = is_bold or size > body_size + 1

                # Attach any link whose rect overlaps this line's bbox
                links: list[ResumeLink] = []
                line_bbox = fitz.Rect(line["bbox"])
                for link in page_links:
                    if "uri" in link and line_bbox.intersects(link["from"]):
                        links.append(ResumeLink(text=line_text, url=link["uri"]))

                elements.append(ResumeElement(
                    text=line_text,
                    type="heading" if is_heading else "normal",
                    bold=is_bold,
                    links=links,
                    font_size_pt=float(size),
                ))

    return elements
```

**This is a heuristic, not ground truth — validate it manually.** Run it
against several real uploaded PDFs (especially any made with Canva, LaTeX,
or exported from Google Docs, which encode fonts differently) and check:
bold detection accuracy, whether body-size detection picks a sane baseline,
and whether links attach to the correct line. If accuracy is poor on your
real resumes, report back with a sample PDF for tuning rather than shipping
this heuristic untested.

Keep `extract_text_from_pdf` (pypdf) as the flat-text fallback for the LLM
parsing call and MongoDB `extracted_text` field — no change needed there.

---

## Step 3 — Update the upload endpoint

File: `app/api/resumes.py`, function `upload_resume`

Add structured extraction alongside the existing flat-text extraction, and
store both:

```python
from app.services.PDF_service import extract_text_from_pdf, extract_structured_from_pdf
from app.services.docx_service import extract_text_from_docx, extract_structured_from_docx

# ── Extract text (existing) ──
try:
    if file.content_type == "application/pdf":
        extracted_text = extract_text_from_pdf(raw_bytes)
        structured_elements = extract_structured_from_pdf(raw_bytes)
    else:
        extracted_text = extract_text_from_docx(raw_bytes)
        structured_elements = extract_structured_from_docx(raw_bytes)
except Exception as e:
    log.error("Text extraction failed: %s", e, exc_info=True)
    raise HTTPException(status_code=422, detail=f"Failed to extract text from file: {str(e)}")
```

Wrap the structured extraction in its own try/except so a structured-parse
failure doesn't break upload entirely — fall back to an all-`normal`-type
element list built from `extracted_text.split("\n")`:

```python
try:
    structured_elements = (
        extract_structured_from_pdf(raw_bytes) if is_pdf
        else extract_structured_from_docx(raw_bytes)
    )
except Exception as e:
    log.warning("Structured extraction failed, falling back to plain elements: %s", e)
    structured_elements = [
        ResumeElement(text=line.strip())
        for line in extracted_text.split("\n") if line.strip()
    ]
```

In the `resume_doc` dict saved to MongoDB, add:
```python
"structured_elements": [el.model_dump() for el in structured_elements],
```
alongside the existing `"extracted_text"` field (keep both — don't remove
`extracted_text`).

**MongoDB schema change required:** add an optional `structured_elements`
array field to your resume collection's JSON schema validator (matching
`ResumeElement`'s shape) if you have schema validation enabled. If you're
unsure whether you have strict schema validation, check `db_service.py` or
your Mongo collection's `validator` — and pause here to confirm before
deploying if you do, since a strict validator will reject the new field
silently or throw.

---

## Step 4 — Update the tailoring LLM call to work on structured elements

File: `app/services/resume_tailor.py`

Change the prompt to require structured JSON in and out, instead of plain
text in and out. This is the one call site where format must change from
free text to JSON, since the LLM is what decides *new* bullet wording while
you need it to preserve/assign `type`/`bold` per element:

```python
import json
import logging
from app.core.llm import call_llm
from app.models.resume_elements import ResumeElement

log = logging.getLogger(__name__)

TAILOR_PROMPT = """You are a professional resume writer. You will receive a candidate's
resume as a JSON array of elements, and a job description. Rewrite the resume
to best match the job, returning the SAME JSON shape back.

Each input element has: "text", "type" (heading/subheading/bullet/normal),
"bold" (true/false), "links" (array of {{text, url}}).

Candidate's Resume (JSON):
{resume_json}

Job Title: {job_title}
Job Description:
{job_description}
Required Skills: {job_skills}

Instructions:
1. Rewrite "text" fields to better match the job — stronger action verbs,
   relevant keywords, quantified achievements where the original supports it.
2. You may reorder bullet elements within a section to put the most relevant
   ones first. Do NOT reorder heading elements or move bullets across sections.
3. Do NOT fabricate experience, employers, dates, or qualifications not present
   in the input.
4. Preserve "type", "bold", and "links" EXACTLY as given on each element you keep.
   If you split one bullet into two, copy the original element's "type" and
   "bold" onto both, and keep "links" only on the one that contains the link text.
5. Do not add new elements with links you invented. Do not delete elements that
   contain a link unless their text becomes truly redundant.

Return ONLY a JSON array of elements in the exact same shape as the input.
No markdown, no commentary, no code fences — raw JSON array only."""


async def tailor_resume_structured(elements: list[ResumeElement], job: dict) -> list[ResumeElement]:
    """
    Tailor structured resume elements to match a job description.
    Preserves bold/type/links per element; only rewrites "text" content
    (and may reorder bullets within a section).
    """
    if not elements:
        return elements

    resume_json = json.dumps([el.model_dump() for el in elements], ensure_ascii=False)

    job_title = job.get("title", "Unknown Position")
    job_description = job.get("description", "")
    job_skills = ", ".join(job.get("skills", []))

    prompt = TAILOR_PROMPT.format(
        resume_json=resume_json[:16000],  # adjust truncation budget for JSON overhead
        job_title=job_title,
        job_description=job_description[:8000],
        job_skills=job_skills or "Not specified",
    )

    try:
        raw = await call_llm(prompt, json_format=True)
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        tailored = [ResumeElement(**el) for el in parsed]
        return tailored
    except Exception as e:
        log.error("Structured resume tailoring failed: %s", e, exc_info=True)
        return elements  # fall back to original structure, untailored
```

Notes:
- This assumes `call_llm` supports `json_format=True` already (it's referenced
  in the original code's signature, just unused with `False`). If your Groq
  wrapper's `json_format=True` enforces strict JSON-object output (not array),
  you may need to wrap the array: ask the LLM to return `{"elements": [...]}`
  instead, and unwrap `parsed["elements"]` — check `app/core/llm.py` to confirm
  which shape `json_format=True` actually guarantees before relying on a bare
  array.
- Add a `try/except` around `ResumeElement(**el)` per-element in production so
  one malformed element from the LLM doesn't crash the whole tailor request —
  skip and log malformed elements rather than failing the batch.
- Keep the old `tailor_resume_text(resume_text: str, job: dict) -> str` function
  in the file too (don't delete it) in case anything else still calls it during
  your migration.

---

## Step 5 — Render DOCX from structured elements (real bold, real hyperlinks)

File: `app/services/docx_service.py`

Add (don't replace yet) a new generator:

```python
from docx.oxml import OxmlElement
from app.models.resume_elements import ResumeElement


def add_hyperlink_run(paragraph, url: str, text: str, bold: bool = False, color: str = "0563C1"):
    part = paragraph.part
    r_id = part.relate_to(
        url,
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
        is_external=True,
    )
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), r_id)

    new_run = OxmlElement("w:r")
    rPr = OxmlElement("w:rPr")
    color_el = OxmlElement("w:color")
    color_el.set(qn("w:val"), color)
    rPr.append(color_el)
    underline = OxmlElement("w:u")
    underline.set(qn("w:val"), "single")
    rPr.append(underline)
    if bold:
        rPr.append(OxmlElement("w:b"))
    new_run.append(rPr)

    t = OxmlElement("w:t")
    t.text = text
    new_run.append(t)
    hyperlink.append(new_run)
    paragraph._p.append(hyperlink)


def generate_docx_from_elements(elements: list[ResumeElement]) -> bytes:
    """
    Render a DOCX from structured elements, applying real bold formatting
    and real clickable hyperlinks — no heuristics, no guessing.
    """
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)

    for el in elements:
        p = doc.add_paragraph(style="List Bullet" if el.type == "bullet" else None)

        if el.links:
            remaining = el.text
            for link in el.links:
                before, sep, remaining = remaining.partition(link.text)
                if before:
                    run = p.add_run(before)
                    run.bold = el.bold
                add_hyperlink_run(p, link.url, link.text, bold=el.bold)
            if remaining:
                run = p.add_run(remaining)
                run.bold = el.bold
        else:
            run = p.add_run(el.text)
            run.bold = el.bold
            if el.type == "heading":
                run.font.size = Pt(13)
            elif el.type == "subheading":
                run.font.size = Pt(12)
            if el.font_size_pt:
                run.font.size = Pt(el.font_size_pt)

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
```

Keep the old `generate_docx(text: str) -> bytes` in the file too during
migration — see Step 7 for the cutover.

---

## Step 6 — Replace reportlab PDF generation with DOCX→PDF conversion

File: `app/services/PDF_service.py`

Add a new function. Requires LibreOffice installed on the server
(`apt-get install -y libreoffice` on Debian/Ubuntu, or the equivalent on
whatever base image your deployment uses — confirm this is installable in
your hosting environment, e.g. some serverless platforms cannot run
`soffice` at all, in which case flag that back before proceeding):

```python
import subprocess
import tempfile
import os


def generate_pdf_from_docx(docx_bytes: bytes) -> bytes:
    """
    Convert DOCX bytes to PDF via headless LibreOffice. This guarantees the
    PDF is visually identical to the DOCX, since it's a direct render of it
    rather than an independently rebuilt document.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        docx_path = os.path.join(tmp_dir, "resume.docx")
        with open(docx_path, "wb") as f:
            f.write(docx_bytes)

        result = subprocess.run(
            ["soffice", "--headless", "--convert-to", "pdf", "--outdir", tmp_dir, docx_path],
            capture_output=True,
            timeout=60,
        )
        if result.returncode != 0:
            raise RuntimeError(f"LibreOffice conversion failed: {result.stderr.decode(errors='ignore')}")

        pdf_path = os.path.join(tmp_dir, "resume.pdf")
        with open(pdf_path, "rb") as f:
            return f.read()
```

Keep the old `generate_pdf(text: str) -> bytes` (reportlab) in the file too
during migration, for the cover letter (see Step 7 — cover letter stays
plain-text/reportlab since it has no formatting to preserve).

---

## Step 7 — Wire it into the `/tailor` endpoint

File: `app/api/resumes.py`, function `tailor_resume`

```python
from app.services.PDF_service import extract_text_from_pdf, generate_pdf, generate_pdf_from_docx
from app.services.docx_service import extract_text_from_docx, generate_docx, generate_docx_from_elements
from app.services.resume_tailor import tailor_resume_text, tailor_resume_structured
from app.models.resume_elements import ResumeElement
```

Replace the body that currently does:
```python
resume_text = resume.get("extracted_text", "")
...
tailored_text = await tailor_resume_text(resume_text, job)
...
pdf_bytes = generate_pdf(tailored_text)
docx_bytes = generate_docx(tailored_text)
```

with:
```python
resume_text = resume.get("extracted_text", "")
structured_raw = resume.get("structured_elements")

if structured_raw:
    elements = [ResumeElement(**el) for el in structured_raw]
else:
    # legacy resume uploaded before this change — no structured data saved
    elements = [ResumeElement(text=line.strip()) for line in resume_text.split("\n") if line.strip()]

parsed = resume.get("parsed_data", {})

# ── Tailor resume (structured) ──
try:
    tailored_elements = await tailor_resume_structured(elements, job)
    tailored_text = "\n".join(el.text for el in tailored_elements)  # for preview/cover-letter context only
except Exception as e:
    log.error("Resume tailoring failed: %s", e, exc_info=True)
    return ResumeTailorErrorResponse(
        resume_id=request.resume_id,
        job_id=request.job_id,
        error=f"Resume tailoring failed: {str(e)}",
        tailored_text=resume_text,
    )
```

And later, where files are generated:
```python
try:
    docx_bytes = generate_docx_from_elements(tailored_elements)
    pdf_bytes = generate_pdf_from_docx(docx_bytes)
    cover_pdf_bytes = generate_pdf(cover_letter)  # cover letter unaffected — plain text is fine here
    ...
```

Everything else in the endpoint (Cloudinary upload, URL generation, session
saving) is unaffected and stays as-is — only the source of `docx_bytes` and
`pdf_bytes` changes.

---

## Step 8 — Rollout order (do this in order, test after each step)

1. Add `app/models/resume_elements.py`. No behavior change yet.
2. Add `extract_structured_from_docx` + `extract_structured_from_pdf` as new
   functions (old extractors untouched). Add a temporary debug script or test
   route that just calls them on a sample upload and prints the result —
   verify bold/links look right on 3-5 real resumes before continuing.
3. Update `upload_resume` to also save `structured_elements` to MongoDB.
   Update the MongoDB schema validator if one exists. Re-upload a test resume
   and confirm the new field is saved.
4. Add `tailor_resume_structured`. Add `generate_docx_from_elements` and
   `generate_pdf_from_docx`. Install LibreOffice in your deployment
   environment and confirm `soffice --headless --convert-to pdf` works from a
   terminal before wiring it into the endpoint.
5. Update `tailor_resume` endpoint to use the new structured functions per
   Step 7. Test end-to-end with a resume uploaded *after* step 3 (so it has
   `structured_elements`), confirm the downloaded DOCX has real bold headings
   and clickable links, and confirm the PDF looks identical to the DOCX.
6. Test the legacy fallback path (a resume uploaded *before* this change, with
   no `structured_elements` in Mongo) to confirm it doesn't crash — it should
   degrade gracefully to unformatted output, not error.
7. Once confident, you can leave the old `tailor_resume_text`/`generate_docx`/
   `generate_pdf(text)` functions in place unused, or remove them later — no
   rush, they're harmless as dead code during the transition.

## Open items to confirm before/while implementing

- Confirm `call_llm(..., json_format=True)` in `app/core/llm.py` returns a bare
  JSON array vs. requires an object wrapper — adjust the prompt/unwrapping in
  Step 4 accordingly.
- Confirm LibreOffice (`soffice`) can be installed in your actual deployment
  target (Docker base image / hosting platform) — this is the one external
  dependency this plan adds.
- Decide whether `structured_elements` should be required or optional in the
  MongoDB schema validator — recommend optional, to avoid breaking ingestion
  if structured extraction ever throws on an unusual file.
