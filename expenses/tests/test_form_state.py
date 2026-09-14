"""The expense form must not lose what the person typed (issue 36).

When the parent form failed -- a blank note, say -- the page came back with
the error and every line item gone, although the POST carried all of them.
Each test here failed before ItemFormSetMixin.form_invalid existed.
"""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from expenses.models import Category, Expense, ExpenseItem, Participant
from expenses.tests.helpers import item_formset

User = get_user_model()


class FormStateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            "alice", email="alice@example.com", password="pw12345!"
        )
        cls.category = Category.objects.create(user=cls.alice, name="Food")
        cls.rahul = Participant.objects.create(user=cls.alice, name="Rahul")

    def setUp(self):
        self.client.force_login(self.alice)

    def _post(self, url, note="", items=(("Pizza", "600.00"), ("Coke", "300.00")), **extra):
        data = {
            "category": self.category.pk,
            "amount": "900.00",
            "spent_on": date.today().isoformat(),
            "note": note,
            "participants": [self.rahul.pk],
            **item_formset(*items),
            **extra,
        }
        return self.client.post(url, data)

    def test_line_items_survive_a_parent_form_error(self):
        response = self._post(reverse("expenses:expense_create"))

        self.assertEqual(response.status_code, 200)
        self.assertIn("note", response.context["form"].errors)
        self.assertTrue(response.context["formset"].is_bound)
        self.assertContains(response, "Pizza")
        self.assertContains(response, "Coke")

    def test_item_shares_survive_a_parent_form_error(self):
        response = self._post(
            reverse("expenses:expense_create"),
            **{"items-0-shared_with": [self.rahul.pk]},
        )

        first_row = response.context["formset"].forms[0]
        self.assertIn(str(self.rahul.pk), [str(v) for v in first_row["shared_with"].value()])

    def test_parent_and_formset_errors_show_together(self):
        # Before the fix the item error only appeared after the note was
        # fixed and the form submitted a second time.
        response = self._post(
            reverse("expenses:expense_create"),
            items=(("Pizza", ""),),
        )

        self.assertIn("note", response.context["form"].errors)
        self.assertIn("amount", response.context["formset"].forms[0].errors)

    def test_nothing_is_saved_on_a_parent_form_error(self):
        self._post(reverse("expenses:expense_create"))

        self.assertEqual(Expense.objects.count(), 0)
        self.assertEqual(ExpenseItem.objects.count(), 0)

    def test_update_keeps_edited_items_on_error(self):
        expense = Expense.objects.create(
            user=self.alice,
            category=self.category,
            amount=Decimal("900.00"),
            spent_on=date.today(),
            note="Dinner",
        )
        item = ExpenseItem.objects.create(expense=expense, name="Pizza", amount=Decimal("900.00"))

        response = self._post(
            reverse("expenses:expense_update", args=[expense.pk]),
            items=(("Large pizza", "900.00"),),
            **{"items-INITIAL_FORMS": "1", "items-0-id": str(item.pk)},
        )

        # The edited name is re-rendered, not the saved one, and nothing
        # was written.
        self.assertContains(response, "Large pizza")
        item.refresh_from_db()
        self.assertEqual(item.name, "Pizza")

    def test_a_valid_submission_still_saves(self):
        # Each item names who had it: the payer is not among the participants
        # here, and the form rightly refuses an item charged to nobody.
        response = self._post(
            reverse("expenses:expense_create"),
            note="Team dinner",
            **{"items-0-shared_with": [self.rahul.pk], "items-1-shared_with": [self.rahul.pk]},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Expense.objects.get().items.count(), 2)


class RequiredMarkerTests(TestCase):
    """The asterisk CSS keys on the required attribute (issue 37).

    A test cannot see CSS, so these pin the property the CSS depends on.
    If a future change stops Django rendering `required`, the stars vanish
    silently; these are what notice.
    """

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            "alice", email="alice@example.com", password="pw12345!"
        )

    def setUp(self):
        self.client.force_login(self.alice)

    def test_required_fields_render_the_required_attribute(self):
        form = self.client.get(reverse("expenses:expense_create")).context["form"]

        for name in ("category", "amount", "spent_on", "note"):
            self.assertIn(" required", str(form[name]), name)

        for name in ("paid_by", "misc_amount", "misc_note"):
            self.assertNotIn(" required", str(form[name]), name)

    def test_line_item_required_columns_are_marked(self):
        response = self.client.get(reverse("expenses:expense_create"))

        self.assertEqual(response.content.decode().count('class="required-mark"'), 2)
