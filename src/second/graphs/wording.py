"""Small pieces of wording that more than one screen shares.

Kept in one place because the screens sit side by side. When Memory quoted a title with ``!r`` and
Schedule did the same, one line on screen read "double" and the next 'single', depending on whether
the title happened to contain an apostrophe. Python's repr is for developers; these are for people.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from second.core.models import PreparedAction

OPEN_QUOTE = "“"
CLOSE_QUOTE = "”"


def quoted(text: str) -> str:
    """A title or a phrase the user wrote, in fixed typographic quotes.

    Fixed rather than chosen by content, so an apostrophe in "my sister's wedding" cannot change
    which quotes the reader sees.
    """
    return f"{OPEN_QUOTE}{text}{CLOSE_QUOTE}"


def plural(count: int, noun: str) -> str:
    """"1 day", "5 days". A sentence a person reads should not say "5 day(s)"."""
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def day_label(day: date) -> str:
    """"Tue 15 Sep". No ``%-d``, which is glibc-only and this is developed on Windows."""
    return f"{day:%a} {day.day} {day:%b}"


PREPARED_KINDS = {
    "email_draft": "A draft is waiting in Gmail",
    "options": "The options are gathered",
    "retrieved_fact": "Second has looked it up",
    "calendar_change": "A calendar change is ready",
}
"""What each kind of prepared work is, said to a person. ``email_draft`` is the contract's word."""


def what_is_prepared(action: PreparedAction) -> str:
    """"A draft is waiting in Gmail (draft-0001): read it and press send."

    Shared by Today's at-risk line and Memory's folded item, which describe the same draft and sit
    one tab apart.
    """
    reference = f" ({action.external_ref})" if action.external_ref else ""
    step = action.awaiting.strip()
    # Lower-cased to sit after the colon, unless the first word is an acronym or an id ("AB-4471").
    first = step.split(" ", 1)[0]
    if first[:1].isupper() and first[1:] == first[1:].lower():
        step = step[0].lower() + step[1:]
    return f"{PREPARED_KINDS.get(action.kind, 'Prepared')}{reference}: {step}"
