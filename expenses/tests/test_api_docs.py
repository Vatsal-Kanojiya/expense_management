"""The frontend pack stays true to the code (phase 21, DECISIONS D48)."""

import json
import re
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.management import call_command
from django.test import SimpleTestCase, TransactionTestCase
from drf_spectacular.generators import SchemaGenerator

from expenses.api import journey
from expenses.management.commands.build_api_docs import run_journey, write_openapi

PACK = Path(settings.BASE_DIR) / "docs" / "frontend"
REGENERATE = "The frontend pack is stale: run `python manage.py build_api_docs`."


class OpenApiSnapshotTests(SimpleTestCase):
    def test_the_committed_schema_matches_the_code(self):
        with tempfile.TemporaryDirectory() as directory:
            fresh = Path(directory) / "openapi.yaml"
            write_openapi(fresh)
            self.assertEqual(fresh.read_text(), (PACK / "openapi.yaml").read_text(), REGENERATE)


class JourneyTests(TransactionTestCase):
    """The recorded journey: every step answers as documented, and nothing is left out.

    A TransactionTestCase, because an export or a scan dispatches its task on
    commit, and the next step polls for the result.
    """

    def test_every_endpoint_has_a_recorded_example(self):
        records = run_journey()  # raises JourneyError on any unexpected status

        recorded = set()
        for record in records:
            recorded.add((record["main"]["method"], journey.schema_path(record["step"].path)))
            for example in record["examples"]:
                path = example["url"][len(journey.API_PREFIX) :]
                recorded.add((example["method"], journey.schema_path(path)))

        schema = SchemaGenerator().get_schema(request=None, public=True)
        in_schema = {
            (method.upper(), journey.schema_path(path[len(journey.API_PREFIX) :]))
            for path, operations in schema["paths"].items()
            for method in operations
        }
        self.assertEqual(in_schema - recorded, set(), "Endpoints with no example in the journey")

    def test_the_command_writes_the_whole_pack(self):
        # The command's own throwaway database is replaced by this test's, so
        # this exercises everything else it does, renderers included.
        class SameDatabase:
            def __init__(self, **kwargs):
                pass

            def setup_test_environment(self):
                pass

            def setup_databases(self):
                return None

            def teardown_databases(self, old_config):
                pass

            def teardown_test_environment(self):
                pass

        with (
            tempfile.TemporaryDirectory() as directory,
            patch(
                "expenses.management.commands.build_api_docs.get_runner", return_value=SameDatabase
            ),
        ):
            call_command("build_api_docs", output=directory, stdout=open("/dev/null", "w"))
            out = Path(directory)

            collection = json.loads(
                (out / "postman" / "expense-tracker.postman_collection.json").read_text()
            )
            reference = (out / "API_REFERENCE.md").read_text()
            environment = json.loads(
                (out / "postman" / "local.postman_environment.json").read_text()
            )

            self.assertEqual(len(collection["item"]), 10)
            self.assertEqual(
                sum(len(folder["item"]) for folder in collection["item"]), len(journey.STEPS)
            )
            for step in journey.STEPS:
                self.assertIn(f"### {step.name}", reference)
            self.assertNotIn("testserver", reference)
            self.assertNotIn("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ", reference)  # no live token
            self.assertEqual(environment["values"][0]["value"], journey.DOC_BASE)
            self.assertTrue(
                (out / "postman" / "sample-bill.png").read_bytes().startswith(b"\x89PNG")
            )
            self.assertIn("/api/v1/expenses/", (out / "openapi.yaml").read_text())


class CollectionTests(SimpleTestCase):
    def setUp(self):
        self.collection = json.loads(
            (PACK / "postman" / "expense-tracker.postman_collection.json").read_text()
        )
        self.requests = [item for folder in self.collection["item"] for item in folder["item"]]

    def test_request_names_are_unique(self):
        # The polling requests repeat themselves by name.
        names = [item["name"] for item in self.requests]
        self.assertEqual(len(names), len(set(names)))

    def test_every_variable_a_request_uses_is_declared(self):
        declared = {variable["key"] for variable in self.collection["variable"]}
        declared |= {"username", "password"}  # from the environment
        used = set()
        for item in self.requests:
            text = json.dumps(item["request"])
            used |= set(re.findall(r"\{\{(\w+)\}\}", text))
        self.assertEqual(used - declared, set())

    def test_every_request_has_a_recorded_example(self):
        for item in self.requests:
            with self.subTest(item["name"]):
                self.assertTrue(item["response"], REGENERATE)
