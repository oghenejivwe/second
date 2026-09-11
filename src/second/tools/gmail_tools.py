"""Gmail, as two tools: read the mailbox, and draft without sending.

``draft_email`` is the governing principle in one function -- carry the work to the
last click, and stop. The user opens their drafts, reads it, and presses send, or
does not.

**Nothing here can send, and the scope cannot stop it.** ``gmail.compose`` is the
narrowest scope that permits ``drafts.create``, and it also authorises
``users.messages.send`` and ``users.drafts.send``. Google offers nothing narrower.
So the only thing between Second and a sent email is the transport interlock in
:mod:`second.tools._google`, which refuses all three transmitting routes --
``messages/send``, ``drafts/send`` and ``settings/sendAs/{email}/verify`` -- plus
their ``/upload/`` aliases.

N+1 is deliberate
-----------------

``messages.list`` returns only ``{id, threadId}``, so each result needs a second
call. ``BatchHttpRequest`` would collapse that into one request -- and put every
sub-request inside a ``multipart/mixed`` body where the interlock cannot read
them, which would make a batched ``messages/send`` invisible. Batching is refused
at the transport, so this makes N+1 calls on purpose.

The cost is latency, not quota: ``messages.list`` is 5 units and ``messages.get``
is 20, so a ten-result search is 205 units against 6,000 per minute.
"""

from __future__ import annotations

import base64
import logging
from datetime import datetime, timezone
from email.message import EmailMessage
from email.policy import SMTP
from typing import Any

from strands import tool

from second.tools._google import call, paged, service

logger = logging.getLogger(__name__)

USER_ID = "me"
SNIPPET_LENGTH = 200
"""How much of the body to hand back as a snippet.

Gmail's own ``snippet`` field is undocumented in length (~200 characters in
practice) and absent from ``messages.list``. Deriving our own keeps the real
connector and the fake rendering the same thing, which matters because SURFACES
displays it and the Communicator quotes it."""


class GmailError(RuntimeError):
    """A Gmail call could not be completed. Raised, never returned."""


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def _decode(data: str) -> str:
    """Decode Gmail's base64url body data.

    Gmail commonly omits the ``=`` padding and ``urlsafe_b64decode`` raises
    ``binascii.Error: Incorrect padding`` on it, so the padding is repaired first.
    """
    padded = data + "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(padded).decode("utf-8", "replace")
    except (ValueError, TypeError):
        logger.warning("could not decode a message part")
        return ""


