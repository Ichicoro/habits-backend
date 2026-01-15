from django.db.models import Manager, F, FloatField, Sum, OuterRef, Subquery
from django.db.models.functions import Coalesce
from . import models


class BalanceManager(Manager):
    def user_balances(self, board_id):
        group = models.Board.objects.get(id=board_id)

        # Paid: sum expenses where payer=user and expense.board_id=board_id
        paid_qs = (
            models.Expense.objects.filter(board_id=board_id, payer=OuterRef("pk"))
            .values("payer")
            .annotate(total=Sum("amount"))
            .values("total")
        )

        # Owed: sum shares where participant.user=pk and expense.board_id=board_id
        owed_qs = (
            models.ExpenseSplit.objects.filter(expense__board_id=board_id, user=OuterRef("pk"))
            .values("user")
            .annotate(total=Sum("share_amount"))
            .values("total")
        )

        users = (
            models.User.objects.filter(groups=group)
            .annotate(
                paid=Subquery(paid_qs, output_field=FloatField()),
                owed=Subquery(owed_qs, output_field=FloatField()),
                balance=F("paid") - Coalesce(F("owed"), 0),
            )
            .values("username", "paid", "owed", "balance")
        )
        return list(users)
