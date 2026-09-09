"""Guards against template mistakes that render as visible text.

These are the failures no unit test catches, because the view returns 200
and the context is correct — the damage is only in the bytes sent to the
browser.
"""

import pathlib
import re
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from expenses.models import Category, Expense

User = get_user_model()

TEMPLATE_DIR = pathlib.Path(settings.BASE_DIR) / "templates"


class TemplateCommentSyntaxTests(TestCase):
    def test_no_multiline_hash_comments(self):
        """Django's {# #} only strips comments that fit on ONE line.

        A multi-line one is not a comment at all — it renders as literal
        text in the page. Eleven of these shipped before anyone rendered a
        page and read it. {% comment %} handles any length.
        """
        offenders = []

        for path in sorted(TEMPLATE_DIR.rglob("*.html")):
            source = path.read_text()
            for match in re.finditer(r"\{#", source):
                close = source.find("#}", match.start())
                if close != -1 and "\n" in source[match.start() : close]:
                    line = source[: match.start()].count("\n") + 1
                    offenders.append(f"{path.relative_to(TEMPLATE_DIR)}:{line}")

        self.assertEqual(
            offenders,
            [],
            "Multi-line {# #} comments render as visible text; use {% comment %}.",
        )


class RenderedOutputTests(TestCase):
    """Fetch every page and assert nothing template-shaped reaches the browser."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("alice", email="alice@example.com", password="pw12345!")
        cls.category = Category.objects.create(user=cls.user, name="Food")
        cls.expense = Expense.objects.create(
            user=cls.user,
            category=cls.category,
            amount=Decimal("10.00"),
            spent_on=date(2026, 9, 1),
        )

    def setUp(self):
        self.client.force_login(self.user)

    def _pages(self):
        return [
            reverse("expenses:dashboard"),
            reverse("expenses:expense_list"),
            reverse("expenses:expense_create"),
            reverse("expenses:expense_update", args=[self.expense.pk]),
            reverse("expenses:expense_delete", args=[self.expense.pk]),
            reverse("expenses:category_list"),
            reverse("expenses:category_create"),
            reverse("expenses:category_update", args=[self.category.pk]),
            reverse("expenses:category_delete", args=[self.category.pk]),
            reverse("accounts:password_change"),
        ]

    def test_no_template_syntax_leaks_into_any_page(self):
        for url in self._pages():
            with self.subTest(url=url):
                body = self.client.get(url).content.decode()

                # Comment markers, unrendered tags and unresolved variables.
                for marker in ("{#", "#}", "{%", "%}", "{{", "}}"):
                    self.assertNotIn(marker, body, f"{marker} reached the browser on {url}")

    def test_every_page_returns_200(self):
        for url in self._pages():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_anonymous_pages_are_clean_too(self):
        self.client.logout()

        for url in [reverse("accounts:login"), reverse("accounts:signup")]:
            with self.subTest(url=url):
                body = self.client.get(url).content.decode()

                self.assertEqual(self.client.get(url).status_code, 200)
                for marker in ("{#", "{%", "{{"):
                    self.assertNotIn(marker, body)
