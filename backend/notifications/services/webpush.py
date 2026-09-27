"""Web Push provider.

Two backends:

* **OneSignal** (default, easiest) - free tier, Website (Web Push) app only.
* **Raw Web Push** with VAPID keys, sent via ``pywebpush``.

The provider sends to every active :class:`PushSubscription` that belongs to the
user (or, for a test send, to the admin's own subscriptions).
"""

from __future__ import annotations

import json
import logging

from .base import BaseProvider, ProviderResult

logger = logging.getLogger(__name__)

ONESIGNAL_API = "https://api.onesignal.com/notifications"


class WebPushProvider(BaseProvider):
    channel = "webpush"
    name = "webpush"

    @property
    def onesignal_configured(self) -> bool:
        return bool(
            self.config.get("ONESIGNAL_APP_ID") and self.config.get("ONESIGNAL_REST_API_KEY")
        )

    @property
    def vapid_configured(self) -> bool:
        return bool(
            self.config.get("VAPID_PRIVATE_KEY")
            and self.config.get("VAPID_PUBLIC_KEY")
        )

    @property
    def is_configured(self) -> bool:
        return self.onesignal_configured or self.vapid_configured

    def missing_config_message(self) -> str:
        return (
            "Web Push is not configured. Set ONESIGNAL_APP_ID + "
            "ONESIGNAL_REST_API_KEY, or VAPID_PUBLIC_KEY + VAPID_PRIVATE_KEY."
        )

    @property
    def public_key(self) -> str:
        """The key the browser needs to subscribe."""
        return self.config.get("VAPID_PUBLIC_KEY") or ""

    # ------------------------------------------------------------------
    def send(
        self,
        *,
        user=None,
        subject: str = "",
        body: str = "",
        title: str = "",
        subscriptions=(),
        **extra,
    ) -> ProviderResult:
        from ..models import PushSubscription  # local import to avoid cycles

        subs = list(subscriptions)
        if not subs:
            subs = list(
                PushSubscription.objects.filter(is_active=True)
                .filter(user=user)
                .order_by("-last_seen_at")
            )
            if user is None:
                subs = list(
                    PushSubscription.objects.filter(is_active=True).order_by("-last_seen_at")
                )

        if not subs:
            return ProviderResult.failed(
                self.name, "No active browser subscriptions for this user."
            )

        title = title or subject or "Notification"
        payload = {"title": title, "body": body}
        if extra.get("url"):
            payload["url"] = extra["url"]

        onesignal_subs = [s for s in subs if s.provider == PushSubscription.Provider.ONESIGNAL]
        raw_subs = [
            s
            for s in subs
            if s.provider == PushSubscription.Provider.WEBPUSH
            and s.p256dh
            and s.auth
        ]

        results: list[ProviderResult] = []
        if onesignal_subs and self.onesignal_configured:
            results.append(self._send_onesignal(onesignal_subs, title, body, payload))
        if raw_subs and self.vapid_configured:
            results.append(self._send_vapid(raw_subs, payload))
        if not results:
            missing = "OneSignal keys" if onesignal_subs else "VAPID keys"
            return ProviderResult.failed(
                self.name,
                f"Matching subscriptions found but the provider is not configured ({missing}).",
            )

        sent = [r for r in results if r.ok]
        if not sent:
            return ProviderResult.failed(
                self.name, "; ".join(r.error for r in results if r.error)
            )
        if len(sent) == len(results):
            return ProviderResult.sent(
                self.name,
                message_id=";".join(r.message_id for r in sent if r.message_id),
                deliveries=len(subs),
            )
        return ProviderResult.failed(
            self.name, "Some subscriptions failed: " + "; ".join(r.error for r in results)
        )

    # ------------------------------------------------------------------
    def _send_onesignal(self, subs, title: str, body: str, payload: dict) -> ProviderResult:
        player_ids = [s.onesignal_subscription_id for s in subs if s.onesignal_subscription_id]
        endpoints = [s.endpoint for s in subs if not s.onesignal_subscription_id]

        body_payload: dict = {
            "app_id": self.config["ONESIGNAL_APP_ID"],
            "headings": {"en": title},
            "contents": {"en": body},
            "data": payload,
            "webpush": {
                "url": payload.get("url", "/"),
                "vibrate": True,
            },
        }
        if player_ids:
            # OneSignal's current user model calls these Subscription IDs;
            # include_player_ids is the deprecated predecessor.
            body_payload["include_subscription_ids"] = player_ids
            body_payload["target_channel"] = "push"
        elif endpoints:
            # OneSignal web push subscriptions are addressed by their endpoint id.
            body_payload["include_aliases"] = {
                "external_id": [e.rsplit("/", 1)[-1] for e in endpoints]
            }
        else:
            body_payload["included_segments"] = ["Subscribed Users"]

        headers = {
            "Authorization": f"Key {self.config['ONESIGNAL_REST_API_KEY']}",
            "Content-Type": "application/json",
        }
        return self.post_json(ONESIGNAL_API, headers=headers, payload=body_payload)

    def _send_vapid(self, subs, payload: dict) -> ProviderResult:
        try:
            from pywebpush import WebPushException, webpush
        except ImportError:  # pragma: no cover
            return ProviderResult.failed(self.name, "pywebpush is not installed.")

        vapid_claims = {"sub": self.config.get("VAPID_CLAIM_EMAIL", "mailto:you@example.com")}
        message = json.dumps(payload)
        errors: list[str] = []
        delivered = 0

        for sub in subs:
            subscription_info = {
                "endpoint": sub.endpoint,
                "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
            }
            try:
                webpush(
                    subscription_info=subscription_info,
                    data=message,
                    vapid_private_key=self.config["VAPID_PRIVATE_KEY"],
                    vapid_claims=vapid_claims,
                    timeout=15,
                )
                delivered += 1
            except WebPushException as exc:
                response = getattr(exc, "response", None)
                status = getattr(response, "status_code", None)
                if status in (404, 410):
                    sub.mark_failed()  # subscription is gone
                errors.append(f"{sub.user or 'anon'}: {exc}")
            except Exception as exc:  # pragma: no cover
                errors.append(f"{sub.user or 'anon'}: {exc}")

        if delivered:
            return ProviderResult.sent("webpush_vapid", deliveries=delivered)
        return ProviderResult.failed(
            "webpush_vapid", "; ".join(errors[:3]) or "no subscription accepted"
        )
