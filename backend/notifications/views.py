"""API views for the notification system."""

from __future__ import annotations

import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from . import tasks
from .constants import CHANNEL_ORDER, Channel
from .models import NotificationLog, PushSubscription, Template, Trigger, UserProfile
from .permissions import AllowAnyPublic, IsAdminUser
from .renderer import extract_placeholders
from .serializers import (
    DraftTestSerializer,
    HealthSerializer,
    LoginSerializer,
    RegisterSerializer,
    NotificationLogSerializer,
    PreviewSerializer,
    PushSubscriptionSerializer,
    TemplateSerializer,
    TestSendSerializer,
    TriggerSerializer,
    TriggerToggleSerializer,
    UserSerializer,
    render_preview,
)
from .services import dispatcher
from .services.context import build_context
from .services.registry import configuration_report, get_provider

logger = logging.getLogger(__name__)
User = get_user_model()


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------
class HealthView(APIView):
    permission_classes = [AllowAnyPublic]

    def get(self, request):
        payload = HealthSerializer(
            {"status": "ok", "sandbox": settings.NOTIFICATIONS["SANDBOX"]}
        ).data
        return Response(payload)


class PublicConfigView(APIView):
    """Everything the frontend needs before anyone has logged in."""

    permission_classes = [AllowAnyPublic]

    def get(self, request):
        webpush = get_provider(Channel.WEBPUSH)
        sample_user = request.user if request.user.is_authenticated else None
        return Response(
            {
                "sandbox": settings.NOTIFICATIONS["SANDBOX"],
                "frontend_url": settings.NOTIFICATIONS["FRONTEND_URL"],
                "channels": [
                    {"key": c, "label": c.capitalize()} for c in CHANNEL_ORDER
                ],
                "providers": configuration_report(),
                "vapid_public_key": webpush.public_key,
                "variables": VARIABLE_CATALOGUE,
                "push": {
                    # The browser needs to know which Web Push backend is live
                    # so it can subscribe through the matching path.
                    "backend": _push_backend(webpush),
                    "onesignal_app_id": settings.NOTIFICATIONS["PUSH"]["ONESIGNAL_APP_ID"],
                    "onesignal_configured": webpush.onesignal_configured,
                    "vapid_configured": webpush.vapid_configured,
                },
                "whatsapp": {
                    "api_version": settings.NOTIFICATIONS["WHATSAPP"]["API_VERSION"],
                    "language": settings.NOTIFICATIONS["WHATSAPP"]["TEMPLATE_LANGUAGE"],
                    "sync_configured": bool(
                        settings.NOTIFICATIONS["WHATSAPP"].get("ACCESS_TOKEN")
                        and settings.NOTIFICATIONS["WHATSAPP"].get("BUSINESS_ACCOUNT_ID")
                    ),
                    "template_console_url": WHATSAPP_TEMPLATE_CONSOLE_URL,
                },
            }
        )


def _push_backend(webpush) -> str:
    """Which Web Push transport the browser should use."""
    if webpush.onesignal_configured:
        return "onesignal"
    if webpush.vapid_configured:
        return "vapid"
    return "none"


#: Meta's template console, used for the manual submit/approve step.
WHATSAPP_TEMPLATE_CONSOLE_URL = "https://business.facebook.com/wa/manage/message-templates/"


VARIABLE_CATALOGUE = [
    {"name": "user", "example": "amit", "description": "Username"},
    {"name": "first_name", "example": "Amit", "description": "First name"},
    {"name": "last_name", "example": "Sharma", "description": "Last name"},
    {"name": "full_name", "example": "Amit Sharma", "description": "Full name"},
    {"name": "email", "example": "amit@example.com", "description": "Email address"},
    {"name": "phone", "example": "+919876543210", "description": "WhatsApp number"},
    {"name": "trigger", "example": "Not logged in 1 week", "description": "Trigger name"},
    {"name": "trigger_key", "example": "not_logged_in_1_week", "description": "Trigger key"},
    {"name": "days", "example": "7", "description": "Inactivity window (days)"},
    {"name": "days_away", "example": "7", "description": "Days since last visit"},
    {"name": "last_seen", "example": "2026-09-19T11:40:00+00:00", "description": "Last visit (ISO)"},
    {"name": "date", "example": "2026-09-26", "description": "Today's date"},
    {"name": "time", "example": "11:43", "description": "Current time"},
    {"name": "year", "example": "2026", "description": "Current year"},
    {"name": "month", "example": "09", "description": "Current month"},
    {"name": "day", "example": "26", "description": "Current day"},
    {"name": "site_name", "example": "Notify Demo", "description": "Site name"},
]


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        refresh = RefreshToken.for_user(user)
        token, _ = Token.objects.get_or_create(user=user)
        return Response(
            {
                "token": token.key,
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "user": UserSerializer(user).data,
            },
            status=status.HTTP_201_CREATED,
        )


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]

        # `authenticate()` does not emit user_logged_in, so the inactivity
        # triggers need last_seen_at updated explicitly.
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.mark_seen()
        user.last_login = timezone.now()
        user.save(update_fields=["last_login"])

        token, _ = Token.objects.get_or_create(user=user)
        refresh = RefreshToken.for_user(user)

        # Login is a trigger - fire it before handing credentials back.
        report = tasks.on_login(user)

        return Response(
            {
                "token": token.key,  # backwards-compatible with the existing frontend
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "user": UserSerializer(user).data,
                "notification": report.as_dict(),
            }
        )


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        try:
            # Logout is a trigger - fire it while we still have a user object.
            report = tasks.on_logout(user)
        finally:
            # Sign-out must succeed even if delivery blows up.
            Token.objects.filter(user=user).delete()
            refresh_value = (request.data or {}).get("refresh")
            if refresh_value:
                try:
                    RefreshToken(refresh_value).blacklist()
                except Exception:
                    logger.info("Refresh token was already invalid/expired during logout.")
        return Response({"detail": "Signed out.", "notification": report.as_dict()})


