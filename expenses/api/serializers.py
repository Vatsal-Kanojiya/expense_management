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
    # The sixth appearance of the scoping lesson, and the one that was missed:
    # a plain PrimaryKeyRelatedField here accepted another user's participant
    # as the payer, and that name then surfaced on this user's balances.
    paid_by = ScopedPrimaryKeyRelatedField(
        queryset=Participant.objects.all(), required=False, allow_null=True
    )
    # The web form pre-selects the user's own participant; an API client has
    # no form, so without this default a request listing only Rahul would
    # charge Rahul the whole bill. Send false for a pure reimbursement.
    include_self = serializers.BooleanField(write_only=True, required=False, default=True)
    items = ExpenseItemSerializer(many=True, required=False)

    class Meta:
        model = Expense
        fields = [
            "id",
            "category",
            "amount",
            "spent_on",
            "note",
            "paid_by",
            "participants",
            "misc_amount",
            "misc_note",
            "include_self",
            "items",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("Amount must be greater than zero.")
        return value

    def validate_misc_amount(self, value):
        if value is not None and value <= 0:
            raise serializers.ValidationError("Misc amount must be greater than zero.")
        return value

    # The cross-row invariant used to be restated here as a second gate, so
    # that an API client got the same refusal the web form gave. Both gates
    # are gone: an expense whose items do not sum is now a legal record that
    # `balances` declines to split, not a rejected write. Keeping the check
    # here alone would have left the two entry points disagreeing about what
    # an expense is, which is worse than either rule on its own.
    #
    # What enforces the invariant now is that nothing consumes an unbalanced
    # expense: `Expense.is_balanced` is the predicate, `balances` skips, and
    # `check_splits` reports. The lesson survives the change -- a rule the
    # database cannot hold has to be restated at every entry point, and that
    # cost is exactly why this one stopped being a gate.

    def _with_self(self, participants, items, include_self):
        """Add the requesting user's own participant where a split names others."""
        if not include_self:
            return participants, items

        me = Participant.get_or_create_self(self.context["request"].user)

        if participants and me not in participants:
            participants = [*participants, me]

        for item in items or []:
            shares = item.get("shares") or []
            if shares and all(share["participant"] != me for share in shares):
                item["shares"] = [*shares, {"participant": me, "weight": 1}]

        return participants, items

    @transaction.atomic
    def create(self, validated_data):
        include_self = validated_data.pop("include_self", True)
        items = validated_data.pop("items", [])
        participants = validated_data.pop("participants", [])
        participants, items = self._with_self(participants, items, include_self)

        expense = Expense.objects.create(**validated_data)
        expense.participants.set(participants)
        self._write_items(expense, items)

        return expense

    @transaction.atomic
    def update(self, instance, validated_data):
        include_self = validated_data.pop("include_self", True)
        items = validated_data.pop("items", None)
        participants = validated_data.pop("participants", None)
        # Only what the request mentions is touched: None stays None, so a
        # PATCH of the note does not quietly add anyone to anything.
        participants, items = self._with_self(participants, items, include_self)

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
