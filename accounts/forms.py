from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

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

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()

        # The model has unique=True as the guarantee; this turns the would-be
        # IntegrityError into a field error. Normalising to lowercase first
        # stops Alice@example.com and alice@example.com being two accounts,
        # which the database would happily allow.
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")

        return email