class ActivityView(APIView):
    """Heartbeat used to keep inactivity triggers based on real website visits."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        profile.mark_seen()
        return Response({"last_seen_at": profile.last_seen_at})


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data)

    def patch(self, request):
        serializer = UserSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class MyProfileView(APIView):
    """The signed-in user's own contact details and opt-ins."""

    permission_classes = [IsAuthenticated]

    def patch(self, request):
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        allowed = {"phone_e164", "whatsapp_opt_in", "email_opt_in", "webpush_opt_in"}
        payload = {k: v for k, v in (request.data or {}).items() if k in allowed}
        for field, value in payload.items():
            setattr(profile, field, value)
        profile.save()
        return Response(UserSerializer(request.user).data)


# ---------------------------------------------------------------------------
# Triggers  (admin)
# ---------------------------------------------------------------------------
class TriggerListCreateView(generics.ListCreateAPIView):
    queryset = Trigger.objects.all().prefetch_related("templates")
    serializer_class = TriggerSerializer
    permission_classes = [IsAdminUser]
    pagination_class = None


class TriggerDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Trigger.objects.all().prefetch_related("templates")
    serializer_class = TriggerSerializer
    permission_classes = [IsAdminUser]
    # The URL uses the human-readable slug, not the numeric id.
    lookup_field = "key"
    lookup_url_kwarg = "key"

    def perform_destroy(self, instance):
        instance.delete()


class TriggerToggleView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, key):
        trigger = get_object_or_404(Trigger, key=key)
        serializer = TriggerToggleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        trigger.is_active = serializer.validated_data["is_active"]
        trigger.save(update_fields=["is_active", "updated_at"])
        return Response(TriggerSerializer(trigger).data)


