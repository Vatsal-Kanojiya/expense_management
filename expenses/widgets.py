from django import forms


class ChipSelectMultiple(forms.SelectMultiple):
    """A multi-select widget rendered as searchable chips.

    Subclasses SelectMultiple so that without JavaScript the browser renders
    and submits a plain <select multiple>. The JavaScript progressively enhances
    it into a type-to-filter chip selector, keeping the underlying <select> as
    the single source of truth.
    """

    template_name = "expenses/widgets/chip_select.html"

    class Media:
        js = ["expenses/chip-select.js"]
