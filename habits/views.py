import io
import re

import qrcode
import qrcode.image.svg
from django.http import JsonResponse
from django.shortcuts import render
from habits import models, serializers
from rest_framework import viewsets, permissions
from rest_framework.authtoken.models import Token
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.decorators import action
from rest_framework.generics import CreateAPIView
from rest_framework.response import Response
from rest_framework.routers import DefaultRouter
from rest_framework.throttling import ScopedRateThrottle

from habits.permissions import IsInBoardPermission

JOIN_CODE_RE = re.compile(r"\D")


def landing_page(request):
    return render(request, "landing.html")


def join_page(request):
    """Landing page for board invite links: tries the app deep link, and
    falls back to a QR code + button for people without the app open."""
    code = JOIN_CODE_RE.sub("", request.GET.get("code", ""))[:9]
    deep_link = f"echoes://join?code={code}" if code else "echoes://join"

    qr_svg = None
    if code:
        img = qrcode.make(deep_link, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=1)
        buf = io.BytesIO()
        img.save(buf)
        qr_svg = buf.getvalue().decode("utf-8")

    return render(
        request,
        "join.html",
        {"code": code, "deep_link": deep_link, "qr_svg": qr_svg},
    )


# iOS Universal Links: lets tapping an https://echoes.zelda.sh/join link open
# the app directly instead of Safari, on both the dev and prod bundle IDs.
def apple_app_site_association(request):
    return JsonResponse(
        {
            "applinks": {
                "apps": [],
                "details": [
                    {"appID": "ZK989FQ3CP.sh.zelda.echoes", "paths": ["/join"]},
                    {"appID": "ZK989FQ3CP.sh.zelda.echoes.dev", "paths": ["/join"]},
                ],
            }
        }
    )


# Android App Links equivalent of the above. sha256_cert_fingerprints must
# match the signing certificate used for the Play Store build.
def android_asset_links(request):
    return JsonResponse(
        [
            {
                "relation": ["delegate_permission/common.handle_all_urls"],
                "target": {
                    "namespace": "android_app",
                    "package_name": "sh.zelda.echoes",
                    "sha256_cert_fingerprints": [
                        "20:01:70:51:B2:D1:DF:4D:8D:35:70:BB:32:C1:89:6B:DB:E3:25:87:99:7C:28:36:84:77:0B:2F:57:33:DD:43"
                    ],
                },
            }
        ],
        safe=False,
    )


class ThrottledObtainAuthToken(ObtainAuthToken):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"


class RegisterView(CreateAPIView):
    serializer_class = serializers.RegisterSerializer
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "register"

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

    def get_throttles(self):
        if self.action in ("check_username", "check_email"):
            self.throttle_scope = "check-username"
            return [ScopedRateThrottle()]
        return super().get_throttles()

    def get_permissions(self):
        # Unauthenticated users need these to get live feedback while
        # choosing a username/email during signup.
        if self.action in ("check_username", "check_email"):
            return [permissions.AllowAny()]
        return super().get_permissions()

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
        methods=["get"],
        url_path="check-username",
        url_name="check-username",
    )
    def check_username(self, request, *args, **kwargs):
        username = request.query_params.get("username", "")
        if not username:
            return Response({"username": "This field is required."}, status=400)
        qs = models.User.objects.filter(username__iexact=username)
        if request.user.is_authenticated:
            qs = qs.exclude(pk=request.user.pk)
        available = not qs.exists()
        return Response({"available": available})

    @action(
        detail=False,
        methods=["get"],
        url_path="check-email",
        url_name="check-email",
    )
    def check_email(self, request, *args, **kwargs):
        email = request.query_params.get("email", "")
        if not email:
            return Response({"email": "This field is required."}, status=400)
        qs = models.User.objects.filter(email__iexact=email)
        if request.user.is_authenticated:
            qs = qs.exclude(pk=request.user.pk)
        available = not qs.exists()
        return Response({"available": available})

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

    def get_throttles(self):
        if self.action == "join":
            self.throttle_scope = "join"
            return [ScopedRateThrottle()]
        return super().get_throttles()

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

        _, created = models.BoardUser.objects.get_or_create(board=board, user=request.user)
        data = self.get_serializer(board).data
        data["already_member"] = not created
        return Response(data)

    @action(detail=True, methods=["post"], url_path="reset-code")
    def reset_code(self, request, pk=None):
        board = self.get_object()
        board.reset_join_code()
        return Response(self.get_serializer(board).data)

    @action(detail=True, methods=["post"])
    def leave(self, request, pk=None):
        board = self.get_object()
        if board.users.count() <= 1:  # type: ignore
            return Response(
                {"detail": "You're the only member of this board. Delete it instead of leaving."},
                status=400,
            )
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
