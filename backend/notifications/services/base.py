"""Provider base classes, result object and small shared helpers."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import requests

from ..constants import SendStatus

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 15


@dataclass
class ProviderResult:
    """Outcome of a single delivery attempt."""

    ok: bool
    status: str
    provider: str
    message_id: str = ""
    error: str = ""
    simulated: bool = False
    detail: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def sent(
        cls,
        provider: str,
        message_id: str = "",
        **detail,
    ) -> "ProviderResult":
        return cls(
            ok=True,
            status=SendStatus.SENT,
            provider=provider,
            message_id=message_id or "",
            detail=detail,
        )

    @classmethod
    def simulated(
        cls,
        provider: str,
        reason: str = "sandbox mode",
    ) -> "ProviderResult":
        return cls(
            ok=True,
            status=SendStatus.SIMULATED,
            provider=provider,
            simulated=True,
            detail={"reason": reason},
        )

    @classmethod
    def failed(
        cls,
        provider: str,
        error: str,
    ) -> "ProviderResult":
        return cls(
            ok=False,
            status=SendStatus.FAILED,
            provider=provider,
            error=error,
        )


class BaseProvider:
    """One delivery channel implementation.

    Subclasses only need to implement :meth:`send`; configuration reporting and
    destination validation come for free.
    """

    channel: str = ""
    name: str = ""

    def __init__(self, config: dict):
        self.config = config

    # -- configuration ----------------------------------------------------
    @property
    def is_configured(self) -> bool:
        raise NotImplementedError

    def missing_config_message(self) -> str:
        return f"{self.name} is not configured."

    # -- delivery ---------------------------------------------------------
    def send(
        self,
        *,
        user,
        subject: str,
        body: str,
        title: str = "",
        **extra,
    ) -> ProviderResult:
        raise NotImplementedError

    # -- helpers ----------------------------------------------------------
    def post_json(
        self,
        url: str,
        *,
        headers: dict,
        payload: dict,
    ) -> ProviderResult:
        try:
            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=DEFAULT_TIMEOUT,
            )
        except requests.RequestException as exc:
            logger.exception(
                "Provider network error provider=%s url=%s",
                self.name,
                url,
            )
            return ProviderResult.failed(
                self.name,
                f"Network error: {exc}",
            )

        if response.status_code >= 400:
            logger.warning(
                "Provider HTTP error provider=%s status=%s response=%s",
                self.name,
                response.status_code,
                _trim(response.text, 400),
            )
            return ProviderResult.failed(
                self.name,
                f"HTTP {response.status_code}: {_trim(response.text, 400)}",
            )

        try:
            data = response.json()
        except ValueError:
            data = {}

        message_id = _extract_id(data)

        return ProviderResult.sent(
            self.name,
            message_id=message_id,
            response=data,
        )

    def post_form(
        self,
        url: str,
        *,
        auth,
        data: dict,
    ) -> ProviderResult:
        try:
            response = requests.post(
                url,
                data=data,
                auth=auth,
                timeout=DEFAULT_TIMEOUT,
            )
        except requests.RequestException as exc:
            logger.exception(
                "Provider network error provider=%s url=%s",
                self.name,
                url,
            )
            return ProviderResult.failed(
                self.name,
                f"Network error: {exc}",
            )

        if response.status_code >= 400:
            logger.warning(
                "Provider HTTP error provider=%s status=%s response=%s",
                self.name,
                response.status_code,
                _trim(response.text, 400),
            )
            return ProviderResult.failed(
                self.name,
                f"HTTP {response.status_code}: {_trim(response.text, 400)}",
            )

        return ProviderResult.sent(
            self.name,
            message_id=_trim(response.text, 120),
            response_text=_trim(response.text, 400),
        )


def _trim(text: str, limit: int) -> str:
    """Trim a string safely for logs/provider errors."""
    text = (text or "").strip().replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _extract_id(data: dict) -> str:
    """Safely extract a provider message ID from common API responses.

    Supports common response shapes used by:
    - Brevo
    - Postmark
    - OneSignal / generic providers
    - nested/list based responses
    """

    if not isinstance(data, dict):
        return ""

    # Direct/common message-id keys.
    for key in (
        "messageId",   # Brevo
        "MessageID",   # Postmark
        "message_id",
        "id",
    ):
        value = data.get(key)
        if isinstance(value, (str, int)):
            return str(value)

    # Example:
    # {
    #     "messages": [
    #         {"id": "abc123"}
    #     ]
    # }
    messages = data.get("messages")

    if isinstance(messages, list) and messages:
        first = messages[0]

        if isinstance(first, dict):
            for key in (
                "id",
                "messageId",
                "message_id",
            ):
                value = first.get(key)

                if isinstance(value, (str, int)):
                    return str(value)

    # Example:
    # {
    #     "data": {
    #         "id": "abc123"
    #     }
    # }
    nested_data = data.get("data")

    if isinstance(nested_data, dict):
        for key in (
            "id",
            "messageId",
            "message_id",
        ):
            value = nested_data.get(key)

            if isinstance(value, (str, int)):
                return str(value)

    return ""


def mask_email(value: str) -> str:
    """Mask an email address for safe display/logging."""
    if not value or "@" not in value:
        return _mask_middle(value)

    local, _, domain = value.partition("@")

    head = local[:1] if local else ""

    return f"{head}{'*' * max(len(local) - 1, 1)}@{domain}"


def mask_phone(value: str) -> str:
    """Mask a phone number while preserving a small prefix/suffix."""
    digits = "".join(
        ch for ch in (value or "")
        if ch.isdigit()
    )

    if len(digits) <= 4:
        return _mask_middle(value)

    return f"{value[:2]}{'*' * (len(digits) - 4)}{digits[-2:]}"


def mask_endpoint(value: str) -> str:
    """Mask a Web Push endpoint before showing it in UI/logs."""
    if not value:
        return ""

    head, _, _ = value.partition("/")

    return (
        f"{head}/…{value[-6:]}"
        if head
        else _mask_middle(value)
    )


def _mask_middle(value: str) -> str:
    """Mask the middle part of an arbitrary string."""
    value = value or ""

    if len(value) <= 4:
        return "*" * len(value)

    return (
        f"{value[:2]}"
        f"{'*' * (len(value) - 4)}"
        f"{value[-2:]}"
    )