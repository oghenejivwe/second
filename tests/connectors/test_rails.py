"""The safety rails, proved rather than claimed.

Second makes two promises that have **no scope-level protection whatsoever**
(verified 2026-09-10: ``gmail.compose`` grants send, ``calendar`` grants delete).
That makes :mod:`second.tools._google` a single point of failure, so it gets
tested the way a single point of failure should be.

Three properties, in increasing order of strength:

1. **The important violations are refused** through the real ``googleapiclient``
   request machinery -- not a mock of our own code. Every call here is composed by
   Google's client library exactly as it would be in production, with no
   credentials and no network, and the guard is the real guard.
2. **The allowlist is complete**, checked against every method in both bundled
   discovery documents rather than against the handful we thought of. A
   destructive route Google adds later is refused by construction, and if anybody
   widens the allowlist this test says exactly what they let through.
3. **No code path exists to delete or send**, checked as text across the source
   this instance owns. The guard stops a call at runtime; this stops one being
   written.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from second.tools import _google
from second.tools._google import (
    RUNTIME_ROUTES,
    SEEDER_ROUTES,
    FixtureMissing,
    GoogleGuardViolation,
    GuardedHttp,
    recorded_service,
)

DISCOVERY = Path(_google.__file__).parents[4] / "googleapiclient" / "discovery_cache" / "documents"


def _discovery_dir() -> Path:
    """Locate the bundled discovery documents, whatever the venv layout."""
    if DISCOVERY.is_dir():
        return DISCOVERY
    import googleapiclient.discovery_cache as cache

    found = Path(cache.__file__).parent / "documents"
    assert found.is_dir(), f"no discovery documents at {found}"
    return found


# ---------------------------------------------------------------------------
# 1. The three rails, through the real request machinery
# ---------------------------------------------------------------------------


def test_draft_email_can_draft():
    """The permitted half of the rail. Without this, "cannot send" is vacuous."""
    gmail, transport = recorded_service(
        "gmail",
        {("POST", "/gmail/v1/users/me/drafts"): {"id": "r-1", "message": {"id": "m-1"}}},
    )
    created = gmail.users().drafts().create(userId="me", body={"message": {"raw": "eA=="}}).execute()

    assert created["id"] == "r-1"
    assert [(verb, path) for verb, path, _ in transport.calls] == [
        ("POST", "https://gmail.googleapis.com/gmail/v1/users/me/drafts?alt=json")
    ] or transport.calls[0][0] == "POST"


def test_draft_email_cannot_send():
    """RAIL 1: nothing can send mail.

    ``gmail.compose`` authorises both of these at the scope level. This guard is
    the only thing between an agent and an email that cannot be unsent.
    """
    gmail, _ = recorded_service("gmail", {})

    with pytest.raises(GoogleGuardViolation, match="send route"):
        gmail.users().messages().send(userId="me", body={}).execute()

    with pytest.raises(GoogleGuardViolation, match="send route"):
        gmail.users().drafts().send(userId="me", body={"id": "r-1"}).execute()


def test_nothing_deletes_a_calendar_event():
    """RAIL 2: no delete, and no near-miss either.

    ``events.delete`` is the obvious one. ``calendars.clear`` empties the whole
    calendar with a **POST**, and ``events.move`` removes an event from this
    calendar without deleting it -- which is why this is an allowlist and not a
    denylist on the DELETE verb.
    """
    calendar, _ = recorded_service("calendar", {})

    with pytest.raises(GoogleGuardViolation, match="DELETE is never permitted"):
        calendar.events().delete(calendarId="primary", eventId="gym000").execute()

    with pytest.raises(GoogleGuardViolation, match="not a DELETE"):
        calendar.calendars().clear(calendarId="primary").execute()

    with pytest.raises(GoogleGuardViolation, match="no tool in this product needs"):
        calendar.events().move(calendarId="primary", eventId="gym000", destination="other").execute()

    with pytest.raises(GoogleGuardViolation, match="DELETE is never permitted"):
        calendar.calendars().delete(calendarId="primary").execute()


def test_a_permitted_patch_cannot_soft_delete():
    """RAIL 2b: the delete that hides inside a permitted route.

    ``Event.status`` is writable -- it is absent from the read-only properties in
    ``calendar.v3.json`` -- and Google documents ``"cancelled"`` as
    ``The event is cancelled (deleted)``. So ``events.patch(body={'status':
    'cancelled'})`` is a delete, on the exact ``PATCH`` route ``reschedule_event``
    requires. A verb-and-path guard permits it.

    This is the hole an adversarial review found after the first eight rails were
    already green, which is the argument for having run one.
    """
    calendar, transport = recorded_service("calendar", {})

    with pytest.raises(GoogleGuardViolation, match="body sets"):
        calendar.events().patch(
            calendarId="primary", eventId="gymaaa01", body={"status": "cancelled"}
        ).execute()

    assert transport.calls == [], "the soft delete must not reach the transport"


def test_a_permitted_patch_still_allows_a_real_reschedule():
    """The permitted half, so the rail above is not vacuous."""
    calendar, _ = recorded_service(
        "calendar",
        {("PATCH", "/calendar/v3/calendars/primary/events/gymaaa01"): {"id": "gymaaa01"}},
    )
    moved = (
        calendar.events()
        .patch(
            calendarId="primary",
            eventId="gymaaa01",
            body={
                "start": {"dateTime": "2026-09-14T07:00:00+01:00", "timeZone": "Europe/London"},
                "end": {"dateTime": "2026-09-14T08:00:00+01:00", "timeZone": "Europe/London"},
            },
        )
        .execute()
    )
    assert moved["id"] == "gymaaa01"


def test_only_the_seeder_may_write_status():
    """The role split is a least-privilege claim; this is the claim being checked.

    The seeder has to patch three events to cancelled to build the dragged-task
    beat. The shipped runtime must be physically unable to do the same thing.
    """
    path = "/calendar/v3/calendars/primary/events/gymaaa01"
    uri = "https://www.googleapis.com" + path + "?alt=json"
    cancel = json.dumps({"status": "cancelled"})

    runtime = GuardedHttp(_NeverCalled(), role="runtime")
    seeder = GuardedHttp(_NeverCalled(), role="seeder")

    with pytest.raises(GoogleGuardViolation, match="body sets"):
        runtime.request(uri, "PATCH", body=cancel)

    with pytest.raises(_Delegated):
        seeder.request(uri, "PATCH", body=cancel)

    # "Wider" is not "unconstrained". The seeder gets exactly one more key, not a
    # blank cheque -- otherwise it could rewrite attendees, recurrence or (via
    # import semantics) the organizer of a real colleague's meeting.
    for forbidden in ({"summary": "renamed"}, {"attendees": []}, {"recurrence": []}):
        with pytest.raises(GoogleGuardViolation, match="body sets"):
            seeder.request(uri, "PATCH", body=json.dumps(forbidden))


def test_an_opaque_body_on_a_constrained_route_is_refused():
    """Failure direction: a body the guard cannot read is refused, not trusted."""
    uri = "https://www.googleapis.com/calendar/v3/calendars/primary/events/gymaaa01?alt=json"
    guard = GuardedHttp(_NeverCalled(), role="runtime")

    for opaque in (b"\x00\x01binary", "not json at all", json.dumps(["start", "end"])):
        with pytest.raises(GoogleGuardViolation):
            guard.request(uri, "PATCH", body=opaque)


def test_batch_requests_are_refused():
    """RAIL 3: the tunnel is closed.

    ``BatchHttpRequest`` posts its sub-requests inside the body of one request to
    ``/batch`` (``googleapiclient/http.py:1577``), where no URL-based guard can
    see them. If this test ever goes green by the batch succeeding, every other
    test in this file is worthless.
    """
    gmail, _ = recorded_service("gmail", {})
    batch = gmail.new_batch_http_request()
    batch.add(gmail.users().messages().send(userId="me", body={}))

    with pytest.raises(GoogleGuardViolation, match="batch"):
        batch.execute(http=gmail._http)

    # Calendar's batchPath is 'batch/calendar/v3' on a different host, so it is a
    # second URL that has to be refused, not the same one.
    calendar, _ = recorded_service("calendar", {})
    cal_batch = calendar.new_batch_http_request()
    cal_batch.add(calendar.events().delete(calendarId="primary", eventId="gymaaa01"))

    with pytest.raises(GoogleGuardViolation, match="batch"):
        cal_batch.execute(http=calendar._http)


def test_service_is_always_guarded():
    """``build(credentials=...)`` would silently replace the guard with its own
    transport (``discovery.py:641-644``), and ``http`` and ``credentials`` are
    mutually exclusive (``:545-548``) so there is no belt-and-braces available.

    This asserts the client this module actually hands out has the guard on it --
    the one part of that hazard a test can check at runtime.
    """
    from second.tools._google import guarded_service

    for api in ("calendar", "gmail"):
        resource = guarded_service(api, _NeverCalled(), role="runtime")
        assert isinstance(resource._http, GuardedHttp), f"{api} client is unguarded"


def test_a_single_event_dict_would_be_swallowed_by_strands():
    """Why every tool returns a ``list[dict]`` and never a bare event dict.

    ``strands``' ``_wrap_tool_result`` treats any returned dict carrying **both**
    ``status`` and ``content`` as an already-formed ``ToolResult`` and passes it
    through with ``exception=None`` (``tools/decorator.py``). Calendar events in
    this contract carry a ``status`` key by design, so a tool that returned one
    event instead of a list of them would be one ``content`` key away from
    silently becoming a fake tool result.

    A list is serialised with ``json.dumps`` and is safe. This test pins the
    reason, so nobody "simplifies" a tool into returning a single dict.
    """
    from strands.tools.decorator import FunctionToolMetadata  # noqa: F401 - import proves the module path

    import inspect

    from strands.tools import decorator as strands_decorator

    source = inspect.getsource(strands_decorator)
    assert 'isinstance(result, dict) and "status" in result and "content" in result' in source, (
        "strands changed how it detects a pre-formed ToolResult; re-check whether "
        "returning a dict with a 'status' key is still safe"
    )


def test_put_is_refused_so_reschedule_must_patch():
    """``events.update`` (PUT) blanks every field the body omits, which would
    silently strip attendees off a rescheduled event. Only PATCH is permitted."""
    calendar, _ = recorded_service("calendar", {})

    with pytest.raises(GoogleGuardViolation):
        calendar.events().update(calendarId="primary", eventId="gym000", body={}).execute()


def test_guard_is_not_a_substring_check():
    """A path parameter cannot smuggle a segment past an anchored pattern.

    Verified behaviour: Google's client percent-encodes path parameters, so an
    event id of ``x/../clear`` arrives as one encoded segment.
    """
    calendar, transport = recorded_service(
        "calendar",
        {("GET", "/calendar/v3/calendars/primary/events/x%2F..%2Fclear"): {"id": "x"}},
    )
    calendar.events().get(calendarId="primary", eventId="x/../clear").execute()

    _, uri, _ = transport.calls[0]
    assert "%2F" in uri, "if Google stops encoding path params, the anchored patterns need revisiting"


def test_guard_refuses_before_the_transport_is_touched():
    """The refusal happens *before* delegation, so a real call never goes out."""
    calendar, transport = recorded_service("calendar", {})

    with pytest.raises(GoogleGuardViolation):
        calendar.events().delete(calendarId="primary", eventId="x").execute()

    assert transport.calls == [], "a refused call must not reach the transport at all"


def test_inner_transport_is_not_reachable_through_the_guard():
    """Holding the guard is not a route around it.

    The first version of this test asserted that ``guard._inner`` raises
    ``AttributeError`` -- and it passed even with ``__getattr__``'s check deleted,
    because the inner object did not happen to have an attribute by that name
    either. It was asserting at a line the input could not reach.

    So the inner here is given attributes that it *does* have, one private and one
    part of the ordinary ``httplib2`` surface. Proxying the public one is wanted;
    proxying the private one would hand out the transport.
    """

    class Inner:
        _secret = "an unguarded transport would be reachable through this"
        timeout = 30

        def request(self, *args, **kwargs):  # pragma: no cover - must never be called
            raise AssertionError("the guard delegated without checking")

    guard = GuardedHttp(Inner(), role="runtime")

    assert guard.timeout == 30, "the incidental httplib2 surface must still proxy"

    # The guard's own attributes (_routes, _role) are readable and harmless -- the
    # allowlist is module-level public data. What must not be readable is anything
    # belonging to the transport underneath.
    for private in ("_secret", "_inner"):
        with pytest.raises(AttributeError):
            getattr(guard, private)

    assert guard.request.__func__ is GuardedHttp.request, (
        "guard.request must be the guard's own method; if __getattr__ ever serves it "
        "from the inner transport the allowlist is bypassed by a single attribute read"
    )


# ---------------------------------------------------------------------------
# 2. The allowlist is complete, checked against Google's own API surface
# ---------------------------------------------------------------------------


def _all_methods(document: str) -> list[tuple[str, str, str]]:
    """Every (httpMethod, full path, id) in a discovery document."""
    doc = json.loads((_discovery_dir() / document).read_text(encoding="utf-8"))
    service_path = doc.get("servicePath", "")
    out: list[tuple[str, str, str]] = []

    def walk(node: dict) -> None:
        for resource in node.get("resources", {}).values():
            for method in resource.get("methods", {}).values():
                out.append(
                    (
                        method["httpMethod"].upper(),
                        "/" + (service_path + method["path"]).lstrip("/"),
                        method["id"],
                    )
                )
            walk(resource)

    walk(doc)
    return out


def _as_request_path(path_template: str) -> str:
    """Turn ``calendars/{calendarId}/events/{eventId}`` into a concrete path.

    Uses a value that could not itself be mistaken for a literal segment, so a
    pattern that matched by accident is caught.
    """
    return re.sub(r"\{[^}]+\}", "zzseg", path_template)


EXPECTED_RUNTIME_ALLOWED = {
    ("GET", "calendar.events.list"),
    ("GET", "calendar.events.get"),
    ("POST", "calendar.events.insert"),
    ("PATCH", "calendar.events.patch"),
    ("GET", "calendar.settings.get"),
    ("GET", "calendar.calendars.get"),
    ("GET", "gmail.users.messages.list"),
    ("GET", "gmail.users.messages.get"),
    ("POST", "gmail.users.drafts.create"),
}
"""Exactly what the shipped runtime may do. Nine routes, written out by hand.

