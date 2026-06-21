# Resume Tailoring Engine — Implementation Plan

**Goal:** Given a person's existing resume (.docx) and a target job description, automatically rewrite the *content* (summary, bullets, skills emphasis) to better match the job — without touching fonts, colors, spacing, layout, or any other visual design.

**Local model:** Gemma 4 E2B (≈2.3B effective params, 128K context, native JSON/function-calling, runs via Ollama as `gemma4:e2b` or llama.cpp/LM Studio). The whole resume + job description fits in context in one shot, and the model's native structured-output support means we don't need brittle regex parsing of its responses.

---

## 0. The Core Problem This Plan Solves

Your attached guide's DOCX snippet is the standard "tutorial" approach:

```python
for paragraph in doc.paragraphs:
    paragraph.text = paragraph.text.replace('old_text', 'new_text')
```

This **destroys formatting** the moment a paragraph contains more than one run with different styling — which is most of a resume. Setting `.text` on a `Paragraph` object deletes every run and creates a single new one using only the first run's style. A line like:

```
**Senior Backend Engineer**  |  Acme Corp  |  Jan 2022 – Present
(bold)                          (normal)       (italic)
```

becomes entirely bold (or entirely normal) after a paragraph-level replace.

**The fix:** never call `paragraph.text = ...` or `cell.text = ...`. Only ever set `run.text = ...` on the *specific run* that holds the content you're changing. The run object keeps its own `<w:rPr>` (font, size, bold, italic, color, etc.), so swapping its text preserves everything else automatically. This single rule is the backbone of the whole pipeline below.

---

## 1. High-Level Pipeline

```
resume.docx + job_description.txt
        │
        ▼
┌───────────────────┐
│ 1. PARSE           │  Walk the docx → build a "Content Map":
│   (python-docx)    │  every editable text span gets a stable ID,
│                    │  its run index, current text, and a length budget.
└─────────┬──────────┘
          ▼
┌───────────────────┐
│ 2. TAILOR           │  Send the Content Map + JD to Gemma 4 E2B
│   (local LLM)       │  (via Ollama, structured/function-calling output).
│                    │  Model returns {id, new_text} pairs only —
│                    │  never touches IDs it wasn't given.
└─────────┬──────────┘
          ▼
┌───────────────────┐
│ 3. VALIDATE          │  Check length budgets, JSON schema, banned
│   (pydantic)         │  content (no invented employers/dates/numbers).
│                    │  Retry/shrink loop if a field overflows.
└─────────┬──────────┘
          ▼
┌───────────────────┐
│ 4. REINJECT          │  Open the ORIGINAL docx again, locate each run
│   (python-docx,       │  by (paragraph_index, run_index), set run.text
│    run-level only)    │  directly. Save as a NEW file.
└─────────┬──────────┘
          ▼
┌───────────────────┐
│ 5. VERIFY            │  Convert to PDF (LibreOffice headless), check
│   (visual diff)      │  page count matches original, render side-by-side
│                    │  image diff for a final human sanity check.
└─────────┬──────────┘
          ▼
   tailored_resume.docx  (design untouched, content tailored)
```

---

## 2. Phase 1 — Parsing the Resume into a "Content Map"

This is the most important phase. Get this right and everything downstream is safe.

### 2.1 What counts as "editable"

Split resume content into tiers, by risk:

| Tier | Examples | Editable? |
|------|----------|-----------|
| 1 — Bullets | Achievement/responsibility bullets under each role | ✅ Freely rewrite (this is 90% of the value) |
| 2 — Summary/Objective | Top-of-resume summary paragraph | ✅ Freely rewrite |
| 3 — Skills list | Comma-separated or bulleted skills | ✅ Reorder/re-emphasize; can drop or add *only if the skill is plausibly implied elsewhere in the resume* |
| 4 — Headers | Name, job titles, company names, dates, degrees, contact info | 🚫 **Never edit.** These are facts, not style. Tailoring should never fabricate or alter a title, employer, date, or credential. |

This guardrail matters for two reasons: (1) it dramatically shrinks the model's blast radius, which matters a lot for a small 2–3B-class model that's more prone to drifting off-task than a frontier model, and (2) it keeps the output honest — a tailored resume that quietly invents a more senior-sounding title is a real harm to the person using it, not just a bug.

### 2.2 Building the map

```python
from docx import Document

def build_content_map(path):
    doc = Document(path)
    content_map = []
    current_section = None

    for p_idx, para in enumerate(doc.paragraphs):
        style = (para.style.name or "").lower()

        # crude section tracking — refine per-template
        if style.startswith("heading"):
            current_section = para.text.strip().lower()
            continue

        if current_section in ("experience", "work experience"):
            if _is_bullet(para):                      # e.g. style == "List Bullet"
                _add_editable_span(content_map, para, p_idx, tier=1)
        elif current_section in ("summary", "profile", "objective"):
            _add_editable_span(content_map, para, p_idx, tier=2)
        elif current_section in ("skills", "technical skills"):
            _add_editable_span(content_map, para, p_idx, tier=3)
        # everything else (headers, dates, job titles) is left out of the map entirely

    return content_map
```

