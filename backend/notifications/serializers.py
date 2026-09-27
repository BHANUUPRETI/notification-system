"""DRF serializers."""

from __future__ import annotations

from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import serializers

from .constants import CHANNEL_ORDER, Channel, ProviderStatus, SendStatus, TriggerKind
from .models import (
    NotificationLog,
    PushSubscription,
    Template,
    Trigger,
    UserProfile,
)
from .renderer import extract_placeholders, render
from .services.context import STANDARD_VARIABLE_PATHS, apply_variable_mapping, build_context

User = get_user_model()


# ---------------------------------------------------------------------------
# Users / auth
# ---------------------------------------------------------------------------
class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = [
            "phone_e164",
            "whatsapp_opt_in",
            "email_opt_in",
            "webpush_opt_in",
            "last_seen_at",
        ]
        read_only_fields = ["last_seen_at"]


class UserSerializer(serializers.ModelSerializer):
    profile = UserProfileSerializer(read_only=True)
    is_admin = serializers.SerializerMethodField()
    push_subscriptions = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "is_staff",
            "is_admin",
            "date_joined",
            "last_login",
            "profile",
            "push_subscriptions",
        ]
        read_only_fields = fields

    def get_is_admin(self, obj) -> bool:
        return bool(obj.is_staff or obj.is_superuser)

    def get_push_subscriptions(self, obj) -> list[dict]:
        return [
            {
                "id": sub.pk,
                "provider": sub.provider,
                "is_active": sub.is_active,
                "created_at": sub.created_at,
            }
            for sub in obj.push_subscriptions.all()[:10]
        ]


class LoginSerializer(serializers.Serializer):
    identifier = serializers.CharField(help_text="Username or email.")
    password = serializers.CharField(write_only=True, style={"input_type": "password"})

    def validate(self, attrs):
        user = authenticate(
            request=self.context.get("request"),
            username=attrs["identifier"],
            password=attrs["password"],
        )
        if user is None:
            raise serializers.ValidationError(
                {"detail": "Incorrect username/email or password."}
            )
        if not user.is_active:
            raise serializers.ValidationError({"detail": "This account is disabled."})
        attrs["user"] = user
        return attrs


class RegisterSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)
    first_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    last_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    phone_number = serializers.CharField(required=False, allow_blank=True, max_length=24)

    def validate_username(self, value):
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("This username is already in use.")
        return value

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("This email is already registered.")
        return value.lower()

    def create(self, validated_data):
        phone = validated_data.pop("phone_number", "")
        user = User.objects.create_user(**validated_data)
        profile, _ = UserProfile.objects.get_or_create(user=user)
        if phone:
            profile.phone_e164 = phone
            profile.save(update_fields=["phone_e164", "updated_at"])
        profile.mark_seen()
        return user


# ---------------------------------------------------------------------------
# Triggers & templates
# ---------------------------------------------------------------------------
class TriggerKeyField(serializers.Field):
    """Readable + writable trigger key (``"login"``) instead of a raw pk."""

    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        super().__init__(**kwargs)

    def to_representation(self, obj):
        return obj.trigger.key

    def to_internal_value(self, data):
        if not isinstance(data, str) or not data.strip():
            raise serializers.ValidationError("Must be a trigger key, e.g. 'login'.")
        return data.strip()


