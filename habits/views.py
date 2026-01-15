from decimal import Decimal
from habits import models, serializers, signals
from rest_framework import viewsets, permissions
from rest_framework.routers import DefaultRouter

from habits.permissions import IsInBoardPermission


class UserViewSet(viewsets.ModelViewSet):
    queryset = models.User.objects.all()
    serializer_class = serializers.UserSerializer
    permission_classes = [permissions.IsAuthenticated]


class HabitViewSet(viewsets.ModelViewSet):
    queryset = models.Habit.objects.all()
    serializer_class = serializers.HabitSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return self.queryset.filter(users__user=self.request.user)  # type: ignore


class BoardsViewSet(viewsets.ModelViewSet):
    queryset = models.Board.objects.all()
    serializer_class = serializers.BoardSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return self.queryset.filter(users__user=self.request.user)  # type: ignore


class ExpenseViewSet(viewsets.ModelViewSet):
    queryset = models.Expense.objects.all()
    serializer_class = serializers.ExpenseSerializer
    permission_classes = [permissions.IsAuthenticated, IsInBoardPermission]
    lookup_field = "id"

    def get_queryset(self):
        return self.queryset.filter(board__users__user=self.request.user)  # type: ignore

    def get_serializer_class(self):
        if self.action == "create" or self.action == "update" or self.action == "partial_update":
            return serializers.ExpenseCreateUpdateSerializer
        return super().get_serializer_class()


router = DefaultRouter()
router.register(r"users", UserViewSet)
router.register(r"habits", HabitViewSet)
router.register(r"boards", BoardsViewSet)
router.register(r"expenses", ExpenseViewSet)
