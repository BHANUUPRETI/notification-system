"""Permissions for the API."""

from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsAdminUser(BasePermission):
    """Any authenticated staff/superuser.

    Used for every admin-panel endpoint (the notification table, logs, users).
    """

    message = "Admin (staff) access is required for this endpoint."

    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(user and user.is_authenticated and (user.is_staff or user.is_superuser))


class IsAdminOrReadOnly(BasePermission):
    """Anyone authenticated may read; only admins may write."""

    def has_permission(self, request, view) -> bool:
        if request.method in SAFE_METHODS:
            return bool(request.user and request.user.is_authenticated)
        return IsAdminUser().has_permission(request, view)


class AllowAnyPublic(BasePermission):
    """Unauthenticated access (health check, public config)."""

    def has_permission(self, request, view) -> bool:
        return True
