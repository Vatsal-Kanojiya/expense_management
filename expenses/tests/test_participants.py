"""Participant CRUD, and the ownership boundary around it.

The scoping assertions here duplicate the shape of test_permissions.py on
purpose. Every new owner-scoped model has to prove the boundary again: the
mixin makes it easy to get right, not automatic.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from expenses.models import Category, Expense, ExpenseItem, ItemShare, Participant

User = get_user_model()


class ParticipantViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            "alice", email="alice@example.com", password="pw12345!"
        )
        cls.bob = User.objects.create_user("bob", email="bob@example.com", password="pw12345!")
        cls.rahul = Participant.objects.create(user=cls.alice, name="Rahul")

    def setUp(self):
        self.client.force_login(self.alice)

    def test_the_list_shows_only_your_people(self):
        Participant.objects.create(user=self.bob, name="Someone else")

        response = self.client.get(reverse("expenses:participant_list"))

        self.assertContains(response, "Rahul")
        self.assertNotContains(response, "Someone else")

    def test_creating_assigns_the_logged_in_user(self):
        self.client.post(reverse("expenses:participant_create"), {"name": "Priya"})

        self.assertEqual(Participant.objects.get(name="Priya").user, self.alice)

    def test_a_duplicate_name_is_a_field_error_not_a_500(self):
        # Case-insensitive, matching clean_name. The DB constraint is exact
        # match, so the form is stricter than the schema here -- the same
        # mismatch logged as known issue 11 for categories.
        response = self.client.post(reverse("expenses:participant_create"), {"name": "rahul"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already have someone with this name")

    def test_two_users_may_both_add_a_rahul(self):
        self.client.force_login(self.bob)

        self.client.post(reverse("expenses:participant_create"), {"name": "Rahul"})

        self.assertEqual(Participant.objects.filter(name="Rahul").count(), 2)

    def test_you_cannot_edit_someone_elses_person(self):
        theirs = Participant.objects.create(user=self.bob, name="Theirs")

        response = self.client.get(reverse("expenses:participant_update", args=[theirs.pk]))

        self.assertEqual(response.status_code, 404)

    def test_you_cannot_delete_someone_elses_person(self):
        theirs = Participant.objects.create(user=self.bob, name="Theirs")

        response = self.client.post(reverse("expenses:participant_delete", args=[theirs.pk]))

        self.assertEqual(response.status_code, 404)
        self.assertTrue(Participant.objects.filter(pk=theirs.pk).exists())

    def test_anonymous_users_are_redirected(self):
        self.client.logout()

        response = self.client.get(reverse("expenses:participant_list"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

    def test_deleting_someone_on_a_line_item_is_refused_with_a_message(self):
        category = Category.objects.create(user=self.alice, name="Food")
        expense = Expense.objects.create(
            user=self.alice, category=category, amount="300.00", spent_on="2026-01-15"
        )
        item = ExpenseItem.objects.create(expense=expense, name="Pizza", amount="300.00")
        ItemShare.objects.create(item=item, participant=self.rahul)

        response = self.client.post(
            reverse("expenses:participant_delete", args=[self.rahul.pk]), follow=True
        )

        # ProtectedError becomes a message, not a 500.
        self.assertContains(response, "cannot be removed")
        self.assertTrue(Participant.objects.filter(pk=self.rahul.pk).exists())

    def test_deleting_someone_on_an_even_split_succeeds(self):
        # The asymmetry, at the view layer: the generated join table cascades.
        category = Category.objects.create(user=self.alice, name="Food")
        expense = Expense.objects.create(
            user=self.alice, category=category, amount="300.00", spent_on="2026-01-15"
        )
        expense.participants.add(self.rahul)

        self.client.post(reverse("expenses:participant_delete", args=[self.rahul.pk]))

        self.assertFalse(Participant.objects.filter(pk=self.rahul.pk).exists())
        self.assertEqual(expense.participants.count(), 0)
