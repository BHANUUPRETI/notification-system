"""Notification jobs and application-event helpers."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta

from django.utils import timezone

from .constants import TRIGGER_LOGIN, TRIGGER_LOGOUT, SendStatus, TriggerKind
from .models import NotificationLog, Trigger, UserProfile
from .services.dispatcher import DispatchReport, fire_trigger

logger = logging.getLogger(__name__)


def fire(trigger_key: str, user=None, **kwargs) -> DispatchReport:
    return fire_trigger(trigger_key, user, **kwargs)


def fire_for_users(trigger_key: str, users, **kwargs) -> list[DispatchReport]:
    return [fire_trigger(trigger_key, user, **kwargs) for user in users]


# ---------------------------------------------------------------------------
# Login / logout
# ---------------------------------------------------------------------------
def on_login(user) -> DispatchReport:
    return fire_trigger(TRIGGER_LOGIN, user, context_extra={"event": "login"})


def on_logout(user) -> DispatchReport:
    return fire_trigger(TRIGGER_LOGOUT, user, context_extra={"event": "logout"})


# ---------------------------------------------------------------------------
# Inactivity scan
# ---------------------------------------------------------------------------
@dataclass
class ScanReport:
    triggered: list[str] = field(default_factory=list)
    users_notified: int = 0
    messages: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "triggers_scanned": self.triggered,
            "users_notified": self.users_notified,
            "messages": self.messages,
        }


def inactivity_dedupe_key(trigger: Trigger, profile: UserProfile) -> str:
    """Stable for one continuous inactivity period, changes after activity."""
    stamp = profile.last_seen_at.isoformat(timespec="seconds") if profile.last_seen_at else "never"
    return f"inactivity:{trigger.key}:user:{profile.user_id}:last_seen:{stamp}"


def scan_inactive_users(*, now=None, dry_run: bool = False) -> ScanReport:
    """Fire each inactivity trigger once per continuous inactivity period."""
    now = now or timezone.now()
    report = ScanReport()

    triggers = Trigger.objects.active().filter(kind=TriggerKind.INACTIVITY)
    for trigger in triggers:
        days = trigger.days
        if not days:
            continue

        report.triggered.append(trigger.key)
        cutoff = now - timedelta(days=days)
        candidates = (
            UserProfile.objects.filter(
                user__is_active=True,
                last_seen_at__isnull=False,
                last_seen_at__lte=cutoff,
            )
            .exclude(user__is_superuser=True)
            .select_related("user")
        )

        for profile in candidates:
            dedupe_key = inactivity_dedupe_key(trigger, profile)
            if _notified_in_cycle(trigger, profile.user, dedupe_key):
                continue
            if dry_run:
                report.messages.append(
                    f"[dry-run] would notify {profile.user} about '{trigger.key}'"
                )
                report.users_notified += 1
                continue

            result = fire_trigger(
                trigger.key,
                profile.user,
                context_extra={"days_away": days, "event": "inactivity"},
                dedupe_key=dedupe_key,
            )
            if any(r.status in {SendStatus.SENT, SendStatus.SIMULATED} for r in result.results):
                report.users_notified += 1
            failed = [r for r in result.results if r.status == SendStatus.FAILED]
            if failed:
                report.messages.append(
                    f"{profile.user} / {trigger.key}: "
                    + "; ".join(f"{r.channel} -> {r.error}" for r in failed)
                )

    return report


def _notified_in_cycle(trigger: Trigger, user, dedupe_key: str) -> bool:
    """True only after at least one successful/simulated send for this cycle."""
    return NotificationLog.objects.filter(
        trigger=trigger,
        user=user,
        dedupe_key=dedupe_key,
        status__in=[SendStatus.SENT, SendStatus.SIMULATED],
    ).exists()


def _notified_recently(trigger: Trigger, user, now=None) -> bool:
    """Backward-compatible helper used by old tests/tools.

    For inactivity triggers the real scanner uses activity-cycle deduplication;
    this helper simply reports whether a successful send exists in the last day.
    """
    now = now or timezone.now()
    return NotificationLog.objects.filter(
        trigger=trigger,
        user=user,
        status__in=[SendStatus.SENT, SendStatus.SIMULATED],
        created_at__gte=now - timedelta(hours=24),
    ).exists()


# ---------------------------------------------------------------------------
# Housekeeping
# ---------------------------------------------------------------------------
def purge_old_logs(*, days: int | None = None) -> int:
    from django.conf import settings

    days = days if days is not None else settings.NOTIFICATIONS["LOG_RETENTION_DAYS"]
    if not days:
        return 0
    cutoff = timezone.now() - timedelta(days=days)
    deleted, _ = NotificationLog.objects.filter(created_at__lt=cutoff).delete()
    logger.info("Purged %s notification logs older than %s days", deleted, days)
    return deleted
