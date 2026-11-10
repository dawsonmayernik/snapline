"""Admin pages for inspecting support sessions.

Everything here is read-only. Sessions, links, and photos are created
through the app itself, so the admin is for oversight, not editing.
"""

from django.contrib import admin

from .models import ConsentRecord, JoinToken, Photo, SupportSession


class ReadOnlyAdmin(admin.ModelAdmin):
    """Admin base class that allows viewing but not changing records."""

    def has_add_permission(self, request):
        """Disallow creating records from the admin.

        Params:
            request: The current request.

        Returns:
            Always False.
        """
        return False

    def has_change_permission(self, request, obj=None):
        """Disallow editing records from the admin.

        Params:
            request: The current request.
            obj: The record being viewed, if any.

        Returns:
            Always False.
        """
        return False


@admin.register(SupportSession)
class SupportSessionAdmin(ReadOnlyAdmin):
    """Admin listing of support sessions."""

    list_display = ["__str__", "created_by", "status", "created_at", "expires_at"]
    list_filter = ["status"]


@admin.register(JoinToken)
class JoinTokenAdmin(ReadOnlyAdmin):
    """Admin listing of join tokens (hashes only, never raw tokens)."""

    list_display = ["session", "created_at", "expires_at", "used_at", "revoked_at"]


@admin.register(ConsentRecord)
class ConsentRecordAdmin(ReadOnlyAdmin):
    """Admin listing of customer consent records."""

    list_display = ["session", "policy_version", "accepted_at"]


@admin.register(Photo)
class PhotoAdmin(ReadOnlyAdmin):
    """Admin listing of photo metadata.

    The image itself is deliberately not shown here; photos are viewed only
    through the session page by the rep who owns the session.
    """

    list_display = ["session", "uploaded_at", "width", "height"]
    exclude = ["image"]
