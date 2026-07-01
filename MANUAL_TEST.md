# Manual Test: ATS-Optimised Resume Tailoring

Test every piece of the new ATS optimisation pipeline end-to-end.

---

## Prerequisites

```bash
# Ensure backend is running
cd backend
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Ensure frontend is running (separate terminal)
cd frontend
npm install
npm run dev
```

---

## Test 1: Unit — Keyword Extraction

**File:** `backend/app/services/ats_keywords.py`

Run from backend directory:
```python
python -c "
from app.services.ats_keywords import extract_jd_keywords

result = extract_jd_keywords(
    job_title='Senior Python Engineer',
    job_description='We need a Senior Python Engineer with FastAPI, Docker, and AWS experience.'
    ' Must have strong communication skills and stakeholder management.',
    job_skills=['Python', 'FastAPI', 'Docker', 'AWS'],
    max_keywords=15,
)

print('Keywords:', result['all_keywords'])
print('Technical:', result['technical'])
print('Soft skills:', result['soft_skills'])
print('Domain:', result['domain'])
print('Required:', result['required'])
print('Preferred:', result['preferred'])
assert len(result['all_keywords']) > 0, 'Should extract keywords'
assert 'Python' in result['technical'], 'Python should be in technical'
print('Test 1 PASSED')
"
```

**Expected:** Keywords extracted, categorised, with `Python`, `FastAPI`, `Docker`, `AWS` as required/technical.

---

## Test 2: Unit — Project Ranking

**File:** `backend/app/services/ats_scoring.py`

```python
python -c "
from app.services.ats_scoring import rank_projects_by_jd

projects = [
    {'name': 'E-commerce Platform', 'description': 'Built with React and Node.js'},
    {'name': 'Data Pipeline', 'description': 'Built ETL pipelines with Python and Airflow'},
    {'name': 'Mobile App', 'description': 'React Native app for iOS and Android'},
    {'name': 'Legacy Migration', 'description': 'Moved monolith to microservices on AWS'},
    {'name': 'Chat Bot', 'description': 'LLM-powered chatbot with RAG'},
]

keywords = ['Python', 'AWS', 'React', 'Node.js', 'LLM', 'RAG', 'microservices']

ranked = rank_projects_by_jd(projects, keywords, max_projects=3)
print('Ranked projects:')
for p in ranked:
    print(f'  - {p[\"name\"]}')
assert len(ranked) <= 3, 'Should keep max 3 projects'
print('Test 2 PASSED')
"
```

**Expected:** Top 3 projects by keyword relevance. Projects with `Python`/`AWS`/`React`/`LLM` should rank higher.

---

## Test 3: Unit — Bullet Reordering

**File:** `backend/app/services/ats_scoring.py`

```python
python -c "
from app.services.ats_scoring import reorder_bullets_by_jd

experience = [
    {
        'company': 'TechCorp',
        'title': 'Senior Engineer',
        'duration': '2020-2024',
        'description': (
            '- Led team of 5 engineers\n'
            '- Built REST APIs with FastAPI\n'
            '- Deployed microservices on AWS ECS\n'
            '- Mentored junior developers\n'
            '- Managed stakeholder expectations\n'
        ),
    }
]

keywords = ['FastAPI', 'AWS', 'REST', 'microservices', 'stakeholder management']

reordered = reorder_bullets_by_jd(experience, keywords)
bullets = [b.strip().lstrip('-').strip() for b in reordered[0]['description'].split('\n') if b.strip()]
print('Reordered bullets:')
for b in bullets:
    print(f'  - {b}')
# First bullet should be JD-relevant
assert 'REST' in bullets[0] or 'FastAPI' in bullets[0] or 'AWS' in bullets[0], 'First bullet should be JD-relevant'
print('Test 3 PASSED')
"
```

**Expected:** Bullets sorted with JD-relevant ones first (FastAPI, AWS, REST, microservices before leadership/mentoring).

---

## Test 4: Unit — Keyword Coverage

**File:** `backend/app/services/ats_scoring.py`

