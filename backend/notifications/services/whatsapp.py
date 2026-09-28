"""WhatsApp Cloud API provider (Meta sandbox / production)."""

from __future__ import annotations

import logging

import requests

from .base import DEFAULT_TIMEOUT, BaseProvider, ProviderResult, _trim

logger = logging.getLogger(__name__)
GRAPH_BASE = "https://graph.facebook.com"


class WhatsAppProvider(BaseProvider):
    channel = "whatsapp"
    name = "whatsapp_cloud_api"

    @property
    def is_configured(self) -> bool:
        return bool(self.config.get("ACCESS_TOKEN") and self.config.get("PHONE_NUMBER_ID"))

    @property
    def sync_configured(self) -> bool:
        return bool(self.config.get("ACCESS_TOKEN") and self.config.get("BUSINESS_ACCOUNT_ID"))

    def missing_config_message(self) -> str:
        missing = []
        if not self.config.get("ACCESS_TOKEN"):
            missing.append("WHATSAPP_ACCESS_TOKEN")
        if not self.config.get("PHONE_NUMBER_ID"):
            missing.append("PHONE_NUMBER_ID")
        return f"WhatsApp Cloud API is not configured (missing {', '.join(missing)})."

    def sync_template(self, template_name: str, language: str = "") -> dict:
        """Fetch one template's current status from the Meta WABA API."""
        if not self.sync_configured:
            return {
                "ok": False,
                "error": "WhatsApp template sync needs WHATSAPP_ACCESS_TOKEN and WHATSAPP_BUSINESS_ACCOUNT_ID.",
            }
        name = (template_name or "").strip()
        if not name:
            return {"ok": False, "error": "Set provider_template_name before syncing."}

        version = self.config.get("API_VERSION") or "v21.0"
        waba_id = self.config.get("BUSINESS_ACCOUNT_ID")
        url = f"{GRAPH_BASE}/{version}/{waba_id}/message_templates"
        headers = {"Authorization": f"Bearer {self.config['ACCESS_TOKEN']}"}
        params = {
            "name": name,
            "fields": "id,name,status,language,rejected_reason",
            "limit": 100,
        }
        try:
            response = requests.get(url, headers=headers, params=params, timeout=DEFAULT_TIMEOUT)
        except requests.RequestException as exc:
            return {"ok": False, "error": f"Network error: {exc}"}
        if response.status_code >= 400:
            return {"ok": False, "error": f"HTTP {response.status_code}: {_trim(response.text, 400)}"}
        try:
            payload = response.json()
        except ValueError:
            return {"ok": False, "error": "Meta returned a non-JSON response."}

        candidates = payload.get("data") or []
        requested_language = (language or "").strip().lower()
        match = None
        for item in candidates:
            if str(item.get("name", "")).lower() != name.lower():
                continue
            if requested_language and str(item.get("language", "")).lower() != requested_language:
                continue
            match = item
            break
        if match is None and candidates:
            match = candidates[0]
        if match is None:
            return {"ok": False, "error": f"Template '{name}' was not found in the configured WhatsApp Business Account."}

        meta_status = str(match.get("status") or "").upper()
        status_map = {
            "APPROVED": "approved",
            "PENDING": "pending",
            "REJECTED": "rejected",
            "PAUSED": "rejected",
            "DISABLED": "rejected",
            "IN_APPEAL": "pending",
        }
        local_status = status_map.get(meta_status, "draft")
        return {
            "ok": True,
            "provider_template_id": str(match.get("id") or ""),
            "provider_template_name": str(match.get("name") or name),
            "provider_language": str(match.get("language") or language or self.config.get("TEMPLATE_LANGUAGE", "en_US")),
            "provider_status": local_status,
            "provider_status_note": str(match.get("rejected_reason") or ""),
            "meta_status": meta_status,
        }

    def send(
        self,
        *,
        user,
        subject: str = "",
        body: str = "",
        title: str = "",
        to: str = "",
        template_name: str = "",
        language: str = "",
        template_parameters: list[str] | None = None,
        **extra,
    ) -> ProviderResult:
        to = to or _phone_of(user)
        if not to:
            return ProviderResult.failed(self.name, "No WhatsApp number for this user.")

        version = self.config.get("API_VERSION") or "v21.0"
        phone_number_id = self.config.get("PHONE_NUMBER_ID")
        url = f"{GRAPH_BASE}/{version}/{phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.config['ACCESS_TOKEN']}",
            "Content-Type": "application/json",
        }

        if template_name:
            payload = _template_payload(
                to,
                template_name,
                language or self.config.get("TEMPLATE_LANGUAGE", "en_US"),
                list(template_parameters or []),
            )
        else:
            payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "text",
                "text": {"preview_url": False, "body": body},
            }

        result = self.post_json(url, headers=headers, payload=payload)
        if not result.ok:
            logger.warning("WhatsApp send failed for %s: %s", to, result.error)
        return result


def _phone_of(user) -> str:
    profile = getattr(user, "profile", None)
    return getattr(profile, "phone_e164", "") or ""


def _template_payload(to: str, name: str, language: str, parameters: list[str]) -> dict:
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "template",
        "template": {"name": name, "language": {"code": language}},
    }
    if parameters:
        payload["template"]["components"] = [
            {
                "type": "body",
                "parameters": [{"type": "text", "text": value[:1024]} for value in parameters],
            }
        ]
    return payload

