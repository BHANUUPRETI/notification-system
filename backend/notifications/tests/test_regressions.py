"""Regression tests for bugs found during review.

Each test here reproduces a real defect that shipped at some point, so they
stay as guards against it coming back.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from notifications.constants import Channel, SendStatus
from notifications.models import PushSubscription, Template, Trigger
from notifications.services.dispatcher import fire_trigger
from notifications.services.email import _from_header, _reply_to
from notifications.services.registry import get_provider

User = get_user_model()


class FromHeaderTests(TestCase):
    """The From address must never carry a Reply-To tacked on the end."""

    CONFIG = {
        "DEFAULT_FROM_NAME": "Notify Demo",
        "DEFAULT_REPLY_TO": "noreply@example.com",
    }

    def test_reply_to_is_not_appended_to_from(self):
        header = _from_header("you@example.com", self.CONFIG)
        self.assertEqual(header, '"Notify Demo" <you@example.com>')
        self.assertNotIn("reply-to", header.lower())
        self.assertNotIn("(", header)

    def test_display_name_is_quoted_when_it_has_specials(self):
        header = _from_header("you@example.com", {"DEFAULT_FROM_NAME": "Notify, Demo (Ltd)"})
        self.assertEqual(header, '"Notify, Demo (Ltd)" <you@example.com>')

    def test_quotes_in_display_name_are_escaped(self):
        header = _from_header("you@example.com", {"DEFAULT_FROM_NAME": 'The "Best" Notify'})
        self.assertEqual(header, '"The \\"Best\\" Notify" <you@example.com>')

    def test_backslash_in_display_name_is_escaped(self):
        header = _from_header("you@example.com", {"DEFAULT_FROM_NAME": "A\\B"})
        self.assertIn("\\\\", header)

    def test_missing_name_gives_bare_address(self):
        self.assertEqual(_from_header("you@example.com", {}), "you@example.com")
        self.assertEqual(
            _from_header("you@example.com", {"DEFAULT_FROM_NAME": "  "}), "you@example.com"
        )

    def test_reply_to_helper(self):
        self.assertEqual(_reply_to(self.CONFIG), "noreply@example.com")
        self.assertIsNone(_reply_to({}))
        self.assertIsNone(_reply_to({"DEFAULT_REPLY_TO": "   "}))


class PushIsolationTests(TestCase):
    """A user's push must never land on another user's device."""

    def setUp(self):
        self.trigger = Trigger.objects.create(key="login", name="Login")
        Template.objects.create(
            trigger=self.trigger,
            channel=Channel.WEBPUSH,
            title="Hi",
            body="Hello {{ first_name }}",
        )
        self.amit = User.objects.create_user(
            username="amit", email="amit@example.com", password="pw", first_name="Amit"
        )
        self.priya = User.objects.create_user(
            username="priya", email="priya@example.com", password="pw", first_name="Priya"
        )

    def _subscribe(self, user, label):
        return PushSubscription.objects.create(
            user=user,
            endpoint=f"https://push.example.com/{label}",
            p256dh="k" * 40,
            auth="a" * 20,
        )

    def test_real_send_does_not_use_another_users_subscription(self):
        # Only priya is subscribed; amit is not.
        self._subscribe(self.priya, "priya")
        report = fire_trigger("login", self.amit)
        push = {r.channel: r for r in report.results}[Channel.WEBPUSH]
        self.assertEqual(push.status, SendStatus.SKIPPED)
        self.assertIn("subscription", push.error)
        self.assertNotIn("priya", push.destination)

    def test_real_send_uses_the_users_own_subscription(self):
        self._subscribe(self.priya, "priya")
        self._subscribe(self.amit, "amit")
        report = fire_trigger("login", self.amit)
        push = {r.channel: r for r in report.results}[Channel.WEBPUSH]
        self.assertEqual(push.status, SendStatus.SIMULATED)

    def test_inactive_subscriptions_are_never_used(self):
        sub = self._subscribe(self.priya, "priya")
        sub.is_active = False
        sub.save()
        report = fire_trigger("login", self.priya)
        push = {r.channel: r for r in report.results}[Channel.WEBPUSH]
        self.assertEqual(push.status, SendStatus.SKIPPED)

    def test_test_send_may_borrow_any_device(self):
        # Deliberate convenience: an admin testing Web Push wants it to arrive
        # on whatever device is available.
        self._subscribe(self.priya, "priya")
        report = fire_trigger("login", self.amit, is_test=True)
        push = {r.channel: r for r in report.results}[Channel.WEBPUSH]
        self.assertEqual(push.status, SendStatus.SIMULATED)

    def test_anonymous_send_does_not_sweep_every_subscription(self):
        # user=None must not fan out to every browser in the system.
        self._subscribe(self.priya, "priya")
        report = fire_trigger("login", None)
        push = {r.channel: r for r in report.results}[Channel.WEBPUSH]
        self.assertEqual(push.status, SendStatus.SKIPPED)


class ProviderRegistryTests(TestCase):
    @staticmethod
    def _notifications(postmark_token: str = "") -> dict:
        from django.conf import settings
        import copy

        config = copy.deepcopy(settings.NOTIFICATIONS)
        config["EMAIL"]["POSTMARK_TOKEN"] = postmark_token
        config["EMAIL"]["POSTMARK_FROM_EMAIL"] = (
            "you@example.com" if postmark_token else ""
        )
        config["EMAIL"]["PROVIDER"] = "postmark"
        return config

    def test_provider_reflects_current_settings(self):
        # A cached provider would keep the config it was built with, so this
        # must return a provider that sees the new token.
        with self.settings(NOTIFICATIONS=self._notifications("")):
            self.assertFalse(get_provider(Channel.EMAIL).is_configured)
        with self.settings(NOTIFICATIONS=self._notifications("token-abc")):
            self.assertTrue(get_provider(Channel.EMAIL).is_configured)

    def test_two_calls_return_independent_instances(self):
        with self.settings(NOTIFICATIONS=self._notifications("token-abc")):
            first = get_provider(Channel.EMAIL)
            second = get_provider(Channel.EMAIL)
        self.assertIsNot(first, second)

    def test_whatsapp_config_reads_whatsapp_block(self):
        config = self._notifications()
        config["WHATSAPP"] = {"ACCESS_TOKEN": "t", "PHONE_NUMBER_ID": "1", "API_VERSION": "v21.0",
                              "TEMPLATE_LANGUAGE": "en_US", "TEST_RECIPIENTS": []}
        with self.settings(NOTIFICATIONS=config):
            provider = get_provider(Channel.WHATSAPP)
        self.assertTrue(provider.is_configured)
        self.assertEqual(provider.config["PHONE_NUMBER_ID"], "1")

    def test_missing_config_message_names_the_variables(self):
        config = self._notifications()
        config["WHATSAPP"] = {"ACCESS_TOKEN": "", "PHONE_NUMBER_ID": "",
                              "API_VERSION": "v21.0", "TEMPLATE_LANGUAGE": "en_US",
                              "TEST_RECIPIENTS": []}
        with self.settings(NOTIFICATIONS=config):
            message = get_provider(Channel.WHATSAPP).missing_config_message()
        self.assertIn("WHATSAPP_ACCESS_TOKEN", message)
        self.assertIn("PHONE_NUMBER_ID", message)

    def test_unknown_channel_raises(self):
        with self.assertRaises(KeyError):
            get_provider("carrier-pigeon")


class PushBackendReportingTests(TestCase):
    """The browser must be told which Web Push transport to subscribe through."""

    def setUp(self):
        from rest_framework.test import APIClient

        self.client = APIClient()
        self.admin = User.objects.create_user(
            username="admin", email="a@example.com", password="pw", is_staff=True
        )
        self.client.force_authenticate(self.admin)

    def _config(self, **push_overrides) -> dict:
        from django.conf import settings
        import copy

        config = copy.deepcopy(settings.NOTIFICATIONS)
        config["PUSH"].update(push_overrides)
        return config

    def test_backend_is_none_when_nothing_configured(self):
        config = self._config(
            ONESIGNAL_APP_ID="", ONESIGNAL_REST_API_KEY="",
            VAPID_PUBLIC_KEY="", VAPID_PRIVATE_KEY="",
        )
        with self.settings(NOTIFICATIONS=config):
            data = self.client.get("/api/config/").json()
        self.assertEqual(data["push"]["backend"], "none")
        self.assertFalse(data["push"]["onesignal_configured"])
        self.assertFalse(data["push"]["vapid_configured"])

    def test_vapid_is_reported(self):
        config = self._config(
            ONESIGNAL_APP_ID="", ONESIGNAL_REST_API_KEY="",
            VAPID_PUBLIC_KEY="BPpub", VAPID_PRIVATE_KEY="priv",
        )
        with self.settings(NOTIFICATIONS=config):
            data = self.client.get("/api/config/").json()
        self.assertEqual(data["push"]["backend"], "vapid")
        self.assertTrue(data["push"]["vapid_configured"])
        self.assertEqual(data["vapid_public_key"], "BPpub")

    def test_onesignal_wins_when_both_are_configured(self):
        # OneSignal is the spec's documented option, so it takes priority.
        config = self._config(
            ONESIGNAL_APP_ID="app-123", ONESIGNAL_REST_API_KEY="key",
            VAPID_PUBLIC_KEY="BPpub", VAPID_PRIVATE_KEY="priv",
        )
        with self.settings(NOTIFICATIONS=config):
            data = self.client.get("/api/config/").json()
        self.assertEqual(data["push"]["backend"], "onesignal")
        self.assertEqual(data["push"]["onesignal_app_id"], "app-123")

    def test_onesignal_needs_both_keys(self):
        config = self._config(
            ONESIGNAL_APP_ID="app-123", ONESIGNAL_REST_API_KEY="",
            VAPID_PUBLIC_KEY="", VAPID_PRIVATE_KEY="",
        )
        with self.settings(NOTIFICATIONS=config):
            data = self.client.get("/api/config/").json()
        self.assertEqual(data["push"]["backend"], "none")
        self.assertFalse(data["push"]["onesignal_configured"])


class OneSignalSubscriptionTests(TestCase):
    """A OneSignal subscription must round-trip through the normal endpoint."""

    def setUp(self):
        from rest_framework.test import APIClient

        self.client = APIClient()
        self.user = User.objects.create_user(
            username="amit", email="amit@example.com", password="pw"
        )
        self.client.force_authenticate(self.user)

    def test_subscribe_and_reuse_by_player_id(self):
        # The frontend keys OneSignal subscriptions by a synthetic https url
        # derived from the player id.
        endpoint = "https://onesignal.app/player/abc-123"
        first = self.client.post(
            "/api/push/subscribe/",
            {
                "provider": "onesignal",
                "endpoint": endpoint,
                "onesignal_subscription_id": "abc-123",
                "p256dh": "",
                "auth": "",
            },
            format="json",
        )
        self.assertEqual(first.status_code, 201, first.content)
        self.assertEqual(first.json()["provider"], "onesignal")
        self.assertEqual(first.json()["onesignal_subscription_id"], "abc-123")

        # Re-subscribing on a page reload must update, not duplicate.
        second = self.client.post(
            "/api/push/subscribe/",
            {
                "provider": "onesignal",
                "endpoint": endpoint,
                "onesignal_subscription_id": "abc-123",
            },
            format="json",
        )
        self.assertEqual(second.status_code, 200)
        self.assertEqual(PushSubscription.objects.count(), 1)

    def test_onesignal_needs_no_vapid_keys(self):
        res = self.client.post(
            "/api/push/subscribe/",
            {
                "provider": "onesignal",
                "endpoint": "https://onesignal.app/player/xyz-789",
                "onesignal_subscription_id": "xyz-789",
            },
            format="json",
        )
        self.assertEqual(res.status_code, 201, res.content)

    def test_unsubscribe_by_synthetic_endpoint(self):
        endpoint = "https://onesignal.app/player/abc-123"
        self.client.post(
            "/api/push/subscribe/",
            {"provider": "onesignal", "endpoint": endpoint,
             "onesignal_subscription_id": "abc-123"},
            format="json",
        )
        res = self.client.post(
            "/api/push/unsubscribe/", {"endpoint": endpoint}, format="json"
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["deactivated"], 1)
        self.assertFalse(PushSubscription.objects.first().is_active)


class LogoutResilienceTests(TestCase):
    def setUp(self):
        from rest_framework.test import APIClient

        self.client = APIClient()
        self.user = User.objects.create_user(
            username="amit", email="amit@example.com", password="pw"
        )
        login = self.client.post(
            "/api/auth/login/",
            {"identifier": "amit", "password": "pw"},
            format="json",
        )
        self.token = login.json()["token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token}")

    def test_token_is_revoked_even_if_the_trigger_raises(self):
        from unittest import mock

        from rest_framework.authtoken.models import Token

        with mock.patch(
            "notifications.views.tasks.on_logout", side_effect=RuntimeError("provider down")
        ):
            with self.assertRaises(RuntimeError):
                self.client.post("/api/auth/logout/", {}, format="json")
        # The user must not be left stuck in a session they asked to leave.
        self.assertFalse(Token.objects.filter(key=self.token).exists())
