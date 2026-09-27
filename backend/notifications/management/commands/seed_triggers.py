"""Seed the triggers from the spec (and optional starter template copy)."""

from django.core.management.base import BaseCommand
from django.db import transaction

from notifications.constants import (
    TRIGGER_INACTIVE_1D,
    TRIGGER_INACTIVE_1W,
    TRIGGER_LOGIN,
    TRIGGER_LOGOUT,
    TRIGGER_ORDER_PLACED,
    TRIGGER_PASSWORD_RESET,
    Channel,
    TriggerKind,
)
from notifications.models import Template, Trigger

TRIGGERS = [
    {
        "key": TRIGGER_LOGIN,
        "name": "Login",
        "description": "User signs in on the website.",
        "kind": TriggerKind.EVENT,
        "config": {},
        "order": 10,
    },
    {
        "key": TRIGGER_LOGOUT,
        "name": "Logout",
        "description": "User signs out.",
        "kind": TriggerKind.EVENT,
        "config": {},
        "order": 20,
    },
    {
        "key": TRIGGER_INACTIVE_1D,
        "name": "Not logged in 1 day",
        "description": "User has not visited the website for 24 hours.",
        "kind": TriggerKind.INACTIVITY,
        "config": {"days": 1},
        "order": 30,
    },
    {
        "key": TRIGGER_INACTIVE_1W,
        "name": "Not logged in 1 week",
        "description": "User has not visited for 7 days.",
        "kind": TriggerKind.INACTIVITY,
        "config": {"days": 7},
        "order": 40,
    },
    {
        "key": TRIGGER_PASSWORD_RESET,
        "name": "Password reset",
        "description": "User asks to reset their password.",
        "kind": TriggerKind.EVENT,
        "config": {},
        "order": 50,
    },
    {
        "key": TRIGGER_ORDER_PLACED,
        "name": "Order placed",
        "description": "User completes a purchase.",
        "kind": TriggerKind.EVENT,
        "config": {},
        "order": 60,
    },
]

# Starter copy so the admin table is not empty. Everything is editable.
STARTER_TEMPLATES = {
    TRIGGER_LOGIN: {
        Channel.WHATSAPP: {
            "body": "Welcome back, {{ first_name }}! 👋 You just logged in to {{ site_name }}.",
        },
        Channel.EMAIL: {
            "subject": "You logged in successfully",
            "body": "Hi {{ first_name }},\n\nYou logged in to {{ site_name }} successfully.\n"
            "Your last visit was {{ last_seen }}.\n\n— {{ site_name }}",
        },
        Channel.WEBPUSH: {
            "title": "Welcome back!",
            "body": "You just logged in to {{ site_name }}.",
        },
    },
    TRIGGER_LOGOUT: {
        Channel.WHATSAPP: {
            "body": "You have been signed out of {{ site_name }}}. See you soon!",
        },
        Channel.EMAIL: {
            "subject": "You have been signed out",
            "body": "Hi {{ first_name }},\n\nYou signed out of {{ site_name }} at {{ time }} on {{ date }}.\n"
            "Come back any time.\n\n— {{ site_name }}",
        },
        Channel.WEBPUSH: {
            "title": "Signed out",
            "body": "You have been signed out of {{ site_name }}.",
        },
    },
    TRIGGER_INACTIVE_1D: {
        Channel.WHATSAPP: {
            "body": "We miss you, {{ first_name }}! You have not visited {{ site_name }} for {{ days }} day. Come back?",
        },
        Channel.EMAIL: {
            "subject": "We miss you — come back to {{ site_name }}",
            "body": "Hi {{ first_name }},\n\nIt has been {{ days }} day since your last visit to "
            "{{ site_name }}.\n\n— {{ site_name }}",
        },
        Channel.WEBPUSH: {
            "title": "We miss you",
            "body": "You have not visited in {{ days }} day. Come visit us again.",
        },
    },
    TRIGGER_INACTIVE_1W: {
        Channel.WHATSAPP: {
            "body": "It has been {{ days }} days, {{ first_name }}! Your {{ site_name }} account is waiting. 💛",
        },
        Channel.EMAIL: {
            "subject": "It's been a week since your last visit",
            "body": "Hi {{ first_name }},\n\nIt has been {{ days }} days since you last visited "
            "{{ site_name }}.\n\nHere is what you missed.\n\n— {{ site_name }}",
        },
        Channel.WEBPUSH: {
            "title": "Come visit us again",
            "body": "It has been {{ days }} days since your last visit to {{ site_name }}.",
        },
    },
    TRIGGER_PASSWORD_RESET: {
        Channel.EMAIL: {
            "subject": "Reset your {{ site_name }} password",
            "body": "Hi {{ first_name }},\n\nUse the link in this email to choose a new password.\n"
            "If you did not ask for this, you can ignore this email.\n\n— {{ site_name }}",
        },
    },
    TRIGGER_ORDER_PLACED: {
        Channel.EMAIL: {
            "subject": "Order confirmed — thank you!",
            "body": "Hi {{ first_name }},\n\nThanks for your order on {{ date }}. We will email you again when it ships.\n\n— {{ site_name }}",
        },
        Channel.WEBPUSH: {
            "title": "Order confirmed",
            "body": "Thanks for your order, {{ first_name }}!",
        },
    },
}


def _spec_defaults(spec: dict) -> dict:
    """Everything in a trigger spec except its key."""
    return {k: v for k, v in spec.items() if k != "key"}


class Command(BaseCommand):
    help = (
        "Create the standard triggers (and optionally starter templates). "
        "Existing triggers are left untouched unless --reset is given."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--with-templates",
            action="store_true",
            help="Also create starter template copy for each trigger/channel.",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Overwrite existing triggers/toggles instead of leaving them alone.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        with_templates = options["with_templates"]
        reset = options["reset"]

        for spec in TRIGGERS:
            # A trigger that does not exist yet must be created with the full
            # spec (kind, config, days...). Passing an empty `defaults` here
            # would silently fall back to the model default of "event", which
            # breaks the inactivity triggers.
            existing = Trigger.objects.filter(key=spec["key"]).first()
            if existing is None:
                trigger = Trigger.objects.create(**spec)
                verb = "created"
            elif reset:
                # --reset also re-enables the trigger, which the spec dict does
                # not carry (an admin may have switched it off).
                trigger = Trigger.objects.update_or_create(
                    key=spec["key"],
                    defaults={**_spec_defaults(spec), "is_active": True},
                )[0]
                verb = "updated"
            else:
                trigger = existing
                verb = "kept"
            self.stdout.write(
                f"  trigger {trigger.key:<22} {verb}  (kind={trigger.kind})"
            )

            if not with_templates:
                continue

            for channel, fields in STARTER_TEMPLATES.get(trigger.key, {}).items():
                existing = Template.objects.filter(
                    trigger=trigger, channel=channel
                ).first()
                if existing is None or reset:
                    template, t_created = Template.objects.update_or_create(
                        trigger=trigger, channel=channel, defaults=fields
                    )
                else:
                    template, t_created = existing, False
                marker = "created" if t_created else "kept"
                self.stdout.write(
                    f"      {channel:<8} template {marker}  (vars: "
                    f"{', '.join(template.variables) or '-'})"
                )

        self.stdout.write(self.style.SUCCESS("\nDone."))
        if not with_templates:
            self.stdout.write("Re-run with --with-templates to add starter copy.")
