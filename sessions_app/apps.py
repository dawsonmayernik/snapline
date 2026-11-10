"""Django application configuration for support sessions."""

from django.apps import AppConfig


class SessionsAppConfig(AppConfig):
    """Registers the support sessions app with Django."""

    name = "sessions_app"
    verbose_name = "Support sessions"
