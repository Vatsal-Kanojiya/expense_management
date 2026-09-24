"""One exception the API turns into an answer instead of a 500.

``on_delete=PROTECT`` is how this project refuses to destroy history:
a category with expenses, a person on a line item or who paid a bill. The
web views catch ``ProtectedError`` and explain. A ViewSet's ``destroy()``
does not, so the same refusal reached an API client as a 500 with no
reason (BUILD_LOG issue 44). Handled here, once, it covers every delete
endpoint, including ones not written yet.
"""

from collections import Counter

from django.db.models import ProtectedError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


def exception_handler(exc, context):
    if isinstance(exc, ProtectedError):
        # "3 expenses and 1 item share", from the rows that blocked the delete.
        # Counts only: naming the rows would put other data in an error body.
        blocking = Counter(str(obj._meta.verbose_name_plural) for obj in exc.protected_objects)
        reason = " and ".join(f"{count} {name}" for name, count in sorted(blocking.items()))
        return Response(
            {
                "detail": f"This is still used by {reason}, so it cannot be deleted.",
                "code": "protected",
                "blocking": dict(sorted(blocking.items())),
            },
            status=status.HTTP_409_CONFLICT,
        )

    return drf_exception_handler(exc, context)
