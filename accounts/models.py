"""Account models for Snapline support staff."""

from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """A support representative (CSR) who can open photo sessions.

    Extends Django's built-in user so staff-specific fields (organization,
    role) can be added later without a painful user-model migration.
    """
