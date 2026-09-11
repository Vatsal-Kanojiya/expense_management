"""Shared test helpers."""


def item_formset(*items, initial=0, prefix="items"):
    """POST data for the line-item formset.

    Every POST to the expense form must carry the formset's management form.
    Django has no way to know how many child forms came back without it and
    raises ValidationError, so a test that omits it fails with the parent
    form apparently rejecting valid data. That failure mode is confusing
    enough to be worth a helper.

    Pass ``(name, amount)`` pairs to submit line items, or nothing for an
    expense with none.
    """
    data = {
        f"{prefix}-TOTAL_FORMS": str(len(items)),
        f"{prefix}-INITIAL_FORMS": str(initial),
        f"{prefix}-MIN_NUM_FORMS": "0",
        f"{prefix}-MAX_NUM_FORMS": "1000",
    }

    for index, (name, amount) in enumerate(items):
        data[f"{prefix}-{index}-name"] = name
        data[f"{prefix}-{index}-amount"] = str(amount)

    return data
