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
from dataclasses import dataclass
from decimal import Decimal

from django.db.models import Prefetch

from .models import Expense, ExpenseItem, Participant
from .splitting import allocate


@dataclass(frozen=True)
class SplitRow:
    participant: Participant | None  # None is the owner
    items: Decimal  # their portions of line items, or of the even split
    misc: Decimal  # their portion of misc_amount; Decimal("0") when none
    total: Decimal  # items + misc


def split_expense(expense):
    """Return a list of SplitRow per person (owner as None), or None if unbalanced.

    Owner row is first (if owner participated), followed by other participants
    ordered by name.
    """
    if not expense.is_balanced():
        return None

    items = list(expense.items.all())
    items_consumption = defaultdict(lambda: Decimal("0"))
    misc_consumption = defaultdict(lambda: Decimal("0"))

    if items:
        for item in items:
            shares = list(item.shares.all())
            if not shares:
                # Unshared line item was consumed by the owner alone.
                items_consumption[None] += item.amount
            else:
                # Sort shares so owner is first (absorbs extra paisa in allocate)
                shares = sorted(
                    shares, key=lambda s: (not s.participant.is_self, s.participant.name)
                )
                weights = [share.weight for share in shares]
                portions = allocate(item.amount, weights)
                for share, portion in zip(shares, portions, strict=True):
                    key = None if share.participant.is_self else share.participant
                    items_consumption[key] += portion

        if expense.misc_amount and expense.misc_amount > 0:
            active_consumers = [k for k in items_consumption if items_consumption[k] > Decimal("0")]
            active_consumers = sorted(
                active_consumers, key=lambda k: (k is not None, k.name if k else "")
            )
            if active_consumers:
                weights = [int(items_consumption[k] * 100) for k in active_consumers]
                if all(w > 0 for w in weights):
                    portions = allocate(expense.misc_amount, weights)
                    for k, portion in zip(active_consumers, portions, strict=True):
                        misc_consumption[k] += portion
    else:
        people = list(expense.participants.all())
        if not people:
            # Yours alone
            items_consumption[None] = expense.amount
        else:
            people = sorted(people, key=lambda p: (not p.is_self, p.name))
            portions = allocate(expense.amount, [1] * len(people))
            for participant, portion in zip(people, portions, strict=True):
                key = None if participant.is_self else participant
                items_consumption[key] += portion

    all_keys = set(items_consumption.keys()) | set(misc_consumption.keys())
    rows = []

    # 1. Owner row first
    if None in all_keys:
        item_val = items_consumption[None]
        misc_val = misc_consumption[None]
        rows.append(
            SplitRow(
                participant=None,
                items=item_val,
                misc=misc_val,
                total=item_val + misc_val,
            )
        )

    # 2. Other participants ordered by name
    non_owner_keys = sorted([k for k in all_keys if k is not None], key=lambda p: p.name)
    for p in non_owner_keys:
        item_val = items_consumption[p]
        misc_val = misc_consumption[p]
        rows.append(
            SplitRow(
                participant=p,
                items=item_val,
                misc=misc_val,
                total=item_val + misc_val,
            )
        )

    return rows


def balances(user, start=None, end=None):
    """Return ``[(participant, amount_owed)]``, largest first.

    Participants who owe nothing are omitted: a list of zeroes is noise on a
    page whose question is "who owes me".
    """
    owed = defaultdict(lambda: Decimal("0"))
    self_participant = Participant.get_or_create_self(user)

    for expense in _expenses(user, start, end):
        rows = split_expense(expense)
        if rows is None:
            continue

        payer = expense.paid_by or self_participant
        owner_row = next((r for r in rows if r.participant is None), None)

        if payer.is_self:
            for row in rows:
                if row.participant is not None:
                    owed[row.participant] += row.total
        else:
            if owner_row is not None:
                owed[payer] -= owner_row.total

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
