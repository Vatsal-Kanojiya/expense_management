from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.db import models, transaction

from .deletion import delete_account

User = get_user_model()


class SignUpForm(UserCreationForm):
    """Registration form for the project's custom user model.

    Subclassing UserCreationForm rather than writing one from scratch keeps
    Django's password handling: the two password fields, the confirmation
    match, AUTH_PASSWORD_VALIDATORS, and set_password() hashing on save.
    A hand-rolled ModelForm over `password` would store it in clear text.

    Overriding Meta.model is mandatory and easy to miss: UserCreationForm's
    own Meta points at django.contrib.auth.models.User, so inheriting it
    unchanged silently writes to the wrong table on a project with a custom
    user model.
    """

    email = forms.EmailField(
        required=True,
        help_text="Used to reset your password, so it must be reachable.",
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")

    @staticmethod
    def _held_by_verified_account(**lookup):
        """Whether `lookup` (a username or an email) belongs to a real account.

        Roadmap A1: a sign-up used to be refused for any matching row, so
        an account that never verified could squat an address forever and
        lock its real owner out of registering. An "unverified" row --
        is_active=False and email_verified_at still null -- is about to be
        replaced by this sign-up (see save(), below), so it does not count
        as held.
        """
        user = User.objects.filter(**lookup).first()
        if user is None:
            return False
        return user.is_active or user.email_verified_at is not None

    def clean_username(self):
        username = self.cleaned_data["username"]

        if self._held_by_verified_account(username=username):
            raise forms.ValidationError("A user with that username already exists.")

        return username

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()

        # Normalising to lowercase first stops Alice@example.com and
        # alice@example.com being two accounts, which the database would
        # happily allow (email__iexact matches either casing).
        if self._held_by_verified_account(email__iexact=email):
            raise forms.ValidationError("An account with this email already exists.")

        return email

    def validate_unique(self):
        """No-op: clean_username/clean_email above already did this check.

        ModelForm's default validate_unique() would otherwise re-run the
        plain unique=True check against the database and block on *any*
        matching row -- including the unverified one save() is about to
        delete -- undoing the point of overriding the two clean_* methods.
        """

    @transaction.atomic
    def save(self, commit=True):
        """Create the account, first clearing out anyone squatting on it.

        Atomic: a half-finished replacement -- old account gone, new one
        not yet created -- would leave the address or username reachable
        by neither the impostor nor the real owner.
        """
        email = self.cleaned_data.get("email")
        username = self.cleaned_data.get("username")

        squatters = User.objects.filter(
            models.Q(email__iexact=email) | models.Q(username=username),
            is_active=False,
            email_verified_at__isnull=True,
        )
        for squatter in squatters:
            delete_account(squatter)

        return super().save(commit=commit)
