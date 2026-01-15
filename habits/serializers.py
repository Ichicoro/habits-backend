import datetime

from django.contrib.auth import get_user_model
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


class BoardSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Board
        fields = "__all__"


class ExpenseSplitSerializer(serializers.ModelSerializer):
    # Let DRF handle the UUID string for user; expense is not required on input
    user = serializers.PrimaryKeyRelatedField(queryset=get_user_model().objects.all())

    class Meta:
        model = models.ExpenseSplit
        fields = ("id", "user", "share_amount", "percentage")
        extra_kwargs = {
            "share_amount": {"required": False},
            "percentage": {"required": False},
        }

    def __init__(self, *args, requires_data=True, **kwargs):
        super().__init__(*args, **kwargs)
        if not requires_data:
            # For EQUAL splits you only send user IDs
            self.fields["share_amount"].required = False
            self.fields["percentage"].required = False
        else:
            # For other split types, share_amount is required
            self.fields["share_amount"].required = True


class ExpenseSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Expense
        fields = "__all__"

    splits = ExpenseSplitSerializer(many=True, read_only=True)


class ExpenseCreateUpdateSerializer(serializers.ModelSerializer):
    splits = ExpenseSplitSerializer(many=True, required=False)

    class Meta:
        model = models.Expense
        fields = "__all__"

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

    def create(self, validated_data):
        splits_data = validated_data.pop("splits", None)
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


class ExpenseUpdateSerializer(serializers.ModelSerializer):
    splits = ExpenseSplitSerializer(many=True, required=False)

    class Meta:
        model = models.Expense
        fields = "__all__"

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

    def update(self, instance, validated_data):
        splits_data = validated_data.pop("splits", None)
        # Update the expense fields (but not splits yet)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        # Now handle splits if provided
        if splits_data is not None:
            self.create_from_splits_data(instance, splits_data)
        return instance
