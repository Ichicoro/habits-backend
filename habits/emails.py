import logging
from concurrent.futures import ThreadPoolExecutor

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"

_executor = ThreadPoolExecutor(max_workers=4)


def _send(payload):
    if not settings.RESEND_API_KEY:
        logger.warning("RESEND_API_KEY is not set; skipping email send: %s", payload.get("subject"))
        return
    try:
        response = requests.post(
            RESEND_API_URL,
            json=payload,
            headers={
                "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            timeout=10,
        )
        response.raise_for_status()
    except requests.RequestException:
        logger.exception("Failed to send email via Resend: %s", payload.get("subject"))


def _send_async(payload):
    _executor.submit(_send, payload)


def send_verification_email(user, verify_url):
    _send_async(
        {
            "from": settings.RESEND_FROM_EMAIL,
            "to": [user.email],
            "subject": "Verify your email for Echoes",
            "html": (
                f"<p>Hi {user.name},</p>"
                f"<p>Confirm your email address to finish setting up your Echoes account.</p>"
                f'<p><a href="{verify_url}">Verify email</a></p>'
                f"<p>This link expires in 24 hours. If you didn't create an Echoes account, "
                f"you can ignore this email.</p>"
            ),
        }
    )


def send_password_reset_email(user, reset_url):
    _send_async(
        {
            "from": settings.RESEND_FROM_EMAIL,
            "to": [user.email],
            "subject": "Reset your Echoes password",
            "html": (
                f"<p>Hi {user.name},</p>"
                f"<p>We received a request to reset your Echoes password.</p>"
                f'<p><a href="{reset_url}">Reset password</a></p>'
                f"<p>This link expires in 1 hour. If you didn't request this, "
                f"you can ignore this email — your password won't be changed.</p>"
            ),
        }
    )
