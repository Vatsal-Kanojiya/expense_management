"""Forms that validate query-string parameters.

A plain Form is the right tool for GET parameters, not just POST bodies.
It turns `?start=banana` into a field error instead of a 500, and hands
back cleaned Python dates rather than strings. Reading request.GET
directly means parsing and validating by hand at every call site.

django-filter does this too and is worth knowing, but a form is enough
here and keeps the mechanics visible.
"""

from datetime import date

from django import forms
from django.db import connection
from django.db.models import Q

from .models import Category
from .summaries import month_bounds


class DateRangeForm(forms.Form):
    """Start and end dates, defaulting to the current calendar month."""

    start = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        label="From",
    )
    end = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        label="To",
    )

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("start"), cleaned.get("end")

        # Both blank is the normal first visit, not an error — the caller
        # falls back to the current month.
        if start and end and start > end:
            raise forms.ValidationError("The start date must be on or before the end date.")

        return cleaned

    def range_or_default(self, today: date | None = None) -> tuple[date, date]:
        """The requested range, falling back to the current month.

        Each end falls back independently, so `?start=2026-01-01` alone is
        a range from January to the end of this month rather than an error.
        """
        today = today or date.today()
        default_start, default_end = month_bounds(today)

        if not self.is_valid():
            return default_start, default_end

        return (
            self.cleaned_data.get("start") or default_start,
            self.cleaned_data.get("end") or default_end,
        )


class ExpenseFilterForm(DateRangeForm):
    """Date range, plus category and free-text search, for the list view."""

    category = forms.ModelChoiceField(
        queryset=Category.objects.none(),
        required=False,
        empty_label="All categories",
    )
    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Search notes, items or people"}),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)

        # Same scoping rule as ExpenseForm: an unscoped queryset here would
        # both list other users' category names in the dropdown and let a
        # crafted ?category=<id> filter against one.
        self.fields["category"].queryset = Category.objects.filter(user=user)

    def apply(self, queryset):
        """Narrow a queryset by whatever was actually supplied."""
        start, end = self.range_or_default()
        queryset = queryset.in_range(start, end)

        if not self.is_valid():
            return queryset

        if category := self.cleaned_data.get("category"):
            queryset = queryset.filter(category=category)

        if search := self.cleaned_data.get("search"):
            # Q objects are how you build OR. Chained .filter() calls are
            # AND, and there is no keyword-argument syntax for OR at all.
            #
            # Three of these four lookups cross a multi-valued relation, so
            # one expense matching two items comes back twice. .distinct()
            # is mandatory here, not tidiness -- without it the page shows
            # duplicate rows and the pagination count is wrong.
            #
            # The note is searched through a full-text index where the
            # database has one, and with LIKE where it does not. See
            # _note_match below for what that trade costs.
            queryset, note_match = self._note_match(queryset, search)

            queryset = queryset.filter(
                note_match
                | Q(items__name__icontains=search)
                | Q(participants__name__icontains=search)
                | Q(items__shares__participant__name__icontains=search)
            ).distinct()

        return queryset

    @staticmethod
    def _note_match(queryset, search):
        """Full-text search on Postgres, LIKE everywhere else.

        Known issue 17: ``note__icontains`` compiles to ``LIKE '%term%'``,
        and a **leading** wildcard cannot use a btree index. Every search is
        a full table scan that gets linearly worse forever.

        Postgres fixes it with a GIN index over ``to_tsvector('english',
        note)`` (migration 0005). The annotation here must name the *same*
        expression, config included -- ``to_tsvector(note)`` and
        ``to_tsvector('english', note)`` are different expressions, and an
        index on one is invisible to the other. That silent miss is the
        usual reason a full-text index appears not to help.

        **The semantics change, and that is a real trade, not a free win.**
        Full-text search matches whole words and their stems: "dinner"
        finds "dinners", and "inn" no longer finds "dinner". LIKE does the
        opposite. Searching for a fragment is what a user does when they
        half-remember a note, so this is worth knowing before assuming the
        indexed version is strictly better.

        The item and participant lookups stay on ``icontains``. They cross
        a join, so no single-table index could serve them, and those tables
        are small.
        """
        if connection.vendor != "postgresql":
            return queryset, Q(note__icontains=search)

        from django.contrib.postgres.search import SearchQuery, SearchVector

        queryset = queryset.annotate(note_vector=SearchVector("note", config="english"))

        return queryset, Q(note_vector=SearchQuery(search, config="english"))

    def is_filtered(self) -> bool:
        """Whether the user narrowed anything, for showing a 'clear' link."""
        return any(self.data.get(field) for field in ("start", "end", "category", "search"))
