from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from .constants import Channel, ProviderStatus, SendStatus, TriggerKind
from .renderer import extract_placeholders


class TriggerQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def ordered(self):
        return self.order_by("order", "name")


class Trigger(models.Model):
    """A row in the admin notification table.

    One trigger = one event on the site. Examples: ``login``, ``logout``,
    ``not_logged_in_1_week``.
    """

    key = models.SlugField(
        max_length=64,
        unique=True,
        help_text="Stable identifier used by the code that fires it, e.g. 'login'.",
    )
    name = models.CharField(max_length=120, help_text="Shown in the admin table.")
    description = models.TextField(blank=True)
    kind = models.CharField(
        max_length=20,
        choices=TriggerKind.choices,
        default=TriggerKind.EVENT,
        help_text=(
            "Event = fired by application code. "
            "Inactivity window = fired by the scheduled scanner."
        ),
    )
    config = models.JSONField(
        default=dict,
        blank=True,
        help_text='Extra settings. Inactivity triggers use {"days": 1}.',
    )
    is_active = models.BooleanField(
        default=True, help_text="Master switch for the whole trigger."
    )
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TriggerQuerySet.as_manager()

    class Meta:
        ordering = ["order", "name"]
        verbose_name = "trigger"
        verbose_name_plural = "triggers"

    def __str__(self) -> str:
        return f"{self.name} ({self.key})"

    @property
    def days(self) -> int | None:
        """Inactivity window in days, or None for event triggers."""
        if self.kind != TriggerKind.INACTIVITY:
            return None
        try:
            return int(self.config.get("days", 0)) or None
        except (TypeError, ValueError):
            return None

    def template_for(self, channel: str) -> "Template | None":
        return self.templates.filter(channel=channel).first()

    def enabled_templates(self):
        return self.templates.filter(is_enabled=True)


class Template(models.Model):
    """One cell of the admin table: the copy used for a trigger on a channel."""

    trigger = models.ForeignKey(
        Trigger, on_delete=models.CASCADE, related_name="templates"
    )
    channel = models.CharField(max_length=20, choices=Channel.choices)

    # --- copy -------------------------------------------------------------
    title = models.CharField(
        max_length=200,
        blank=True,
        help_text="Web Push notification title.",
    )
    subject = models.CharField(
        max_length=200,
        blank=True,
        help_text="Email subject line.",
    )
    body = models.TextField(
        blank=True,
        help_text="Message copy. Use {{ placeholders }} - see variables below.",
    )

    # --- provider specifics ----------------------------------------------
    provider_template_name = models.CharField(
        max_length=120,
        blank=True,
        help_text=(
            "WhatsApp only: the approved template name in Meta. Leave blank to "
            "send the body as free-form text (sandbox only)."
        ),
    )
    provider_template_id = models.CharField(
        max_length=120,
        blank=True,
        editable=False,
        help_text="WhatsApp only: Meta template id populated by Sync.",
    )
    provider_language = models.CharField(
        max_length=16,
        blank=True,
        help_text="WhatsApp only, e.g. en_US.",
    )

    # --- WhatsApp template approval (see ProviderStatus) ----------------
    provider_status = models.CharField(
        max_length=20,
        choices=ProviderStatus.choices,
        default=ProviderStatus.NOT_SUBMITTED,
        help_text=(
            "WhatsApp only: current Meta approval state. Use the admin Sync "
            "action to refresh this from the configured WhatsApp Business Account."
        ),
    )
    provider_status_note = models.CharField(
        max_length=300,
        blank=True,
        help_text="Why Meta rejected it, or any note about the submission.",
    )
    provider_submitted_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Set automatically the first time the status leaves 'not submitted'.",
        editable=False,
    )

    # --- behaviour --------------------------------------------------------
    is_enabled = models.BooleanField(
        default=True, help_text="Per-channel on/off toggle."
    )
    variables = models.JSONField(
        default=list,
        blank=True,
        editable=False,
        help_text="Auto-detected placeholders used by this template.",
    )
    variable_mapping = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Maps template variables to controlled application fields, e.g. "
            '{"first_name": "user.first_name"}.'
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["trigger__order", "trigger__name", "channel"]
        constraints = [
            models.UniqueConstraint(
                fields=["trigger", "channel"],
                name="unique_template_per_trigger_channel",
            )
        ]
        verbose_name = "template"
        verbose_name_plural = "templates"

    def __str__(self) -> str:
        return f"{self.trigger.key} / {self.get_channel_display()}"

    def save(self, *args, **kwargs):
        # Keep detected variables and safe default mappings in sync. Existing
        # admin-provided mappings are preserved; newly added known variables get
        # a controlled default source automatically.
        self.variables = extract_placeholders(self.title, self.subject, self.body)
        from .services.context import default_variable_mapping

        current_mapping = self.variable_mapping if isinstance(self.variable_mapping, dict) else {}
        defaults = default_variable_mapping(self.variables)
        self.variable_mapping = {**defaults, **current_mapping}

        # Stamp the first time this template leaves "not submitted" so the
        # admin can see how long it has been waiting on Meta.
        if (
            self.provider_status != ProviderStatus.NOT_SUBMITTED
            and not self.provider_submitted_at
        ):
            self.provider_submitted_at = timezone.now()
            # When the caller whitelists columns, our derived fields have to be
            # added to that whitelist or Django will silently skip them.
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                extra = [
                    name
                    for name in ("variables", "variable_mapping", "provider_submitted_at")
                    if name not in update_fields
                ]
                kwargs["update_fields"] = [*update_fields, *extra]

        super().save(*args, **kwargs)

    def preview(self, context: dict) -> dict:
        from .renderer import render

        return {
            "title": render(self.title, context),
            "subject": render(self.subject, context),
            "body": render(self.body, context),
        }


