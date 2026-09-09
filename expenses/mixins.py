from django.contrib.auth.mixins import LoginRequiredMixin


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
