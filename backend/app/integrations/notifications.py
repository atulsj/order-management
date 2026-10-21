import logging
import smtplib
from email.message import EmailMessage

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def send_email(recipient: str, subject: str, body: str) -> None:
    settings = get_settings()
    if settings.smtp_host is None:
        logger.info(
            "notification_console recipient=%s subject=%s body=%s",
            recipient,
            subject,
            body,
        )
        return
    message = EmailMessage()
    message["From"] = settings.smtp_from_address
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as client:
        if settings.smtp_use_tls:
            client.starttls()
        if settings.smtp_username and settings.smtp_password:
            client.login(
                settings.smtp_username,
                settings.smtp_password.get_secret_value(),
            )
        client.send_message(message)
