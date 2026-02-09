from decimal import Decimal
from habits import models, serializers, signals
from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.routers import DefaultRouter

from habits.permissions import IsInBoardPermission


class UserViewSet(viewsets.ModelViewSet):
    queryset = models.User.objects.all()
    serializer_class = serializers.UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    @action(detail=False, methods=["get"], url_path="me", url_name="get-me")
    def get_me(self, request, *args, **kwargs):
        serializer = self.get_serializer(request.user)
        return Response(serializer.data)


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
        queryset = self.queryset.filter(board__users__user=self.request.user)  # type: ignore

        # Filter by board if board_pk is in URL kwargs (nested route)
        board_pk = self.kwargs.get("board_pk")
        if board_pk is not None:
            queryset = queryset.filter(board__id=board_pk)

        return queryset

    def get_serializer_context(self):
        context = super().get_serializer_context()
        board_pk = self.kwargs.get("board_pk")
        if board_pk is not None:
            context["board_id"] = board_pk
        return context

    def get_serializer_class(self):
        if self.action == "create" or self.action == "update" or self.action == "partial_update":
            return serializers.ExpenseCreateUpdateSerializer
        return super().get_serializer_class()


router = DefaultRouter()
router.register(r"users", UserViewSet)
router.register(r"habits", HabitViewSet)
router.register(r"boards", BoardsViewSet, basename="board")
router.register(r"expenses", ExpenseViewSet)

# Nested route for board expenses
router.register(r"boards/(?P<board_pk>[^/.]+)/expenses", ExpenseViewSet, basename="board-expenses")
