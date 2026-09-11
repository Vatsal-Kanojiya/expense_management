"""Audit itemised expenses whose line items do not sum to their amount.

Phase 8 moved that invariant into the formset because a CheckConstraint
cannot see across sibling rows. The honest cost of a rule the database
cannot hold is that the database cannot hold it: rows written by the admin,
a shell session, a data migration, or any version of the code from before
the rule existed can violate it silently.

This command is the other half of that trade. A rule enforced only at one
entry point needs a way to check the rows at rest.
"""

from django.core.management.base import BaseCommand

from expenses.models import Expense


class Command(BaseCommand):
    help = "Report itemised expenses whose line items do not sum to the expense amount."

    def add_arguments(self, parser):
        parser.add_argument(
            "--fail",
            action="store_true",
            help="Exit non-zero when anything is found, for use in CI or a cron alert.",
        )

    def handle(self, *args, **options):
        broken = Expense.objects.unbalanced().select_related("user", "category")

        for expense in broken:
            self.stdout.write(
                self.style.WARNING(
                    f"#{expense.pk} {expense.user} {expense.spent_on} "
                    # Quantised: SQLite hands back a Decimal with no scale,
                    # so an unformatted Sum prints "600" beside "900.00".
                    f"{expense.category.name}: items total {expense.items_total:.2f}, "
                    f"expense is {expense.amount:.2f}"
                )
            )

        count = len(broken)

        if not count:
            self.stdout.write(self.style.SUCCESS("Every itemised expense adds up."))
            return

        message = f"{count} expense{'s' if count > 1 else ''} do not add up."

        if options["fail"]:
            # SystemExit rather than raising CommandError: this is a finding
            # about the data, not a failure of the command.
            self.stderr.write(self.style.ERROR(message))
            raise SystemExit(1)

        self.stdout.write(self.style.ERROR(message))
