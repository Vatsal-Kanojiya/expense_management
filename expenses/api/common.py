"""Response shapes shared by every API module, named once for the schema."""

from rest_framework import serializers


class MessageSerializer(serializers.Serializer):
    """A plain answer: what happened, and a stable code a client can branch on.

    ``detail`` is for people and may be reworded; ``code`` is for programs
    and will not change. Error responses from DRF itself use the same
    ``detail`` key, so a client reads one field for both.
    """

    detail = serializers.CharField()
    code = serializers.CharField(required=False)


class ValidationErrorSerializer(serializers.Serializer):
    """DRF's 400 shape: each invalid field maps to a list of messages.

    Errors that belong to no single field are under ``non_field_errors``.
    Declared with one example field only because the keys depend on the
    request; the schema cannot list them all.
    """

    non_field_errors = serializers.ListField(child=serializers.CharField(), required=False)


def raise_form_errors(form, rename=None):
    """Turn a Django form's errors into a DRF 400, in DRF's own shape.

    The account endpoints validate with the same forms the Django pages use
    -- password rules, unique email, the old-password check -- rather than
    restating them in serializers (DECISIONS D44). Only the field names are
    translated, from Django's (``password1``) to the API's (``password``).
    """
    rename = {"__all__": "non_field_errors", **(rename or {})}
    raise serializers.ValidationError(
        {rename.get(field, field): list(messages) for field, messages in form.errors.items()}
    )
