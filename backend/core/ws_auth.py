"""JWT authentication for WebSockets.

Browsers cannot set an ``Authorization`` header on a WebSocket, so the access token may be sent as
``?token=<jwt>`` (or, for non-browser clients, as an ``Authorization: Bearer`` header). The token is
never logged; ``daphne.access`` is silenced in settings because it would print the query string.
"""
from __future__ import annotations

import logging
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken

logger = logging.getLogger('research_lab')


def _extract_token(scope) -> str | None:
    query = parse_qs(scope.get('query_string', b'').decode())
    if query.get('token'):
        return query['token'][0]
    for name, value in scope.get('headers', []):
        if name == b'authorization':
            parts = value.decode().split()
            if len(parts) == 2 and parts[0].lower() == 'bearer':
                return parts[1]
    return None


@database_sync_to_async
def _get_user(token: str):
    User = get_user_model()
    try:
        validated = AccessToken(token)
        user = User.objects.get(pk=validated['user_id'])
    except (TokenError, User.DoesNotExist, KeyError):
        return AnonymousUser()
    return user if user.is_active else AnonymousUser()


class JWTAuthMiddleware(BaseMiddleware):
    async def __call__(self, scope, receive, send):
        scope = dict(scope)
        token = _extract_token(scope)
        scope['user'] = await _get_user(token) if token else AnonymousUser()
        if token and not scope['user'].is_authenticated:
            logger.warning('WebSocket connection with an invalid or expired token rejected')
        return await super().__call__(scope, receive, send)
