"""Query behaviour: joins that multiply, and counts that must stay flat.

Every assertion here failed at some point during phase 9 with a plausible
wrong answer rather than an error, which is what makes these worth pinning.
"""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from expenses.models import Category, Expense, ExpenseItem, ItemShare, Participant

User = get_user_model()


class SearchAcrossRelationsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            "alice", email="alice@example.com", password="pw12345!"
        )
        cls.category = Category.objects.create(user=cls.alice, name="Food")
        cls.rahul = Participant.objects.create(user=cls.alice, name="Rahul")

        cls.dinner = Expense.objects.create(
            user=cls.alice,
            category=cls.category,
            amount=Decimal("900.00"),
            spent_on=date.today(),
            note="Team dinner",
        )
        cls.pizza = ExpenseItem.objects.create(
            expense=cls.dinner, name="Pizza", amount=Decimal("600.00")
        )
        cls.garlic = ExpenseItem.objects.create(
            expense=cls.dinner, name="Pizza bread", amount=Decimal("300.00")
        )
        ItemShare.objects.create(item=cls.pizza, participant=cls.rahul)

    def setUp(self):
        self.client.force_login(self.alice)

    def _search(self, term):
        return self.client.get(reverse("expenses:expense_list"), {"search": term})

    def test_search_matches_the_note(self):
        self.assertEqual(len(self._search("dinner").context["expenses"]), 1)

    def test_search_matches_an_item_name(self):
        self.assertEqual(len(self._search("Pizza").context["expenses"]), 1)

    def test_search_matches_a_participant_name(self):
        self.assertEqual(len(self._search("Rahul").context["expenses"]), 1)

    def test_one_expense_matching_two_items_appears_once(self):
        """The .distinct() test.

        "Pizza" matches both line items, so the join produces two rows for
        one expense. Without .distinct() the page lists it twice and the
        pagination count is wrong.
        """
        self.assertEqual(len(self._search("Pizza").context["expenses"]), 1)

    def test_the_total_is_not_multiplied_by_the_join(self):
        """The subtler half, and the one .distinct() does not fix.

        DISTINCT removes duplicate rows from a result set. An aggregate has
        already consumed them, so Sum() over a join counts this 900 expense
        once per matching item and reports 1800.
        """
        self.assertEqual(self._search("Pizza").context["filtered_total"], Decimal("900.00"))

    def test_an_unfiltered_total_is_still_right(self):
        self.assertEqual(self._search("").context["filtered_total"], Decimal("900.00"))

    def test_search_is_case_insensitive(self):
        self.assertEqual(len(self._search("pIzZa").context["expenses"]), 1)

    def test_a_term_matching_nothing_returns_nothing(self):
        response = self._search("nothing here")

        self.assertEqual(len(response.context["expenses"]), 0)
        self.assertEqual(response.context["filtered_total"], Decimal("0"))


class QueryCountTests(TestCase):
    """The N+1 guarantee for a fully itemised, fully shared page."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            "alice", email="alice@example.com", password="pw12345!"
        )
        cls.category = Category.objects.create(user=cls.alice, name="Food")
        cls.rahul = Participant.objects.create(user=cls.alice, name="Rahul")

    def _itemised_expense(self):
        expense = Expense.objects.create(
            user=self.alice,
            category=self.category,
            amount=Decimal("600.00"),
            spent_on=date.today(),
        )
        expense.participants.add(self.rahul)
        item = ExpenseItem.objects.create(expense=expense, name="Pizza", amount=Decimal("600.00"))
        ItemShare.objects.create(item=item, participant=self.rahul)
        return expense

    def setUp(self):
        self.client.force_login(self.alice)

    def test_the_count_is_flat_as_itemised_rows_grow(self):
        self._itemised_expense()

        # Ten queries: the eight from test_views, plus the two nested
        # prefetches that now have a non-empty parent set -- shares, and
        # the participant behind each share.
        with self.assertNumQueries(10):
            self.client.get(reverse("expenses:expense_list"))

        for _ in range(12):
            self._itemised_expense()

        # Thirteen expenses, thirteen items, twenty-six shares. Same count.
        # Without the nested Prefetch this would be well over fifty.
        with self.assertNumQueries(10):
            self.client.get(reverse("expenses:expense_list"))

    def test_shared_with_reads_only_prefetched_data(self):
        expense = self._itemised_expense()
        loaded = (
            Expense.objects.filter(pk=expense.pk)
            .prefetch_related("participants", "items__shares__participant")
            .first()
        )

        # Four queries to load it, then none at all to render the names.
        with self.assertNumQueries(0):
            self.assertEqual(loaded.shared_with(), ["Rahul"])

    def test_shared_with_deduplicates_across_both_routes(self):
        # Rahul is on the even-split list AND on a line item. He should be
        # named once, not twice.
        expense = self._itemised_expense()

        self.assertEqual(expense.shared_with(), ["Rahul"])
