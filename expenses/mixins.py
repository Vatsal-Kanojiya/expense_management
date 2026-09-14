from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction


class OwnerScopedMixin(LoginRequiredMixin):
    """Require login and restrict the view's queryset to the user's own rows.

    Login and scoping are deliberately bundled. Splitting them means a view
    can be written with scoping but without LoginRequiredMixin, and
    `self.request.user` on an anonymous request is AnonymousUser — which
    `filter(user=...)` rejects with a TypeError rather than a redirect. One
    mixin makes the safe combination the default.

    Scoping in get_queryset (rather than get_object) covers list, detail,
    update and delete in one place: an unowned pk simply is not in the
    queryset, so Django raises 404 before any permission code runs.
    """

    def get_queryset(self):
        return super().get_queryset().filter(user=self.request.user)


class OwnerFormMixin:
    """Give the form the request user, and stamp ownership on save.

    `user` is never a form field, so ownership cannot be reassigned by a
    crafted POST. The form receives the user only to scope its own
    validation (duplicate names, the category dropdown).
    """

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        # On update this is a no-op: OwnerScopedMixin already guarantees the
        # instance belongs to this user. On create it is what assigns
        # ownership, server-side, from the session.
        form.instance.user = self.request.user
        return super().form_valid(form)


class ItemFormSetMixin:
    """Save an expense and its line items as one unit.

    Two things make this more than boilerplate.

    **Ordering.** A child row needs its parent's primary key, so the parent
    must be saved first. But the formset's validation needs the parent's
    *amount* to check the sum, and that amount only exists on an unsaved
    instance at that point. So the formset is validated against the unsaved
    parent and saved against the saved one.

    **Atomicity.** Because the parent is written before the children, a
    failure between the two would leave an expense whose items do not add up
    -- exactly the state the invariant exists to prevent. The transaction is
    what makes the rule hold at rest, not just at submit time.
    """

    formset_class = None
    formset_prefix = "items"

    def build_formset(self, instance=None, data=None):
        return self.formset_class(
            data=data,
            instance=instance,
            prefix=self.formset_prefix,
            # Reaches every child form. Without it the "shared with" checkboxes
            # would list every user's people -- the same leak as an unscoped
            # ModelChoiceField, multiplied by the number of rows.
            form_kwargs={"user": self.request.user},
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # setdefault, not assignment: form_invalid re-renders with a bound
        # formset that already carries its errors, and overwriting it here
        # would silently discard them.
        context.setdefault("formset", self.build_formset(instance=self.object))
        return context

    def form_valid(self, form):
        formset = self.build_formset(instance=form.instance, data=self.request.POST)

        if not formset.is_valid():
            return self.render_to_response(self.get_context_data(form=form, formset=formset))

        with transaction.atomic():
            response = super().form_valid(form)
            formset.instance = self.object
            formset.save()

        self._warn_if_unbalanced(formset)

        return response

    def _warn_if_unbalanced(self, formset):
        """Say what was saved, and what it will not be counted towards.

        The save succeeded, so this is not an error. But an itemised expense
        that does not add up is left out of balances, and letting that happen
        quietly would be worse than the refusal it replaced -- the person
        would think the split was recorded.
        """
        if formset.sum_mismatch is None:
            return

        unaccounted_diff, expected = formset.sum_mismatch
        difference = abs(unaccounted_diff)

        messages.warning(
            self.request,
            f"Saved, but ₹{difference:.2f} of the ₹{expected:.2f} is not accounted for by "
            "the line items or the misc amount, so this expense is left out of "
            "balances until it is.",
        )
