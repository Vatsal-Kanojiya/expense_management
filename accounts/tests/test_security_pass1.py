"""Security pass 1 (commit ea732e4): the protections added, checked one by one."""

from django.test import RequestFactory, SimpleTestCase, override_settings
from rest_framework.throttling import AnonRateThrottle

from accounts import ratelimit


class ClientAddressTests(SimpleTestCase):
    """Which address the limits apply to. Only what a trusted proxy wrote counts."""

    def request(self, forwarded=None):
        extra = {"REMOTE_ADDR": "10.0.0.1"}
        if forwarded is not None:
            extra["HTTP_X_FORWARDED_FOR"] = forwarded
        return RequestFactory().get("/", **extra)

    @override_settings(TRUSTED_PROXY_COUNT=0)
    def test_without_a_proxy_the_forwarded_header_is_ignored(self):
        self.assertEqual(ratelimit.client_ip(self.request("203.0.113.9")), "10.0.0.1")

    @override_settings(TRUSTED_PROXY_COUNT=1)
    def test_behind_one_proxy_the_right_most_entry_is_used(self):
        request = self.request("198.51.100.7, 203.0.113.9")

        self.assertEqual(ratelimit.client_ip(request), "203.0.113.9")

    @override_settings(TRUSTED_PROXY_COUNT=2)
    def test_behind_two_proxies_the_second_from_the_right_is_used(self):
        request = self.request("198.51.100.7, 203.0.113.9, 192.0.2.1")

        self.assertEqual(ratelimit.client_ip(request), "203.0.113.9")

    @override_settings(TRUSTED_PROXY_COUNT=1)
    def test_behind_a_proxy_with_no_header_the_socket_address_is_used(self):
        self.assertEqual(ratelimit.client_ip(self.request()), "10.0.0.1")

    def test_the_api_throttle_follows_the_same_rule(self):
        # Default settings: no proxy, so the header must make no difference.
        throttle = AnonRateThrottle()

        first = throttle.get_ident(self.request("203.0.113.9"))
        second = throttle.get_ident(self.request("198.51.100.7"))

        self.assertEqual((first, second), ("10.0.0.1", "10.0.0.1"))
