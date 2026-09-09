from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """Project user.

    Deliberately empty for now. The point is the seam: swapping
    AUTH_USER_MODEL after migrations exist is one of Django's genuinely
    painful migrations, so the custom model is introduced up front and
    extended later without a schema swap.
    """

    pass
