"""Fires a trigger: renders every enabled template and delivers it.



This is the single place that knows the order of operations, so the admin API,

the authentication views and the scheduled scanner all behave identically.

"""



from __future__ import annotations



import logging

from dataclasses import dataclass, field

from typing import Any, Iterable



from django.conf import settings

from django.db import transaction

from django.utils import timezone



from ..constants import CHANNEL_ORDER, Channel, ProviderStatus, SendStatus

from ..models import NotificationLog, PushSubscription, Template, Trigger

from ..renderer import TemplateRenderError, render

from .base import ProviderResult, mask_email, mask_endpoint, mask_phone

from .context import apply_variable_mapping, build_context

from .registry import get_provider



logger = logging.getLogger(__name__)





#: Sentinel telling :func:`_deliver_channel` to look the template up in the DB.

FROM_DATABASE = object()





@dataclass

class ChannelResult:

    channel: str

    status: str

    message: str = ""

    error: str = ""

    destination: str = ""

    log_id: int | None = None



    @property

    def ok(self) -> bool:

        return self.status in {SendStatus.SENT, SendStatus.SIMULATED}





@dataclass

class DispatchReport:

    trigger: str

    results: list[ChannelResult] = field(default_factory=list)



    @property

    def sent(self) -> list[ChannelResult]:

        return [r for r in self.results if r.status == SendStatus.SENT]



    @property

    def simulated(self) -> list[ChannelResult]:

        return [r for r in self.results if r.status == SendStatus.SIMULATED]



    @property

    def failed(self) -> list[ChannelResult]:

        return [r for r in self.results if r.status == SendStatus.FAILED]



    @property

    def skipped(self) -> list[ChannelResult]:

        return [r for r in self.results if r.status == SendStatus.SKIPPED]



    def as_dict(self) -> dict[str, Any]:

        return {

            "trigger": self.trigger,

            "results": [

                {

                    "channel": r.channel,

                    "status": r.status,

                    "message": r.message,

                    "error": r.error,

                    "destination": r.destination,

                    "log_id": r.log_id,

                }

                for r in self.results

            ],

            "summary": {

                "sent": len(self.sent),

                "simulated": len(self.simulated),

                "failed": len(self.failed),

                "skipped": len(self.skipped),

            },

        }





# ---------------------------------------------------------------------------

# Public API

# ---------------------------------------------------------------------------

def fire_trigger(

    trigger_key: str,

    user=None,

    *,

    is_test: bool = False,

    overrides: dict[str, str] | None = None,

    context_extra: dict[str, Any] | None = None,

    dedupe_key: str = "",

) -> DispatchReport:

    """Deliver *trigger_key* to *user* on every applicable channel."""

    overrides = overrides or {}

    try:

        trigger = Trigger.objects.get(key=trigger_key)

    except Trigger.DoesNotExist:

        report = DispatchReport(trigger=trigger_key)

        report.results.append(

            ChannelResult(

                channel="-",

                status=SendStatus.FAILED,

                error=f"Unknown trigger '{trigger_key}'.",

            )

        )

        return report



    report = DispatchReport(trigger=trigger.key)

    context = build_context(user, trigger, extra=context_extra)



    for channel in CHANNEL_ORDER:

        report.results.append(

            _deliver_channel(

                trigger=trigger,

                channel=channel,

                user=user,

                context=context,

                is_test=is_test,

                override=overrides.get(channel),

                dedupe_key=dedupe_key,

            )

        )



    logger.info(

        "Fired '%s' for %s -> %s",

        trigger.key,

        getattr(user, "username", "system"),

        ", ".join(f"{r.channel}:{r.status}" for r in report.results),

    )

    return report





@transaction.atomic

