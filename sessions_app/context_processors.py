"""Template context shared by every Snapline page."""

from django.conf import settings


def snapline(request):
    """Add project-wide values to every template's context.

    Exposes the source code URL so every page can offer users the source,
    as AGPL-3.0 section 13 requires for network-accessible software.

    Params:
        request: The current request (unused).

    Returns:
        A dict with the source code URL.
    """
    del request
    return {"snapline_source_url": settings.SNAPLINE_SOURCE_URL}
