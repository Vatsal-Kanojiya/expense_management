"""A full-text index that only one backend can have.

Known issue 17: `note__icontains` compiles to `LIKE '%term%'`. A leading
wildcard cannot use a btree index, so search is a full table scan that gets
linearly worse with every expense ever recorded.

Postgres answers this with a GIN index over `to_tsvector(note)`, which is
an *expression* index -- no extra column to store, no trigger to keep in
sync, nothing to backfill. SQLite has FTS5, but it is a separate virtual
table rather than an index on this one, so there is no single migration
that gives both backends the same thing.

So the index is created only on Postgres, and `ExpenseFilterForm` branches
on `connection.vendor` to match. That branch is the honest cost of an
index one backend cannot have, and it is worth seeing rather than hiding
behind an abstraction.
"""

from django.db import migrations


def add_index(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return

    schema_editor.execute(
        "CREATE INDEX IF NOT EXISTS expense_note_fts "
        "ON expenses_expense USING GIN (to_tsvector('english', note))"
    )


def drop_index(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return

    schema_editor.execute("DROP INDEX IF EXISTS expense_note_fts")


class Migration(migrations.Migration):
    dependencies = [("expenses", "0004_remove_category_uniq_category_per_user_and_more")]

    operations = [
        # RunPython rather than a Meta index, because a GinIndex declared on
        # the model would be attempted on every backend and fail to migrate
        # on SQLite. The state half is empty on purpose: Django's model state
        # does not need to know about an index it cannot always create.
        migrations.RunPython(add_index, drop_index),
    ]
