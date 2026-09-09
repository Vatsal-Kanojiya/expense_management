import os

from celery import Celery

# Must be set before the app is created: the worker is a separate process
# that never runs manage.py, so nothing else configures Django for it.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("expense_tracker")

# namespace="CELERY" means every Celery option is read from a Django setting
# prefixed CELERY_, so CELERY_BROKER_URL configures broker_url. One settings
# file, no second config format.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Imports tasks.py from every app in INSTALLED_APPS. Without this the worker
# starts fine and then reports "unregistered task" at call time — the tasks
# have to be imported by the worker process, not just the web process.
app.autodiscover_tasks()


@app.task
def debug_task():
    """Smoke test that the worker is alive and can reach the broker.

    Deliberately returns a value: with ignore_result=True the result is
    never stored, so .get() blocks and the state reads PENDING forever even
    though the task ran fine. That is a confusing thing to hand someone as
    their first check.
    """
    return "pong from worker"  # pragma: no cover - exercised by a live worker, not the suite
