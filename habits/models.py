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

    def balance_in_board(self, board):
        paid = self.paid_expenses.filter(board=board).aggregate(total=models.Sum("amount"))["total"] or 0  # type: ignore
        owed = (
            ExpenseSplit.objects.filter(user=self, expense__board=board).aggregate(
                total=models.Sum("share_amount")
            )["total"]
            or 0
        )
        return float(paid - owed)


class Board(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, blank=False, null=False)
    description = models.TextField(blank=True, null=True)
    created_by = models.ForeignKey(
        get_user_model(), on_delete=models.DO_NOTHING, related_name="created_habit_boards"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

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

    def __str__(self):
        return f"{self.user.username} in {self.board.name}"


class HabitFrequency(models.TextChoices):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    CUSTOM = "custom"
    NONE = "none"


class Habit(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    board = models.ForeignKey(get_user_model(), on_delete=models.CASCADE, related_name="habits")
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

    def __str__(self):
        return f"{self.amount} spent by {self.payer.username} (category: {self.category.name if self.category else None})"
