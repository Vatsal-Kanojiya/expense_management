from django import forms

from .models import Category


class CategoryForm(forms.ModelForm):
    """Form for a user's own categories.

    `user` is deliberately NOT a form field. If it were, the browser could
    post any user id and reassign ownership. Instead the view supplies the
    user out of band and the form uses it only for validation.
    """

    class Meta:
        model = Category
        fields = ["name"]

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_name(self):
        name = self.cleaned_data["name"].strip()

        # The DB already has UniqueConstraint(user, name) as the backstop, but
        # a ModelForm cannot check it: Django excludes constraints that touch
        # fields absent from the form, and `user` is absent by design. Without
        # this check a duplicate becomes an IntegrityError 500 instead of a
        # field error. Two layers, two jobs: the DB guarantees, the form explains.
        duplicates = Category.objects.filter(user=self.user, name__iexact=name)
        if self.instance.pk:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise forms.ValidationError("You already have a category with this name.")

        return name
