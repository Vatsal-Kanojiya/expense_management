"""Security pass 3 (docs/HANDOVER.md): each account sees and changes only
its own records.

Four items, checked one by one, in the order HANDOVER.md lists them:
reading (list/detail/download, web and API), linking (an id in a body or
form must belong to the same account), changing and deleting (update,
partial update, delete -- web and API), and staff-only access (the admin
site and the API never show one account another's data).

`test_permissions.py` already covers the core expense/category boundary in
detail; this file rounds out the picture across every resource -- people,
exports, scans, splits, settlements, item shares -- and both surfaces.
"""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from expenses.models import (
    BillScan,
    Category,
    Expense,
    ExpenseItem,
    ExportJob,
    Participant,
    Settlement,
)

User = get_user_model()
PASSWORD = "Str0ng-Enough-Pass"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def api(name, *args):
    return reverse(f"api:v1:{name}", args=args)


class TwoAccountsTestCase(TestCase):
    """Alice and Bob, each with one of everything."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", "alice@example.com", PASSWORD)
        cls.bob = User.objects.create_user("bob", "bob@example.com", PASSWORD)

        cls.alice_category = Category.objects.create(user=cls.alice, name="Food")
        cls.bob_category = Category.objects.create(user=cls.bob, name="Rent")

        cls.alice_person = Participant.objects.create(user=cls.alice, name="Rahul")
        cls.bob_person = Participant.objects.create(user=cls.bob, name="Stranger")

        cls.alice_expense = Expense.objects.create(
            user=cls.alice,
            category=cls.alice_category,
            amount=Decimal("50.00"),
            spent_on=date(2026, 9, 1),
            note="Alice lunch",
        )
        cls.bob_expense = Expense.objects.create(
            user=cls.bob,
            category=cls.bob_category,
            amount=Decimal("900.00"),
            spent_on=date(2026, 9, 1),
            note="Bob rent",
        )
        cls.alice_item = ExpenseItem.objects.create(
            expense=cls.alice_expense, name="Line", amount=Decimal("50.00")
        )

        cls.alice_export = ExportJob.objects.create(
            user=cls.alice, start=date(2026, 9, 1), end=date(2026, 9, 30)
        )
        cls.bob_export = ExportJob.objects.create(
            user=cls.bob, start=date(2026, 9, 1), end=date(2026, 9, 30)
        )

        cls.alice_scan = BillScan.objects.create(
            user=cls.alice,
            image=SimpleUploadedFile("a.png", PNG, content_type="image/png"),
            status=BillScan.Status.DONE,
        )
        cls.bob_scan = BillScan.objects.create(
            user=cls.bob,
            image=SimpleUploadedFile("b.png", PNG, content_type="image/png"),
            status=BillScan.Status.DONE,
        )

        cls.bob_settlement = Settlement.objects.create(
            user=cls.bob, participant=cls.bob_person, amount=Decimal("10.00")
        )

    def setUp(self):
        self.client.force_login(self.alice)


# --- 1. Reading: every list, detail and download is scoped -----------------


class ReadingBoundaryTests(TwoAccountsTestCase):
    def test_web_lists_never_show_the_other_account(self):
        pages = [
            ("expenses:expense_list", "Alice lunch", "Bob rent"),
            ("expenses:category_list", "Food", "Rent"),
            ("expenses:export_list", None, None),
            ("expenses:bill_list", None, None),
        ]
        for name, mine, theirs in pages:
            with self.subTest(view=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                if mine:
                    self.assertContains(response, mine)
                    self.assertNotContains(response, theirs)

    def test_web_detail_and_download_routes_are_404_for_the_other_account(self):
        routes = [
            ("expenses:expense_update", self.bob_expense.pk),
            ("expenses:expense_delete", self.bob_expense.pk),
            ("expenses:category_update", self.bob_category.pk),
            ("expenses:category_delete", self.bob_category.pk),
            ("expenses:participant_update", self.bob_person.pk),
            ("expenses:participant_delete", self.bob_person.pk),
            ("expenses:export_download", self.bob_export.pk),
            ("expenses:bill_review", self.bob_scan.pk),
        ]
        for name, pk in routes:
            with self.subTest(view=name):
                self.assertEqual(self.client.get(reverse(name, args=[pk])).status_code, 404)

    def test_api_lists_are_scoped(self):
        endpoints = [
            (api("expense-list"), "id", [self.alice_expense.pk], [self.bob_expense.pk]),
            (api("category-list"), "id", [self.alice_category.pk], [self.bob_category.pk]),
            (api("participant-list"), "id", [self.alice_person.pk], [self.bob_person.pk]),
            (api("export-list"), "id", [self.alice_export.pk], [self.bob_export.pk]),
            (api("bill-scan-list"), "id", [self.alice_scan.pk], [self.bob_scan.pk]),
            (api("settlement-list"), "id", [], [self.bob_settlement.pk]),
        ]
        for url, key, mine, theirs in endpoints:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                data = response.json()
                results = data["results"] if isinstance(data, dict) and "results" in data else data
                ids = {row[key] for row in results}
                for pk in mine:
                    self.assertIn(pk, ids)
                for pk in theirs:
                    self.assertNotIn(pk, ids)

    def test_api_detail_routes_are_404_for_the_other_account(self):
        routes = [
            api("expense-detail", self.bob_expense.pk),
            api("category-detail", self.bob_category.pk),
            api("participant-detail", self.bob_person.pk),
            api("export-detail", self.bob_export.pk),
            api("bill-scan-detail", self.bob_scan.pk),
            api("settlement-detail", self.bob_settlement.pk),
            api("expense-split", self.bob_expense.pk),
            api("export-download", self.bob_export.pk),
            api("bill-scan-image", self.bob_scan.pk),
            api("bill-scan-prefill", self.bob_scan.pk),
        ]
        for url in routes:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)

    def test_settling_up_with_someone_elses_person_is_a_404_on_both_surfaces(self):
        web = self.client.post(reverse("expenses:settle_up", args=[self.bob_person.pk]))
        self.assertEqual(web.status_code, 404)

        api_response = self.client.post(
            api("settle-up", self.bob_person.pk), {}, content_type="application/json"
        )
        self.assertEqual(api_response.status_code, 404)
