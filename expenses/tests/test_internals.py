"""Middleware, template tags and the context processor."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from config.middleware import get_request_id
from expenses.templatetags.money import owed_label, rupees

User = get_user_model()


class RequestIDTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            "alice", email="alice@example.com", password="pw12345!"
        )

    def test_every_response_carries_an_id(self):
        response = self.client.get(reverse("accounts:login"))

        self.assertTrue(response["X-Request-ID"])

    def test_an_inbound_id_is_honoured(self):
        # So an id set by a load balancer survives into these logs, which
        # is what makes it useful across service boundaries.
        response = self.client.get(reverse("accounts:login"), HTTP_X_REQUEST_ID="from-upstream")

        self.assertEqual(response["X-Request-ID"], "from-upstream")

    def test_an_oversized_inbound_id_is_truncated(self):
        # The value is only ever logged, never looked up, but an unbounded
        # header would let anyone write arbitrarily long lines into the log.
        response = self.client.get(reverse("accounts:login"), HTTP_X_REQUEST_ID="x" * 500)

        self.assertEqual(len(response["X-Request-ID"]), 64)

    def test_two_requests_get_different_ids(self):
        first = self.client.get(reverse("accounts:login"))["X-Request-ID"]
        second = self.client.get(reverse("accounts:login"))["X-Request-ID"]

        self.assertNotEqual(first, second)

    def test_the_id_does_not_outlive_the_request(self):
        self.client.get(reverse("accounts:login"))

        # Reset in a finally block, so a view that raised cannot leave its
        # id labelling whatever the worker handles next.
        self.assertEqual(get_request_id(), "-")


class RupeesFilterTests(TestCase):
    def test_indian_digit_grouping(self):
        # Not what a locale-free formatter produces: the last three digits
        # group together and everything above groups in twos.
        self.assertEqual(rupees(Decimal("1234567")), "₹12,34,567.00")

    def test_small_amounts_are_ungrouped(self):
        self.assertEqual(rupees(Decimal("150")), "₹150.00")

    def test_exactly_four_digits(self):
        self.assertEqual(rupees(Decimal("1000")), "₹1,000.00")

    def test_five_digits(self):
        self.assertEqual(rupees(Decimal("99999.5")), "₹99,999.50")

    def test_paise_are_always_shown(self):
        self.assertEqual(rupees(Decimal("150")), "₹150.00")
        self.assertEqual(rupees(Decimal("150.5")), "₹150.50")

    def test_negatives_keep_their_sign_outside_the_symbol(self):
        self.assertEqual(rupees(Decimal("-1234567")), "-₹12,34,567.00")

    def test_none_is_an_em_dash_not_a_zero(self):
        # "nothing" and "zero" are different statements about money.
        self.assertEqual(rupees(None), "—")
        self.assertEqual(rupees(Decimal("0")), "₹0.00")

    def test_junk_is_returned_unchanged_rather_than_raising(self):
        # A filter that raises takes the whole page with it.
        self.assertEqual(rupees("not a number"), "not a number")


class OwedLabelTests(TestCase):
    def test_no_count_is_a_plain_label(self):
        self.assertEqual(owed_label(None), "Balances")
        self.assertEqual(owed_label(0), "Balances")

    def test_a_count_is_shown(self):
        self.assertEqual(owed_label(3), "Balances (3)")


class ContextProcessorTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            "alice", email="alice@example.com", password="pw12345!"
        )

    def test_anonymous_requests_get_nothing(self):
        response = self.client.get(reverse("accounts:login"))

        self.assertIsNone(response.context.get("nav_owed_count"))

    def test_it_never_issues_a_query(self):
        self.client.force_login(self.alice)

        # Five: session, user, the empty list's pagination count and rows,
        # and the category dropdown. None of them belong to the context
        # processor, which is the whole point -- a cache miss means no
        # badge, not a computation. It runs on every render in the project.
        with self.assertNumQueries(5):
            self.client.get(reverse("expenses:expense_list"))
