from django.conf import settings
from django.test.runner import DiscoverRunner


class FastTestRunner(DiscoverRunner):
    """Test runner that swaps the password hasher for a fast one.

    Django's default PBKDF2 hasher is deliberately slow — that slowness is
    the security property, since it is what makes brute-forcing a stolen
    password database expensive. In tests it buys nothing and costs
    everything: every create_user and every login pays the same price.

    On this suite that is 20.5s versus 0.5s, a 40x difference, and it grows
    with every test that touches a user.

    MD5 is used here *only* because it is fast and this runner is never
    active outside the test process. Never put this in settings.PASSWORD_HASHERS.

    The alternative is a settings split (config/settings/test.py). This is
    the lighter option while the project has a single settings module.
    """

    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
