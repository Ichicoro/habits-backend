import datetime

from django.contrib.auth import get_user_model
from django.db.models import Q
from habits import models
from rest_framework import serializers


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.User
        fields = ("id", "username", "email", "first_name", "last_name")


class HabitSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Habit
        fields = "__all__"


class ExpenseCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = models.ExpenseCategory
        fields = "__all__"


class BoardSerializer(serializers.ModelSerializer):
    expense_categories = serializers.SerializerMethodField()
    users = serializers.SerializerMethodField()

    class Meta:
        model = models.Board
        fields = (
            "id",
            "name",
            "users",
            "description",
            "created_by",
            "created_at",
            "updated_at",
            "expense_categories",
        )

    def get_expense_categories(self, obj):
        qs = models.ExpenseCategory.objects.filter(Q(board=obj) | Q(board__isnull=True)).order_by(
            "board"
        )
        return ExpenseCategorySerializer(qs, many=True).data

    def get_users(self, obj):
        board_users = obj.users.all()  # type: ignore
        return UserSerializer([bu.user for bu in board_users], many=True).data


class ExpenseSplitSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    # For deserial: accept either 'user' as a PK or keep the old field name
    user_input = serializers.PrimaryKeyRelatedField(
        queryset=get_user_model().objects.all(), source="user", write_only=True, required=False
    )

    class Meta:
        model = models.ExpenseSplit
        fields = ("id", "user", "share_amount", "percentage", "user_input")
        extra_kwargs = {
            "share_amount": {"required": False},
            "percentage": {"required": False},
        }

    def __init__(self, *args, requires_data=True, **kwargs):
        super().__init__(*args, **kwargs)
        if not requires_data:
            self.fields["share_amount"].required = False
            self.fields["percentage"].required = False
        else:
            self.fields["share_amount"].required = True

    def to_internal_value(self, data):
        # Support both 'user' and 'user_input' keys for backwards compatibility
        if "user" in data and "user_input" not in data:
            data = dict(data)
            data["user_input"] = data.pop("user")
        return super().to_internal_value(data)


class ExpenseSerializer(serializers.ModelSerializer):
    payer = UserSerializer(read_only=True)
    category = ExpenseCategorySerializer(read_only=True)
    splits = ExpenseSplitSerializer(many=True, read_only=True)

    class Meta:
        model = models.Expense
        fields = (
            "id",
            "board",
            "payer",
            "split_type",
            "amount",
            "description",
            "date",
            "created_at",
            "updated_at",
            "category",
            "splits",
        )
        read_only_fields = ("created_at", "updated_at")


class ExpenseCreateUpdateSerializer(serializers.ModelSerializer):
    splits = ExpenseSplitSerializer(many=True, required=False)
    payer_id = serializers.PrimaryKeyRelatedField(
        queryset=get_user_model().objects.all(), write_only=True, source="payer"
    )
    payer = UserSerializer(read_only=True)
    category = ExpenseCategorySerializer(read_only=True)
    category_id = serializers.PrimaryKeyRelatedField(
        queryset=models.ExpenseCategory.objects.all(), write_only=True, source="category"
    )
    board = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = models.Expense
        fields = "__all__"
        read_only_fields = ("created_at", "updated_at")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        split_type = self.initial_data.get("split_type") if self.initial_data else None  # type: ignore
        if split_type == models.ExpenseSplitType.EQUAL:
            self.fields["splits"] = ExpenseSplitSerializer(
                many=True, required=False, requires_data=False
            )

    def handle_equal_splits(self, expense, splits_data):
        if not splits_data:
            # BoardUser is your through model; each has .user
            users = [bu.user for bu in expense.board.users.all()]
        else:
            users = [sd["user"] for sd in splits_data]

        if not users:
            raise serializers.ValidationError("No users to split between.")

        # Enforce uniqueness by user id
        user_ids = [u.id for u in users]
        if len(user_ids) != len(set(user_ids)):
            raise serializers.ValidationError("Each user can appear only once in splits.")

        share = expense.amount / len(users)

        for user in users:
            models.ExpenseSplit.objects.update_or_create(
                expense=expense,
                user=user,
                defaults={"share_amount": share, "percentage": None},
            )

    def handle_percentage_splits(self, expense, splits_data):
        if not splits_data:
            raise serializers.ValidationError("Splits data is required for percentage split type")

        total_percentage = sum(sd["percentage"] for sd in splits_data)
        if total_percentage != 100:
            raise serializers.ValidationError("Total split percentage must equal 100%")

        users = [sd["user"] for sd in splits_data]
        user_ids = [u.id for u in users]
        if len(user_ids) != len(set(user_ids)):
            raise serializers.ValidationError("Each user can appear only once in splits.")

        for sd in splits_data:
            user = sd["user"]
            share_amount = (sd["percentage"] / 100) * expense.amount
            models.ExpenseSplit.objects.update_or_create(
                expense=expense,
                user=user,
                defaults={
                    "share_amount": share_amount,
                    "percentage": sd["percentage"],
                },
            )

    def handle_amount_splits(self, expense, splits_data):
        if not splits_data:
            raise serializers.ValidationError("Splits data is required for amount split type")

        total = sum(sd["share_amount"] for sd in splits_data)
        if total != expense.amount:
            raise serializers.ValidationError("Total split amount must equal the expense amount")

        users = [sd["user"] for sd in splits_data]
        user_ids = [u.id for u in users]
        if len(user_ids) != len(set(user_ids)):
            raise serializers.ValidationError("Each user can appear only once in splits.")

        for sd in splits_data:
            user = sd["user"]
            models.ExpenseSplit.objects.update_or_create(
                expense=expense,
                user=user,
                defaults={
                    "share_amount": sd["share_amount"],
                    "percentage": sd.get("percentage"),
                },
            )

    def create_from_splits_data(self, expense, splits_data):
        expense.splits.all().delete()
        if expense.split_type == models.ExpenseSplitType.AMOUNT:
            self.handle_amount_splits(expense, splits_data)
        elif expense.split_type == models.ExpenseSplitType.PERCENTAGE:
            self.handle_percentage_splits(expense, splits_data)
        elif expense.split_type == models.ExpenseSplitType.EQUAL:
            self.handle_equal_splits(expense, splits_data)

    def update_category(self, board, category_id):
        category = models.ExpenseCategory(id=category_id) if category_id else None
        if category:
            if category.board and category.board != board:
                raise serializers.ValidationError(
                    "Category does not belong to the specified board."
                )
        return category  # type: ignore

    def create(self, validated_data):
        splits_data = validated_data.pop("splits", None)
        board = models.Board.objects.get(id=self.context.get("board_id"))  # type: ignore
        validated_data["board"] = board  # type: ignore
        expense = models.Expense.objects.create(**validated_data)
        self.create_from_splits_data(expense, splits_data)
        expense.save()
        return expense

    def update(self, instance: models.Expense, validated_data):
        splits_data = validated_data.pop("splits", None)
        # Update the expense fields (but not splits yet)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        # Now handle splits if provided
        if splits_data is not None:
            self.create_from_splits_data(instance, splits_data)
        return instance
