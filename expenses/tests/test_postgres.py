"""Behaviour that only exists on Postgres.

Skipped entirely on SQLite rather than faked, because a test that passes by
not running on the backend it describes is worse than no test. Run them
with:

    DATABASE_URL=postgres://... python manage.py test expenses.tests.test_postgres
"""

import unittest
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.urls import reverse

from expenses.models import Category, Expense

User = get_user_model()

postgres_only = unittest.skipUnless(
    connection.vendor == "postgresql", "Full-text search is a Postgres feature"
)


@postgres_only
class FullTextSearchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            "alice", email="alice@example.com", password="pw12345!"
        )
        cls.category = Category.objects.create(user=cls.alice, name="Food")
        cls.dinner = Expense.objects.create(
            user=cls.alice,
            category=cls.category,
            amount=Decimal("900.00"),
            # today(), because the list view's date range defaults to the
            # current month and would otherwise filter this row out before
            # search ever ran.
            spent_on=date.today(),
            note="Team dinner at the airport",
        )

    def setUp(self):
        self.client.force_login(self.alice)

    def _search(self, term):
        return self.client.get(reverse("expenses:expense_list"), {"search": term})

    def test_a_whole_word_matches(self):
        self.assertEqual(len(self._search("dinner").context["expenses"]), 1)

    def test_stemming_matches_a_different_form_of_the_word(self):
        # The thing LIKE cannot do. "dinners" finds "dinner" because the
        # english configuration stems both to the same lexeme.
        self.assertEqual(len(self._search("dinners").context["expenses"]), 1)

    def test_a_fragment_no_longer_matches(self):
        """The cost of the trade, asserted rather than left as a surprise.

        icontains would find "dinner" inside a search for "inn". Full-text
        search indexes lexemes, not substrings, so it does not. That is the
        price of an index a leading-wildcard LIKE can never use.
        """
        self.assertEqual(len(self._search("inn").context["expenses"]), 0)

    def test_stop_words_match_nothing_on_their_own(self):
        # "at" and "the" are not indexed by the english configuration.
        self.assertEqual(len(self._search("the").context["expenses"]), 0)

    def test_the_index_expression_matches_the_query_expression(self):
        """The silent failure this guards against.

        to_tsvector(note) and to_tsvector('english', note) are different
        expressions. An index on one is invisible to the other, and the
        query still returns correct results -- just via a sequential scan,
        with nothing to indicate the index was skipped.
        """
        with connection.cursor() as cursor:
            cursor.execute("SELECT indexdef FROM pg_indexes WHERE indexname = 'expense_note_fts'")
            definition = cursor.fetchone()[0]

        # Postgres casts the varchar column, so the stored definition reads
        # to_tsvector('english'::regconfig, (note)::text).
        self.assertIn("to_tsvector('english'::regconfig", definition)
        self.assertIn("gin", definition.lower())


@postgres_only
class IndexPresenceTests(TestCase):
    def test_the_composite_index_exists_with_its_columns_in_order(self):
        # Equality columns first, range column last. Reversed, the category
        # equality could not be used at all.
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT indexdef FROM pg_indexes WHERE indexname = 'expense_user_cat_date'"
            )
            definition = cursor.fetchone()[0]

        self.assertIn("(user_id, category_id, spent_on)", definition)

    def test_the_case_insensitive_constraint_is_a_functional_index(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT indexdef FROM pg_indexes WHERE indexname = 'uniq_category_name_per_user_ci'"
            )
            definition = cursor.fetchone()[0]

        self.assertIn("UNIQUE", definition)
        self.assertIn("lower((name", definition.lower())