def _deliver_channel(

    *,

    trigger: Trigger,

    channel: str,

    user,

    context: dict[str, Any],

    is_test: bool,

    override: str | None = None,

    template_override: Any = FROM_DATABASE,

    dedupe_key: str = "",

) -> ChannelResult:

    template = (

        trigger.template_for(channel)

        if template_override is FROM_DATABASE

        else template_override

    )



    if template is None or not (template.body or "").strip():

        return _log(

            trigger=None,

            channel=channel,

            user=user,

            status=SendStatus.SKIPPED,

            error="No template configured for this channel.",

        )



    # Test sends deliberately bypass the on/off toggles so an admin can verify

    # copy before switching a channel on.

    if not is_test:

        if not trigger.is_active:

            return _log(

                trigger=trigger,

                template=template,

                channel=channel,

                user=user,

                status=SendStatus.SKIPPED,

                error="Trigger is switched off.",

            )

        if not template.is_enabled:

            return _log(

                trigger=trigger,

                template=template,

                channel=channel,

                user=user,

                status=SendStatus.SKIPPED,

                error="Channel toggle is off.",

            )

        if not _opted_in(user, channel):

            return _log(

                trigger=trigger,

                template=template,

                channel=channel,

                user=user,

                status=SendStatus.SKIPPED,

                error="User has opted out of this channel.",

            )



    # Real Web Push delivery must always target a concrete authenticated user.
    # Never sweep or borrow another user's subscription during a normal trigger.
    # Admin/test sends are intentionally exempt and may use any available device.
    if (
        channel == Channel.WEBPUSH
        and not is_test
        and (
            user is None
            or not getattr(user, "is_authenticated", False)
        )
    ):
        return _log(
            trigger=trigger,
            template=template,
            channel=channel,
            user=user,
            status=SendStatus.SKIPPED,
            destination="no subscription",
            error="Web Push requires an authenticated target user.",
            is_test=is_test,
            dedupe_key=dedupe_key,
        )

    provider = get_provider(channel)

    mapped_context = apply_variable_mapping(

        context, getattr(template, "variable_mapping", {}) or {}

    )



    try:

        if channel == Channel.EMAIL:

            rendered_subject = render(template.subject, mapped_context, strict=True) or f"Notification: {trigger.name}"

            rendered_title = ""

            rendered_body = render(template.body, mapped_context, strict=True)

            destination = mask_email(override or (getattr(user, "email", "") or ""))

            missing = not (override or getattr(user, "email", ""))

        elif channel == Channel.WEBPUSH:

            rendered_title = render(template.title, mapped_context, strict=True) or trigger.name

            rendered_subject = ""

            rendered_body = render(template.body, mapped_context, strict=True)

            subs = _subscriptions_for(user, allow_any=is_test)

            destination = mask_endpoint(subs[0].endpoint) if subs else "no subscription"

            missing = not subs

        else:  # WhatsApp

            phone = override or _phone_of(user)

            rendered_title = ""

            rendered_subject = ""

            rendered_body = render(template.body, mapped_context, strict=True)

            destination = mask_phone(phone)

            missing = not phone

    except TemplateRenderError as exc:

        return _log(

            trigger=trigger,

            template=template,

            channel=channel,

            user=user,

            status=SendStatus.FAILED,

            error=str(exc),

            is_test=is_test,

            dedupe_key=dedupe_key,

        )



    if (

        channel == Channel.WHATSAPP

        and (template.provider_template_name or "").strip()

        and getattr(template, "provider_status", ProviderStatus.NOT_SUBMITTED) != ProviderStatus.APPROVED

    ):

        return _log(

            trigger=trigger,

            template=template,

            channel=channel,

            user=user,

            status=SendStatus.SKIPPED,

            destination=destination,

            body=rendered_body,

            error="WhatsApp provider template is not approved yet. Sync the Meta status before sending.",

            is_test=is_test,

            dedupe_key=dedupe_key,

        )



    if missing:

        return _log(

            trigger=trigger,

            template=template,

            channel=channel,

            user=user,

            status=SendStatus.SKIPPED,

            destination=destination,

            error=_missing_destination_message(channel),

            is_test=is_test,

            dedupe_key=dedupe_key,

        )



    # --- sandbox short-circuit -----------------------------------------

    if settings.NOTIFICATIONS["SANDBOX"]:

        result = ProviderResult.simulated(provider.name)

    elif not provider.is_configured:

        result = ProviderResult.failed(provider.name, provider.missing_config_message())

    else:

        result = _call_provider(

            provider,

            channel=channel,

            user=user,

            template=template,

            subject=rendered_subject,

            body=rendered_body,

            title=rendered_title,

            override=override,

            allow_any=is_test,

        )



    status = result.status if result.status != SendStatus.SIMULATED else SendStatus.SIMULATED

    return _log(

        trigger=trigger,

        template=template,

        channel=channel,

        user=user,

        status=status,

        destination=destination,

        title=rendered_title,

        subject=rendered_subject,

        body=rendered_body,

        provider=result.provider,

        message_id=result.message_id,

        provider_response=_sanitize_provider_response(result.detail),

        error=result.error,

        is_test=is_test,

        dedupe_key=dedupe_key,

    )





