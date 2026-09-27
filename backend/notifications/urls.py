"""URL routing for the notification API.

Mounted under ``/api/`` (see ``config/urls.py``).
"""

from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from . import views

urlpatterns = [
    # --- public ---
    path("health/", views.HealthView.as_view(), name="health"),
    path("config/", views.PublicConfigView.as_view(), name="public-config"),
    # --- auth ---
    path("auth/register/", views.RegisterView.as_view(), name="register"),
    path("auth/login/", views.LoginView.as_view(), name="login"),
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("auth/logout/", views.LogoutView.as_view(), name="logout"),
    path("auth/me/", views.MeView.as_view(), name="me"),
    path("auth/me/profile/", views.MyProfileView.as_view(), name="my-profile"),
    path("users/activity/", views.ActivityView.as_view(), name="user-activity"),
    # --- triggers (admin) ---
    path("triggers/", views.TriggerListCreateView.as_view(), name="trigger-list"),
    path("triggers/<slug:key>/", views.TriggerDetailView.as_view(), name="trigger-detail"),
    path("triggers/<slug:key>/toggle/", views.TriggerToggleView.as_view(), name="trigger-toggle"),
    path("triggers/<slug:key>/fire/", views.TriggerFireView.as_view(), name="trigger-fire"),
    # --- templates (admin) ---
    path("templates/", views.TemplateListCreateView.as_view(), name="template-list"),
    path("templates/draft-test/", views.DraftTestView.as_view(), name="template-draft-test"),
    path("templates/<int:pk>/", views.TemplateDetailView.as_view(), name="template-detail"),
    path("templates/<int:pk>/toggle/", views.TemplateToggleView.as_view(), name="template-toggle"),
    path("templates/<int:pk>/preview/", views.TemplatePreviewView.as_view(), name="template-preview"),
    path("templates/<int:pk>/test/", views.TemplateTestView.as_view(), name="template-test"),
    path("templates/<int:pk>/sync/", views.TemplateSyncView.as_view(), name="template-sync"),
    # --- web push ---
    path("push/subscribe/", views.PushSubscribeView.as_view(), name="push-subscribe"),
    path("push/unsubscribe/", views.PushUnsubscribeView.as_view(), name="push-unsubscribe"),
    path("push/subscriptions/", views.PushSubscriptionListView.as_view(), name="push-list"),
    # --- admin extras ---
    path("logs/", views.NotificationLogListView.as_view(), name="log-list"),
    path("users/", views.AdminUserListView.as_view(), name="user-list"),
    path("stats/", views.AdminStatsView.as_view(), name="stats"),
    path("variables/scan/", views.VariableScanView.as_view(), name="variable-scan"),
    # --- internal (token authenticated) ---
    path("internal/scan-inactive/", views.InternalScanView.as_view(), name="internal-scan"),
]
