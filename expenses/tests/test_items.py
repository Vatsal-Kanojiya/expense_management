"""Line items, the invariant no constraint can express, and atomicity.

The rule under test is "the items of an expense must sum to that expense's
amount". It spans rows, so a CheckConstraint cannot hold it.

It is no longer a gate. Refusing the submission cost the person everything
else they had typed, so a mismatch is now saved and reported instead, and
what keeps the numbers honest is that `balances` declines to split an
expense that does not add up. These tests cover that shift: the record is
written, the warning is shown, and `is_balanced` marks it.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from expenses.models import Category, Expense, ExpenseItem, ItemShare, Participant
from expenses.tests.helpers import item_formset

User = get_user_model()


class ItemFormSetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            "alice", email="alice@example.com", password="pw12345!"
        )
        cls.category = Category.objects.create(user=cls.alice, name="Food")

    def setUp(self):
        self.client.force_login(self.alice)

    def _post(self, amount="900.00", items=(), initial=0, url=None, follow=False):
        return self.client.post(
            url or reverse("expenses:expense_create"),
            {
                "category": self.category.pk,
                "amount": amount,
                "spent_on": "2026-01-15",
                "note": "Dinner",
                **item_formset(*items, initial=initial),
            },
            follow=follow,
        )

    def test_an_expense_can_be_itemised(self):
        self._post(items=[("Pizza", "600.00"), ("Coke", "300.00")])

        expense = Expense.objects.get()
        self.assertEqual(expense.items.count(), 2)
        self.assertEqual(expense.items.first().name, "Pizza")

    def test_items_that_do_not_sum_are_saved_with_a_warning(self):
        response = self._post(items=[("Pizza", "600.00"), ("Coke", "200.00")], follow=True)

        self.assertContains(response, "100.00")
        self.assertContains(response, "not accounted for")
        self.assertContains(response, "left out of balances")

    def test_the_expense_is_written_even_when_the_items_do_not_sum(self):
        # The rule used to refuse the submission outright, which threw away
        # every other field the person had filled in. The record is kept now;
        # what protects the numbers is that nothing will split it.
        self._post(items=[("Pizza", "600.00"), ("Coke", "200.00")])

        self.assertEqual(Expense.objects.count(), 1)
        self.assertEqual(ExpenseItem.objects.count(), 2)

    def test_an_expense_that_does_not_sum_is_not_balanced(self):
        self._post(items=[("Pizza", "600.00"), ("Coke", "200.00")])

        expense = Expense.objects.get()
        self.assertEqual(expense.items_total(), Decimal("800.00"))
        self.assertFalse(expense.is_balanced())

    def test_an_expense_with_no_items_is_balanced(self):
        self._post(items=[])

        self.assertIsNone(Expense.objects.get().items_total())
        self.assertTrue(Expense.objects.get().is_balanced())

    def test_itemising_is_optional(self):
        self._post(items=[])

        self.assertEqual(Expense.objects.get().items.count(), 0)

    def test_an_item_must_cost_something(self):
        response = self._post(items=[("Free", "0.00")])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Expense.objects.count(), 0)

    def test_items_can_be_edited(self):
        self._post(items=[("Pizza", "900.00")])
        expense = Expense.objects.get()
        item = expense.items.get()

        self.client.post(
            reverse("expenses:expense_update", args=[expense.pk]),
            {
                "category": self.category.pk,
                "amount": "900.00",
                "spent_on": "2026-01-15",
                "note": "Dinner",
                "items-TOTAL_FORMS": "1",
                "items-INITIAL_FORMS": "1",
                "items-MIN_NUM_FORMS": "0",
                "items-MAX_NUM_FORMS": "1000",
                # Without this id the edit becomes an insert and the totals
                # double. This is why the template renders {{ form.id }}.
                "items-0-id": str(item.pk),
                "items-0-name": "Large pizza",
                "items-0-amount": "900.00",
            },
        )

        self.assertEqual(expense.items.get().name, "Large pizza")
        self.assertEqual(expense.items.count(), 1)

    def test_an_item_can_be_deleted_if_the_rest_still_sums(self):
        self._post(amount="900.00", items=[("Pizza", "600.00"), ("Coke", "300.00")])
        expense = Expense.objects.get()
        pizza, coke = expense.items.all()

        self.client.post(
            reverse("expenses:expense_update", args=[expense.pk]),
            {
                "category": self.category.pk,
                "amount": "600.00",
                "spent_on": "2026-01-15",
                "note": "Dinner",
                "items-TOTAL_FORMS": "2",
                "items-INITIAL_FORMS": "2",
                "items-MIN_NUM_FORMS": "0",
                "items-MAX_NUM_FORMS": "1000",
                "items-0-id": str(pizza.pk),
                "items-0-name": pizza.name,
                "items-0-amount": "600.00",
                "items-1-id": str(coke.pk),
                "items-1-name": coke.name,
                "items-1-amount": "300.00",
                "items-1-DELETE": "on",
            },
        )

        self.assertEqual(expense.items.count(), 1)
        self.assertEqual(expense.items.get().name, "Pizza")

    def test_a_deleted_row_is_excluded_from_the_sum(self):
        # If DELETE were ignored, this would be rejected as 900 against 600.
        self._post(amount="900.00", items=[("Pizza", "900.00")])

        self.assertEqual(Expense.objects.count(), 1)

    def test_a_missing_management_form_rejects_the_whole_post(self):
        """The trap that makes a valid-looking POST fail.

        Django cannot tell how many child forms came back without the
        management form, so it refuses the submission entirely. In a browser
        that means someone deleted ``{{ formset.management_form }}`` from the
        template; in a test it means the helper was not used.
        """
        response = self.client.post(
            reverse("expenses:expense_create"),
            {
                "category": self.category.pk,
                "amount": "900.00",
                "spent_on": "2026-01-15",
                "note": "Dinner",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Expense.objects.count(), 0)

    def test_the_sum_is_compared_exactly_not_approximately(self):
        # Decimal, not float. 0.1 + 0.2 != 0.3 in binary floating point.
        # Decimal sums stay exact; the ₹1 tolerance applies only to whether
        # an expense is balanced, not to floating-point imprecision.
        response = self._post(amount="0.30", items=[("A", "0.10"), ("B", "0.20")])

        self.assertEqual(Expense.objects.count(), 1)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(sum(i.amount for i in Expense.objects.get().items.all()), Decimal("0.30"))

    def test_misc_amount_needs_line_items(self):
        # A misc amount on an expense with no line items is refused.
        data = {
            "category": self.category.pk,
            "amount": "300.00",
            "spent_on": "2026-01-15",
            "note": "Dinner",
            "misc_amount": "50.00",
            "misc_note": "Tip",
            "items-TOTAL_FORMS": "0",
            "items-INITIAL_FORMS": "0",
            "items-MIN_NUM_FORMS": "0",
            "items-MAX_NUM_FORMS": "1000",
        }
        response = self.client.post(reverse("expenses:expense_create"), data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Expense.objects.count(), 0)
        self.assertContains(response, "A misc amount can only be added to an itemised expense")


class ItemShareTests(TestCase):
    """Editing a through model through a plain multiple-choice field."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            "alice", email="alice@example.com", password="pw12345!"
        )
        cls.bob = User.objects.create_user("bob", email="bob@example.com", password="pw12345!")
        cls.category = Category.objects.create(user=cls.alice, name="Food")
        cls.rahul = Participant.objects.create(user=cls.alice, name="Rahul")
        cls.stranger = Participant.objects.create(user=cls.bob, name="Stranger")

    def setUp(self):
        self.client.force_login(self.alice)

    def _post(self, shared_with, url=None, initial=0, item_pk=None, participants=None):
        if participants is None:
            participants = shared_with or [self.rahul.pk]
        data = {
            "category": self.category.pk,
            "amount": "600.00",
            "spent_on": "2026-01-15",
            "note": "Dinner",
            "participants": participants,
            "items-TOTAL_FORMS": "1",
            "items-INITIAL_FORMS": str(initial),
            "items-MIN_NUM_FORMS": "0",
            "items-MAX_NUM_FORMS": "1000",
            "items-0-name": "Pizza",
            "items-0-amount": "600.00",
            "items-0-shared_with": shared_with,
        }
        if item_pk:
            data["items-0-id"] = str(item_pk)
        return self.client.post(url or reverse("expenses:expense_create"), data)

    def test_ticking_someone_creates_a_share(self):
        self._post([self.rahul.pk])

        share = ItemShare.objects.get()
        self.assertEqual(share.participant, self.rahul)
        self.assertEqual(share.weight, 1)

    def test_a_line_can_only_charge_an_expense_participant(self):
        priya = Participant.objects.create(user=self.alice, name="Priya")
        response = self._post(
            shared_with=[priya.pk],
            participants=[self.rahul.pk],
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Expense.objects.count(), 0)
        self.assertContains(response, "Priya")

    def test_an_existing_share_outside_the_participants_is_preserved(self):
        priya = Participant.objects.create(user=self.alice, name="Priya")
        expense = Expense.objects.create(
            user=self.alice,
            category=self.category,
            amount=Decimal("600.00"),
            spent_on="2026-01-15",
        )
        expense.participants.add(self.rahul)
        item = ExpenseItem.objects.create(expense=expense, name="Pizza", amount=Decimal("600.00"))
        share = ItemShare.objects.create(item=item, participant=priya)

        # GET edit view: Priya is offered in the line item options
        response = self.client.get(reverse("expenses:expense_update", args=[expense.pk]))
        self.assertContains(response, "Priya")
        self.assertContains(response, "Rahul")

        # POST edit view: resaving with Priya preserved succeeds
        response = self._post(
            shared_with=[priya.pk],
            url=reverse("expenses:expense_update", args=[expense.pk]),
            initial=1,
            item_pk=item.pk,
            participants=[self.rahul.pk],
        )
        self.assertEqual(response.status_code, 302)
        share.refresh_from_db()
        self.assertEqual(share.participant, priya)

    def test_the_picker_offers_only_the_expense_participants(self):
        priya = Participant.objects.create(user=self.alice, name="Priya")
        amit = Participant.objects.create(user=self.alice, name="Amit")
        expense = Expense.objects.create(
            user=self.alice,
            category=self.category,
            amount=Decimal("600.00"),
            spent_on="2026-01-15",
        )
        expense.participants.add(self.rahul, priya)

        response = self.client.get(reverse("expenses:expense_update", args=[expense.pk]))

        formset = response.context["formset"]
        picker_qs = formset.forms[0].fields["shared_with"].queryset
        self.assertIn(self.rahul, picker_qs)
        self.assertIn(priya, picker_qs)
        self.assertNotIn(amit, picker_qs)

    def test_the_checkbox_list_is_scoped_to_your_people(self):
        response = self.client.get(reverse("expenses:expense_create"))

        self.assertNotContains(response, "Stranger")

    def test_a_crafted_post_cannot_tick_someone_elses_person(self):
        response = self._post([self.stranger.pk])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(ItemShare.objects.count(), 0)

    def test_unticking_removes_the_share(self):
        self._post([self.rahul.pk])
        expense = Expense.objects.get()
        item = expense.items.get()

        self._post(
            [],
            url=reverse("expenses:expense_update", args=[expense.pk]),
            initial=1,
            item_pk=item.pk,
        )

        self.assertEqual(ItemShare.objects.count(), 0)

    def test_resaving_keeps_the_same_share_row(self):
        # Reconciliation is a diff, not delete-then-recreate, so the primary
        # key survives and so would a weight the UI does not set.
        self._post([self.rahul.pk])
        expense = Expense.objects.get()
        item = expense.items.get()
        original = ItemShare.objects.get().pk

        self._post(
            [self.rahul.pk],
            url=reverse("expenses:expense_update", args=[expense.pk]),
            initial=1,
            item_pk=item.pk,
        )

        self.assertEqual(ItemShare.objects.get().pk, original)

    def test_existing_shares_are_preselected_when_editing(self):
        self._post([self.rahul.pk])
        expense = Expense.objects.get()

        response = self.client.get(reverse("expenses:expense_update", args=[expense.pk]))

        # SelectMultiple renders selected options with the selected attribute.
        self.assertContains(response, f'value="{self.rahul.pk}" selected')
