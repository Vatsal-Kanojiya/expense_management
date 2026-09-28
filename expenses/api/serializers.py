"""Serializers, and the one thing that makes nested writes awkward.

DRF gives you readable nested output for free and writable nested input
never. ``ModelSerializer.create()`` refuses nested data because it cannot
guess the order, the ownership, or what "update" means for a list of
children. Writing that logic yourself is the point of this module.
"""

from django.db import transaction
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from expenses.models import BillScan, Category, Expense, ExpenseItem, ItemShare, Participant


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


MONEY = {"max_digits": 12, "decimal_places": 2}


class CategorySerializer(serializers.ModelSerializer):
    # The Categories page's columns. Annotated by with_category_activity, so
    # the page and the API report the same numbers from the same query.
    expense_count = serializers.IntegerField(read_only=True)
    total = serializers.DecimalField(**MONEY, read_only=True, allow_null=True)
    last_spent_on = serializers.DateField(read_only=True, allow_null=True)
    last_amount = serializers.DecimalField(**MONEY, read_only=True, allow_null=True)

    class Meta:
        model = Category
        fields = [
            "id",
            "name",
            "created_at",
            "expense_count",
            "total",
            "last_spent_on",
            "last_amount",
        ]
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
    # True for the one participant that stands for the signed-in user in
    # splits. The People page hides it; the API lists it, marked, because a
    # client needs its id for `paid_by` and `participants` (issue 34).
    is_self = serializers.BooleanField(read_only=True)
    shared_count = serializers.IntegerField(read_only=True)
    item_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Participant
        fields = ["id", "name", "is_self", "created_at", "shared_count", "item_count"]
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
    # Saving a scanned bill: the id from `bill-scans/{id}/prefill/`. On
    # create only, and each scan at most once -- the page enforced that by
    # 404ing the review URL of a saved scan; here it is a rule.
    bill_scan = ScopedPrimaryKeyRelatedField(
        queryset=BillScan.objects.all(),
        write_only=True,
        required=False,
        allow_null=True,
        help_text="On create only: the scan this expense was confirmed from.",
    )

    # Read-only conveniences, so a list can be rendered without a lookup per
    # row. The ids above stay the fields a client writes.
    category_name = serializers.CharField(source="category.name", read_only=True)
    paid_by_name = serializers.CharField(source="paid_by.name", read_only=True, allow_null=True)
    # The web form's warning, as data: an itemised expense whose lines and
    # misc amount do not add up is saved, but left out of balances until it
    # does. `unaccounted_amount` is positive when under, negative when over.
    # Both null when there are no line items: nothing to reconcile.
    items_total = serializers.DecimalField(**MONEY, read_only=True, allow_null=True)
    unaccounted_amount = serializers.SerializerMethodField()
    is_balanced = serializers.BooleanField(read_only=True)

    class Meta:
        model = Expense
        fields = [
            "id",
            "category",
            "category_name",
            "amount",
            "spent_on",
            "note",
            "paid_by",
            "paid_by_name",
            "participants",
            "misc_amount",
            "misc_note",
            "include_self",
            "bill_scan",
            "items",
            "items_total",
            "unaccounted_amount",
            "is_balanced",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("Amount must be greater than zero.")
        return value

    @extend_schema_field(serializers.DecimalField(**MONEY, allow_null=True))
    def get_unaccounted_amount(self, expense):
        return None if expense.items_total() is None else f"{expense.unaccounted_amount():.2f}"

    def validate_bill_scan(self, scan):
        if scan is None:
            return scan
        if self.instance is not None:
            raise serializers.ValidationError("A scan can only be attached when creating.")
        if scan.status != BillScan.Status.DONE:
            raise serializers.ValidationError("This bill has not finished scanning.")
        if scan.expense_id:
            raise serializers.ValidationError("This bill has already been saved as an expense.")
        return scan

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

    def validate(self, attrs):
        """The Django form's rules, restated at this entry point (D44, issue 45).

        Each rule checks the expense as it will be after the write, so a
        PATCH that sends only some fields is judged together with what is
        already saved.
        """
        instance = self.instance

        def current(field, default=None):
            return attrs[field] if field in attrs else getattr(instance, field, default)

        misc_amount = current("misc_amount")
        items = attrs.get("items")  # None: not sent. []: remove them all.
        has_items = bool(items) if items is not None else bool(instance and instance.items.exists())

        if misc_amount and not (current("misc_note", "") or "").strip():
            raise serializers.ValidationError(
                {"misc_note": ["Please describe what this misc amount is for."]}
            )
        if misc_amount and not has_items:
            raise serializers.ValidationError(
                {
                    "misc_amount": [
                        "A misc amount can only be added to an itemised expense with line items."
                    ]
                }
            )

        # With the owner out of the split, "nobody named means it is mine"
        # stops being true, and an unshared line would be quietly charged to
        # the owner anyway. Only checked when items are being written.
        if items:
            participants = attrs.get("participants")
            if participants is None:
                participants = list(instance.participants.all()) if instance else []
            participants, items_after = self._with_self(
                participants, [dict(item) for item in items], attrs.get("include_self", True)
            )
            everyone = self._with_item_people(participants, items_after)
            me = Participant.get_or_create_self(self.context["request"].user)

            if everyone and me not in everyone:
                errors = [
                    {}
                    if item.get("shares")
                    else {
                        "shares": ["You're not part of this expense, so choose who had this item."]
                    }
                    for item in items_after
                ]
                if any(errors):
                    raise serializers.ValidationError({"items": errors})

        return attrs

    @staticmethod
    def _with_item_people(participants, items):
        """Everyone the expense involves: its participants and each line's sharers.

        Written back as the expense's participants. The web edit form offers
        only the participants when it lists who had each line, so a share on
        anyone else would be dropped the first time the expense was saved on
        the web (issue 45).
        """
        people = list(participants or [])
        for item in items or []:
            for share in item.get("shares") or []:
                if share["participant"] not in people:
                    people.append(share["participant"])
        return people

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
        scan = validated_data.pop("bill_scan", None)
        participants, items = self._with_self(participants, items, include_self)
        participants = self._with_item_people(participants, items)

        expense = Expense.objects.create(**validated_data)
        expense.participants.set(participants)
        self._write_items(expense, items)

        if scan is not None:
            # Locked and re-checked inside this transaction: two saves of one
            # scan racing past validation must not both create an expense.
            # Raising here rolls the expense back with it.
            scan = BillScan.objects.select_for_update().get(pk=scan.pk)
            if scan.expense_id:
                raise serializers.ValidationError(
                    {"bill_scan": ["This bill has already been saved as an expense."]}
                )
            scan.expense = expense
            scan.save(update_fields=["expense"])

        return expense

    @transaction.atomic
    def update(self, instance, validated_data):
        include_self = validated_data.pop("include_self", True)
        validated_data.pop("bill_scan", None)  # refused on update by validate_bill_scan
        items = validated_data.pop("items", None)
        participants = validated_data.pop("participants", None)
        # Only what the request mentions is touched: None stays None, so a
        # PATCH of the note does not quietly add anyone to anything.
        participants, items = self._with_self(participants, items, include_self)
        if items is not None and any(item.get("shares") for item in items):
            if participants is None:
                participants = list(instance.participants.all())
            participants = self._with_item_people(participants, items)

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


class SplitPersonSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    is_self = serializers.BooleanField()


class SplitRowSerializer(serializers.Serializer):
    participant = SplitPersonSerializer()
    items = serializers.DecimalField(**MONEY, help_text="Their share of the lines or even split.")
    misc = serializers.DecimalField(**MONEY, help_text="Their share of tax, tip and the like.")
    total = serializers.DecimalField(**MONEY)


class ExpenseSplitSerializer(serializers.Serializer):
    expense = serializers.IntegerField()
    is_balanced = serializers.BooleanField()
    unaccounted_amount = serializers.DecimalField(**MONEY, allow_null=True)
    rows = SplitRowSerializer(many=True)
    items_total = serializers.DecimalField(**MONEY)
    misc_total = serializers.DecimalField(**MONEY)
    grand_total = serializers.DecimalField(**MONEY)
