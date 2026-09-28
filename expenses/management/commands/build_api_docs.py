"""Regenerate the frontend pack's generated files from a real run of the API.

    python manage.py build_api_docs            # or: make api-docs

Writes, under docs/frontend/:

* ``postman/expense-tracker.postman_collection.json`` and two environments
* ``API_REFERENCE.md``
* ``openapi.yaml``
* ``postman/sample-bill.png``, the image the collection uploads

The journey runs against a **throwaway test database**, created and dropped
here exactly as the test runner does, so the real data is never touched and
the examples are the same on every machine. DECISIONS D48.
"""

import json
import logging
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import BaseCommand, call_command
from django.test.utils import get_runner, override_settings
from django.utils import timezone

from expenses.api import journey

JOURNEY_SETTINGS = {
    # Tasks inline, so an export or a scan is finished by the next request.
    "CELERY_TASK_ALWAYS_EAGER": True,
    "CELERY_TASK_EAGER_PROPAGATES": True,
    # Mailed links point at the frontend, where the documented routes are.
    "FRONTEND_URL": journey.FRONTEND,
    "BILL_SCAN_PROVIDER": "fake",
    # No throttling or rate limiting while the journey runs.
    "CACHES": {"default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}},
}


def run_journey():
    """Create the journey's account and drive every step. Needs a database."""
    user = get_user_model().objects.create_user(**journey.MAIN_USER)
    with override_settings(**JOURNEY_SETTINGS):
        return journey.Journey(user).run()


def write_openapi(path):
    call_command("spectacular", "--validate", "--fail-on-warn", "--file", str(path))


class Command(BaseCommand):
    help = "Regenerate docs/frontend's Postman collection, API reference and OpenAPI schema."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            default=str(Path(settings.BASE_DIR) / "docs" / "frontend"),
            help="Where to write the files (default: docs/frontend).",
        )

    def handle(self, *args, **options):
        output = Path(options["output"])
        (output / "postman").mkdir(parents=True, exist_ok=True)

        # The test runner's own set-up: a throwaway database, locmem email,
        # fast password hashing, and a temporary media directory.
        runner = get_runner(settings)(verbosity=0, interactive=False)
        runner.setup_test_environment()
        databases = runner.setup_databases()
        # The error examples are deliberate 4xx answers; their warnings, and
        # every inline task's log line, would bury the one line that matters.
        logging.disable(logging.WARNING)
        try:
            records = run_journey()
        finally:
            logging.disable(logging.NOTSET)
            runner.teardown_databases(databases)
            runner.teardown_test_environment()

        def write_json(name, data):
            (output / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")

        write_json(
            "postman/expense-tracker.postman_collection.json", journey.postman_collection(records)
        )
        write_json(
            "postman/local.postman_environment.json",
            journey.postman_environment("local", journey.DOC_BASE),
        )
        write_json(
            "postman/hosted.postman_environment.json",
            journey.postman_environment("hosted", "https://your-domain.example/api/v1"),
        )
        (output / "postman" / "sample-bill.png").write_bytes(journey.sample_bill_png())
        (output / "API_REFERENCE.md").write_text(
            journey.reference_markdown(records, timezone.localdate())
        )
        write_openapi(output / "openapi.yaml")

        examples = sum(len(record["examples"]) for record in records)
        self.stdout.write(
            self.style.SUCCESS(
                f"Recorded {len(records)} requests and {examples} examples into {output}"
            )
        )
