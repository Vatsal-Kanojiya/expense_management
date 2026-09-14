"""What each person owes you.

One convention decides every number here: **the owner always counts as one
share of anything that is shared at all.** "Split evenly with Rahul" on a
300 bill means two shares, not one, so Rahul owes 150. The same holds per
line item: the people ticked on an item share it *with you*.

An expense is read one of three ways, and nothing stores which:

* it has line items, so each item is split among its own sharers;
* it has no items but has participants, so the whole amount splits evenly;
* it has neither, so it is yours alone and contributes nothing.

Items win over participants when both are present. Itemising is the more
specific statement, and letting both apply would charge people twice.

An itemised expense whose lines do not sum to its amount is skipped. Such an
expense can be saved -- refusing the whole form over one wrong figure cost
more than it was worth -- but it cannot be split, so it contributes nothing
until it is corrected. ``check_splits`` lists them.
"""

from collections import defaultdict
from decimal import Decimal

from django.db.models import Prefetch

from .models import Expense, ExpenseItem, Participant
from .splitting import allocate


def balances(user, start=None, end=None):
    """Return ``[(participant, amount_owed)]``, largest first.

    Participants who owe nothing are omitted: a list of zeroes is noise on a
    page whose question is "who owes me".
    """
    owed = defaultdict(lambda: Decimal("0"))
    self_participant = Participant.get_or_create_self(user)

    for expense in _expenses(user, start, end):
        payer = expense.paid_by or self_participant
        items = list(expense.items.all())

        if items:
            # An itemised expense whose lines do not add up to its amount is
            # a split nobody can compute: some part of the bill is charged to
            # no one. The form no longer refuses to save it, so the refusal
            # happens here instead -- the expense is left out entirely rather
            # than contributing a figure that looks authoritative and is not.
            if not expense.is_balanced():
                continue

            for item in items:
                _charge_item(owed, item, payer, self_participant)
        else:
            _charge_evenly(owed, expense, self_participant)

    ranked = sorted(owed.items(), key=lambda pair: (-pair[1], pair[0].name))
    return [(participant, amount) for participant, amount in ranked if amount]


def outstanding_balances(user, start=None, end=None):
    """Balances net of what has already been repaid.

    Kept separate from ``balances`` so the gross figure stays available:
    "Rahul owed 900 this year and has repaid 750" is two numbers, and
    collapsing them loses the first.
    """
    from django.db.models import Sum

    from .models import Settlement

    repaid = {
        row["participant"]: row["total"]
        for row in Settlement.objects.filter(user=user)
        .values("participant")
        .annotate(total=Sum("amount"))
    }

    net = [
        (participant, amount - repaid.get(participant.pk, Decimal("0")))
        for participant, amount in balances(user, start, end)
    ]

    return [(participant, amount) for participant, amount in net if amount > 0]


def _expenses(user, start, end):
    """Every expense, with its items, shares and people already loaded.

    Written with prefetch from the start rather than added later. Reading a
    balance touches four tables, so the lazy version is two levels of N+1:
    one query per expense for its items, then one per item for its shares.
    Phase 9 pins the count with assertNumQueries so it cannot regress.
    """
    queryset = (
        Expense.objects.for_user(user)
        .select_related("paid_by")
        .prefetch_related(
            "participants",
            Prefetch(
                "items",
                queryset=ExpenseItem.objects.prefetch_related("shares__participant"),
            ),
        )
    )

    if start is not None:
        queryset = queryset.filter(spent_on__gte=start)
    if end is not None:
        queryset = queryset.filter(spent_on__lte=end)

    return queryset


def _charge_item(owed, item, payer, self_participant):
    shares = list(item.shares.all())

    # Nobody ticked: the line was consumed by the owner alone.
    if not shares:
        if not payer.is_self:
            owed[payer] -= item.amount
        return

    # Sort shares so self is first (absorbs extra paisa in allocate)
    shares = sorted(shares, key=lambda s: (not s.participant.is_self, s.participant.name))
    weights = [share.weight for share in shares]
    portions = allocate(item.amount, weights)

    for share, portion in zip(shares, portions, strict=True):
        participant = share.participant
        if payer.is_self:
            if not participant.is_self:
                owed[participant] += portion
        else:
            if participant.is_self:
                owed[payer] -= portion


def _charge_evenly(owed, expense, self_participant):
    people = list(expense.participants.all())
    payer = expense.paid_by or self_participant

    if not people:
        if not payer.is_self:
            owed[payer] -= expense.amount
        return

    # Sort participants so that the owner/self is first (to absorb any extra paisa)
    people = sorted(people, key=lambda p: (not p.is_self, p.name))
    portions = allocate(expense.amount, [1] * len(people))

    for participant, portion in zip(people, portions, strict=True):
        if payer.is_self:
            if not participant.is_self:
                owed[participant] += portion
        else:
            if participant.is_self:
                owed[payer] -= portion
