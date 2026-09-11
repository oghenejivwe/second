"""Watch every safety rail fail, then pass. Run it; do not take my word for it.

    uv run python tests/connectors/prove_rails.py

A green suite is not evidence. A test can pass while proving nothing -- by
mocking the primitive that would have failed, by hand-building an object the
framework never constructs, or by asserting at a line the input cannot reach.
The only way to know a guard works is to break it and watch the test notice.

This script does that mechanically: for each rail it edits the source file the rail
lives in, runs the one test that should now fail, checks
that it **did** fail, and restores the file. Every mutation is a plausible change
someone might actually make -- a route added to the allowlist "just for now", an
anchor dropped, a check moved one line down.

It is committed so the reviewer can re-run it, and so the claim in the commit
message is checkable rather than rhetorical.
"""

from __future__ import annotations

import atexit
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUARD = "src/second/tools/_google.py"
GMAIL = "src/second/tools/gmail_tools.py"
CALENDAR = "src/second/tools/calendar_tools.py"
SUITES = "tests/connectors"


@dataclass(frozen=True)
class Mutation:
    """One way to break a rail, and the test that must notice.

    ``target`` is repo-relative: the rails stopped living in one file once the tools
    landed, and a harness that can only mutate the interlock would silently stop
    covering the ones that moved.
    """

    rail: str
    test: str
    find: str
    replace: str
    why: str
    target: str = GUARD
    suite: str = "tests/connectors/test_rails.py"


MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        rail="never send an email",
        test="test_draft_email_cannot_send",
        find='RUNTIME_ROUTES: tuple[Route, ...] = (\n',
        replace=(
            'RUNTIME_ROUTES: tuple[Route, ...] = (\n'
            '    _route("POST", rf"{_GMAIL}/users/{_SEG}/messages/send", "MUTATION"),\n'
            '    _route("POST", rf"{_GMAIL}/users/{_SEG}/drafts/send", "MUTATION"),\n'
        ),
        why="the exact change a hurried person makes when a send 'would be convenient'",
    ),
    Mutation(
        rail="never delete a calendar event",
        test="test_nothing_deletes_a_calendar_event",
        find='RUNTIME_ROUTES: tuple[Route, ...] = (\n',
        replace=(
            'RUNTIME_ROUTES: tuple[Route, ...] = (\n'
            '    _route("DELETE", rf"{_CAL}/calendars/{_SEG}/events/{_SEG}", "MUTATION"),\n'
        ),
        why="a delete_event tool would need exactly this line, and only this line",
    ),
    Mutation(
        rail="the batch tunnel stays closed",
        test="test_batch_requests_are_refused",
        find='RUNTIME_ROUTES: tuple[Route, ...] = (\n',
        replace=(
            'RUNTIME_ROUTES: tuple[Route, ...] = (\n'
            '    _route("POST", r"/batch", "MUTATION"),\n'
        ),
        why="batching looks like a harmless performance win and defeats every URL rule",
    ),
    Mutation(
        rail="a permitted PATCH cannot soft-delete via status",
        test="test_a_permitted_patch_cannot_soft_delete",
        find='        body_keys=frozenset({"start", "end"}),\n',
        replace="",
        why=(
            "dropping the body constraint leaves the verb and path permitted, and "
            "events.patch(status='cancelled') is Google's own delete on that route"
        ),
    ),
    Mutation(
        rail="the body check runs at all",
        test="test_a_permitted_patch_cannot_soft_delete",
        find="        if (violation := allowed.body_violation(body)) is not None:",
        replace="        if False:",
        why="a check that is never reached is the most convincing kind of decoration",
    ),
    Mutation(
        rail="an unreadable body is refused, not trusted",
        test="test_an_opaque_body_on_a_constrained_route_is_refused",
        find='            return f"body is not JSON, so its keys cannot be checked against {sorted(self.body_keys)}"',
        replace="            return None",
        why="failing open on a body you cannot parse is the same mistake as failing open on a route",
    ),
    Mutation(
        rail="only the seeder may write status",
        test="test_only_the_seeder_may_write_status",
        find='        body_keys=frozenset({"start", "end", "status"}),',
        replace="        body_keys=None,",
        why=(
            "body_keys=None on the seeder's PATCH reads like a harmless relaxation "
            "and quietly removes the only check on what the seeder writes"
        ),
    ),
    Mutation(
        rail="events.import stays out of the runtime",
        test="test_events_import_is_refused_for_the_runtime",
        find='RUNTIME_ROUTES: tuple[Route, ...] = (\n',
        replace=(
            'RUNTIME_ROUTES: tuple[Route, ...] = (\n'
            '    _route("POST", rf"{_CAL}/calendars/{_SEG}/events/import", "MUTATION"),\n'
        ),
        why="import is the only route that can write Event.organizer, which would make reschedule_event's refusal meaningless",
    ),
    Mutation(
        rail="an unknown route is refused, not passed through",
        test="test_allowlist_permits_exactly_the_intended_routes",
        find="        if allowed is None:\n            raise GoogleGuardViolation(self._refusal(verb, path, uri))",
        replace="        if allowed is None:\n            logger.warning('unrecognised route %s %s', verb, path)",
        why="failing open with a log line is the single most common way a guard dies",
    ),
    Mutation(
        rail="patterns are anchored end to end",
        test="test_allowlist_permits_exactly_the_intended_routes",
        find="        return method == self.method and self.pattern.fullmatch(path) is not None",
        replace="        return method == self.method and self.pattern.match(path) is not None",
        why=(
            "match() instead of fullmatch() turns the drafts route into a prefix, "
            "so POST /drafts/send is permitted by the rule that allows drafts.create"
        ),
    ),
    Mutation(
        rail="the refusal happens before the transport is touched",
        test="test_guard_refuses_before_the_transport_is_touched",
        find="        allowed = next((route for route in self._routes if route.matches(verb, path)), None)",
        replace=(
            "        self.__inner.request(uri, method, body=body, headers=headers, **kwargs)\n"
            "        allowed = next((route for route in self._routes if route.matches(verb, path)), None)"
        ),
        why="a check after the call is decoration; the damage is already done",
    ),
    Mutation(
        rail="the inner transport is not reachable through the guard",
        test="test_inner_transport_is_not_reachable_through_the_guard",
        find='        if name.startswith("_") or name == "request":\n            raise AttributeError(name)',
        replace="        pass",
        why="a permissive __getattr__ hands out an unguarded transport to anyone holding the guard",
    ),
    # --- rails that live in the tools, not in the interlock -----------------
    Mutation(
        rail="a forwarded message does not leak into quoted evidence",
        target=GMAIL,
        suite="tests/connectors/test_gmail.py",
        test="test_a_forwarded_message_does_not_leak_into_the_body",
        find='        if node.get("filename") or (node.get("mimeType") or "").lower() in ENCLOSED_MESSAGE_TYPES:\n            return\n',
        replace="",
        why=(
            "walking into a message/rfc822 part splices somebody else's email into "
            "the text Second quotes back to the user as evidence -- MUTATION"
        ),
    ),
    Mutation(
        rail="reschedule refuses an event the user does not organise",
        target=CALENDAR,
        suite="tests/connectors/test_calendar.py",
        test="test_reschedule_refuses_someone_elses_meeting",
        find='    organised = bool((event.get("organizer") or {}).get("self"))\n    return organised and not event.get("locked")',
        replace='    return True  # MUTATION',
        why="one permissive default here is an apology to eight colleagues",
    ),
    Mutation(
        rail="reschedule refuses a locked copy",
        target=CALENDAR,
        suite="tests/connectors/test_calendar.py",
        test="test_reschedule_refuses_a_locked_copy",
        find='    return organised and not event.get("locked")',
        replace="    return organised  # MUTATION",
        why=(
            "a locked copy has organizer.self true and still refuses start/end "
            "changes, so without this the refusal happens at Google and lands "
            "outside the audit trail"
        ),
    ),
    Mutation(
        rail="a declined event does not hold its time",
        target=CALENDAR,
        suite="tests/connectors/test_calendar.py",
        test="test_a_declined_block_does_not_hold_its_time",
        find='    if event["status"] == "cancelled" or event["response"] == "declined":\n        return False\n    if raw.get("transparency") == "transparent":',
        replace='    if event["status"] == "cancelled":  # MUTATION\n        return False\n    if raw.get("transparency") == "transparent":',
        why=(
            "if a declined gym block counts as busy, 18:00 looks contended by the gym "
            "rather than by the Eng sync that took it, and the diagnosis names the "
            "wrong cause"
        ),
    ),
    Mutation(
        rail="an unknown eventType still holds its time",
        target=CALENDAR,
        suite="tests/connectors/test_calendar.py",
        test="test_an_unknown_event_type_still_holds_its_time",
        find='    if raw.get("eventType", "default") in FREE_EVENT_TYPES:\n        return False',
        replace='    if raw.get("eventType", "default") not in ("default", "focusTime"):  # MUTATION\n        return False',
        why=(
            "an inclusion list instead of an exclusion list books the user over their "
            "own flight, because fromGmail events are the bookings Google creates "
            "from confirmation emails"
        ),
    ),
    Mutation(
        rail="an empty transcript raises rather than reading as success",
        target="src/second/voice/transcribe.py",
        suite="tests/connectors/test_voice.py",
        test="test_an_empty_transcript_raises",
        find="    text = _read_transcript(job, job_id)\n    if not text.strip():",
        replace="    text = _read_transcript(job, job_id)\n    if False:  # MUTATION",
        why=(
            "a silent recording transcribes successfully to '', and returning it hands "
            "an agent a valid-looking success to plan against"
        ),
    ),
    Mutation(
        rail="a presigned URL that signs content-type is refused",
        target="src/second/voice/upload.py",
        suite="tests/connectors/test_voice.py",
        test="test_a_url_that_would_fail_in_a_browser_is_refused",
        find='    if "content-type" in signed:',
        replace="    if False:  # MUTATION",
        why=(
            "MediaRecorder sends audio/webm;codecs=opus, so a signed content-type is "
            "a SignatureDoesNotMatch 403 that reads as CORS and eats an evening"
        ),
    ),
    Mutation(
        rail="a failed web search does not degrade to an empty list",
        target="src/second/tools/search_tools.py",
        suite="tests/connectors/test_search.py",
        test="test_a_failure_never_degrades_to_an_empty_list",
        find='    raise SearchError(f"could not search the web after {MAX_ATTEMPTS} attempt(s). Last: {last}")',
        replace='    return {"results": []}  # MUTATION',
        why=(
            "the Resource Finder would report that no material exists when it could "
            "not look, and the route gets planned on a confident nothing"
        ),
    ),
    Mutation(
        rail="a missing fixture raises instead of reading as empty",
        test="test_fixture_transport_fails_loudly_on_an_unrecorded_call",
        find='            raise FixtureMissing(\n                f"no recorded response for {verb} {path}. "\n                f"recorded: {sorted(self._responses)}"\n            )',
        replace='            recorded = {}\n        else:',
        why="an empty fixture response makes every downstream test pass while proving nothing",
    ),
)


