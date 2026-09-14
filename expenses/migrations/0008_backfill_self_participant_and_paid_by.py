from django.conf import settings
from django.db import migrations


def _self_name(Participant, user):
    # A copy of models.self_name_for, frozen here on purpose: a migration
    # must not import code that can change after it runs. The original
    # version created a row named "You" and crashed on any user who already
    # had a contact by that name, because names are unique per user.
    base = f"{(user.first_name or user.username).strip()} (self)"
    taken = {n.lower() for n in Participant.objects.filter(user_id=user.id).values_list("name", flat=True)}
    candidate, n = base, 2
    while candidate.lower() in taken:
        candidate = f"{base} {n}"
        n += 1
    return candidate[:60]


def backfill_self_participants(apps, schema_editor):
    User = apps.get_model(settings.AUTH_USER_MODEL)
    Participant = apps.get_model("expenses", "Participant")
    Expense = apps.get_model("expenses", "Expense")
    ItemShare = apps.get_model("expenses", "ItemShare")

    for user in User.objects.all():
        self_p = Participant.objects.filter(user_id=user.id, is_self=True).first()
        if self_p is None:
            self_p = Participant.objects.create(
                user_id=user.id, is_self=True, name=_self_name(Participant, user)
            )
        Expense.objects.filter(user_id=user.id, paid_by__isnull=True).update(paid_by=self_p)

        for expense in Expense.objects.filter(user_id=user.id):
            if expense.participants.exists() and not expense.participants.filter(id=self_p.id).exists():
                expense.participants.add(self_p)

            for item in expense.items.all():
                if item.shares.exists() and not item.shares.filter(participant_id=self_p.id).exists():
                    ItemShare.objects.create(item=item, participant=self_p, weight=1)


class Migration(migrations.Migration):

    dependencies = [
        ("expenses", "0007_expense_paid_by_participant_is_self"),
    ]

    operations = [
        migrations.RunPython(backfill_self_participants, reverse_code=migrations.RunPython.noop),
    ]
