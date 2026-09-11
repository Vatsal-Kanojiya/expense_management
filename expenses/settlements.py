"""Settling up, and the read-then-write that races.

A balance is derived: what someone owes across every expense, minus what
they have already repaid. Settling means reading that derived number and
then writing a row based on it, which is the canonical shape of a lost
update. Two requests both read 150 outstanding, both write a settlement of
150, and the participant has repaid 300 for a 150 debt.

Nothing about the schema prevents it. There is no unique constraint that
could: two genuine settlements of the same amount on the same day are
perfectly legal. The only thing that makes the read and the write atomic
with respect to each other is a lock held across both.
"""

from decimal import Decimal

from django.db import transaction
from django.db.models import Sum

from .balances import balances
from .models import Participant, Settlement


def outstanding(user, participant):
    """What this participant still owes, after repayments."""
    owed = dict(balances(user)).get(participant, Decimal("0"))
    repaid = Settlement.objects.filter(user=user, participant=participant).aggregate(
        total=Sum("amount")
    )["total"] or Decimal("0")

    return owed - repaid


@transaction.atomic
def settle_up(user, participant_id, note=""):
    """Record that a participant has repaid everything outstanding.

    Returns the Settlement written, or None when nothing was owed.

    ``select_for_update`` on the participant row is what makes this safe.
    The row itself is not modified; it is being used as the lock, because
    the thing that needs protecting -- a number derived from four tables --
    has no single row of its own to lock.

    A second caller blocks on that ``SELECT ... FOR UPDATE`` until the
    first commits, and then reads a balance that already includes the first
    settlement. It writes nothing instead of double-settling.

    This is a no-op on SQLite, which locks the whole database rather than
    individual rows. The guarantee here is real only on a backend with row
    locks, which is why phase 11 brought Postgres in before this phase.
    """
    # get(), not filter().first(): a missing or non-owned participant must
    # raise rather than silently settle nothing.
    participant = Participant.objects.select_for_update().get(pk=participant_id, user=user)

    amount = outstanding(user, participant)

    if amount <= 0:
        return None

    return Settlement.objects.create(user=user, participant=participant, amount=amount, note=note)
