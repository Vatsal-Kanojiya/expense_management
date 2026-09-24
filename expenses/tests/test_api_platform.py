"""Phase 20 platform: bearer tokens, CORS, the schema, 409s and health."""

import tempfile
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework_simplejwt.tokens import RefreshToken

from expenses.models import Category, Expense, ExpenseItem, ItemShare, Participant

User = get_user_model()


class PlatformTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", "alice@example.com", "pw-Alice-123")
        cls.food = Category.objects.create(user=cls.alice, name="Food")
        cls.rahul = Participant.objects.create(user=cls.alice, name="Rahul")

    def bearer(self, user=None):
        token = RefreshToken.for_user(user or self.alice).access_token
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


class BearerTokenTests(PlatformTestCase):
    def test_an_access_token_authenticates_without_a_session(self):
        response = self.client.get(reverse("api:v1:category-list"), **self.bearer())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"][0]["name"], "Food")

    def test_a_malformed_token_is_a_401_not_anonymous_access(self):
        response = self.client.get(
            reverse("api:v1:category-list"), HTTP_AUTHORIZATION="Bearer not-a-token"
        )

        self.assertEqual(response.status_code, 401)

    def test_a_token_request_needs_no_csrf_token(self):
        # Cross-origin clients cannot read the CSRF cookie, and do not need
        # to: a bearer token is not sent automatically by the browser, which
        # is the whole attack CSRF defends against.
        client = self.client_class(enforce_csrf_checks=True)
        response = client.post(
            reverse("api:v1:category-list"),
            {"name": "Travel"},
            content_type="application/json",
            **self.bearer(),
        )

        self.assertEqual(response.status_code, 201)


@override_settings(CORS_ALLOWED_ORIGINS=["http://localhost:5173"])
class CorsTests(PlatformTestCase):
    def preflight(self, origin, path=None):
        return self.client.options(
            path or reverse("api:v1:category-list"),
            HTTP_ORIGIN=origin,
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS="authorization,content-type",
        )

    def test_an_allowed_origin_passes_the_preflight(self):
        response = self.preflight("http://localhost:5173")

        self.assertEqual(response["Access-Control-Allow-Origin"], "http://localhost:5173")
        self.assertIn("authorization", response["Access-Control-Allow-Headers"])

    def test_any_other_origin_is_refused(self):
        response = self.preflight("https://evil.example")

        self.assertNotIn("Access-Control-Allow-Origin", response)

    def test_cookies_are_not_allowed_cross_origin(self):
        response = self.preflight("http://localhost:5173")

        self.assertNotIn("Access-Control-Allow-Credentials", response)

    def test_only_the_api_is_opened(self):
        response = self.preflight("http://localhost:5173", path="/accounts/login/")

        self.assertNotIn("Access-Control-Allow-Origin", response)


class ProtectedDeleteTests(PlatformTestCase):
    """Issue 44: a delete the database refuses was a 500 through the API."""

    def setUp(self):
        self.client.force_login(self.alice)

    def test_a_category_with_expenses_is_a_409_with_a_reason(self):
        Expense.objects.create(
            user=self.alice, category=self.food, amount=Decimal("10"), spent_on=date(2026, 1, 1)
        )

        response = self.client.delete(reverse("api:v1:category-detail", args=[self.food.pk]))

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "protected")
        self.assertEqual(response.json()["blocking"], {"expenses": 1})
        self.assertTrue(Category.objects.filter(pk=self.food.pk).exists())

    def test_a_person_on_a_line_item_is_a_409(self):
        expense = Expense.objects.create(
            user=self.alice, category=self.food, amount=Decimal("10"), spent_on=date(2026, 1, 1)
        )
        item = ExpenseItem.objects.create(expense=expense, name="Tea", amount=Decimal("10"))
        ItemShare.objects.create(item=item, participant=self.rahul)

        response = self.client.delete(reverse("api:v1:participant-detail", args=[self.rahul.pk]))

        self.assertEqual(response.status_code, 409)
        self.assertIn("item shares", response.json()["detail"])

    def test_an_unused_category_still_deletes(self):
        response = self.client.delete(reverse("api:v1:category-detail", args=[self.food.pk]))

        self.assertEqual(response.status_code, 204)


class HealthTests(TestCase):
    def test_health_needs_no_login(self):
        response = self.client.get(reverse("api:v1:health"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})


class SchemaTests(TestCase):
    def test_the_schema_generates_without_a_single_warning(self):
        # The contract a frontend developer builds against is generated from
        # the code (D43). A warning means an endpoint the generator had to
        # guess about -- a guess that would land in the Postman collection.
        with tempfile.NamedTemporaryFile(suffix=".yaml") as schema:
            call_command("spectacular", "--fail-on-warn", "--validate", "--file", schema.name)
            self.assertIn(b"/api/v1/expenses/", schema.read())

    def test_swagger_ui_is_served(self):
        response = self.client.get(reverse("api:v1:docs"))

        self.assertEqual(response.status_code, 200)
