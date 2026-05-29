"""Email delivery via SMTP (standard library only)."""

import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def send_email(*, host: str, port: int | str, username: str | None, password: str | None,
               sender: str, recipient: str, subject: str, html_body: str,
               use_tls: bool = True) -> None:
    """Send a single HTML email. Raises on SMTP/connection failure."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(host, int(port), timeout=30) as server:
        if use_tls:
            server.starttls(context=ssl.create_default_context())
        if username:
            server.login(username, password or "")
        server.sendmail(sender, [recipient], msg.as_string())