```python
python -c "
from app.services.ats_scoring import compute_keyword_coverage

tailored_data = {
    'summary': 'Experienced Python engineer with FastAPI and AWS skills.',
    'skills': ['Python', 'FastAPI', 'Docker', 'React'],
    'experience': [
        {'company': 'X', 'title': 'Engineer', 'description': 'Built microservices with AWS ECS'}
    ],
    'projects': [
        {'name': 'Pipeline', 'description': 'Python ETL pipeline'}
    ],
}

coverage = compute_keyword_coverage(tailored_data, ['Python', 'FastAPI', 'AWS', 'Kubernetes', 'React'])
print('Matched:', coverage['matched'])
print('Missing:', coverage['missing'])
print('Coverage:', coverage['coverage_pct'], '%')
print('Distribution:', coverage['distribution'])
assert 'Python' in coverage['matched']
assert 'Kubernetes' in coverage['missing']
assert coverage['coverage_pct'] == 80.0
print('Test 4 PASSED')
"
```

**Expected:** 4/5 matched (80%), `Kubernetes` missing.

---

## Test 5: Unit — Paper Format Detection

**File:** `backend/app/services/ats_location.py`

```python
python -c "
from app.services.ats_location import detect_paper_format, paper_format_to_page_width

# US location
assert detect_paper_format('San Francisco, CA', '') == 'letter'
assert detect_paper_format('New York, NY', '') == 'letter'
assert detect_paper_format('Remote (US)', '') == 'letter'
assert detect_paper_format('Toronto, ON', '') == 'letter'

# Non-US location
assert detect_paper_format('London, UK', '') == 'a4'
assert detect_paper_format('Berlin, Germany', '') == 'a4'
assert detect_paper_format('Sydney, Australia', '') == 'a4'
assert detect_paper_format('Mumbai, India', '') == 'a4'

# Default
assert detect_paper_format(None, '') == 'letter'

# Page width mapping
assert paper_format_to_page_width('letter') == '8.5in'
assert paper_format_to_page_width('a4') == '210mm'

print('Test 5 PASSED')
"
```

**Expected:** All assertions pass.

---

## Test 6: Unit — HTML Template Renderer

**File:** `backend/app/services/html_renderer.py`

```python
python -c "
from app.services.html_renderer import (
    render_cv_template, build_contact_items, build_competency_tags,
    build_experience_html, build_projects_html, build_education_html,
)

# Build contact items
contact = build_contact_items(
    email='john@example.com',
    phone='+1-555-1234',
    location='San Francisco, CA',
    linkedin_url='https://linkedin.com/in/john',
)
print('Contact:', contact)

# Build competency tags
tags = build_competency_tags(['Python', 'FastAPI', 'AWS', 'Docker'])
print('Tags:', tags)

# Render full template
html = render_cv_template(
    lang='en',
    page_width='8.5in',
    name='John Doe',
    contact_items=contact,
    summary_text='Experienced software engineer.',
    competency_tags=tags,
    experience_html=build_experience_html([
        {'company': 'TechCorp', 'title': 'Senior Engineer', 'duration': '2020-2024',
         'description': '- Built APIs\\n- Deployed on AWS'}
    ]),
    projects_html=build_projects_html([
        {'name': 'My Project', 'description': 'A cool project'}
    ]),
    education_html=build_education_html([
        {'institution': 'MIT', 'degree': 'BS CS', 'year': 2018}
    ]),
)

# Verify placeholders are replaced
assert '{{NAME}}' not in html
assert '{{CONTACT_ITEMS}}' not in html
assert 'John Doe' in html
assert 'section-header' in html
print('Test 6 PASSED')
"
```

**Expected:** All placeholders replaced. Valid HTML with ATS-optimised CSS classes.

---

## Test 7: Integration — Full API Tailor Flow

**Requires:** MongoDB running, backend running.

