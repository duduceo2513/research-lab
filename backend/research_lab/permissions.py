"""Research Lab is teacher/admin content-authoring tooling, not a student-facing feature, and is
subject to the ``RESEARCH_LAB_ENABLED`` feature flag."""
from __future__ import annotations

from django.conf import settings
from rest_framework.permissions import SAFE_METHODS, BasePermission

from accounts.permissions import is_admin, is_teacher_or_admin


class IsResearchLabEnabled(BasePermission):
    message = 'Research Lab is disabled on this server.'

    def has_permission(self, request, view):
        return settings.RESEARCH_LAB_ENABLED


class IsResearchLabUser(BasePermission):
    """Teachers/admins only; object-level access is "own run, or admin" via ``user_can_manage``."""

    def has_permission(self, request, view):
        return is_teacher_or_admin(request.user)

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS and is_admin(request.user):
            return True
        checker = getattr(obj, 'user_can_manage', None)
        return bool(checker and checker(request.user))
