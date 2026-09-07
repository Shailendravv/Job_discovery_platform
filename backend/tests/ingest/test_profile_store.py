"""``profile_status``/``add_profile_file`` — milestone 4, PLAN.md §3
"Profile store". Extraction dispatch is exercised against real .md/.txt
input (no parsing needed) and against mocked PDF/DOCX extractors so this
suite never needs a real binary fixture or the pypdf/python-docx stack."""

from pathlib import Path
from unittest.mock import patch

import pytest

from app.ingest.profile_store import (
    PROSE_FILES,
    RESUME_FILENAME,
    UnsupportedProfileFileError,
    add_profile_file,
    profile_status,
)


@pytest.fixture
def isolated_profile_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("app.ingest.profile_store.PROFILE_DIR", tmp_path)
    return tmp_path


def test_profile_status_reports_all_four_files_missing_on_empty_dir(isolated_profile_dir):
    rows = profile_status()
    names = [r.name for r in rows]
    assert names == [RESUME_FILENAME, *PROSE_FILES]
    assert all(not r.exists for r in rows)
    assert all(r.size_bytes == 0 for r in rows)


def test_profile_status_reports_existing_file_size(isolated_profile_dir):
    (isolated_profile_dir / "preferences.md").write_text("hello", encoding="utf-8")
    rows = profile_status()
    prefs = next(r for r in rows if r.name == "preferences.md")
    assert prefs.exists is True
    assert prefs.size_bytes == 5


def test_add_profile_file_rejects_unknown_as_key(isolated_profile_dir, tmp_path):
    src = tmp_path / "in.md"
    src.write_text("resume text", encoding="utf-8")
    with pytest.raises(UnsupportedProfileFileError):
        add_profile_file(src, as_key="preferences")


def test_add_profile_file_rejects_unsupported_extension(isolated_profile_dir, tmp_path):
    src = tmp_path / "in.xyz"
    src.write_text("resume text", encoding="utf-8")
    with pytest.raises(UnsupportedProfileFileError):
        add_profile_file(src, as_key="resume")


def test_add_profile_file_passes_through_markdown_unchanged(isolated_profile_dir, tmp_path):
    src = tmp_path / "in.md"
    src.write_text("# My Resume\n\nPython, FastAPI.", encoding="utf-8")

    status = add_profile_file(src, as_key="resume")

    dest = isolated_profile_dir / RESUME_FILENAME
    assert status.exists is True
    assert status.path == str(dest)
    assert dest.read_text(encoding="utf-8").strip() == "# My Resume\n\nPython, FastAPI."


def test_add_profile_file_rejects_empty_extracted_text(isolated_profile_dir, tmp_path):
    src = tmp_path / "in.txt"
    src.write_text("   \n  ", encoding="utf-8")
    with pytest.raises(UnsupportedProfileFileError):
        add_profile_file(src, as_key="resume")


def test_add_profile_file_dispatches_pdf_to_pdf_service(isolated_profile_dir, tmp_path):
    src = tmp_path / "resume.pdf"
    src.write_bytes(b"%PDF-fake-bytes")

    with patch("app.services.PDF_service.extract_text_from_pdf", return_value="Extracted PDF text") as mock_extract:
        status = add_profile_file(src, as_key="resume")

    mock_extract.assert_called_once_with(b"%PDF-fake-bytes")
    dest = Path(status.path)
    assert dest.read_text(encoding="utf-8").strip() == "Extracted PDF text"


def test_add_profile_file_dispatches_docx_to_docx_service(isolated_profile_dir, tmp_path):
    src = tmp_path / "resume.docx"
    src.write_bytes(b"fake-docx-bytes")

    with patch("app.services.docx_service.extract_text_from_docx", return_value="Extracted DOCX text") as mock_extract:
        status = add_profile_file(src, as_key="resume")

    mock_extract.assert_called_once_with(b"fake-docx-bytes")
    dest = Path(status.path)
    assert dest.read_text(encoding="utf-8").strip() == "Extracted DOCX text"


def test_add_profile_file_overwrites_existing_resume(isolated_profile_dir, tmp_path):
    (isolated_profile_dir / RESUME_FILENAME).write_text("old resume", encoding="utf-8")
    src = tmp_path / "new.md"
    src.write_text("new resume", encoding="utf-8")

    add_profile_file(src, as_key="resume")

    assert (isolated_profile_dir / RESUME_FILENAME).read_text(encoding="utf-8").strip() == "new resume"