def _call_provider(

    provider,

    *,

    channel: str,

    user,

    template: Template,

    subject: str,

    body: str,

    title: str,

    override: str | None,

    allow_any: bool = False,

) -> ProviderResult:

    if channel == Channel.WHATSAPP:

        return provider.send(

            user=user,

            subject=subject,

            body=body,

            title=title,

            to=override or "",

            template_name=(template.provider_template_name or "").strip(),

            language=template.provider_language or "",

        )

    if channel == Channel.EMAIL:

        return provider.send(

            user=user, subject=subject, body=body, title=title, to=override or ""

        )

    return provider.send(

        user=user,

        subject=subject,

        body=body,

        title=title,

        subscriptions=_subscriptions_for(user, allow_any=allow_any),

        url=settings.NOTIFICATIONS["FRONTEND_URL"],

    )





def send_template(

    template: Template,

    user,

    *,

    is_test: bool = True,

    override: str | None = None,

    context_extra: dict[str, Any] | None = None,

    dedupe_key: str = "",

) -> ChannelResult:

    """Deliver exactly one saved template/cell, never the other channels."""

    trigger = template.trigger

    context = build_context(user, trigger, extra=context_extra)

    return _deliver_channel(

        trigger=trigger,

        channel=template.channel,

        user=user,

        context=context,

        is_test=is_test,

        override=override,

        template_override=template,

        dedupe_key=dedupe_key,

    )





def send_draft(

    *,

    trigger: Trigger,

    channel: str,

    user,

    body: str = "",

    subject: str = "",

    title: str = "",

    provider_template_name: str = "",

    provider_language: str = "",

    provider_status: str = ProviderStatus.NOT_SUBMITTED,

    variable_mapping: dict[str, str] | None = None,

    override: str | None = None,

    context_extra: dict[str, Any] | None = None,

) -> ChannelResult:

    """Deliver copy that has **not** been saved yet (admin live editor).



    The template is never persisted, but the send is still logged so the admin

    can see the result in the activity feed.

    """

    draft = Template(

        trigger=trigger,

        channel=channel,

        body=body or "",

        subject=subject or "",

        title=title or "",

        provider_template_name=provider_template_name or "",

        provider_language=provider_language or "",

        provider_status=provider_status or ProviderStatus.NOT_SUBMITTED,

        variable_mapping=variable_mapping or {},

        is_enabled=True,

    )

    context = build_context(user, trigger, extra=context_extra)

    return _deliver_channel(

        trigger=trigger,

        channel=channel,

        user=user,

        context=context,

        is_test=True,

        override=override,

        template_override=draft,

    )





# ---------------------------------------------------------------------------

# Helpers

# ---------------------------------------------------------------------------

