"""Show which notification channels are ready to send."""

from django.conf import settings
from django.core.management.base import BaseCommand

from notifications.services.registry import configuration_report


class Command(BaseCommand):
    help = "Report provider configuration status for each channel."

    def handle(self, *args, **options):
        sandbox = settings.NOTIFICATIONS["SANDBOX"]
        self.stdout.write(f"Sandbox mode: {'ON' if sandbox else 'OFF'}")
        if sandbox:
            self.stdout.write(
                self.style.WARNING(
                    "  Nothing is sent over the network. Set NOTIFICATION_SANDBOX=False "
                    "once real keys are in .env."
                )
            )
        self.stdout.write("")

        for row in configuration_report():
            mark = self.style.SUCCESS("OK     ") if row["configured"] else self.style.ERROR("MISSING")
            self.stdout.write(
                f"  [{mark}] {row['channel']:<8} {row['provider']:<20} {row['message']}"
            )

        self.stdout.write("")
        self.stdout.write(
            "Generate VAPID keys with:  python manage.py generate_vapid_keys"
        )
