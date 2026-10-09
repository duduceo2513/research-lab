"""Helpers for building compact, safe, cross-linked admin pages."""
from __future__ import annotations

from django.contrib import admin
from django.urls import NoReverseMatch, reverse
from django.utils.html import format_html
from django.utils.text import Truncator


def truncated(text: str | None, length: int = 80) -> str:
    return Truncator(text or '').chars(length)


def admin_link(obj, label: str | None = None):
    """Link to the admin change page of ``obj`` (or '-' when empty/unroutable)."""
    if obj is None:
        return '-'
    opts = obj._meta
    try:
        url = reverse(f'admin:{opts.app_label}_{opts.model_name}_change', args=[obj.pk])
    except NoReverseMatch:
        return str(obj)
    return format_html('<a href="{}">{}</a>', url, label or str(obj))


def preview_block(text: str | None, limit: int = 4000):
    """Read-only, scrollable, pre-formatted preview of a long text field."""
    text = text or ''
    shown = text[:limit]
    suffix = f'\n… (+{len(text) - limit} chars)' if len(text) > limit else ''
    return format_html(
        '<pre style="max-height:320px;overflow:auto;white-space:pre-wrap;margin:0">{}{}</pre>',
        shown, suffix,
    )


class TimestampedAdminMixin:
    """Marks created_at/updated_at read-only wherever they exist."""

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        model_fields = {f.name for f in self.model._meta.get_fields()}
        for name in ('created_at', 'updated_at'):
            if name in model_fields and name not in fields:
                fields.append(name)
        return fields


class ReadOnlyAdmin(admin.ModelAdmin):
    """Journal-style models: no manual add/change (delete stays for admins)."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
