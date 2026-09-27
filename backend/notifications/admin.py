"""Django admin - the fastest way to inspect data while developing.

The real "admin panel" for this project is the Next.js app; this is for
debugging and for a quick manual trigger list.
"""

from django.contrib import admin

from .models import NotificationLog, PushSubscription, Template, Trigger, UserProfile
from .services.dispatcher import fire_trigger


@admin.register(Template)
class TemplateAdmin(admin.ModelAdmin):
    list_display = ("__str__", "channel", "is_enabled", "variables", "updated_at")
    list_filter = ("channel", "is_enabled", "trigger__kind")
    search_fields = ("body", "subject", "title", "trigger__name")


class TemplateInline(admin.TabularInline):
    model = Template
    extra = 0
    fields = ("channel", "title", "subject", "body", "is_enabled")


@admin.register(Trigger)
class TriggerAdmin(admin.ModelAdmin):
    list_display = ("name", "key", "kind", "is_active", "order", "template_summary")
    list_filter = ("kind", "is_active")
    search_fields = ("name", "key", "description")
    list_editable = ("is_active", "order")
    inlines = [TemplateInline]

    @admin.display(description="templates")
    def template_summary(self, obj):
        enabled = [t.get_channel_display() for t in obj.templates.filter(is_enabled=True)]
        return ", ".join(enabled) or "—"

    @admin.action(description="Fire this trigger for the first active user")
    def fire_for_first_user(self, request, queryset):
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.filter(is_active=True).order_by("id").first()
        for trigger in queryset:
            fire_trigger(trigger.key, user, is_test=True)
        self.message_user(request, f"Fired {len(queryset)} trigger(s).")

    actions = [fire_for_first_user]


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "phone_e164",
        "last_seen_at",
        "whatsapp_opt_in",
        "email_opt_in",
        "webpush_opt_in",
    )
    list_filter = ("whatsapp_opt_in", "email_opt_in", "webpush_opt_in")
    search_fields = ("user__username", "user__email", "phone_e164")


@admin.register(PushSubscription)
class PushSubscriptionAdmin(admin.ModelAdmin):
    list_display = ("user", "provider", "is_active", "failure_count", "last_seen_at")
    list_filter = ("provider", "is_active")
    search_fields = ("endpoint", "user__username")


@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "channel",
        "status",
        "trigger",
        "user",
        "destination",
        "is_test",
    )
    list_filter = ("channel", "status", "is_test", "trigger__key")
    search_fields = ("destination", "rendered_body", "user__username")
    readonly_fields = tuple(
        f.name for f in NotificationLog._meta.fields if f.name != "id"
    )
