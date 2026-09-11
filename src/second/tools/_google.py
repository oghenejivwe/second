"""The one place Google is reached from, and the one place it is fenced in.

Second makes two promises it cannot break:

* **Never send an email.** Drafts only.
* **Never delete a calendar event.**

**There is no scope-level layer behind these. Verified 2026-09-10 against the
discovery documents shipped with ``google-api-python-client`` 2.200.0:**
``gmail.compose`` grants ``users.messages.send`` *and* ``users.drafts.send``;
``drafts.create`` has no narrower scope. ``calendar`` grants ``events.delete``,
and even ``calendar.events.owned`` grants delete, move and import. So the promise
rests entirely on code, and this file is that code.

It sits *below* every tool. A tool nobody reviewed, a library call nobody
anticipated, and an agent that gets creative all arrive here, because
``googleapiclient`` funnels every request through the ``http`` object handed to
:func:`googleapiclient.discovery.build` -- one call, ``http.request(uri,
method=..., body=..., headers=...)``, verified at
``googleapiclient/http.py:191`` and ``:1003``.

An allowlist, not a denylist
----------------------------

The brief specified a denylist of ``DELETE`` and ``*/send``. **I implemented an
allowlist instead, because the denylist is not complete and cannot be made
complete.** Enumerated from the two discovery documents, these routes are
destructive and are *not* ``DELETE`` and do *not* end in ``/send``:

    POST   calendars/{id}/clear                    empties an entire calendar
    POST   calendars/{id}/events/{id}/move         moves an event off the calendar
    POST   calendars/{id}/events/import            writes events wholesale
    POST   calendars/{id}/transferOwnership        gives the calendar away
    PUT    calendars/{id}/events/{id}              blanks every field not supplied
    POST   users/{id}/messages/batchDelete         permanently deletes mail
    POST   users/{id}/messages/{id}/trash          and threads/{id}/trash
    PUT    users/{id}/settings/autoForwarding      silently forwards all future mail
    POST   users/{id}/settings/forwardingAddresses
    POST   users/{id}/settings/delegates           hands the mailbox to someone else
    POST   users/{id}/settings/filters             standing rules
    POST   users/{id}/settings/sendAs              a new send-as identity

Some of those are blocked by scope today. Several are not: ``calendar`` alone
authorises ``clear``, ``move``, ``import``, ``update`` and ``transferOwnership``.
A denylist has to predict every one of them, plus whatever Google ships next
month. **An allowlist fails closed on all of it.** Nine routes are needed to
build this product; everything else raises.

Failure direction: an unrecognised route is **refused**, not passed through. A
refused call is a line in a log and a loud test failure. A permitted one can be
an apology to a colleague or an email that cannot be unsent.

Batch requests are refused outright
-----------------------------------

``googleapiclient.http.BatchHttpRequest`` posts every sub-request inside the body
of a single ``POST https://gmail.googleapis.com/batch`` (``http.py:1577``,
``_batch_uri`` at ``:1303``). **A URL-based guard cannot see inside it**, so
batching would be a tunnel straight through this file. The batch endpoint is
therefore not on the allowlist, and the cost is accepted: ``search_gmail`` makes
N+1 calls instead of 2. Sub-second, and the guarantee stays whole.

Where the guard sits relative to auth
-------------------------------------

Outside ``AuthorizedHttp``, not inside. ``AuthorizedHttp`` builds its own
``Request`` over the *inner* http (``google_auth_httplib2.py:181``) and refreshes
tokens through it, so a guard placed inside would also have to allowlist
``oauth2.googleapis.com/token``. Outside, the guard sees exactly the API calls
``googleapiclient`` composes and nothing else.

Path parameters cannot smuggle a segment
----------------------------------------

Verified by execution: an ``eventId`` of ``abc/../events/xyz/move`` becomes
``events/abc%2F..%2Fevents%2Fxyz%2Fmove``. So a single-segment pattern
(``[^/?]+``) is a real boundary, and every route below is anchored end-to-end.

What this guard does NOT stop, stated plainly
---------------------------------------------

It is an in-process guard, so in-process code can step around it. Four ways, all
verified in ``googleapiclient`` source:

* ``build(..., credentials=creds)`` constructs its **own** ``AuthorizedHttp``
  (``discovery.py:641-644``) and ``http`` and ``credentials`` are mutually
  exclusive (``:545-548``) -- so that one spelling makes this file irrelevant.
* ``HttpRequest.execute(http=other)`` uses ``other`` for that call
  (``http.py:977``). So does ``next_chunk(http=...)`` and
  ``BatchHttpRequest.execute(http=...)``.
* Assigning ``request.http = other`` directly.
* Importing ``googleapiclient`` and calling ``build`` somewhere else entirely.

None of these can be caught at runtime by a transport wrapper, because they all
replace the transport. They are caught instead by
``tests/connectors/test_rails.py``, which reads the source of every file this
instance owns and fails on those shapes, and by
``test_service_is_always_guarded``, which asserts the client this module hands out
has the guard installed.

**Naming this is deliberate.** A guard described as unconditional invites someone
to stop checking, and a claim of two layers where there is one is worse than an
honest one. One layer, well tested, with the bypasses written down.
"""

