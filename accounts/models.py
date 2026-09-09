from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Project user.

    Extends AbstractUser rather than AbstractBaseUser: the username,
    password, permissions and staff flags are all wanted as-is, so there is
    no reason to rebuild them.

    The only override is email. AbstractUser declares it blank and
    non-unique, which breaks password reset — the reset form looks users up
    by email, so a blank or duplicated address means either no match or an
    ambiguous one. Making it required and unique is what turns
    "reset my password" into a reliable flow rather than a best-effort one.
    """

    email = models.EmailField(
        "email address",
        unique=True,
        help_text="Used to sign in to support and to reset your password.",
    )

    # AbstractUser already sets REQUIRED_FIELDS = ["email"], so createsuperuser
    # prompts for it. Restated here only because the guarantee now matters.
    REQUIRED_FIELDS = ["email"]
