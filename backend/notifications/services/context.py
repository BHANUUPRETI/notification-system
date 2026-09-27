"""Builds and maps the controlled variable context used by templates."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from django.utils import timezone

# Safe, explicitly supported variable sources. The admin may map template keys
# to these paths; arbitrary object traversal/eval is intentionally not allowed.
STANDARD_VARIABLE_PATHS: dict[str, str] = {
    "user": "user.username",
    "username": "user.username",
    "first_name": "user.first_name",
    "last_name": "user.last_name",
    "full_name": "user.full_name",
    "email": "user.email",
    "phone": "user.phone_number",
    "trigger": "trigger.name",
    "trigger_key": "trigger.code",
    "days": "trigger.days",
    "days_away": "user.days_away",
    "last_seen": "user.last_seen",
    "date": "system.date",
    "time": "system.time",
    "datetime": "system.datetime",
    "year": "system.year",
    "month": "system.month",
    "day": "system.day",
    "site_name": "system.site_name",
    "event": "event",
}

PATH_TO_CONTEXT_KEY = {path: key for key, path in STANDARD_VARIABLE_PATHS.items()}



def build_context(
    user=None,
    trigger=None,
    *,
    extra: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or timezone.now()
    settings_obj = timezone.get_current_timezone()

    context: dict[str, Any] = {
        "date": now.astimezone(settings_obj).date().isoformat(),
        "time": now.astimezone(settings_obj).strftime("%H:%M"),
        "datetime": now.astimezone(settings_obj).isoformat(timespec="seconds"),
        "year": now.year,
        "month": f"{now.month:02d}",
        "day": f"{now.day:02d}",
        "site_name": "Notify Demo",
        "trigger": "",
        "trigger_key": "",
    }

    if trigger is not None:
        context["trigger"] = trigger.name
        context["trigger_key"] = trigger.key
        days = trigger.days
        if days:
            context["days"] = days
            context["days_away"] = days

    if user is not None:
        full_name = (user.get_full_name() or "").strip()
        context.update(
            {
                "user": user.get_username(),
                "username": user.get_username(),
                "first_name": user.first_name or user.get_username(),
                "last_name": user.last_name or "",
                "full_name": full_name or user.get_username(),
                "email": user.email or "",
            }
        )
        profile = getattr(user, "profile", None)
        if profile is not None:
            context["phone"] = profile.phone_e164 or ""
            if profile.last_seen_at:
                away = now - profile.last_seen_at
                context["last_seen"] = profile.last_seen_at.isoformat(timespec="seconds")
                context["days_away"] = context.get("days_away", max(away.days, 0))
            else:
                context["last_seen"] = "never"

    if extra:
        context.update({k: v for k, v in extra.items() if v is not None})
    return context



def default_variable_mapping(placeholders: list[str]) -> dict[str, str]:
    """Generate safe defaults for known placeholders."""
    return {
        name: STANDARD_VARIABLE_PATHS[name]
        for name in placeholders
        if name in STANDARD_VARIABLE_PATHS
    }



def apply_variable_mapping(
    base_context: dict[str, Any],
    mapping: dict[str, str] | None,
) -> dict[str, Any]:
    """Overlay admin variable mappings without arbitrary attribute access."""
    if not mapping:
        return dict(base_context)

    mapped = dict(base_context)
    for variable, source in mapping.items():
        if not isinstance(variable, str) or not isinstance(source, str):
            continue
        source_key = PATH_TO_CONTEXT_KEY.get(source, source if source in base_context else None)
        if source_key is not None and source_key in base_context:
            mapped[variable] = base_context[source_key]
    return mapped