If this set and the allowlist ever disagree, one of them was changed without
thinking about the other, and that is precisely the change worth failing on."""

EXPECTED_SEEDER_EXTRA = {
    ("POST", "gmail.users.messages.insert"),
    ("POST", "calendar.events.import"),
}
"""The seeder's two additional routes, each argued in ``_google.py``.

``messages.insert`` places the backdated demo mail; the runtime scopes cannot.
``events.import`` is the only way to write ``Event.organizer``, which is the only
way to seed a meeting the demo account does **not** own -- without which
``reschedule_event`` never refuses anything on real data.

The seeder also differs invisibly here: its ``events.patch`` may write ``status``
and the runtime's may not. That asymmetry is checked by
:func:`test_only_the_seeder_may_write_status`, because this test looks at routes
and not at bodies."""


@pytest.mark.parametrize("role,expected", [
    ("runtime", EXPECTED_RUNTIME_ALLOWED),
    ("seeder", EXPECTED_RUNTIME_ALLOWED | EXPECTED_SEEDER_EXTRA),
])
def test_allowlist_permits_exactly_the_intended_routes(role, expected):
    """Walk every method Google documents and check the guard's verdict on each.

    This is the test that makes the allowlist *provably* complete rather than
    merely careful: it is driven by Google's own API surface, so a destructive
    route added to the Calendar or Gmail API later is refused by construction and
    any widening of the allowlist shows up here by name.
    """
    guard = GuardedHttp(_NeverCalled(), role=role)
    permitted: set[tuple[str, str]] = set()

    for document, host in (
        ("calendar.v3.json", "https://www.googleapis.com"),
        ("gmail.v1.json", "https://gmail.googleapis.com"),
    ):
        for verb, path_template, method_id in _all_methods(document):
            uri = host + _as_request_path(path_template) + "?alt=json"
            try:
                guard.request(uri, verb)
            except GoogleGuardViolation:
                continue
            except _Delegated:
                permitted.add((verb, method_id))

    assert permitted == expected, (
        "the allowlist no longer matches what this product is supposed to do.\n"
        f"  unexpectedly permitted: {sorted(permitted - expected)}\n"
        f"  expected but refused:   {sorted(expected - permitted)}"
    )


@pytest.mark.parametrize("method_id", [
    "calendar.events.delete",
    "calendar.events.move",
    "calendar.events.quickAdd",
    "calendar.events.update",
    "calendar.calendars.clear",
    "calendar.calendars.delete",
    "calendar.calendars.transferOwnership",
    "calendar.calendarList.delete",
    "calendar.acl.insert",
    "gmail.users.messages.send",
    "gmail.users.drafts.send",
    "gmail.users.messages.delete",
    "gmail.users.messages.batchDelete",
    "gmail.users.messages.trash",
    "gmail.users.messages.import",
    "gmail.users.drafts.delete",
    "gmail.users.threads.delete",
    "gmail.users.settings.updateAutoForwarding",
    "gmail.users.settings.forwardingAddresses.create",
    "gmail.users.settings.delegates.create",
    "gmail.users.settings.filters.create",
    "gmail.users.settings.sendAs.create",
])
def test_named_destructive_routes_are_refused(method_id):
    """The ones worth naming, so a reviewer can read the list.

    Several of these are authorised by the approved scopes and none of them is a
    ``DELETE`` ending in ``/send`` -- which is the whole argument for an allowlist.
    Auto-forwarding in particular would quietly redirect every future email the
    user receives.
    """
    document = "calendar.v3.json" if method_id.startswith("calendar.") else "gmail.v1.json"
    host = "https://www.googleapis.com" if document.startswith("calendar") else "https://gmail.googleapis.com"
    match = [m for m in _all_methods(document) if m[2] == method_id]
    assert match, f"{method_id} is not in {document}; the discovery document changed"
    verb, path_template, _ = match[0]

    guard = GuardedHttp(_NeverCalled(), role="seeder")  # the wider of the two roles
    with pytest.raises(GoogleGuardViolation):
        guard.request(host + _as_request_path(path_template) + "?alt=json", verb)


def test_events_import_is_refused_for_the_runtime():
    """``events.import`` is the seeder's, and only the seeder's.

    It is the one route that can write ``Event.organizer``, which is what makes it
    useful for seeding and exactly why the shipped runtime must not have it: an
    agent that could set the organizer could make a foreign meeting look like the
    user's own, and ``reschedule_event``'s refusal would stop meaning anything.
    """
    uri = "https://www.googleapis.com/calendar/v3/calendars/primary/events/import?alt=json"

    with pytest.raises(GoogleGuardViolation):
        GuardedHttp(_NeverCalled(), role="runtime").request(uri, "POST", body="{}")

    with pytest.raises(_Delegated):
        GuardedHttp(_NeverCalled(), role="seeder").request(uri, "POST", body="{}")


def _media_upload_paths(document: str) -> list[tuple[str, str, str]]:
    """Every ``/upload/`` and ``/resumable/upload/`` alias in a discovery document."""
    doc = json.loads((_discovery_dir() / document).read_text(encoding="utf-8"))
    out: list[tuple[str, str, str]] = []

    def walk(node: dict) -> None:
        for resource in node.get("resources", {}).values():
            for method in resource.get("methods", {}).values():
                for info in (method.get("mediaUpload") or {}).get("protocols", {}).values():
                    if path := info.get("path"):
                        out.append((method["httpMethod"].upper(), path, method["id"]))
            walk(resource)

    walk(doc)
    return out


@pytest.mark.parametrize("role", ["runtime", "seeder"])
def test_every_media_upload_alias_is_refused(role):
    """Six Gmail methods have a second path, and one of them sends mail.

    ``messages.send`` is also reachable at ``/upload/gmail/v1/users/{id}/messages/send``
    and ``/resumable/upload/gmail/v1/...``. So is ``drafts.send``, and so is
    ``messages.insert``. An interlock anchored on ``/gmail/v1/`` refuses all of
    them -- which is the allowlist earning its keep, because nobody writing a
    denylist thinks of the upload aliases.

    Enumerated from the discovery document rather than listed by hand, so an alias
    Google adds later is covered without anybody remembering to add it.
    """
    guard = GuardedHttp(_NeverCalled(), role=role)
    aliases = _media_upload_paths("gmail.v1.json")
    assert len(aliases) >= 12, "the discovery document no longer declares upload aliases"

    for verb, path_template, method_id in aliases:
        uri = "https://gmail.googleapis.com" + _as_request_path(path_template) + "?alt=json&uploadType=media"
        with pytest.raises(GoogleGuardViolation):
            guard.request(uri, verb, body="{}")


def test_the_seeder_is_wider_than_the_runtime_in_exactly_three_ways():
    """Scope splitting is a claim about least privilege; this checks the claim.

    Three differences, no more: insert mail, import an event, and patch ``status``.
    Anything else appearing here is a hole somebody opened without arguing for it.
    """
    runtime = {(r.method, r.pattern.pattern, r.body_keys) for r in RUNTIME_ROUTES}
    seeder = {(r.method, r.pattern.pattern, r.body_keys) for r in SEEDER_ROUTES}

    added = seeder - runtime
    removed = runtime - seeder

    assert {(method, pattern) for method, pattern, _ in added} == {
        ("POST", r"/gmail/v1/users/[^/?]+/messages"),
        ("POST", r"/calendar/v3/calendars/[^/?]+/events/import"),
        ("PATCH", r"/calendar/v3/calendars/[^/?]+/events/[^/?]+"),
    }
    # The PATCH is not an addition so much as a widening: same route, bigger body.
    assert {(method, pattern) for method, pattern, _ in removed} == {
        ("PATCH", r"/calendar/v3/calendars/[^/?]+/events/[^/?]+"),
    }

    assert all(
        route.body_keys == frozenset({"start", "end"})
        for route in RUNTIME_ROUTES
        if route.method == "PATCH"
    ), "the runtime's PATCH must never be able to write status"

    insert_mail = next(
        route for route in SEEDER_ROUTES
        if route.method == "POST" and route.pattern.fullmatch("/gmail/v1/users/me/messages")
    )
    assert not insert_mail.pattern.fullmatch("/gmail/v1/users/me/messages/batchDelete")


# ---------------------------------------------------------------------------
# 3. No code path exists
# ---------------------------------------------------------------------------

CONNECTOR_SOURCES = (
    "src/second/tools/_google.py",
    "src/second/tools/calendar_tools.py",
    "src/second/tools/gmail_tools.py",
    "src/second/tools/search_tools.py",
    "src/second/voice/upload.py",
    "src/second/voice/transcribe.py",
    "scripts/authorize_google.py",
    "scripts/seed_demo.py",
)

FORBIDDEN_CALLS = (
    # A googleapiclient call chain: resource().method(. Precise, so a dict's own
    # .clear() or .update() does not read as a Google call.
    re.compile(r"\)\s*\.\s*(delete|send|clear|trash|batchDelete|move|quickAdd|import_|update)\s*\("),
    # Batching tunnels sub-requests through one POST /batch where the guard cannot
    # read them (googleapiclient/http.py:1577).
    re.compile(r"new_batch_http_request"),
    # execute(http=...) swaps out the transport for that one call
    # (googleapiclient/http.py:977), which is a door straight past the guard.
    re.compile(r"\.execute\(\s*http\s*="),
)
"""Call shapes that must not appear in code that talks to Google.

