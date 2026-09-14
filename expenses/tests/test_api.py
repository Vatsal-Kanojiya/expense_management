"""The API, and the boundary that is not where DRF's docs suggest.

The load-bearing assertion in this file is test_the_list_endpoint_is_scoped.
Object permissions never run on list, so a ViewSet that leans on
has_object_permission alone leaks the whole table from its collection
endpoint while correctly refusing each row one at a time.
"""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from expenses.models import Category, Expense, ExpenseItem, ItemShare, Participant

User = get_user_model()


class ApiTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            "alice", email="alice@example.com", password="pw12345!"
        )
        cls.bob = User.objects.create_user("bob", email="bob@example.com", password="pw12345!")

        cls.food = Category.objects.create(user=cls.alice, name="Food")
        cls.rahul = Participant.objects.create(user=cls.alice, name="Rahul")

        cls.their_category = Category.objects.create(user=cls.bob, name="Theirs")
        cls.their_participant = Participant.objects.create(user=cls.bob, name="Stranger")

        cls.mine = Expense.objects.create(
            user=cls.alice,
            category=cls.food,
            amount=Decimal("900.00"),
            spent_on=date(2026, 1, 15),
        )
        cls.theirs = Expense.objects.create(
            user=cls.bob,
            category=cls.their_category,
            amount=Decimal("100.00"),
            spent_on=date(2026, 1, 15),
        )

    def setUp(self):
        self.client.force_login(self.alice)

    @property
    def list_url(self):
        return reverse("api:v1:expense-list")

    def detail_url(self, pk):
        return reverse("api:v1:expense-detail", args=[pk])