class TriggerFireView(APIView):
    """Fire a trigger immediately for a chosen user (demo / testing)."""

    permission_classes = [IsAdminUser]

    def post(self, request, key):
        trigger = get_object_or_404(Trigger, key=key)
        user_id = request.data.get("user_id")
        user = get_object_or_404(User, pk=user_id) if user_id else request.user
        report = tasks.fire(trigger.key, user, is_test=True)
        return Response(report.as_dict(), status=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# Templates  (admin)
# ---------------------------------------------------------------------------
class TemplateListCreateView(generics.ListCreateAPIView):
    queryset = Template.objects.select_related("trigger").all()
    serializer_class = TemplateSerializer
    permission_classes = [IsAdminUser]
    pagination_class = None

    def get_queryset(self):
        queryset = super().get_queryset()
        trigger_key = self.request.query_params.get("trigger")
        channel = self.request.query_params.get("channel")
        if trigger_key:
            queryset = queryset.filter(trigger__key=trigger_key)
        if channel:
            queryset = queryset.filter(channel=channel)
        return queryset

    def perform_create(self, serializer):
        # The serializer resolves the trigger from trigger_key / trigger itself.
        serializer.save()


class TemplateDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Template.objects.select_related("trigger").all()
    serializer_class = TemplateSerializer
    permission_classes = [IsAdminUser]


class TemplateToggleView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        template = get_object_or_404(Template, pk=pk)
        template.is_enabled = not template.is_enabled
        template.save(update_fields=["is_enabled", "updated_at"])
        return Response(TemplateSerializer(template).data)


class TemplatePreviewView(APIView):
    """Show the rendered copy with a real user's data, without sending."""

    permission_classes = [IsAdminUser]

    def get(self, request, pk):
        template = get_object_or_404(Template.objects.select_related("trigger"), pk=pk)
        serializer = PreviewSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        user = self._resolve_user(serializer.validated_data.get("user_id"), request)
        return Response(render_preview(template, user))

    def _resolve_user(self, user_id, request):
        if user_id:
            return get_object_or_404(User, pk=user_id)
        return request.user


class TemplateTestView(APIView):
    """Send a saved template to a real destination."""

    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        template = get_object_or_404(Template.objects.select_related("trigger"), pk=pk)
        serializer = TestSendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        user = (
            get_object_or_404(User, pk=data["user_id"])
            if data.get("user_id")
            else request.user
        )
        overrides = _overrides(template.channel, data)
        result = dispatcher.send_template(
            template,
            user,
            is_test=True,
            override=overrides.get(template.channel),
        )
        return Response(_as_payload(result))


class TemplateSyncView(APIView):
    """Refresh WhatsApp template approval state from the configured Meta WABA."""

    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        template = get_object_or_404(Template.objects.select_related("trigger"), pk=pk)
        if template.channel != Channel.WHATSAPP:
            return Response({"detail": "Sync is only available for WhatsApp templates."}, status=400)
        provider = get_provider(Channel.WHATSAPP)
        result = provider.sync_template(template.provider_template_name, template.provider_language)
        if not result.get("ok"):
            return Response({"detail": result.get("error", "Meta sync failed.")}, status=400)
        template.provider_template_id = result.get("provider_template_id", "")
        template.provider_template_name = result.get("provider_template_name", template.provider_template_name)
        template.provider_language = result.get("provider_language", template.provider_language)
        template.provider_status = result.get("provider_status", template.provider_status)
        template.provider_status_note = result.get("provider_status_note", "")
        template.save(
            update_fields=[
                "provider_template_id",
                "provider_template_name",
                "provider_language",
                "provider_status",
                "provider_status_note",
                "updated_at",
            ]
        )
        return Response(TemplateSerializer(template).data)


class DraftTestView(APIView):
    """Send copy straight from the editor before saving it."""

    permission_classes = [IsAdminUser]

    def post(self, request):
        serializer = DraftTestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        trigger = get_object_or_404(Trigger, key=data["trigger_key"])
        user = (
            get_object_or_404(User, pk=data["user_id"])
            if data.get("user_id")
            else request.user
        )
        result = dispatcher.send_draft(
            trigger=trigger,
            channel=data["channel"],
            user=user,
            body=data.get("body", ""),
            subject=data.get("subject", ""),
            title=data.get("title", ""),
            provider_template_name=data.get("provider_template_name", ""),
            provider_language=data.get("provider_language", ""),
            provider_status=data.get("provider_status", "not_submitted"),
            variable_mapping=data.get("variable_mapping") or {},
            override=_overrides(data["channel"], data).get(data["channel"]),
        )
        return Response(_as_payload(result))


# ---------------------------------------------------------------------------
# Push subscriptions
# ---------------------------------------------------------------------------
class PushSubscribeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = PushSubscriptionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sub, created = PushSubscription.objects.update_or_create(
            endpoint=serializer.validated_data["endpoint"],
            defaults={
                "user": request.user,
                "provider": serializer.validated_data.get("provider", PushSubscription.Provider.WEBPUSH),
                "p256dh": serializer.validated_data.get("p256dh", ""),
                "auth": serializer.validated_data.get("auth", ""),
                "onesignal_subscription_id": serializer.validated_data.get(
                    "onesignal_subscription_id", ""
                ),
                "user_agent": (request.headers.get("User-Agent") or "")[:300],
                "is_active": True,
                "failure_count": 0,
            },
        )
        return Response(
            PushSubscriptionSerializer(sub).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class PushUnsubscribeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        endpoint = (request.data or {}).get("endpoint", "")
        # Unsubscribe either the exact endpoint, or every subscription this
        # account owns (used when the browser reports a wiped subscription list).
        queryset = PushSubscription.objects.filter(is_active=True)
        if endpoint:
            queryset = queryset.filter(Q(endpoint=endpoint) | Q(user=request.user))
        else:
            queryset = queryset.filter(user=request.user)
        deactivated = queryset.update(is_active=False)
        return Response({"deactivated": deactivated})


class PushSubscriptionListView(generics.ListAPIView):
    queryset = PushSubscription.objects.select_related("user").all()
    serializer_class = PushSubscriptionSerializer
    permission_classes = [IsAdminUser]
    pagination_class = None


# ---------------------------------------------------------------------------
# Logs & users (admin)
# ---------------------------------------------------------------------------
class NotificationLogListView(generics.ListAPIView):
    serializer_class = NotificationLogSerializer
    permission_classes = [IsAdminUser]
    pagination_class = None

    def get_queryset(self):
        queryset = NotificationLog.objects.select_related("trigger", "user").all()
        params = self.request.query_params

        channel = params.get("channel")
        if channel:
            queryset = queryset.filter(channel=channel)
        st = params.get("status")
        if st:
            queryset = queryset.filter(status=st)
        trigger_key = params.get("trigger")
        if trigger_key:
            queryset = queryset.filter(trigger__key=trigger_key)
        is_test = params.get("is_test")
        if is_test in {"1", "true", "True"}:
            queryset = queryset.filter(is_test=True)
        elif is_test in {"0", "false", "False"}:
            queryset = queryset.filter(is_test=False)
        try:
            limit = min(int(params.get("limit", 100)), 500)
        except (TypeError, ValueError):
            limit = 100
        return queryset[:limit]


class AdminUserListView(generics.ListAPIView):
    serializer_class = UserSerializer
    permission_classes = [IsAdminUser]
    pagination_class = None

    def get_queryset(self):
        queryset = User.objects.select_related("profile").annotate(
            subs=Count("push_subscriptions", filter=Q(push_subscriptions__is_active=True))
        )
        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(
                Q(username__icontains=search)
                | Q(email__icontains=search)
                | Q(first_name__icontains=search)
            )
        return queryset.order_by("id")


class AdminStatsView(APIView):
    """Small summary used by the admin dashboard header."""

    permission_classes = [IsAdminUser]

    def get(self, request):
        since = timezone.now() - timezone.timedelta(days=7)
        logs = NotificationLog.objects.filter(created_at__gte=since)
        by_status = {
            row["status"]: row["n"]
            for row in logs.values("status").annotate(n=Count("id"))
        }
        by_channel = {
            row["channel"]: row["n"]
            for row in logs.values("channel").annotate(n=Count("id"))
        }
        return Response(
            {
                "triggers": Trigger.objects.count(),
                "templates": Template.objects.count(),
                "templates_enabled": Template.objects.filter(is_enabled=True).count(),
                "users": User.objects.count(),
                "push_subscriptions": PushSubscription.objects.filter(is_active=True).count(),
                "logs_last_7_days": {
                    "total": sum(by_status.values()),
                    "by_status": by_status,
                    "by_channel": by_channel,
                },
                "sandbox": settings.NOTIFICATIONS["SANDBOX"],
            }
        )


class InternalScanView(APIView):
    """Fire the inactivity triggers from an external scheduler.

    Render's free plan cannot run cron jobs, so point cron-job.org /
    GitHub Actions at this endpoint:

        curl -X POST https://<api>/api/internal/scan-inactive/ \\
             -H "X-Scan-Token: $SCAN_TOKEN"

    Set ``SCAN_TOKEN`` in the environment. If it is unset the endpoint is
    disabled and returns 404, so it can never be called by accident.
    """

    permission_classes = [AllowAnyPublic]
    authentication_classes: list = []

    def post(self, request):
        import hmac

        expected = settings.NOTIFICATIONS.get("SCAN_TOKEN") or ""
        if not expected:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        provided = request.headers.get("X-Scan-Token", "")
        if not hmac.compare_digest(provided, expected):
            return Response({"detail": "Invalid scan token."}, status=403)

        report = tasks.scan_inactive_users()
        return Response(report.as_dict())


class VariableScanView(APIView):
    """Report unknown placeholders used in the stored templates."""

    permission_classes = [IsAdminUser]

    def get(self, request):
        known = {item["name"] for item in VARIABLE_CATALOGUE}
        report = []
        for template in Template.objects.select_related("trigger").all():
            used = set(extract_placeholders(template.title, template.subject, template.body))
            unknown = sorted(used - known)
            if unknown:
                report.append(
                    {
                        "template_id": template.pk,
                        "trigger": template.trigger.key,
                        "channel": template.channel,
                        "unknown": unknown,
                    }
                )
        return Response({"unknown": report, "known": sorted(known)})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _overrides(channel: str, data: dict) -> dict:
    overrides: dict[str, str] = {}
    if data.get("email"):
        overrides[Channel.EMAIL] = data["email"]
    if data.get("phone"):
        overrides[Channel.WHATSAPP] = data["phone"]
    return overrides


def _as_payload(result: dispatcher.ChannelResult) -> dict:
    return {
        "channel": result.channel,
        "status": result.status,
        "message": result.message,
        "error": result.error,
        "destination": result.destination,
        "log_id": result.log_id,
    }


def _single(report: dispatcher.DispatchReport, channel: str) -> dict:
    for item in report.results:
        if item.channel == channel:
            return _as_payload(item)
    return {"channel": channel, "status": "skipped", "message": "No result."}


def build_context_for(trigger, user) -> dict:
    """Kept public for management commands / shell use."""
    return build_context(user, trigger)
