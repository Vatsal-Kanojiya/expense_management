from django.apps import AppConfig


class ExpensesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "expenses"

    def ready(self):
        """Import the signal receivers.

        ready() rather than module level in models.py: importing signals
        from models would run at import time, before the app registry is
        populated, and the receivers import models themselves. Django calls
        ready() once every app is loaded, which is the only safe point.

        The import is for its side effect -- @receiver registers on import
        -- so the name is unused and noqa says so on purpose.
        """
        from . import signals  # noqa: F401
