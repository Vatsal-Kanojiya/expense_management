from django.conf import settings
from django.db import migrations


def backfill_self_participants(apps, schema_editor):
    User = apps.get_model(settings.AUTH_USER_MODEL)
    Participant = apps.get_model("expenses", "Participant")
    Expense = apps.get_model("expenses", "Expense")
    ItemShare = apps.get_model("expenses", "ItemShare")

    for user in User.objects.all():
        self_p, _ = Participant.objects.get_or_create(
            user_id=user.id,
            is_self=True,
            defaults={"name": "You"},
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
