from django.db import migrations


def rename_self_participants(apps, schema_editor):
    """Rename self rows created as "You" by the original 0008.

    0008 has since been corrected to name them "FirstName (self)", but
    databases that already ran the old version still hold "You". This brings
    them into line. Logic is copied, not imported, for the same reason as in
    0008.
    """
    Participant = apps.get_model("expenses", "Participant")

    for row in Participant.objects.filter(is_self=True, name="You").select_related("user"):
        user = row.user
        base = f"{(user.first_name or user.username).strip()} (self)"
        taken = {
            n.lower()
            for n in Participant.objects.filter(user_id=user.id)
            .exclude(pk=row.pk)
            .values_list("name", flat=True)
        }
        candidate, n = base, 2
        while candidate.lower() in taken:
            candidate = f"{base} {n}"
            n += 1
        row.name = candidate[:60]
        row.save(update_fields=["name"])


class Migration(migrations.Migration):
    dependencies = [
        ("expenses", "0009_expense_misc_amount_expense_misc_note_and_more"),
    ]

    operations = [
        migrations.RunPython(rename_self_participants, reverse_code=migrations.RunPython.noop),
    ]
