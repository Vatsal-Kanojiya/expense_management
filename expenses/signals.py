"""The one place this project uses signals, and the argument for it.

Signals make control flow implicit. A reader of ``ExpenseCreateView`` has
no way to see that saving also invalidates a cache, and a debugger has to
know the receiver exists before it can look for it. That cost is why the
rest of this codebase has none: business logic belongs where it is called.

Cache invalidation is the case that overturns the argument, for three
reasons:

1. **It is not business logic.** Nothing about the meaning of "record an
   expense" involves a cache. It is bookkeeping about a derived copy.
2. **Forgetting is silent.** A missed ``bump_version`` does not raise, fail
   a test, or look wrong in review. It serves a stale number, indefinitely,
   to exactly one user. Phase 14 shipped that gap as known issue 26.
3. **The write sites are unbounded.** Views, the API, the admin, a shell
   session, a data migration, a management command, a Celery task. Auditing
   that list forever is a losing game; the ORM is the one chokepoint they
   all pass through.

The rule this project settles on: **a signal is right when the concern is
cross-cutting, invisible by nature, and must not be forgotten.** Cache
invalidation and audit logging qualify. "Create a related row when this one
is saved" does not -- that is business logic hiding from its caller.
"""

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .cache import bump_version
from .models import Expense, ExpenseItem, ItemShare, Settlement


def _owner_id(instance):
    """Walk to the user who owns the row.

    Items and shares have no user column; they belong to an expense that
    does. The walk costs a query when the relation is not already loaded,
    which is acceptable on a write and would not be on a read.
    """
    if isinstance(instance, ItemShare):
        return instance.item.expense.user_id
    if isinstance(instance, ExpenseItem):
        return instance.expense.user_id
    return instance.user_id


@receiver(post_save, sender=Expense)
@receiver(post_save, sender=ExpenseItem)
@receiver(post_save, sender=ItemShare)
@receiver(post_save, sender=Settlement)
@receiver(post_delete, sender=Expense)
@receiver(post_delete, sender=ExpenseItem)
@receiver(post_delete, sender=ItemShare)
@receiver(post_delete, sender=Settlement)
def invalidate_summaries(sender, instance, **kwargs):
    """Bump the owner's cache version on any write to their money.

    **bulk_create and queryset.update() do not fire these.** That is not an
    oversight in Django, it is the definition: those operate on rows, not
    instances, so there is no instance to signal about. ItemShare rows
    written by ``_sync_shares`` go in through bulk_create, which is why the
    parent ExpenseItem save still carries the invalidation.
    """
    try:
        user_id = _owner_id(instance)
    except (Expense.DoesNotExist, ExpenseItem.DoesNotExist):
        # post_delete during a cascade: the parent may already be gone.
        # Nothing to invalidate that the parent's own signal did not.
        return

    if user_id is not None:
        bump_version(user_id)
