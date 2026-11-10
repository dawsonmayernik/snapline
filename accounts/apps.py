"""Django application configuration for support staff accounts."""

from django.apps import AppConfig


class AccountsConfig(AppConfig):
    """Registers the accounts app with Django."""

    name = "accounts"
    verbose_name = "Accounts"
