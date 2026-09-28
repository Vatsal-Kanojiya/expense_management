"""Roadmap A2: PwnedPasswordValidator (accounts/password_validation.py).

Every test here turns PWNED_PASSWORDS_ENABLED back on and mocks
requests.get -- the test runner (config/test_runner.py) turns the check
off everywhere else precisely so nothing makes a real network call.
"""

import hashlib
from unittest import mock

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, override_settings

from accounts.password_validation import PwnedPasswordValidator

enabled = override_settings(PWNED_PASSWORDS_ENABLED=True)


def fake_response(text, status_code=200):
    response = mock.Mock()
    response.text = text
    response.status_code = status_code
    response.raise_for_status = mock.Mock()
    if status_code >= 400:
        response.raise_for_status.side_effect = Exception("HTTP error")
    return response


class PwnedPasswordValidatorTests(SimpleTestCase):
    password = "correct horse battery staple"

    def _digest(self):
        return hashlib.sha1(self.password.encode()).hexdigest().upper()  # noqa: S324

    @enabled
    @mock.patch("accounts.password_validation.requests.get")
    def test_a_breached_password_is_rejected(self, mock_get):
        suffix = self._digest()[5:]
        mock_get.return_value = fake_response(f"{suffix}:37\r\nAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA:0")

        with self.assertRaises(ValidationError) as ctx:
            PwnedPasswordValidator().validate(self.password)

        self.assertEqual(ctx.exception.code, "password_breached")

    @enabled
    @mock.patch("accounts.password_validation.requests.get")
    def test_a_clean_password_is_accepted(self, mock_get):
        mock_get.return_value = fake_response(
            "0000000000000000000000000000AAAAA:0\r\n1111111111111111111111111111BBBBB:0"
        )

        PwnedPasswordValidator().validate(self.password)  # must not raise

    @enabled
    @mock.patch("accounts.password_validation.requests.get")
    def test_a_zero_count_line_is_padding_not_a_real_match(self, mock_get):
        # Add-Padding fills the response with extra lines whose count is 0
        # to obscure the real match count on the wire; a suffix that
        # happens to appear with count 0 must not be treated as a hit.
        suffix = self._digest()[5:]
        mock_get.return_value = fake_response(f"{suffix}:0")

        PwnedPasswordValidator().validate(self.password)  # must not raise

    @enabled
    @mock.patch("accounts.password_validation.requests.get", side_effect=Exception("boom"))
    def test_a_network_error_fails_open(self, mock_get):
        with self.assertLogs("accounts.password_validation", level="WARNING") as logs:
            PwnedPasswordValidator().validate(self.password)  # must not raise

        self.assertTrue(any("Pwned Passwords" in line for line in logs.output))
        self.assertNotIn(self.password, "".join(logs.output))

    @enabled
    @mock.patch("accounts.password_validation.requests.get")
    def test_only_five_characters_of_the_hash_are_sent(self, mock_get):
        mock_get.return_value = fake_response("")

        PwnedPasswordValidator().validate(self.password)

        requested_url = mock_get.call_args[0][0]
        prefix = self._digest()[:5]
        self.assertTrue(requested_url.endswith(f"/range/{prefix}"))
        # And nothing past the prefix -- the rest of the hash never
        # appears anywhere in the request.
        self.assertNotIn(self._digest()[5:], requested_url)

    @enabled
    @mock.patch("accounts.password_validation.requests.get")
    def test_sends_the_add_padding_header_and_a_timeout(self, mock_get):
        mock_get.return_value = fake_response("")

        PwnedPasswordValidator().validate(self.password)

        _, kwargs = mock_get.call_args
        self.assertEqual(kwargs["headers"], {"Add-Padding": "true"})
        self.assertEqual(kwargs["timeout"], 3)

    def test_disabled_by_setting_makes_no_request(self):
        # PWNED_PASSWORDS_ENABLED=False (the test runner's own default) --
        # no override here, so this exercises the actual test configuration.
        with mock.patch("accounts.password_validation.requests.get") as mock_get:
            PwnedPasswordValidator().validate(self.password)

        mock_get.assert_not_called()

    def test_help_text_is_informative(self):
        self.assertIn("breach", PwnedPasswordValidator().get_help_text().lower())
