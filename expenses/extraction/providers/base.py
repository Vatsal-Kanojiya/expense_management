"""The shape every provider implements.

A Protocol, not an ABC: nothing here needs to be inherited from, only
matched -- FakeProvider already satisfies this without knowing it exists.
"""

from typing import Protocol

from ..types import ExtractedBill


class BillProvider(Protocol):
    name: str

    def extract(self, data: bytes, mime_type: str, model: str) -> ExtractedBill: ...
