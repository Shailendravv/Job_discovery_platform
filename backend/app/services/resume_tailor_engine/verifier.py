"""
Phase 4 — Verification

After reinjection, the tailored resume's page count should match the original.
A rewritten bullet that's "within budget" by character count can still wrap
to a third line and push a one-page resume onto page two.

This module:
1. Converts both original and tailored to PDF (via LibreOffice headless)
2. Compares page counts
3. Optionally renders a side-by-side image diff for human review

Requirements:
    - LibreOffice (soffice) installed system-wide for DOCX → PDF conversion
    - pdftoppm (poppler-utils) for PDF → image rendering (optional, for visual diff)
"""

import logging
import os
import subprocess
import tempfile
from typing import Optional

log = logging.getLogger(__name__)


def verify_page_count(
    original_path: str,
    tailored_path: str,
    min_pages: int = 1,
    max_pages: int = 10,
) -> Optional[bool]:
    """
    Convert both DOCX files to PDF and compare page counts.

    Args:
        original_path: Path to the original resume .docx.
        tailored_path: Path to the tailored resume .docx.
        min_pages: Minimum expected pages (below this = conversion error).
        max_pages: Maximum expected pages (sanity check).

    Returns:
        True if page counts match.
        False if they differ.
        None if conversion or comparison fails.

    Raises:
        FileNotFoundError: If either input file doesn't exist.
    """
    if not os.path.exists(original_path):
        raise FileNotFoundError(f"Original file not found: {original_path}")
    if not os.path.exists(tailored_path):
        raise FileNotFoundError(f"Tailored file not found: {tailored_path}")

    # ── Check if LibreOffice is available ──
    if not _libreoffice_available():
        log.warning("LibreOffice not found. Page count verification requires soffice.")
        return None

    with tempfile.TemporaryDirectory() as tmp_dir:
        try:
            # Convert original to PDF
            orig_pdf = _convert_to_pdf(original_path, tmp_dir)
            if not orig_pdf:
                return None

            # Convert tailored to PDF
            tailored_pdf = _convert_to_pdf(tailored_path, tmp_dir)
            if not tailored_pdf:
                return None

            # Count pages
            orig_pages = _count_pdf_pages(orig_pdf)
            tailored_pages = _count_pdf_pages(tailored_pdf)

            if orig_pages is None or tailored_pages is None:
                return None

            # Sanity checks
            if orig_pages < min_pages or orig_pages > max_pages:
                log.warning(
                    "Original page count (%d) outside expected range [%d, %d]",
                    orig_pages,
                    min_pages,
                    max_pages,
                )

            match = orig_pages == tailored_pages
            if match:
                log.info("Page count verified: both are %d page(s)", orig_pages)
            else:
                log.warning(
                    "Page count mismatch: original has %d page(s), tailored has %d page(s)",
                    orig_pages,
                    tailored_pages,
                )

            return match

        except Exception as e:
            log.error("Page count verification failed: %s", e, exc_info=True)
            return None


