"""Write requests as .eml drafts and optionally send them over SMTP."""
from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

from ..profile import Profile


def build_message(profile: Profile, to: str, subject: str, body: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = f"{profile.full_name} <{profile.contact_email}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()
    msg.set_content(body)
    return msg


def write_draft(msg: EmailMessage, outbox: Path, stem: str) -> Path:
    outbox.mkdir(parents=True, exist_ok=True)
    path = outbox / f"{stem}.eml"
    path.write_bytes(bytes(msg))
    return path


def send(msg: EmailMessage, smtp: dict) -> None:
    """Send via SMTP. Password comes from the env var named in smtp.password_env."""
    password = os.environ[smtp.get("password_env", "UNLISTED_SMTP_PASSWORD")]
    with smtplib.SMTP(smtp["host"], int(smtp.get("port", 587)), timeout=30) as s:
        s.starttls()
        s.login(smtp["username"], password)
        s.send_message(msg)
