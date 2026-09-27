"""Tests for the dispatcher: toggles, opt-outs, destinations, logging."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from notifications.constants import Channel, SendStatus
from notifications.models import NotificationLog, PushSubscription, Template, Trigger
from notifications.services.dispatcher import fire_trigger, send_draft

User = get_user_model()


class DispatcherTests(TestCase):
    def setUp(self):
        self.trigger = Trigger.objects.create(key="login", name="Login")
        self.user = User.objects.create_user(
            username="amit", email="amit@example.com", password="pw", first_name="Amit"
        )
        self.user.profile.phone_e164 = "+919876543210"
        self.user.profile.save()

        self.wa = Template.objects.create(
            trigger=self.trigger, channel=Channel.WHATSAPP, body="Hi {{ first_name }}"
        )
        self.em = Template.objects.create(
            trigger=self.trigger,
            channel=Channel.EMAIL,
            subject="Hello {{ first_name }}",
            body="Welcome {{ first_name }}",
        )
        self.wp = Template.objects.create(
            trigger=self.trigger,
            channel=Channel.WEBPUSH,
            title="Welcome",
            body="Hi {{ first_name }}",
        )
        self.subscription = PushSubscription.objects.create(
            user=self.user,
            endpoint="https://push.example.com/sub/abcdef123456",
            p256dh="k" * 40,
            auth="a" * 20,
        )

    def test_sends_all_three_channels_in_sandbox(self):
        report = fire_trigger("login", self.user)
        self.assertEqual(len(report.results), 3)
        self.assertTrue(all(r.ok for r in report.results))
        self.assertEqual(len(report.simulated), 3)
        self.assertEqual(NotificationLog.objects.count(), 3)

    def test_renders_variables(self):
        fire_trigger("login", self.user)
        log = NotificationLog.objects.get(channel=Channel.EMAIL)
        self.assertEqual(log.rendered_subject, "Hello Amit")
        self.assertEqual(log.rendered_body, "Welcome Amit")

    def test_masked_destinations(self):
        fire_trigger("login", self.user)
        wa_log = NotificationLog.objects.get(channel=Channel.WHATSAPP)
        self.assertNotIn("9876543210", wa_log.destination)
        self.assertIn("*", wa_log.destination)

    def test_disabled_channel_toggle_is_skipped(self):
        self.em.is_enabled = False
        self.em.save()
        report = fire_trigger("login", self.user)
        skipped = {r.channel for r in report.skipped}
        self.assertEqual(skipped, {Channel.EMAIL})

    def test_disabled_trigger_skips_everything(self):
        self.trigger.is_active = False
        self.trigger.save()
        report = fire_trigger("login", self.user)
        self.assertEqual(len(report.skipped), 3)

    def test_test_send_bypasses_toggles(self):
        self.trigger.is_active = False
        self.trigger.save()
        report = fire_trigger("login", self.user, is_test=True)
        self.assertEqual(len(report.skipped), 0)
        self.assertEqual(len(report.simulated), 3)

    def test_opt_out_is_respected(self):
        self.user.profile.email_opt_in = False
        self.user.profile.save()
        report = fire_trigger("login", self.user)
        skipped = {r.channel for r in report.skipped}
        self.assertIn(Channel.EMAIL, skipped)

    def test_missing_destination_is_skipped(self):
        self.user.profile.phone_e164 = ""
        self.user.profile.save()
        report = fire_trigger("login", self.user)
        by_channel = {r.channel: r for r in report.results}
        self.assertEqual(by_channel[Channel.WHATSAPP].status, SendStatus.SKIPPED)
        self.assertIn("WhatsApp number", by_channel[Channel.WHATSAPP].error)

    def test_no_template_is_skipped(self):
        Trigger.objects.create(key="logout", name="Logout")
        report = fire_trigger("logout", self.user)
        self.assertEqual(len(report.skipped), 3)

    def test_unknown_trigger_reports_failure(self):
        report = fire_trigger("nope", self.user)
        self.assertEqual(report.results[0].status, SendStatus.FAILED)

    def test_webpush_requires_subscription(self):
        self.subscription.delete()
        report = fire_trigger("login", self.user)
        wp = {r.channel: r for r in report.results}[Channel.WEBPUSH]
        self.assertEqual(wp.status, SendStatus.SKIPPED)
        self.assertIn("subscription", wp.error)

        PushSubscription.objects.create(
            user=self.user,
            endpoint="https://push.example.com/sub/abcdef123456",
            p256dh="k" * 40,
            auth="a" * 20,
        )
        report = fire_trigger("login", self.user)
        wp = {r.channel: r for r in report.results}[Channel.WEBPUSH]
        self.assertEqual(wp.status, SendStatus.SIMULATED)

    def test_override_destination(self):
        report = fire_trigger(
            "login", self.user, is_test=True, overrides={Channel.EMAIL: "other@example.com"}
        )
        em = {r.channel: r for r in report.results}[Channel.EMAIL]
        # The log always masks the destination.
        self.assertEqual(em.destination, "o****@example.com")

    def test_draft_send_is_logged_without_saving_template(self):
        before = Template.objects.count()
        result = send_draft(
            trigger=self.trigger,
            channel=Channel.EMAIL,
            user=self.user,
            subject="Draft subject",
            body="Draft body for {{ first_name }}",
        )
        self.assertEqual(result.status, SendStatus.SIMULATED)
        self.assertEqual(Template.objects.count(), before)
        log = NotificationLog.objects.get(pk=result.log_id)
        self.assertIsNone(log.template_id)  # draft is not linked
        self.assertEqual(log.rendered_body, "Draft body for Amit")

    def test_inactive_days_context(self):
        trigger = Trigger.objects.create(
            key="not_logged_in_1_week",
            name="Not logged in 1 week",
            kind="inactivity",
            config={"days": 7},
        )
        Template.objects.create(
            trigger=trigger, channel=Channel.EMAIL, subject="Away", body="Gone {{ days }} days"
        )
        fire_trigger("not_logged_in_1_week", self.user)
        log = NotificationLog.objects.get(channel=Channel.EMAIL)
        self.assertEqual(log.rendered_body, "Gone 7 days")

    def test_dedupe_cooldown_helper(self):
        from notifications.tasks import _notified_recently

        fire_trigger("login", self.user)
        self.assertTrue(_notified_recently(self.trigger, self.user, timezone.now()))
        self.assertFalse(
            _notified_recently(
                self.trigger, self.user, timezone.now() + timedelta(days=3)
            )
        )
