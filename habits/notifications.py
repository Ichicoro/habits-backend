import logging
from concurrent.futures import ThreadPoolExecutor

import requests

from habits import models

logger = logging.getLogger(__name__)

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"

_executor = ThreadPoolExecutor(max_workers=4)


def _send_expo_push(messages):
    try:
        response = requests.post(
            EXPO_PUSH_URL,
            json=messages,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            timeout=10,
        )
        response.raise_for_status()
    except requests.RequestException:
        logger.exception("Failed to send Expo push notification")


def notify_expense_added(expense):
    board = expense.board
    recipients = board.users.filter(
        notify_on_expense=True, user__push_notifications_enabled=True
    ).exclude(user=expense.payer)
    tokens = list(
        models.PushToken.objects.filter(user__in=[bu.user for bu in recipients]).values_list(
            "token", flat=True
        )
    )
    if not tokens:
        return

    messages = [
        {
            "to": token,
            "title": board.name,
            "body": (
                f"{expense.payer.username} added an expense: "
                f"{expense.description or expense.amount}"
            ),
            "data": {"boardId": str(board.id), "expenseId": str(expense.id)},
        }
        for token in tokens
    ]
    _executor.submit(_send_expo_push, messages)