class TemplateSerializer(serializers.ModelSerializer):
    trigger = serializers.PrimaryKeyRelatedField(
        queryset=Trigger.objects.all(), required=False
    )
    trigger_key = TriggerKeyField()
    channel_label = serializers.CharField(source="get_channel_display", read_only=True)
    placeholder_count = serializers.SerializerMethodField()

    class Meta:
        model = Template
        fields = [
            "id",
            "trigger",
            "trigger_key",
            "channel",
            "channel_label",
            "title",
            "subject",
            "body",
            "provider_template_name",
            "provider_template_id",
            "provider_language",
            "provider_status",
            "provider_status_label",
            "provider_status_note",
            "provider_submitted_at",
            "is_enabled",
            "variables",
            "variable_mapping",
            "placeholder_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "variables",
            "provider_template_id",
            "provider_submitted_at",
            "created_at",
            "updated_at",
        ]
        # The model has UniqueConstraint(trigger, channel) and DRF >= 3.15 turns
        # that into a UniqueTogetherValidator, which would demand `trigger` on
        # every create - but we accept `trigger_key` instead. The duplicate is
        # already checked in validate() with a friendlier message, and the
        # database constraint remains the real guard.
        validators: list = []

    provider_status_label = serializers.CharField(
        source="get_provider_status_display", read_only=True
    )

    def get_placeholder_count(self, obj) -> int:
        return len(obj.variables or [])

    def validate_channel(self, value: str) -> str:
        if value not in Channel.values:
            raise serializers.ValidationError(f"Unknown channel '{value}'.")
        return value

    def validate(self, attrs):
        # Resolve the trigger from either `trigger=<id>` or `trigger_key="login"`.
        trigger = attrs.get("trigger") or getattr(self.instance, "trigger", None)
        if trigger is None and attrs.get("trigger_key"):
            key = attrs["trigger_key"]
            trigger = Trigger.objects.filter(key=key).first()
            if trigger is None:
                raise serializers.ValidationError(
                    {"trigger_key": f"No trigger with key '{key}'."}
                )
        if trigger is None:
            raise serializers.ValidationError(
                {"trigger_key": "A trigger_key (or trigger id) is required."}
            )
        attrs["trigger"] = trigger
        attrs.pop("trigger_key", None)

        channel = attrs.get("channel") or getattr(self.instance, "channel", None)
        body = attrs.get("body", getattr(self.instance, "body", ""))
        subject = attrs.get("subject", getattr(self.instance, "subject", ""))
        title = attrs.get("title", getattr(self.instance, "title", ""))

        if not (body or "").strip():
            raise serializers.ValidationError({"body": "Message body cannot be empty."})
        if channel == Channel.EMAIL and not (subject or "").strip():
            raise serializers.ValidationError(
                {"subject": "An email subject is required."}
            )
        if channel == Channel.WEBPUSH and not (title or "").strip():
            raise serializers.ValidationError(
                {"title": "A Web Push title is required."}
            )

        # --- WhatsApp template approval -----------------------------------
        # These fields only mean something for WhatsApp, so a status on an
        # email/web-push template is coerced back to "not submitted" rather
        # than stored as misleading data.
        effective_channel = channel
        if effective_channel != Channel.WHATSAPP:
            if attrs.get("provider_status", None) not in (None, ProviderStatus.NOT_SUBMITTED):
                attrs["provider_status"] = ProviderStatus.NOT_SUBMITTED
                attrs["provider_status_note"] = ""
                attrs["provider_submitted_at"] = None
        else:
            status = attrs.get("provider_status") or getattr(
                self.instance, "provider_status", ProviderStatus.NOT_SUBMITTED
            )
            template_name = attrs.get(
                "provider_template_name",
                getattr(self.instance, "provider_template_name", ""),
            )
            if status != ProviderStatus.NOT_SUBMITTED and not (template_name or "").strip():
                raise serializers.ValidationError(
                    {
                        "provider_template_name": (
                            "Add the Meta template name, or set the status back to "
                            "'Not submitted to Meta'."
                        )
                    }
                )

        used_variables = set(extract_placeholders(title, subject, body))
        mapping = attrs.get(
            "variable_mapping",
            getattr(self.instance, "variable_mapping", {}) if self.instance else {},
        )
        if mapping is None:
            mapping = {}
        if not isinstance(mapping, dict):
            raise serializers.ValidationError(
                {"variable_mapping": "Must be a JSON object mapping variables to safe sources."}
            )
        allowed_sources = set(STANDARD_VARIABLE_PATHS.values()) | set(STANDARD_VARIABLE_PATHS.keys())
        invalid_sources = sorted(
            source for source in mapping.values()
            if not isinstance(source, str) or source not in allowed_sources
        )
        if invalid_sources:
            raise serializers.ValidationError(
                {"variable_mapping": f"Unsupported mapping source(s): {', '.join(map(str, invalid_sources))}."}
            )
        unknown_variables = sorted(
            name for name in used_variables
            if name not in STANDARD_VARIABLE_PATHS and name not in mapping
        )
        if unknown_variables:
            raise serializers.ValidationError(
                {
                    "variable_mapping": (
                        "Map or remove unknown variable(s): " + ", ".join(unknown_variables)
                    )
                }
            )
        attrs["variable_mapping"] = mapping

        if self.instance is None:
            existing = Template.objects.filter(trigger=trigger, channel=channel).first()
            if existing is not None:
                raise serializers.ValidationError(
                    {
                        "channel": (
                            f"A {channel} template already exists for "
                            f"'{trigger.key}'. Edit it instead."
                        )
                    }
                )
        return attrs


class TriggerSerializer(serializers.ModelSerializer):
    templates = TemplateSerializer(many=True, read_only=True)
    template_count = serializers.SerializerMethodField()
    enabled_channels = serializers.SerializerMethodField()

    class Meta:
        model = Trigger
        fields = [
            "id",
            "key",
            "name",
            "description",
            "kind",
            "config",
            "is_active",
            "order",
            "days",
            "templates",
            "template_count",
            "enabled_channels",
            "updated_at",
        ]
        # `key` is writable but optional: it is derived from `name` in validate().
        read_only_fields = ["id", "updated_at", "days", "enabled_channels"]
        extra_kwargs = {"key": {"required": False, "allow_blank": True}}

    def get_template_count(self, obj) -> int:
        return obj.templates.count()

    def get_enabled_channels(self, obj) -> list[str]:
        return [
            t.channel
            for t in obj.templates.filter(is_enabled=True)
            if t.channel in CHANNEL_ORDER
        ]

    def get_days(self, obj):
        return obj.days

    def validate(self, attrs):
        # --- key: derive from the name when the admin left it blank --------
        if not (attrs.get("key") or getattr(self.instance, "key", "")):
            base = slugify(attrs.get("name", ""))[:60].strip("-")
            if not base:
                raise serializers.ValidationError(
                    {"name": "A trigger needs a name (or an explicit key)."}
                )
            key, n = base, 2
            while Trigger.objects.filter(key=key).exists():
                key = f"{base}-{n}"
                n += 1
            attrs["key"] = key

        # --- config must be an object -------------------------------------
        config = attrs.get("config")
        if config is None:
            config = getattr(self.instance, "config", None) or {}
        if not isinstance(config, dict):
            raise serializers.ValidationError({"config": "Must be a JSON object."})
        config = dict(config)

        # --- an inactivity trigger needs a usable window ------------------
        kind = attrs.get("kind") or getattr(self.instance, "kind", TriggerKind.EVENT)
        if kind == TriggerKind.INACTIVITY:
            try:
                days = int(config.get("days", 0))
            except (TypeError, ValueError):
                days = 0
            if days <= 0:
                raise serializers.ValidationError(
                    {
                        "config": (
                            "An inactivity trigger needs how many days count as "
                            "inactive, e.g. {\"days\": 7}."
                        )
                    }
                )
            if days > 365:
                raise serializers.ValidationError(
                    {"config": "Use 365 days or fewer."}
                )
            config["days"] = days
        else:
            config.pop("days", None)

        attrs["config"] = config
        return attrs


