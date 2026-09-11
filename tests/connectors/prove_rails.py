"""Watch every safety rail fail, then pass. Run it; do not take my word for it.

    uv run python tests/connectors/prove_rails.py

A green suite is not evidence. A test can pass while proving nothing -- by
mocking the primitive that would have failed, by hand-building an object the
framework never constructs, or by asserting at a line the input cannot reach.
The only way to know a guard works is to break it and watch the test notice.

This script does that mechanically: for each rail it edits
``src/second/tools/_google.py``, runs the one test that should now fail, checks
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
TARGET = ROOT / "src" / "second" / "tools" / "_google.py"
SUITE = "tests/connectors/test_rails.py"


@dataclass(frozen=True)
class Mutation:
    """One way to break a rail, and the test that must notice."""

    rail: str
    test: str
    find: str
    replace: str
    why: str


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
    Mutation(
        rail="a missing fixture raises instead of reading as empty",
        test="test_fixture_transport_fails_loudly_on_an_unrecorded_call",
        find='            raise FixtureMissing(\n                f"no recorded response for {verb} {path}. "\n                f"recorded: {sorted(self._responses)}"\n            )',
        replace='            recorded = {}\n        else:',
        why="an empty fixture response makes every downstream test pass while proving nothing",
    ),
)


def run(test: str = "") -> tuple[bool, str]:
    """Run one test, or the whole suite when ``test`` is empty.

    Returns (passed, last line of output).
    """
    target = f"{SUITE}::{test}" if test else SUITE
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", target, "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    tail = [line for line in completed.stdout.splitlines() if line.strip()]
    return completed.returncode == 0, tail[-1] if tail else "(no output)"


def _arm_restore(original: str) -> None:
    """Put the file back even if this process is interrupted.

    ``finally`` does not run when the process is killed, and the mutation being
    held at that moment may be a **widened allowlist**. That is the worst thing to
    leave on disk, so the restore is registered with ``atexit`` and with the
    signals a terminal actually sends, not only with a ``try/finally``.

    Belt and braces: ``test_no_mutation_sentinel_is_left_in_the_source`` fails the
    ordinary suite if a mutation survives anyway. This happened once, which is why
    both exist.
    """

    def restore(*_: object) -> None:
        if "MUTATION" in TARGET.read_text(encoding="utf-8"):
            TARGET.write_text(original, encoding="utf-8")
            print("\n[restored] a mutation was still in place; the guard has been put back")
        sys.exit(1)

    atexit.register(lambda: None if "MUTATION" not in TARGET.read_text(encoding="utf-8") else restore())
    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        if (sig := getattr(signal, name, None)) is not None:
            try:
                signal.signal(sig, restore)
            except (ValueError, OSError):  # not available on this platform/thread
                pass


def main() -> int:
    original = TARGET.read_text(encoding="utf-8")
    assert "MUTATION" not in original, (
        "the guard already contains a mutation -- an earlier run of this script was "
        "interrupted. Inspect `git diff` and restore before proving anything."
    )
    _arm_restore(original)
    failures: list[str] = []

    print(f"Proving {len(MUTATIONS)} rails in {TARGET.relative_to(ROOT)}\n")

    baseline_ok, baseline = run("")
    print(f"  baseline suite: {baseline}")
    if not baseline_ok:
        print("\nThe suite is not green to begin with. Fix that before trusting anything below.")
        return 1

    for mutation in MUTATIONS:
        if mutation.find not in original:
            failures.append(f"{mutation.rail}: the mutation no longer applies -- the code moved")
            print(f"  [STALE] {mutation.rail}\n          mutation target not found; this script needs updating")
            continue

        try:
            TARGET.write_text(original.replace(mutation.find, mutation.replace, 1), encoding="utf-8")
            went_red, line = run(mutation.test)
        finally:
            TARGET.write_text(original, encoding="utf-8")

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
