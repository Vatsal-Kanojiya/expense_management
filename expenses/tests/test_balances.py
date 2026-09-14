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
        cls.self_participant = Participant.get_or_create_self(cls.alice)
        cls.rahul = Participant.objects.create(user=cls.alice, name="Rahul")
        cls.priya = Participant.objects.create(user=cls.alice, name="Priya")

    def _expense(self, amount, spent_on=date(2026, 1, 15), user=None):
        return Expense.objects.create(
            user=user or self.alice,
            category=self.category,
            amount=Decimal(amount),
            spent_on=spent_on,
        )

    def test_an_itemised_expense_that_does_not_sum_is_skipped(self):
        """The guarantee that replaced the validation error.

        A mismatch can be saved now, so this is what stops it being counted.
        Charging the items anyway would put 150 on the board for a bill whose
        remaining 600 belongs to nobody -- a number that looks settled and is
        not. Skipping is the honest reading of an incomplete split.
        """
        expense = self._expense("900.00")
        item = ExpenseItem.objects.create(expense=expense, name="Pizza", amount=Decimal("300.00"))
        ItemShare.objects.create(item=item, participant=self.self_participant)
        ItemShare.objects.create(item=item, participant=self.rahul)

        self.assertFalse(expense.is_balanced())
        self.assertEqual(balances(self.alice), [])

    def test_the_same_expense_counts_once_it_adds_up(self):
        expense = self._expense("300.00")
        item = ExpenseItem.objects.create(expense=expense, name="Pizza", amount=Decimal("300.00"))
        ItemShare.objects.create(item=item, participant=self.self_participant)
        ItemShare.objects.create(item=item, participant=self.rahul)

        self.assertTrue(expense.is_balanced())
        self.assertEqual(balances(self.alice), [(self.rahul, Decimal("150.00"))])

    def test_an_unshared_expense_owes_nothing(self):
        self._expense("300.00")

        self.assertEqual(balances(self.alice), [])

    def test_an_even_split_counts_the_owner_as_a_share(self):
        # 300 between Alice and Rahul is 150 each, not 300.
        expense = self._expense("300.00")
        expense.participants.add(self.self_participant, self.rahul)

        self.assertEqual(balances(self.alice), [(self.rahul, Decimal("150.00"))])

    def test_owner_can_be_excluded_from_split(self):
        # Pure reimbursement: 300 shared with Rahul and Priya with Alice excluded
        # gives each of them 150, not 100.
        expense = self._expense("300.00")
        expense.participants.add(self.rahul, self.priya)

        self.assertEqual(
            dict(balances(self.alice)),
            {self.rahul: Decimal("150.00"), self.priya: Decimal("150.00")},
        )

    def test_owner_can_be_excluded_from_an_item(self):
        # Pure reimbursement on a line item: Alice paid 300 for Rahul's pizza.
        expense = self._expense("300.00")
        item = ExpenseItem.objects.create(expense=expense, name="Pizza", amount=Decimal("300.00"))
        ItemShare.objects.create(item=item, participant=self.rahul)

        self.assertEqual(balances(self.alice), [(self.rahul, Decimal("300.00"))])

    def test_friend_can_be_the_payer(self):
        # Third-party payment: Rahul paid 300 for dinner for Alice and Rahul.
        # Alice owes Rahul 150 (represented as negative owed).
        dinner = self._expense("300.00")
        dinner.paid_by = self.rahul
        dinner.save()
        dinner.participants.add(self.self_participant, self.rahul)

        self.assertEqual(dict(balances(self.alice)), {self.rahul: Decimal("-150.00")})

    def test_friend_payer_netted_against_user_payment(self):
        # Rahul paid 300 for dinner (Alice owes Rahul 150).
        # Later Alice paid 500 for lunch (Rahul owes Alice 250).
        # Net: Rahul owes Alice 100.
        dinner = self._expense("300.00")
        dinner.paid_by = self.rahul
        dinner.save()
        dinner.participants.add(self.self_participant, self.rahul)

        lunch = self._expense("500.00")
        lunch.participants.add(self.self_participant, self.rahul)

        self.assertEqual(balances(self.alice), [(self.rahul, Decimal("100.00"))])

    def test_an_even_split_across_three_people(self):
        expense = self._expense("300.00")
        expense.participants.add(self.self_participant, self.rahul, self.priya)

        self.assertEqual(
            dict(balances(self.alice)),
            {self.rahul: Decimal("100.00"), self.priya: Decimal("100.00")},
        )

    def test_an_indivisible_even_split_still_adds_up(self):
        # 100 across three shares. Alice absorbs the extra paisa because the
        # owner's share is first in the allocation.
        expense = self._expense("100.00")
        expense.participants.add(self.self_participant, self.rahul, self.priya)

        owed = dict(balances(self.alice))

        self.assertEqual(owed[self.rahul], Decimal("33.33"))
        self.assertEqual(owed[self.priya], Decimal("33.33"))

    def test_items_split_per_line(self):
        expense = self._expense("900.00")
        pizza = ExpenseItem.objects.create(expense=expense, name="Pizza", amount=Decimal("600.00"))
        ExpenseItem.objects.create(expense=expense, name="Coffee", amount=Decimal("300.00"))
        # Only Rahul shared the pizza; the coffee was Alice's alone.
        ItemShare.objects.create(item=pizza, participant=self.self_participant)
        ItemShare.objects.create(item=pizza, participant=self.rahul)

        self.assertEqual(balances(self.alice), [(self.rahul, Decimal("300.00"))])

    def test_an_item_nobody_ticked_is_yours(self):
        expense = self._expense("600.00")
        ExpenseItem.objects.create(expense=expense, name="Pizza", amount=Decimal("600.00"))

        self.assertEqual(balances(self.alice), [])

    def test_items_win_over_participants_when_both_exist(self):
        # Applying both would charge Rahul twice for the same bill.
        expense = self._expense("600.00")
        expense.participants.add(self.self_participant, self.rahul)
        pizza = ExpenseItem.objects.create(expense=expense, name="Pizza", amount=Decimal("600.00"))
        ItemShare.objects.create(item=pizza, participant=self.self_participant)
        ItemShare.objects.create(item=pizza, participant=self.rahul)

        self.assertEqual(balances(self.alice), [(self.rahul, Decimal("300.00"))])

    def test_weights_make_an_unequal_share(self):
        expense = self._expense("400.00")
        item = ExpenseItem.objects.create(expense=expense, name="Platter", amount=Decimal("400.00"))
        # Alice 1 share, Rahul 3. Four shares of 100.
        ItemShare.objects.create(item=item, participant=self.self_participant, weight=1)
        ItemShare.objects.create(item=item, participant=self.rahul, weight=3)

        self.assertEqual(balances(self.alice), [(self.rahul, Decimal("300.00"))])

    def test_balances_accumulate_across_expenses(self):
        first = self._expense("300.00")
        first.participants.add(self.self_participant, self.rahul)
        second = self._expense("100.00")
        second.participants.add(self.self_participant, self.rahul)

        self.assertEqual(balances(self.alice), [(self.rahul, Decimal("200.00"))])

    def test_the_date_range_is_respected(self):
        january = self._expense("300.00", spent_on=date(2026, 1, 15))
        january.participants.add(self.self_participant, self.rahul)
        march = self._expense("500.00", spent_on=date(2026, 3, 15))
        march.participants.add(self.self_participant, self.rahul)

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
        big.participants.add(self.self_participant, self.rahul)
        small = self._expense("100.00")
        small.participants.add(self.self_participant, self.priya)

        self.assertEqual(
            [participant for participant, _ in balances(self.alice)], [self.rahul, self.priya]
        )

    def test_misc_is_split_by_consumption_not_by_head(self):
        # Pizza 600 shared with Rahul, Coke 200 not shared, misc 80, amount 880.
        # Owner consumed 300 + 200 = 500, Rahul consumed 300.
        # Rahul owes 300 + 30 = 330.
        expense = self._expense("880.00")
        expense.misc_amount = Decimal("80.00")
        expense.misc_note = "Tip and tax"
        expense.save()

        pizza = ExpenseItem.objects.create(expense=expense, name="Pizza", amount=Decimal("600.00"))
        ItemShare.objects.create(item=pizza, participant=self.self_participant)
        ItemShare.objects.create(item=pizza, participant=self.rahul)

        ExpenseItem.objects.create(expense=expense, name="Coke", amount=Decimal("200.00"))

        self.assertEqual(balances(self.alice), [(self.rahul, Decimal("330.00"))])

    def test_a_participant_who_consumed_nothing_bears_no_misc(self):
        # Priya on the expense participants list but on no line items consumed nothing
        # and bears no misc.
        expense = self._expense("880.00")
        expense.misc_amount = Decimal("80.00")
        expense.misc_note = "GST"
        expense.save()
        expense.participants.add(self.self_participant, self.rahul, self.priya)

        pizza = ExpenseItem.objects.create(expense=expense, name="Pizza", amount=Decimal("600.00"))
        ItemShare.objects.create(item=pizza, participant=self.self_participant)
        ItemShare.objects.create(item=pizza, participant=self.rahul)

        ExpenseItem.objects.create(expense=expense, name="Coke", amount=Decimal("200.00"))

        self.assertEqual(balances(self.alice), [(self.rahul, Decimal("330.00"))])

    def test_misc_is_not_charged_to_the_owner_when_the_owner_is_out(self):
        # Rahul and Priya shared a 600 meal (300 each), misc 80 (40 each).
        # Alice is not on the items and paid for it. Rahul owes 340, Priya owes 340.
        expense = self._expense("680.00")
        expense.misc_amount = Decimal("80.00")
        expense.misc_note = "Delivery charge"
        expense.save()

        meal = ExpenseItem.objects.create(expense=expense, name="Meal", amount=Decimal("600.00"))
        ItemShare.objects.create(item=meal, participant=self.rahul)
        ItemShare.objects.create(item=meal, participant=self.priya)

        self.assertEqual(
            dict(balances(self.alice)),
            {self.rahul: Decimal("340.00"), self.priya: Decimal("340.00")},
        )

    def test_misc_adds_no_queries(self):
        for _ in range(5):
            expense = self._expense("880.00")
            expense.misc_amount = Decimal("80.00")
            expense.misc_note = "Tip"
            expense.save()
            pizza = ExpenseItem.objects.create(
                expense=expense, name="Pizza", amount=Decimal("600.00")
            )
            ItemShare.objects.create(item=pizza, participant=self.self_participant)
            ItemShare.objects.create(item=pizza, participant=self.rahul)
            ExpenseItem.objects.create(expense=expense, name="Coke", amount=Decimal("200.00"))

        with self.assertNumQueries(6):
            balances(self.alice)


class BalanceViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            "alice", email="alice@example.com", password="pw12345!"
        )
        cls.category = Category.objects.create(user=cls.alice, name="Food")
        cls.rahul = Participant.objects.create(user=cls.alice, name="Rahul")
        cls.self_participant = Participant.get_or_create_self(cls.alice)

    def test_the_page_shows_a_balance(self):
        self.client.force_login(self.alice)
        expense = Expense.objects.create(
            user=self.alice,
            category=self.category,
            amount=Decimal("300.00"),
            spent_on=date.today(),
        )
        expense.participants.add(self.self_participant, self.rahul)

        response = self.client.get(reverse("expenses:balances"))

        self.assertContains(response, "Rahul")
        self.assertContains(response, "150.00")

    def test_anonymous_users_are_redirected(self):
        response = self.client.get(reverse("expenses:balances"))

        self.assertEqual(response.status_code, 302)