class TriggerToggleSerializer(serializers.Serializer):
    is_active = serializers.BooleanField()


# ---------------------------------------------------------------------------
# Push subscriptions
# ---------------------------------------------------------------------------
class PushSubscriptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PushSubscription
        fields = [
            "id",
            "provider",
            "endpoint",
            "p256dh",
            "auth",
            "onesignal_subscription_id",
            "is_active",
            "created_at",
            "last_seen_at",
        ]
        read_only_fields = ["id", "created_at", "last_seen_at", "is_active"]

    def validate_endpoint(self, value: str) -> str:
        if not value.startswith("https://"):
            raise serializers.ValidationError("Push endpoints must be HTTPS.")
        return value


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------
class NotificationLogSerializer(serializers.ModelSerializer):
    trigger_key = serializers.CharField(source="trigger.key", read_only=True, default=None)
    channel_label = serializers.CharField(source="get_channel_display", read_only=True)
    username = serializers.CharField(source="user.username", read_only=True, default=None)

    class Meta:
        model = NotificationLog
        fields = [
            "id",
            "trigger",
            "trigger_key",
            "channel",
            "channel_label",
            "status",
            "username",
            "destination",
            "rendered_title",
            "rendered_subject",
            "rendered_body",
            "provider",
            "provider_message_id",
            "provider_response",
            "error",
            "is_test",
            "dedupe_key",
            "created_at",
            "sent_at",
        ]
        read_only_fields = fields


# ---------------------------------------------------------------------------
# Test send
# ---------------------------------------------------------------------------
class TestSendSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(
        required=False, help_text="Defaults to the signed-in admin."
    )
    email = serializers.CharField(required=False, allow_blank=True)
    phone = serializers.CharField(required=False, allow_blank=True)

    def validate_user_id(self, value):
        if not User.objects.filter(pk=value).exists():
            raise serializers.ValidationError("No such user.")
        return value


class DraftTestSerializer(serializers.Serializer):
    """Test a template that has not been saved yet (used by the live editor)."""

    trigger_key = serializers.CharField()
    channel = serializers.ChoiceField(choices=Channel.choices)
    title = serializers.CharField(required=False, allow_blank=True)
    subject = serializers.CharField(required=False, allow_blank=True)
    body = serializers.CharField(required=False, allow_blank=True)
    provider_template_name = serializers.CharField(required=False, allow_blank=True)
    provider_language = serializers.CharField(required=False, allow_blank=True)
    provider_status = serializers.ChoiceField(choices=ProviderStatus.choices, required=False)
    variable_mapping = serializers.JSONField(required=False)
    user_id = serializers.IntegerField(required=False)
    email = serializers.CharField(required=False, allow_blank=True)
    phone = serializers.CharField(required=False, allow_blank=True)


class PreviewSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(required=False)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
class HealthSerializer(serializers.Serializer):
    status = serializers.CharField()
    time = serializers.DateTimeField(default=timezone.now)
    sandbox = serializers.BooleanField()


def render_preview(template: Template, user=None) -> dict:
    context = build_context(user, template.trigger)
    mapped_context = apply_variable_mapping(context, template.variable_mapping or {})
    return {
        "context": mapped_context,
        "title": render(template.title, mapped_context),
        "subject": render(template.subject, mapped_context),
        "body": render(template.body, mapped_context),
    }


__all__ = [
    "User",
    "UserSerializer",
    "UserProfileSerializer",
    "LoginSerializer",
    "RegisterSerializer",
    "TriggerSerializer",
    "TemplateSerializer",
    "TriggerToggleSerializer",
    "PushSubscriptionSerializer",
    "NotificationLogSerializer",
    "TestSendSerializer",
    "DraftTestSerializer",
    "PreviewSerializer",
    "HealthSerializer",
    "SendStatus",
    "default_token_generator",
    "render_preview",
]
