"""
Cloudinary service for file upload and management.
"""
import cloudinary
import cloudinary.uploader
from app.core.config import settings


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


async def upload_file(file_bytes: bytes, public_id: str, resource_type: str = "raw") -> dict:
    """
    Upload a file to Cloudinary.

    Args:
        file_bytes: Raw file bytes to upload.
        public_id: Desired public ID (e.g., "resumes/uuid-filename").
        resource_type: Cloudinary resource type ("raw" for documents, "image" for images).

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
