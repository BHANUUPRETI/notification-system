"""Shared constants for the notification system."""

from django.db import models


class Channel(models.TextChoices):
    """The three delivery channels from the spec."""

    WHATSAPP = "whatsapp", "WhatsApp"
    EMAIL = "email", "Email"
    WEBPUSH = "webpush", "Web Push"


CHANNEL_ORDER = [Channel.WHATSAPP, Channel.EMAIL, Channel.WEBPUSH]

#: Which field of the template is the "main" copy for each channel.
CHANNEL_PRIMARY_FIELD = {
    Channel.WHATSAPP: "body",
    Channel.EMAIL: "body",
    Channel.WEBPUSH: "body",
}


class TriggerKind(models.TextChoices):
    #: Fired explicitly by application code (login, order placed, ...).
    EVENT = "event", "Event"
    #: Fired by a scheduled scan based on a time window.
    INACTIVITY = "inactivity", "Inactivity window"


#: Trigger keys that must exist after `manage.py seed_triggers`.
TRIGGER_LOGIN = "login"
TRIGGER_LOGOUT = "logout"
TRIGGER_INACTIVE_1D = "not_logged_in_1_day"
TRIGGER_INACTIVE_1W = "not_logged_in_1_week"
TRIGGER_PASSWORD_RESET = "password_reset"
TRIGGER_ORDER_PLACED = "order_placed"


class SendStatus(models.TextChoices):
    SENT = "sent", "Sent"
    SIMULATED = "simulated", "Simulated (sandbox)"
    FAILED = "failed", "Failed"
    SKIPPED = "skipped", "Skipped"


class ProviderStatus(models.TextChoices):
    """Approval state of a WhatsApp template inside Meta.

    The provider template itself is managed by Meta. The application stores the
    latest state and can refresh it through the admin Sync action.
    """

    NOT_SUBMITTED = "not_submitted", "Not submitted to Meta"
    DRAFT = "draft", "Draft created in Meta"
    PENDING = "pending", "Pending review"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
