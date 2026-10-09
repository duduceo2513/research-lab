"""Domain exceptions shared by service layers, plus the DRF handler that maps them."""
from __future__ import annotations

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


class ServiceError(Exception):
    """Base class for expected, user-presentable failures raised from services."""

    status_code = status.HTTP_400_BAD_REQUEST
    code = 'service_error'

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code


class PermissionDeniedError(ServiceError):
    status_code = status.HTTP_403_FORBIDDEN
    code = 'permission_denied'


class ConflictError(ServiceError):
    status_code = status.HTTP_409_CONFLICT
    code = 'conflict'


class ExternalServiceError(ServiceError):
    """An upstream provider (LLM, STT, TTS, embeddings) failed."""

    status_code = status.HTTP_502_BAD_GATEWAY
    code = 'external_service_error'


def api_exception_handler(exc, context):
    if isinstance(exc, ServiceError):
        return Response({'detail': exc.message, 'code': exc.code}, status=exc.status_code)
    return drf_exception_handler(exc, context)
