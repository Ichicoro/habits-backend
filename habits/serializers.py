from decimal import ROUND_DOWN, Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.db.models import Q
from habits import models
from rest_framework import serializers


class UserSerializer(serializers.ModelSerializer):
    # Intentionally not use_url=True / request-absolute: build_absolute_uri()
    # depends on the Host header reaching Django correctly through whatever's
    # in front of gunicorn in prod, which isn't reliable there. The app
    # already resolves relative media paths against its own known-good API
    # base URL, so we hand back the raw relative path instead.
    profile_picture = serializers.SerializerMethodField()
    email_verified = serializers.BooleanField(source="is_email_verified", read_only=True)

    class Meta:
        model = models.User
        fields = (
            "id",
            "username",
            "name",
            "email",
            "first_name",
            "last_name",
            "profile_picture",
            "push_notifications_enabled",
            "email_verified",
        )

    def get_profile_picture(self, obj):
        return obj.profile_picture.url if obj.profile_picture else None

    def validate_username(self, value):
        qs = models.User.objects.filter(username__iexact=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A user with that username already exists.")
        return value

    def validate_email(self, value):
        qs = models.User.objects.filter(email__iexact=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A user with that email already exists.")
        return value


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])

    class Meta:
        model = models.User
        fields = ("username", "email", "password", "first_name")
        extra_kwargs = {
            "email": {"required": True},
            "first_name": {"required": False},
        }

    def validate_username(self, value):
        if models.User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("A user with that username already exists.")
        return value

    def validate_email(self, value):
        if models.User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with that email already exists.")
        return value

    def create(self, validated_data):
        password = validated_data.pop("password")
        user = models.User(**validated_data)
        user.set_password(password)
        user.save()
        return user


class PushTokenSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.PushToken
        fields = ("id", "token", "created_at", "last_seen_at")
        read_only_fields = ("created_at", "last_seen_at")
        # Uniqueness is handled via upsert in create() below, not rejected
        # up front - a token legitimately gets re-registered on reinstall
        # or when a different account logs in on the same device.
        extra_kwargs = {"token": {"validators": []}}

    def create(self, validated_data):
        # A token can be re-registered (app reinstall, account switch on the
        # same device) - upsert on the unique token rather than erroring.
        token, _ = models.PushToken.objects.update_or_create(
            token=validated_data["token"],
            defaults={"user": validated_data["user"]},
        )
        return token


class HabitSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Habit
        fields = "__all__"


class ExpenseCategorySerializer(serializers.ModelSerializer):
    in_use = serializers.SerializerMethodField()

    class Meta:
        model = models.ExpenseCategory
        fields = "__all__"

    def get_in_use(self, obj):
        return obj.expenses.exists()


class ExpenseCategoryCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.ExpenseCategory
        fields = ("id", "name", "emoji", "board", "created_at", "updated_at")
        read_only_fields = ("board", "created_at", "updated_at")

    def create(self, validated_data):
        board_id = self.context.get("board_id")
        if not board_id:
            raise serializers.ValidationError(
                {"board": "Categories must be created via /boards/<id>/expense-categories/."}
            )
        validated_data["board"] = models.Board.objects.get(id=board_id)
        return super().create(validated_data)


class ExpenseCategoryUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.ExpenseCategory
        fields = ("id", "name", "emoji", "board", "created_at", "updated_at")
        read_only_fields = ("board", "created_at", "updated_at")


class BoardSerializer(serializers.ModelSerializer):
    expense_categories = serializers.SerializerMethodField()
    users = serializers.SerializerMethodField()
    notify_on_expense = serializers.SerializerMethodField()

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
            "join_code",
            "notify_on_expense",
        )
        read_only_fields = ("created_by", "created_at", "updated_at", "join_code")

    def get_expense_categories(self, obj):
        qs = models.ExpenseCategory.objects.filter(Q(board=obj) | Q(board__isnull=True)).order_by(
            "board"
        )
        return ExpenseCategorySerializer(qs, many=True).data

    def get_users(self, obj):
        board_users = obj.users.all()  # type: ignore
        return UserSerializer([bu.user for bu in board_users], many=True).data

    def get_notify_on_expense(self, obj):
        # The requesting user's own notification preference for this board.
        request = self.context.get("request")
        if request is None or not request.user.is_authenticated:
            return None
        board_user = obj.users.filter(user=request.user).first()  # type: ignore
        return board_user.notify_on_expense if board_user else None


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
    created_by = UserSerializer(read_only=True)
    category = ExpenseCategorySerializer(read_only=True)
    splits = ExpenseSplitSerializer(many=True, read_only=True)

    class Meta:
        model = models.Expense
        fields = (
            "id",
            "board",
            "payer",
            "created_by",
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
        queryset=models.ExpenseCategory.objects.all(),
        write_only=True,
        source="category",
        required=False,
        allow_null=True,
    )
    board = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = models.Expense
        fields = "__all__"
        read_only_fields = ("created_at", "updated_at", "created_by")

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

        # Split to the cent, then hand any leftover pennies (from rounding)
        # to the first user so shares always sum exactly to expense.amount.
        cent = Decimal("0.01")
        share = (expense.amount / len(users)).quantize(cent, rounding=ROUND_DOWN)
        remainder = expense.amount - (share * len(users))

        for i, user in enumerate(users):
            user_share = share + remainder if i == 0 else share
            models.ExpenseSplit.objects.update_or_create(
                expense=expense,
                user=user,
                defaults={"share_amount": user_share, "percentage": None},
            )

    def handle_percentage_splits(self, expense, splits_data):
        if not splits_data:
            raise serializers.ValidationError("Splits data is required for percentage split type")

        total_percentage = sum(sd["percentage"] for sd in splits_data)
        if abs(total_percentage - Decimal("100")) > Decimal("0.01"):
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
        if abs(total - expense.amount) > Decimal("0.01"):
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
        board_id = self.context.get("board_id")
        if not board_id:
            raise serializers.ValidationError({"board": "Expenses must be created via /boards/<id>/expenses/."})
        board = models.Board.objects.get(id=board_id)
        validated_data["board"] = board
        with transaction.atomic():
            expense = models.Expense.objects.create(**validated_data)
            self.create_from_splits_data(expense, splits_data)
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
