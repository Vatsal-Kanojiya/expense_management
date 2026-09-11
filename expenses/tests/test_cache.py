"""The cache, including the version of it that leaks other people's money.

Caching is off for the rest of the suite (see config/test_runner.py), so
every class here turns it back on explicitly. That is deliberate: a test
that caches by accident passes for a reason nobody chose.
"""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.views.decorators.cache import cache_page

from expenses.cache import bump_version, cached_summary, summary_key, version
from expenses.models import Category, Expense

User = get_user_model()

with_cache = override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "test-cache",
        }
    }
)


@with_cache
class CacheKeyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            "alice", email="alice@example.com", password="pw12345!"
        )
        cls.bob = User.objects.create_user("bob", email="bob@example.com", password="pw12345!")

    def setUp(self):
        cache.clear()

    def test_two_users_never_share_a_key(self):
        start, end = date(2026, 1, 1), date(2026, 1, 31)

        self.assertNotEqual(
            summary_key(self.alice.pk, start, end),
            summary_key(self.bob.pk, start, end),
        )

    def test_two_date_ranges_never_share_a_key(self):
        self.assertNotEqual(
            summary_key(self.alice.pk, date(2026, 1, 1), date(2026, 1, 31)),
            summary_key(self.alice.pk, date(2026, 2, 1), date(2026, 2, 28)),
        )

    def test_a_bump_changes_every_key_for_that_user_at_once(self):
        start, end = date(2026, 1, 1), date(2026, 1, 31)
        before = summary_key(self.alice.pk, start, end)

        bump_version(self.alice.pk)

        self.assertNotEqual(summary_key(self.alice.pk, start, end), before)

    def test_a_bump_does_not_touch_another_user(self):
        start, end = date(2026, 1, 1), date(2026, 1, 31)
        theirs = summary_key(self.bob.pk, start, end)

        bump_version(self.alice.pk)

        self.assertEqual(summary_key(self.bob.pk, start, end), theirs)

    def test_bumping_an_uncached_user_is_not_an_error(self):
        # cache.incr raises when the key is absent. Nothing cached means
        # nothing to invalidate, which is a no-op and not a failure.
        cache.clear()

        bump_version(self.alice.pk)

        self.assertEqual(version(self.alice.pk), 1)


@with_cache
class CachedSummaryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            "alice", email="alice@example.com", password="pw12345!"
        )

    def setUp(self):
        cache.clear()
        self.calls = 0

    def _build(self):
        self.calls += 1
        return {"total": Decimal("100.00")}

    def test_the_second_call_does_not_rebuild(self):
        start, end = date(2026, 1, 1), date(2026, 1, 31)

        cached_summary(self.alice, start, end, self._build)
        cached_summary(self.alice, start, end, self._build)

        self.assertEqual(self.calls, 1)

    def test_a_bump_forces_a_rebuild(self):
        start, end = date(2026, 1, 1), date(2026, 1, 31)
        cached_summary(self.alice, start, end, self._build)

        bump_version(self.alice.pk)
        cached_summary(self.alice, start, end, self._build)

        self.assertEqual(self.calls, 2)