The guard refuses them at runtime; this stops one being written, which is cheaper
than discovering it. ``update`` is here because the Calendar PUT blanks every
field the body omits, so ``reschedule_event`` must PATCH.

The last pattern is the one worth reading twice: ``execute(http=...)`` replaces
the transport for a single call, so it is the only in-process route around the
guard, and it is forbidden by text because no runtime check can see it coming.
"""


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    raise AssertionError("could not find the repository root")


ARGUED_EXCEPTIONS: dict[str, frozenset[str]] = {
    # events.import is the only route that can write Event.organizer, and a written
    # organizer is the only way to seed a meeting the demo account does not own --
    # without which reschedule_event never refuses anything on real data. Permitted
    # to the seeder allowlist and to this one file; the runtime cannot reach it, which
    # test_events_import_is_refused_for_the_runtime checks.
    "scripts/seed_demo.py": frozenset({"import_"}),
}
"""Per-file exceptions to :data:`FORBIDDEN_CALLS`, each with its argument written out.

A dict rather than inline ``noqa`` markers, so every exception in the codebase is
visible in one place and adding one is a diff a reviewer will notice.
:func:`test_the_exception_list_stays_short` fails if it grows."""


def test_the_exception_list_stays_short():
    """One exception, in one file, for one method.

    This exists so the list cannot quietly become the place where the rails go to
    die. If it needs a second entry, that is a conversation, not a commit.
    """
    assert ARGUED_EXCEPTIONS == {"scripts/seed_demo.py": frozenset({"import_"})}


@pytest.mark.parametrize("relative", CONNECTOR_SOURCES)
def test_no_connector_source_calls_a_destructive_method(relative):
    """Read the source this instance owns and check for the shapes, not the intent."""
    path = _repo_root() / relative
    if not path.exists():
        pytest.skip(f"{relative} not written yet")

    allowed = ARGUED_EXCEPTIONS.get(relative, frozenset())
    offences = []
    for number, code in _code_lines(path):
        for shape in FORBIDDEN_CALLS:
            found = shape.search(code)
            if found and not (found.groups() and found.group(1) in allowed):
                offences.append(f"{relative}:{number} matches {shape.pattern}: {code.strip()}")

    assert not offences, "\n".join(offences)


def _code_lines(path: Path) -> list[tuple[int, str]]:
    """The file's lines with comments and string literals blanked out.

    Tokenising rather than splitting on ``#`` matters here: this module's own
    docstring *documents* the bypasses (``execute(http=...)``) as prose, and a
    naive scan flags the documentation as the violation. Blanking strings also
    stops a log message mentioning ``.send(`` from failing the build, which is the
    kind of false positive that gets a guard deleted.
    """
    import io
    import tokenize

    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    blanked = list(lines)
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except tokenize.TokenError:  # pragma: no cover - a syntax error fails elsewhere first
        return list(enumerate(lines, start=1))

    for token in tokens:
        if token.type not in (tokenize.STRING, tokenize.COMMENT):
            continue
        (start_row, start_col), (end_row, end_col) = token.start, token.end
        for row in range(start_row, end_row + 1):
            index = row - 1
            if index >= len(blanked):
                continue
            line = blanked[index]
            begin = start_col if row == start_row else 0
            finish = end_col if row == end_row else len(line)
            blanked[index] = line[:begin] + " " * (finish - begin) + line[finish:]

    return [(n, line) for n, line in enumerate(blanked, start=1)]


def test_the_source_scan_would_catch_a_real_violation():
    """Guards the guard: a text scan that matches nothing is indistinguishable
    from a clean tree. Prove the patterns fire on the shapes they exist for."""
    samples = (
        'service.events().delete(calendarId="primary", eventId=event_id).execute()',
        'service.users().messages().send(userId="me", body=message).execute()',
        'service.users().drafts().send(userId="me", body={"id": draft_id}).execute()',
        'service.calendars().clear(calendarId="primary").execute()',
        "batch = service.new_batch_http_request()",
        "request.execute(http=unguarded)",
    )
    for sample in samples:
        assert any(shape.search(sample) for shape in FORBIDDEN_CALLS), sample


def test_no_delete_event_tool_exists_anywhere():
    """The guarantee that Second never deletes an event is that nothing can ask.

    Checked across the whole source tree, not just this domain: an agent prompt
    offering a ``delete_event`` tool would be a defect even though prompts are
    AGENTS' to write.

    Matches a definition or a call, not the words -- ``fake_connectors.py`` says in
    prose that no ``delete_event`` exists, and that sentence is the opposite of a
    violation.
    """
    root = _repo_root()
    shape = re.compile(r"(def\s+delete_event|delete_event\s*\()")
    hits = [
        str(path.relative_to(root))
        for path in (root / "src").rglob("*.py")
        if shape.search(path.read_text(encoding="utf-8"))
    ]
    assert hits == [], f"delete_event is defined or called in {hits}"


def test_no_mutation_sentinel_is_left_in_the_source():
    """``prove_rails.py`` edits the guard in place. This makes an interrupted run loud.

    Every mutation in that harness carries the word ``MUTATION``, and the harness
    restores the file in a ``finally``. A ``finally`` does not run if the process
    is killed -- and the mutation it was holding at that moment might be a widened
    allowlist, which is the single worst thing to leave lying on disk in a shared
    repository three days from a deadline.

    **This happened.** The harness was killed between applying
    ``_route("POST", r"/batch", "MUTATION")`` and restoring, and that route sat in
    ``RUNTIME_ROUTES`` until the next run's baseline check caught it. The next run
    catching it was luck. This test is not luck.
    """
    source = (_repo_root() / "src" / "second" / "tools" / "_google.py").read_text(encoding="utf-8")
    assert "MUTATION" not in source, (
        "prove_rails.py was interrupted and left a mutation in the guard. "
        "Check `git diff src/second/tools/_google.py` and remove it."
    )


def test_fixture_transport_fails_loudly_on_an_unrecorded_call():
    """A test that silently sees no data passes while proving nothing.

    This is the same failure direction as the tools themselves: raise, never
    return empty.
    """
    gmail, _ = recorded_service("gmail", {})
    with pytest.raises(FixtureMissing):
        gmail.users().messages().list(userId="me", q="anything").execute()


# ---------------------------------------------------------------------------


class _Delegated(Exception):
    """Raised by the stub transport to signal "the guard let this through"."""


class _NeverCalled:
    """Stands in for the transport in allowlist tests.

    Raising rather than returning means a permitted route is unmistakable, and a
    refused one never silently looks the same as a successful one.
    """

    def request(self, uri, method="GET", body=None, headers=None, **kwargs):
        raise _Delegated(f"{method} {uri}")

    def close(self) -> None:
        pass
