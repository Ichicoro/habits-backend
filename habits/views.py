import io
import re
from decimal import Decimal

import qrcode
import qrcode.image.svg
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q, Sum
from django.http import JsonResponse
from django.shortcuts import render
from django.utils.timezone import now
from habits import emails, models, notifications, serializers
from rest_framework import mixins, viewsets, permissions
from rest_framework.authtoken.models import Token
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
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


def _send_verification_email(request, user):
    token = models.EmailVerificationToken.objects.create(user=user)
    verify_url = request.build_absolute_uri(f"/verify-email?token={token.token}")
    emails.send_verification_email(user, verify_url)


def verify_email_page(request):
    """Landing page for the link in the "verify your email" email."""
    token = request.GET.get("token", "")
    verification_token = (
        models.EmailVerificationToken.objects.filter(token=token).select_related("user").first()
        if token
        else None
    )

    if verification_token is None:
        status = "invalid"
    elif verification_token.user.email_verified:
        status = "already"
    elif verification_token.is_expired:
        status = "expired"
    else:
        verification_token.user.email_verified = True
        verification_token.user.save(update_fields=["email_verified"])
        status = "success"

    return render(request, "verify_email.html", {"status": status})


def reset_password_page(request):
    """Handles both steps of password reset as a single web page: entering
    an email to request a reset link, and (once that link is followed)
    entering a new password. Deliberately not part of the app - a reset
    flow needs to work even when the user is signed out and has forgotten
    their credentials, so it can't depend on an authenticated app session."""
    token = request.GET.get("token") or request.POST.get("token", "")
    reset_token = None
    if token:
        reset_token = models.PasswordResetToken.objects.filter(token=token).select_related("user").first()
    token_valid = bool(reset_token and reset_token.is_valid)

    error = None
    sent = False
    success = False

    if request.method == "POST":
        if token:
            if not token_valid:
                error = "This reset link is invalid or has expired."
            else:
                password = request.POST.get("password", "")
                password_confirm = request.POST.get("password_confirm", "")
                if password != password_confirm:
                    error = "Passwords don't match."
                else:
                    try:
                        validate_password(password, user=reset_token.user)
                    except DjangoValidationError as exc:
                        error = " ".join(exc.messages)
                    else:
                        reset_token.user.set_password(password)
                        reset_token.user.save(update_fields=["password"])
                        reset_token.used_at = now()
                        reset_token.save(update_fields=["used_at"])
                        success = True
        else:
            email = request.POST.get("email", "").strip()
            if email:
                user = models.User.objects.filter(email__iexact=email).first()
                if user:
                    new_token = models.PasswordResetToken.objects.create(user=user)
                    reset_url = request.build_absolute_uri(f"/reset-password?token={new_token.token}")
                    emails.send_password_reset_email(user, reset_url)
                # Always report success, whether or not that email is
                # registered, so this can't be used to enumerate accounts.
                sent = True

    return render(
        request,
        "reset_password.html",
        {"token": token, "token_valid": token_valid, "error": error, "sent": sent, "success": success},
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
        transaction.on_commit(lambda: _send_verification_email(request, user))
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
        if self.action == "resend_verification":
            self.throttle_scope = "resend-verification"
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
        methods=["post"],
        url_path="resend-verification",
        url_name="resend-verification",
    )
    def resend_verification(self, request, *args, **kwargs):
        if request.user.email_verified:
            return Response({"detail": "Email is already verified."}, status=400)
        _send_verification_email(request, request.user)
        return Response(status=204)

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


