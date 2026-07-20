import re

from habits import models, serializers
from rest_framework import viewsets, permissions
from rest_framework.authtoken.models import Token
from rest_framework.decorators import action
from rest_framework.generics import CreateAPIView
from rest_framework.response import Response
from rest_framework.routers import DefaultRouter

from habits.permissions import IsInBoardPermission


class RegisterView(CreateAPIView):
    serializer_class = serializers.RegisterSerializer
    permission_classes = [permissions.AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        token, _ = Token.objects.get_or_create(user=user)
        return Response({"token": token.key}, status=201)


class UserViewSet(viewsets.ModelViewSet):
    serializer_class = serializers.UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return models.User.objects.filter(pk=self.request.user.pk)

    @action(
        detail=False,
        methods=["get"],
        url_path="me",
        url_name="get-me",
    )
    def get_me(self, request, *args, **kwargs):
        serializer = self.get_serializer(request.user)
        return Response(serializer.data)

    @action(
        detail=False,
        methods=["post", "delete"],
        url_path="me/profile-picture",
        url_name="set-profile-picture",
    )
    def set_profile_picture(self, request, *args, **kwargs):
        if request.method == "DELETE":
            request.user.profile_picture.delete(save=True)
            return Response(status=204)
        image = request.FILES.get("profile_picture")
        if not image:
            return Response({"profile_picture": "This field is required."}, status=400)
        request.user.profile_picture = image
        request.user.save(update_fields=["profile_picture"])
        serializer = self.get_serializer(request.user)
        return Response(serializer.data)


class HabitViewSet(viewsets.ModelViewSet):
    queryset = models.Habit.objects.all()
    serializer_class = serializers.HabitSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return self.queryset.filter(board__users__user=self.request.user)


class BoardsViewSet(viewsets.ModelViewSet):
    queryset = models.Board.objects.all()
    serializer_class = serializers.BoardSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return self.queryset.filter(users__user=self.request.user)

    def perform_create(self, serializer):
        board = serializer.save(created_by=self.request.user)
        models.BoardUser.objects.create(board=board, user=self.request.user)

    @action(detail=False, methods=["post"])
    def join(self, request):
        code = re.sub(r"\D", "", str(request.data.get("code", "")))
        try:
            board = models.Board.objects.get(join_code=code)
        except models.Board.DoesNotExist:
            return Response({"detail": "Invalid code."}, status=404)

        models.BoardUser.objects.get_or_create(board=board, user=request.user)
        return Response(self.get_serializer(board).data)

    @action(detail=True, methods=["post"], url_path="reset-code")
    def reset_code(self, request, pk=None):
        board = self.get_object()
        board.reset_join_code()
        return Response(self.get_serializer(board).data)

    @action(detail=True, methods=["post"])
    def leave(self, request, pk=None):
        board = self.get_object()
        if models.BoardUser.objects.filter(user=request.user).count() <= 1:
            return Response({"detail": "You can't leave your only board."}, status=400)
        models.BoardUser.objects.filter(board=board, user=request.user).delete()
        return Response(status=204)


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
router.register(r"users", UserViewSet, basename="user")
router.register(r"habits", HabitViewSet)
router.register(r"boards", BoardsViewSet, basename="board")
router.register(r"expenses", ExpenseViewSet)

# Nested route for board expenses
router.register(r"boards/(?P<board_pk>[^/.]+)/expenses", ExpenseViewSet, basename="board-expenses")
