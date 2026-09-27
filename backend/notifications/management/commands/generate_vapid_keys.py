"""Print a fresh VAPID key pair for raw Web Push."""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Generate a VAPID public/private key pair for Web Push."

    def handle(self, *args, **options):
        try:
            from py_vapid import Vapid
        except ImportError:  # pragma: no cover
            self.stderr.write(
                "py_vapid is not installed. Add it with: pip install py-vapid"
            )
            return

        vapid = Vapid()
        vapid.generate_keys()
        self.stdout.write(self.style.SUCCESS("Add these to backend/.env:\n"))
        self.stdout.write(f"VAPID_PUBLIC_KEY={vapid.public_key}")
        self.stdout.write(f"VAPID_PRIVATE_KEY={vapid.private_key}")
        self.stdout.write("VAPID_CLAIM_EMAIL=mailto:you@example.com")
        self.stdout.write(
            "\nNote: keep VAPID_PRIVATE_KEY secret. The public key goes to the browser."
        )
