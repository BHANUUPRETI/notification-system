"""Maps a channel key to its provider instance."""

from __future__ import annotations

from django.conf import settings

from ..constants import CHANNEL_ORDER, Channel
from .base import BaseProvider
from .email import EmailProvider
from .webpush import WebPushProvider
from .whatsapp import WhatsAppProvider

_PROVIDERS: dict[str, type[BaseProvider]] = {
    Channel.WHATSAPP: WhatsAppProvider,
    Channel.EMAIL: EmailProvider,
    Channel.WEBPUSH: WebPushProvider,
}


def get_provider(channel: str) -> BaseProvider:
    """Build the provider for *channel* from the current settings.

    Deliberately not cached: a cached instance would keep the settings it was
    built with, which surprises tests and any runtime settings reload. These
    objects are tiny, and they are only built once per channel per send.
    """
    cls = _PROVIDERS.get(channel)
    if cls is None:
        raise KeyError(f"No provider registered for channel '{channel}'.")
    config = settings.NOTIFICATIONS
    if cls is WhatsAppProvider:
        return cls(config["WHATSAPP"])
    if cls is EmailProvider:
        return cls(config["EMAIL"])
    return cls(config["PUSH"])


def all_providers() -> list[BaseProvider]:
    return [get_provider(channel) for channel in CHANNEL_ORDER]


def configuration_report() -> list[dict]:
    """Human readable 'is this channel ready?' list for the admin screen."""
    report = []
    for channel in CHANNEL_ORDER:
        provider = get_provider(channel)
        report.append(
            {
                "channel": channel,
                "label": provider.channel and channel.capitalize(),
                "provider": provider.name,
                "configured": provider.is_configured,
                "message": (
                    "" if provider.is_configured else provider.missing_config_message()
                ),
            }
        )
    return report
