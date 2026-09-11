"""The Gmail tools, against recorded payloads.

The fixtures carry the shapes Gmail actually returns, including the ones that are
easy to get wrong and silent when you do: a missing ``messages`` key on zero hits,
unpadded base64url, an HTML-only message, and ``internalDate`` as a string of epoch
milliseconds.
"""

from __future__ import annotations

import base64
import json
from email import message_from_bytes
from email.policy import SMTP

import pytest

from second.tools import _google, gmail_tools
from second.tools._google import GoogleGuardViolation, recorded_service
from second.tools.gmail_tools import GmailError, draft_email, rfc822, search_gmail

MESSAGES = "/gmail/v1/users/me/messages"
DRAFTS = "/gmail/v1/users/me/drafts"


def _b64(text: str, *, strip_padding: bool = False) -> str:
    encoded = base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii")
    return encoded.rstrip("=") if strip_padding else encoded


def _message(message_id, subject, sender, body, internal_date="1757318400000", **extra):
    """A Gmail ``messages.get(format='full')`` payload."""
    payload = {
        "id": message_id,
        "threadId": f"t-{message_id}",
        "internalDate": internal_date,
        "snippet": "gmail's own snippet",
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "Subject", "value": subject},
                {"name": "From", "value": sender},
                {"name": "To", "value": "jivwewonder@gmail.com"},
                {"name": "Date", "value": "Tue, 08 Sep 2026 09:00:00 +0100"},
            ],
            "body": {"data": _b64(body)},
        },
    }
    payload.update(extra)
    return payload


def _install(responses):
    resource, transport = recorded_service("gmail", responses)
    _google.install_service("gmail", resource)
    return transport


@pytest.fixture(autouse=True)
def _clean():
    _google.reset_services()
    yield
    _google.reset_services()


# ---------------------------------------------------------------------------
# Searching
# ---------------------------------------------------------------------------


def test_search_returns_the_contract_shape():
    _install(
        {
            ("GET", MESSAGES): {"messages": [{"id": "mpolicy", "threadId": "t"}], "resultSizeEstimate": 1},
            ("GET", f"{MESSAGES}/mpolicy"): _message(
                "mpolicy",
                "Your travel insurance policy AB-4471-92X",
                "no-reply@ableinsure.example",
                "Policy number: AB-4471-92X\nCover: Annual multi-trip, Europe",
            ),
        }
    )
    (message,) = search_gmail("subject:policy")

    assert set(message) == {"id", "from", "to", "subject", "date", "snippet", "body"}
    assert message["id"] == "mpolicy"
    assert message["subject"] == "Your travel insurance policy AB-4471-92X"
    assert message["from"] == "no-reply@ableinsure.example"
    assert "AB-4471-92X" in message["body"], "the Preparer has to be able to find the policy number"
    assert "AB-4471-92X" in message["snippet"]


def test_zero_hits_returns_an_empty_list_without_raising():
    """Gmail omits the ``messages`` key entirely on zero hits -- the body is
    ``{"resultSizeEstimate": 0}``, not an empty list. Indexing it raises KeyError,
    and the tempting repair (wrap the search, return ``[]``) is exactly how "could
    not look" becomes indistinguishable from "nothing found".

    Here nothing matched *and the call succeeded*, so an empty list is the honest
    answer. The distinction is that a transport failure raises; see
    :func:`test_a_failed_search_raises_rather_than_returning_empty`.
    """
    _install({("GET", MESSAGES): {"resultSizeEstimate": 0}})
    assert search_gmail("subject:nothingmatchesthis") == []


def test_a_failed_search_raises_rather_than_returning_empty():
    """The failure direction that matters most in this domain."""
    _install({("GET", MESSAGES): (503, {"error": {"errors": [{"reason": "backendError"}]}})})
    with pytest.raises(Exception) as raised:
        search_gmail("subject:policy")
    assert "could not" in str(raised.value)


def test_search_asks_for_the_full_format_not_metadata():
    """``format='metadata'`` returns headers and no body. The smoke test passes and
    then the Preparer cannot quote the policy number -- which is the whole point of
    the search."""
    transport = _install(
        {
            ("GET", MESSAGES): {"messages": [{"id": "mpolicy"}]},
            ("GET", f"{MESSAGES}/mpolicy"): _message("mpolicy", "s", "a@b.c", "body"),
        }
    )
    search_gmail("subject:policy")

    (_, uri, _) = next(call for call in transport.calls if "/messages/mpolicy" in call[1])
    assert "format=full" in uri, uri


def test_search_paginates_to_reach_the_eleventh_match():
    """A demo inbox with 11 matching emails that returns 10 is the kind of thing
    that shows up on stage."""
    pages = iter(
        [
            {"messages": [{"id": f"m{n:02d}"} for n in range(5)], "nextPageToken": "p2"},
            {"messages": [{"id": f"m{n:02d}"} for n in range(5, 11)]},
        ]
    )
    _install(
        {
            ("GET", MESSAGES): lambda uri, body: next(pages),
            **{
                ("GET", f"{MESSAGES}/m{n:02d}"): _message(f"m{n:02d}", f"subject {n}", "a@b.c", f"body {n}")
                for n in range(11)
            },
        }
    )
    found = search_gmail("label:anything", max_results=11)
    assert [m["id"] for m in found] == [f"m{n:02d}" for n in range(11)]