from __future__ import annotations

import http.client
import json
import logging
import os
import random
import re
import socket
import ssl
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

import httplib2
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from second.settings import GOOGLE_SCOPES

logger = logging.getLogger(__name__)

Api = Literal["calendar", "gmail"]
Role = Literal["runtime", "seeder"]


# ---------------------------------------------------------------------------
# Errors. Every one of these is raised, never returned.
#
# strands' @tool decorator attaches a raised exception to
# AfterToolCallEvent.exception (tools/decorator.py:671); a returned error dict
# passes through with exception=None and strips the audit record of its cause.
# The audit log is the demo's evidence, so the rails raise.
# ---------------------------------------------------------------------------


class GoogleGuardViolation(RuntimeError):
    """A Google call was refused before it left the process.

    Either it would have broken one of Second's promises, or it is a route this
    product has no business making. Both are bugs, and both are loud.
    """


class GoogleCredentialsMissing(RuntimeError):
    """No usable Google credential. Says which file or secret is absent."""


class GoogleAuthExpired(RuntimeError):
    """The refresh token no longer works -- the one failure that looks like a bug.

    A ``400 invalid_grant`` from Google is indistinguishable from a code defect at
    a glance, and it is exactly what a refresh token minted in *Testing* mode does
    after seven days. This error says what to do about it instead.
    """


class GoogleCallFailed(RuntimeError):
    """A Google call failed after retries. Carries the status and Google's reason.

    Never degrades to an empty list. An empty list is indistinguishable from
    "nothing found" and produces a confidently wrong diagnosis downstream.
    """


class FixtureMissing(LookupError):
    """A test asked for a response that was never recorded.

    Raised rather than returning empty, for the same reason as
    :class:`GoogleCallFailed`: a test that silently sees no data passes while
    proving nothing.
    """


# ---------------------------------------------------------------------------
# The allowlist
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Route:
    """One API call this product is allowed to make, and why it is allowed.

    The ``why`` is not decoration. When a judge asks what stops Second sending an
    email, the answer is this table.

    ``body_keys`` constrains the top-level keys of a JSON request body. ``None``
    means unconstrained -- correct for reads, and for bodies this codebase builds
    as literals. It exists because **a permitted verb on a permitted path can
    still be a delete**: ``Event.status`` is writable (it is absent from the
    read-only list in ``calendar.v3.json``) and Google's own wording for it is
    ``"cancelled" - The event is cancelled (deleted)``. So
    ``events.patch(body={"status": "cancelled"})`` is the Calendar API's soft
    delete, arriving as a ``PATCH`` on exactly the route ``reschedule_event``
    needs. A verb-and-path guard waves it through.
    """

    method: str
    pattern: re.Pattern[str]
    why: str
    body_keys: frozenset[str] | None = None

    def matches(self, method: str, path: str) -> bool:
        return method == self.method and self.pattern.fullmatch(path) is not None

    def body_violation(self, body: Any) -> str | None:
        """Say what is wrong with this body, or ``None`` if it is acceptable.

        Failure direction: a body that cannot be parsed as a JSON object, on a
        route that constrains its keys, is **refused**. An opaque body on a
        write route is the case this check exists for.
        """
        if self.body_keys is None:
            return None
        if body is None:
            return None
        raw = body.decode("utf-8", "replace") if isinstance(body, bytes) else body
        if not isinstance(raw, str):
            return f"body is {type(body).__name__}, which cannot be checked against {sorted(self.body_keys)}"
        try:
            parsed = json.loads(raw)
        except ValueError:
            return f"body is not JSON, so its keys cannot be checked against {sorted(self.body_keys)}"
        if not isinstance(parsed, dict):
            return f"body is a JSON {type(parsed).__name__}, not an object"
        extra = sorted(set(parsed) - self.body_keys)
        if extra:
            return f"body sets {extra}; this route may only set {sorted(self.body_keys)}"
        return None


