"""Categories, people and expenses at parity with the pages (phase 20.4)."""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from expenses.models import Category, Expense, ExpenseItem, ItemShare, Participant

User = get_user_model()


def url(name, *args):
    return reverse(f"api:v1:{name}", args=args)


class ResourceTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", "alice@example.com", "pw-Alice-123")
        cls.bob = User.objects.create_user("bob", "bob@example.com", "pw-Bob-12345")
        cls.me = Participant.get_or_create_self(cls.alice)
        cls.food = Category.objects.create(user=cls.alice, name="Food")
        cls.travel = Category.objects.create(user=cls.alice, name="Travel")
        cls.rahul = Participant.objects.create(user=cls.alice, name="Rahul")
        cls.priya = Participant.objects.create(user=cls.alice, name="Priya")

    def setUp(self):
        self.client.force_login(self.alice)

    def expense(self, amount, day, category=None, note=""):
        return Expense.objects.create(
            user=self.alice,
            category=category or self.food,
            amount=Decimal(amount),
            spent_on=day,
            note=note,
        )

    def post(self, name, data, *args):
        return self.client.post(url(name, *args), data, content_type="application/json")

    def patch(self, name, data, *args):
        return self.client.patch(url(name, *args), data, content_type="application/json")


class CategoryTests(ResourceTestCase):
    def test_the_list_carries_the_pages_usage_columns(self):
        self.expense("100", date(2026, 3, 1))
        self.expense("50", date(2026, 3, 9))

        rows = {row["name"]: row for row in self.client.get(url("category-list")).json()["results"]}

        self.assertEqual(rows["Food"]["expense_count"], 2)
        self.assertEqual(rows["Food"]["total"], "150.00")
        self.assertEqual(
            (rows["Food"]["last_spent_on"], rows["Food"]["last_amount"]), ("2026-03-09", "50.00")
        )
        self.assertEqual((rows["Travel"]["expense_count"], rows["Travel"]["total"]), (0, None))

    def test_a_create_answers_with_the_same_shape_as_a_get(self):
        body = self.post("category-list", {"name": "Rent"}).json()

        self.assertEqual((body["expense_count"], body["total"]), (0, None))


class ParticipantTests(ResourceTestCase):
    def test_yourself_is_listed_and_marked(self):
        rows = self.client.get(url("participant-list")).json()["results"]

        self.assertEqual([row["name"] for row in rows if row["is_self"]], [self.me.name])

    def test_yourself_cannot_be_renamed_or_deleted(self):
        rename = self.patch("participant-detail", {"name": "Rahul's friend"}, self.me.pk)
        delete = self.client.delete(url("participant-detail", self.me.pk))

        self.assertEqual((rename.status_code, delete.status_code), (403, 403))
        self.assertEqual(rename.json()["code"], "self_participant")
        self.me.refresh_from_db()
        self.assertFalse(self.me.name.startswith("Rahul"))

    def test_other_people_can_be_renamed(self):
        response = self.patch("participant-detail", {"name": "Rahul K"}, self.rahul.pk)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["shared_count"], 0)


