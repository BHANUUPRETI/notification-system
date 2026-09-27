"""Delete old notification logs."""

from django.core.management.base import BaseCommand

from notifications.tasks import purge_old_logs


class Command(BaseCommand):
    help = (
        "Delete NotificationLog rows older than the retention window. "
        "Use --days 0 to disable cleanup."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=None,
            help="Override NOTIFICATION_LOG_RETENTION_DAYS (settings key LOG_RETENTION_DAYS).",
        )

    def handle(self, *args, **options):
        deleted = purge_old_logs(days=options["days"])
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} log row(s)."))