def _route(
    method: str,
    path_regex: str,
    why: str,
    body_keys: frozenset[str] | None = None,
) -> Route:
    return Route(method=method.upper(), pattern=re.compile(path_regex), why=why, body_keys=body_keys)


_CAL = r"/calendar/v3"
_GMAIL = r"/gmail/v1"
_SEG = r"[^/?]+"
"""One URL path segment. Google's client percent-encodes path parameters, so a
value containing a slash cannot widen this."""


RUNTIME_ROUTES: tuple[Route, ...] = (
    _route(
        "GET",
        rf"{_CAL}/calendars/{_SEG}/events",
        "get_calendar_events and find_free_slots read the schedule. showDeleted=true "
        "is required: the dragged task is four events, three cancelled, and the "
        "story is invisible without them.",
    ),
    _route(
        "GET",
        rf"{_CAL}/calendars/{_SEG}/events/{_SEG}",
        "reschedule_event reads the event before it touches it, to establish "
        "ownership and the existing duration.",
    ),
    _route(
        "POST",
        rf"{_CAL}/calendars/{_SEG}/events",
        "create_event. Anchored, so it cannot reach events/import or events/quickAdd.",
    ),
    _route(
        "PATCH",
        rf"{_CAL}/calendars/{_SEG}/events/{_SEG}",
        "reschedule_event moves start and end. PATCH, never PUT: PUT blanks every "
        "field the body omits. The body is held to start and end only, because "
        "status is writable and writing status='cancelled' is Google's own soft "
        "delete on this exact route.",
        body_keys=frozenset({"start", "end"}),
    ),
    _route(
        "GET",
        rf"{_CAL}/users/me/settings/{_SEG}",
        "get_calendar_timezone. Every wall-clock claim Second makes is wrong by an "
        "hour or a day without it, and nothing crashes when it is.",
    ),
    _route(
        "GET",
        rf"{_CAL}/calendars/{_SEG}",
        "the timezone fallback, when the account never set one explicitly.",
    ),
    _route(
        "GET",
        rf"{_GMAIL}/users/{_SEG}/messages",
        "search_gmail lists matching ids. Anchored, so it cannot reach "
        "messages/batchDelete, which shares this path with one more segment.",
    ),
    _route(
        "GET",
        rf"{_GMAIL}/users/{_SEG}/messages/{_SEG}",
        "search_gmail fetches each message. Every reminder must quote the message "
        "it came from, so the body is needed, not just the id.",
    ),
    _route(
        "POST",
        rf"{_GMAIL}/users/{_SEG}/drafts",
        "draft_email. Anchored, so it cannot reach drafts/send -- which the "
        "gmail.compose scope would otherwise permit.",
    ),
)
"""What the shipped runtime may do. Nine routes.

Deliberately absent, all of them authorised by the approved scopes:
``DELETE .../events/{id}``, ``POST .../calendars/{id}/clear``,
``POST .../events/{id}/move``, ``POST .../events/import``,
``POST .../events/quickAdd``, ``PUT .../events/{id}``,
``POST .../messages/send``, ``POST .../drafts/send``,
``DELETE .../drafts/{id}``, and the batch endpoint."""