def test_search_stops_at_max_results():
    pages = iter([{"messages": [{"id": f"m{n:02d}"} for n in range(10)], "nextPageToken": "p2"}])
    _install(
        {
            ("GET", MESSAGES): lambda uri, body: next(pages),
            **{
                ("GET", f"{MESSAGES}/m{n:02d}"): _message(f"m{n:02d}", "s", "a@b.c", "b")
                for n in range(10)
            },
        }
    )
    assert len(search_gmail("anything", max_results=3)) == 3


def test_unpadded_base64_decodes():
    """Gmail commonly omits the ``=`` padding and ``urlsafe_b64decode`` raises
    ``binascii.Error: Incorrect padding`` on it."""
    raw = _message("m1", "Subject", "a@b.c", "x")
    raw["payload"]["body"]["data"] = _b64("Policy number: AB-4471-92X", strip_padding=True)
    _install({("GET", MESSAGES): {"messages": [{"id": "m1"}]}, ("GET", f"{MESSAGES}/m1"): raw})

    (message,) = search_gmail("subject:policy")
    assert "AB-4471-92X" in message["body"]


def test_a_multipart_message_finds_the_plain_part():
    raw = _message("m1", "Subject", "a@b.c", "ignored")
    raw["payload"] = {
        "mimeType": "multipart/alternative",
        "headers": [{"name": "Subject", "value": "Subject"}, {"name": "From", "value": "a@b.c"}],
        "parts": [
            {"mimeType": "text/html", "body": {"data": _b64("<p>html version</p>")}},
            {"mimeType": "text/plain", "body": {"data": _b64("plain version")}},
        ],
    }
    _install({("GET", MESSAGES): {"messages": [{"id": "m1"}]}, ("GET", f"{MESSAGES}/m1"): raw})

    (message,) = search_gmail("anything")
    assert message["body"] == "plain version"


def test_an_html_only_message_still_yields_quotable_text():
    """A reminder that cites nothing is worse than no reminder, so an HTML-only
    message is stripped rather than skipped."""
    raw = _message("m1", "Subject", "a@b.c", "ignored")
    raw["payload"] = {
        "mimeType": "text/html",
        "headers": [{"name": "Subject", "value": "Subject"}],
        "body": {"data": _b64("<html><body><p>Leave must reach your manager</p><p>14 days before</p></body></html>")},
    }
    _install({("GET", MESSAGES): {"messages": [{"id": "m1"}]}, ("GET", f"{MESSAGES}/m1"): raw})

    (message,) = search_gmail("anything")
    assert "Leave must reach your manager" in message["body"]
    assert "<p>" not in message["body"]


def test_a_forwarded_message_does_not_leak_into_the_body():
    """Gmail nests an attached ``.eml`` as a ``message/rfc822`` part carrying its own
    ``text/plain``. Walking into it splices **somebody else's email** into the text
    Second quotes back to the user as evidence.

    The tree is pruned at the attachment rather than the attachment merely being
    skipped: recursing past it while declining to read it reaches the same nested
    parts by another route.
    """
    raw = _message("m1", "Fwd: leave policy", "colleague@example.com", "ignored")
    raw["payload"] = {
        "mimeType": "multipart/mixed",
        "headers": [{"name": "Subject", "value": "Fwd: leave policy"}],
        "parts": [
            {"mimeType": "text/plain", "body": {"data": _b64("See the attached, it explains it.")}},
            {
                "mimeType": "message/rfc822",
                "filename": "forwarded.eml",
                "parts": [
                    {
                        "mimeType": "text/plain",
                        "body": {"data": _b64("CONFIDENTIAL: salary review for another employee")},
                    }
                ],
            },
        ],
    }
    _install({("GET", MESSAGES): {"messages": [{"id": "m1"}]}, ("GET", f"{MESSAGES}/m1"): raw})

    (message,) = search_gmail("anything")
    assert message["body"] == "See the attached, it explains it."
    assert "CONFIDENTIAL" not in message["body"]
    assert "CONFIDENTIAL" not in message["snippet"]


def test_an_attachment_part_is_not_read_as_body():
    """A part carrying ``filename`` is an attachment, not this message's prose."""
    raw = _message("m1", "Invoice", "a@b.c", "ignored")
    raw["payload"] = {
        "mimeType": "multipart/mixed",
        "headers": [{"name": "Subject", "value": "Invoice"}],
        "parts": [
            {"mimeType": "text/plain", "body": {"data": _b64("Invoice attached.")}},
            {"mimeType": "text/plain", "filename": "notes.txt", "body": {"data": _b64("attachment text")}},
        ],
    }
    _install({("GET", MESSAGES): {"messages": [{"id": "m1"}]}, ("GET", f"{MESSAGES}/m1"): raw})

    (message,) = search_gmail("anything")
    assert message["body"] == "Invoice attached."