class PushTokenViewSet(
    mixins.CreateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet
):
    queryset = models.PushToken.objects.all()
    serializer_class = serializers.PushTokenSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return self.queryset.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


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

    @action(detail=True, methods=["patch"], url_path="notifications")
    def notifications(self, request, pk=None):
        board = self.get_object()
        enabled = request.data.get("notify_on_expense")
        if not isinstance(enabled, bool):
            return Response(
                {"notify_on_expense": "This field is required and must be a boolean."}, status=400
            )
        models.BoardUser.objects.filter(board=board, user=request.user).update(
            notify_on_expense=enabled
        )
        return Response(self.get_serializer(board).data)

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

    @action(detail=True, methods=["post"], url_path="remove-user")
    def remove_user(self, request, pk=None):
        board = self.get_object()
        user_id = request.data.get("user_id")
        if not user_id:
            return Response({"detail": "user_id is required."}, status=400)
        if board.users.count() <= 1:  # type: ignore
            return Response(
                {"detail": "You're the only member of this board. Delete it instead of removing users."},
                status=400,
            )
        board_user = models.BoardUser.objects.filter(board=board, user_id=user_id).first()
        if board_user is None:
            return Response({"detail": "User is not a member of this board."}, status=404)
        board_user.delete()
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

    def perform_create(self, serializer):
        expense = serializer.save(created_by=self.request.user)
        transaction.on_commit(lambda: notifications.notify_expense_added(expense))

    @action(detail=False, methods=["get"], url_path="stats")
    def stats(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        total = queryset.aggregate(total=Sum("amount"))["total"] or Decimal("0")

        by_payer = queryset.values("payer").annotate(total=Sum("amount")).order_by("-total")
        paid_totals = {row["payer"]: row["total"] for row in by_payer}
        payer_users = models.User.objects.in_bulk(paid_totals.keys())
        by_user = [
            {"user": serializers.UserSerializer(payer_users[payer_id]).data, "total": total}
            for payer_id, total in sorted(paid_totals.items(), key=lambda item: -item[1])
        ]

        by_cat = queryset.values("category").annotate(total=Sum("amount")).order_by("-total")
        category_ids = [row["category"] for row in by_cat if row["category"] is not None]
        categories = models.ExpenseCategory.objects.in_bulk(category_ids)
        by_category = [
            {
                "category": serializers.ExpenseCategorySerializer(categories[row["category"]]).data
                if row["category"] is not None
                else None,
                "total": row["total"],
            }
            for row in by_cat
        ]

        # Net balance per user: what they paid minus what they owe across
        # their splits, i.e. "who owes whom" - same definition as
        # Board.get_balances(), but scoped to this (possibly date-filtered)
        # queryset rather than every expense on the board.
        owed_totals = {
            row["user"]: row["total"]
            for row in models.ExpenseSplit.objects.filter(expense__in=queryset)
            .values("user")
            .annotate(total=Sum("share_amount"))
        }
        balance_user_ids = set(paid_totals) | set(owed_totals)
        balance_users = models.User.objects.in_bulk(balance_user_ids)
        balances = sorted(
            (
                {
                    "user": serializers.UserSerializer(balance_users[user_id]).data,
                    "balance": paid_totals.get(user_id, Decimal("0")) - owed_totals.get(user_id, Decimal("0")),
                }
                for user_id in balance_user_ids
            ),
            key=lambda row: -row["balance"],
        )

        return Response(
            {"total": total, "by_user": by_user, "by_category": by_category, "balances": balances}
        )


class ExpenseCategoryViewSet(viewsets.ModelViewSet):
    queryset = models.ExpenseCategory.objects.all()
    serializer_class = serializers.ExpenseCategorySerializer
    permission_classes = [permissions.IsAuthenticated, IsInBoardPermission]

    def get_queryset(self):
        board_pk = self.kwargs.get("board_pk")
        return self.queryset.filter(Q(board__id=board_pk) | Q(board__isnull=True))

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["board_id"] = self.kwargs.get("board_pk")
        return context

    def get_serializer_class(self):
        if self.action == "create":
            return serializers.ExpenseCategoryCreateSerializer
        if self.action in ("update", "partial_update"):
            return serializers.ExpenseCategoryUpdateSerializer
        return super().get_serializer_class()

    def perform_update(self, serializer):
        if serializer.instance.board_id is None:
            raise ValidationError({"detail": "Cannot edit a global expense category."})
        serializer.save()

    def perform_destroy(self, instance):
        if instance.board_id is None:
            raise ValidationError({"detail": "Cannot delete a global expense category."})
        if instance.expenses.exists():
            raise ValidationError({"detail": "Cannot delete a category that is in use."})
        instance.delete()


router = DefaultRouter()
router.register(r"users", UserViewSet, basename="user")
router.register(r"habits", HabitViewSet)
router.register(r"boards", BoardsViewSet, basename="board")
router.register(r"expenses", ExpenseViewSet)
router.register(r"push-tokens", PushTokenViewSet, basename="push-token")

# Nested route for board expenses
router.register(r"boards/(?P<board_pk>[^/.]+)/expenses", ExpenseViewSet, basename="board-expenses")

# Nested route for board expense categories
router.register(
    r"boards/(?P<board_pk>[^/.]+)/expense-categories",
    ExpenseCategoryViewSet,
    basename="board-expense-categories",
)