SEEDER_ROUTES: tuple[Route, ...] = (
    # The runtime's nine, except that the seeder's PATCH may also write status.
    *(route for route in RUNTIME_ROUTES if route.method != "PATCH"),
    _route(
        "PATCH",
        rf"{_CAL}/calendars/{_SEG}/events/{_SEG}",
        "seed_demo.py only: the three cancelled 'Draft the talk pitch' events are "
        "created confirmed and then patched to cancelled, because whether "
        "events.insert accepts status='cancelled' on creation is not documented "
        "anywhere I could verify. The same route is the wipe: a deleted event id is "
        "not reusable (409 duplicate persists against the tombstone), so seed data "
        "is retired by patching status, never by deleting.",
        body_keys=frozenset({"start", "end", "status"}),
    ),
    _route(
        "POST",
        rf"{_GMAIL}/users/{_SEG}/messages",
        "seed_demo.py only: users.messages.insert places the backdated demo mail. "
        "The runtime scopes genuinely cannot do this, which is the point -- the "
        "agent cannot fabricate the evidence it later cites.",
    ),
    _route(
        "POST",
        rf"{_CAL}/calendars/{_SEG}/events/import",
        "seed_demo.py only, and the one route I would rather not have. Event."
        "organizer is 'Read-only, except when importing an event', so import is the "
        "only way to seed the fifteen 'Eng sync' events as someone ELSE's meeting. "
        "Without them every seeded event is owned, reschedule_event never refuses, "
        "and the demo beat that shows Second declining to move a colleague's "
        "meeting has nothing real to stand on. events.import takes no sendUpdates "
        "parameter, so unlike insert it cannot notify anybody.",
    ),
)
"""What the local seeder may do: twelve routes.

Still no send, still no delete, still no ``clear``, ``move`` or ``quickAdd``. The
seeder runs once on a laptop and is never deployed, but it writes to the same real
mailbox and the same real calendar, so it gets the same kind of rails -- just
three more holes in them, each one named and argued above.

The ``status`` asymmetry is the point of splitting the roles at all: the shipped
runtime physically cannot cancel an event, and the thing that can is not deployed.
"""


ROUTES: dict[Role, tuple[Route, ...]] = {"runtime": RUNTIME_ROUTES, "seeder": SEEDER_ROUTES}


# ---------------------------------------------------------------------------
# The guard
# ---------------------------------------------------------------------------


