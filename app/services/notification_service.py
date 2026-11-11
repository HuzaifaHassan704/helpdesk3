import asyncio
import smtplib
from email.message import EmailMessage

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("app.notifications")


def _clean(value: str) -> str:
    return value.replace("\r", " ").replace("\n", " ")[:200]  # header-injection safe


def _send(to: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = settings.SMTP_FROM, to, _clean(subject)
    msg.set_content(body)
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as smtp:
        if settings.SMTP_STARTTLS:
            smtp.starttls()
        if settings.SMTP_USER:
            smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        smtp.send_message(msg)


async def notify(to: str, subject: str, body: str) -> None:
    """Email a user. Without SMTP_HOST it only logs, so development needs no mail server. Never raises."""
    logger.info("notification", to=to, subject=_clean(subject), smtp=bool(settings.SMTP_HOST))
    if not settings.SMTP_HOST:
        return
    try:
        await asyncio.to_thread(_send, to, subject, body)
    except Exception:
        logger.exception("notification_failed", to=to)