def test_date_comes_from_internal_date_not_the_header():
    """``internalDate`` is always present and always a valid integer. The ``Date``
    header can be absent, malformed, or carry a ``-0000`` offset that makes
    ``parsedate_to_datetime`` return a naive value a later conversion misplaces."""
    raw = _message("m1", "Subject", "a@b.c", "body", internal_date="1757318400000")
    raw["payload"]["headers"] = [
        {"name": "Subject", "value": "Subject"},
        {"name": "Date", "value": "rubbish, not a date at all -0000"},
    ]
    _install({("GET", MESSAGES): {"messages": [{"id": "m1"}]}, ("GET", f"{MESSAGES}/m1"): raw})

    (message,) = search_gmail("anything")
    assert message["date"].startswith("2025-09-08T"), message["date"]


def test_an_unreadable_internal_date_does_not_lose_the_message():
    raw = _message("m1", "Subject", "a@b.c", "body", internal_date="not a number")
    _install({("GET", MESSAGES): {"messages": [{"id": "m1"}]}, ("GET", f"{MESSAGES}/m1"): raw})

    (message,) = search_gmail("anything")
    assert message["id"] == "m1" and message["date"] == ""


def test_search_rejects_an_empty_query():
    _install({})
    with pytest.raises(GmailError, match="empty query"):
        search_gmail("   ")
    with pytest.raises(GmailError, match="must be positive"):
        search_gmail("subject:policy", max_results=0)


# ---------------------------------------------------------------------------
# Drafting
# ---------------------------------------------------------------------------


def test_draft_email_creates_a_draft_and_says_it_did_not_send():
    transport = _install({("POST", DRAFTS): {"id": "r9182", "message": {"id": "m9182", "labelIds": ["DRAFT"]}}})
    told = draft_email(
        "manager@example.com",
        "Leave request: 25-29 October",
        "Hello,\n\nI would like to request leave for the week of 25 October.\n\nThanks",
    )

    assert "r9182" in told, "the draft id is the one a human can act on, not the message id"
    assert "Not sent" in told

    (_, uri, body) = transport.calls[0]
    assert uri.endswith("/drafts?alt=json"), uri
    sent = json.loads(body)
    assert set(sent) == {"message"} and set(sent["message"]) == {"raw"}


def test_the_draft_body_is_crlf_terminated():
    """``EmailMessage`` without ``policy=SMTP`` emits bare LF, which is the
    documented cause of intermittent ``drafts.create`` 400s and of Gmail rendering
    headers as body text. It works until it does not."""
    decoded = base64.urlsafe_b64decode(rfc822("a@b.c", "Subject", "Line one\nLine two"))
    assert decoded.count(b"\r\n") > 0
    assert decoded.replace(b"\r\n", b"").count(b"\n") == 0, "a bare LF survived"


def test_the_raw_field_is_a_string_not_bytes():
    """``googleapiclient`` calls ``json.dumps`` on the body and does no base64
    handling, so bytes raise ``TypeError: Object of type bytes is not JSON
    serializable`` at the wire rather than at the call site."""
    raw = rfc822("a@b.c", "Subject", "Body")
    assert isinstance(raw, str)
    json.dumps({"message": {"raw": raw}})


def test_the_draft_round_trips_through_a_real_parser():
    """Built with the stdlib, parsed with the stdlib -- so the test is about the
    message rather than about my own encoder agreeing with itself."""
    raw = rfc822("manager@example.com", "Leave request", "Body text here")
    parsed = message_from_bytes(base64.urlsafe_b64decode(raw), policy=SMTP)

    assert parsed["To"] == "manager@example.com"
    assert parsed["Subject"] == "Leave request"
    assert "Body text here" in parsed.get_content()


def test_draft_email_refuses_an_empty_field():
    _install({})
    for args, expect in (
        (("", "Subject", "Body"), "recipient"),
        (("a@b.c", "  ", "Body"), "subject"),
        (("a@b.c", "Subject", ""), "body"),
    ):
        with pytest.raises(GmailError, match=expect):
            draft_email(*args)


def test_nothing_in_this_module_can_send():
    """The rail, asserted at the level the tools actually run at.

    ``gmail.compose`` authorises all three of these. The interlock is the only
    thing that refuses them, so this checks the interlock is in the path the tools
    use -- not a separately constructed one.
    """
    _install({})
    gmail = _google.service("gmail")

    with pytest.raises(GoogleGuardViolation):
        gmail.users().messages().send(userId="me", body={"raw": "x"}).execute()
    with pytest.raises(GoogleGuardViolation):
        gmail.users().drafts().send(userId="me", body={"id": "r9182"}).execute()
    with pytest.raises(GoogleGuardViolation):
        gmail.users().settings().sendAs().verify(userId="me", sendAsEmail="a@b.c").execute()

    assert not hasattr(gmail_tools, "send_email")
    assert {t.tool_name for t in gmail_tools.ALL_GMAIL_TOOLS} == {"search_gmail", "draft_email"}
