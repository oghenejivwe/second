"""Small pieces of wording that more than one screen shares.

Kept in one place because the screens sit side by side. When Memory quoted a title with ``!r`` and
Schedule did the same, one line on screen read "double" and the next 'single', depending on whether
the title happened to contain an apostrophe. Python's repr is for developers; these are for people.
"""

from __future__ import annotations

from datetime import date

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
