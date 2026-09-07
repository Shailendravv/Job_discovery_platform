"""Profile store — PLAN.md §3 "Profile store" (milestone 2's own status note
deferred this to milestone 4). ``profile/`` holds the plain-markdown files
the judging agent reads directly every ``/nightly`` run:

    profile/resume.md          — extracted resume text (this module writes it)
    profile/preferences.md     — locations, visa status, salary floor, domains
    profile/hard_filters.md    — automatic disqualifiers, stated plainly
    profile/calibration.md     — grows over time (PLAN.md §5 "Calibration")

PLAN.md is explicit: "The agent reads these files directly. Do not
summarize them into a prompt template — let the model see the source." So
``profile_add_resume`` only extracts text (reusing the existing PDF/DOCX
services) and writes markdown — it never calls an LLM, matching the
anti-goal "Do not add an LLM API key requirement to the judging path."

``profile/`` lives under ``backend/`` (next to ``config/``), matching how
``jobctl`` is installed and run from ``backend/`` — same convention as
``app.ingest.prefilter.CONFIG_PATH``. Real content is gitignored (PLAN.md
§10: "Never commit profile/ contents ... to a public repo"); ``*.example``
seed templates are tracked, the same split this repo already uses for
``backend/.env`` / ``backend/.env.example``. See backend/docs/judging.md.
"""

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

# backend/app/ingest/profile_store.py -> up 2 levels -> backend/ -> profile/
PROFILE_DIR = Path(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
) / "profile"

RESUME_FILENAME = "resume.md"

# The hand-edited prose files (PLAN.md §3) — not written by any jobctl
# command, only checked for presence so `profile show` / `/nightly` can
# tell the user what's still missing.
PROSE_FILES = ("preferences.md", "hard_filters.md", "calibration.md")

# What `jobctl profile add --as <key>` is allowed to write. Only "resume" is
# parsed from a binary file; the prose files are meant to be hand-written
# directly per PLAN.md §3, not generated.
ADDABLE_KEYS = {"resume": RESUME_FILENAME}

_PDF_EXTENSIONS = {".pdf"}
_DOCX_EXTENSIONS = {".docx", ".doc"}


@dataclass
class ProfileFileStatus:
    name: str
    path: str
    exists: bool
    size_bytes: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


class UnsupportedProfileFileError(ValueError):
    pass


def profile_status() -> list[ProfileFileStatus]:
    """One row per profile file PLAN.md §3 describes (resume + the three
    prose files), in read order — ``jobctl profile show`` and the
    ``/nightly`` pre-flight check both use this to report what's missing
    before spending any judging quota."""
    rows = []
    for name in (RESUME_FILENAME, *PROSE_FILES):
        path = PROFILE_DIR / name
        exists = path.is_file()
        rows.append(
            ProfileFileStatus(
                name=name,
                path=str(path),
                exists=exists,
                size_bytes=path.stat().st_size if exists else 0,
            )
        )
    return rows


def _normalize_newlines(text: str) -> str:
    """CRLF/CR -> LF. Without this, a source file carrying \\r\\n (common on
    Windows) round-trips through ``Path.write_text``'s own \\n -> \\r\\n
    translation and comes out doubled (\\r\\n -> \\r\\r\\n). Normalize once,
    right after extraction, so the file this module writes is always plain
    \\n regardless of the source file's or the OS's line endings."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _extract_text(filename: str, raw_bytes: bytes) -> str:
    """Plain-text extraction only — reuses the existing, LLM-free services
    already used by the resume-upload endpoint (``app.services.PDF_service``
    / ``app.services.docx_service``). ``.md``/``.txt`` pass through
    unchanged so a user who already has a plain-text resume doesn't need to
    round-trip it through a document format."""
    suffix = Path(filename).suffix.lower()

    if suffix in _PDF_EXTENSIONS:
        from app.services.PDF_service import extract_text_from_pdf

        text = extract_text_from_pdf(raw_bytes)
    elif suffix in _DOCX_EXTENSIONS:
        from app.services.docx_service import extract_text_from_docx

        text = extract_text_from_docx(raw_bytes)
    elif suffix in (".md", ".markdown", ".txt"):
        text = raw_bytes.decode("utf-8")
    else:
        raise UnsupportedProfileFileError(
            f"unsupported file type {suffix or '(none)'!r} — expected .pdf, .docx, .md, or .txt"
        )

    return _normalize_newlines(text)


def add_profile_file(source_path: Path, *, as_key: str) -> ProfileFileStatus:
    """Extract text from ``source_path`` and write it to ``profile/<file>``
    for the given ``as_key`` (currently only ``"resume"`` — PLAN.md §3
    ``jobctl profile add resume.pdf --as resume``). Overwrites any existing
    file at that path unconditionally — unlike ``jobctl judge --apply``,
    there's no ``--force`` gate here: re-running ``profile add`` with an
    updated resume is the expected way to refresh it, not a rare
    destructive action worth a confirmation prompt."""
    if as_key not in ADDABLE_KEYS:
        raise UnsupportedProfileFileError(
            f"--as must be one of {sorted(ADDABLE_KEYS)} — the other profile "
            f"files ({', '.join(PROSE_FILES)}) are hand-edited prose, not "
            f"parsed from a file (PLAN.md §3)"
        )

    raw_bytes = source_path.read_bytes()
    text = _extract_text(source_path.name, raw_bytes)
    if not text.strip():
        raise UnsupportedProfileFileError(f"no text could be extracted from {source_path}")

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    dest = PROFILE_DIR / ADDABLE_KEYS[as_key]
    dest.write_text(text.strip() + "\n", encoding="utf-8")

    return ProfileFileStatus(
        name=dest.name, path=str(dest), exists=True, size_bytes=dest.stat().st_size
    )
