"""Internal SMTP delivery for deployment recovery codes."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage


class SmtpMailer:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        sender: str,
        username: str | None = None,
        password: str | None = None,
        starttls: bool = True,
    ) -> None:
        self.host = host
        self.port = port
        self.sender = sender
        self.username = username
        self.password = password
        self.starttls = starttls

    def __call__(self, recipient: str, code: str) -> None:
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = recipient
        message["Subject"] = "Media Bridge 관리자 복구 코드"
        message.set_content(f"Media Bridge 복구 코드: {code}\n5분 동안 유효합니다.")
        with smtplib.SMTP(self.host, self.port, timeout=10) as client:
            if self.starttls:
                client.starttls()
            if self.username and self.password:
                client.login(self.username, self.password)
            client.send_message(message)