def _subscriptions_for(user, *, allow_any: bool = False) -> list[PushSubscription]:

    """Active Web Push subscriptions that may receive *this user's* message.



    A real send must only ever reach the recipient's own devices. The

    ``allow_any`` fallback exists for admin test sends, where the admin wants

    to see a push on whatever device is available even if the browser is not

    yet associated with their account. It is deliberately never used for

    normal delivery.

    """

    queryset = PushSubscription.objects.filter(is_active=True)

    if user is not None and getattr(user, "is_authenticated", False):

        own = list(queryset.filter(user=user).order_by("-last_seen_at"))

        if own:

            return own

        if not allow_any:

            return []

    if allow_any:

        return list(queryset.order_by("-last_seen_at"))

    return []





def _phone_of(user) -> str:

    profile = getattr(user, "profile", None)

    return (getattr(profile, "phone_e164", "") or "").strip()





def _opted_in(user, channel: str) -> bool:

    profile = getattr(user, "profile", None)

    if profile is None:

        return True

    return {

        Channel.WHATSAPP: profile.whatsapp_opt_in,

        Channel.EMAIL: profile.email_opt_in,

        Channel.WEBPUSH: profile.webpush_opt_in,

    }[channel]





def _missing_destination_message(channel: str) -> str:

    return {

        Channel.WHATSAPP: "No WhatsApp number on this profile (add one in the admin).",

        Channel.EMAIL: "No email address on this account.",

        Channel.WEBPUSH: "No active browser subscription (subscribe first).",

    }[channel]





def _log(

    *,

    channel: str,

    status: str,

    trigger: Trigger | None = None,

    template: Template | None = None,

    user=None,

    destination: str = "",

    title: str = "",

    subject: str = "",

    body: str = "",

    provider: str = "",

    message_id: str = "",

    provider_response: dict | None = None,

    error: str = "",

    is_test: bool = False,

    dedupe_key: str = "",

) -> ChannelResult:

    entry = NotificationLog.objects.create(

        trigger=trigger,

        # An unsaved draft (live editor) has no pk, so it cannot be linked.

        template=template if (template is not None and template.pk) else None,

        channel=channel,

        status=status,

        user=user if (user is not None and getattr(user, "is_authenticated", False)) else None,

        destination=destination,

        rendered_title=title[:200],

        rendered_subject=subject[:200],

        rendered_body=body,

        provider=provider,

        provider_message_id=(message_id or "")[:200],

        provider_response=provider_response or {},

        error=error,

        is_test=is_test,

        dedupe_key=(dedupe_key or "")[:255],

        sent_at=timezone.now() if status in {SendStatus.SENT, SendStatus.SIMULATED} else None,

    )

    message = {

        SendStatus.SENT: f"Delivered via {provider or channel}.",

        SendStatus.SIMULATED: "Sandbox mode - message rendered and logged, not sent.",

        SendStatus.SKIPPED: error or "Skipped.",

        SendStatus.FAILED: error or "Delivery failed.",

    }.get(status, status)

    return ChannelResult(

        channel=channel,

        status=status,

        message=message,

        error=error,

        destination=destination,

        log_id=entry.pk,

    )





def _sanitize_provider_response(value: Any) -> dict:

    """Keep useful provider diagnostics without persisting credentials."""

    blocked = {"authorization", "access_token", "token", "api_key", "apikey", "password", "secret"}



    def clean(node):

        if isinstance(node, dict):

            return {

                str(k): ("[redacted]" if str(k).lower() in blocked else clean(v))

                for k, v in node.items()

            }

        if isinstance(node, list):

            return [clean(v) for v in node[:50]]

        if isinstance(node, (str, int, float, bool)) or node is None:

            return node

        return str(node)



    cleaned = clean(value or {})

    return cleaned if isinstance(cleaned, dict) else {"detail": cleaned}





def available_channels() -> Iterable[str]:

    return CHANNEL_ORDER
