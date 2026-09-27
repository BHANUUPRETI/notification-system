"""End-to-end tests for the REST API used by the Next.js admin panel."""

from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from notifications.constants import Channel
from notifications.models import (
    NotificationLog,
    PushSubscription,
    Template,
    Trigger,
    UserProfile,
)

User = get_user_model()


class ApiTestCase(TestCase):
    def setUp(self):
        self.base_notifications = settings.NOTIFICATIONS
        self.client = APIClient()
        self.admin = User.objects.create_user(
            username="admin",
            email="admin@example.com",
            password="admin12345",
            is_staff=True,
            is_superuser=True,
            first_name="Ad",
        )
        self.user = User.objects.create_user(
            username="amit", email="amit@example.com", password="demo12345", first_name="Amit"
        )
        self.user.profile.phone_e164 = "+919876543210"
        self.user.profile.save()

        self.trigger = Trigger.objects.create(key="login", name="Login", order=10)
        self.template = Template.objects.create(
            trigger=self.trigger,
            channel=Channel.EMAIL,
            subject="Hello {{ first_name }}",
            body="Welcome {{ first_name }}",
        )
        self.subscription = PushSubscription.objects.create(
            user=self.user,
            endpoint="https://push.example.com/sub/base123456",
            p256dh="k" * 40,
            auth="a" * 20,
        )

    def auth_admin(self):
        self.client.force_authenticate(self.admin)

    # -- public ---------------------------------------------------------
    def test_health_is_public(self):
        res = self.client.get("/api/health/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "ok")

    def test_public_config_lists_channels_and_variables(self):
        res = self.client.get("/api/config/")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual([c["key"] for c in data["channels"]], ["whatsapp", "email", "webpush"])
        self.assertTrue(any(v["name"] == "first_name" for v in data["variables"]))

    # -- auth -----------------------------------------------------------
    def test_login_by_username_returns_token_and_fires_trigger(self):
        res = self.client.post(
            "/api/auth/login/", {"identifier": "amit", "password": "demo12345"}, format="json"
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["token"])
        self.assertEqual(data["user"]["username"], "amit")
        # Only the email template exists in this fixture.
        self.assertEqual(
            data["notification"]["summary"],
            {"sent": 0, "simulated": 1, "failed": 0, "skipped": 2},
        )
        self.user.refresh_from_db()
        self.assertIsNotNone(UserProfile.objects.get(user=self.user).last_seen_at)

    def test_login_by_email(self):
        res = self.client.post(
            "/api/auth/login/", {"identifier": "amit@example.com", "password": "demo12345"}, format="json"
        )
        self.assertEqual(res.status_code, 200)

    def test_login_rejects_bad_password(self):
        res = self.client.post(
            "/api/auth/login/", {"identifier": "amit", "password": "wrong"}, format="json"
        )
        self.assertEqual(res.status_code, 400)

    def test_logout_fires_trigger_and_revokes_token(self):
        logout_trigger = Trigger.objects.create(key="logout", name="Logout")
        Template.objects.create(
            trigger=logout_trigger,
            channel=Channel.EMAIL,
            subject="Bye",
            body="Bye {{ first_name }}",
        )

        login = self.client.post(
            "/api/auth/login/", {"identifier": "amit", "password": "demo12345"}, format="json"
        )
        token = login.json()["token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        res = self.client.post("/api/auth/logout/", {}, format="json")
        self.assertEqual(res.status_code, 200)

        report = res.json()["notification"]
        self.assertEqual(report["trigger"], "logout")
        self.assertEqual(len(report["results"]), 3)
        # Only the email template exists for logout, so 1 sent + 2 skipped.
        self.assertEqual(
            report["summary"], {"sent": 0, "simulated": 1, "failed": 0, "skipped": 2}
        )
        logged = NotificationLog.objects.filter(trigger=logout_trigger)
        self.assertEqual([row.channel for row in logged], ["email"])
        self.assertEqual(logged.first().rendered_body, "Bye Amit")

        # token revoked
        from rest_framework.authtoken.models import Token as AuthToken

        self.assertFalse(AuthToken.objects.filter(key=token).exists())

    def test_fire_unknown_trigger_reports_failure(self):
        self.auth_admin()
        res = self.client.post("/api/triggers/does-not-exist/fire/", {}, format="json")
        self.assertEqual(res.status_code, 404)

    def test_trigger_detail_uses_slug_lookup(self):
        # Regression: the URL captures <slug:key>, so the generic view must not
        # default to looking up "pk" (which raised AssertionError -> HTTP 500).
        self.auth_admin()
        res = self.client.get("/api/triggers/login/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["key"], "login")

        missing = self.client.get("/api/triggers/nope-not-real/")
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing["Content-Type"], "application/json")
        self.assertIn("detail", missing.json())

    def test_trigger_detail_patch_and_delete(self):
        self.auth_admin()
        res = self.client.patch(
            "/api/triggers/login/", {"name": "Signed in"}, format="json"
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["name"], "Signed in")

        gone = self.client.delete("/api/triggers/login/")
        self.assertEqual(gone.status_code, 204)
        self.assertFalse(Trigger.objects.filter(key="login").exists())

    def test_unknown_api_path_returns_json_404(self):
        res = self.client.get("/api/definitely-not-a-route/")
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res["Content-Type"], "application/json")
        self.assertEqual(res.json(), {"detail": "Not found."})

    # --- internal scheduler endpoint ---------------------------------
    def test_scan_endpoint_disabled_without_token(self):
        with self.settings(NOTIFICATIONS={**self.base_notifications, "SCAN_TOKEN": ""}):
            res = self.client.post("/api/internal/scan-inactive/", {}, format="json")
        self.assertEqual(res.status_code, 404)

    def test_scan_endpoint_rejects_bad_token(self):
        with self.settings(
            NOTIFICATIONS={**self.base_notifications, "SCAN_TOKEN": "s3cret"}
        ):
            res = self.client.post("/api/internal/scan-inactive/", {}, format="json")
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json()["detail"], "Invalid scan token.")

    def test_scan_endpoint_runs_with_valid_token(self):
        inactivity = Trigger.objects.create(
            key="not_logged_in_1_day", name="Not logged in 1 day",
            kind="inactivity", config={"days": 1},
        )
        Template.objects.create(
            trigger=inactivity,
            channel=Channel.EMAIL,
            subject="We miss you",
            body="Gone {{ days }} day",
        )
        UserProfile.objects.filter(user=self.user).update(
            last_seen_at=timezone.now() - timedelta(days=3)
        )

        with self.settings(
            NOTIFICATIONS={**self.base_notifications, "SCAN_TOKEN": "s3cret"}
        ):
            res = self.client.post(
                "/api/internal/scan-inactive/",
                {},
                format="json",
                HTTP_X_SCAN_TOKEN="s3cret",
            )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["triggers_scanned"], ["not_logged_in_1_day"])
        self.assertEqual(data["users_notified"], 1)
        self.assertTrue(
            NotificationLog.objects.filter(trigger=inactivity).exists()
        )

    def test_me_requires_auth(self):
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 401)

    def test_me_returns_profile(self):
        self.client.force_authenticate(self.user)
        res = self.client.get("/api/auth/me/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["profile"]["phone_e164"], "+919876543210")

    def test_update_own_profile_phone(self):
        self.client.force_authenticate(self.user)
        res = self.client.patch(
            "/api/auth/me/profile/", {"phone_e164": "+911111111111"}, format="json"
        )
        self.assertEqual(res.status_code, 200)
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.phone_e164, "+911111111111")

    # -- admin permissions ----------------------------------------------
    def test_non_admin_cannot_list_triggers(self):
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.get("/api/triggers/").status_code, 403)

    def test_admin_can_list_triggers_with_templates(self):
        self.auth_admin()
        res = self.client.get("/api/triggers/")
        self.assertEqual(res.status_code, 200)
        row = res.json()[0]
        self.assertEqual(row["key"], "login")
        self.assertEqual(len(row["templates"]), 1)
        self.assertEqual(row["enabled_channels"], ["email"])

    # -- templates -------------------------------------------------------
    def test_create_template_requires_admin(self):
        self.client.force_authenticate(self.user)
        res = self.client.post(
            "/api/templates/",
            {"trigger_key": "login", "channel": "whatsapp", "body": "hi"},
            format="json",
        )
        self.assertEqual(res.status_code, 403)

    def test_create_template_autodetects_variables(self):
        self.auth_admin()
        res = self.client.post(
            "/api/templates/",
            {
                "trigger_key": "login",
                "channel": "whatsapp",
                "body": "Hello {{ first_name }}, back after {{ days }} days",
            },
            format="json",
        )
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.json()["variables"], ["days", "first_name"])

    def test_cannot_create_duplicate_channel_template(self):
        self.auth_admin()
        res = self.client.post(
            "/api/templates/",
            {"trigger_key": "login", "channel": "email", "body": "hi"},
            format="json",
        )
        self.assertEqual(res.status_code, 400)

    def test_email_template_requires_subject(self):
        self.auth_admin()
        res = self.client.post(
            "/api/templates/",
            {"trigger_key": "login", "channel": "email", "body": "hi"},
            format="json",
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("subject", res.json())

    def test_webpush_template_requires_title(self):
        self.auth_admin()
        res = self.client.post(
            "/api/templates/",
            {"trigger_key": "login", "channel": "webpush", "body": "hi"},
            format="json",
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("title", res.json())

    def test_update_template(self):
        self.auth_admin()
        res = self.client.patch(
            f"/api/templates/{self.template.pk}/",
            {"body": "Changed {{ first_name }}"},
            format="json",
        )
        self.assertEqual(res.status_code, 200)
        self.template.refresh_from_db()
        self.assertEqual(self.template.body, "Changed {{ first_name }}")

    def test_toggle_template(self):
        self.auth_admin()
        res = self.client.post(f"/api/templates/{self.template.pk}/toggle/", {}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.json()["is_enabled"])
        res = self.client.post(f"/api/templates/{self.template.pk}/toggle/", {}, format="json")
        self.assertTrue(res.json()["is_enabled"])

    def test_toggle_trigger(self):
        self.auth_admin()
        res = self.client.post(
            "/api/triggers/login/toggle/", {"is_active": False}, format="json"
        )
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.json()["is_active"])

    def test_template_preview(self):
        self.auth_admin()
        res = self.client.get(f"/api/templates/{self.template.pk}/preview/?user_id={self.user.pk}")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["subject"], "Hello Amit")

    def test_template_test_send(self):
        self.auth_admin()
        res = self.client.post(
            f"/api/templates/{self.template.pk}/test/",
            {"user_id": self.user.pk},
            format="json",
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["channel"], "email")
        self.assertEqual(data["status"], "simulated")
        self.assertTrue(NotificationLog.objects.filter(is_test=True).exists())

    def test_template_test_send_to_explicit_email(self):
        self.auth_admin()
        res = self.client.post(
            f"/api/templates/{self.template.pk}/test/",
            {"email": "someone@else.com"},
            format="json",
        )
        self.assertEqual(res.status_code, 200)
        # The stored destination is always masked.
        self.assertEqual(res.json()["destination"], "s******@else.com")

    def test_draft_test_send(self):
        self.auth_admin()
        res = self.client.post(
            "/api/templates/draft-test/",
            {
                "trigger_key": "login",
                "channel": "webpush",
                "title": "Draft",
                "body": "Draft for {{ first_name }}",
            },
            format="json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(Template.objects.filter(channel=Channel.WEBPUSH).count(), 0)

    def test_fire_trigger_endpoint(self):
        self.auth_admin()
        res = self.client.post(
            f"/api/triggers/login/fire/", {"user_id": self.user.pk}, format="json"
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["trigger"], "login")

    # -- push ------------------------------------------------------------
    def test_push_subscribe_requires_auth(self):
        self.assertEqual(
            self.client.post("/api/push/subscribe/", {"endpoint": "https://x/y"}, format="json").status_code,
            401,
        )

    def test_push_subscribe_and_resubscribe_is_idempotent(self):
        self.client.force_authenticate(self.user)
        PushSubscription.objects.all().delete()
        payload = {
            "endpoint": "https://push.example.com/sub/abc123456",
            "p256dh": "k" * 40,
            "auth": "a" * 20,
            "provider": "webpush",
        }
        first = self.client.post("/api/push/subscribe/", payload, format="json")
        self.assertEqual(first.status_code, 201)
        second = self.client.post("/api/push/subscribe/", payload, format="json")
        self.assertEqual(second.status_code, 200)
        self.assertEqual(PushSubscription.objects.count(), 1)

    def test_push_subscribe_rejects_http(self):
        self.client.force_authenticate(self.user)
        res = self.client.post(
            "/api/push/subscribe/", {"endpoint": "http://push.example.com/x"}, format="json"
        )
        self.assertEqual(res.status_code, 400)

    def test_push_unsubscribe(self):
        self.client.force_authenticate(self.user)
        self.client.post(
            "/api/push/subscribe/",
            {"endpoint": "https://push.example.com/sub/abc123456", "p256dh": "k", "auth": "a"},
            format="json",
        )
        res = self.client.post(
            "/api/push/unsubscribe/", {"endpoint": "https://push.example.com/sub/abc123456"}, format="json"
        )
        self.assertEqual(res.status_code, 200)
        self.assertFalse(PushSubscription.objects.first().is_active)

    # -- logs / stats / variables ---------------------------------------
    def test_log_list_filters(self):
        self.auth_admin()
        fire = self.client.post(f"/api/triggers/login/fire/", {}, format="json")
        self.assertEqual(fire.status_code, 200)
        res = self.client.get("/api/logs/?channel=email")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(all(r["channel"] == "email" for r in res.json()))

    def test_stats(self):
        self.auth_admin()
        res = self.client.get("/api/stats/")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["triggers"], 1)
        self.assertEqual(data["templates"], 1)
        self.assertEqual(data["templates_enabled"], 1)

    def test_variable_scan_reports_unknown(self):
        self.auth_admin()
        self.template.body = "Hi {{ first_name }} {{ bogus }}"
        self.template.save()
        res = self.client.get("/api/variables/scan/")
        self.assertEqual(res.status_code, 200)
        unknown = res.json()["unknown"]
        self.assertEqual(unknown[0]["unknown"], ["bogus"])