```python
def _add_editable_span(content_map, para, p_idx, tier):
    # Only safe to whole-swap if the paragraph is "uniform":
    # either a single run, or every run shares identical formatting.
    if _is_uniform(para):
        content_map.append({
            "id": f"p{p_idx}",
            "tier": tier,
            "paragraph_index": p_idx,
            "run_index": 0,            # we'll merge into run 0 on write-back
            "run_count": len(para.runs),
            "text": para.text,
            "char_budget": int(len(para.text) * 1.15),  # ~15% slack
        })
    else:
        # mixed-formatting paragraph (e.g. "Led **5** engineers to ship X")
        # — flag for manual review rather than guess wrong
        content_map.append({
            "id": f"p{p_idx}",
            "tier": tier,
            "needs_manual_review": True,
            "text": para.text,
        })
```

`_is_uniform` just checks whether every run in the paragraph has the same bold/italic/underline/font/size/color. Most bullets and summary lines are uniform; flag the rest instead of guessing.

### 2.3 Calibration step (recommended, not optional)

Resume templates vary too much for heuristics to be 100% reliable on the first pass. Before running this on a real resume, do a one-time dry run that just **prints the content map** (which paragraphs were detected as Tier 1/2/3, which were flagged for manual review) and have a human glance at it. This costs five minutes and prevents the model from silently skipping a whole section because a heading wasn't recognized, or — worse — editing something it shouldn't have.

---

## 3. Phase 2 — Tailoring with Gemma 4 E2B

### 3.1 Serving the model

```bash
ollama pull gemma4:e2b
ollama serve   # exposes an OpenAI-compatible + native API on localhost:11434
```

### 3.2 Why structured output, not free text

Don't ask the model to "rewrite the resume" and parse prose back out — that's where small local models get unreliable. Instead, give it the content map as JSON and force a JSON-shaped response via Gemma 4's native function-calling/structured output. Disable "thinking mode" for this call (you want a fast, deterministic transform, not a reasoning trace) — thinking is opt-in via a control token, so simply don't include it.

**Tool/schema definition:**

```python
REWRITE_SCHEMA = {
    "type": "object",
    "properties": {
        "rewrites": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "new_text": {"type": "string"},
                },
                "required": ["id", "new_text"],
            },
        }
    },
    "required": ["rewrites"],
}
```

**Prompt skeleton** (keep it narrow — small models do better with one clear job than a sprawling instruction set):

```python
SYSTEM_PROMPT = """You tailor resume content to a job description.
Rules:
- You will receive a list of text spans, each with an id and a character budget.
- Return ONLY a JSON object matching the given schema: one rewrite per id you were given.
- Do not invent job titles, employers, dates, degrees, or metrics that
  are not already present in the original text. You may rephrase and
  re-emphasize, never fabricate.
- Stay within roughly the given char_budget for each id (do not pad
  artificially, do not run far over).
- Keep the original first-person/implied-subject style (resumes omit "I").
- If a span is already a strong match for the job description, you may
  return it unchanged.
"""

user_payload = {
    "job_description": jd_text,
    "spans": [s for s in content_map if not s.get("needs_manual_review")],
}
```

### 3.3 Batch size: per job-entry, not the whole resume at once

Send one job/role's bullets together (with its own job title + the JD as context), rather than every bullet in the resume in one call. A 2–3B class model stays more focused on a 5–8 item batch than a 30-item one, and you get better failure isolation — if one batch comes back malformed, you only retry that batch.

### 3.4 Validation + retry loop

```python
from pydantic import BaseModel, ValidationError

class Rewrite(BaseModel):
    id: str
    new_text: str

def validate_and_apply_budget(rewrites, content_map_by_id):
    accepted = {}
    for r in rewrites:
        original = content_map_by_id.get(r.id)
        if not original:
            continue  # model referenced an id it wasn't given — drop it
        if len(r.new_text) > original["char_budget"]:
            continue  # over budget — caller should re-request a shorter version
        accepted[r.id] = r.new_text
    return accepted
```

If a field comes back over budget, re-prompt just that field with "shorten to under N characters, keep the key point" rather than discarding it outright. Cap retries at 2; after that, fall back to the original text for that field — never block the whole pipeline on one stubborn bullet.

---

## 4. Phase 3 — Reinjection (the formatting-preserving write-back)

This is where the Phase 0 rule pays off.

