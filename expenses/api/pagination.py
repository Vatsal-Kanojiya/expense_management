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