def run(test: str = "", suite: str = SUITES) -> tuple[bool, str]:
    """Run one test, or a whole suite when ``test`` is empty.

    Returns (passed, last line of output).
    """
    target = f"{suite}::{test}" if test else suite
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", target, "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    tail = [line for line in completed.stdout.splitlines() if line.strip()]
    return completed.returncode == 0, tail[-1] if tail else "(no output)"


def _arm_restore(originals: dict[str, bytes]) -> None:
    """Put the file back even if this process is interrupted.

    ``finally`` does not run when the process is killed, and the mutation being
    held at that moment may be a **widened allowlist**. That is the worst thing to
    leave on disk, so the restore is registered with ``atexit`` and with the
    signals a terminal actually sends, not only with a ``try/finally``.

    Belt and braces: ``test_no_mutation_sentinel_is_left_in_the_source`` fails the
    ordinary suite if a mutation survives anyway. This happened once, which is why
    both exist.
    """

    def dirty() -> list[str]:
        return [
            relative
            for relative in originals
            if b"MUTATION" in (ROOT / relative).read_bytes()
        ]

    def restore(*_: object) -> None:
        for relative in dirty():
            (ROOT / relative).write_bytes(originals[relative])
            print(f"\n[restored] a mutation was still in {relative}; it has been put back")
        sys.exit(1)

    atexit.register(lambda: restore() if dirty() else None)
    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        if (sig := getattr(signal, name, None)) is not None:
            try:
                signal.signal(sig, restore)
            except (ValueError, OSError):  # not available on this platform/thread
                pass


