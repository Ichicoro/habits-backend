import secrets
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.contrib.auth import get_user_model
from django.utils.timezone import now
import uuid


def get_today():
    return now().date()


from habits import managers


class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = ["email"]
    profile_picture = models.ImageField(upload_to="profile_pictures/", blank=True, null=True)
    push_notifications_enabled = models.BooleanField(default=True)
    email_verified = models.BooleanField(default=False)

    @property
    def name(self):
        return self.first_name or self.username

    def balance_in_board(self, board):
        paid = self.paid_expenses.filter(board=board).aggregate(total=models.Sum("amount"))["total"] or Decimal("0")  # type: ignore
        owed = (
            ExpenseSplit.objects.filter(user=self, expense__board=board).aggregate(
                total=models.Sum("share_amount")
            )["total"]
            or Decimal("0")
        )
        return paid - owed


def generate_token():
    return secrets.token_urlsafe(32)


class EmailVerificationToken(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        get_user_model(), on_delete=models.CASCADE, related_name="email_verification_tokens"
    )
    token = models.CharField(max_length=64, unique=True, default=generate_token, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = now() + timedelta(hours=24)
        super().save(*args, **kwargs)

    @property
    def is_expired(self):
        return now() >= self.expires_at

    def __str__(self):
        return f"Email verification token for {self.user.username}"


class PasswordResetToken(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        get_user_model(), on_delete=models.CASCADE, related_name="password_reset_tokens"
    )
    token = models.CharField(max_length=64, unique=True, default=generate_token, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = now() + timedelta(hours=1)
        super().save(*args, **kwargs)

    @property
    def is_valid(self):
        return self.used_at is None and now() < self.expires_at

    def __str__(self):
        return f"Password reset token for {self.user.username}"


def generate_join_code():
    # 9-digit numeric code, zero-padded; retried on the rare collision.
    while True:
        code = f"{secrets.randbelow(1_000_000_000):09d}"
        if not Board.objects.filter(join_code=code).exists():
            return code


class Board(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, blank=False, null=False)
    description = models.TextField(blank=True, null=True)
    join_code = models.CharField(max_length=9, unique=True, default=generate_join_code, editable=False)
    created_by = models.ForeignKey(
        get_user_model(),
        on_delete=models.SET_NULL,
        related_name="created_habit_boards",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def reset_join_code(self):
        self.join_code = generate_join_code()
        self.save(update_fields=["join_code"])

    def get_balances(self):
        # Detailed per-user balances
        user_balances = {}
        for boarduser in self.users.all():  # type: ignore
            paid_total = (
                self.expenses.filter(payer=boarduser.user).aggregate(models.Sum("amount"))["amount__sum"] or 0  # type: ignore
            )
            owed_total = (
                ExpenseSplit.objects.filter(expense__board=self, user=boarduser.user).aggregate(
                    models.Sum("share_amount")
                )[
                    "share_amount__sum"
                ]  # type: ignore
                or 0
            )
            user_balances[boarduser.user.id] = paid_total - owed_total
        return user_balances

    objects = managers.BalanceManager()

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return self.name


class BoardUserRole(models.TextChoices):
    ADMIN = "admin"
    MEMBER = "member"


class BoardUser(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name="users")
    user = models.ForeignKey(
        get_user_model(), on_delete=models.CASCADE, related_name="habit_boards"
    )
    joined_at = models.DateTimeField(auto_now_add=True)
    notify_on_expense = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.user.username} in {self.board.name}"


class PushToken(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        get_user_model(), on_delete=models.CASCADE, related_name="push_tokens"
    )
    token = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username}'s push token"


class HabitFrequency(models.TextChoices):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    CUSTOM = "custom"
    NONE = "none"


class Habit(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name="habits")
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    frequency = models.CharField(
        max_length=10, choices=HabitFrequency.choices, default=HabitFrequency.NONE
    )
    # custom_days = models.JSONField(blank=True, null=True, help_text="List of custom days in a week (e.g., ['Monday', 'Wednesday'] for a custom weekly habit)")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class ExpenseCategory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    emoji = models.CharField(max_length=10, default="💰")
    board = models.ForeignKey(
        Board, on_delete=models.CASCADE, related_name="expense_categories", null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.emoji} {self.name}"


class ExpenseSplitType(models.TextChoices):
    EQUAL = "equal"
    AMOUNT = "amount"
    PERCENTAGE = "percentage"


class ExpenseSplit(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    expense = models.ForeignKey("Expense", on_delete=models.CASCADE, related_name="splits")
    user = models.ForeignKey(
        get_user_model(), on_delete=models.CASCADE, related_name="expense_splits"
    )
    share_amount = models.DecimalField(max_digits=10, decimal_places=2)
    percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def calculated_share(self):
        return self.share_amount

    class Meta:
        unique_together = ("expense", "user")

    def __str__(self):
        return f"{self.user.username}'s {self.share_amount} split for {self.expense.amount}"


class Expense(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name="expenses")
    payer = models.ForeignKey(
        get_user_model(), on_delete=models.CASCADE, related_name="paid_expenses"
    )
    created_by = models.ForeignKey(
        get_user_model(),
        on_delete=models.SET_NULL,
        related_name="added_expenses",
        null=True,
        blank=True,
    )
    split_type = models.CharField(
        max_length=10, choices=ExpenseSplitType.choices, default=ExpenseSplitType.EQUAL
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.TextField(blank=True, null=True)
    date = models.DateField(default=get_today)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    category = models.ForeignKey(
        ExpenseCategory, on_delete=models.CASCADE, related_name="expenses", null=True, blank=True
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.amount} spent by {self.payer.username} (category: {self.category.name if self.category else None})"