class ExpenseListTests(ResourceTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.march = Expense.objects.create(
            user=cls.alice,
            category=cls.food,
            amount=Decimal("100"),
            spent_on=date(2026, 3, 5),
            note="Dinner",
        )
        cls.april = Expense.objects.create(
            user=cls.alice,
            category=cls.travel,
            amount=Decimal("40"),
            spent_on=date(2026, 4, 2),
            note="Taxi",
        )
        cls.may = Expense.objects.create(
            user=cls.alice,
            category=cls.food,
            amount=Decimal("60"),
            spent_on=date(2026, 5, 20),
            note="Lunch",
        )

    def ids(self, query=""):
        return [row["id"] for row in self.client.get(url("expense-list") + query).json()["results"]]

    def test_all_time_newest_date_first(self):
        self.assertEqual(self.ids(), [self.may.pk, self.april.pk, self.march.pk])

    def test_the_pages_filters(self):
        self.assertEqual(self.ids("?start=2026-04-01"), [self.may.pk, self.april.pk])
        self.assertEqual(self.ids("?end=2026-04-30"), [self.april.pk, self.march.pk])
        self.assertEqual(self.ids(f"?category={self.food.pk}"), [self.may.pk, self.march.pk])
        self.assertEqual(self.ids("?search=taxi"), [self.april.pk])

    def test_count_and_total_cover_every_page(self):
        body = self.client.get(url("expense-list") + f"?category={self.food.pk}&page_size=1").json()

        self.assertEqual(len(body["results"]), 1)
        self.assertEqual((body["count"], body["total_amount"]), (2, "160.00"))
        self.assertIsNotNone(body["next"])

    def test_a_bad_filter_is_a_400_naming_it(self):
        bad_date = self.client.get(url("expense-list") + "?start=banana")
        their_category = Category.objects.create(user=self.bob, name="Theirs")
        not_mine = self.client.get(url("expense-list") + f"?category={their_category.pk}")

        self.assertEqual(bad_date.status_code, 400)
        self.assertIn("start", bad_date.json())
        self.assertEqual(not_mine.status_code, 400)

    def test_filters_never_hide_a_single_expense(self):
        response = self.client.get(url("expense-detail", self.march.pk) + "?start=2030-01-01")

        self.assertEqual(response.status_code, 200)

    def test_rows_are_readable_without_lookups(self):
        row = self.client.get(url("expense-detail", self.march.pk)).json()

        self.assertEqual((row["category_name"], row["paid_by_name"]), ("Food", self.me.name))
        # Not itemised: nothing to reconcile.
        self.assertEqual(
            (row["items_total"], row["unaccounted_amount"], row["is_balanced"]), (None, None, True)
        )


class ExpenseRuleTests(ResourceTestCase):
    """Issue 45: the web form's rules, now also at the API."""

    base = {"amount": "300.00", "spent_on": "2026-06-01", "note": "Dinner"}

    def payload(self, **extra):
        return {**self.base, "category": self.food.pk, **extra}

    def test_a_misc_amount_needs_a_description(self):
        response = self.post(
            "expense-list",
            self.payload(misc_amount="30.00", items=[{"name": "Pizza", "amount": "270.00"}]),
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("misc_note", response.json())

    def test_a_misc_amount_needs_line_items(self):
        response = self.post("expense-list", self.payload(misc_amount="30.00", misc_note="Tip"))

        self.assertEqual(response.status_code, 400)
        self.assertIn("misc_amount", response.json())

    def test_a_misc_amount_on_a_patch_is_judged_with_the_saved_items(self):
        expense = self.expense("300", date(2026, 6, 1))
        ExpenseItem.objects.create(expense=expense, name="Pizza", amount=Decimal("270"))

        response = self.patch(
            "expense-detail", {"misc_amount": "30.00", "misc_note": "Tip"}, expense.pk
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["is_balanced"])

    def test_without_you_every_line_must_say_who_had_it(self):
        response = self.post(
            "expense-list",
            self.payload(
                include_self=False,
                participants=[self.rahul.pk],
                items=[
                    {
                        "name": "Pizza",
                        "amount": "200.00",
                        "shares": [{"participant": self.rahul.pk}],
                    },
                    {"name": "Coke", "amount": "100.00"},
                ],
            ),
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["items"][0], {})
        self.assertIn("shares", response.json()["items"][1])

    def test_line_item_people_join_the_expense(self):
        response = self.post(
            "expense-list",
            self.payload(
                participants=[self.rahul.pk],
                items=[
                    {"name": "Wine", "amount": "300.00", "shares": [{"participant": self.priya.pk}]}
                ],
            ),
        )

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(
            set(response.json()["participants"]), {self.rahul.pk, self.priya.pk, self.me.pk}
        )

    def test_a_patch_of_items_extends_the_saved_participants(self):
        expense = self.expense("300", date(2026, 6, 1))
        expense.participants.set([self.rahul])

        self.patch(
            "expense-detail",
            {
                "items": [
                    {"name": "Wine", "amount": "300.00", "shares": [{"participant": self.priya.pk}]}
                ]
            },
            expense.pk,
        )

        # And you, through include_self, the API's documented default (D25).
        self.assertEqual(set(expense.participants.all()), {self.rahul, self.priya, self.me})

    def test_an_expense_that_does_not_add_up_says_so(self):
        response = self.post(
            "expense-list", self.payload(items=[{"name": "Pizza", "amount": "200.00"}])
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            (response.json()["unaccounted_amount"], response.json()["is_balanced"]),
            ("100.00", False),
        )


class SplitTests(ResourceTestCase):
    def test_the_split_tab_as_data(self):
        expense = self.expense("300", date(2026, 6, 1))
        expense.participants.set([self.me, self.rahul])
        pizza = ExpenseItem.objects.create(expense=expense, name="Pizza", amount=Decimal("200"))
        ItemShare.objects.create(item=pizza, participant=self.me)
        ItemShare.objects.create(item=pizza, participant=self.rahul)
        ExpenseItem.objects.create(expense=expense, name="Coke", amount=Decimal("100"))

        body = self.client.get(url("expense-split", expense.pk)).json()

        rows = {row["participant"]["name"]: row["total"] for row in body["rows"]}
        self.assertEqual(rows, {self.me.name: "200.00", "Rahul": "100.00"})
        self.assertTrue(body["rows"][0]["participant"]["is_self"])
        self.assertEqual((body["is_balanced"], body["grand_total"]), (True, "300.00"))

    def test_an_expense_that_does_not_add_up_has_no_rows(self):
        expense = self.expense("300", date(2026, 6, 1))
        ExpenseItem.objects.create(expense=expense, name="Pizza", amount=Decimal("100"))

        body = self.client.get(url("expense-split", expense.pk)).json()

        self.assertEqual(
            (body["is_balanced"], body["rows"], body["unaccounted_amount"]), (False, [], "200.00")
        )

    def test_someone_elses_expense_is_a_404(self):
        theirs = Expense.objects.create(
            user=self.bob,
            category=Category.objects.create(user=self.bob, name="Theirs"),
            amount=Decimal("5"),
            spent_on=date(2026, 1, 1),
        )

        self.assertEqual(self.client.get(url("expense-split", theirs.pk)).status_code, 404)