def _body_text(payload: dict[str, Any]) -> str:
    """The best plain-text rendering of a message, walking the MIME tree.

    Prefers ``text/plain``. Falls back to ``text/html`` with the tags stripped,
    because an HTML-only message is common and the Communicator has to be able to
    quote *something* -- every reminder must cite the message it came from, and a
    reminder that cites nothing is worse than no reminder.
    """
    plain, html = _collect(payload)
    if plain.strip():
        return plain.strip()
    if html.strip():
        import re

        text = re.sub(r"<br\s*/?>|</p>", "\n", html, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        return " ".join(text.split())
    return ""


def _collect(part: dict[str, Any]) -> tuple[str, str]:
    """Walk a MIME part, returning (plain, html) text found anywhere beneath it."""
    plain_parts: list[str] = []
    html_parts: list[str] = []

    def visit(node: dict[str, Any]) -> None:
        mime = node.get("mimeType", "")
        data = (node.get("body") or {}).get("data")
        if data:
            if mime == "text/plain":
                plain_parts.append(_decode(data))
            elif mime == "text/html":
                html_parts.append(_decode(data))
        for child in node.get("parts") or []:
            visit(child)

    visit(part)
    return "\n".join(plain_parts), "\n".join(html_parts)


def _headers(payload: dict[str, Any]) -> dict[str, str]:
    """Message headers, lowercased, because Gmail's casing is not guaranteed."""
    return {h.get("name", "").lower(): h.get("value", "") for h in payload.get("headers") or []}


def _message_date(message: dict[str, Any]) -> str:
    """The message date as a naive local-ish ISO string, from ``internalDate``.

    ``internalDate`` is epoch milliseconds and is always present and always a valid
    integer. The ``Date`` header is not: it can be absent, malformed, or carry a
    ``-0000`` offset, which makes ``email.utils.parsedate_to_datetime`` hand back a
    *naive* datetime that a later conversion would then silently misplace.
    """
    stamp = message.get("internalDate")
    if stamp is None:
        logger.warning("message %s has no internalDate", message.get("id"))
        return ""
    try:
        moment = datetime.fromtimestamp(int(stamp) / 1000, tz=timezone.utc)
    except (TypeError, ValueError):
        logger.warning("message %s has an unreadable internalDate %r", message.get("id"), stamp)
        return ""
    return moment.replace(tzinfo=None).isoformat()


def _normalise(message: dict[str, Any]) -> dict[str, Any]:
    """One Gmail message as the small dict this contract returns."""
    payload = message.get("payload") or {}
    headers = _headers(payload)
    body = _body_text(payload)
    return {
        "id": message.get("id", ""),
        "from": headers.get("from", ""),
        "to": headers.get("to", ""),
        "subject": headers.get("subject", ""),
        "date": _message_date(message),
        "snippet": " ".join(body.split())[:SNIPPET_LENGTH] or message.get("snippet", ""),
        "body": body,
    }


@tool
def search_gmail(query: str, max_results: int = 10) -> list[dict]:
    """Search the user's mail.

    Uses Gmail's own search syntax. Useful operators: ``subject:policy``,
    ``from:hr@example.com``, and ``in:sent`` to search what the user has sent
    rather than received -- which is how you establish that something was never
    sent at all.

    Quote multi-word phrases: ``subject:"travel insurance policy"``. Unquoted,
    ``subject:travel insurance policy`` means ``subject:travel`` AND the free-text
    words "insurance" and "policy", which is a different query that happens to work
    on a small mailbox.

    Prefer searching on content rather than dates, so a query keeps working as the
    mailbox ages.

    Args:
        query: Gmail search terms.
        max_results: How many messages to return at most.

    Returns:
        Matching messages, newest first, each with id, from, to, subject, date,
        snippet and body. The body is included because every reminder Second
        raises has to quote the message it came from.

    Raises:
        GmailError: If the query is empty or max_results is not positive.
        GoogleCallFailed: If Gmail could not be reached. Never an empty list on
            failure -- "nothing found" and "could not look" must not be the same
            answer.
    """
    if not query.strip():
        raise GmailError("a search needs a query; an empty query would match the whole mailbox")
    if max_results <= 0:
        raise GmailError(f"max_results must be positive; got {max_results}")

    mail = service("gmail").users().messages()
    found = list(
        paged(
            mail,
            f"search mail for {query!r}",
            key="messages",
            limit=max_results,
            userId=USER_ID,
            q=query,
            maxResults=min(max_results, 500),
        )
    )

    messages = []
    for stub in found:
        full = call(
            mail.get(userId=USER_ID, id=stub["id"], format="full"),
            f"read message {stub['id']!r}",
        )
        messages.append(_normalise(full))
    return messages


# ---------------------------------------------------------------------------
# Drafting
# ---------------------------------------------------------------------------


def rfc822(to: str, subject: str, body: str, *, sent_at: datetime | None = None) -> str:
    """Build an RFC 822 message, base64url encoded the way Gmail wants it.

    Two details that are each worth an evening:

    * ``policy=SMTP``. The default policy emits bare LF line endings, which is the
      documented cause of intermittent ``drafts.create`` 400s and of Gmail
      rendering headers as body text. Measured in this venv: ``SMTP`` gives 11 CRLF
      and 0 bare LF; the default gives 0 CRLF and 8 bare LF.
    * ``raw`` must be a ``str``, not ``bytes``. ``googleapiclient`` calls
      ``json.dumps`` on the body and does no base64 handling of its own, so bytes
      raise ``TypeError: Object of type bytes is not JSON serializable``. The
      ``=`` padding is kept, as in Google's own sample.

    Args:
        sent_at: Stamped into the ``Date`` header. The seeder passes a backdated
            value; ``draft_email`` leaves it unset.
    """
    message = EmailMessage(policy=SMTP)
    message["To"] = to
    message["Subject"] = subject
    if sent_at is not None:
        from email.utils import format_datetime

        message["Date"] = format_datetime(sent_at)
    message.set_content(body)
    return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")


@tool
def draft_email(to: str, subject: str, body: str) -> str:
    """Create a draft email. It is never sent.

    This is the governing principle in one tool: carry the work to the last click,
    and stop. The user opens their drafts, reads it, and presses send -- or does
    not.

    Write the body ready to send, not as a sketch. A draft the user has to finish
    is not the work carried to the last click.

    Args:
        to: Recipient address.
        subject: Subject line.
        body: Full message body.

    Returns:
        A description of the draft, including its id, and the fact that it was not
        sent.

    Raises:
        GmailError: If the recipient, subject or body is empty.
        GoogleGuardViolation: Never, for this call -- but the interlock underneath
            refuses ``drafts.send`` and ``messages.send`` unconditionally, which is
            what makes the promise in this docstring true rather than merely
            intended.
    """
    if not to.strip():
        raise GmailError("a draft needs a recipient")
    if not subject.strip():
        raise GmailError("a draft needs a subject")
    if not body.strip():
        raise GmailError("a draft needs a body; an empty draft is not work carried to the last click")

    # drafts.create has exactly one parameter, userId. There is no query parameter
    # on this route that could send, which is the second reason this is safe; the
    # first is that the interlock refuses the send routes outright.
    created = call(
        service("gmail")
        .users()
        .drafts()
        .create(userId=USER_ID, body={"message": {"raw": rfc822(to.strip(), subject.strip(), body)}}),
        f"draft a message to {to.strip()!r}",
    )

    # Two different ids come back. The draft id is the one a human can act on.
    draft_id = created.get("id", "?")
    return (
        f"drafted {draft_id!r} to {to.strip()} - {subject.strip()!r} "
        f"({len(body)} chars). Not sent; it is waiting in the user's drafts."
    )


ALL_GMAIL_TOOLS = (search_gmail, draft_email)
"""Two tools. There is no ``send_email`` and there is no ``delete_email``."""