def main() -> int:
    targets = sorted({mutation.target for mutation in MUTATIONS})
    # Bytes, not text. This script edits source files in place, and a text
    # read/write round-trip rewrites every line ending on Windows -- turning a
    # one-line mutation into a whole-file diff in the reviewer's face.
    # Path.read_text has no newline= argument before Python 3.13.
    originals = {relative: (ROOT / relative).read_bytes() for relative in targets}
    for relative, source in originals.items():
        assert b"MUTATION" not in source, (
            f"{relative} already contains a mutation -- an earlier run of this script "
            "was interrupted. Inspect `git diff` and restore before proving anything."
        )
    _arm_restore(originals)
    failures: list[str] = []

    print(f"Proving {len(MUTATIONS)} rails across {len(targets)} file(s)\n")

    baseline_ok, baseline = run()
    print(f"  baseline suite: {baseline}")
    if not baseline_ok:
        print("\nThe suite is not green to begin with. Fix that before trusting anything below.")
        return 1

    for mutation in MUTATIONS:
        path = ROOT / mutation.target
        source = originals[mutation.target]
        # The mutation literals are written with LF; the files on disk are CRLF on
        # Windows. Translate to whatever the file actually uses, or every
        # multi-line mutation silently fails to apply and gets reported as the
        # code having "moved" -- which is a stale-harness warning for a harness
        # that is fine.
        eol = b"\r\n" if b"\r\n" in source else b"\n"
        find = mutation.find.encode("utf-8").replace(b"\n", eol)
        if find not in source:
            failures.append(f"{mutation.rail}: the mutation no longer applies -- the code moved")
            print(f"  [STALE] {mutation.rail}\n          not found in {mutation.target}; update this script")
            continue

        try:
            mutated = source.replace(
                find, mutation.replace.encode("utf-8").replace(b"\n", eol), 1
            )
            path.write_bytes(mutated)
            went_red, line = run(mutation.test, mutation.suite)
        finally:
            path.write_bytes(source)

        if went_red:
            failures.append(f"{mutation.rail}: {mutation.test} still PASSED with the guard broken")
            print(f"  [NOT A GUARD] {mutation.rail}")
            print(f"                {mutation.test} passed anyway: {line}")
        else:
            print(f"  [RED then GREEN] {mutation.rail}")
            print(f"                   {mutation.test} -- {mutation.why}")

    restored_ok, restored = run("")
    print(f"\n  restored suite: {restored}")
    if not restored_ok:
        failures.append("the file was not restored cleanly")

    if failures:
        print("\nFAILED:")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print(f"\nAll {len(MUTATIONS)} rails watched failing and then passing. Nothing here is decoration.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
