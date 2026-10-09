"""WebSocket ``/ws/research-lab/runs/<run_id>/`` — live Agent Workspace events for one run.

Server -> client: ``{"event": "research_event", "payload": <serialized ResearchEvent>}``, plus
``connected`` on join and ``pong``. The socket is read-only (apart from ``{"action": "ping"}``): the
authoritative state lives in the database (``GET runs/<id>/events/`` and ``.../workspace/``), this
channel only delivers new events as they are written.

Close codes: 4401 unauthenticated, 4403 forbidden / Research Lab disabled, 4404 unknown run.
"""
from __future__ import annotations

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.conf import settings

from accounts.permissions import is_teacher_or_admin
from research_lab import selectors
from research_lab.services import events

CLOSE_UNAUTHENTICATED = 4401
CLOSE_FORBIDDEN = 4403
CLOSE_NOT_FOUND = 4404


class ResearchRunConsumer(AsyncJsonWebsocketConsumer):
    group: str | None = None

    async def connect(self):
        user = self.scope.get('user')
        if user is None or not user.is_authenticated:
            await self.close(code=CLOSE_UNAUTHENTICATED)
            return
        if not settings.RESEARCH_LAB_ENABLED or not is_teacher_or_admin(user):
            await self.close(code=CLOSE_FORBIDDEN)
            return
        run_id = int(self.scope['url_route']['kwargs']['run_id'])
        if not await self._can_see(user, run_id):
            await self.close(code=CLOSE_NOT_FOUND)  # same answer for "missing" and "not yours"
            return
        self.group = events.group_name(run_id)
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()
        await self.send_json({'event': 'connected', 'payload': {'run_id': run_id}})

    async def disconnect(self, code):
        if self.group:
            await self.channel_layer.group_discard(self.group, self.channel_name)

    async def receive_json(self, content, **kwargs):
        if isinstance(content, dict) and content.get('action') == 'ping':
            await self.send_json({'event': 'pong', 'payload': {}})

    async def research_event(self, message):
        await self.send_json({'event': 'research_event', 'payload': message['event']})

    @database_sync_to_async
    def _can_see(self, user, run_id: int) -> bool:
        return selectors.runs_for_user(user).filter(pk=run_id).exists()