```bash
# Step 1: Upload a resume
curl -X POST http://localhost:8000/api/v1/resumes/upload \
  -F "file=@test_resume.pdf" \
  -H "Content-Type: multipart/form-data"

# Save the resume_id from response

# Step 2: Search for a job
curl -X POST http://localhost:8000/api/v1/jobs/search \
  -H "Content-Type: application/json" \
  -d '{"user_input": "Python engineer"}' \
  | python -m json.tool

# Save one job_id from the response

# Step 3: Tailor resume
curl -X POST http://localhost:8000/api/v1/resumes/tailor-structured \
  -H "Content-Type: application/json" \
  -d '{"resume_id": "<resume_id>", "job_id": "<job_id>"}' \
  | python -m json.tool
```

**Expected response** includes new fields:
```json
{
  "keyword_coverage_pct": 72.3,
  "paper_format": "letter",
  "jd_keywords": ["Python", "FastAPI", "AWS", ...],
  "competency_keywords": ["Python", "FastAPI", ...],
  "selected_project_count": 3,
  "keyword_distribution": {
    "summary": ["Python"],
    "experience": ["Python", "FastAPI", "AWS"],
    "skills": ["Python", "FastAPI"],
    "projects": []
  }
}
```

---

## Test 8: Visual — PDF Output Quality

1. Run Test 7 (get a tailored resume PDF)
2. Download the PDF via the frontend or curl
3. Open in any PDF viewer and verify:
   - [ ] Font is Space Grotesk for headings (header name, section titles)
   - [ ] Font is DM Sans for body text
   - [ ] Gradient line below name (teal-to-purple, 2px)
   - [ ] Contact info in a single row with `|` separators
   - [ ] Section headers: 13px uppercase, teal color, letter-spaced
   - [ ] Company names in purple
   - [ ] Competency tags in purple on light purple background
   - [ ] Bullet points are disc-style, properly indented
   - [ ] Pages use Letter (8.5×11in) or A4 based on company location
   - [ ] Margins are consistent at 0.6in all sides
   - [ ] No images, no SVGs, no tables — ATS-safe
   - [ ] All text is selectable and searchable (not rasterized)
   - [ ] Single-column layout throughout

---

## Test 9: Visual — Frontend ATS Metadata Display

1. Open the frontend at `http://localhost:5173`
2. Click on a job to open its detail page
3. Upload a resume (PDF/DOCX)
4. Click "Tailor Resume"
5. After completion, verify:
   - [ ] ATS Match percentage badge (green/yellow/red)
   - [ ] "Format: Letter (US/Canada)" or "A4 (Rest of World)"
   - [ ] "N most relevant projects selected"
   - [ ] Expandable keyword section showing matched (green) vs missing (red)
   - [ ] Download buttons still work for PDF, DOCX, and cover letter

---

## Test 10: Edge Cases

```python
python -c "
from app.services.ats_keywords import extract_jd_keywords
from app.services.ats_scoring import rank_projects_by_jd, compute_keyword_coverage
from app.services.ats_location import detect_paper_format

# Edge: Empty JD
print('Empty JD:', extract_jd_keywords('', '', [])['all_keywords'])
assert extract_jd_keywords('', '', [])['all_keywords'] == []

# Edge: No projects
assert rank_projects_by_jd([], ['Python'], max_projects=4) == []

# Edge: No keywords
cov = compute_keyword_coverage({'skills': ['Python']}, [])
assert cov['coverage_pct'] == 0.0

# Edge: Remote worldwide
assert detect_paper_format('Remote', 'This is a worldwide remote role') == 'letter'

# Edge: null location
assert detect_paper_format(None, 'Anywhere') == 'letter'

print('Test 10 PASSED — all edge cases handled')
"
```

---

## Summary

| Test | What it verifies | Status |
|------|-----------------|--------|
| 1 | Keyword extraction from JD | ☐ |
| 2 | Project ranking by relevance | ☐ |
| 3 | Bullet point reordering | ☐ |
| 4 | Keyword coverage computation | ☐ |
| 5 | Paper format detection | ☐ |
| 6 | HTML template rendering | ☐ |
| 7 | Full API tailor flow with new fields | ☐ |
| 8 | PDF visual quality | ☐ |
| 9 | Frontend ATS metadata display | ☐ |
| 10 | Edge cases | ☐ |
