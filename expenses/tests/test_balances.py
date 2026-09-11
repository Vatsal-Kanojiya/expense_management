"""Who owes what, and the convention that decides every number.

The rule under test: the owner always counts as one share of anything that
is shared at all. Get that wrong and every balance is off by a factor of
(n+1)/n, which looks plausible and is never right.
"""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from expenses.balances import balances
from expenses.models import Category, Expense, ExpenseItem, ItemShare, Participant

User = get_user_model()


class BalanceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            "alice", email="alice@example.com", password="pw12345!"
        )
        cls.bob = User.objects.create_user("bob", email="bob@example.com", password="pw12345!")
        cls.category = Category.objects.create(user=cls.alice, name="Food")
        cls.rahul = Participant.objects.create(user=cls.alice, name="Rahul")
        cls.priya = Participant.objects.create(user=cls.alice, name="Priya")

    def _expense(self, amount, spent_on=date(2026, 1, 15), user=None):
        return Expense.objects.create(
            user=user or self.alice,
            category=self.category,
            amount=Decimal(amount),
            spent_on=spent_on,
        )

    def test_an_unshared_expense_owes_nothing(self):
        self._expense("300.00")

        self.assertEqual(balances(self.alice), [])

    def test_an_even_split_counts_the_owner_as_a_share(self):
        # 300 between Alice and Rahul is 150 each, not 300.
        expense = self._expense("300.00")
        expense.participants.add(self.rahul)

        self.assertEqual(balances(self.alice), [(self.rahul, Decimal("150.00"))])

    def test_an_even_split_across_three_people(self):
        expense = self._expense("300.00")
        expense.participants.add(self.rahul, self.priya)

        self.assertEqual(
            dict(balances(self.alice)),
            {self.rahul: Decimal("100.00"), self.priya: Decimal("100.00")},
        )

    def test_an_indivisible_even_split_still_adds_up(self):
        # 100 across three shares. Alice absorbs the extra paisa because the
        # owner's share is first in the allocation.
        expense = self._expense("100.00")
        expense.participants.add(self.rahul, self.priya)

        owed = dict(balances(self.alice))

        self.assertEqual(owed[self.rahul], Decimal("33.33"))
        self.assertEqual(owed[self.priya], Decimal("33.33"))

    def test_items_split_per_line(self):
        expense = self._expense("900.00")
        pizza = ExpenseItem.objects.create(expense=expense, name="Pizza", amount=Decimal("600.00"))
        ExpenseItem.objects.create(expense=expense, name="Coffee", amount=Decimal("300.00"))
        # Only Rahul shared the pizza; the coffee was Alice's alone.
        ItemShare.objects.create(item=pizza, participant=self.rahul)

        self.assertEqual(balances(self.alice), [(self.rahul, Decimal("300.00"))])

    def test_an_item_nobody_ticked_is_yours(self):
        expense = self._expense("600.00")
        ExpenseItem.objects.create(expense=expense, name="Pizza", amount=Decimal("600.00"))

        self.assertEqual(balances(self.alice), [])

    def test_items_win_over_participants_when_both_exist(self):
        # Applying both would charge Rahul twice for the same bill.
        expense = self._expense("600.00")
        expense.participants.add(self.rahul)
        pizza = ExpenseItem.objects.create(expense=expense, name="Pizza", amount=Decimal("600.00"))
        ItemShare.objects.create(item=pizza, participant=self.rahul)

        self.assertEqual(balances(self.alice), [(self.rahul, Decimal("300.00"))])

    def test_weights_make_an_unequal_share(self):
        expense = self._expense("400.00")
        item = ExpenseItem.objects.create(expense=expense, name="Platter", amount=Decimal("400.00"))
        # Alice 1 share, Rahul 3. Four shares of 100.
        ItemShare.objects.create(item=item, participant=self.rahul, weight=3)

        self.assertEqual(balances(self.alice), [(self.rahul, Decimal("300.00"))])

    def test_balances_accumulate_across_expenses(self):
        first = self._expense("300.00")
        first.participants.add(self.rahul)
        second = self._expense("100.00")
        second.participants.add(self.rahul)

        self.assertEqual(balances(self.alice), [(self.rahul, Decimal("200.00"))])

    def test_the_date_range_is_respected(self):
        january = self._expense("300.00", spent_on=date(2026, 1, 15))
        january.participants.add(self.rahul)
        march = self._expense("500.00", spent_on=date(2026, 3, 15))
        march.participants.add(self.rahul)

        owed = balances(self.alice, date(2026, 1, 1), date(2026, 1, 31))

        self.assertEqual(owed, [(self.rahul, Decimal("150.00"))])

    def test_another_users_expenses_are_never_counted(self):
        theirs = self._expense("900.00", user=self.bob)
        # Bob cannot actually reach Alice's participants through the UI; this
        # asserts the scoping holds even if a row were crafted.
        theirs.participants.add(self.rahul)

        self.assertEqual(balances(self.alice), [])

    def test_results_are_ranked_by_amount(self):
        big = self._expense("1000.00")
        big.participants.add(self.rahul)
        small = self._expense("100.00")
        small.participants.add(self.priya)

        self.assertEqual(
            [participant for participant, _ in balances(self.alice)], [self.rahul, self.priya]
        )


class BalanceViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            "alice", email="alice@example.com", password="pw12345!"
        )
        cls.category = Category.objects.create(user=cls.alice, name="Food")
        cls.rahul = Participant.objects.create(user=cls.alice, name="Rahul")

    def test_the_page_shows_a_balance(self):
        self.client.force_login(self.alice)
        expense = Expense.objects.create(
            user=self.alice,
            category=self.category,
            amount=Decimal("300.00"),
            spent_on=date.today(),
        )
        expense.participants.add(self.rahul)

        response = self.client.get(reverse("expenses:balances"))

        self.assertContains(response, "Rahul")
        self.assertContains(response, "150.00")

    def test_anonymous_users_are_redirected(self):
        response = self.client.get(reverse("expenses:balances"))

        self.assertEqual(response.status_code, 302)