class GuardedHttp:
    """An ``httplib2``-shaped object that refuses anything not on the allowlist.

    Wraps the real transport rather than replacing it, so the guarantee holds for
    every call ``googleapiclient`` composes -- including ones this codebase does
    not contain yet.

    Args:
        inner: The transport to delegate to once a call is permitted. In
            production an ``AuthorizedHttp``; in tests a :class:`RecordedHttp`,
            so the tests drive the real request machinery through the real guard.
        role: Which allowlist applies.
        seen: Optional list that every permitted ``(method, path)`` is appended
            to. Tests assert on it; production leaves it ``None``.
    """

    def __init__(
        self,
        inner: Any,
        role: Role = "runtime",
        seen: list[tuple[str, str]] | None = None,
    ) -> None:
        self.__inner = inner
        self._role = role
        self._routes = ROUTES[role]
        self.seen = seen if seen is not None else []

    # -- the single chokepoint ------------------------------------------

    def request(
        self,
        uri: str,
        method: str = "GET",
        body: Any = None,
        headers: Mapping[str, str] | None = None,
        **kwargs: Any,
    ) -> tuple[httplib2.Response, bytes]:
        """Permit a call, or raise before anything leaves the process.

        The signature matches what ``googleapiclient`` actually calls: ``uri``
        positional, the rest by keyword (``http.py:191``, ``:1003``).

        Raises:
            GoogleGuardViolation: If the route is not on this role's allowlist.
        """
        verb = method.upper()
        path = urlsplit(uri).path

        allowed = next((route for route in self._routes if route.matches(verb, path)), None)
        if allowed is None:
            raise GoogleGuardViolation(self._refusal(verb, path, uri))

        # A permitted verb on a permitted path can still be a delete: writing
        # status='cancelled' through events.patch is Google's own soft delete.
        if (violation := allowed.body_violation(body)) is not None:
            raise GoogleGuardViolation(
                f"refused {verb} {path}\n"
                f"  the route is permitted but the body is not: {violation}\n"
                f"  why this route is constrained: {allowed.why}\n"
                f"  full uri: {uri}"
            )

        self.seen.append((verb, path))
        logger.debug("google %s %s", verb, path)
        return self.__inner.request(uri, method, body=body, headers=headers, **kwargs)

    def _refusal(self, verb: str, path: str, uri: str) -> str:
        """Say what was refused and what is permitted, because a guard that fails
        opaquely gets disabled by the next person who hits it."""
        reason = _why_refused(verb, path)
        permitted = "\n".join(f"    {r.method:6} {r.pattern.pattern}" for r in self._routes)
        return (
            f"refused {verb} {path}\n"
            f"  {reason}\n"
            f"  Second's promises are enforced here and nowhere else: never send an "
            f"email, never delete a calendar event.\n"
            f"  role={self._role!r} permits only:\n{permitted}\n"
            f"  full uri: {uri}"
        )

    # -- the rest of the httplib2 surface -------------------------------

    def close(self) -> None:
        """``Resource.close()`` calls this (``discovery.py:1495``)."""
        closer = getattr(self.__inner, "close", None)
        if closer is not None:
            closer()

    def __getattr__(self, name: str) -> Any:
        """Proxy the incidental httplib2 surface (``timeout``, ``connections``...).

        Refuses to hand out ``request`` or anything private, so holding this
        object is not a route around it. ``request`` is defined above, so Python
        never consults ``__getattr__`` for it; the explicit check is there to stop
        the inner transport being reachable as an unguarded transport. Name
        mangling does the rest: ``guard._inner`` lands here and is refused.
        """
        if name.startswith("_") or name == "request":
            raise AttributeError(name)
        return getattr(self.__inner, name)


def _why_refused(verb: str, path: str) -> str:
    """Name the promise a refused call would have broken, when it is one of them."""
    if verb == "DELETE":
        return "DELETE is never permitted. No code path in Second deletes anything."
    if path.endswith("/send"):
        return (
            "this is a send route. gmail.compose authorises it at the scope level, "
            "so this guard is the only thing that stops it."
        )
    if path.startswith("/batch"):
        # Calendar's batchPath is 'batch/calendar/v3' and Gmail's is 'batch', on
        # two different hosts, so both land under /batch.
        return (
            "batch requests carry their sub-requests in the POST body, where no "
            "URL guard can see them -- a batch body can contain a DELETE and a "
            "send while the wrapper sees one innocuous POST. Refused so there is "
            "no tunnel."
        )
    if path.endswith("/clear") or path.endswith("/batchDelete") or path.endswith("/trash"):
        return "destructive, and not a DELETE -- which is why this is an allowlist."
    if path.endswith("/move") or path.endswith("/import") or path.endswith("/quickAdd"):
        return "writes the calendar in a way no tool in this product needs."
    return "not a route this product makes. An unrecognised route is refused, not passed through."


# ---------------------------------------------------------------------------
# The fixture transport: the same guard, recorded responses
# ---------------------------------------------------------------------------


