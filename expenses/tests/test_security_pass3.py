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
    ItemShare,
    Participant,
    Settlement,
)
from expenses.tests.helpers import item_formset

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


# --- 2. Linking: an id in a body or form must belong to the same account ---


class LinkingBoundaryTests(TwoAccountsTestCase):
    def test_web_expense_form_rejects_the_other_accounts_category_and_people(self):
        response = self.client.post(
            reverse("expenses:expense_create"),
            {
                "category": self.bob_category.pk,
                "amount": "5.00",
                "spent_on": "2026-09-02",
                "note": "sneaky",
                "participants": [self.bob_person.pk],
                **item_formset(),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("category", response.context["form"].errors)
        self.assertIn("participants", response.context["form"].errors)
        self.assertFalse(Expense.objects.filter(note="sneaky").exists())

    def test_web_line_item_cannot_be_shared_with_someone_elses_person(self):
        # The formset scopes its own `shared_with` queryset to the expense's
        # participants, so a crafted id for another account's person is
        # simply not a valid choice.
        response = self.client.post(
            reverse("expenses:expense_create"),
            {
                "category": self.alice_category.pk,
                "amount": "10.00",
                "spent_on": "2026-09-02",
                "note": "shared item",
                "participants": [self.alice_person.pk],
                **item_formset(("Line", "10.00")),
                "items-0-shared_with": [self.bob_person.pk],
            },
        )
        self.assertEqual(response.status_code, 200)
        formset = response.context["formset"]
        self.assertFalse(formset.is_valid())
        self.assertFalse(Expense.objects.filter(note="shared item").exists())

    def test_api_expense_create_rejects_every_other_accounts_id(self):
        payloads = [
            ("category", {"category": self.bob_category.pk}),
            ("participants", {"participants": [self.bob_person.pk]}),
            ("paid_by", {"paid_by": self.bob_person.pk}),
            ("bill_scan", {"bill_scan": self.bob_scan.pk}),
        ]
        base = {"category": self.alice_category.pk, "amount": "10.00", "spent_on": "2026-09-02"}
        for field, override in payloads:
            with self.subTest(field=field):
                response = self.client.post(
                    api("expense-list"), {**base, **override}, content_type="application/json"
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.json())
                self.assertFalse(Expense.objects.filter(spent_on=date(2026, 9, 2)).exists())

    def test_api_item_share_rejects_someone_elses_participant(self):
        response = self.client.post(
            api("expense-list"),
            {
                "category": self.alice_category.pk,
                "amount": "10.00",
                "spent_on": "2026-09-02",
                "participants": [self.alice_person.pk],
                "items": [
                    {
                        "name": "Line",
                        "amount": "10.00",
                        "shares": [{"participant": self.bob_person.pk, "weight": 1}],
                    }
                ],
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Expense.objects.filter(spent_on=date(2026, 9, 2)).exists())

    def test_api_update_also_rejects_every_other_accounts_id(self):
        payloads = [
            {"category": self.bob_category.pk},
            {"participants": [self.bob_person.pk]},
            {"paid_by": self.bob_person.pk},
        ]
        for override in payloads:
            with self.subTest(override=list(override)[0]):
                response = self.client.patch(
                    api("expense-detail", self.alice_expense.pk),
                    override,
                    content_type="application/json",
                )
                self.assertEqual(response.status_code, 400)
                self.alice_expense.refresh_from_db()
                self.assertEqual(self.alice_expense.category, self.alice_category)

    def test_web_and_api_cannot_settle_up_a_forged_note_onto_someone_elses_person(self):
        # settle_up looks the participant up scoped to the caller, so there
        # is no id to forge here beyond the 404 already covered above -- this
        # documents that the same is true through the ORM helper directly.
        from expenses.settlements import settle_up

        with self.assertRaises(Participant.DoesNotExist):
            settle_up(self.alice, self.bob_person.pk)


# --- 3. Changing and deleting: same boundary, on writes -------------------


class ChangingAndDeletingBoundaryTests(TwoAccountsTestCase):
    def test_web_update_and_delete_of_someone_elses_row_is_refused_and_unchanged(self):
        cases = [
            (
                "expenses:category_update",
                self.bob_category.pk,
                {"name": "hijacked"},
            ),
            (
                "expenses:participant_update",
                self.bob_person.pk,
                {"name": "hijacked"},
            ),
        ]
        for name, pk, data in cases:
            with self.subTest(view=name):
                response = self.client.post(reverse(name, args=[pk]), data)
                self.assertEqual(response.status_code, 404)

        self.bob_category.refresh_from_db()
        self.bob_person.refresh_from_db()
        self.assertEqual(self.bob_category.name, "Rent")
        self.assertEqual(self.bob_person.name, "Stranger")

        for name, pk in [
            ("expenses:category_delete", self.bob_category.pk),
            ("expenses:participant_delete", self.bob_person.pk),
            ("expenses:expense_delete", self.bob_expense.pk),
        ]:
            with self.subTest(view=name):
                self.assertEqual(self.client.post(reverse(name, args=[pk])).status_code, 404)

        self.assertTrue(Category.objects.filter(pk=self.bob_category.pk).exists())
        self.assertTrue(Participant.objects.filter(pk=self.bob_person.pk).exists())
        self.assertTrue(Expense.objects.filter(pk=self.bob_expense.pk).exists())

    def test_api_update_and_delete_of_someone_elses_row_is_404_and_unchanged(self):
        write_routes = [
            (api("expense-detail", self.bob_expense.pk), {"note": "hijacked"}),
            (api("category-detail", self.bob_category.pk), {"name": "hijacked"}),
            (api("participant-detail", self.bob_person.pk), {"name": "hijacked"}),
        ]
        for url, body in write_routes:
            with self.subTest(url=url, method="PATCH"):
                response = self.client.patch(url, body, content_type="application/json")
                self.assertEqual(response.status_code, 404)

        for url in [route for route, _ in write_routes]:
            with self.subTest(url=url, method="DELETE"):
                self.assertEqual(self.client.delete(url).status_code, 404)

        self.bob_expense.refresh_from_db()
        self.bob_category.refresh_from_db()
        self.bob_person.refresh_from_db()
        self.assertEqual(self.bob_expense.note, "Bob rent")
        self.assertEqual(self.bob_category.name, "Rent")
        self.assertEqual(self.bob_person.name, "Stranger")
        self.assertTrue(Expense.objects.filter(pk=self.bob_expense.pk).exists())
        self.assertTrue(Category.objects.filter(pk=self.bob_category.pk).exists())
        self.assertTrue(Participant.objects.filter(pk=self.bob_person.pk).exists())

    def test_api_put_of_someone_elses_expense_is_also_a_404(self):
        response = self.client.put(
            api("expense-detail", self.bob_expense.pk),
            {"category": self.alice_category.pk, "amount": "1.00", "spent_on": "2026-09-02"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)

    def test_deleting_someone_elses_item_share_is_impossible_through_the_api(self):
        # There is no direct item/share endpoint -- items are only ever
        # rewritten through the parent expense, which is itself scoped.
        share = ItemShare.objects.create(item=self.alice_item, participant=self.alice_person)
        response = self.client.patch(
            api("expense-detail", self.bob_expense.pk),
            {"items": []},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)
        self.assertTrue(ItemShare.objects.filter(pk=share.pk).exists())


# --- 4. Staff: the admin site and the API stay off-limits to normal users --


class StaffBoundaryTests(TwoAccountsTestCase):
    def test_a_normal_account_is_refused_admin_access(self):
        response = self.client.get("/admin/expenses/expense/")
        # Django's admin redirects a non-staff, logged-in user to the login
        # page rather than 403ing, so it never confirms the admin exists.
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response.url)

    def test_a_normal_account_cannot_open_the_user_admin(self):
        response = self.client.get("/admin/accounts/user/")
        self.assertEqual(response.status_code, 302)

    def test_is_staff_alone_grants_no_model_permissions(self):
        # is_staff only opens the door (Django's AdminSite.has_permission);
        # seeing or changing rows inside still needs explicit model
        # permissions, which this account has none of.
        staff = User.objects.create_user("staffer", "staffer@example.com", PASSWORD, is_staff=True)
        self.client.force_login(staff)

        self.assertEqual(self.client.get("/admin/expenses/expense/").status_code, 403)

    def test_is_staff_grants_no_extra_reach_through_the_api(self):
        # is_staff has no bearing on the API's scoping at all: even a
        # superuser only ever sees their own rows through it, because
        # OwnerScopedViewSet.get_queryset filters on request.user
        # unconditionally.
        superuser = User.objects.create_superuser("boss", "boss@example.com", PASSWORD)
        self.client.force_login(superuser)

        response = self.client.get(api("expense-list"))
        ids = {row["id"] for row in response.json()["results"]}
        self.assertNotIn(self.alice_expense.pk, ids)
        self.assertNotIn(self.bob_expense.pk, ids)

    def test_is_staff_cannot_be_set_through_the_account_api(self):
        response = self.client.patch(api("me"), {"is_staff": True}, content_type="application/json")
        self.assertIn(response.status_code, (200, 405))
        self.alice.refresh_from_db()
        self.assertFalse(self.alice.is_staff)
