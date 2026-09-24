"""Cursor pagination, and why it dictates the ordering.

A cursor encodes "where the last page stopped" as a value of the ordering
field. That only works if the field is **unique and does not change**:

* not unique, and rows sharing a value straddle the boundary, so one is
  returned twice or skipped;
* editable, and a row that moves can drop a client into the wrong place.

``spent_on`` fails both tests -- several expenses share a date, and a date
is exactly the field a user corrects. The primary key fails neither, which
is why it is the ordering here even though the web list sorts by date.

DRF's default is ``-created``, a field this project does not have. That
mismatch is a 500 on the first request rather than a warning, which is why
this class exists at all.
"""

from rest_framework.pagination import CursorPagination


class IdCursorPagination(CursorPagination):
    page_size = 25
    max_page_size = 100
    page_size_query_param = "page_size"
    ordering = "-id"


class ExpenseCursorPagination(IdCursorPagination):
    """Expenses newest date first, as the Expenses page lists them.

    A deliberate exception to the rule above. The date alone is neither
    unique nor fixed, but DRF's cursor handles a non-unique leading field
    with an offset within the tie, and ``-id`` makes the order total. What
    remains is that an expense whose date is edited *while* a client is
    paging may be seen twice or missed on that pass. For a list a person
    reads by date, that is a better trade than showing them in the order
    they happened to be typed in.
    """

    ordering = ("-spent_on", "-id")
