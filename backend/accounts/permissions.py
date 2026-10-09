"""Role-based DRF permissions used across all apps.

Object-level rule: models expose ``user_can_manage(user) -> bool``;
``IsManagerOrReadOnly`` delegates write access on objects to it. Read
visibility is enforced by each view's queryset (selectors), so a student can
never even discover objects they are not allowed to see.
"""
from rest_framework.permissions import SAFE_METHODS, BasePermission

from accounts.models import UserRole


def _role(user):
    return getattr(user, 'role', None)


def is_admin(user) -> bool:
    return bool(user and user.is_authenticated and (user.is_superuser or _role(user) == UserRole.ADMIN))


def is_teacher_or_admin(user) -> bool:
    return bool(user and user.is_authenticated and (is_admin(user) or _role(user) == UserRole.TEACHER))


class IsAdminRole(BasePermission):
    def has_permission(self, request, view):
        return is_admin(request.user)


class IsTeacherOrAdmin(BasePermission):
    def has_permission(self, request, view):
        return is_teacher_or_admin(request.user)


class IsTeacherOrAdminOrReadOnly(BasePermission):
    """Any authenticated user may read; only teachers/admins may write."""

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        return request.method in SAFE_METHODS or is_teacher_or_admin(request.user)


class IsAdminWriteStaffRead(BasePermission):
    """Global configuration (RAG/LLM/speech profiles): teachers and admins read, only admins write."""

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return is_teacher_or_admin(request.user)
        return is_admin(request.user)


class IsManagerOrReadOnly(IsTeacherOrAdminOrReadOnly):
    """Object writes require ``obj.user_can_manage(request.user)``."""

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        if is_admin(request.user):
            return True
        checker = getattr(obj, 'user_can_manage', None)
        return bool(checker and checker(request.user))


class IsManager(BasePermission):
    """Teachers/admins only. Reads of a visible object are allowed (visibility is enforced by the
    view's queryset); writes and actions require ``obj.user_can_manage(user)``."""

    def has_permission(self, request, view):
        return is_teacher_or_admin(request.user)

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS or is_admin(request.user):
            return True
        checker = getattr(obj, 'user_can_manage', None)
        return bool(checker and checker(request.user))
