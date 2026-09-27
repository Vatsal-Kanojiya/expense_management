"""Security pass 6 (docs/HANDOVER.md): what goes in, and what comes back out.

Four items, checked one by one, in the order HANDOVER.md lists them.

Item 1, amounts and numbers: every money field must reject a bad value
with a form or serializer error, on the web and the API, never a 500.
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
by stating the field's real bounds (1 to 32767) explicitly.

Item 2, text shown on pages: a grep of every template and every app's
Python turns up no ``|safe``, ``mark_safe`` or ``SafeString`` anywhere,
and the one ``{% autoescape off %}`` in the project is the plain-text
password-reset email, which is never rendered as HTML. Nothing in the
project embeds JSON into a page either, so there is nothing for
``json_script`` to apply to. This item needed no fix -- the tests below
both pin the grep itself (so a future ``|safe`` cannot creep back in
unnoticed) and confirm the escaping it implies on every page that shows
user-entered text: category and participant names, an expense's note,
and a bill scan's merchant name.

Item 3, redirects: the only two places anything in the app redirects to a
caller-supplied URL are login and logout, and both go through Django's
own ``LoginView``/``LogoutView`` (via ``RedirectURLMixin``), which already
checks ``next`` against ``url_has_allowed_host_and_scheme`` before
honouring it (read directly from the installed Django source, not
assumed). Every other redirect in the project's own views is to a fixed,
named route -- confirmed by grepping every ``redirect(`` call in
``accounts/`` and ``expenses/``. This item needed no fix either; an
earlier pass (``test_auth_flows.py``) already pinned the ordinary login
case. The tests below extend that to logout, to a scheme-relative and a
``javascript:`` URL, and confirm a same-site ``next`` still works.
"""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from expenses.models import BillScan, Category, Expense, ExpenseItem, Participant
from expenses.tests.helpers import item_formset

User = get_user_model()
PASSWORD = "Str0ng-Enough-Pass"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


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


# --- 2. Text shown on pages is always escaped -------------------------------


PAYLOAD = '<script>alert("xss")</script>'
ESCAPED = "&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;"


class NoUnsafeTemplateConstructsTests(SimpleTestCase):
    """Nothing in the app defeats Django's autoescaping.

    A single ``|safe``, ``mark_safe`` or ``{% autoescape off %}`` around
    user-entered text would make every test below pass for the wrong
    reason, so this checks the source directly rather than only the
    rendered output.
    """

    def test_no_unsafe_filters_or_tags_outside_the_plain_text_email(self):
        import pathlib

        root = pathlib.Path(__file__).resolve().parent.parent.parent
        # Only the application's own code and templates -- not docs/, which
        # discusses these constructs in prose without using any of them.
        source_dirs = ["templates", "expenses", "accounts", "config"]
        offenders = []

        for source_dir in source_dirs:
            for pattern in ("**/*.html", "**/*.py"):
                for path in (root / source_dir).glob(pattern):
                    if (
                        ".venv" in path.parts
                        or "/tests/" in str(path)
                        or "migrations" in path.parts
                    ):
                        continue
                    text = path.read_text(encoding="utf-8", errors="ignore")
                    for needle in ("|safe", "mark_safe", "SafeString", "SafeText"):
                        if needle in text:
                            offenders.append(f"{path}: {needle}")
                    if "autoescape off" in text and path.name != "password_reset_email.html":
                        offenders.append(f"{path}: autoescape off")

        self.assertEqual(offenders, [])


class TextEscapingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", "alice@example.com", PASSWORD)

    def setUp(self):
        self.client.force_login(self.alice)

    def test_category_name_is_escaped_on_the_category_list(self):
        Category.objects.create(user=self.alice, name=PAYLOAD)

        response = self.client.get(reverse("expenses:category_list"))

        self.assertNotContains(response, PAYLOAD, html=False)
        self.assertContains(response, ESCAPED, html=False)

    def test_participant_name_is_escaped_on_the_people_and_balance_pages(self):
        Participant.objects.create(user=self.alice, name=PAYLOAD)

        for view_name in ("expenses:participant_list", "expenses:balances"):
            with self.subTest(view=view_name):
                response = self.client.get(reverse(view_name))

                self.assertNotContains(response, PAYLOAD, html=False)

    def test_expense_note_is_escaped_on_the_expense_list(self):
        category = Category.objects.create(user=self.alice, name="Food")
        Expense.objects.create(
            user=self.alice,
            category=category,
            amount=Decimal("10.00"),
            spent_on=date(2026, 9, 1),
            note=PAYLOAD,
        )

        response = self.client.get(reverse("expenses:expense_list"))

        self.assertNotContains(response, PAYLOAD, html=False)
        self.assertContains(response, ESCAPED, html=False)

    def test_bill_scan_merchant_is_escaped_on_the_review_page(self):
        category = Category.objects.create(user=self.alice, name="Food")
        scan = BillScan.objects.create(
            user=self.alice,
            image=SimpleUploadedFile("a.png", PNG, content_type="image/png"),
            status=BillScan.Status.DONE,
            result={
                "merchant": PAYLOAD,
                "total": "10.00",
                "tax": "0",
                "lines": [],
                "category_hint": "",
            },
        )

        response = self.client.get(reverse("expenses:bill_review", args=[scan.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, PAYLOAD, html=False)
        del category  # only needed so the review page has a category to offer


class LoginPageReflectionTests(TestCase):
    def test_the_next_field_cannot_break_out_of_its_attribute(self):
        # A ?next= holding a quote must not let a crafted value close the
        # hidden input's attribute and inject markup beside it.
        response = self.client.get(f"{reverse('accounts:login')}?next=%22><script>evil()</script>")

        self.assertNotContains(response, "<script>evil()</script>", html=False)


# --- 3. Redirects: a caller-supplied URL never leaves the site --------------


class RedirectGuardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", "alice@example.com", PASSWORD)

    def test_login_ignores_an_off_site_next_and_uses_the_default(self):
        for evil in (
            "https://evil.example.com/",
            "//evil.example.com/",
            "javascript:alert(1)",
        ):
            with self.subTest(next=evil):
                response = self.client.post(
                    f"{reverse('accounts:login')}?next={evil}",
                    {"username": "alice", "password": PASSWORD},
                )

                self.assertRedirects(response, reverse("expenses:dashboard"))
                self.client.logout()

    def test_login_still_honours_a_same_site_next(self):
        target = reverse("expenses:category_list")

        response = self.client.post(
            f"{reverse('accounts:login')}?next={target}",
            {"username": "alice", "password": PASSWORD},
        )

        self.assertRedirects(response, target)

    def test_logout_ignores_an_off_site_next_and_uses_the_default(self):
        self.client.force_login(self.alice)

        response = self.client.post(f"{reverse('accounts:logout')}?next=https://evil.example.com/")

        # fetch_redirect_response=False: logout has already signed the
        # client out by this point, so following the redirect would hit
        # the dashboard as an anonymous user and 302 again to the login
        # page -- a fact about LoginRequiredMixin, not about this guard.
        self.assertRedirects(response, reverse("expenses:dashboard"), fetch_redirect_response=False)
