"""Deleting an account, in the order the database will accept.

Known issue 10, open since session 4: ``user.delete()`` raises
``ProtectedError`` for any user who has ever recorded an expense.

**Why, precisely.** Deleting a user cascades to their categories and their
expenses. But ``Expense.category`` is ``on_delete=PROTECT``, and Django's
collector evaluates that protection even though the protecting expense is
itself in the same delete plan. It has no way to know the order would work
out; it sees a protected reference and refuses. ``ItemShare.participant``
does the same for participants.

**Three ways out, and why this one.**

1. Change the FKs to ``CASCADE``. Fixes deletion and removes the protection
   that stops someone deleting a category out from under a year of
   expenses. That protection is worth more than the convenience.
2. ``SET_NULL`` on ``Expense.category``. Makes the column nullable, so every
   query and template must now handle a category-less expense forever, to
   solve a problem that occurs once per account.
3. Delete in dependency order, explicitly. The protection stays exactly as
   strong, and the one operation that legitimately needs to bypass it says
   so out loud.

Three is what this does. It is more code, and the code is the point: an
account deletion is destructive and irreversible, and a function that
spells out what it destroys is easier to review than a cascade nobody can
see.
"""

import logging

from django.db import transaction

from expenses.models import Category, Expense, ExpenseItem, Participant, Settlement

logger = logging.getLogger("expenses")


@transaction.atomic
def delete_account(user):
    """Remove a user and everything they own. Returns what was deleted.

    Atomic, because a partial account deletion is worse than none: the user
    would be gone while their expenses remained, owned by nobody and
    unreachable by any scoped queryset.

    Order is bottom-up. Each step removes the rows that protect the next.
    """
    counts = {"items": ExpenseItem.objects.filter(expense__user=user).count()}

    # Files first, while the rows that name them still exist. ExportJob
    # rows cascade from the user, but the files on disk do not: deleting
    # the rows alone would leave a full copy of someone's financial history
    # after they asked to be forgotten.
    for job in user.export_jobs.all():
        if job.file:
            job.file.delete(save=False)

    # Expenses first among the rows: they hold the PROTECT reference to
    # categories, and their items and shares cascade with them.
    counts["expenses"] = Expense.objects.filter(user=user).delete()[0]

    # Settlements reference participants; clear them before participants go.
    counts["settlements"] = Settlement.objects.filter(user=user).delete()[0]

    # Participants are now unprotected, because every ItemShare went with
    # the expenses above.
    counts["participants"] = Participant.objects.filter(user=user).delete()[0]

    # Categories are now unprotected too.
    counts["categories"] = Category.objects.filter(user=user).delete()[0]

    logger.info("Deleting account %s: %s", user.pk, counts)

    user.delete()

    return counts
