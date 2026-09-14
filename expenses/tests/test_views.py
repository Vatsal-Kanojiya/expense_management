"""View-level tests: the request/response cycle for the happy paths.

Cross-user access is deliberately NOT covered here — it lives in
test_permissions.py, so the security boundary is one file you can read
end to end rather than assertions scattered through CRUD tests.
"""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from expenses.models import Category, Expense, ExpenseItem, Participant
from expenses.tests.helpers import item_formset

User = get_user_model()

ALL_URLS = [
    ("expenses:expense_list", ()),
    ("expenses:expense_create", ()),
    ("expenses:expense_update", (1,)),
    ("expenses:expense_delete", (1,)),
    ("expenses:category_list", ()),
    ("expenses:category_create", ()),
    ("expenses:category_update", (1,)),
    ("expenses:category_delete", (1,)),
]


class AuthenticationRequiredTests(TestCase):
    def test_every_view_redirects_anonymous_users(self):
        # subTest reports which URL failed instead of stopping at the first.
        login_url = reverse("accounts:login")

        for name, args in ALL_URLS:
            with self.subTest(url=name):
                target = reverse(name, args=args)

                response = self.client.get(target)

                self.assertEqual(response.status_code, 302)
                # Asserting the whole URL also pins that ?next= round-trips,
                # which is what returns the user to the page they wanted
                # instead of dumping them on the dashboard after login.
                self.assertEqual(response.url, f"{login_url}?next={target}")


class CategoryViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            "alice", email="alice@example.com", password="pw12345!"
        )

    def setUp(self):
        self.client.force_login(self.alice)

    def test_list_renders_with_expected_template(self):
        Category.objects.create(user=self.alice, name="Food")

        response = self.client.get(reverse("expenses:category_list"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "expenses/category_list.html")
        self.assertContains(response, "Food")

    def test_list_annotates_expense_counts(self):
        category = Category.objects.create(user=self.alice, name="Food")
        Expense.objects.create(
            user=self.alice, category=category, amount=5, spent_on=date(2026, 9, 1)
        )

        response = self.client.get(reverse("expenses:category_list"))

        self.assertEqual(response.context["categories"][0].expense_count, 1)

    def test_empty_state_is_shown(self):
        response = self.client.get(reverse("expenses:category_list"))

        self.assertContains(response, "No categories yet")

    def test_create_assigns_the_logged_in_user(self):
        response = self.client.post(reverse("expenses:category_create"), {"name": "Travel"})

        self.assertRedirects(response, reverse("expenses:category_list"))
        self.assertEqual(Category.objects.get(name="Travel").user, self.alice)

    def test_create_rejects_duplicate_without_a_500(self):
        Category.objects.create(user=self.alice, name="Food")

        response = self.client.post(reverse("expenses:category_create"), {"name": "Food"})

        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"], "name", ["You already have a category with this name."]
        )

    def test_update_renames(self):
        category = Category.objects.create(user=self.alice, name="Food")

        self.client.post(
            reverse("expenses:category_update", args=[category.pk]),
            {"name": "Groceries"},
        )

        category.refresh_from_db()
        self.assertEqual(category.name, "Groceries")

    def test_delete_removes_an_unused_category(self):
        category = Category.objects.create(user=self.alice, name="Unused")

        self.client.post(reverse("expenses:category_delete", args=[category.pk]))

        self.assertFalse(Category.objects.filter(pk=category.pk).exists())

    def test_delete_is_refused_while_expenses_exist(self):
        category = Category.objects.create(user=self.alice, name="Food")
        Expense.objects.create(
            user=self.alice, category=category, amount=5, spent_on=date(2026, 9, 1)
        )

        response = self.client.post(
            reverse("expenses:category_delete", args=[category.pk]), follow=True
        )

        # ProtectedError must surface as a message, not a 500.
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Category.objects.filter(pk=category.pk).exists())
        self.assertContains(response, "cannot be deleted")

    def test_delete_requires_post(self):
        category = Category.objects.create(user=self.alice, name="Unused")

        self.client.get(reverse("expenses:category_delete", args=[category.pk]))

        # A GET renders the confirmation page and must not delete anything.
        self.assertTrue(Category.objects.filter(pk=category.pk).exists())


class ExpenseViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            "alice", email="alice@example.com", password="pw12345!"
        )
        cls.category = Category.objects.create(user=cls.alice, name="Food")

    def setUp(self):
        self.client.force_login(self.alice)

    def _create(self, **overrides):
        defaults = {
            "user": self.alice,
            "category": self.category,
            "amount": Decimal("10.00"),
            "spent_on": date(2026, 9, 1),
        }
        return Expense.objects.create(**{**defaults, **overrides})

    def test_list_renders(self):
        self._create(note="Lunch")

        response = self.client.get(reverse("expenses:expense_list"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "expenses/expense_list.html")
        self.assertContains(response, "Lunch")

    def test_empty_state_is_shown(self):
        response = self.client.get(reverse("expenses:expense_list"))

        self.assertContains(response, "No expenses in this date range")

    def test_create_assigns_the_logged_in_user(self):
        response = self.client.post(
            reverse("expenses:expense_create"),
            {
                "category": self.category.pk,
                "amount": "25.00",
                "spent_on": "2026-09-05",
                "note": "Dinner",
                **item_formset(),
            },
        )

        self.assertRedirects(response, reverse("expenses:expense_list"))
        self.assertEqual(Expense.objects.get(note="Dinner").user, self.alice)

    def test_update_changes_amount(self):
        expense = self._create()

        self.client.post(
            reverse("expenses:expense_update", args=[expense.pk]),
            {
                "category": self.category.pk,
                "amount": "99.00",
                "spent_on": "2026-09-01",
                "note": "Dinner",
                **item_formset(),
            },
        )

        expense.refresh_from_db()
        self.assertEqual(expense.amount, Decimal("99.00"))

    def test_delete_removes_the_expense(self):
        expense = self._create()

        self.client.post(reverse("expenses:expense_delete", args=[expense.pk]))

        self.assertFalse(Expense.objects.filter(pk=expense.pk).exists())

    def test_list_is_paginated_at_25(self):
        for _ in range(26):
            self._create()

        response = self.client.get(reverse("expenses:expense_list"))

        self.assertTrue(response.context["is_paginated"])
        self.assertEqual(len(response.context["expenses"]), 25)

    def test_list_does_not_issue_a_query_per_row(self):
        for _ in range(10):
            self._create()

        # Eight queries: session, user, pagination count, the rows
        # themselves, the filtered total, the category dropdown's options,
        # and one each for the participants and items prefetches. The number
        # grew from four when filtering was added and from six when splitting
        # did; every addition is accounted for above.
        #
        # Note these expenses have no items, so the nested shares prefetch is
        # skipped -- Django does not run a prefetch whose parent set is
        # empty. test_orm.py pins the itemised case, where it does run.
        #
        # What matters is that it is FLAT: select_related and prefetch_related
        # mean it does not grow with the number of rows.
        # test_query_count_is_flat_as_rows_grow asserts that property.
        with self.assertNumQueries(8):
            self.client.get(reverse("expenses:expense_list"))

    def test_query_count_is_flat_as_rows_grow(self):
        for _ in range(3):
            self._create()
        with self.assertNumQueries(8):
            self.client.get(reverse("expenses:expense_list"))

        for _ in range(20):
            self._create()

        # Same count with 23 rows as with 3. This is the N+1 guarantee
        # stated as a property rather than a magic number.
        with self.assertNumQueries(8):
            self.client.get(reverse("expenses:expense_list"))

    def test_the_split_tab_appears_for_a_balanced_shared_expense(self):
        bob = Participant.objects.create(user=self.alice, name="Bob")
        expense = self._create(amount=Decimal("100.00"))
        expense.participants.set([Participant.get_or_create_self(self.alice), bob])
        item = ExpenseItem.objects.create(expense=expense, name="Dinner", amount=Decimal("100.00"))
        item.shares.create(participant=bob, weight=Decimal("1"))

        response = self.client.get(reverse("expenses:expense_update", args=[expense.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.context["split"], list)
        self.assertContains(response, 'id="panel-split"')
        self.assertContains(response, 'id="tab-split"')

    def test_the_split_tab_is_absent_when_unbalanced(self):
        bob = Participant.objects.create(user=self.alice, name="Bob")
        expense = self._create(amount=Decimal("100.00"))
        expense.participants.set([Participant.get_or_create_self(self.alice), bob])
        item = ExpenseItem.objects.create(expense=expense, name="Starter", amount=Decimal("30.00"))
        item.shares.create(participant=bob, weight=Decimal("1"))

        response = self.client.get(reverse("expenses:expense_update", args=[expense.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["split"])
        self.assertNotContains(response, 'id="panel-split"')
        self.assertNotContains(response, 'id="tab-split"')

    def test_the_split_tab_is_absent_for_an_expense_that_is_yours_alone(self):
        expense = self._create(amount=Decimal("50.00"))
        self_p = Participant.get_or_create_self(self.alice)
        expense.participants.set([self_p])
        ExpenseItem.objects.create(expense=expense, name="Coffee", amount=Decimal("50.00"))

        response = self.client.get(reverse("expenses:expense_update", args=[expense.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["split"])
        self.assertNotContains(response, 'id="panel-split"')
        self.assertNotContains(response, 'id="tab-split"')

    def test_the_split_tab_is_absent_on_the_create_page(self):
        response = self.client.get(reverse("expenses:expense_create"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="panel-split"')
        self.assertNotContains(response, 'id="tab-split"')

    def test_a_rejected_edit_shows_the_saved_split(self):
        bob = Participant.objects.create(user=self.alice, name="Bob")
        expense = self._create(amount=Decimal("100.00"))
        expense.participants.set([Participant.get_or_create_self(self.alice), bob])
        item = ExpenseItem.objects.create(expense=expense, name="Dinner", amount=Decimal("100.00"))
        item.shares.create(participant=bob, weight=Decimal("1"))

        response = self.client.post(
            reverse("expenses:expense_update", args=[expense.pk]),
            {
                "category": self.category.pk,
                "amount": "",
                "spent_on": "2026-09-01",
                "note": "Dinner",
                **item_formset(),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.context["split"])
        self.assertContains(response, 'id="panel-split"')
        self.assertContains(response, "₹100.00")

    def test_the_split_tab_is_scoped_to_the_owner(self):
        bob_user = User.objects.create_user(
            "bob_user", email="bob_user@example.com", password="pw!"
        )
        bob = Participant.objects.create(user=self.alice, name="Bob")
        expense = self._create(amount=Decimal("100.00"))
        expense.participants.set([Participant.get_or_create_self(self.alice), bob])

        self.client.force_login(bob_user)
        response = self.client.get(reverse("expenses:expense_update", args=[expense.pk]))

        self.assertEqual(response.status_code, 404)

    def test_the_edit_page_query_count_does_not_grow_with_items(self):
        bob = Participant.objects.create(user=self.alice, name="Bob")
        self_p = Participant.get_or_create_self(self.alice)

        exp1 = self._create(amount=Decimal("20.00"))
        exp1.participants.set([self_p, bob])
        item1 = ExpenseItem.objects.create(expense=exp1, name="Item 1", amount=Decimal("20.00"))
        item1.shares.create(participant=bob, weight=Decimal("1"))

        exp5 = self._create(amount=Decimal("50.00"))
        exp5.participants.set([self_p, bob])
        for i in range(5):
            it = ExpenseItem.objects.create(expense=exp5, name=f"Item {i}", amount=Decimal("10.00"))
            it.shares.create(participant=bob, weight=Decimal("1"))

        with CaptureQueriesContext(connection) as ctx1:
            self.client.get(reverse("expenses:expense_update", args=[exp1.pk]))

        with CaptureQueriesContext(connection) as ctx5:
            self.client.get(reverse("expenses:expense_update", args=[exp5.pk]))

        self.assertEqual(len(ctx1), len(ctx5))
