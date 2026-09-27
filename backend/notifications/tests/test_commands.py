"""Tests for the seed / scan / purge management commands.

Regression cover for a real bug: the seeder used to create triggers with an
empty ``defaults`` dict, so the inactivity triggers were saved as ``kind="event"``
and ``scan_inactive`` silently found nothing.
"""

from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from notifications.constants import TRIGGER_INACTIVE_1D, TRIGGER_LOGIN
from notifications.models import NotificationLog, Template, Trigger, UserProfile

User = get_user_model()


def seed(*args):
    out = StringIO()
    call_command("seed_triggers", *args, stdout=out)
    return out.getvalue()


class SeedTriggerTests(TestCase):
    def test_fresh_seed_applies_inactivity_kind_and_days(self):
        seed()
        one_day = Trigger.objects.get(key=TRIGGER_INACTIVE_1D)
        self.assertEqual(one_day.kind, "inactivity")
        self.assertEqual(one_day.config, {"days": 1})
        self.assertEqual(one_day.days, 1)

        one_week = Trigger.objects.get(key="not_logged_in_1_week")
        self.assertEqual(one_week.kind, "inactivity")
        self.assertEqual(one_week.days, 7)

    def test_event_triggers_stay_events(self):
        seed()
        self.assertEqual(Trigger.objects.get(key=TRIGGER_LOGIN).kind, "event")
        self.assertIsNone(Trigger.objects.get(key=TRIGGER_LOGIN).days)

    def test_all_spec_triggers_exist(self):
        seed()
        self.assertEqual(Trigger.objects.count(), 6)

    def test_rerun_keeps_admin_changes(self):
        seed()
        trigger = Trigger.objects.get(key=TRIGGER_LOGIN)
        trigger.name = "Renamed by admin"
        trigger.is_active = False
        trigger.save()

        seed()
        trigger.refresh_from_db()
        self.assertEqual(trigger.name, "Renamed by admin")
        self.assertFalse(trigger.is_active)

    def test_reset_restores_spec(self):
        seed()
        trigger = Trigger.objects.get(key=TRIGGER_LOGIN)
        trigger.name = "Renamed by admin"
        trigger.is_active = False
        trigger.save()

        seed("--reset")
        trigger.refresh_from_db()
        self.assertEqual(trigger.name, "Login")
        self.assertTrue(trigger.is_active)

    def test_seed_with_templates_is_idempotent(self):
        seed("--with-templates")
        count = Template.objects.count()
        self.assertGreater(count, 0)
        seed("--with-templates")
        self.assertEqual(Template.objects.count(), count)

    def test_templates_detect_variables(self):
        seed("--with-templates")
        template = Template.objects.get(
            trigger__key=TRIGGER_INACTIVE_1D, channel="whatsapp"
        )
        self.assertIn("days", template.variables)
        self.assertIn("first_name", template.variables)


class ScanInactiveTests(TestCase):
    def setUp(self):
        seed("--with-templates")
        self.user = User.objects.create_user(
            username="sleepy", email="sleepy@example.com", password="pw", first_name="Sam"
        )
        profile = self.user.profile
        profile.last_seen_at = timezone.now() - timedelta(days=5)
        profile.save()

    def test_dry_run_reports_without_sending(self):
        out = StringIO()
        call_command("scan_inactive", "--dry-run", stdout=out)
        text = out.getvalue()
        self.assertIn("not_logged_in_1_day", text)
        self.assertIn("not_logged_in_1_week", text)
        self.assertIn("dry-run", text)
        self.assertEqual(NotificationLog.objects.count(), 0)

    def test_scan_notifies_users_past_the_window(self):
        call_command("scan_inactive", stdout=StringIO())
        # 5 days inactive: inside the 1-day window, outside the 7-day window.
        self.assertTrue(NotificationLog.objects.filter(trigger__key="not_logged_in_1_day").exists())
        self.assertFalse(NotificationLog.objects.filter(trigger__key="not_logged_in_1_week").exists())

    def test_recent_user_is_not_notified(self):
        UserProfile.objects.filter(user=self.user).update(
            last_seen_at=timezone.now() - timedelta(hours=2)
        )
        call_command("scan_inactive", stdout=StringIO())
        self.assertEqual(NotificationLog.objects.count(), 0)

    def test_superusers_are_excluded(self):
        admin = User.objects.create_superuser(
            username="root", email="root@example.com", password="pw"
        )
        UserProfile.objects.filter(user=admin).update(
            last_seen_at=timezone.now() - timedelta(days=30)
        )
        call_command("scan_inactive", stdout=StringIO())
        self.assertFalse(NotificationLog.objects.filter(user=admin).exists())

    def test_cooldown_prevents_resend(self):
        call_command("scan_inactive", stdout=StringIO())
        first = NotificationLog.objects.count()
        self.assertGreater(first, 0)
        call_command("scan_inactive", stdout=StringIO())
        self.assertEqual(NotificationLog.objects.count(), first)


class PurgeLogsTests(TestCase):
    def test_purge_respects_cutoff(self):
        seed()
        user = User.objects.create_user(username="u1", email="u1@example.com", password="pw")
        UserProfile.objects.filter(user=user).update(
            last_seen_at=timezone.now() - timedelta(days=5)
        )
        call_command("scan_inactive", stdout=StringIO())
        self.assertTrue(NotificationLog.objects.exists())
        total = NotificationLog.objects.count()

        # A window far in the future keeps everything.
        call_command("purge_logs", "--days", "99999", stdout=StringIO())
        self.assertEqual(NotificationLog.objects.count(), total)

        # Backdate the rows, then a one-day window removes them.
        NotificationLog.objects.update(
            created_at=timezone.now() - timedelta(days=5)
        )
        call_command("purge_logs", "--days", "1", stdout=StringIO())
        self.assertEqual(NotificationLog.objects.count(), 0)

        # days=0 means "cleanup disabled", not "delete everything".
        NotificationLog.objects.create(channel="email", status="sent")
        call_command("purge_logs", "--days", "0", stdout=StringIO())
        self.assertEqual(NotificationLog.objects.count(), 1)


class ProviderStatusTests(TestCase):
    def test_command_runs(self):
        out = StringIO()
        call_command("provider_status", stdout=out)
        text = out.getvalue()
        for channel in ("whatsapp", "email", "webpush"):
            self.assertIn(channel, text)
