"""Email provider with a pluggable backend.

Supported ``EMAIL_PROVIDER`` values: postmark, brevo, resend, mailgun, ses,
console. All of them need a verified sender and an API token in ``.env``.
"""

from __future__ import annotations

import logging

import requests

from .base import DEFAULT_TIMEOUT, BaseProvider, ProviderResult, _trim

logger = logging.getLogger(__name__)

PLAIN = "text/plain; charset=utf-8"
HTML = "text/html; charset=utf-8"


class EmailProvider(BaseProvider):
    channel = "email"
    name = "email"

    # ------------------------------------------------------------------
    def __init__(self, config: dict):
        super().__init__(config)
        self.backend = (config.get("PROVIDER") or "postmark").lower()

    @property
    def from_email(self) -> str:
        return (
            self.config.get("POSTMARK_FROM_EMAIL")
            or self.config.get("BREVO_FROM_EMAIL")
            or self.config.get("RESEND_FROM_EMAIL")
            or self.config.get("MAILGUN_FROM_EMAIL")
            or self.config.get("SES_FROM_EMAIL")
            or ""
        )

    @property
    def is_configured(self) -> bool:
        if self.backend == "console":
            return True
        if self.backend == "postmark":
            return bool(self.config.get("POSTMARK_TOKEN") and self.from_email)
        if self.backend == "brevo":
            return bool(self.config.get("BREVO_API_KEY") and self.from_email)
        if self.backend == "resend":
            return bool(self.config.get("RESEND_API_KEY") and self.from_email)
        if self.backend == "mailgun":
            return bool(
                self.config.get("MAILGUN_API_KEY")
                and self.config.get("MAILGUN_DOMAIN")
                and self.from_email
            )
        if self.backend == "ses":
            return bool(
                self.config.get("AWS_ACCESS_KEY_ID")
                and self.config.get("AWS_SECRET_ACCESS_KEY")
                and self.from_email
            )
        return False

    def missing_config_message(self) -> str:
        return (
            f"Email provider '{self.backend}' is not configured. "
            "Set EMAIL_PROVIDER and the matching token + verified sender in .env."
        )

    # ------------------------------------------------------------------
    def send(
        self, *, user, subject: str = "", body: str = "", title: str = "", to: str = "", **extra
    ) -> ProviderResult:
        to = (to or getattr(user, "email", "") or "").strip()
        if not to:
            return ProviderResult.failed(self.name, "User has no email address.")

        handler = {
            "postmark": self._postmark,
            "brevo": self._brevo,
            "resend": self._resend,
            "mailgun": self._mailgun,
            "ses": self._ses,
            "console": self._console,
        }.get(self.backend)

        if handler is None:
            return ProviderResult.failed(
                self.name, f"Unknown EMAIL_PROVIDER '{self.backend}'."
            )
        return handler(to=to, subject=subject, body=body)

    # ------------------------------------------------------------------
    # backends
    # ------------------------------------------------------------------
    def _console(self, *, to: str, subject: str, body: str) -> ProviderResult:
        logger.info("[email:console] to=%s subject=%s body=%s", to, subject, body)
        return ProviderResult.sent("console", message_id="console", backend="console")

    def _postmark(self, *, to: str, subject: str, body: str) -> ProviderResult:
        url = "https://api.postmarkapp.com/email"
        headers = {
            "X-Postmark-Server-Token": self.config["POSTMARK_TOKEN"],
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        payload = {
            "From": _from_header(self.from_email, self.config),
            "To": to,
            "Subject": subject,
            "TextBody": body,
            "MessageStream": "outbound",
        }
        reply_to = _reply_to(self.config)
        if reply_to:
            payload["ReplyTo"] = reply_to
        return self.post_json(url, headers=headers, payload=payload)

    def _brevo(self, *, to: str, subject: str, body: str) -> ProviderResult:
        url = "https://api.brevo.com/v3/smtp/email"
        headers = {
            "api-key": self.config["BREVO_API_KEY"],
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        sender_name = self.config.get("DEFAULT_FROM_NAME") or "Notify"
        payload = {
            "sender": {"name": sender_name, "email": self.from_email},
            "to": [{"email": to}],
            "subject": subject,
            "textContent": body,
        }
        reply_to = _reply_to(self.config)
        if reply_to:
            payload["replyTo"] = {"email": reply_to}
        return self.post_json(url, headers=headers, payload=payload)

    def _resend(self, *, to: str, subject: str, body: str) -> ProviderResult:
        url = "https://api.resend.com/emails"
        headers = {
            "Authorization": f"Bearer {self.config['RESEND_API_KEY']}",
            "Content-Type": "application/json",
        }
        payload = {
            "from": _from_header(self.from_email, self.config),
            "to": [to],
            "subject": subject,
            "text": body,
        }
        reply_to = _reply_to(self.config)
        if reply_to:
            payload["reply_to"] = reply_to
        return self.post_json(url, headers=headers, payload=payload)

    def _mailgun(self, *, to: str, subject: str, body: str) -> ProviderResult:
        domain = self.config["MAILGUN_DOMAIN"]
        url = f"https://api.mailgun.net/v3/{domain}/messages"
        auth = ("api", self.config["MAILGUN_API_KEY"])
        data = {
            "from": _from_header(self.from_email, self.config),
            "to": to,
            "subject": subject,
            "text": body,
        }
        try:
            response = requests.post(url, data=data, auth=auth, timeout=DEFAULT_TIMEOUT)
        except requests.RequestException as exc:
            return ProviderResult.failed(self.name, f"Network error: {exc}")
        if response.status_code >= 400:
            return ProviderResult.failed(
                self.name, f"HTTP {response.status_code}: {_trim(response.text, 400)}"
            )
        return ProviderResult.sent("mailgun", message_id=_trim(response.text, 120))

    def _ses(self, *, to: str, subject: str, body: str) -> ProviderResult:
        try:
            import boto3  # imported lazily so it stays an optional dependency
        except ImportError:
            return ProviderResult.failed(
                self.name, "Amazon SES needs boto3 installed: pip install boto3"
            )

        try:
            client = boto3.client(
                "ses",
                region_name=self.config.get("AWS_REGION", "us-east-1"),
                aws_access_key_id=self.config["AWS_ACCESS_KEY_ID"],
                aws_secret_access_key=self.config["AWS_SECRET_ACCESS_KEY"],
            )
            response = client.send_email(
                Source=_from_header(self.from_email, self.config),
                Destination={"ToAddresses": [to]},
                Message={
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {
                        "Text": {"Data": body, "Charset": "UTF-8"},
                        "Html": {"Data": f"<pre>{body}</pre>", "Charset": "UTF-8"},
                    },
                },
            )
        except Exception as exc:  # boto raises a wide range of client errors
            return ProviderResult.failed(self.name, f"{type(exc).__name__}: {exc}")

        return ProviderResult.sent(
            "ses", message_id=(response.get("MessageId") or "")
        )


def _from_header(from_email: str, config: dict) -> str:
    """Build a From address: ``"Display Name" <user@example.com>``.

    The display name is always quoted and escaped. Never append anything else
    to this string - a trailing ``(reply-to ...)`` produces a malformed address
    that transactional providers reject. Use the dedicated Reply-To field
    instead (see ``_reply_to_payload``).
    """
    name = (config.get("DEFAULT_FROM_NAME") or "").strip()
    if not name:
        return from_email
    escaped = name.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}" <{from_email}>'


def _reply_to(config: dict) -> str | None:
    """Optional Reply-To address, or None when unset/blank."""
    value = (config.get("DEFAULT_REPLY_TO") or "").strip()
    return value or None
