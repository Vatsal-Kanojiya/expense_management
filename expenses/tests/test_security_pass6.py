"""Security pass 6 (docs/HANDOVER.md): what goes in, and what comes back out.

Four items, checked one by one, in the order HANDOVER.md lists them. This
first part covers item 1, amounts and numbers: every money field must
reject a bad value with a form or serializer error, on the web and the
API, never a 500.

Most of this was already correct: the model's CheckConstraints and the
form/serializer clean_amount methods already refuse negative, zero and
non-numeric amounts, and Django's own DecimalField and DateField already
turn "NaN", "Infinity", an oversized value or a malformed date into a
field error rather than an exception (confirmed against the framework
directly, not just guessed). The one real gap was
``ItemShareSerializer.weight``: its auto-generated bounds (min_value=0,
max_value in the billions) let 0 and values beyond the smallint column
through the serializer, both of which then reached the database as an
uncaught ``IntegrityError`` -- a 500 -- instead of a field error. Fixed
here by stating the field's real bounds (1 to 32767) explicitly.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from expenses.models import Category, Expense, ExpenseItem, Participant
from expenses.tests.helpers import item_formset

User = get_user_model()
PASSWORD = "Str0ng-Enough-Pass"


def api(name, *args):
    return reverse(f"api:v1:{name}", args=args)


# --- 1. Amounts and numbers: never a 500, web or API ------------------------


class ExpenseAmountsTestCase(TestCase):
    """One account, one category -- the fixtures every amount test shares."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", "alice@example.com", PASSWORD)
        cls.category = Category.objects.create(user=cls.alice, name="Food")
        cls.person = Participant.get_or_create_self(cls.alice)

    def setUp(self):
        self.client.force_login(self.alice)

    def _web_payload(self, **overrides):
        data = {
            "category": self.category.pk,
            "amount": "25.00",
            "spent_on": "2026-09-01",
            "note": "Lunch",
            "paid_by": "",
            "participants": [],
            "misc_amount": "",
            "misc_note": "",
        }
        data.update(item_formset())
        data.update(overrides)
        return data

    def _api_payload(self, **overrides):
        data = {
            "category": self.category.pk,
            "amount": "25.00",
            "spent_on": "2026-09-01",
            "note": "Lunch",
        }
        data.update(overrides)
        return data


# Values that must never be saved as an Expense.amount / misc_amount /
# ExpenseItem.amount: negative, zero, non-numeric, and beyond the model's
# max_digits=10, decimal_places=2 (8 integer digits + 2 decimal is the
# largest that fits).
BAD_AMOUNTS = ["-5.00", "0.00", "not-a-number", "123456789.01", "NaN", "Infinity"]


class BadAmountsWebTests(ExpenseAmountsTestCase):
    def test_expense_amount_never_500s_and_shows_a_form_error(self):
        for bad in BAD_AMOUNTS:
            with self.subTest(amount=bad):
                response = self.client.post(
                    reverse("expenses:expense_create"), self._web_payload(amount=bad)
                )

                self.assertEqual(response.status_code, 200)
                self.assertIn("amount", response.context["form"].errors)
                self.assertFalse(Expense.objects.filter(note="Lunch").exists())

    def test_misc_amount_never_500s_and_shows_a_form_error(self):
        for bad in BAD_AMOUNTS:
            with self.subTest(misc_amount=bad):
                response = self.client.post(
                    reverse("expenses:expense_create"),
                    self._web_payload(misc_amount=bad, misc_note="Tip"),
                )

                self.assertEqual(response.status_code, 200)
                self.assertIn("misc_amount", response.context["form"].errors)

    def test_line_item_amount_never_500s(self):
        for bad in BAD_AMOUNTS:
            with self.subTest(item_amount=bad):
                payload = self._web_payload()
                payload.update(item_formset(("Coffee", bad)))

                response = self.client.post(reverse("expenses:expense_create"), payload)

                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["formset"].errors[0])
                self.assertEqual(ExpenseItem.objects.count(), 0)

    def test_bad_spent_on_never_500s(self):
        for bad in ["not-a-date", "2026-02-30", "2026-13-01", "0000-01-01", "99999-01-01"]:
            with self.subTest(spent_on=bad):
                response = self.client.post(
                    reverse("expenses:expense_create"), self._web_payload(spent_on=bad)
                )

                self.assertEqual(response.status_code, 200)
                self.assertIn("spent_on", response.context["form"].errors)


class BadAmountsApiTests(ExpenseAmountsTestCase):
    def test_expense_amount_never_500s_and_returns_400(self):
        for bad in BAD_AMOUNTS:
            with self.subTest(amount=bad):
                response = self.client.post(
                    api("expense-list"),
                    self._api_payload(amount=bad),
                    content_type="application/json",
                )

                self.assertEqual(response.status_code, 400)
                self.assertIn("amount", response.json())

    def test_misc_amount_never_500s_and_returns_400(self):
        for bad in BAD_AMOUNTS:
            with self.subTest(misc_amount=bad):
                response = self.client.post(
                    api("expense-list"),
                    self._api_payload(misc_amount=bad, misc_note="Tip"),
                    content_type="application/json",
                )

                self.assertEqual(response.status_code, 400)
                self.assertIn("misc_amount", response.json())

    def test_line_item_amount_never_500s(self):
        for bad in BAD_AMOUNTS:
            with self.subTest(item_amount=bad):
                payload = self._api_payload(items=[{"name": "Coffee", "amount": bad}])

                response = self.client.post(
                    api("expense-list"), payload, content_type="application/json"
                )

                self.assertEqual(response.status_code, 400)
                self.assertIn("items", response.json())

    def test_bad_spent_on_never_500s(self):
        for bad in ["not-a-date", "2026-02-30", "2026-13-01", "99999-01-01"]:
            with self.subTest(spent_on=bad):
                response = self.client.post(
                    api("expense-list"),
                    self._api_payload(spent_on=bad),
                    content_type="application/json",
                )

                self.assertEqual(response.status_code, 400)
                self.assertIn("spent_on", response.json())

    def test_item_share_weight_zero_never_500s(self):
        # The gap this pass fixed: 0 passed ItemShareSerializer's
        # auto-generated min_value=0, then hit the database's
        # CheckConstraint(weight__gt=0) as an uncaught IntegrityError.
        payload = self._api_payload(
            items=[
                {
                    "name": "Coffee",
                    "amount": "10.00",
                    "shares": [{"participant": self.person.pk, "weight": 0}],
                }
            ]
        )

        response = self.client.post(api("expense-list"), payload, content_type="application/json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("items", response.json())
        self.assertFalse(Expense.objects.exists())

    def test_item_share_weight_beyond_the_column_never_500s(self):
        # The other half of the same gap: the auto-generated field allowed
        # any 64-bit value, but the column is a 16-bit smallint.
        payload = self._api_payload(
            items=[
                {
                    "name": "Coffee",
                    "amount": "10.00",
                    "shares": [{"participant": self.person.pk, "weight": 99999}],
                }
            ]
        )

        response = self.client.post(api("expense-list"), payload, content_type="application/json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("items", response.json())
        self.assertFalse(Expense.objects.exists())
