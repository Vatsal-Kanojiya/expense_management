"""Serializers, and the one thing that makes nested writes awkward.

DRF gives you readable nested output for free and writable nested input
never. ``ModelSerializer.create()`` refuses nested data because it cannot
guess the order, the ownership, or what "update" means for a list of
children. Writing that logic yourself is the point of this module.
"""

from django.db import transaction
from rest_framework import serializers

from expenses.models import Category, Expense, ExpenseItem, ItemShare, Participant


class ScopedPrimaryKeyRelatedField(serializers.PrimaryKeyRelatedField):
    """A related field limited to the requesting user's own rows.

    The DRF mirror of the ``ModelChoiceField`` lesson from phase 3. An
    unscoped related field accepts any primary key in the table, so a
    crafted payload files an expense against someone else's category. There
    is no dropdown to notice it in an API, which makes it easier to miss and
    no less serious.
    """

    def get_queryset(self):
        request = self.context.get("request")
        return super().get_queryset().filter(user=request.user)


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name", "created_at"]
        read_only_fields = ["created_at"]

    def validate_name(self, value):
        # Mirrors CategoryForm.clean_name. Same reason it exists there: a
        # ModelSerializer cannot check a UniqueConstraint over a field the
        # payload does not carry, and `user` is supplied by the view.
        name = value.strip()
        duplicates = Category.objects.filter(user=self.context["request"].user, name__iexact=name)

        if self.instance:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise serializers.ValidationError("You already have a category with this name.")

        return name


class ParticipantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Participant
        fields = ["id", "name", "created_at"]
        read_only_fields = ["created_at"]

    def validate_name(self, value):
        name = value.strip()
        duplicates = Participant.objects.filter(
            user=self.context["request"].user, name__iexact=name
        )

        if self.instance:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise serializers.ValidationError("You already have someone with this name.")

        return name


class ItemShareSerializer(serializers.ModelSerializer):
    participant = ScopedPrimaryKeyRelatedField(queryset=Participant.objects.all())

    class Meta:
        model = ItemShare
        fields = ["participant", "weight"]


class ExpenseItemSerializer(serializers.ModelSerializer):
    shares = ItemShareSerializer(many=True, required=False)

    class Meta:
        model = ExpenseItem
        fields = ["id", "name", "amount", "shares"]
        read_only_fields = ["id"]

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("Amount must be greater than zero.")
        return value


class ExpenseSerializer(serializers.ModelSerializer):
    category = ScopedPrimaryKeyRelatedField(queryset=Category.objects.all())
    participants = ScopedPrimaryKeyRelatedField(
        queryset=Participant.objects.all(), many=True, required=False
    )
    items = ExpenseItemSerializer(many=True, required=False)

    class Meta:
        model = Expense
        fields = [
            "id",
            "category",
            "amount",
            "spent_on",
            "note",
            "participants",
            "items",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("Amount must be greater than zero.")
        return value

    def validate(self, attrs):
        """The cross-row invariant again, in its second home.

        The formset enforces this for the web form; nothing it does applies
        here. An invariant the database cannot hold has to be restated at
        every entry point, which is the real cost of moving a rule out of
        the schema -- and the reason ``check_splits`` exists.

        ``validate()`` rather than ``validate_items()``, because the rule
        needs both the items and the amount, and a field-level validator
        only sees its own field.
        """
        items = attrs.get("items")

        if not items:
            return attrs

        # On PATCH the amount may be absent, in which case the stored one
        # is what the items must match.
        amount = attrs.get("amount", getattr(self.instance, "amount", None))

        if amount is None:
            return attrs

        total = sum(item["amount"] for item in items)

        if total != amount:
            raise serializers.ValidationError(
                {"items": f"The items add up to {total}, but the expense is {amount}."}
            )

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        items = validated_data.pop("items", [])
        participants = validated_data.pop("participants", [])

        expense = Expense.objects.create(**validated_data)
        expense.participants.set(participants)
        self._write_items(expense, items)

        return expense

    @transaction.atomic
    def update(self, instance, validated_data):
        items = validated_data.pop("items", None)
        participants = validated_data.pop("participants", None)

        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()

        if participants is not None:
            instance.participants.set(participants)

        # None means "not mentioned", [] means "remove them all". Collapsing
        # the two would make every PATCH that omits items silently delete
        # them, which is the classic nested-write data loss.
        if items is not None:
            instance.items.all().delete()
            self._write_items(instance, items)

        return instance

    @staticmethod
    def _write_items(expense, items):
        """Replace an expense's items wholesale.

        Deliberately not a diff. Line items have no client-supplied stable
        identity -- two lines can share a name and an amount -- so matching
        incoming rows to stored ones would need an id the caller does not
        have. Replacing is honest about that; the through rows go with them
        because ItemShare cascades from the item.
        """
        for item_data in items:
            shares = item_data.pop("shares", [])
            item = ExpenseItem.objects.create(expense=expense, **item_data)
            ItemShare.objects.bulk_create([ItemShare(item=item, **share) for share in shares])
