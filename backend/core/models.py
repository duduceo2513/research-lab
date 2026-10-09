"""Shared abstract base models."""
from django.db import models


class TimestampedModel(models.Model):
    """Adds created_at / updated_at."""

    created_at = models.DateTimeField('created at', auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField('updated at', auto_now=True)

    class Meta:
        abstract = True


class MetadataMixin(models.Model):
    """Free-form, non-relational extras (never a substitute for real columns)."""

    metadata = models.JSONField('metadata', default=dict, blank=True)

    class Meta:
        abstract = True