```python
def apply_rewrites(original_path, content_map, rewrites, output_path):
    doc = Document(original_path)

    for span in content_map:
        new_text = rewrites.get(span["id"])
        if new_text is None:
            continue  # unchanged — leave exactly as-is

        para = doc.paragraphs[span["paragraph_index"]]

        if span["run_count"] <= 1:
            # simple case: one run, just swap its text
            if para.runs:
                para.runs[0].text = new_text
            else:
                # paragraph had no runs at all (rare) — add one, inheriting
                # paragraph-level formatting only
                para.add_run(new_text)
        else:
            # multiple runs but flagged "uniform" (identical formatting) —
            # collapse safely: keep run 0's formatting, clear the rest
            para.runs[0].text = new_text
            for extra_run in para.runs[1:]:
                extra_run.text = ""

    doc.save(output_path)   # ALWAYS a new file — never overwrite the original
```

Notes:
- Bullet/numbering formatting lives in `pPr/numPr`, not in the run — it's untouched automatically since you're not rebuilding the paragraph.
- Hyperlink runs: if a run is part of a hyperlink relationship (e.g. portfolio/LinkedIn link), don't include it in the editable map at all — link text should stay factual, not be paraphrased.
- Typography: post-process `new_text` to convert straight quotes/apostrophes (`'`, `"`) to the typographic equivalents (`'`, `'`, `"`, `"`) so tailored text matches the rest of the document's typography.

---

## 5. Phase 4 — Verification

Don't ship the output blind — a rewritten bullet that's "within budget" by character count can still wrap to a third line and push a one-page resume onto page two.

```bash
soffice --headless --convert-to pdf tailored_resume.docx
pdftoppm -jpeg -r 150 tailored_resume.pdf page
```

1. **Page-count check (automatic):** convert both original and tailored docx to PDF, confirm page counts match. If the tailored version grew a page, trigger a shrink pass on the longest 2–3 edited fields and re-render.
2. **Visual diff (human-in-the-loop):** show original vs. tailored page images side by side, or a simple before/after text table per field, before the user accepts the final file. Given this is a local 2–3B model, a quick human glance before saving is cheap insurance against an odd phrasing slipping through.

---

## 6. Suggested Project Layout

```
resume_tailor/
  parser.py        # Phase 1 — Content Map builder (python-docx)
  llm_client.py     # Phase 2 — Ollama HTTP client, schema, prompts
  validator.py       # Phase 2 — pydantic schema + budget/retry logic
  reinjector.py       # Phase 3 — run-level write-back
  verifier.py         # Phase 4 — LibreOffice render + page-count diff
  cli.py              # orchestrates parser → llm_client → reinjector → verifier
requirements.txt      # python-docx, pydantic, requests, ollama (python client)
```

**Suggested build order:**
1. `parser.py` — get the Content Map right first; test on 3–5 real resume templates and eyeball the printed map before writing any LLM code.
2. `reinjector.py` — write the run-level patcher and test it with *hand-written* fake rewrites (no LLM yet) to confirm formatting survives a round-trip.
3. `llm_client.py` + `validator.py` — wire up Gemma 4 E2B once 1–2 are solid.
4. `verifier.py` — page-count + visual diff.
5. CLI first; a small local web UI (Streamlit/Gradio) for the before/after review step can come after the pipeline is trustworthy.

---

## 7. Edge Cases to Plan For

- **Tables used for layout** (common in two-column resume templates): apply the exact same run-level rule to table cells — never `cell.text = ...`, only `cell.paragraphs[i].runs[j].text = ...`.
- **Text boxes / DrawingML content:** python-docx can't read text inside floating text boxes. If a resume uses them for the header or a sidebar, those sections simply won't appear in the Content Map — treat as out-of-scope for v1 and flag to the user rather than failing silently.
- **Mixed-run bullets** (e.g., a metric mid-sentence in bold): these get flagged `needs_manual_review` by the parser rather than guessed at. It's fine for v1 to just leave these untouched and tell the user which lines weren't auto-tailored.
- **PDF-only resumes:** don't try to tailor a PDF directly with coordinate-based text replacement (the approach in your attached guide) — it doesn't reflow, and resume layouts are exactly the dense, multi-column case where that breaks fastest. Convert PDF → DOCX once up front (LibreOffice's import or a dedicated converter), run the whole pipeline above, then export the final DOCX → PDF for delivery. Treat PDF as an *output* format only, never the editable source.

---

## 8. Optional v2 Ideas

- **ATS keyword coverage score:** simple TF-IDF/keyword overlap between the JD and the tailored resume (no LLM needed) shown to the user as a sanity metric — separate from the LLM rewriting step, useful as a second opinion.
- **Word-native Track Changes output:** instead of silently swapping `run.text`, generate the diff as real `<w:ins>`/`<w:del>` XML elements so the user sees the edits as reviewable tracked changes when they open the file in Word. This requires moving from python-docx to the unpack-XML-edit-repack approach (raw `document.xml` editing) instead of the run-level method in Phase 3 — more work, but gives a much more trustworthy review experience than a flat diff table.