class ScopingTests(ApiTestCase):
    def test_the_list_endpoint_is_scoped(self):
        """The one that matters.

        has_object_permission is never consulted here. If get_queryset did
        not filter, this endpoint would return Bob's expense with a 200.
        """
        response = self.client.get(self.list_url)

        ids = [row["id"] for row in response.json()["results"]]
        self.assertEqual(ids, [self.mine.pk])

    def test_another_users_expense_is_a_404_not_a_403(self):
        # 404, because the row is absent from the queryset before any
        # permission code runs. A 403 would confirm it exists.
        self.assertEqual(self.client.get(self.detail_url(self.theirs.pk)).status_code, 404)

    def test_another_users_expense_cannot_be_updated(self):
        response = self.client.patch(
            self.detail_url(self.theirs.pk),
            {"note": "hijacked"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 404)
        self.theirs.refresh_from_db()
        self.assertEqual(self.theirs.note, "")

    def test_a_crafted_category_id_is_rejected(self):
        # The ModelChoiceField lesson, with no dropdown to notice it in.
        response = self.client.post(
            self.list_url,
            {
                "category": self.their_category.pk,
                "amount": "10.00",
                "spent_on": "2026-01-15",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("category", response.json())

    def test_a_crafted_participant_id_is_rejected(self):
        response = self.client.post(
            self.list_url,
            {
                "category": self.food.pk,
                "amount": "10.00",
                "spent_on": "2026-01-15",
                "participants": [self.their_participant.pk],
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)

    def test_ownership_cannot_be_set_from_the_payload(self):
        self.client.post(
            self.list_url,
            {
                "category": self.food.pk,
                "amount": "10.00",
                "spent_on": "2026-01-15",
                "user": self.bob.pk,
            },
            content_type="application/json",
        )

        self.assertEqual(Expense.objects.get(amount=Decimal("10.00")).user, self.alice)

    def test_anonymous_access_is_refused(self):
        self.client.logout()

        self.assertIn(self.client.get(self.list_url).status_code, (401, 403))


class NestedWriteTests(ApiTestCase):
    def test_an_expense_can_be_created_with_items_and_shares(self):
        response = self.client.post(
            self.list_url,
            {
                "category": self.food.pk,
                "amount": "900.00",
                "spent_on": "2026-02-01",
                "items": [
                    {
                        "name": "Pizza",
                        "amount": "600.00",
                        "shares": [{"participant": self.rahul.pk, "weight": 1}],
                    },
                    {"name": "Coke", "amount": "300.00"},
                ],
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201, response.content)
        expense = Expense.objects.get(spent_on=date(2026, 2, 1))
        self.assertEqual(expense.items.count(), 2)
        self.assertEqual(
            ItemShare.objects.filter(item__expense=expense).count(), 2
        )  # Rahul, plus the owner added by include_self

    def test_items_that_do_not_sum_are_accepted(self):
        # The web form stopped refusing these, so the API cannot keep
        # refusing them: two entry points disagreeing about what an expense
        # is would be worse than either rule alone.
        response = self.client.post(
            self.list_url,
            {
                "category": self.food.pk,
                "amount": "900.00",
                "spent_on": "2026-02-01",
                "items": [{"name": "Pizza", "amount": "600.00"}],
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201, response.content)

    def test_an_expense_that_does_not_sum_is_written_but_not_balanced(self):
        self.client.post(
            self.list_url,
            {
                "category": self.food.pk,
                "amount": "900.00",
                "spent_on": "2026-02-01",
                "items": [{"name": "Pizza", "amount": "600.00"}],
            },
            content_type="application/json",
        )

        expense = Expense.objects.get(spent_on=date(2026, 2, 1))
        self.assertEqual(expense.items.count(), 1)
        self.assertFalse(expense.is_balanced())

    def test_a_patch_that_omits_items_leaves_them_alone(self):
        """The classic nested-write data loss, asserted as not happening.

        Absent and empty must not mean the same thing. If they did, every
        PATCH of a note would silently delete the line items.
        """
        ExpenseItem.objects.create(expense=self.mine, name="Pizza", amount=Decimal("900.00"))

        self.client.patch(
            self.detail_url(self.mine.pk),
            {"note": "updated"},
            content_type="application/json",
        )

        self.assertEqual(self.mine.items.count(), 1)

    def test_an_explicit_empty_list_removes_them(self):
        ExpenseItem.objects.create(expense=self.mine, name="Pizza", amount=Decimal("900.00"))

        self.client.patch(
            self.detail_url(self.mine.pk),
            {"items": []},
            content_type="application/json",
        )

        self.assertEqual(self.mine.items.count(), 0)

    def test_a_zero_amount_item_is_rejected(self):
        response = self.client.post(
            self.list_url,
            {
                "category": self.food.pk,
                "amount": "0.00",
                "spent_on": "2026-02-01",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)


class QueryCountTests(ApiTestCase):
    def test_the_list_does_not_issue_a_query_per_item(self):
        for index in range(6):
            expense = Expense.objects.create(
                user=self.alice,
                category=self.food,
                amount=Decimal("100.00"),
                spent_on=date(2026, 4, index + 1),
            )
            item = ExpenseItem.objects.create(
                expense=expense, name="Thing", amount=Decimal("100.00")
            )
            ItemShare.objects.create(item=item, participant=self.rahul)

        # Nested serializers walk three levels. Without the prefetch this
        # would be one query per expense plus one per item.
        with self.assertNumQueries(6):
            self.client.get(self.list_url)


class PaginationTests(ApiTestCase):
    def test_results_are_paginated_with_a_cursor(self):
        response = self.client.get(self.list_url).json()

        # Cursor pagination gives next/previous and deliberately no count:
        # it cannot know the total without the scan it exists to avoid.
        self.assertIn("next", response)
        self.assertIn("results", response)
        self.assertNotIn("count", response)


class CategoryApiTests(ApiTestCase):
    def test_a_duplicate_name_is_a_400_not_a_500(self):
        response = self.client.post(
            reverse("api:v1:category-list"), {"name": "food"}, content_type="application/json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("name", response.json())

    def test_the_list_is_scoped(self):
        names = [
            row["name"]
            for row in self.client.get(reverse("api:v1:category-list")).json()["results"]
        ]

        self.assertEqual(names, ["Food"])