class RecordedHttp:
    """Serves recorded Google responses. No network, no credentials.

    Sits *inside* a :class:`GuardedHttp` so a test exercises the real
    ``googleapiclient`` request machinery and the real guard, and only the wire is
    fake. A test that mocks the tool instead of the transport proves nothing about
    either.

    Args:
        responses: Keyed by ``(METHOD, path)`` -- path only, no query string.
            Each value is either a JSON-serialisable body, or a
            ``(status, body)`` pair for an error. A callable receives
            ``(uri, body)`` and returns the same, for paging.
    """

    def __init__(self, responses: Mapping[tuple[str, str], Any]) -> None:
        self._responses = dict(responses)
        self.calls: list[tuple[str, str, Any]] = []

    def request(
        self,
        uri: str,
        method: str = "GET",
        body: Any = None,
        headers: Mapping[str, str] | None = None,
        **kwargs: Any,
    ) -> tuple[httplib2.Response, bytes]:
        verb = method.upper()
        path = urlsplit(uri).path
        self.calls.append((verb, uri, body))

        if (verb, path) not in self._responses:
            raise FixtureMissing(
                f"no recorded response for {verb} {path}. "
                f"recorded: {sorted(self._responses)}"
            )

        recorded = self._responses[(verb, path)]
        if callable(recorded):
            recorded = recorded(uri, body)
        status, payload = recorded if isinstance(recorded, tuple) else (200, recorded)

        # httplib2.Response is the real type googleapiclient receives, so the
        # fixture cannot pass by being shaped more conveniently than reality.
        response = httplib2.Response({"status": str(status), "content-type": "application/json"})
        # httplib2.Response defaults .reason to the string "Ok". HttpError reads
        # .reason to build its message, so an error fixture would print "Ok" as its
        # explanation -- and HttpError construction requires the attribute to exist.
        response.reason = "OK" if status < 300 else f"HTTP {status}"
        return response, json.dumps(payload).encode("utf-8")

    def close(self) -> None:  # pragma: no cover - symmetry with the real transport
        pass


# ---------------------------------------------------------------------------
# Credentials. Lazy, always.
# ---------------------------------------------------------------------------

_TOKEN_ENV: dict[Role, tuple[str, str]] = {
    "runtime": ("GOOGLE_TOKEN", "token.json"),
    "seeder": ("GOOGLE_SEED_TOKEN", "token_seed.json"),
}

SECRET_ID_ENV = "SECOND_GOOGLE_SECRET_ID"
"""In a deployed runtime there is no browser and no token file, so the refresh
token comes from Secrets Manager instead. Set this and leave GOOGLE_TOKEN unset."""


def _load_credentials(role: Role) -> Any:
    """Build credentials for a role, or say exactly what is missing.

    **Never called at import time.** ``graphs/composition.py:129-138`` imports
    these tool modules inside a ``try/except ImportError``; a ``FileNotFoundError``
    raised during import would escape that and take the whole composition root
    down at startup. Failure direction: import always succeeds, the first call
    fails loudly.
    """
    from google.oauth2.credentials import Credentials  # noqa: PLC0415 - lazy on purpose

    scopes = list(getattr(GOOGLE_SCOPES, role))
    secret_id = os.environ.get(SECRET_ID_ENV)

    if secret_id and role == "runtime":
        return Credentials.from_authorized_user_info(_secret_payload(secret_id), scopes)

    env_name, default = _TOKEN_ENV[role]
    path = os.environ.get(env_name, default)
    if not os.path.exists(path):
        raise GoogleCredentialsMissing(
            f"no {role} Google token at {path!r} (set ${env_name}, or "
            f"${SECRET_ID_ENV} in a deployed runtime). "
            f"Run: uv run python scripts/authorize_google.py --role {role}"
        )
    return Credentials.from_authorized_user_file(path, scopes)


def _secret_payload(secret_id: str) -> dict[str, Any]:
    """Read the refresh-token JSON out of Secrets Manager."""
    import boto3  # noqa: PLC0415 - lazy, so importing this module needs no AWS

    from second.settings import AWS_REGION
    from second.voice.upload import aws_config

    # botocore defaults to legacy retries (five attempts, uncapped backoff).
    client = boto3.client("secretsmanager", region_name=AWS_REGION, config=aws_config())
    return json.loads(client.get_secret_value(SecretId=secret_id)["SecretString"])


# ---------------------------------------------------------------------------
# Building the client
# ---------------------------------------------------------------------------

_VERSIONS: dict[Api, str] = {"calendar": "v3", "gmail": "v1"}