class UserProfile(models.Model):
    """Contact details + opt-ins for a site user."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    phone_e164 = models.CharField(
        max_length=24,
        blank=True,
        help_text="WhatsApp number in E.164 format, e.g. +919876543210.",
    )
    last_seen_at = models.DateTimeField(
        null=True, blank=True, help_text="Drives the inactivity triggers."
    )
    whatsapp_opt_in = models.BooleanField(default=True)
    email_opt_in = models.BooleanField(default=True)
    webpush_opt_in = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Profile<{self.user}>"

    def mark_seen(self):
        self.last_seen_at = timezone.now()
        self.save(update_fields=["last_seen_at", "updated_at"])

    @property
    def is_inactive_for(self) -> "timezone.datetime | None":
        if not self.last_seen_at:
            return None
        return timezone.now() - self.last_seen_at


class PushSubscription(models.Model):
    """A browser Web Push subscription (raw Web Push and/or OneSignal)."""

    class Provider(models.TextChoices):
        WEBPUSH = "webpush", "Raw Web Push (VAPID)"
        ONESIGNAL = "onesignal", "OneSignal"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="push_subscriptions",
        null=True,
        blank=True,
    )
    provider = models.CharField(
        max_length=20, choices=Provider.choices, default=Provider.WEBPUSH
    )
    endpoint = models.URLField(max_length=500)
    p256dh = models.CharField(max_length=255, blank=True)
    auth = models.CharField(max_length=255, blank=True)
    onesignal_subscription_id = models.CharField(max_length=64, blank=True, db_index=True)
    user_agent = models.CharField(max_length=300, blank=True)
    is_active = models.BooleanField(default=True)
    failure_count = models.PositiveIntegerField(default=0)
    last_seen_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "push subscription"
        verbose_name_plural = "push subscriptions"

    def __str__(self) -> str:
        return f"{self.provider}:{self.user or 'anon'}"

    def mark_failed(self):
        """Deactivate a subscription that a push service rejected (404/410)."""
        self.failure_count += 1
        if self.failure_count >= 3:
            self.is_active = False
        self.save(update_fields=["failure_count", "is_active", "last_seen_at"])


class NotificationLog(models.Model):
    """Audit trail for every send attempt, per channel."""

    trigger = models.ForeignKey(
        Trigger, on_delete=models.SET_NULL, null=True, blank=True, related_name="logs"
    )
    template = models.ForeignKey(
        Template,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="logs",
    )
    channel = models.CharField(max_length=20, choices=Channel.choices)
    status = models.CharField(
        max_length=20, choices=SendStatus.choices, default=SendStatus.SIMULATED
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notification_logs",
    )
    destination = models.CharField(
        max_length=300, blank=True, help_text="Where it went (masked)."
    )
    rendered_title = models.CharField(max_length=200, blank=True)
    rendered_subject = models.CharField(max_length=200, blank=True)
    rendered_body = models.TextField(blank=True)
    provider = models.CharField(max_length=40, blank=True)
    provider_message_id = models.CharField(max_length=200, blank=True)
    provider_response = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)
    is_test = models.BooleanField(default=False)
    dedupe_key = models.CharField(max_length=255, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "notification log"
        verbose_name_plural = "notification logs"

    def __str__(self) -> str:
        who = self.user or "system"
        return f"[{self.channel}/{self.status}] {self.trigger_id or '-'} -> {who}"
