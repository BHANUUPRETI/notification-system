"""Fire the inactivity triggers. Run this daily (Render cron job)."""

from django.core.management.base import BaseCommand

from notifications.tasks import scan_inactive_users


class Command(BaseCommand):
    help = "Notify users who have been inactive for each inactivity trigger's window."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List who would be notified without sending anything.",
        )

    def handle(self, *args, **options):
        report = scan_inactive_users(dry_run=options["dry_run"])
        data = report.as_dict()

        if not data["triggers_scanned"]:
            self.stdout.write(
                self.style.WARNING(
                    "No inactivity triggers found. Run: manage.py seed_triggers"
                )
            )
            return

        self.stdout.write(
            f"Scanned {len(data['triggers_scanned'])} trigger(s): "
            + ", ".join(data["triggers_scanned"])
        )
        self.stdout.write(f"Users notified: {data['users_notified']}")
        for line in data["messages"]:
            self.stdout.write(f"  ! {line}")
        self.stdout.write(self.style.SUCCESS("Scan complete."))
