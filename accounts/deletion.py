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

from django.core.files.storage import default_storage
from django.db import transaction
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken

from expenses.models import Category, Expense, ExpenseItem, Participant, Settlement

from .audit import record
from .models import SecurityEvent

logger = logging.getLogger("expenses")


@transaction.atomic
def delete_account(user, request=None):
    """Remove a user and everything they own. Returns what was deleted.

    Atomic, because a partial account deletion is worse than none: the user
    would be gone while their expenses remained, owned by nobody and
    unreachable by any scoped queryset.

    Order is bottom-up. Each step removes the rows that protect the next.

    Roadmap A3: records ``account_deleted``, then blanks ``username`` on
    every SecurityEvent this account ever produced (including the one just
    recorded). They stay -- deleting them would erase exactly the trail an
    audit log is for -- but once someone has asked to be forgotten, no row
    should carry their name any more. Collected *before* ``user.delete()``,
    while the FK is still valid: the delete's own collector already sets
    ``user`` to NULL on each of them (SET_NULL), which loses the only way
    to find them again by user, so their ids are grabbed first.
    """
    record(
        "account_deleted",
        request=request,
        user=user,
        username=user.get_username(),
        user_id=user.pk,
    )
    event_ids = list(SecurityEvent.objects.filter(user=user).values_list("pk", flat=True))

    counts = {"items": ExpenseItem.objects.filter(expense__user=user).count()}

    # The files go too. ExportJob and BillScan rows cascade from the user,
    # but the files on disk do not: deleting the rows alone would leave a
    # full copy of someone's financial history -- or a photo of a receipt
    # -- after they asked to be forgotten. Security pass 5 added the bill
    # photos, which were missing here.
    #
    # Names are collected now, while the rows that hold them exist, and the
    # files are removed only once the transaction commits. Removed inside
    # it, a failure further down would roll the rows back but not the
    # files, leaving an account that still exists pointing at files that
    # no longer do.
    names = [job.file.name for job in user.export_jobs.all() if job.file]
    names += [scan.image.name for scan in user.bill_scans.all() if scan.image]
    transaction.on_commit(lambda: _delete_files(names))

    # The refresh tokens issued to this account. OutstandingToken.user is
    # SET_NULL (rest_framework_simplejwt.token_blacklist), so left alone it
    # would survive the account -- the raw signed token string sitting in
    # the row's own `token` column -- as an orphan nothing can enumerate to
    # revoke on its own. Deleting it here cascades to any BlacklistedToken
    # for it (a OneToOne with on_delete=CASCADE) and leaves nothing of the
    # session behind. The token was already unusable the moment the user
    # row went (JWTAuthentication.get_user() 401s with "user_not_found" for
    # an access token whose subject no longer exists); this is about not
    # leaving the token itself sitting in the database, not about access.
    # Security pass 5.
    counts["refresh_tokens"] = OutstandingToken.objects.filter(user=user).delete()[0]

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

    SecurityEvent.objects.filter(pk__in=event_ids).update(username="")

    return counts


def _delete_files(names):
    for name in names:
        default_storage.delete(name)
