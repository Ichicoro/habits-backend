"""Fan-out helpers for realtime board nudges.

Every function here is fail-open by construction. Broadcasts are triggered from
`transaction.on_commit` in habits.signals, and an exception raised in an
on_commit callback propagates to the request *after* the write has already been
committed - which would turn a degraded channel layer into a 500 on a
successful expense creation, prompting the user to retry and duplicate it. So
every failure is swallowed and logged, the way habits.notifications treats Expo
push delivery.

Unlike that module these sends are *not* handed to a thread pool. asgiref's
async_to_sync reaches back to the event loop that spawned the current sync
thread, which is how a send from a sync view reaches sockets living on the
server's loop. A plain ThreadPoolExecutor severs that link: the send then runs
on a brand-new loop, and under InMemoryChannelLayer it lands in a queue nobody
is awaiting - silently dropped, no exception. Sending inline keeps it correct.
The latency that a thread pool would have bought back is instead bounded by the
socket timeouts on the Redis channel layer in settings.
"""

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings

logger = logging.getLogger(__name__)


def _send(group: str, message: dict):
    try:
        channel_layer = get_channel_layer()
        if channel_layer is None:
            return
        async_to_sync(channel_layer.group_send)(group, message)
        # Logged after the send so it reflects a completed fan-out, not just an
        # intent: "socket connected" and "nudge reached the right group" are
        # separate failure modes and this is the only signal for the second.
        logger.debug("broadcast %s to %s", message.get("type"), group)
    except Exception:
        # Never re-raise: callers are post-commit hooks on successful writes.
        logger.exception("Failed to broadcast %s to %s", message.get("type"), group)


def broadcast_board_changed(board_id, kind: str):
    """Nudge everyone watching `board_id` that something of `kind` changed.

    `kind` is a hint letting the client pick the cheapest refetch; it is never
    the data itself. Values: "expense", "board", "category", "members".
    """
    if not settings.REALTIME_ENABLED or board_id is None:
        return
    _send(
        f"board_{board_id}",
        {"type": "board.changed", "board_id": str(board_id), "kind": kind},
    )


def broadcast_membership_refresh(user_id):
    """Tell one user's sockets to re-resolve which board groups they belong to.

    Needed when a user joins or leaves a board: the groups joined at connect
    time are now stale, and without this a newly joined board would not receive
    live updates until the next reconnect.
    """
    if not settings.REALTIME_ENABLED or user_id is None:
        return
    _send(f"user_{user_id}", {"type": "membership.refresh"})