@with_cache
class DashboardCacheTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            "alice", email="alice@example.com", password="pw12345!"
        )
        cls.category = Category.objects.create(user=cls.alice, name="Food")

    def setUp(self):
        cache.clear()
        self.client.force_login(self.alice)

    def _expense(self, amount):
        return Expense.objects.create(
            user=self.alice,
            category=self.category,
            amount=Decimal(amount),
            spent_on=date.today(),
        )

    def test_a_second_view_costs_fewer_queries(self):
        self._expense("100.00")

        first = len(self._queries_for_dashboard())
        second = len(self._queries_for_dashboard())

        self.assertLess(second, first)

    def _queries_for_dashboard(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as captured:
            self.client.get(reverse("expenses:dashboard"))
        return list(captured)

    def test_adding_an_expense_through_the_app_updates_the_dashboard(self):
        self._expense("100.00")
        self.client.get(reverse("expenses:dashboard"))

        self.client.post(
            reverse("expenses:expense_create"),
            {
                "category": self.category.pk,
                "amount": "50.00",
                "spent_on": date.today().isoformat(),
                "note": "",
                "items-TOTAL_FORMS": "0",
                "items-INITIAL_FORMS": "0",
                "items-MIN_NUM_FORMS": "0",
                "items-MAX_NUM_FORMS": "1000",
            },
        )
        response = self.client.get(reverse("expenses:dashboard"))

        self.assertEqual(response.context["summary"].total, Decimal("150.00"))

    def test_a_write_that_bypasses_the_app_still_invalidates(self):
        """Known issue 26, closed by a signal rather than more call sites.

        Phase 14 invalidated explicitly in the views and the API, and this
        test asserted the opposite of what it asserts now: a row written
        straight to the ORM -- as the admin, a shell session or a data
        migration would -- left the dashboard serving the old number.

        A post_save receiver closed it. The argument for using a signal
        here, and against using one for anything else in this project, is
        in expenses/signals.py.
        """
        self._expense("100.00")
        self.client.get(reverse("expenses:dashboard"))

        self._expense("50.00")  # straight to the ORM, as the admin would

        response = self.client.get(reverse("expenses:dashboard"))
        self.assertEqual(response.context["summary"].total, Decimal("150.00"))

    def test_bulk_create_does_not_fire_the_signal(self):
        """The limit of the signal approach, asserted rather than assumed.

        bulk_create operates on rows, not instances, so there is no
        instance to signal about. This is Django's documented behaviour and
        not a bug, but it means a bulk write still needs an explicit bump.
        """
        self._expense("100.00")
        self.client.get(reverse("expenses:dashboard"))

        Expense.objects.bulk_create(
            [
                Expense(
                    user=self.alice,
                    category=self.category,
                    amount=Decimal("50.00"),
                    spent_on=date.today(),
                )
            ]
        )

        response = self.client.get(reverse("expenses:dashboard"))
        self.assertEqual(response.context["summary"].total, Decimal("100.00"))


@with_cache
class CachePageLeaksTests(TestCase):
    """Why @cache_page is not on the dashboard.

    Built here, demonstrated leaking, and rejected. The decorator keys on
    the URL and nothing else, so every signed-in user asking for the same
    path gets whatever the first one put there.
    """

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            "alice", email="alice@example.com", password="pw12345!"
        )
        cls.bob = User.objects.create_user("bob", email="bob@example.com", password="pw12345!")

    def setUp(self):
        cache.clear()

    def test_cache_page_serves_one_users_response_to_another(self):
        from django.http import HttpResponse

        seen = []

        @cache_page(60)
        def whose_money(request):
            seen.append(request.user.username)
            return HttpResponse(f"secret total for {request.user.username}")

        from django.test import RequestFactory

        factory = RequestFactory()

        first = factory.get("/whose-money/")
        first.user = self.alice
        whose_money(first)

        second = factory.get("/whose-money/")
        second.user = self.bob
        response = whose_money(second)

        # Bob is served Alice's page. The view never even ran for him.
        self.assertIn("alice", response.content.decode())
        self.assertEqual(seen, ["alice"])

    def test_the_real_dashboard_does_not_do_this(self):
        self.client.force_login(self.alice)
        Category.objects.create(user=self.alice, name="Food")
        Expense.objects.create(
            user=self.alice,
            category=Category.objects.get(user=self.alice),
            amount=Decimal("100.00"),
            spent_on=date.today(),
        )
        self.client.get(reverse("expenses:dashboard"))

        self.client.force_login(self.bob)
        response = self.client.get(reverse("expenses:dashboard"))

        self.assertEqual(response.context["summary"].total, Decimal("0"))
