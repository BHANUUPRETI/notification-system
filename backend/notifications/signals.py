"""Signal handlers.

These keep ``UserProfile`` in sync (auto-created, ``last_seen_at`` updated on
sign-in) so the inactivity triggers have something to read. Notification
firing itself is *not* done here - it is triggered explicitly by the auth API
so a single sign-in cannot produce duplicate messages.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import UserProfile


@receiver(post_save, sender=get_user_model(), dispatch_uid="create_user_profile")
def ensure_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.get_or_create(user=instance)


@receiver(user_logged_in, dispatch_uid="profile_mark_seen_on_login")
def mark_seen_on_login(sender, request, user, **kwargs):
    profile, _ = UserProfile.objects.get_or_create(user=user)
    if profile.last_seen_at is None or profile.last_seen_at < user.last_login:
        profile.last_seen_at = user.last_login
        profile.save(update_fields=["last_seen_at", "updated_at"])


@receiver(user_logged_out, dispatch_uid="profile_mark_seen_on_logout")
def mark_seen_on_logout(sender, request, user, **kwargs):
    if user is None:
        return
    profile = UserProfile.objects.filter(user=user).first()
    if profile is not None:
        from django.utils import timezone

        profile.last_seen_at = timezone.now()
        profile.save(update_fields=["last_seen_at", "updated_at"])
