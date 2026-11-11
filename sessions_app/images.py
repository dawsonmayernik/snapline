"""
Sanitizing of customer-uploaded photos.

The original bytes are never stored. Each photo is decoded, checked, and reencoded
as a fresh JPEG, which removes all metadata and any non-image content hidden in the
file.
"""

from io import BytesIO

from django.conf import settings
from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError

# Image formats accepted from customers (as identified by Pillow, not by
# the file name or the browser-supplied content type).
ALLOWED_FORMATS = frozenset({"JPEG", "PNG", "WEBP"})


class InvalidImageError(Exception):
    """Raised when an upload is not an acceptable image."""


def sanitize_photo(uploaded_file) -> ContentFile:
    """Decode, check, and re-encode an uploaded photo.

    Params:
        uploaded_file: A file-like objejct containing the upload.

    Returns:
        A ContentFile holding the sanitized JPEG bytes.. Its name is a
        place holder; Photo's uploaded path replaces it with a UUID.

    Throws:
        InvalidImageError: If the file is not an acceptable image.
    """
    try:
        with Image.open(uploaded_file) as original:
            if original.format not in ALLOWED_FORMATS:
                raise InvalidImageError(f"Unsupported format: {original.format}")
            width, height = original.size
            if width * height > settings.SNAPLINE_MAX_IMAGE_PIXELS:
                raise InvalidImageError("Image has too many pixels.")
            image = ImageOps.exif_transpose(original).convert("RGB")
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as exc:
        raise InvalidImageError("File is not a readable image.") from exc

    max_dimension = settings.SNAPLINE_PHOTO_MAX_DIMENSION
    image.thumbnail((max_dimension, max_dimension))
    output = BytesIO()
    image.save(
        output,
        format="JPEG",
        quality=settings.SNAPLINE_PHOTO_JPEG_QUALITY,
        optimize=True,
    )
    return ContentFile(output.getvalue(), name="photo.jpg")
