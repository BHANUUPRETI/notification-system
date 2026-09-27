"""Create demo users with phone numbers so test sends have a destination."""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from notifications.models import UserProfile

User = get_user_model()

DEMO_USERS = [
    {
        "username": "demo",
        "email": "demo@example.com",
        "password": "demo12345",
        "first_name": "Demo",
        "last_name": "User",
        "phone_e164": "",  # set your own number to receive real WhatsApp messages
    },
    {
        "username": "amit",
        "email": "amit@example.com",
        "password": "demo12345",
        "first_name": "Amit",
        "last_name": "Sharma",
        "phone_e164": "+919876543210",
    },
    {
        "username": "priya",
        "email": "priya@example.com",
        "password": "demo12345",
        "first_name": "Priya",
        "last_name": "Nair",
        "phone_e164": "+919876543211",
    },
]


class Command(BaseCommand):
    help = "Create the demo users used for testing notifications."

    def add_arguments(self, parser):
        parser.add_argument(
            "--admin",
            action="store_true",
            help="Also create a superuser 'admin' / 'admin12345'.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        for spec in DEMO_USERS:
            user, created = User.objects.get_or_create(
                username=spec["username"],
                defaults={
                    "email": spec["email"],
                    "first_name": spec["first_name"],
                    "last_name": spec["last_name"],
                },
            )
            if created:
                user.set_password(spec["password"])
                user.save(update_fields=["password"])
            profile, _ = UserProfile.objects.get_or_create(user=user)
            if spec["phone_e164"] and not profile.phone_e164:
                profile.phone_e164 = spec["phone_e164"]
                profile.save(update_fields=["phone_e164", "updated_at"])

            self.stdout.write(
                f"  {user.username:<8} {'created' if created else 'exists':<8} "
                f"phone={profile.phone_e164 or '-'}"
            )

        if options["admin"]:
            admin, created = User.objects.get_or_create(
                username="admin",
                defaults={"email": "admin@example.com", "is_staff": True, "is_superuser": True},
            )
            if created:
                admin.set_password("admin12345")
                admin.save(update_fields=["password", "is_staff", "is_superuser"])
            self.stdout.write(
                f"  admin    {'created' if created else 'exists'}  (password: admin12345)"
            )

        self.stdout.write(self.style.SUCCESS("\nDone."))
        self.stdout.write("Sign in with username or email, e.g. 'demo' / 'demo12345'.")
