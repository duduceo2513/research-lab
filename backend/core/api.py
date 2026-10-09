"""Small DRF helpers shared by all apps."""
from __future__ import annotations

import functools

from django.apps import apps


class SchemaSafeQuerysetMixin:
    """Lets drf-spectacular introspect viewsets whose ``get_queryset`` depends on ``request.user``.

    While the OpenAPI schema is generated there is no real user, so ``get_queryset`` returns an empty
    queryset of ``schema_model`` (``'app_label.ModelName'``). Real requests are untouched.
    """

    schema_model: str = ''

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        original = cls.__dict__.get('get_queryset')
        if original is None:
            return

        @functools.wraps(original)
        def get_queryset(self, *args, **kw):
            if getattr(self, 'swagger_fake_view', False):
                return apps.get_model(self.schema_model).objects.none()
            return original(self, *args, **kw)

        cls.get_queryset = get_queryset