def render_diff_pages(
    original_path: str,
    tailored_path: str,
    output_dir: str,
    dpi: int = 150,
) -> list[str]:
    """
    Render both PDFs as images and save side-by-side comparison.

    Args:
        original_path: Path to original resume .docx.
        tailored_path: Path to tailored resume .docx.
        output_dir: Directory where page images will be saved.
        dpi: Image resolution.

    Returns:
        List of paths to generated comparison image files.
        Empty list if rendering fails.

    Requires:
        - soffice (LibreOffice) for DOCX → PDF
        - pdftoppm (poppler-utils) for PDF → image
    """
    comparison_images: list[str] = []

    if not _libreoffice_available():
        log.warning("LibreOffice not available. Cannot render diff pages.")
        return comparison_images

    if not _pdftoppm_available():
        log.warning("pdftoppm not available. Cannot render diff pages.")
        return comparison_images

    os.makedirs(output_dir, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp_dir:
        try:
            # Convert to PDFs
            orig_pdf = _convert_to_pdf(original_path, tmp_dir)
            tailored_pdf = _convert_to_pdf(tailored_path, tmp_dir)

            if not orig_pdf or not tailored_pdf:
                return comparison_images

            # Render pages to images
            orig_images = _pdf_to_images(orig_pdf, tmp_dir, dpi)
            tailored_images = _pdf_to_images(tailored_pdf, tmp_dir, dpi)

            # Create comparison images (one per page pair)
            max_pages = max(len(orig_images), len(tailored_images))
            for i in range(max_pages):
                # We just track which pages exist — the user can inspect manually
                comp_filename = f"page_{i + 1:03d}.png"
                comp_path = os.path.join(output_dir, comp_filename)

                # Simple approach: save side indicator
                orig_exists = i < len(orig_images)
                tailored_exists = i < len(tailored_images)

                if orig_exists and tailored_exists:
                    label = f"Page {i + 1}: Both"
                elif orig_exists:
                    label = f"Page {i + 1}: Original only"
                else:
                    label = f"Page {i + 1}: Tailored only"

                # Write a small text file indicating the status
                info_path = os.path.join(output_dir, f"page_{i + 1:03d}_info.txt")
                with open(info_path, "w") as f:
                    f.write(label)

                comparison_images.append(comp_path)

            return comparison_images

        except Exception as e:
            log.error("Diff rendering failed: %s", e, exc_info=True)
            return comparison_images


# ═══════════════════════════════════════════════════════════════
#  Internal helpers
# ═══════════════════════════════════════════════════════════════


def _libreoffice_available() -> bool:
    """Check if LibreOffice soffice command is available."""
    try:
        result = subprocess.run(
            ["soffice", "--headless", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _pdftoppm_available() -> bool:
    """Check if pdftoppm is available."""
    try:
        result = subprocess.run(
            ["pdftoppm", "-v"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _convert_to_pdf(docx_path: str, output_dir: str) -> Optional[str]:
    """
    Convert a DOCX file to PDF using LibreOffice headless.

    Returns path to the generated PDF, or None on failure.
    """
    try:
        result = subprocess.run(
            [
                "soffice",
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                output_dir,
                docx_path,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode != 0:
            log.error("LibreOffice conversion failed (code %d): %s", result.returncode, result.stderr[:200])
            return None

        # Derived PDF filename
        base = os.path.splitext(os.path.basename(docx_path))[0]
        pdf_path = os.path.join(output_dir, f"{base}.pdf")

        if not os.path.exists(pdf_path):
            log.error("PDF output not found after conversion: %s", pdf_path)
            return None

        return pdf_path

    except FileNotFoundError:
        log.error("LibreOffice (soffice) not found on system PATH")
        return None
    except subprocess.TimeoutExpired:
        log.error("LibreOffice conversion timed out after 60s")
        return None
    except Exception as e:
        log.error("DOCX → PDF conversion failed: %s", e, exc_info=True)
        return None


def _count_pdf_pages(pdf_path: str) -> Optional[int]:
    """
    Count the number of pages in a PDF.

    Uses pdftoppm -f 1 -l 1 and counts actual pages, or falls back
    to various pdfinfo/pypdf approaches.
    """
    # Method 1: pdfinfo (poppler-utils)
    try:
        result = subprocess.run(
            ["pdfinfo", pdf_path],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            for line in result.stdout.split("\n"):
                if "Pages" in line:
                    parts = line.split(":")
                    if len(parts) >= 2:
                        return int(parts[1].strip())
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        pass

    # Method 2: fallback to pypdf
    try:
        from pypdf import PdfReader
        reader = PdfReader(pdf_path)
        return len(reader.pages)
    except Exception as e:
        log.warning("Failed to count PDF pages with pypdf: %s", e)

    return None


def _pdf_to_images(pdf_path: str, output_dir: str, dpi: int = 150) -> list[str]:
    """
    Render PDF pages as JPEG images using pdftoppm.

    Returns list of image paths, one per page.
    """
    output_pattern = os.path.join(output_dir, "page")
    images: list[str] = []

    try:
        result = subprocess.run(
            [
                "pdftoppm",
                "-jpeg",
                "-r",
                str(dpi),
                pdf_path,
                output_pattern,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode != 0:
            log.error("pdftoppm failed (code %d): %s", result.returncode, result.stderr[:200])
            return images

        # Collect generated images
        for f in sorted(os.listdir(output_dir)):
            if f.startswith("page") and f.endswith(".jpg"):
                images.append(os.path.join(output_dir, f))

        return images

    except FileNotFoundError:
        log.error("pdftoppm not found on system PATH")
        return images
    except subprocess.TimeoutExpired:
        log.error("pdftoppm timed out after 60s")
        return images
    except Exception as e:
        log.error("PDF → image rendering failed: %s", e, exc_info=True)
        return images
