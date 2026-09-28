"""The setup page's QR code (``docs/design/MFA.md``).

Built server-side with ``segno`` -- pure Python, no dependencies of its
own -- as a ``data:`` URI for an ``<img src="...">``, not markup dropped
into the page: the app disallows anything that defeats autoescaping
(``expenses/tests/test_security_pass6.py``), and an URI is plain text like
any other template variable, needing no exception from that rule.
"""

import segno


def otpauth_data_uri(uri, scale=4):
    """A ``data:image/svg+xml,...`` URI for ``uri``, for an ``<img src>``."""
    return segno.make(uri, error="m").svg_data_uri(scale=scale, svgclass=None, lineclass=None)
