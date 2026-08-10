"""Websocket consumer backing realtime board sync.

The socket is a *nudge* channel: it never carries authoritative data, only
"board X changed, kind Y". Clients react by refetching over the normal REST
API. That keeps this layer optional - a client that never connects, or whose
connection drops, is merely stale rather than wrong, and a full refetch on
(re)connect makes missed messages a non-issue.
"""

import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from rest_framework.authtoken.models import Token

from habits import models

logger = logging.getLogger(__name__)

# Closing before accept() means the handshake never completes, so a real client
# sees an HTTP 403 rather than this code - it is only visible to ASGI-level
# tests. That is the deliberate tradeoff: never accept an unauthenticated
# socket, at the cost of the client not being able to tell "bad token" from
# "no websocket endpoint here". Both are handled the same way anyway (back off
# and retry), and an actually-invalid token gets cleared by the REST layer's
# 401 interceptor, which logs out and tears down this socket with it.
CLOSE_UNAUTHORIZED = 4001


def board_group(board_id) -> str:
    return f"board_{board_id}"


def user_group(user_id) -> str:
    return f"user_{user_id}"


class BoardConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        token_key = self._token_from_query()
        if not token_key:
            await self.close(code=CLOSE_UNAUTHORIZED)
            return

        user = await self._authenticate(token_key)
        if user is None:
            await self.close(code=CLOSE_UNAUTHORIZED)
            return

        self.user = user
        self.board_ids = set()
        await self.accept()
        await self.channel_layer.group_add(user_group(user.id), self.channel_name)
        await self._sync_board_groups()

    async def disconnect(self, code):
        # `user` is unset if we closed before authenticating.
        if not hasattr(self, "user"):
            return
        await self.channel_layer.group_discard(user_group(self.user.id), self.channel_name)
        for board_id in self.board_ids:
            await self.channel_layer.group_discard(board_group(board_id), self.channel_name)

    async def receive_json(self, content, **kwargs):
        # Liveness only. The client has nothing else to say - all state changes
        # go through the REST API.
        if content.get("action") == "ping":
            await self.send_json({"type": "pong"})

    # -- outbound handlers (names match the "type" used by realtime.broadcast) --

    async def board_changed(self, event):
        await self.send_json(
            {"type": "board.changed", "board_id": event["board_id"], "kind": event["kind"]}
        )

    async def membership_refresh(self, event):
        # The set of boards this user belongs to changed, so the groups joined
        # at connect time are stale. Re-resolve instead of forcing a reconnect,
        # otherwise being added to a board wouldn't go live until the next one.
        await self._sync_board_groups()
        await self.send_json({"type": "board.changed", "board_id": None, "kind": "members"})

    # -- internals --

    def _token_from_query(self) -> str | None:
        # Token travels in the query string rather than an Authorization header:
        # browsers cannot set headers on a websocket handshake, and this keeps
        # the door open for a web client later.
        raw = self.scope.get("query_string", b"").decode()
        for part in raw.split("&"):
            key, _, value = part.partition("=")
            if key == "token" and value:
                return value
        return None

    async def _sync_board_groups(self):
        current = set(await self._board_ids_for_user())
        for board_id in current - self.board_ids:
            await self.channel_layer.group_add(board_group(board_id), self.channel_name)
        for board_id in self.board_ids - current:
            await self.channel_layer.group_discard(board_group(board_id), self.channel_name)
        self.board_ids = current

    @database_sync_to_async
    def _authenticate(self, token_key: str):
        try:
            return Token.objects.select_related("user").get(key=token_key).user
        except Token.DoesNotExist:
            return None

    @database_sync_to_async
    def _board_ids_for_user(self):
        return list(
            models.BoardUser.objects.filter(user=self.user).values_list("board_id", flat=True)
        )
