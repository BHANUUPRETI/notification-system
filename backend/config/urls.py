"""Root URL configuration.

Custom 400/404/500 handlers keep API responses JSON even when ``DEBUG`` is on,
so the Next.js client never has to parse a Django HTML error page.
"""

from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def json_400(request, exception=None):
    return JsonResponse({"detail": "Bad request."}, status=400)


def json_404(request, exception=None):
    return JsonResponse({"detail": "Not found."}, status=404)


def json_500(request):
    # Never leak internals; the traceback is already in the server log.
    return JsonResponse({"detail": "Internal server error."}, status=500)


handler400 = "config.urls.json_400"
handler404 = "config.urls.json_404"
handler500 = "config.urls.json_500"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("notifications.urls")),
    path("api-auth/", include("rest_framework.urls")),
]
