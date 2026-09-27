"""Tests for admin-created triggers and WhatsApp template approval status."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from notifications.constants import Channel, ProviderStatus
from notifications.models import Template, Trigger

User = get_user_model()


class CreateTriggerTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            username="admin", email="a@example.com", password="pw", is_staff=True
        )
        self.client.force_authenticate(self.admin)

    def test_create_event_trigger_derives_key(self):
        res = self.client.post(
            "/api/triggers/",
            {"name": "Cart Abandoned", "kind": "event", "description": "Left items"},
            format="json",
        )
        self.assertEqual(res.status_code, 201, res.content)
        data = res.json()
        self.assertEqual(data["key"], "cart-abandoned")
        self.assertEqual(data["name"], "Cart Abandoned")
        self.assertTrue(data["is_active"])
        self.assertEqual(data["templates"], [])

    def test_duplicate_key_is_suffixed(self):
        self.client.post("/api/triggers/", {"name": "Cart Abandoned"}, format="json")
        res = self.client.post("/api/triggers/", {"name": "Cart Abandoned"}, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.json()["key"], "cart-abandoned-2")

    def test_explicit_key_is_respected(self):
        res = self.client.post(
            "/api/triggers/", {"name": "Cart Abandoned", "key": "cart"}, format="json"
        )
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.json()["key"], "cart")

    def test_inactivity_trigger_requires_days(self):
        res = self.client.post(
            "/api/triggers/",
            {"name": "Idle 3 days", "kind": "inactivity"},
            format="json",
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("config", res.json())

    def test_inactivity_trigger_with_days(self):
        res = self.client.post(
            "/api/triggers/",
            {"name": "Idle 3 days", "kind": "inactivity", "config": {"days": 3}},
            format="json",
        )
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.json()["days"], 3)
        self.assertEqual(Trigger.objects.get(key="idle-3-days").days, 3)

    def test_inactivity_rejects_absurd_window(self):
        res = self.client.post(
            "/api/triggers/",
            {"name": "Idle forever", "kind": "inactivity", "config": {"days": 5000}},
            format="json",
        )
        self.assertEqual(res.status_code, 400)

    def test_config_must_be_an_object(self):
        res = self.client.post(
            "/api/triggers/",
            {"name": "Bad config", "kind": "event", "config": [1, 2]},
            format="json",
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("config", res.json())

    def test_days_stripped_from_event_trigger(self):
        res = self.client.post(
            "/api/triggers/",
            {"name": "Plain event", "kind": "event", "config": {"days": 5}},
            format="json",
        )
        self.assertEqual(res.status_code, 201)
        self.assertIsNone(res.json()["days"])

    def test_name_is_required(self):
        res = self.client.post("/api/triggers/", {"kind": "event"}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("name", res.json())

    def test_non_admin_cannot_create(self):
        user = User.objects.create_user(username="u", email="u@example.com", password="pw")
        self.client.force_authenticate(user)
        res = self.client.post("/api/triggers/", {"name": "Nope"}, format="json")
        self.assertEqual(res.status_code, 403)

    def test_new_trigger_appears_in_the_table_shape(self):
        self.client.post("/api/triggers/", {"name": "Cart Abandoned"}, format="json")
        res = self.client.get("/api/triggers/")
        keys = {t["key"] for t in res.json()}
        self.assertIn("cart-abandoned", keys)

    def test_patch_keeps_existing_key(self):
        self.client.post("/api/triggers/", {"name": "Cart Abandoned"}, format="json")
        res = self.client.patch(
            "/api/triggers/cart-abandoned/", {"name": "Cart abandoned v2"}, format="json"
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["key"], "cart-abandoned")
        self.assertEqual(res.json()["name"], "Cart abandoned v2")


class ProviderStatusTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            username="admin", email="a@example.com", password="pw", is_staff=True
        )
        self.client.force_authenticate(self.admin)
        self.trigger = Trigger.objects.create(key="login", name="Login")
        self.template = Template.objects.create(
            trigger=self.trigger, channel=Channel.WHATSAPP, body="Hi"
        )

    def test_defaults_to_not_submitted(self):
        res = self.client.get(f"/api/templates/{self.template.pk}/")
        self.assertEqual(res.json()["provider_status"], "not_submitted")
        self.assertEqual(res.json()["provider_status_label"], "Not submitted to Meta")
        self.assertIsNone(res.json()["provider_submitted_at"])

    def test_status_update_stamps_submitted_at(self):
        res = self.client.patch(
            f"/api/templates/{self.template.pk}/",
            {"provider_status": "pending", "provider_template_name": "welcome_v1"},
            format="json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["provider_status"], "pending")
        self.assertIsNotNone(res.json()["provider_submitted_at"])

    def test_status_requires_template_name(self):
        # A status of approved/pending with no Meta name is meaningless: the
        # name is what actually gets sent.
        res = self.client.patch(
            f"/api/templates/{self.template.pk}/",
            {"provider_status": "approved"},
            format="json",
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("provider_template_name", res.json())

    def test_submitted_at_is_not_overwritten(self):
        self.client.patch(
            f"/api/templates/{self.template.pk}/",
            {"provider_status": "pending", "provider_template_name": "welcome_v1"},
            format="json",
        )
        self.template.refresh_from_db()
        first = self.template.provider_submitted_at
        self.client.patch(
            f"/api/templates/{self.template.pk}/",
            {"provider_status": "approved"},
            format="json",
        )
        self.template.refresh_from_db()
        self.assertEqual(self.template.provider_status, "approved")
        self.assertEqual(self.template.provider_submitted_at, first)

    def test_status_note_round_trips(self):
        self.client.patch(
            f"/api/templates/{self.template.pk}/",
            {
                "provider_status": "rejected",
                "provider_template_name": "welcome_v1",
                "provider_status_note": "Too promotional",
            },
            format="json",
        )
        res = self.client.get(f"/api/templates/{self.template.pk}/")
        self.assertEqual(res.json()["provider_status_note"], "Too promotional")

    def test_invalid_status_rejected(self):
        res = self.client.patch(
            f"/api/templates/{self.template.pk}/",
            {"provider_status": "banana"},
            format="json",
        )
        self.assertEqual(res.status_code, 400)

    def test_toggle_with_update_fields_keeps_stamp(self):
        # ToggleView saves with update_fields; a derived column must survive it.
        self.client.patch(
            f"/api/templates/{self.template.pk}/",
            {
                "provider_status": "approved",
                "provider_template_name": "welcome_v1",
                "body": "Hello {{ first_name }}",
            },
            format="json",
        )
        self.client.post(f"/api/templates/{self.template.pk}/toggle/", {}, format="json")
        self.template.refresh_from_db()
        self.assertEqual(self.template.provider_status, "approved")
        self.assertIsNotNone(self.template.provider_submitted_at)
        self.assertEqual(self.template.variables, ["first_name"])

    def test_email_and_webpush_ignore_provider_status(self):
        # The approval workflow is WhatsApp-only, so a status sent on an email
        # template is coerced back to "not submitted" instead of being stored.
        trigger = Trigger.objects.create(key="logout", name="Logout")
        email = Template.objects.create(
            trigger=trigger, channel=Channel.EMAIL, subject="Bye", body="Bye"
        )
        res = self.client.patch(
            f"/api/templates/{email.pk}/",
            {"provider_status": "approved"},
            format="json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["provider_status"], "not_submitted")
        self.assertIsNone(res.json()["provider_submitted_at"])

    def test_whatsapp_status_requires_template_name(self):
        res = self.client.patch(
            f"/api/templates/{self.template.pk}/",
            {"provider_status": "approved"},
            format="json",
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("provider_template_name", res.json())

    def test_public_config_exposes_template_console_link(self):
        res = self.client.get("/api/config/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("whatsapp", res.json())
        self.assertIn("template_console_url", res.json()["whatsapp"])


class TriggerModelHelperTests(TestCase):
    def test_days_property_parses_config(self):
        t = Trigger.objects.create(
            key="idle", name="Idle", kind="inactivity", config={"days": "4"}
        )
        self.assertEqual(t.days, 4)

    def test_days_property_ignores_garbage(self):
        t = Trigger.objects.create(
            key="idle2", name="Idle 2", kind="inactivity", config={"days": "soon"}
        )
        self.assertIsNone(t.days)

    def test_days_is_none_for_events(self):
        t = Trigger.objects.create(key="e", name="E", kind="event", config={"days": 3})
        self.assertIsNone(t.days)

    def test_provider_status_choices_complete(self):
        self.assertEqual(
            [c[0] for c in ProviderStatus.choices],
            ["not_submitted", "draft", "pending", "approved", "rejected"],
        )