_cache: dict[tuple[Api, Role], Any] = {}
_overrides: dict[tuple[Api, Role], Any] = {}


def guarded_service(api: Api, inner: Any, role: Role = "runtime") -> Any:
    """Build a Google client whose every call passes through the guard.

    ``static_discovery=True`` uses the discovery document bundled in the wheel, so
    construction needs no network -- which is what lets the guard tests run with
    no credentials at all.
    """
    return build(
        api,
        _VERSIONS[api],
        http=GuardedHttp(inner, role=role),
        static_discovery=True,
        cache_discovery=False,
    )


def service(api: Api, role: Role = "runtime") -> Any:
    """The guarded Google client for an API, built on first use and cached.

    Raises:
        GoogleCredentialsMissing: If no token exists for this role.
    """
    key = (api, role)
    if key in _overrides:
        return _overrides[key]
    if key not in _cache:
        from google_auth_httplib2 import AuthorizedHttp  # noqa: PLC0415 - lazy

        authorized = AuthorizedHttp(_load_credentials(role), http=httplib2.Http(timeout=30))
        _cache[key] = guarded_service(api, authorized, role)
    return _cache[key]


def install_service(api: Api, resource: Any, role: Role = "runtime") -> None:
    """Point :func:`service` at a pre-built client. Tests only."""
    _overrides[(api, role)] = resource


def reset_services() -> None:
    """Drop every cached and overridden client. Tests only."""
    _cache.clear()
    _overrides.clear()


def recorded_service(
    api: Api,
    responses: Mapping[tuple[str, str], Any],
    role: Role = "runtime",
) -> tuple[Any, RecordedHttp]:
    """A fully guarded client backed by fixtures, plus the transport to assert on."""
    transport = RecordedHttp(responses)
    return guarded_service(api, transport, role), transport


# ---------------------------------------------------------------------------
# Calling: retries that fail in the right direction
# ---------------------------------------------------------------------------

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
RETRYABLE_REASONS = frozenset({"rateLimitExceeded", "userRateLimitExceeded", "backendError"})
"""A Google 403 is usually permanent -- except when it carries one of these
reasons, where it means "slow down". Retrying a real permission denial wastes
three attempts and then reports the wrong cause."""

MAX_ATTEMPTS = 3
"""Matches settings.RETRY_MAX_ATTEMPTS. On a live demo, fail fast and say why."""

TRANSIENT_ERRORS: tuple[type[BaseException], ...] = (
    ssl.SSLError,
    socket.timeout,
    ConnectionError,
    http.client.IncompleteRead,
    http.client.BadStatusLine,
    httplib2.ServerNotFoundError,
    httplib2.HttpLib2Error,
)
"""Transport failures worth one more try.

These are precisely the errors ``googleapiclient._retry_request`` handles itself
(``http.py:191-222``) -- and :func:`call` passes ``num_retries=0``, which turns that
off to stop the two retry loops compounding. So they are caught here instead.
Without this, a dropped connection mid-demo raises where the library would have
recovered, which is a regression dressed as a simplification.

``socket.timeout`` is an alias of ``TimeoutError``, itself an ``OSError``, and
``ConnectionError`` covers the reset/abort/refused family -- so a bare ``OSError``
is not listed: a missing file or a permission error has nothing to do with the
network and should not be retried three times before being reported."""


def _error_reason(error: HttpError) -> str:
    """Google buries the machine-readable reason in the error body."""
    try:
        payload = json.loads(error.content.decode("utf-8"))
    except (ValueError, AttributeError, UnicodeDecodeError):
        return ""
    errors = payload.get("error", {})
    if isinstance(errors, str):
        return errors
    details = errors.get("errors") or [{}]
    return str(details[0].get("reason", "")) if isinstance(details, list) else ""


def _is_retryable(error: HttpError) -> bool:
    status = getattr(error.resp, "status", 0)
    if status in RETRYABLE_STATUS:
        return True
    return status == 403 and _error_reason(error) in RETRYABLE_REASONS


