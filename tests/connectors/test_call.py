"""``_google.call`` and ``_google.paged``: what gets retried, and what does not.

Retrying the wrong thing is slow; retrying nothing loses a demo to one dropped
packet; and degrading to an empty result on failure is the defect this whole domain
is written against, because "nothing found" and "could not look" then become the
same answer.
"""

from __future__ import annotations

import http.client
import socket
import ssl

import httplib2
import pytest
from googleapiclient.errors import HttpError

from second.tools._google import (
    MAX_ATTEMPTS,
    GoogleAuthExpired,
    GoogleCallFailed,
    call,
    paged,
)


def _http_error(status: int, reason_code: str = "") -> HttpError:
    """An HttpError shaped the way googleapiclient builds one."""
    response = httplib2.Response({"status": str(status), "content-type": "application/json"})
    response.reason = f"HTTP {status}"
    body = b'{"error": {"errors": [{"reason": "%s"}], "message": "x"}}' % reason_code.encode()
    return HttpError(response, body, uri="https://example.com/x")


class Request:
    """An unexecuted request that raises a scripted sequence of failures."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.attempts = 0

    def execute(self, num_retries=0):
        self.attempts += 1
        assert num_retries == 0, (
            "call() must pass num_retries=0; googleapiclient's own retry loop would "
            "otherwise compound with this one into nine attempts"
        )
        outcome = self.outcomes[min(self.attempts - 1, len(self.outcomes) - 1)]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _call(request, **kwargs):
    return call(request, "do the thing", sleep=lambda _: None, jitter=lambda: 0.5, **kwargs)


# ---------------------------------------------------------------------------


def test_a_successful_call_does_not_retry():
    request = Request({"ok": True})
    assert _call(request) == {"ok": True}
    assert request.attempts == 1


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_transient_statuses_are_retried(status):
    request = Request(_http_error(status), _http_error(status), {"ok": True})
    assert _call(request) == {"ok": True}
    assert request.attempts == 3


@pytest.mark.parametrize("reason", ["rateLimitExceeded", "userRateLimitExceeded", "backendError"])
def test_a_throttling_403_is_retried(reason):
    """A Google 403 is usually permanent -- except when it carries one of these
    reasons, where it means "slow down". The reason lives in the body, not in
    ``HttpError.reason``, which is the human message."""
    request = Request(_http_error(403, reason), {"ok": True})
    assert _call(request) == {"ok": True}
    assert request.attempts == 2


@pytest.mark.parametrize("status,reason", [(403, "insufficientPermissions"), (400, ""), (404, ""), (401, "")])
def test_permanent_failures_are_not_retried(status, reason):
    """Retrying a real permission denial spends three attempts and then reports the
    wrong cause."""
    request = Request(_http_error(status, reason))
    with pytest.raises(GoogleCallFailed) as raised:
        _call(request)

    assert request.attempts == 1
    assert str(status) in str(raised.value)


@pytest.mark.parametrize(
    "error",
    [
        ssl.SSLError("handshake"),
        socket.timeout("timed out"),
        ConnectionResetError("reset by peer"),
        http.client.IncompleteRead(b"half"),
        http.client.BadStatusLine("garbage"),
        httplib2.ServerNotFoundError("dns"),
    ],
)
def test_transport_failures_are_retried(error):
    """``num_retries=0`` switches off googleapiclient's own transport retries
    (``http.py:191-222``), so they have to be handled here.

    Without this, a dropped connection mid-demo raises where the library would have
    recovered -- a regression dressed as a simplification.
    """
    request = Request(error, {"ok": True})
    assert _call(request) == {"ok": True}
    assert request.attempts == 2


def test_a_transport_failure_that_never_clears_reports_the_cause():
    request = Request(ConnectionResetError("reset by peer"))
    with pytest.raises(GoogleCallFailed, match="connection failed"):
        _call(request)
    assert request.attempts == MAX_ATTEMPTS


def test_a_non_network_oserror_is_not_retried():
    """``OSError`` is deliberately not in the transient set. A missing file or a
    permission error has nothing to do with the network, and retrying it three times
    only delays the real message."""
    request = Request(PermissionError("no"))
    with pytest.raises(PermissionError):
        _call(request)
    assert request.attempts == 1


def test_a_dead_refresh_token_says_what_to_do_about_it():
    """``400 invalid_grant`` is indistinguishable from a code defect at a glance, and
    it is exactly what a token minted in Testing mode does after seven days."""
    from google.auth.exceptions import RefreshError

    request = Request(RefreshError("invalid_grant: Token has been expired or revoked."))
    with pytest.raises(GoogleAuthExpired, match="authorize_google.py"):
        _call(request)
    assert request.attempts == 1, "a dead refresh token will not recover on a retry"


def test_backoff_doubles_and_is_logged():
    waited = []
    request = Request(_http_error(503))
    with pytest.raises(GoogleCallFailed):
        call(request, "do the thing", sleep=waited.append, jitter=lambda: 0.5)

    assert waited == [1.0, 2.0], "two sleeps for three attempts; the last failure does not wait"


def test_a_failure_never_returns_a_falsy_value():
    """The whole point. An empty list reaching the Diagnostician is
    indistinguishable from "nothing found" and produces a confident diagnosis of the
    wrong thing."""
    with pytest.raises(GoogleCallFailed):
        _call(Request(_http_error(500)))


# ---------------------------------------------------------------------------
# paged
# ---------------------------------------------------------------------------


class Collection:
    """A list endpoint returning scripted pages."""

    def __init__(self, *pages):
        self.pages = list(pages)
        self.tokens_seen: list[str | None] = []

    def list(self, **params):
        self.tokens_seen.append(params.get("pageToken"))
        page = self.pages[len(self.tokens_seen) - 1]
        return Request(page)


def test_paging_follows_the_token_through_a_short_page():
    """A short page is not the end. Google documents that a page "may be less than
    this value, or none at all, even if there are more events matching the query"."""
    collection = Collection(
        {"items": [1, 2], "nextPageToken": "p2"},
        {"items": [], "nextPageToken": "p3"},
        {"items": [3, 4, 5]},
    )
    assert list(paged(collection, "list things", key="items")) == [1, 2, 3, 4, 5]
    assert collection.tokens_seen == [None, "p2", "p3"]


def test_paging_stops_at_the_limit_without_fetching_more():
    collection = Collection({"items": [1, 2, 3], "nextPageToken": "p2"}, {"items": [4, 5]})
    assert list(paged(collection, "list things", key="items", limit=2)) == [1, 2]
    assert collection.tokens_seen == [None], "the limit was reached inside the first page"


def test_paging_crosses_pages_to_reach_the_limit():
    """The eleventh match of eleven. A demo inbox that returns ten is the kind of
    thing that shows up on stage."""
    collection = Collection(
        {"items": list(range(5)), "nextPageToken": "p2"},
        {"items": list(range(5, 11))},
    )
    assert list(paged(collection, "list things", key="items", limit=11)) == list(range(11))


def test_a_missing_items_key_is_not_an_error():
    """Gmail omits the ``messages`` key entirely on zero hits -- the body is
    ``{"resultSizeEstimate": 0}``, not an empty list. Indexing it raises KeyError."""
    collection = Collection({"resultSizeEstimate": 0})
    assert list(paged(collection, "list things", key="messages")) == []
