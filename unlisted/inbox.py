"""Watch the opt-out inbox for broker confirmation emails.

Only links whose host belongs to that broker's `verify_domains` and whose
path looks like a confirmation link are ever opened, and only when
`auto_open_verify_links` is on. Everything else is reported for you to review.
"""
from __future__ import annotations

import email
import imaplib
import os
import re
from dataclasses import dataclass
from datetime import date, timedelta
from email.utils import parseaddr
from urllib.parse import urlparse

import requests

from .brokers import Broker, broker_for_domain

LINK_RE = re.compile(r"https://[^\s\"'<>]+")
VERIFY_PATH_RE = re.compile(r"verif|confirm|opt-?out|remov|suppress|unsubscribe", re.I)


@dataclass
class InboxEvent:
    broker_id: str
    subject: str
    verify_links: list[str]
    opened: list[str]


def verification_links(body: str, broker: Broker) -> list[str]:
    links = []
    for url in LINK_RE.findall(body):
        url = url.rstrip(").,;")
        host = (urlparse(url).hostname or "").lower()
        if broker_for_domain([broker], host) and VERIFY_PATH_RE.search(url):
            links.append(url)
    return list(dict.fromkeys(links))


def _body(msg: email.message.Message) -> str:
    parts = msg.walk() if msg.is_multipart() else [msg]
    out = []
    for part in parts:
        if part.get_content_type() in ("text/plain", "text/html"):
            payload = part.get_payload(decode=True) or b""
            out.append(payload.decode(part.get_content_charset() or "utf-8", "replace"))
    return "\n".join(out)


def check_inbox(imap_cfg: dict, brokers: list[Broker], auto_open: bool,
                days: int = 14) -> list[InboxEvent]:
    if not imap_cfg.get("host"):
        return []
    password = os.environ[imap_cfg.get("password_env", "UNLISTED_IMAP_PASSWORD")]
    since = (date.today() - timedelta(days=days)).strftime("%d-%b-%Y")
    events = []
    with imaplib.IMAP4_SSL(imap_cfg["host"], int(imap_cfg.get("port", 993))) as imap:
        imap.login(imap_cfg["username"], password)
        imap.select(imap_cfg.get("folder", "INBOX"), readonly=True)
        _, data = imap.search(None, "SINCE", since)
        for num in data[0].split():
            _, msg_data = imap.fetch(num, "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])
            sender_domain = parseaddr(msg.get("From", ""))[1].rpartition("@")[2]
            broker = broker_for_domain(brokers, sender_domain)
            if broker is None:
                continue
            links = verification_links(_body(msg), broker)
            opened = []
            if auto_open:
                for link in links:
                    try:
                        requests.get(link, timeout=20).raise_for_status()
                        opened.append(link)
                    except requests.RequestException:
                        pass
            events.append(InboxEvent(broker.id, msg.get("Subject", ""), links, opened))
    return events