def call(
    request: Any,
    what: str,
    *,
    sleep: Callable[[float], None] = time.sleep,
    jitter: Callable[[], float] = random.random,
) -> Any:
    """Execute one Google request, retrying only what is worth retrying.

    Exponential backoff with full jitter, three attempts, then raise. **Never
    returns a falsy value on failure** -- an empty list reaching the
    Diagnostician is indistinguishable from "nothing found", and it would produce
    a confident diagnosis of the wrong thing.

    Args:
        request: An unexecuted ``googleapiclient`` request.
        what: Human description for the error message, e.g. ``"list events"``.
        sleep: Injected so tests do not wait.
        jitter: Injected so tests are deterministic.

    Raises:
        GoogleAuthExpired: The refresh token is dead. Says how to fix it.
        GoogleCallFailed: Anything else, carrying Google's status and reason.
    """
    from google.auth.exceptions import RefreshError  # noqa: PLC0415 - lazy

    last: BaseException | None = None
    attempt = 0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            # num_retries=0 so googleapiclient's own retry loop does not compound
            # with this one: three attempts here times three there is nine attempts
            # and close to a minute of silent waiting on a live demo. The cost is
            # that its TRANSPORT retries go too, which is what TRANSIENT_ERRORS
            # below puts back.
            return request.execute(num_retries=0)
        except RefreshError as error:
            raise GoogleAuthExpired(
                f"Google refused the refresh token while trying to {what}: {error}. "
                "A token minted while the OAuth app was in Testing mode expires after "
                "seven days. Re-run scripts/authorize_google.py; if it keeps happening, "
                "the app is not published."
            ) from error
        except HttpError as error:
            last = error
            if not _is_retryable(error) or attempt == MAX_ATTEMPTS:
                break
            _wait(what, f"HTTP {getattr(error.resp, 'status', '?')}", attempt, sleep, jitter)
        except TRANSIENT_ERRORS as error:
            last = error
            if attempt == MAX_ATTEMPTS:
                break
            _wait(what, type(error).__name__, attempt, sleep, jitter)

    if isinstance(last, HttpError):
        status: object = getattr(last.resp, "status", "?")
        reason = _error_reason(last)
        described = f"Google returned {status}{f' ({reason})' if reason else ''}"
    elif last is not None:
        described = f"the connection failed ({type(last).__name__}: {last})"
    else:  # pragma: no cover - the loop always sets `last` before breaking
        described = "no attempt was made"

    # The real count, not MAX_ATTEMPTS: a 404 reported as "after 3 attempts" sends
    # the next reader looking for a retry storm that never happened.
    raise GoogleCallFailed(
        f"could not {what}: {described} after {attempt} attempt(s)"
    ) from last


def _wait(
    what: str,
    because: str,
    attempt: int,
    sleep: Callable[[float], None],
    jitter: Callable[[], float],
) -> None:
    """Back off with full jitter. Logged, so a slow call is explicable afterwards."""
    delay = jitter() * 2**attempt
    logger.warning(
        "google %s failed with %s; retry %d/%d in %.2fs", what, because, attempt, MAX_ATTEMPTS, delay
    )
    sleep(delay)


def paged(
    collection: Any,
    what: str,
    *,
    key: str,
    limit: int | None = None,
    **params: Any,
) -> Iterator[dict[str, Any]]:
    """Walk every page of a list call.

    A demo inbox with 11 matching emails that returns 10 is the kind of thing that
    shows up on stage, so pagination is implemented rather than assumed away.

    Args:
        collection: e.g. ``service.events()`` or ``service.users().messages()``.
        what: Description for errors.
        key: The response key holding the items (``"items"``, ``"messages"``).
        limit: Stop after this many. ``None`` means every page.
    """
    page_token: str | None = None
    yielded = 0
    while True:
        request = collection.list(**params, **({"pageToken": page_token} if page_token else {}))
        payload = call(request, what)
        for item in payload.get(key) or []:
            yield item
            yielded += 1
            if limit is not None and yielded >= limit:
                return
        page_token = payload.get("nextPageToken")
        if not page_token:
            return
