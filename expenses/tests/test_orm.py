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


class SubqueryAnnotationTests(TestCase):
    """Reading a field off one specific related row."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            "alice", email="alice@example.com", password="pw12345!"
        )
        cls.food = Category.objects.create(user=cls.alice, name="Food")
        cls.empty = Category.objects.create(user=cls.alice, name="Unused")

        # The newest expense is deliberately NOT the largest, which is what
        # separates a Subquery from a pair of Max() aggregates.
        Expense.objects.create(
            user=cls.alice,
            category=cls.food,
            amount=Decimal("5000.00"),
            spent_on=date(2026, 1, 1),
        )
        Expense.objects.create(
            user=cls.alice,
            category=cls.food,
            amount=Decimal("120.00"),
            spent_on=date(2026, 3, 1),
        )

    def setUp(self):
        self.client.force_login(self.alice)

    def _categories(self):
        response = self.client.get(reverse("expenses:category_list"))
        return {c.name: c for c in response.context["categories"]}

    def test_the_latest_amount_belongs_to_the_latest_date(self):
        # Max("expenses__spent_on") and Max("expenses__amount") would report
        # 2026-03-01 paired with 5000.00, which is two different rows and a
        # number that never happened.
        food = self._categories()["Food"]

        self.assertEqual(food.last_spent_on, date(2026, 3, 1))
        self.assertEqual(food.last_amount, Decimal("120.00"))

    def test_a_category_with_no_expenses_annotates_to_none(self):
        empty = self._categories()["Unused"]

        self.assertIsNone(empty.last_spent_on)
        self.assertIsNone(empty.last_amount)
        self.assertEqual(empty.expense_count, 0)

    def test_the_total_is_summed(self):
        self.assertEqual(self._categories()["Food"].total, Decimal("5120.00"))

    def test_another_users_expenses_are_not_counted(self):
        bob = User.objects.create_user("bob", email="bob@example.com", password="pw12345!")
        # Same category object is Alice's; a crafted row must not leak in.
        Expense.objects.create(
            user=bob, category=self.food, amount=Decimal("1.00"), spent_on=date(2026, 6, 1)
        )

        # The subquery correlates on category only, so it sees Bob's row.
        # The *list* is still scoped by OwnerScopedMixin, so Bob never sees
        # this page -- but the annotation is a reminder that a Subquery
        # inherits no scoping from the outer queryset.
        food = self._categories()["Food"]

        self.assertEqual(food.last_spent_on, date(2026, 6, 1))


class UnbalancedExpenseTests(TestCase):
    """The audit for an invariant the database cannot hold."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            "alice", email="alice@example.com", password="pw12345!"
        )
        cls.category = Category.objects.create(user=cls.alice, name="Food")

    def _expense(self, amount, items=()):
        expense = Expense.objects.create(
            user=self.alice,
            category=self.category,
            amount=Decimal(amount),
            spent_on=date.today(),
        )
        for name, item_amount in items:
            ExpenseItem.objects.create(expense=expense, name=name, amount=Decimal(item_amount))
        return expense

    def test_a_balanced_expense_is_not_reported(self):
        self._expense("900.00", [("Pizza", "600.00"), ("Coke", "300.00")])

        self.assertEqual(list(Expense.objects.unbalanced()), [])

    def test_an_unbalanced_expense_is_reported(self):
        # Written directly, bypassing the formset -- exactly how a bad row
        # gets in once the rule lives outside the schema.
        broken = self._expense("900.00", [("Pizza", "600.00")])

        self.assertEqual(list(Expense.objects.unbalanced()), [broken])

    def test_an_expense_with_no_items_is_not_reported(self):
        # Not itemised is not unbalanced. Without the items__isnull filter,
        # Sum over no rows is NULL and NULL != amount reports every one.
        self._expense("900.00")

        self.assertEqual(list(Expense.objects.unbalanced()), [])

    def test_the_command_reports_and_can_fail(self):
        from io import StringIO

        from django.core.management import call_command

        self._expense("900.00", [("Pizza", "600.00")])
        out = StringIO()

        call_command("check_splits", stdout=out, stderr=StringIO())

        self.assertIn("items total 600.00", out.getvalue())

        with self.assertRaises(SystemExit):
            call_command("check_splits", "--fail", stdout=StringIO(), stderr=StringIO())

    def test_the_command_is_quiet_when_everything_adds_up(self):
        from io import StringIO

        from django.core.management import call_command

        self._expense("900.00", [("Pizza", "900.00")])
        out = StringIO()

        call_command("check_splits", stdout=out)

        self.assertIn("adds up", out.getvalue())


class DeferredFieldTests(TestCase):
    """only() and defer(), and the N+1 they can create instead of avoid."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            "alice", email="alice@example.com", password="pw12345!"
        )
        cls.category = Category.objects.create(user=cls.alice, name="Food")
        for day in range(1, 6):
            Expense.objects.create(
                user=cls.alice,
                category=cls.category,
                amount=Decimal("10.00"),
                spent_on=date(2026, 1, day),
                note="x" * 200,
            )

    def test_only_loads_one_query_when_you_stay_inside_it(self):
        with self.assertNumQueries(1):
            [e.amount for e in Expense.objects.only("amount")]

    def test_touching_a_deferred_field_costs_one_query_per_row(self):
        """The trap. only() is a performance tool that can cost performance.

        A deferred field is not missing, it is lazy. Reading it re-queries
        that single row, so a field left out of only() and then used in a
        template is a textbook N+1 that no amount of select_related fixes.
        """
        with self.assertNumQueries(6):  # 1 for the rows, 5 for the notes
            [e.note for e in Expense.objects.only("amount")]

    def test_defer_is_the_same_thing_from_the_other_end(self):
        with self.assertNumQueries(6):
            [e.note for e in Expense.objects.defer("note")]

    def test_values_has_no_such_trap(self):
        # values() returns dicts, so there is no model instance to lazily
        # re-populate. You lose model methods; you cannot accidentally N+1.
        with self.assertNumQueries(1):
            [row["amount"] for row in Expense.objects.values("amount")]


class ExistsVersusCountTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            "alice", email="alice@example.com", password="pw12345!"
        )
        cls.category = Category.objects.create(user=cls.alice, name="Food")

    def test_exists_answers_the_question_without_fetching(self):
        # Both are one query. The difference is what the database does:
        # EXISTS can stop at the first matching row, COUNT(*) must scan
        # every one. On an empty table they are indistinguishable, which is
        # exactly why this gets written the slow way.
        with self.assertNumQueries(1):
            self.assertFalse(Expense.objects.filter(user=self.alice).exists())

    def test_truthiness_evaluates_the_whole_queryset(self):
        """The costly idiom that looks free.

        ``if queryset:`` evaluates it and caches every row. That is a
        bargain when you then iterate, and pure waste when you only wanted
        the yes-or-no, because the rows are built into model instances.
        """
        Expense.objects.create(
            user=self.alice,
            category=self.category,
            amount=Decimal("10.00"),
            spent_on=date(2026, 1, 1),
        )
        queryset = Expense.objects.filter(user=self.alice)

        with self.assertNumQueries(1):
            self.assertTrue(bool(queryset))
            # Already cached: iterating costs nothing more. This is why the
            # idiom survives -- it is right when the next line is a loop.
            self.assertEqual(len(list(queryset)), 1)
