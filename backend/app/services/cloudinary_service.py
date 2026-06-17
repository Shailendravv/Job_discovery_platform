"""
Cloudinary service for file upload, download URL generation, and file streaming.

Key design rules (per Cloudinary docs):
- PDFs must be uploaded with resource_type="image" (Cloudinary treats PDFs as images
  for page-by-page transformations).
- The public_id must NOT include the file extension (e.g., "resumes/uuid" not "resumes/uuid.pdf").
- When generating delivery URLs for PDFs, use resource_type="image" and format="pdf".
- DOCX files should use resource_type="raw" (no special handling needed).
- Free Cloudinary accounts block PDF/ZIP delivery by default; unblock in Security settings.
"""
import logging
import re
import httpx
import cloudinary
import cloudinary.uploader
import cloudinary.utils
from app.core.config import settings

log = logging.getLogger(__name__)


def configure_cloudinary():
    """Configure Cloudinary with settings from .env."""
    if not settings.CLOUDINARY_CLOUD_NAME or not settings.CLOUDINARY_API_KEY or not settings.CLOUDINARY_API_SECRET:
        raise ValueError(
            "Cloudinary is not configured. Set CLOUDINARY_CLOUD_NAME, "
            "CLOUDINARY_API_KEY, and CLOUDINARY_API_SECRET in .env"
        )
    cloudinary.config(
        cloud_name=settings.CLOUDINARY_CLOUD_NAME,
        api_key=settings.CLOUDINARY_API_KEY,
        api_secret=settings.CLOUDINARY_API_SECRET,
        secure=True,
    )


async def upload_file(
    file_bytes: bytes,
    public_id: str,
    resource_type: str = "raw",
) -> dict:
    """
    Upload a file to Cloudinary.

    Args:
        file_bytes: Raw file bytes to upload.
        public_id: Desired public ID WITHOUT file extension
                   (e.g. "resumes/uuid" NOT "resumes/uuid.pdf").
        resource_type: "image" for PDFs, "raw" for DOCX/other documents.

    Returns:
        dict with keys: url, public_id, format, bytes
    """
    configure_cloudinary()
    result = cloudinary.uploader.upload(
        file_bytes,
        public_id=public_id,
        resource_type=resource_type,
        overwrite=True,
    )
    return {
        "url": result["secure_url"],
        "public_id": result["public_id"],
        "format": result.get("format", ""),
        "bytes": result.get("bytes", 0),
    }


def get_download_url(public_id: str, resource_type: str = "image", file_format: str | None = "pdf") -> str:
    """
    Generate a proper Cloudinary download/delivery URL.

    For PDFs:
        - resource_type must be "image" (not "raw")
        - file_format must be "pdf" (appended to the URL)
        - public_id must NOT include the .pdf extension

    For DOCX:
        - resource_type must be "raw"
        - file_format is ignored (Cloudinary serves raw files as-is)

    Args:
        public_id: Cloudinary public_id WITHOUT file extension.
        resource_type: "image" for PDFs, "raw" for DOCX.
        file_format: File format to append (e.g. "pdf"). Ignored for resource_type="raw".

    Returns:
        Fully qualified HTTPS URL to the file.
    """
    configure_cloudinary()

    if resource_type == "raw":
        # Raw files are served directly — use cloudinary_url without format
        url, _ = cloudinary.utils.cloudinary_url(
            public_id,
            resource_type="raw",
        )
    else:
        # Images/PDFs — specify the format
        url, _ = cloudinary.utils.cloudinary_url(
            public_id,
            resource_type=resource_type,
            format=file_format or "pdf",
        )

    return url


async def stream_file(public_id: str, resource_type: str = "image", file_format: str | None = "pdf"):
    """
    Async generator that streams file bytes from Cloudinary.

    Yields chunks of bytes that can be used with FastAPI's StreamingResponse.
    Raises HTTPException if Cloudinary returns a non-200 status.
    """
    from fastapi import HTTPException

    url = get_download_url(public_id, resource_type=resource_type, file_format=file_format)

    async with httpx.AsyncClient() as client:
        async with client.stream("GET", url) as response:
            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=(
                        f"Cloudinary blocked delivery (HTTP {response.status_code}). "
                        "If this is a PDF, uncheck 'Restrict PDF and ZIP files delivery' "
                        "in Cloudinary Dashboard > Settings > Security."
                    ),
                )
            async for chunk in response.aiter_bytes():
                yield chunk


def get_resource_type_for_file(filename: str) -> str:
    """
    Determine the correct Cloudinary resource_type based on file extension.

    - PDF → "image" (Cloudinary treats PDFs as images)
    - Everything else → "raw"
    """
    if filename.lower().endswith(".pdf"):
        return "image"
    return "raw"


def get_format_for_file(filename: str) -> str | None:
    """
    Get the format string for Cloudinary URL generation.

    - PDF → "pdf"
    - DOCX → None (no format needed for raw)
    """
    if filename.lower().endswith(".pdf"):
        return "pdf"
    if filename.lower().endswith(".docx"):
        return None
    # Fallback: extract extension without dot
    if "." in filename:
        return filename.rsplit(".", 1)[-1]
    return None


def parse_cloudinary_url(cloudinary_url: str) -> dict:
    """
    Parse a Cloudinary delivery URL into its components for re-download.

    Handles both formats:
      - PDF (resource_type="image"): https://res.cloudinary.com/{cloud}/image/upload/v1/{public_id}.pdf
      - Raw (resource_type="raw"):   https://res.cloudinary.com/{cloud}/raw/upload/v1/{public_id}

    Returns:
        dict with keys: public_id, resource_type, file_format, filename

    Raises:
        ValueError if the URL cannot be parsed.
    """
    # Expected pattern:
    # https://res.cloudinary.com/{cloud_name}/{resource_type}/upload/v{version}/{path}
    import re

    # Strip query params
    url = cloudinary_url.split("?")[0]

    # Match: https://res.cloudinary.com/{cloud}/{resource_type}/upload/v{version}/{rest}
    pattern = r"^https?://res\.cloudinary\.com/[^/]+/([^/]+)/upload/v\d+/(.+)$"
    match = re.match(pattern, url)
    if not match:
        raise ValueError(f"Could not parse Cloudinary URL: {cloudinary_url}")

    resource_type = match.group(1)
    path = match.group(2)

    if resource_type == "raw":
        # Raw URLs: no format extension
        public_id = path
        file_format = None
        filename = path.rsplit("/", 1)[-1] or "download"
    else:
        # Image URLs: path ends with .{format}
        if "." not in path:
            # No extension - assume PDF
            public_id = path
            file_format = "pdf"
            filename = f"{path.rsplit('/', 1)[-1]}.pdf"
        else:
            public_id, file_format = path.rsplit(".", 1)
            filename = path.rsplit("/", 1)[-1] or f"download.{file_format}"

    return {
        "public_id": public_id,
        "resource_type": resource_type,
        "file_format": file_format,
        "filename": filename,
    }
