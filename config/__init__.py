# Importing the Celery app here means it is configured as soon as Django
# starts, so shared_task decorators anywhere in the project bind to it.
# Without this, tasks defined with @shared_task have no app to attach to.
from .celery import app as celery_app

__all__ = ("celery_app",)
